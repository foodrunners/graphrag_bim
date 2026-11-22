"""Validate and query the IFC+SG semantic bridge against GraphRAG and optional IFC models."""

import argparse
import json
from pathlib import Path
import sys

from multicode import read_graph

ROOT = Path(__file__).resolve().parents[1]
BRIDGE_PATH = ROOT / "05_ifcsg" / "bridge.json"
FULL_ENTITIES = ROOT / "03_graphrag" / "full" / "output" / "entities.parquet"
SCDF_ENTITIES = ROOT / "03_graphrag" / "scdf" / "output" / "entities.parquet"


def load_bridge(path=BRIDGE_PATH):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_bridge(bridge=None, check_full_graph=True):
    bridge = bridge or load_bridge()
    records, labels, topics, _ = read_graph()
    sources = {s["source_id"] for s in json.loads((ROOT / "01_source/sources.json").read_text(encoding="utf-8"))}

    entity_ids = {}
    errors = []
    warnings = []

    for ent in bridge.get("ifc_entities", []):
        eid = ent["id"]
        if eid in entity_ids:
            errors.append(f"Duplicate IFC entity id: {eid}")
        entity_ids[eid] = ent
        for concept in ent.get("multicode_concepts", []):
            if concept not in labels:
                errors.append(f"{eid}: unknown multicode concept {concept!r}")

    allowed_methods = {"property_lookup", "geometry_clearance", "submittal_or_drawing"}
    allowed_topics = set(topics) | {"fire_safety"}
    check_ids = set()
    for chk in bridge.get("checks", []):
        cid = chk["check_id"]
        if cid in check_ids:
            errors.append(f"Duplicate check_id: {cid}")
        check_ids.add(cid)
        if chk["topic"] not in allowed_topics:
            errors.append(f"{cid}: unknown topic {chk['topic']!r} (expected one of {sorted(allowed_topics)})")
        if chk["source_id"] not in sources:
            errors.append(f"{cid}: unknown source_id {chk['source_id']!r}")
        if chk["ifc_entity_id"] not in entity_ids:
            errors.append(f"{cid}: unknown ifc_entity_id {chk['ifc_entity_id']!r}")
        if chk["evaluation_method"] not in allowed_methods:
            errors.append(f"{cid}: invalid evaluation_method {chk['evaluation_method']!r}")

    matched_full = 0
    total_full_refs = 0
    matched_scdf = 0
    total_scdf_refs = 0
    if check_full_graph and FULL_ENTITIES.is_file():
        import pandas as pd

        full_titles = set(pd.read_parquet(FULL_ENTITIES, columns=["title"])["title"].astype(str))
        for ent in bridge.get("ifc_entities", []):
            for title in ent.get("graphrag_full_entities", []):
                total_full_refs += 1
                if title in full_titles:
                    matched_full += 1
                else:
                    warnings.append(f"{ent['id']}: GraphRAG BCA entity not found verbatim: {title!r}")

        if SCDF_ENTITIES.is_file():
            scdf_titles = set(pd.read_parquet(SCDF_ENTITIES, columns=["title"])["title"].astype(str))
            for ent in bridge.get("ifc_entities", []):
                for title in ent.get("graphrag_scdf_entities", []):
                    total_scdf_refs += 1
                    if title in scdf_titles:
                        matched_scdf += 1
                    else:
                        warnings.append(f"{ent['id']}: GraphRAG SCDF entity not found verbatim: {title!r}")

    return {
        "ok": not errors,
        "entities": len(entity_ids),
        "checks": len(check_ids),
        "full_graph_matched": matched_full,
        "full_graph_refs": total_full_refs,
        "scdf_graph_matched": matched_scdf,
        "scdf_graph_refs": total_scdf_refs,
        "errors": errors,
        "warnings": warnings,
    }


def format_checklist(topic, bridge=None):
    bridge = bridge or load_bridge()
    entities = {e["id"]: e for e in bridge["ifc_entities"]}
    selected = [c for c in bridge["checks"] if c["topic"] == topic]
    if not selected:
        available = sorted({c["topic"] for c in bridge["checks"]})
        raise ValueError(f"Unknown topic {topic!r}. Choose from: {', '.join(available)}")

    lines = [f"# IFC+SG BIM Compliance Checklist — {topic}", ""]
    for chk in selected:
        ent = entities[chk["ifc_entity_id"]]
        psets = ", ".join(
            f"{p['pset']} ({p['schema_status']})" for p in ent.get("property_sets", [])
        )
        page_note = f"PDF p. {chk['pdf_page']}" if chk.get("pdf_page") else "HTML clause"
        lines.extend([
            f"## {chk['check_id']} — {chk['title']}",
            f"- **Authority & Clause:** {chk['authority']} `{chk['code_ref']}` ({page_note})",
            f"- **Applies when:** {chk['applies_when']}",
            f"- **IFC+SG Entity:** `{ent['ifc_class']}` (`PredefinedType`: `{ent['predefined_type']}`)",
            f"- **Property Sets:** {psets}",
            f"- **Evaluation Method:** `{chk['evaluation_method']}`",
            f"- **Measurement Basis:** {chk['measurement_basis']}",
            f"- **Threshold ({chk['unit']}):** `{json.dumps(chk['threshold'], ensure_ascii=False)}`",
            f"- **If unmodeled / open evidence:** {chk['open_evidence_if_unmodeled']}",
            "",
        ])
    return "\n".join(lines)


def format_entity_view(ifc_class, bridge=None):
    bridge = bridge or load_bridge()
    matches = [e for e in bridge["ifc_entities"] if e["ifc_class"].casefold() == ifc_class.casefold()]
    if not matches:
        available = ", ".join(e["ifc_class"] for e in bridge["ifc_entities"])
        raise ValueError(f"No bridge entry for {ifc_class!r}. Available: {available}")
    ent = matches[0]
    checks = [c for c in bridge["checks"] if c["ifc_entity_id"] == ent["id"]]
    lines = [
        f"# {ent['ifc_class']} — {ent['label']}",
        f"- **PredefinedType:** `{ent['predefined_type']}` | **Container:** `{ent['spatial_container']}`",
        f"- **Multi-code concepts:** {', '.join(ent['multicode_concepts'])}",
        f"- **GraphRAG full hub entities:** {', '.join(ent['graphrag_full_entities'])}",
        "",
        "## Property Sets",
    ]
    for ps in ent.get("property_sets", []):
        props = ", ".join(ps["properties"])
        lines.append(f"- `{ps['pset']}` [`{ps['schema_status']}`]: {props} — {ps['purpose']}")
    lines.extend(["", "## Linked Regulatory Checks"])
    for chk in checks:
        lines.append(f"- **{chk['check_id']}** ({chk['authority']} `{chk['code_ref']}`, `{chk['evaluation_method']}`): {chk['title']}")
    return "\n".join(lines)


def inspect_ifc(ifc_path, topic=None):
    try:
        import ifcopenshell
        from ifcopenshell.util import element as ifc_element
    except ImportError as error:
        raise RuntimeError(
            "ifcopenshell is not installed yet. Install it inside your venv with:\n"
            "  python -m pip install ifcopenshell"
        ) from error

    bridge = load_bridge()
    model = ifcopenshell.open(str(ifc_path))
    target_entities = bridge["ifc_entities"]
    if topic:
        topic_eids = {c["ifc_entity_id"] for c in bridge["checks"] if c["topic"] == topic}
        target_entities = [e for e in target_entities if e["id"] in topic_eids]

    report = {
        "file": str(ifc_path),
        "schema": model.schema,
        "topic": topic or "all",
        "entities": {},
    }
    for ent in target_entities:
        cls = ent["ifc_class"]
        instances = model.by_type(cls)
        rows = []
        for obj in instances:
            psets = ifc_element.get_psets(obj)
            sg_psets = {k: v for k, v in psets.items() if k.startswith(("SGPset_", "Pset_", "Qto_"))}
            rows.append({
                "global_id": getattr(obj, "GlobalId", None),
                "name": getattr(obj, "Name", None),
                "long_name": getattr(obj, "LongName", None),
                "predefined_type": getattr(obj, "PredefinedType", None),
                "psets": sg_psets,
            })
        report["entities"][cls] = {"count": len(rows), "sample": rows[:20]}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("validate", help="Validate 05_ifcsg/bridge.json against multicode and full GraphRAG.")

    p_chk = sub.add_parser("checklist", help="Print a BIM compliance checklist for a topic.")
    p_chk.add_argument("topic", help="Topic name, e.g. washroom or ramp.")

    p_ent = sub.add_parser("entity", help="Show regulatory checks linked to an IFC entity class.")
    p_ent.add_argument("ifc_class", help="IFC class name, e.g. IfcSpace, IfcRamp, IfcAlarm.")

    p_ifc = sub.add_parser("inspect-ifc", help="Extract IFC+SG entities and Psets from a local .ifc file.")
    p_ifc.add_argument("ifc_file", type=Path)
    p_ifc.add_argument("--topic", help="Optional topic filter (washroom, ramp).")

    args = parser.parse_args()
    try:
        if args.command == "validate":
            result = validate_bridge()
            status = "pass" if result["ok"] else "fail"
            summary = (
                f"{status}\n\n"
                f"IFC+SG bridge: {result['entities']} IFC entities, {result['checks']} regulatory checks.\n"
                f"GraphRAG BCA full-code hub matches: {result['full_graph_matched']} / {result['full_graph_refs']}.\n"
                f"GraphRAG SCDF 540-page hub matches: {result['scdf_graph_matched']} / {result['scdf_graph_refs']}.\n"
            )
            if result["warnings"]:
                summary += "\nWarnings:\n" + "\n".join(f"- {w}" for w in result["warnings"]) + "\n"
            if result["errors"]:
                summary += "\nErrors:\n" + "\n".join(f"- {e}" for e in result["errors"]) + "\n"
            out = ROOT / "05_ifcsg" / "output" / "check.md"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(summary, encoding="utf-8")
            print(summary)
            if not result["ok"]:
                sys.exit(1)
        elif args.command == "checklist":
            print(format_checklist(args.topic))
        elif args.command == "entity":
            print(format_entity_view(args.ifc_class))
        elif args.command == "inspect-ifc":
            print(json.dumps(inspect_ifc(args.ifc_file, topic=args.topic), indent=2, ensure_ascii=False))
    except (ValueError, RuntimeError, FileNotFoundError) as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
