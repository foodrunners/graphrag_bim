"""Export GraphRAG Parquet tables and the IFC+SG bridge to Obsidian Markdown notes with wikilinks."""

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
import shutil

import pandas as pd

from ifcsg_bridge import load_bridge

ROOT = Path(__file__).resolve().parents[1]
GRAPHRAG_DIR = ROOT / "03_graphrag"
OBSIDIAN_ROOT = GRAPHRAG_DIR / "obsidian_graph"

INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\[\]#^]+')


def safe_note_name(prefix, raw_title, used_names):
    cleaned = INVALID_FILENAME_CHARS.sub(" ", str(raw_title)).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).rstrip(". ")
    if not cleaned:
        cleaned = "UNTITLED"
    if len(cleaned) > 90:
        cleaned = cleaned[:90].rstrip(". ")
    base = f"{prefix} - {cleaned}"
    candidate = base
    suffix = 2
    while candidate.casefold() in used_names:
        candidate = f"{base} ({suffix})"
        suffix += 1
    used_names.add(candidate.casefold())
    return candidate


def tag_for_type(entity_type):
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", str(entity_type or "ENTITY").strip()).strip("_").upper()
    return f"#{cleaned or 'ENTITY'}"


def yaml_escape(text):
    return json.dumps(str(text), ensure_ascii=False)


def export_graphrag_scope(scope, prefix, filter_term=None, min_degree=0, folder_name=None):
    output_dir = GRAPHRAG_DIR / scope / "output"
    entities_file = output_dir / "entities.parquet"
    rels_file = output_dir / "relationships.parquet"
    if not entities_file.is_file() or not rels_file.is_file():
        raise FileNotFoundError(f"Missing GraphRAG output for {scope!r}. Run graphrag index --root 03_graphrag/{scope} first.")

    entities = pd.read_parquet(entities_file)
    rels = pd.read_parquet(rels_file)

    if filter_term:
        term = filter_term.casefold()
        seed_mask = (
            entities["title"].astype(str).str.casefold().str.contains(term, regex=False)
            | entities["description"].astype(str).str.casefold().str.contains(term, regex=False)
        )
        seed_titles = set(entities.loc[seed_mask, "title"].astype(str))
        neighbor_rels = rels[rels["source"].isin(seed_titles) | rels["target"].isin(seed_titles)]
        keep_titles = seed_titles | set(neighbor_rels["source"]) | set(neighbor_rels["target"])
        entities = entities[entities["title"].isin(keep_titles)]
        rels = rels[rels["source"].isin(keep_titles) & rels["target"].isin(keep_titles)]

    if min_degree > 0:
        entities = entities[entities["degree"] >= min_degree]
        keep_titles = set(entities["title"].astype(str))
        rels = rels[rels["source"].isin(keep_titles) & rels["target"].isin(keep_titles)]

    base_folder = folder_name or scope
    dest = OBSIDIAN_ROOT / (f"{base_folder}_{re.sub(r'[^a-zA-Z0-9]+', '_', filter_term).strip('_')}" if filter_term else base_folder)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)

    used_names = set()
    title_to_note = {}
    for row in entities.itertuples(index=False):
        title_to_note[str(row.title)] = safe_note_name(prefix, row.title, used_names)

    outgoing = defaultdict(list)
    incoming = defaultdict(list)
    for row in rels.itertuples(index=False):
        src = str(row.source)
        tgt = str(row.target)
        if src in title_to_note and tgt in title_to_note:
            outgoing[src].append((tgt, str(row.description or ""), float(row.weight or 1.0)))
            incoming[tgt].append((src, str(row.description or ""), float(row.weight or 1.0)))

    for row in entities.itertuples(index=False):
        title = str(row.title)
        note_name = title_to_note[title]
        etype = str(row.type or "ENTITY")
        tag = tag_for_type(etype)
        lines = [
            "---",
            f"title: {yaml_escape(title)}",
            f"scope: {yaml_escape(scope)}",
            f"entity_type: {yaml_escape(etype)}",
            f"degree: {int(row.degree)}",
            f"frequency: {int(row.frequency)}",
            f"tags: [{tag.lstrip('#')}, GRAPHRAG_{scope.upper()}]",
            "---",
            "",
            f"# {title}",
            "",
            f"{tag} `#GRAPHRAG_{scope.upper()}`",
            "",
            str(row.description or "").strip(),
            "",
        ]
        if outgoing[title]:
            lines.append("## Outgoing relationships")
            lines.append("")
            for tgt, desc, weight in sorted(outgoing[title], key=lambda item: (-item[2], item[0])):
                lines.append(f"- → [[{title_to_note[tgt]}|{tgt}]] — {desc}")
            lines.append("")
        if incoming[title]:
            lines.append("## Incoming relationships")
            lines.append("")
            for src, desc, weight in sorted(incoming[title], key=lambda item: (-item[2], item[0])):
                lines.append(f"- ← [[{title_to_note[src]}|{src}]] — {desc}")
            lines.append("")
        (dest / f"{note_name}.md").write_text("\n".join(lines), encoding="utf-8")

    index_lines = [
        f"# Obsidian Graph Export — {scope}" + (f" (filter: {filter_term})" if filter_term else ""),
        "",
        f"- **Nodes exported:** {len(entities)}",
        f"- **Relationships linked:** {sum(len(v) for v in outgoing.values())}",
        f"- **Obsidian Graph View filter:** `path:03_graphrag/obsidian_graph/{dest.name}`",
        "",
        "## Top hub nodes",
        "",
    ]
    for row in entities.sort_values("degree", ascending=False).head(20).itertuples(index=False):
        title = str(row.title)
        index_lines.append(f"- [[{title_to_note[title]}|{title}]] (`{row.type}`, degree {int(row.degree)})")
    (dest / "_INDEX.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")

    return dest, len(entities), sum(len(v) for v in outgoing.values()), title_to_note


def export_ifcsg_bridge(full_title_map=None, multicode_title_map=None):
    bridge = load_bridge()
    dest = OBSIDIAN_ROOT / "ifcsg"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)

    full_title_map = full_title_map or {}
    multicode_title_map = multicode_title_map or {}
    used_names = set()
    entity_note = {}
    check_note = {}

    for ent in bridge["ifc_entities"]:
        entity_note[ent["id"]] = safe_note_name("IFCSG", ent["ifc_class"], used_names)
    for chk in bridge["checks"]:
        check_note[chk["check_id"]] = safe_note_name("CHK", f"{chk['check_id']} {chk['code_ref']}", used_names)

    for ent in bridge["ifc_entities"]:
        name = entity_note[ent["id"]]
        linked_checks = [c for c in bridge["checks"] if c["ifc_entity_id"] == ent["id"]]
        lines = [
            "---",
            f"title: {yaml_escape(ent['ifc_class'])}",
            f"predefined_type: {yaml_escape(ent['predefined_type'])}",
            f"spatial_container: {yaml_escape(ent['spatial_container'])}",
            "tags: [IFCSG_ENTITY, STEP2_BRIDGE]",
            "---",
            "",
            f"# {ent['ifc_class']} — {ent['label']}",
            "",
            "#IFCSG_ENTITY #STEP2_BRIDGE",
            "",
            f"- **PredefinedType:** `{ent['predefined_type']}`",
            f"- **Spatial Container:** `{ent['spatial_container']}`",
            "",
            "## Property Sets",
            "",
        ]
        for ps in ent.get("property_sets", []):
            lines.append(f"- **`{ps['pset']}`** (`{ps['schema_status']}`): {', '.join(ps['properties'])} — {ps['purpose']}")

        lines.extend(["", "## Linked GraphRAG Regulatory Hub Nodes", ""])
        for hub in ent.get("graphrag_full_entities", []):
            if hub in full_title_map:
                lines.append(f"- [[{full_title_map[hub]}|{hub}]] (BCA 116-page index)")
            else:
                lines.append(f"- `{hub}`")

        lines.extend(["", "## Linked Compliance Checks", ""])
        for chk in linked_checks:
            lines.append(f"- [[{check_note[chk['check_id']]}|{chk['check_id']}: {chk['title']}]] (`{chk['evaluation_method']}`)")

        (dest / f"{name}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    for chk in bridge["checks"]:
        name = check_note[chk["check_id"]]
        ent_id = chk["ifc_entity_id"]
        lines = [
            "---",
            f"check_id: {yaml_escape(chk['check_id'])}",
            f"topic: {yaml_escape(chk['topic'])}",
            f"authority: {yaml_escape(chk['authority'])}",
            f"code_ref: {yaml_escape(chk['code_ref'])}",
            f"evaluation_method: {yaml_escape(chk['evaluation_method'])}",
            "tags: [IFCSG_CHECK, STEP2_BRIDGE]",
            "---",
            "",
            f"# {chk['check_id']} — {chk['title']}",
            "",
            "#IFCSG_CHECK #STEP2_BRIDGE",
            "",
            f"- **Authority & Clause:** {chk['authority']} `{chk['code_ref']}`"
            + (f" (PDF p. {chk['pdf_page']})" if chk.get("pdf_page") else ""),
            f"- **Applies when:** {chk['applies_when']}",
            f"- **IFC+SG Entity:** [[{entity_note[ent_id]}|{ent_id}]]",
            f"- **Evaluation method:** `{chk['evaluation_method']}`",
            f"- **Measurement basis:** {chk['measurement_basis']}",
            f"- **Threshold ({chk['unit']}):** `{json.dumps(chk['threshold'], ensure_ascii=False)}`",
            f"- **Open evidence fallback:** {chk['open_evidence_if_unmodeled']}",
            "",
        ]
        # Link matching clause nodes in multicode if present
        matched_mc = [
            (t, n) for t, n in multicode_title_map.items()
            if any(part.strip().casefold() in t.casefold() for part in chk["code_ref"].split("/"))
        ]
        if matched_mc:
            lines.append("## Linked Multicode Graph Nodes")
            lines.append("")
            for title, note in matched_mc:
                lines.append(f"- [[{note}|{title}]]")
            lines.append("")
        (dest / f"{name}.md").write_text("\n".join(lines), encoding="utf-8")

    idx = [
        "# Obsidian Graph Export — IFC+SG Semantic Bridge",
        "",
        f"- **IFC+SG Entities:** {len(entity_note)}",
        f"- **Compliance Checks:** {len(check_note)}",
        "- **Obsidian Graph View filter (IFC+SG + Multicode):** `path:03_graphrag/obsidian_graph/ifcsg OR path:03_graphrag/obsidian_graph/multicode`",
        "- **Obsidian Graph View filter (IFC+SG + Full Washroom Slice):** `path:03_graphrag/obsidian_graph/ifcsg OR path:03_graphrag/obsidian_graph/full_washroom`",
        "",
        "## IFC+SG Entities",
        "",
    ]
    for eid, note in entity_note.items():
        idx.append(f"- [[{note}|{eid}]]")
    (dest / "_INDEX.md").write_text("\n".join(idx) + "\n", encoding="utf-8")
    return dest, len(entity_note) + len(check_note)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scope",
        choices=["multicode", "full", "ifcsg", "ifcsg_graph", "all"],
        default="all",
        help="Which graph(s) to export to 03_graphrag/obsidian_graph/.",
    )
    parser.add_argument("--filter", help="Optional keyword filter when exporting a focused slice of 'full' or 'ifcsg_graph'.")
    parser.add_argument("--min-degree", type=int, default=0, help="Only export nodes with degree >= N.")
    args = parser.parse_args()

    mc_map = {}
    full_map = {}

    if args.scope in {"multicode", "all"}:
        dest, n, e, mc_map = export_graphrag_scope("multicode", "MC", min_degree=args.min_degree)
        print(f"Exported multicode -> {dest} ({n} notes, {e} links)")

    if args.scope in {"full", "all"}:
        if args.filter:
            dest, n, e, full_map = export_graphrag_scope("full", "BCA", filter_term=args.filter, min_degree=args.min_degree)
            print(f"Exported full ({args.filter}) -> {dest} ({n} notes, {e} links)")
        else:
            dest, n, e, full_map = export_graphrag_scope("full", "BCA", min_degree=args.min_degree)
            print(f"Exported full -> {dest} ({n} notes, {e} links)")

    if args.scope in {"ifcsg_graph", "all"} and (GRAPHRAG_DIR / "ifcsg" / "output" / "entities.parquet").is_file():
        if args.filter:
            dest, n, e, _ = export_graphrag_scope("ifcsg", "IFCSG-G", filter_term=args.filter, min_degree=args.min_degree, folder_name="ifcsg_full")
            print(f"Exported ifcsg_graph ({args.filter}) -> {dest} ({n} notes, {e} links)")
        else:
            dest, n, e, _ = export_graphrag_scope("ifcsg", "IFCSG-G", min_degree=args.min_degree, folder_name="ifcsg_full")
            print(f"Exported ifcsg_graph -> {dest} ({n} notes, {e} links)")

    if args.scope in {"ifcsg", "all"}:
        dest, n = export_ifcsg_bridge(full_title_map=full_map, multicode_title_map=mc_map)
        print(f"Exported ifcsg bridge -> {dest} ({n} notes)")


if __name__ == "__main__":
    main()
