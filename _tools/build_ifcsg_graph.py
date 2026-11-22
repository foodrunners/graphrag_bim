"""Build the full CORENET X IFC+SG graph deterministically from Excel and embed with gemini-embedding-2."""

import argparse
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import uuid

import numpy as np
import openpyxl
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SOURCE_XLSX = ROOT / "01_source" / "output" / "ifcsg_industry_mapping_09_2026.xlsx"
EDITION_JSON = ROOT / "01_source" / "ifcsg_edition.json"
OUT_DIR = ROOT / "03_graphrag" / "ifcsg" / "output"
ENV_FILE = ROOT / "03_graphrag" / "ifcsg" / ".env"
FULL_LANCE = ROOT / "03_graphrag" / "full" / "output" / "lancedb"
FULL_ENTITIES = ROOT / "03_graphrag" / "full" / "output" / "entities.parquet"


def _norm(val):
    if val is None:
        return ""
    return " ".join(str(val).strip().split())


def _norm_agency(val):
    text = _norm(val)
    upper = text.upper()
    if upper == "ALL":
        return "All"
    if upper == "NPARKS":
        return "NParks"
    return text


def _stable_id(namespace, key):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"sg-ifcsg:{namespace}:{key}"))


def load_excel_tables(xlsx_path=SOURCE_XLSX):
    edition = json.loads(EDITION_JSON.read_text(encoding="utf-8"))
    data = Path(xlsx_path).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != edition["sha256"]:
        raise ValueError(f"Excel SHA-256 mismatch: got {digest}, expected {edition['sha256']}")

    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)

    # 1. CX Pilot Mapping (1,112 rows)
    cx_raw = [r for r in list(wb["CX Pilot Mapping"].iter_rows(values_only=True))[1:] if any(r[:14])]
    params = []
    for r in cx_raw:
        pset = _norm(r[11])
        is_header_row = "please refer to property sets below" in pset.lower()
        params.append({
            "sn": _norm(r[0]),
            "agency": _norm_agency(r[1]),
            "component": _norm(r[2]),
            "parameter": _norm(r[3]),
            "revit": _norm(r[4]),
            "archicad": _norm(r[5]),
            "tekla": _norm(r[6]),
            "bentley": _norm(r[7]),
            "discipline": _norm(r[8]),
            "ifc_entity": _norm(r[9]),
            "ifc_subtypes": _norm(r[10]),
            "property_set": "" if is_header_row else ("" if pset.upper() == "N.A" else pset),
            "property_name": "" if is_header_row else ("" if _norm(r[12]).upper() == "N.A" else _norm(r[12])),
            "property_type": "" if _norm(r[13]).upper() == "N.A" else _norm(r[13]),
            "property_unit": "" if len(r) <= 14 or _norm(r[14]).upper() == "N.A" else _norm(r[14]),
            "material_set": "" if len(r) <= 15 or _norm(r[15]).upper() == "N.A" else _norm(r[15]),
            "accepted_values": "" if len(r) <= 16 or _norm(r[16]).upper() == "N.A" else _norm(r[16]),
            "sample_value": "" if len(r) <= 17 or _norm(r[17]).upper() == "N.A" else _norm(r[17]),
            "is_subtype_declaration": is_header_row,
        })

    # 2. Space Values (1,405 rows)
    sv_raw = [r for r in list(wb["Space Values"].iter_rows(values_only=True))[1:] if _norm(r[0])]
    space_values = [
        {
            "property": _norm(r[0]),
            "value": _norm(r[1]),
            "development_use": _norm(r[2]) if len(r) > 2 else "",
        }
        for r in sv_raw
        if _norm(r[1])
    ]

    # 3. Industrial Activity Type Enum (157 rows)
    ind_raw = [r for r in list(wb["Industrial Activity Type Enum"].iter_rows(values_only=True))[1:] if _norm(r[0]) or _norm(r[1])]
    ind_enums = [
        {"activity": _norm(r[0]), "enum_code": _norm(r[1])}
        for r in ind_raw
    ]

    return pd.DataFrame(params), pd.DataFrame(space_values), pd.DataFrame(ind_enums)


def build_deterministic_graph(xlsx_path=SOURCE_XLSX, out_dir=OUT_DIR):
    params_df, sv_df, ind_df = load_excel_tables(xlsx_path)

    entities = {}  # title -> dict
    edges = {}     # (source, target) -> dict

    def add_entity(title, etype, description, freq=1):
        entities[title] = {
            "id": _stable_id("entity", title),
            "title": title,
            "type": etype,
            "description": description,
            "text_unit_ids": [],
            "frequency": int(freq),
            "degree": 0,
        }

    def add_edge(source, target, description, weight=1.0):
        if source == target or source not in entities or target not in entities:
            return
        key = (source, target)
        if key in edges:
            edges[key]["weight"] += float(weight)
            if description not in edges[key]["description"]:
                edges[key]["description"] += f" | {description}"
        else:
            edges[key] = {
                "id": _stable_id("rel", f"{source}->{target}"),
                "source": source,
                "target": target,
                "description": description,
                "weight": float(weight),
                "combined_degree": 0,
                "text_unit_ids": [],
            }

    # Agency nodes
    agency_names = {
        "BCA": "Singapore Building and Construction Authority (BCA)",
        "SCDF": "Singapore Civil Defence Force (SCDF)",
        "URA": "Urban Redevelopment Authority (URA)",
        "PUB": "PUB, Singapore's National Water Agency",
        "NEA": "National Environment Agency (NEA)",
        "LTA": "Land Transport Authority (LTA)",
        "NParks": "National Parks Board (NParks)",
        "All": "All CORENET X Agencies (shared parameters)",
    }
    for ag, grp in params_df.groupby("agency"):
        if not ag:
            continue
        comps = sorted(grp["component"].unique())
        add_entity(
            f"AGENCY: {ag}",
            "AGENCY",
            f"{agency_names.get(ag, ag)}. Governs {len(grp)} IFC+SG parameter rows across {len(comps)} components: {', '.join(comps[:20])}{'...' if len(comps) > 20 else ''}.",
            freq=len(grp),
        )

    # Discipline nodes
    for disc, grp in params_df.groupby("discipline"):
        if not disc:
            continue
        comps = sorted(grp["component"].unique())
        add_entity(
            f"DISCIPLINE: {disc}",
            "DISCIPLINE",
            f"CORENET X BIM discipline {disc}. Covers {len(grp)} parameter rows across {len(comps)} components.",
            freq=len(grp),
        )

    # IFC4 Entity nodes
    for ifc_cls, grp in params_df.groupby("ifc_entity"):
        if not ifc_cls or ifc_cls.upper() == "N.A":
            continue
        comps = sorted(grp["component"].unique())
        psets = sorted({p for p in grp["property_set"] if p})
        subtypes = sorted({
            s.strip() for raw in grp["ifc_subtypes"] if raw and raw.upper() != "N.A"
            for s in raw.split(",") if s.strip()
        })
        agencies = sorted({a for a in grp["agency"] if a})
        add_entity(
            ifc_cls,
            "IFC_ENTITY",
            (
                f"IFC4 entity {ifc_cls} in CORENET X IFC+SG. "
                f"Used by agencies: {', '.join(agencies)}. "
                f"Components ({len(comps)}): {', '.join(comps)}. "
                f"SubTypes (* = USERDEFINED): {', '.join(subtypes) if subtypes else 'None'}. "
                f"Property Sets ({len(psets)}): {', '.join(psets)}."
            ),
            freq=len(grp),
        )

    # Property Set nodes
    for pset, grp in params_df[params_df["property_set"] != ""].groupby("property_set"):
        props = sorted({
            f"{r.property_name} ({r.property_type or 'Label'})"
            for r in grp.itertuples(index=False) if r.property_name
        })
        agencies = sorted({a for a in grp["agency"] if a})
        ifc_classes = sorted({c for c in grp["ifc_entity"] if c and c.upper() != "N.A"})
        add_entity(
            pset,
            "PROPERTY_SET",
            (
                f"CORENET X IFC+SG Property Set {pset}. "
                f"Attached to IFC entities: {', '.join(ifc_classes)}. "
                f"Agencies: {', '.join(agencies)}. "
                f"Properties ({len(props)}): {', '.join(props)}."
            ),
            freq=len(grp),
        )

    # Identified Component nodes
    for comp, grp in params_df.groupby("component"):
        if not comp:
            continue
        agencies = sorted({a for a in grp["agency"] if a})
        disciplines = sorted({d for d in grp["discipline"] if d})
        ifc_classes = sorted({c for c in grp["ifc_entity"] if c and c.upper() != "N.A"})
        subtypes = sorted({
            s.strip() for raw in grp["ifc_subtypes"] if raw and raw.upper() != "N.A"
            for s in raw.split(",") if s.strip()
        })
        psets = sorted({p for p in grp["property_set"] if p})
        revit = sorted({x for x in grp["revit"] if x and x.upper() != "N.A"})
        archicad = sorted({x for x in grp["archicad"] if x and x.upper() != "N.A"})
        tekla = sorted({x for x in grp["tekla"] if x and x.upper() != "N.A"})
        bentley = sorted({x for x in grp["bentley"] if x and x.upper() != "N.A"})
        prop_specs = sorted({
            f"{r.property_set}.{r.property_name}" if r.property_set else r.property_name
            for r in grp.itertuples(index=False) if r.property_name
        })
        add_entity(
            comp,
            "COMPONENT",
            (
                f"CORENET X Identified Component: {comp}. "
                f"Agencies: {', '.join(agencies)}. Disciplines: {', '.join(disciplines)}. "
                f"IFC4 Entities: {', '.join(ifc_classes)}. "
                f"SubTypes (* = USERDEFINED): {', '.join(subtypes) if subtypes else 'None'}. "
                f"Authoring tools — Revit: {', '.join(revit) or 'N.A'}; Archicad: {', '.join(archicad) or 'N.A'}; "
                f"Tekla: {', '.join(tekla) or 'N.A'}; Bentley: {', '.join(bentley) or 'N.A'}. "
                f"Property Sets: {', '.join(psets)}. "
                f"Mapped Properties ({len(prop_specs)}): {', '.join(prop_specs)}."
            ),
            freq=len(grp),
        )

    # Vocabulary nodes (Space Values + SS593 Industrial Activity Enum)
    for prop, grp in sv_df.groupby("property"):
        vals = sorted(grp["value"].unique())
        sample = ", ".join(vals[:25]) + ("..." if len(vals) > 25 else "")
        title = f"ENUM: {prop}"
        add_entity(
            title,
            "VOCABULARY",
            f"Controlled Space Values list for {prop} ({len(vals)} allowed values). Examples: {sample}.",
            freq=len(vals),
        )
    add_entity(
        "ENUM: IndustrialActivityType (SS593)",
        "VOCABULARY",
        f"Controlled SS593 Annex A Industrial Activity Type codes ({len(ind_df)} values, e.g. SS593-AnnexA-01 through SS593-AnnexA-{len(ind_df):02d}).",
        freq=len(ind_df),
    )

    # Build deterministic relationships
    for (comp, ifc_cls), grp in params_df.groupby(["component", "ifc_entity"]):
        if not comp or not ifc_cls or ifc_cls.upper() == "N.A":
            continue
        subtypes = sorted({
            s.strip() for raw in grp["ifc_subtypes"] if raw and raw.upper() != "N.A"
            for s in raw.split(",") if s.strip()
        })
        add_edge(comp, ifc_cls, f"mapped_to_ifc (SubTypes: {', '.join(subtypes) if subtypes else 'standard'})", weight=len(grp))

    for (comp, pset), grp in params_df[params_df["property_set"] != ""].groupby(["component", "property_set"]):
        props = sorted({r for r in grp["property_name"] if r})
        add_edge(comp, pset, f"uses_pset ({', '.join(props[:12])}{'...' if len(props) > 12 else ''})", weight=len(grp))

    for (ifc_cls, pset), grp in params_df[params_df["property_set"] != ""].groupby(["ifc_entity", "property_set"]):
        if ifc_cls and ifc_cls.upper() != "N.A":
            add_edge(ifc_cls, pset, f"has_property_set ({len(grp)} parameters)", weight=len(grp))

    for (ag, comp), grp in params_df.groupby(["agency", "component"]):
        if ag and comp:
            add_edge(f"AGENCY: {ag}", comp, f"governs_component ({len(grp)} parameters)", weight=len(grp))

    for (comp, disc), grp in params_df.groupby(["component", "discipline"]):
        if comp and disc:
            add_edge(comp, f"DISCIPLINE: {disc}", f"discipline ({len(grp)} parameters)", weight=len(grp))

    # Link vocabulary enums to their property sets
    for prop in sv_df["property"].unique():
        matching_psets = sorted({
            r.property_set
            for r in params_df[params_df["property_name"] == prop].itertuples(index=False)
            if r.property_set
        })
        for pset in matching_psets:
            add_edge(pset, f"ENUM: {prop}", f"controlled_values_for ({prop})", weight=1.0)
    if "SGPset_Space" in entities:
        add_edge("SGPset_Space", "ENUM: IndustrialActivityType (SS593)", "industrial_activity_enum", weight=1.0)

    # Compute node degrees and combined edge degrees
    degree = defaultdict(int)
    for src, tgt in edges:
        degree[src] += 1
        degree[tgt] += 1
    for title, row in entities.items():
        row["degree"] = degree[title]
    for row in edges.values():
        row["combined_degree"] = degree[row["source"]] + degree[row["target"]]

    ent_df = pd.DataFrame(list(entities.values())).sort_values(["type", "degree", "title"], ascending=[True, False, True]).reset_index(drop=True)
    ent_df.insert(1, "human_readable_id", range(len(ent_df)))

    rel_df = pd.DataFrame(list(edges.values())).sort_values(["weight", "source", "target"], ascending=[False, True, True]).reset_index(drop=True)
    rel_df.insert(1, "human_readable_id", range(len(rel_df)))

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ent_df.to_parquet(out_dir / "entities.parquet", index=False)
    rel_df.to_parquet(out_dir / "relationships.parquet", index=False)
    params_df.to_parquet(out_dir / "parameters.parquet", index=False)
    sv_df.to_parquet(out_dir / "space_values.parquet", index=False)
    ind_df.to_parquet(out_dir / "industrial_enums.parquet", index=False)

    return ent_df, rel_df, params_df, sv_df, ind_df


def _load_gemini_key():
    if os.environ.get("GEMINI_API_KEY"):
        return os.environ["GEMINI_API_KEY"]
    for candidate in (ENV_FILE, ROOT / "03_graphrag" / "full" / ".env", ROOT / "03_graphrag" / "multicode" / ".env"):
        if candidate.is_file():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("GEMINI_API_KEY="):
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if val and not val.startswith("<"):
                        return val
    raise RuntimeError("No GEMINI_API_KEY found in environment or 03_graphrag/*/.env.")


def embed_entities(out_dir=OUT_DIR, model="gemini/gemini-embedding-2", batch_size=50):
    import lancedb
    import litellm

    api_key = _load_gemini_key()
    ent_df = pd.read_parquet(Path(out_dir) / "entities.parquet")
    texts = [f"{r.title} ({r.type}): {r.description}" for r in ent_df.itertuples(index=False)]

    vectors = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start:start + batch_size]
        resp = litellm.embedding(model=model, input=batch, api_key=api_key)
        for item in resp["data"]:
            vec = np.asarray(item["embedding"], dtype=np.float32)
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            vectors.append(vec.tolist())

    lance_rows = [
        {
            "id": str(r.id),
            "text": texts[i],
            "vector": vectors[i],
            "attributes": json.dumps({"title": str(r.title), "type": str(r.type)}),
        }
        for i, r in enumerate(ent_df.itertuples(index=False))
    ]

    db = lancedb.connect(str(Path(out_dir) / "lancedb"))
    db.create_table("entity_description", data=lance_rows, mode="overwrite")
    return len(lance_rows), len(vectors[0])


def semantic_search(query, top_k=10, out_dir=OUT_DIR, model="gemini/gemini-embedding-2"):
    import lancedb
    import litellm

    api_key = _load_gemini_key()
    resp = litellm.embedding(model=model, input=[query], api_key=api_key)
    qvec = np.asarray(resp["data"][0]["embedding"], dtype=np.float32)
    qvec = qvec / np.linalg.norm(qvec)

    db = lancedb.connect(str(Path(out_dir) / "lancedb"))
    df = db.open_table("entity_description").to_pandas()
    mat = np.stack(df["vector"].values)
    scores = mat @ qvec
    top_idx = np.argsort(scores)[::-1][:top_k]

    results = []
    for idx in top_idx:
        attrs = json.loads(df.iloc[idx]["attributes"])
        results.append({
            "score": round(float(scores[idx]), 4),
            "type": attrs["type"],
            "title": attrs["title"],
            "text": df.iloc[idx]["text"],
        })
    return results


def cross_match_bca_to_ifcsg(top_k=3, min_score=0.62):
    """Match all BCA 116-page Space / Building Element / Component / System nodes to CORENET X IFC+SG via cosine similarity."""
    import lancedb

    if not FULL_ENTITIES.is_file() or not FULL_LANCE.is_dir():
        raise FileNotFoundError("Full BCA GraphRAG index not found at 03_graphrag/full/output.")

    bca_ent = pd.read_parquet(FULL_ENTITIES)
    target_types = {"SPACE", "BUILDING ELEMENT", "COMPONENT", "SYSTEM"}
    bca_sub = bca_ent[bca_ent["type"].isin(target_types)].copy()

    bca_db = lancedb.connect(str(FULL_LANCE))
    bca_vec_df = bca_db.open_table("entity_description").to_pandas()
    bca_merged = bca_sub.merge(bca_vec_df[["id", "vector"]], on="id", how="inner")

    ifc_db = lancedb.connect(str(OUT_DIR / "lancedb"))
    ifc_vec_df = ifc_db.open_table("entity_description").to_pandas()
    ifc_attrs = [json.loads(a) for a in ifc_vec_df["attributes"]]
    ifc_vec_df["title"] = [a["title"] for a in ifc_attrs]
    ifc_vec_df["type"] = [a["type"] for a in ifc_attrs]
    ifc_targets = ifc_vec_df[ifc_vec_df["type"].isin({"COMPONENT", "IFC_ENTITY", "PROPERTY_SET"})].reset_index(drop=True)

    bca_mat = np.stack(bca_merged["vector"].values).astype(np.float32)
    bca_mat /= np.clip(np.linalg.norm(bca_mat, axis=1, keepdims=True), 1e-12, None)
    ifc_mat = np.stack(ifc_targets["vector"].values).astype(np.float32)
    ifc_mat /= np.clip(np.linalg.norm(ifc_mat, axis=1, keepdims=True), 1e-12, None)

    sim = bca_mat @ ifc_mat.T

    rows = []
    for i, bca_row in enumerate(bca_merged.itertuples(index=False)):
        order = np.argsort(sim[i])[::-1][:top_k]
        for rank, j in enumerate(order, 1):
            score = float(sim[i, j])
            if score < min_score and rank > 1:
                continue
            rows.append({
                "bca_entity": bca_row.title,
                "bca_type": bca_row.type,
                "bca_degree": int(bca_row.degree),
                "rank": rank,
                "cosine_score": round(score, 4),
                "ifcsg_title": ifc_targets.iloc[j]["title"],
                "ifcsg_type": ifc_targets.iloc[j]["type"],
            })

    out_csv = ROOT / "05_ifcsg" / "output" / "bca_to_ifcsg_matches.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df_out = pd.DataFrame(rows).sort_values(["bca_degree", "bca_entity", "rank"], ascending=[False, True, True])
    df_out.to_csv(out_csv, index=False, encoding="utf-8")
    return out_csv, df_out


def offline_find(query, top_k=15, out_dir=OUT_DIR):
    """Exact/substring offline search across IFC+SG entities and 1,112 parameters (zero API calls)."""
    out_dir = Path(out_dir)
    params_df = pd.read_parquet(out_dir / "parameters.parquet")
    ent_df = pd.read_parquet(out_dir / "entities.parquet")
    terms = [t.casefold() for t in query.split() if t.strip()]

    def score_text(text):
        low = str(text).casefold()
        return sum(1 for t in terms if t in low)

    ent_scores = ent_df.apply(lambda r: score_text(f"{r['title']} {r['type']} {r['description']}"), axis=1)
    ent_hits = ent_df[ent_scores > 0].assign(match_terms=ent_scores[ent_scores > 0]).sort_values(
        ["match_terms", "degree"], ascending=[False, False]
    ).head(top_k)

    param_blob = (
        params_df["agency"] + " " + params_df["component"] + " " + params_df["parameter"] + " "
        + params_df["ifc_entity"] + " " + params_df["ifc_subtypes"] + " "
        + params_df["property_set"] + "." + params_df["property_name"]
    )
    p_scores = param_blob.map(score_text)
    param_hits = params_df[p_scores > 0].assign(match_terms=p_scores[p_scores > 0]).sort_values(
        ["match_terms", "agency", "component"], ascending=[False, True, True]
    ).head(top_k)

    return ent_hits, param_hits


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="Compile Excel into exact Parquet graph tables (offline, $0).")
    p_build.add_argument("--embed", action="store_true", help="Also embed all entities with gemini-embedding-2.")
    p_build.add_argument("--match-bca", action="store_true", help="Also cross-match BCA 116-page entities to IFC+SG.")

    p_find = sub.add_parser("find", help="Fast offline lookup across all IFC+SG entities and 1,112 parameters ($0).")
    p_find.add_argument("query")
    p_find.add_argument("--top-k", type=int, default=12)

    p_search = sub.add_parser("search", help="Semantic vector search over the full IFC+SG graph (uses gemini-embedding-2).")
    p_search.add_argument("query")
    p_search.add_argument("--top-k", type=int, default=8)

    sub.add_parser("match-bca", help="Cross-match BCA 116-page entities to IFC+SG using gemini-embedding-2 vectors.")

    args = parser.parse_args()

    if args.command == "build":
        ent_df, rel_df, params_df, sv_df, ind_df = build_deterministic_graph()
        print(
            f"Built deterministic IFC+SG graph: {len(ent_df)} entities, {len(rel_df)} relationships, "
            f"{len(params_df)} parameters, {len(sv_df)} space values, {len(ind_df)} industrial enums."
        )
        print("Entity counts:", ent_df["type"].value_counts().to_dict())
        if args.embed:
            n, dim = embed_entities()
            print(f"Embedded {n} IFC+SG entities ({dim}-dim gemini-embedding-2) -> 03_graphrag/ifcsg/output/lancedb")
        if args.match_bca:
            out_csv, df_out = cross_match_bca_to_ifcsg()
            print(f"Cross-matched BCA -> IFC+SG: {len(df_out)} links saved -> {out_csv}")
    elif args.command == "find":
        ent_hits, param_hits = offline_find(args.query, top_k=args.top_k)
        print(f"=== Matching IFC+SG Graph Nodes ({len(ent_hits)}) ===")
        for r in ent_hits.itertuples(index=False):
            print(f"[{r.match_terms} hits] ({r.type}) {r.title} (degree {r.degree})")
        print(f"\n=== Matching CORENET X Parameters ({len(param_hits)}) ===")
        for r in param_hits.itertuples(index=False):
            prop = f"{r.property_set}.{r.property_name}" if r.property_set else r.property_name
            print(f"- [{r.agency} | {r.discipline}] {r.component} -> {r.ifc_entity} ({r.ifc_subtypes}) | {r.parameter} -> `{prop}` ({r.property_type})")
    elif args.command == "search":
        hits = semantic_search(args.query, top_k=args.top_k)
        for h in hits:
            print(f"[{h['score']:.4f}] ({h['type']}) {h['title']}")
            print(f"    {h['text'][:220]}")
    elif args.command == "match-bca":
        out_csv, df_out = cross_match_bca_to_ifcsg()
        print(f"Cross-matched BCA -> IFC+SG: {len(df_out)} links saved -> {out_csv}")
        print(df_out[df_out["rank"] == 1].head(20).to_string(index=False))


if __name__ == "__main__":
    main()
