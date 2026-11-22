"""Local web UI for searching Singapore design codes (BCA COA + Multi-Code) alongside CORENET X IFC+SG BIM rules."""

import argparse
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlparse

import pandas as pd

from ifcsg_bridge import load_bridge
from multicode import read_graph
from watch_index import ascii_bar, read_index_status

ROOT = Path(__file__).resolve().parents[1]
FULL_OUT = ROOT / "03_graphrag" / "full" / "output"
SCDF_OUT = ROOT / "03_graphrag" / "scdf" / "output"
IFCSG_OUT = ROOT / "03_graphrag" / "ifcsg" / "output"
SCDF_JSONL = ROOT / "02_evidence" / "output" / "scdf" / "records.jsonl"
MATCHES_CSV = ROOT / "05_ifcsg" / "output" / "bca_to_ifcsg_matches.csv"
SCDF_MATCHES_CSV = ROOT / "05_ifcsg" / "output" / "scdf_to_ifcsg_matches.csv"
BCA_PDF_URL = "https://file.go.gov.sg/bca-coa2025.pdf"
SCDF_PDF_URL = "https://www.scdf.gov.sg/docs/default-source/firecode-whole-document-with-annotations/firecode_full_latest_07jul2026.pdf?sfvrsn=a794fc8b_0"

SYNONYMS = {
    "toilet": [
        "toilet", "water closet", "wc", "washroom", "awc", "lwc", "sanitary",
        "cubicle", "urinal", "bidet", "wash basin", "grab bar", "emergency assistance",
        "visualalarm", "largeraccessible", "watercloset",
    ],
    "washroom": [
        "washroom", "toilet", "water closet", "wc", "awc", "lwc", "sanitary",
        "wash basin", "grab bar", "emergency assistance", "visualalarm", "largeraccessible", "watercloset",
    ],
    "wc": ["wc", "water closet", "watercloset", "washroom", "toilet", "awc", "lwc", "cubicle"],
    "ramp": ["ramp", "gradient", "kerb ramp", "flaredkerbramp", "landing", "slope", "handrail", "steprampaccess"],
    "door": ["door", "doorway", "clearwidth", "clear width", "opening", "gate", "poweroperated", "fireexit", "selfclosing"],
    "lift": ["lift", "elevator", "passenger lift", "platform lift", "stairlift", "transportelement"],
    "elevator": ["lift", "elevator", "passenger lift", "platform lift", "transportelement"],
    "alarm": ["alarm", "emergency push-button", "pull-cord", "visualalarm", "sounder", "fire alarm", "assistance alarm"],
    "stair": ["stair", "staircase", "step", "handrail", "tgsi", "nosing", "railing"],
    "staircase": ["stair", "staircase", "step", "handrail", "tgsi", "nosing", "railing"],
    "parking": ["parking", "carpark", "parking lot", "alighting", "boarding"],
    "shower": ["shower", "asf", "shower seat", "sanitary"],
    "basin": ["wash basin", "washhandbasin", "basin", "tap", "mirror"],
    "railing": ["railing", "handrail", "grab bar", "guardrail", "barrier", "bollard"],
    "handrail": ["handrail", "railing", "grab bar", "guardrail", "ramp", "staircase"],
    "refuse": ["refuse", "chute", "recyclables", "food waste", "waste"],
    "drain": ["drain", "culvert", "pipe", "duct", "gutter", "grating", "interceptor", "pump"],
    "disabled": ["accessible", "barrier free", "barrierfreeaccessibility", "wheelchair", "ambulant"],
    "wheelchair": ["accessible", "wheelchair", "barrier free", "barrierfreeaccessibility", "turning", "clear floor"],
}


def expand_terms(query):
    raw = [t.strip().casefold() for t in re.split(r"[,;/\s]+", query) if len(t.strip()) >= 2]
    expanded = []
    seen = set()
    for token in raw:
        if token not in seen:
            expanded.append(token)
            seen.add(token)
        for key, syns in SYNONYMS.items():
            if token == key or token in syns[:2]:
                for s in syns:
                    if s not in seen:
                        expanded.append(s)
                        seen.add(s)
    return raw, expanded


class ComplianceStore:
    """In-memory index over BCA 116-page GraphRAG, multicode, and CORENET X IFC+SG Parquet tables."""

    def __init__(self):
        self.bca_entities = pd.read_parquet(FULL_OUT / "entities.parquet")
        self.bca_rels = pd.read_parquet(FULL_OUT / "relationships.parquet")
        self.bca_docs = pd.read_parquet(FULL_OUT / "documents.parquet")
        self.bca_units = pd.read_parquet(FULL_OUT / "text_units.parquet")

        self.ifc_entities = pd.read_parquet(IFCSG_OUT / "entities.parquet")
        self.ifc_params = pd.read_parquet(IFCSG_OUT / "parameters.parquet")
        self.ifc_space_values = pd.read_parquet(IFCSG_OUT / "space_values.parquet")

        self.bridge = load_bridge()
        self.mc_records, self.mc_labels, self.mc_topics, self.mc_links = read_graph()
        self.auto_matches = pd.read_csv(MATCHES_CSV) if MATCHES_CSV.is_file() else pd.DataFrame()
        self.scdf_matches = pd.read_csv(SCDF_MATCHES_CSV) if SCDF_MATCHES_CSV.is_file() else pd.DataFrame()
        self.scdf_pages = []
        if SCDF_JSONL.is_file():
            self.scdf_pages = [
                json.loads(line)
                for line in SCDF_JSONL.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        self.scdf_entities = pd.read_parquet(SCDF_OUT / "entities.parquet") if (SCDF_OUT / "entities.parquet").is_file() else pd.DataFrame()
        self.scdf_rels = pd.read_parquet(SCDF_OUT / "relationships.parquet") if (SCDF_OUT / "relationships.parquet").is_file() else pd.DataFrame()
        self.scdf_unit_page = {}
        self.scdf_neighbors = defaultdict(list)
        if not self.scdf_entities.empty and (SCDF_OUT / "documents.parquet").is_file():
            scdf_docs = pd.read_parquet(SCDF_OUT / "documents.parquet")
            scdf_units = pd.read_parquet(SCDF_OUT / "text_units.parquet")
            sdoc_page = {}
            for r in scdf_docs.itertuples(index=False):
                m = re.search(r"p\.\s*(\d+)", str(r.title))
                sdoc_page[str(r.id)] = int(m.group(1)) if m else None
            for r in scdf_units.itertuples(index=False):
                self.scdf_unit_page[str(r.id)] = sdoc_page.get(str(r.document_id))
            stype_map = dict(zip(self.scdf_entities["title"].astype(str), self.scdf_entities["type"].astype(str)))
            for r in self.scdf_rels.itertuples(index=False):
                src, tgt = str(r.source), str(r.target)
                self.scdf_neighbors[src].append({"title": tgt, "type": stype_map.get(tgt, "")})
                self.scdf_neighbors[tgt].append({"title": src, "type": stype_map.get(src, "")})

        # Pre-index text_unit_id -> PDF page number
        doc_page = {}
        for r in self.bca_docs.itertuples(index=False):
            m = re.search(r"p\.\s*(\d+)", str(r.title))
            doc_page[str(r.id)] = int(m.group(1)) if m else None
        self.unit_page = {}
        for r in self.bca_units.itertuples(index=False):
            self.unit_page[str(r.id)] = doc_page.get(str(r.document_id))

        # Pre-index BCA entity adjacency for instant neighbor lookup
        self.bca_neighbors = defaultdict(list)
        ent_type_map = dict(zip(self.bca_entities["title"].astype(str), self.bca_entities["type"].astype(str)))
        for r in self.bca_rels.itertuples(index=False):
            src, tgt, desc = str(r.source), str(r.target), str(r.description or "")
            self.bca_neighbors[src].append({"title": tgt, "type": ent_type_map.get(tgt, ""), "desc": desc})
            self.bca_neighbors[tgt].append({"title": src, "type": ent_type_map.get(src, ""), "desc": desc})

        self.stats = {
            "bca_pages": len(self.bca_docs),
            "bca_entities": len(self.bca_entities),
            "bca_relationships": len(self.bca_rels),
            "scdf_pages": len(self.scdf_pages),
            "scdf_entities": len(self.scdf_entities),
            "ifcsg_components": int((self.ifc_entities["type"] == "COMPONENT").sum()),
            "ifcsg_entities": int((self.ifc_entities["type"] == "IFC_ENTITY").sum()),
            "ifcsg_psets": int((self.ifc_entities["type"] == "PROPERTY_SET").sum()),
            "ifcsg_parameters": len(self.ifc_params),
            "ifcsg_space_values": len(self.ifc_space_values),
            "agencies": sorted({a for a in self.ifc_params["agency"].unique() if a}),
        }

    def _pages_for_entity(self, text_unit_ids):
        pages = sorted({
            self.unit_page[str(uid)]
            for uid in (text_unit_ids if text_unit_ids is not None else [])
            if str(uid) in self.unit_page and self.unit_page[str(uid)] is not None
        })
        return pages

    def _score_blob(self, text, raw_terms, expanded_terms):
        low = str(text).casefold()
        score = 0.0
        for t in raw_terms:
            if t in low:
                score += 3.0
        for t in expanded_terms:
            if t not in raw_terms and t in low:
                score += 1.2
        return score

    def search(self, query, agency_filter="ALL"):
        raw_terms, expanded_terms = expand_terms(query)
        if not expanded_terms:
            return {"query": query, "expanded_terms": [], "stats": self.stats}

        # 1. Verified Bridge Checks (05_ifcsg/bridge.json)
        entity_by_id = {e["id"]: e for e in self.bridge["ifc_entities"]}
        bridge_checks = []
        for chk in self.bridge["checks"]:
            ent = entity_by_id[chk["ifc_entity_id"]]
            blob = " ".join([
                chk["topic"], chk["title"], chk["code_ref"], chk["applies_when"],
                chk["measurement_basis"], ent["ifc_class"], ent["predefined_type"], ent["label"],
                " ".join(ent["graphrag_full_entities"]),
            ])
            sc = self._score_blob(blob, raw_terms, expanded_terms)
            if sc > 0:
                bridge_checks.append({
                    **chk,
                    "score": sc,
                    "ifc_class": ent["ifc_class"],
                    "predefined_type": ent["predefined_type"],
                    "pdf_url": f"{BCA_PDF_URL}#page={chk['pdf_page']}" if chk.get("pdf_page") else None,
                })
        bridge_checks.sort(key=lambda x: (-x["score"], x["check_id"]))

        # 2. Multi-code cross-agency clauses (BCA + SCDF + Approved Doc)
        multicode_hits = []
        for row in self.mc_records.values():
            blob = f"{row['title']} {row['authority']} {row['code_ref']} {row['applies_when']} {row['text']}"
            sc = self._score_blob(blob, raw_terms, expanded_terms)
            if sc > 0:
                multicode_hits.append({
                    "id": row["id"],
                    "authority": row["authority"],
                    "edition": row["edition"],
                    "code_ref": row["code_ref"],
                    "source_locator": row["source_locator"],
                    "applies_when": row["applies_when"],
                    "text": row["text"],
                    "source_url": row["source_url"],
                    "score": sc,
                })
        multicode_hits.sort(key=lambda x: (-x["score"], x["authority"], x["code_ref"]))

        # 3. BCA 116-page entities (Clauses, Spaces, Measurements, Elements, Components)
        bca_scored = []
        matched_bca_titles = set()
        for r in self.bca_entities.itertuples(index=False):
            title = str(r.title)
            desc = str(r.description or "")
            sc = self._score_blob(f"{title} {title} {desc}", raw_terms, expanded_terms)
            if sc > 0:
                pages = self._pages_for_entity(r.text_unit_ids)
                bca_scored.append({
                    "title": title,
                    "type": str(r.type),
                    "degree": int(r.degree),
                    "description": desc,
                    "pages": pages,
                    "pdf_url": f"{BCA_PDF_URL}#page={pages[0]}" if pages else None,
                    "score": round(sc + min(int(r.degree), 30) * 0.08, 2),
                })
        bca_scored.sort(key=lambda x: (-x["score"], -x["degree"], x["title"]))
        matched_bca_titles = {x["title"] for x in bca_scored[:25]}

        bca_clauses = [x for x in bca_scored if x["type"] in {"CLAUSE", "TABLE", "FIGURE"}][:18]
        bca_measurements = [x for x in bca_scored if x["type"] in {"MEASUREMENT", "CONDITION"}][:18]
        bca_objects = [x for x in bca_scored if x["type"] in {"SPACE", "BUILDING ELEMENT", "COMPONENT", "SYSTEM", "BUILDING USE"}][:18]

        # Pull measurements/clauses directly connected in the BCA graph to top matched objects
        for item in bca_clauses[:12]:
            nbrs = self.bca_neighbors.get(item["title"], [])
            item["related_measurements"] = [n["title"] for n in nbrs if n["type"] == "MEASUREMENT"][:6]
            item["related_objects"] = [n["title"] for n in nbrs if n["type"] in {"SPACE", "COMPONENT", "BUILDING ELEMENT", "SYSTEM"}][:5]

        # 4. BCA Source PDF Page excerpts
        page_hits = []
        for r in self.bca_docs.itertuples(index=False):
            text = str(r.text or "")
            sc = self._score_blob(text, raw_terms, expanded_terms)
            if sc > 0:
                m = re.search(r"p\.\s*(\d+)", str(r.title))
                page_no = int(m.group(1)) if m else None
                # Extract a focused snippet around first matching term
                low = text.casefold()
                pos = next((low.find(t) for t in raw_terms + expanded_terms if low.find(t) >= 0), 0)
                start = max(0, pos - 140)
                snippet = ("..." if start > 0 else "") + text[start:start + 520].strip() + ("..." if start + 520 < len(text) else "")
                page_hits.append({
                    "title": str(r.title),
                    "page": page_no,
                    "pdf_url": f"{BCA_PDF_URL}#page={page_no}" if page_no else None,
                    "score": sc,
                    "snippet": snippet,
                })
        page_hits.sort(key=lambda x: (-x["score"], x["page"] or 999))

        # 4b. SCDF Fire Code 2023 (540-page PDF) hits
        scdf_hits = []
        for row in self.scdf_pages:
            text = str(row.get("text") or "")
            sc = self._score_blob(f"{row.get('chapter','')} {row.get('code_ref','')} {text}", raw_terms, expanded_terms)
            if sc > 0:
                low = text.casefold()
                pos = next((low.find(t) for t in raw_terms + expanded_terms if low.find(t) >= 0), 0)
                start = max(0, pos - 140)
                snippet = ("..." if start > 0 else "") + text[start:start + 520].strip() + ("..." if start + 520 < len(text) else "")
                scdf_hits.append({
                    "title": row.get("title", ""),
                    "chapter": row.get("chapter", ""),
                    "code_ref": row.get("code_ref", ""),
                    "page": int(row["pdf_page"]) if str(row.get("pdf_page", "")).isdigit() else None,
                    "pdf_url": row.get("source_url"),
                    "score": sc,
                    "snippet": snippet,
                })
        scdf_hits.sort(key=lambda x: (-x["score"], x["page"] or 999))

        # 4c. SCDF 540-page GraphRAG extracted clauses & dimensions
        scdf_clauses = []
        matched_scdf_titles = set()
        if not self.scdf_entities.empty:
            scdf_scored = []
            for r in self.scdf_entities.itertuples(index=False):
                title = str(r.title)
                desc = str(r.description or "")
                sc = self._score_blob(f"{title} {title} {desc}", raw_terms, expanded_terms)
                if sc > 0:
                    pages = sorted({
                        self.scdf_unit_page[str(uid)]
                        for uid in (r.text_unit_ids if r.text_unit_ids is not None else [])
                        if str(uid) in self.scdf_unit_page and self.scdf_unit_page[str(uid)] is not None
                    })
                    scdf_scored.append({
                        "title": title,
                        "type": str(r.type),
                        "degree": int(r.degree),
                        "description": desc,
                        "pages": pages,
                        "pdf_url": f"{SCDF_PDF_URL}#page={pages[0]}" if pages else None,
                        "score": round(sc + min(int(r.degree), 30) * 0.08, 2),
                    })
            scdf_scored.sort(key=lambda x: (-x["score"], -x["degree"], x["title"]))
            matched_scdf_titles = {x["title"] for x in scdf_scored[:25]}
            scdf_clauses = [x for x in scdf_scored if x["type"] in {"CLAUSE", "TABLE", "FIGURE", "MEASUREMENT"}][:20]
            for item in scdf_clauses[:15]:
                nbrs = self.scdf_neighbors.get(item["title"], [])
                item["related_measurements"] = [n["title"] for n in nbrs if n["type"] == "MEASUREMENT"][:6]
                item["related_objects"] = [n["title"] for n in nbrs if n["type"] in {"SPACE", "COMPONENT", "BUILDING ELEMENT", "SYSTEM"}][:5]

        # 5. IFC+SG Matched Components (direct text + pre-computed gemini-embedding-2 BCA->IFCSG matches)
        vector_boost = defaultdict(float)
        if not self.auto_matches.empty and matched_bca_titles:
            col = "code_entity" if "code_entity" in self.auto_matches.columns else "bca_entity"
            sub = self.auto_matches[
                (self.auto_matches[col].isin(matched_bca_titles))
                & (self.auto_matches["cosine_score"] >= 0.70)
                & (self.auto_matches["rank"] == 1)
            ]
            for r in sub.itertuples(index=False):
                vector_boost[str(r.ifcsg_title)] = max(vector_boost[str(r.ifcsg_title)], float(r.cosine_score))
        if not self.scdf_matches.empty and matched_scdf_titles:
            sub_s = self.scdf_matches[
                (self.scdf_matches["code_entity"].isin(matched_scdf_titles))
                & (self.scdf_matches["cosine_score"] >= 0.72)
                & (self.scdf_matches["rank"] == 1)
            ]
            for r in sub_s.itertuples(index=False):
                vector_boost[str(r.ifcsg_title)] = max(vector_boost[str(r.ifcsg_title)], float(r.cosine_score))

        comp_rows = []
        for comp, grp in self.ifc_params.groupby("component"):
            if not comp:
                continue
            agencies = sorted({a for a in grp["agency"] if a})
            if agency_filter != "ALL" and agency_filter not in agencies and "All" not in agencies:
                continue
            ifc_classes = sorted({c for c in grp["ifc_entity"] if c and c.upper() != "N.A"})
            subtypes = sorted({
                s.strip() for raw in grp["ifc_subtypes"] if raw and raw.upper() != "N.A"
                for s in raw.split(",") if s.strip()
            })
            psets = sorted({p for p in grp["property_set"] if p})
            prop_names = sorted({p for p in grp["property_name"] if p})
            blob = " ".join([
                comp, " ".join(ifc_classes), " ".join(subtypes),
                " ".join(psets), " ".join(prop_names),
                " ".join(grp["parameter"].astype(str).tolist()),
            ])
            text_score = self._score_blob(blob, raw_terms, expanded_terms)
            vec_score = max(
                [vector_boost.get(comp, 0.0)]
                + [vector_boost.get(c, 0.0) for c in ifc_classes]
                + [vector_boost.get(p, 0.0) for p in psets]
            )
            total_score = text_score + (vec_score * 5.0 if vec_score > 0 else 0.0)
            if total_score > 0:
                comp_rows.append({
                    "component": comp,
                    "agencies": agencies,
                    "disciplines": sorted({d for d in grp["discipline"] if d}),
                    "ifc_entities": ifc_classes,
                    "subtypes": subtypes,
                    "property_sets": psets,
                    "revit": sorted({x for x in grp["revit"] if x and x.upper() != "N.A"}),
                    "archicad": sorted({x for x in grp["archicad"] if x and x.upper() != "N.A"}),
                    "tekla": sorted({x for x in grp["tekla"] if x and x.upper() != "N.A"}),
                    "bentley": sorted({x for x in grp["bentley"] if x and x.upper() != "N.A"}),
                    "param_count": len(grp),
                    "vector_match": round(vec_score, 3) if vec_score > 0 else None,
                    "score": round(total_score, 2),
                })
        comp_rows.sort(key=lambda x: (-x["score"], x["component"]))
        top_components = comp_rows[:14]
        selected_comp_names = {c["component"] for c in top_components[:10]}

        # 6. Exact CORENET X Parameter Table for matched components (plus direct parameter hits)
        param_rows = []
        for r in self.ifc_params.itertuples(index=False):
            if r.is_subtype_declaration:
                continue
            if agency_filter != "ALL" and r.agency not in (agency_filter, "All"):
                continue
            in_comp = r.component in selected_comp_names
            blob = f"{r.component} {r.parameter} {r.ifc_entity} {r.ifc_subtypes} {r.property_set} {r.property_name} {r.accepted_values}"
            sc = self._score_blob(blob, raw_terms, expanded_terms)
            if in_comp or sc >= 3.0:
                param_rows.append({
                    "agency": r.agency,
                    "discipline": r.discipline,
                    "component": r.component,
                    "parameter": r.parameter,
                    "ifc_entity": r.ifc_entity,
                    "ifc_subtypes": r.ifc_subtypes,
                    "property_set": r.property_set,
                    "property_name": r.property_name,
                    "property_type": r.property_type,
                    "property_unit": r.property_unit,
                    "accepted_values": r.accepted_values,
                    "sample_value": r.sample_value,
                    "score": sc + (2.0 if in_comp else 0.0),
                })
        param_rows.sort(key=lambda x: (-x["score"], x["component"], x["agency"], x["property_set"], x["property_name"]))

        # 7. Controlled Space Values matching query
        sv_hits = []
        for r in self.ifc_space_values.itertuples(index=False):
            sc = self._score_blob(f"{r.property} {r.value} {r.development_use}", raw_terms, expanded_terms)
            if sc > 0:
                sv_hits.append({
                    "property": r.property,
                    "value": r.value,
                    "development_use": r.development_use,
                    "score": sc,
                })
        sv_hits.sort(key=lambda x: (-x["score"], x["property"], x["value"]))

        return {
            "query": query,
            "agency_filter": agency_filter,
            "expanded_terms": expanded_terms,
            "stats": self.stats,
            "design": {
                "bridge_checks": bridge_checks,
                "multicode_clauses": multicode_hits[:12],
                "bca_clauses": bca_clauses,
                "bca_measurements": bca_measurements,
                "bca_objects": bca_objects,
                "pdf_pages": page_hits[:12],
                "scdf_clauses": scdf_clauses,
                "scdf_pages": scdf_hits[:18],
            },
            "ifcsg": {
                "components": top_components,
                "parameters": param_rows[:120],
                "space_values": sv_hits[:60],
            },
        }


HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>SG BIM Compliance Workbench — BCA Code + CORENET X IFC+SG</title>
<style>
  :root {
    --bg: #0f172a;
    --panel: #1e293b;
    --card: #0b1220;
    --border: #334155;
    --text: #e2e8f0;
    --muted: #94a3b8;
    --blue: #38bdf8;
    --green: #34d399;
    --purple: #a78bfa;
    --amber: #fbbf24;
    --pink: #f472b6;
    --red: #fb7185;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.45;
  }
  header {
    background: #020617;
    border-bottom: 1px solid var(--border);
    padding: 16px 24px;
    position: sticky;
    top: 0;
    z-index: 20;
  }
  .top-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 12px;
  }
  h1 {
    margin: 0;
    font-size: 18px;
    font-weight: 700;
    letter-spacing: 0.2px;
  }
  .subtitle {
    color: var(--muted);
    font-size: 12px;
  }
  .search-bar {
    display: flex;
    gap: 10px;
    max-width: 1100px;
  }
  input[type="text"] {
    flex: 1;
    padding: 11px 14px;
    font-size: 15px;
    background: var(--panel);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 8px;
    outline: none;
  }
  input[type="text"]:focus { border-color: var(--blue); }
  button.primary {
    padding: 10px 20px;
    font-size: 14px;
    font-weight: 600;
    background: var(--blue);
    color: #020617;
    border: none;
    border-radius: 8px;
    cursor: pointer;
  }
  button.primary:hover { filter: brightness(1.1); }
  button.ghost {
    padding: 6px 12px;
    font-size: 12px;
    background: transparent;
    color: var(--muted);
    border: 1px solid var(--border);
    border-radius: 6px;
    cursor: pointer;
  }
  button.ghost:hover { color: var(--text); border-color: var(--blue); }
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 10px;
    align-items: center;
  }
  .chip-label { font-size: 12px; color: var(--muted); margin-right: 4px; }
  .chip {
    padding: 4px 10px;
    font-size: 12px;
    background: var(--panel);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 999px;
    cursor: pointer;
  }
  .chip:hover, .chip.active {
    background: rgba(56, 189, 248, 0.18);
    border-color: var(--blue);
    color: #fff;
  }
  .meta-strip {
    padding: 8px 24px;
    font-size: 12px;
    color: var(--muted);
    border-bottom: 1px solid var(--border);
    background: rgba(30, 41, 59, 0.45);
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    gap: 8px;
  }
  main {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 18px;
    padding: 18px 24px 40px;
  }
  @media (max-width: 1100px) {
    main { grid-template-columns: 1fr; }
  }
  .column {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 16px;
    min-width: 0;
  }
  .col-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    border-bottom: 1px solid var(--border);
    padding-bottom: 10px;
    margin-bottom: 14px;
  }
  .col-title {
    font-size: 15px;
    font-weight: 700;
    margin: 0;
  }
  .design-accent { color: var(--blue); }
  .ifc-accent { color: var(--purple); }
  .tabs {
    display: flex;
    gap: 6px;
    margin-bottom: 14px;
    flex-wrap: wrap;
  }
  .tab {
    padding: 6px 12px;
    font-size: 12px;
    font-weight: 600;
    background: var(--card);
    color: var(--muted);
    border: 1px solid var(--border);
    border-radius: 7px;
    cursor: pointer;
  }
  .tab.active {
    background: rgba(56, 189, 248, 0.16);
    border-color: var(--blue);
    color: #fff;
  }
  .tab.active.purple {
    background: rgba(167, 139, 250, 0.18);
    border-color: var(--purple);
  }
  .card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 9px;
    padding: 12px 14px;
    margin-bottom: 10px;
  }
  .card-title {
    font-size: 14px;
    font-weight: 650;
    margin: 0 0 6px;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
  }
  .card p, .card .small {
    margin: 4px 0;
    font-size: 12.5px;
    color: #cbd5e1;
  }
  .badge {
    display: inline-block;
    padding: 2px 7px;
    border-radius: 5px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.2px;
  }
  .b-blue { background: rgba(56,189,248,0.18); color: #7dd3fc; }
  .b-purple { background: rgba(167,139,250,0.2); color: #ddd6fe; }
  .b-green { background: rgba(52,211,153,0.18); color: #6ee7b7; }
  .b-amber { background: rgba(251,191,36,0.18); color: #fde68a; }
  .b-pink { background: rgba(244,114,182,0.18); color: #fbcfe8; }
  .b-red { background: rgba(251,113,133,0.2); color: #fecdd3; }
  .b-slate { background: rgba(148,163,184,0.18); color: #cbd5e1; }
  a { color: var(--blue); text-decoration: none; }
  a:hover { text-decoration: underline; }
  code {
    background: rgba(15, 23, 42, 0.9);
    border: 1px solid #334155;
    padding: 1px 5px;
    border-radius: 4px;
    font-size: 11.5px;
    color: #f8fafc;
  }
  .table-wrap {
    overflow-x: auto;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--card);
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
  }
  th, td {
    text-align: left;
    padding: 7px 9px;
    border-bottom: 1px solid #1e293b;
    vertical-align: top;
  }
  th {
    background: #020617;
    color: var(--muted);
    font-weight: 600;
    position: sticky;
    top: 0;
  }
  tr:hover td { background: rgba(56, 189, 248, 0.05); }
  .empty {
    color: var(--muted);
    font-size: 13px;
    padding: 16px;
    text-align: center;
  }
  .authoring {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 6px;
    font-size: 11.5px;
    color: var(--muted);
  }
</style>
</head>
<body>
<header>
  <div class="top-row">
    <div>
      <h1>SG BIM Compliance Workbench</h1>
      <div class="subtitle" id="statsLine">Loading BCA Accessibility Code 2025 v1.1 + CORENET X IFC+SG (Sep 2026)...</div>
    </div>
    <button class="ghost" onclick="copyMarkdown()">Copy Markdown Summary</button>
  </div>
  <div class="search-bar">
    <input id="q" type="text" value="toilet" placeholder="Search any element or space: toilet, ramp, door, lift, alarm, railing, parking, refuse chute..." onkeydown="if(event.key==='Enter') runSearch()" />
    <button class="primary" onclick="runSearch()">Search</button>
  </div>
  <div class="chips">
    <span class="chip-label">Try:</span>
    <span class="chip" onclick="quick('toilet')">toilet</span>
    <span class="chip" onclick="quick('ramp')">ramp</span>
    <span class="chip" onclick="quick('door')">door</span>
    <span class="chip" onclick="quick('lift')">lift</span>
    <span class="chip" onclick="quick('alarm')">alarm</span>
    <span class="chip" onclick="quick('railing')">railing</span>
    <span class="chip" onclick="quick('shower')">shower</span>
    <span class="chip" onclick="quick('parking')">parking</span>
    <span class="chip" onclick="quick('refuse')">refuse chute</span>
    <span class="chip-label" style="margin-left:14px;">Agency:</span>
    <span id="agencyChips"></span>
  </div>
</header>

<div class="meta-strip">
  <div id="expandedInfo">Expanded BIM terms: —</div>
  <div id="modeInfo">Offline instant search ($0) · Uses BCA 116-page GraphRAG + CORENET X IFC+SG Excel + pre-computed gemini-embedding-2 matches</div>
</div>
<div id="indexMonitor" style="padding:8px 24px;background:#020617;border-bottom:1px solid var(--border);font-family:ui-monospace,Consolas,monospace;font-size:12px;color:#34d399;white-space:pre-wrap;display:none;"></div>

<main>
  <section class="column">
    <div class="col-header">
      <h2 class="col-title design-accent">1. Design Requirements (BCA COA 2025 v1.1 + Multi-Code)</h2>
      <span class="badge b-blue" id="designCount">0</span>
    </div>
    <div class="tabs" id="designTabs">
      <button class="tab active" onclick="switchDesignTab('checks', this)">Verified Checks & Cross-Code</button>
      <button class="tab" onclick="switchDesignTab('clauses', this)">BCA Clauses (116p Graph)</button>
      <button class="tab" onclick="switchDesignTab('measurements', this)">Dimensions & Conditions</button>
      <button class="tab" onclick="switchDesignTab('pages', this)">BCA PDF Pages</button>
      <button class="tab" onclick="switchDesignTab('scdf', this)">SCDF Fire Code (540p)</button>
    </div>
    <div id="designBody"></div>
  </section>

  <section class="column">
    <div class="col-header">
      <h2 class="col-title ifc-accent">2. IFC+SG Model Requirements (CORENET X CoP 3.1)</h2>
      <span class="badge b-purple" id="ifcCount">0</span>
    </div>
    <div class="tabs" id="ifcTabs">
      <button class="tab active purple" onclick="switchIfcTab('components', this)">IFC Entities & Components</button>
      <button class="tab" onclick="switchIfcTab('params', this)">SGPset / Parameter Table</button>
      <button class="tab" onclick="switchIfcTab('spaces', this)">Allowed Space Values</button>
    </div>
    <div id="ifcBody"></div>
  </section>
</main>

<script>
let currentData = null;
let currentAgency = "ALL";
let designTab = "checks";
let ifcTab = "components";

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
}

function renderAgencyChips(agencies) {
  const all = ["ALL", ...agencies.filter(a => a !== "All")];
  document.getElementById("agencyChips").innerHTML = all.map(a =>
    `<span class="chip ${currentAgency===a?'active':''}" onclick="setAgency('${a}')">${a}</span>`
  ).join(" ");
}

function setAgency(ag) {
  currentAgency = ag;
  runSearch();
}

function quick(term) {
  document.getElementById("q").value = term;
  runSearch();
}

function switchDesignTab(tab, btn) {
  designTab = tab;
  document.querySelectorAll("#designTabs .tab").forEach(b => b.classList.remove("active"));
  btn.classList.add("active");
  renderDesign();
}

function switchIfcTab(tab, btn) {
  ifcTab = tab;
  document.querySelectorAll("#ifcTabs .tab").forEach(b => b.classList.remove("active", "purple"));
  btn.classList.add("active", "purple");
  renderIfc();
}

async function runSearch() {
  const q = document.getElementById("q").value.trim();
  if (!q) return;
  const res = await fetch(`/api/search?q=${encodeURIComponent(q)}&agency=${encodeURIComponent(currentAgency)}`);
  currentData = await res.json();
  const s = currentData.stats;
  document.getElementById("statsLine").textContent =
    `BCA COA 2025 v1.1 (${s.bca_pages}p · ${s.bca_entities.toLocaleString()} entities)  |  SCDF Fire Code 2023 (${s.scdf_pages}p · ${(s.scdf_entities||0).toLocaleString()} entities)  |  CORENET X IFC+SG Sep 2026 (${s.ifcsg_components} components · ${s.ifcsg_parameters.toLocaleString()} parameters)`;
  renderAgencyChips(s.agencies);
  document.getElementById("expandedInfo").textContent =
    `Matched terms (${currentData.expanded_terms.length}): ${currentData.expanded_terms.join(", ")}`;
  const d = currentData.design;
  const i = currentData.ifcsg;
  document.getElementById("designCount").textContent =
    `${d.bridge_checks.length} checks · ${d.bca_clauses.length} BCA clauses · ${d.scdf_pages.length} SCDF pages`;
  document.getElementById("ifcCount").textContent =
    `${i.components.length} components · ${i.parameters.length} parameters`;
  renderDesign();
  renderIfc();
}

function methodBadge(m) {
  if (m === "geometry_clearance") return `<span class="badge b-amber">3D geometry check</span>`;
  if (m === "property_lookup") return `<span class="badge b-green">IFC property check</span>`;
  return `<span class="badge b-pink">Drawing / submittal</span>`;
}

function renderDesign() {
  if (!currentData) return;
  const d = currentData.design;
  const el = document.getElementById("designBody");

  if (designTab === "checks") {
    let html = "";
    if (d.bridge_checks.length) {
      html += d.bridge_checks.map(c => `
        <div class="card">
          <div class="card-title">
            <span class="badge b-blue">${esc(c.check_id)}</span>
            <span class="badge b-slate">${esc(c.authority)} ${esc(c.code_ref)}</span>
            ${methodBadge(c.evaluation_method)}
            <span class="badge b-purple">${esc(c.ifc_class)}</span>
          </div>
          <p><strong>${esc(c.title)}</strong></p>
          <p><strong>Applies when:</strong> ${esc(c.applies_when)}</p>
          <p><strong>Requirement (${esc(c.unit)}):</strong> <code>${esc(JSON.stringify(c.threshold))}</code></p>
          <p><strong>How to verify:</strong> ${esc(c.measurement_basis)}</p>
          <p class="small"><strong>If not modeled:</strong> ${esc(c.open_evidence_if_unmodeled)}
            ${c.pdf_url ? ` · <a href="${c.pdf_url}" target="_blank">Open BCA PDF p. ${c.pdf_page} ↗</a>` : ""}
          </p>
        </div>
      `).join("");
    }
    if (d.multicode_clauses.length) {
      html += `<h3 style="font-size:13px;color:var(--muted);margin:14px 0 8px;">Cross-Agency Clauses (BCA + SCDF + Approved Document)</h3>`;
      html += d.multicode_clauses.map(c => `
        <div class="card">
          <div class="card-title">
            <span class="badge ${c.authority==='SCDF'?'b-red':'b-blue'}">${esc(c.authority)}</span>
            <span>${esc(c.code_ref)}</span>
            <span class="badge b-slate">${esc(c.source_locator)}</span>
            <a style="margin-left:auto;font-size:12px;" href="${esc(c.source_url)}" target="_blank">Source ↗</a>
          </div>
          <p>${esc(c.text)}</p>
        </div>
      `).join("");
    }
    if (!html) {
      html = `<div class="empty">No pre-written Stage 05 bridge check for this term yet — open the <strong>BCA Clauses (116p Graph)</strong> or <strong>Source PDF Pages</strong> tab to inspect all extracted clauses across all 116 pages!</div>`;
    }
    el.innerHTML = html;
  } else if (designTab === "clauses") {
    if (!d.bca_clauses.length) { el.innerHTML = `<div class="empty">No matching clauses found.</div>`; return; }
    el.innerHTML = d.bca_clauses.map(c => `
      <div class="card">
        <div class="card-title">
          <span class="badge b-blue">${esc(c.type)}</span>
          <span>${esc(c.title)}</span>
          ${c.pages.length ? `<a style="margin-left:auto;font-size:12px;" href="${c.pdf_url}" target="_blank">PDF p. ${c.pages.join(", ")} ↗</a>` : ""}
        </div>
        <p>${esc(c.description)}</p>
        ${(c.related_measurements && c.related_measurements.length) ? `<p><strong>Linked dimensions:</strong> ${c.related_measurements.map(m => `<code>${esc(m)}</code>`).join(" ")}</p>` : ""}
        ${(c.related_objects && c.related_objects.length) ? `<p><strong>Linked spaces/elements:</strong> ${c.related_objects.map(o => `<span class="badge b-green">${esc(o)}</span>`).join(" ")}</p>` : ""}
      </div>
    `).join("");
  } else if (designTab === "measurements") {
    const items = [...d.bca_measurements, ...d.bca_objects];
    if (!items.length) { el.innerHTML = `<div class="empty">No matching dimensions or objects found.</div>`; return; }
    el.innerHTML = items.map(c => `
      <div class="card">
        <div class="card-title">
          <span class="badge ${c.type==='MEASUREMENT'?'b-amber':c.type==='CONDITION'?'b-pink':'b-green'}">${esc(c.type)}</span>
          <span>${esc(c.title)}</span>
          ${c.pages.length ? `<a style="margin-left:auto;font-size:12px;" href="${c.pdf_url}" target="_blank">PDF p. ${c.pages.join(", ")} ↗</a>` : ""}
        </div>
        <p>${esc(c.description)}</p>
      </div>
    `).join("");
  } else if (designTab === "pages") {
    if (!d.pdf_pages.length) { el.innerHTML = `<div class="empty">No matching BCA PDF pages found.</div>`; return; }
    el.innerHTML = d.pdf_pages.map(p => `
      <div class="card">
        <div class="card-title">
          <span class="badge b-blue">BCA PDF p. ${p.page}</span>
          <span>${esc(p.title)}</span>
          ${p.pdf_url ? `<a style="margin-left:auto;font-size:12px;" href="${p.pdf_url}" target="_blank">Open Official PDF ↗</a>` : ""}
        </div>
        <p style="font-family:ui-monospace,Consolas,monospace;font-size:11.5px;white-space:pre-wrap;">${esc(p.snippet)}</p>
      </div>
    `).join("");
  } else if (designTab === "scdf") {
    let html = "";
    if (d.scdf_clauses && d.scdf_clauses.length) {
      html += `<h3 style="font-size:13px;color:var(--muted);margin:0 0 8px;">Extracted SCDF Clauses & Dimensions (540p GraphRAG)</h3>`;
      html += d.scdf_clauses.map(c => `
        <div class="card">
          <div class="card-title">
            <span class="badge b-red">${esc(c.type)}</span>
            <span>${esc(c.title)}</span>
            ${c.pages.length ? `<a style="margin-left:auto;font-size:12px;" href="${esc(c.pdf_url)}" target="_blank">SCDF PDF p. ${c.pages.slice(0,5).join(", ")} ↗</a>` : ""}
          </div>
          <p>${esc(c.description)}</p>
          ${(c.related_measurements && c.related_measurements.length) ? `<p><strong>Linked numbers:</strong> ${c.related_measurements.map(m => `<code>${esc(m)}</code>`).join(" ")}</p>` : ""}
          ${(c.related_objects && c.related_objects.length) ? `<p><strong>Linked elements:</strong> ${c.related_objects.map(o => `<span class="badge b-green">${esc(o)}</span>`).join(" ")}</p>` : ""}
        </div>
      `).join("");
    }
    if (d.scdf_pages && d.scdf_pages.length) {
      html += `<h3 style="font-size:13px;color:var(--muted);margin:14px 0 8px;">Matching SCDF Fire Code PDF Pages</h3>`;
      html += d.scdf_pages.slice(0, 10).map(p => `
        <div class="card">
          <div class="card-title">
            <span class="badge b-red">SCDF p. ${p.page}</span>
            <span class="badge b-slate">${esc(p.code_ref)}</span>
            <span style="font-size:12px;color:var(--muted);">${esc(p.chapter)}</span>
            ${p.pdf_url ? `<a style="margin-left:auto;font-size:12px;" href="${esc(p.pdf_url)}" target="_blank">Open SCDF PDF ↗</a>` : ""}
          </div>
          <p style="font-family:ui-monospace,Consolas,monospace;font-size:11.5px;white-space:pre-wrap;">${esc(p.snippet)}</p>
        </div>
      `).join("");
    }
    el.innerHTML = html || `<div class="empty">No matching SCDF Fire Code 2023 results found.</div>`;
  }
}

function renderIfc() {
  if (!currentData) return;
  const i = currentData.ifcsg;
  const el = document.getElementById("ifcBody");

  if (ifcTab === "components") {
    if (!i.components.length) { el.innerHTML = `<div class="empty">No matching CORENET X IFC+SG components for this filter.</div>`; return; }
    el.innerHTML = i.components.map(c => `
      <div class="card">
        <div class="card-title">
          <span>${esc(c.component)}</span>
          ${c.ifc_entities.map(e => `<span class="badge b-purple">${esc(e)}</span>`).join("")}
          ${c.vector_match ? `<span class="badge b-green" title="Pre-computed gemini-embedding-2 match to BCA Code">AI match ${c.vector_match}</span>` : ""}
        </div>
        <p>
          <strong>Agencies:</strong> ${c.agencies.map(a => `<span class="badge ${a==='SCDF'?'b-red':a==='BCA'?'b-blue':'b-slate'}">${esc(a)}</span>`).join(" ")}
          &nbsp;<strong>Disciplines:</strong> ${c.disciplines.map(d => `<code>${esc(d)}</code>`).join(" ")}
          &nbsp;(${c.param_count} parameters)
        </p>
        <p><strong>IFC SubTypes (* = USERDEFINED):</strong> ${c.subtypes.length ? c.subtypes.map(s => `<code>${esc(s)}</code>`).join(" ") : "Standard / N.A"}</p>
        <p><strong>Property Sets:</strong> ${c.property_sets.length ? c.property_sets.map(p => `<code>${esc(p)}</code>`).join(" ") : "Native IFC attributes"}</p>
        <div class="authoring">
          <span><strong>Revit:</strong> ${esc(c.revit.join(", ") || "N.A")}</span> ·
          <span><strong>Archicad:</strong> ${esc(c.archicad.join(", ") || "N.A")}</span> ·
          <span><strong>Tekla:</strong> ${esc(c.tekla.join(", ") || "N.A")}</span> ·
          <span><strong>Bentley:</strong> ${esc(c.bentley.join(", ") || "N.A")}</span>
        </div>
      </div>
    `).join("");
  } else if (ifcTab === "params") {
    if (!i.parameters.length) { el.innerHTML = `<div class="empty">No matching parameters.</div>`; return; }
    el.innerHTML = `
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Agency</th>
              <th>Component</th>
              <th>IFC4 Entity / SubType</th>
              <th>Property Set . Property</th>
              <th>Type / Allowed Values</th>
            </tr>
          </thead>
          <tbody>
            ${i.parameters.map(p => `
              <tr>
                <td><span class="badge ${p.agency==='SCDF'?'b-red':p.agency==='BCA'?'b-blue':'b-slate'}">${esc(p.agency)}</span><br/><span style="color:var(--muted);font-size:10.5px;">${esc(p.discipline)}</span></td>
                <td><strong>${esc(p.component)}</strong><br/><span style="color:var(--muted);font-size:11px;">${esc(p.parameter)}</span></td>
                <td><code>${esc(p.ifc_entity)}</code><br/><span style="color:var(--muted);font-size:10.5px;">${esc(p.ifc_subtypes)}</span></td>
                <td><code>${esc(p.property_set ? p.property_set + "." + p.property_name : p.property_name)}</code></td>
                <td>${esc(p.property_type)}${p.property_unit ? ` (${esc(p.property_unit)})` : ""}${p.accepted_values ? `<br/><span style="color:#a7f3d0;font-size:11px;">${esc(p.accepted_values)}</span>` : ""}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    `;
  } else if (ifcTab === "spaces") {
    if (!i.space_values.length) { el.innerHTML = `<div class="empty">No matching controlled Space Values for this term.</div>`; return; }
    el.innerHTML = `
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>Property</th><th>Allowed CORENET X Value</th><th>Development Use</th></tr>
          </thead>
          <tbody>
            ${i.space_values.map(v => `
              <tr>
                <td><code>${esc(v.property)}</code></td>
                <td><strong>${esc(v.value)}</strong></td>
                <td style="color:var(--muted);">${esc(v.development_use || "—")}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    `;
  }
}

function copyMarkdown() {
  if (!currentData) return;
  const d = currentData.design;
  const i = currentData.ifcsg;
  const lines = [
    `# SG BIM Compliance Summary — "${currentData.query}" (Agency: ${currentData.agency_filter})`,
    "",
    "## 1. Design Requirements (BCA COA 2025 v1.1 + Multi-Code)",
    ...d.bridge_checks.map(c => `- **${c.check_id}** (${c.authority} \`${c.code_ref}\`, ${c.evaluation_method}): ${c.title} — Threshold: \`${JSON.stringify(c.threshold)}\``),
    ...d.bca_clauses.slice(0, 8).map(c => `- **${c.title}** (PDF p. ${c.pages.join(", ")}): ${c.description}`),
    "",
    "## 2. IFC+SG Model Requirements (CORENET X CoP 3.1)",
    ...i.components.slice(0, 8).map(c => `- **${c.component}** → \`${c.ifc_entities.join(", ")}\` | SubTypes: \`${c.subtypes.join(", ") || "N.A"}\` | Agencies: ${c.agencies.join(", ")} | Psets: \`${c.property_sets.join(", ")}\``),
  ];
  navigator.clipboard.writeText(lines.join("\n"));
  alert("Copied Markdown checklist to clipboard!");
}

async function pollIndexStatus() {
  try {
    const res = await fetch("/api/index-status?scope=scdf");
    const st = await res.json();
    const box = document.getElementById("indexMonitor");
    if (st.state === "not_started") { box.style.display = "none"; return; }
    box.style.display = "block";
    box.style.color = st.state === "error" ? "#fb7185" : (st.state === "complete" ? "#38bdf8" : "#34d399");
    box.textContent =
      `[SCDF 540p INDEXER :: ${st.state.toUpperCase()}] ${st.ascii_bar}  |  ${st.current_stage} (${st.done.toLocaleString()} / ${st.total.toLocaleString()})  |  Cache: ${st.cache_files.toLocaleString()} files (${st.cache_mb} MB)  |  Last log: ${st.last_update}`;
  } catch (_) {}
}

runSearch();
pollIndexStatus();
setInterval(pollIndexStatus, 3000);
</script>
</body>
</html>
"""


def make_handler(store):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, body, content_type):
            data = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path in ("/", "/index.html"):
                self._send(200, HTML_PAGE, "text/html; charset=utf-8")
                return
            if parsed.path == "/api/search":
                qs = parse_qs(parsed.query)
                query = qs.get("q", [""])[0]
                agency = qs.get("agency", ["ALL"])[0]
                payload = store.search(query, agency_filter=agency)
                self._send(200, json.dumps(payload, ensure_ascii=False), "application/json; charset=utf-8")
                return
            if parsed.path == "/api/health":
                self._send(200, json.dumps({"ok": True, "stats": store.stats}), "application/json; charset=utf-8")
                return
            if parsed.path == "/api/index-status":
                qs = parse_qs(parsed.query)
                scope = qs.get("scope", ["scdf"])[0]
                st = read_index_status(scope)
                st["ascii_bar"] = ascii_bar(st["pct"], width=32)
                self._send(200, json.dumps(st, ensure_ascii=False), "application/json; charset=utf-8")
                return
            self._send(404, "Not found", "text/plain; charset=utf-8")

        def log_message(self, format, *args):
            return

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    store = ComplianceStore()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(store))
    print(f"SG BIM Compliance Workbench running at http://{args.host}:{args.port}", flush=True)
    print(
        f"Loaded BCA ({store.stats['bca_pages']} pages, {store.stats['bca_entities']} entities) "
        f"+ IFC+SG ({store.stats['ifcsg_components']} components, {store.stats['ifcsg_parameters']} parameters).",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
