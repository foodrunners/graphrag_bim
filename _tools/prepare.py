"""Prepare pinned BCA PDF, multicode, and CORENET X IFC+SG Excel inputs for Microsoft GraphRAG."""

import argparse
from collections import defaultdict
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import NamedTemporaryFile, TemporaryDirectory
from urllib.request import urlopen

from pypdf import PdfReader
import yaml

from multicode import read_graph


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "01_source"
EVIDENCE = ROOT / "02_evidence"
ENGINE = ROOT / "03_graphrag"
EDITION = json.loads((SOURCE / "edition.json").read_text(encoding="utf-8"))
IFCSG_EDITION = json.loads((SOURCE / "ifcsg_edition.json").read_text(encoding="utf-8"))
SCDF_EDITION = json.loads((SOURCE / "scdf_edition.json").read_text(encoding="utf-8"))


def save(path, data):
    """Publish a complete file, including when repeating a preparation run."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temp = Path(handle.name)
        try:
            handle.write(data)
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
    try:
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def open_edition(local_copy):
    cached = SOURCE / "output" / "code.pdf"
    if local_copy or cached.exists():
        data = (local_copy or cached).read_bytes()
    else:
        with urlopen(EDITION["pdf"], timeout=90) as response:
            data = response.read()
    if sha256(data).hexdigest() != EDITION["sha256"]:
        raise ValueError("The PDF differs from the pinned source. Check its amendment page and review the clause selectors before changing edition.json.")
    reader = PdfReader(BytesIO(data))
    if len(reader.pages) != EDITION["page_count"]:
        raise ValueError("PDF page count differs from edition.json.")
    if not cached.exists() or local_copy:
        save(cached, data)
    return reader


def open_scdf_edition(local_copy):
    cached = SOURCE / "output" / SCDF_EDITION["filename"]
    if local_copy or cached.exists():
        data = (local_copy or cached).read_bytes()
    else:
        with urlopen(SCDF_EDITION["pdf"], timeout=180) as response:
            data = response.read()
    digest = sha256(data).hexdigest()
    if digest != SCDF_EDITION["sha256"]:
        raise ValueError(
            "The SCDF Fire Code PDF differs from 01_source/scdf_edition.json. "
            f"Got SHA-256 {digest}. Inspect amendments before updating scdf_edition.json."
        )
    reader = PdfReader(BytesIO(data))
    if len(reader.pages) != SCDF_EDITION["page_count"]:
        raise ValueError(f"SCDF PDF page count differs from scdf_edition.json ({len(reader.pages)} vs {SCDF_EDITION['page_count']}).")
    if not cached.exists() or local_copy:
        save(cached, data)
    return reader, digest


def records_for_scdf(reader):
    rev = SCDF_EDITION["revision_date"]
    url = SCDF_EDITION["pdf"]
    current_chapter = "Front Matter"
    for page, source_page in enumerate(reader.pages, 1):
        raw_text = (source_page.extract_text() or "").strip()
        text = re.sub(r"[ \t]+\n", "\n", raw_text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if not text:
            text = "Image-only page. Open the source SCDF Fire Code PDF for visual review."
        ch_match = re.search(r"\b(CHAPTER\s+\d+\s*[-–:]?[^\n]{0,60}|APPENDIX\s+\d+[^\n]{0,60})", text, re.I)
        if ch_match and page > 3:
            current_chapter = " ".join(ch_match.group(1).split())
        cl_matches = re.findall(r"\bCLAUSE\s+(\d+(?:\.\d+)*[^\n]{0,45})", text, re.I)
        if cl_matches:
            code_ref = "Clause " + " ".join(cl_matches[0].split())
        else:
            sub_matches = re.findall(r"(?m)^(\d+\.\d+(?:\.\d+)*[a-z]?)\s+", text)
            code_ref = f"Clause {sub_matches[0]}" if sub_matches else f"PDF page {page}"
        yield {
            "id": f"SG-SCDF-FC2023-{rev}/p{page}",
            "title": f"SCDF Fire Code 2023 ({rev}) | {code_ref} | p. {page}",
            "authority": "SCDF",
            "chapter": current_chapter,
            "code_ref": code_ref,
            "pdf_page": str(page),
            "record_kind": "scdf fire code page",
            "source_url": f"{url}#page={page}",
            "text": text,
        }


def open_ifcsg_workbook(local_copy):
    try:
        import openpyxl
    except ImportError as error:
        raise ValueError("Install openpyxl (pip install -r requirements.txt) to prepare the ifcsg scope.") from error

    cached = SOURCE / "output" / IFCSG_EDITION["filename"]
    if local_copy or cached.exists():
        data = (local_copy or cached).read_bytes()
    else:
        with urlopen(IFCSG_EDITION["xlsx"], timeout=90) as response:
            data = response.read()
    digest = sha256(data).hexdigest()
    if digest != IFCSG_EDITION["sha256"]:
        raise ValueError(
            "The IFC+SG Excel workbook differs from 01_source/ifcsg_edition.json. "
            f"Got SHA-256 {digest}. Inspect the Change Log sheet before updating ifcsg_edition.json."
        )
    if not cached.exists() or local_copy:
        save(cached, data)
    return openpyxl.load_workbook(BytesIO(data), read_only=True, data_only=True), digest


def _norm_cell(val):
    if val is None:
        return ""
    return " ".join(str(val).strip().split())


def _norm_agency(val):
    text = _norm_cell(val)
    upper = text.upper()
    if upper == "ALL":
        return "All"
    if upper == "NPARKS":
        return "NParks"
    return text


def _chunk(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def records_for_ifcsg(wb):
    """Build cohesive semantic JSONL records from all sheets of the official CORENET X IFC+SG workbook."""
    rev = IFCSG_EDITION["revision_date"]
    url = IFCSG_EDITION["publisher_page"]

    # 1. Edition & Change Log summary
    readme_lines = [
        _norm_cell(" ".join(_norm_cell(c) for c in row if _norm_cell(c)))
        for row in wb["README"].iter_rows(values_only=True)
    ]
    readme_lines = [line for line in readme_lines if line]
    changelog_rows = list(wb["Change Log"].iter_rows(values_only=True))
    recent_changes = []
    for row in changelog_rows[1:25]:
        date_str = str(row[0])[:10] if row[0] else ""
        parts = [date_str, _norm_cell(row[1]), _norm_cell(row[2]), _norm_cell(row[3])]
        if any(parts):
            recent_changes.append(" | ".join(p for p in parts if p))
    yield {
        "id": f"SG-IFCSG-{rev}/overview",
        "title": f"CORENET X IFC+SG {rev} | Overview & Change Log",
        "source_sheet": "README + Change Log",
        "ifc_entity": "N.A",
        "agencies": "All",
        "discipline": "All",
        "record_kind": "schema overview",
        "source_url": url,
        "text": (
            f"CORENET X IFC+SG Industry Mapping File ({IFCSG_EDITION['edition']}, revised {rev}).\n\n"
            "README:\n" + "\n".join(f"- {line}" for line in readme_lines) + "\n\n"
            "Recent Change Log entries:\n" + "\n".join(f"- {line}" for line in recent_changes)
        ),
    }

    # 2. CX Pilot Mapping grouped by (Identified Component, IFC4 Entity) across all agencies
    ws = wb["CX Pilot Mapping"]
    cx_rows = [row for row in list(ws.iter_rows(values_only=True))[1:] if any(row[:14])]
    grouped = defaultdict(list)
    for row in cx_rows:
        component = _norm_cell(row[2])
        ifc_entity = _norm_cell(row[9]) or "Unspecified"
        grouped[(component, ifc_entity)].append(row)

    for (component, ifc_entity), group_rows in sorted(grouped.items()):
        agencies = sorted({_norm_agency(r[1]) for r in group_rows if _norm_cell(r[1])})
        disciplines = sorted({_norm_cell(r[8]) for r in group_rows if _norm_cell(r[8])})
        subtypes = sorted({
            st.strip()
            for r in group_rows
            if _norm_cell(r[10]) and _norm_cell(r[10]).upper() != "N.A"
            for st in _norm_cell(r[10]).split(",")
            if st.strip()
        })
        revit = sorted({_norm_cell(r[4]) for r in group_rows if _norm_cell(r[4]) and _norm_cell(r[4]).upper() != "N.A"})
        archicad = sorted({_norm_cell(r[5]) for r in group_rows if _norm_cell(r[5]) and _norm_cell(r[5]).upper() != "N.A"})
        tekla = sorted({_norm_cell(r[6]) for r in group_rows if _norm_cell(r[6]) and _norm_cell(r[6]).upper() != "N.A"})
        bentley = sorted({_norm_cell(r[7]) for r in group_rows if _norm_cell(r[7]) and _norm_cell(r[7]).upper() != "N.A"})

        param_lines = []
        for r in group_rows:
            sn = _norm_cell(r[0])
            ag = _norm_agency(r[1])
            param = _norm_cell(r[3])
            sub = _norm_cell(r[10])
            pset = _norm_cell(r[11])
            pname = _norm_cell(r[12])
            ptype = _norm_cell(r[13])
            punit = _norm_cell(r[14]) if len(r) > 14 else ""
            mat = _norm_cell(r[15]) if len(r) > 15 else ""
            accepted = _norm_cell(r[16]) if len(r) > 16 else ""
            sample = _norm_cell(r[17]) if len(r) > 17 else ""
            if "please refer to property sets below" in pset.lower():
                param_lines.append(f"- [S/N {sn} | {ag}] Subtype declaration: {param or 'Component'} -> IFC Sub Type: {sub}")
                continue
            prop_ref = f"{pset}.{pname}" if pset and pset.upper() != "N.A" else (pname or "N.A")
            details = [f"Type: {ptype}" if ptype and ptype.upper() != "N.A" else ""]
            if punit and punit.upper() != "N.A":
                details.append(f"Unit: {punit}")
            if sub and sub.upper() != "N.A":
                details.append(f"SubTypes: {sub}")
            if mat and mat.upper() != "N.A":
                details.append(f"MaterialSet: {mat}")
            if accepted and accepted.upper() != "N.A":
                details.append(f"AcceptedValues: {accepted}")
            if sample and sample.upper() != "N.A":
                details.append(f"Sample: {sample}")
            detail_str = "; ".join(d for d in details if d)
            param_lines.append(f"- [S/N {sn} | {ag}] Parameter '{param}' -> `{prop_ref}` ({detail_str})")

        slug = re.sub(r"[^a-zA-Z0-9]+", "-", f"{component}-{ifc_entity}").strip("-").lower()
        text = (
            f"Identified Component: {component}\n"
            f"IFC4 Entity: {ifc_entity}\n"
            f"IFC Sub Types (* = USERDEFINED): {', '.join(subtypes) if subtypes else 'N.A'}\n"
            f"Governing Agencies: {', '.join(agencies)}\n"
            f"Suggested Disciplines: {', '.join(disciplines)}\n"
            f"Authoring Tool Representations: "
            f"Revit={', '.join(revit) or 'N.A'}; "
            f"Archicad={', '.join(archicad) or 'N.A'}; "
            f"Tekla={', '.join(tekla) or 'N.A'}; "
            f"Bentley={', '.join(bentley) or 'N.A'}\n\n"
            "Mapped Regulatory Parameters & Property Sets:\n"
            + "\n".join(param_lines)
        )
        yield {
            "id": f"SG-IFCSG-{rev}/component/{slug}",
            "title": f"IFC+SG | {component} | {ifc_entity}",
            "source_sheet": "CX Pilot Mapping",
            "ifc_entity": ifc_entity,
            "agencies": ", ".join(agencies),
            "discipline": ", ".join(disciplines),
            "record_kind": "ifc-sg component mapping",
            "source_url": url,
            "text": text,
        }

    # 3. Space Values controlled vocabularies
    sv_rows = [row for row in list(wb["Space Values"].iter_rows(values_only=True))[1:] if _norm_cell(row[0])]
    sv_by_prop = defaultdict(list)
    for row in sv_rows:
        prop = _norm_cell(row[0])
        val = _norm_cell(row[1])
        dev_use = _norm_cell(row[2]) if len(row) > 2 else ""
        if val:
            sv_by_prop[prop].append((val, dev_use))

    for prop, entries in sorted(sv_by_prop.items()):
        if prop == "AGF_Name":
            by_use = defaultdict(list)
            for val, dev_use in entries:
                by_use[dev_use or "General"].append(val)
            for dev_use, vals in sorted(by_use.items()):
                for part, batch in enumerate(_chunk(vals, 60), 1):
                    slug = re.sub(r"[^a-zA-Z0-9]+", "-", f"agf-name-{dev_use}-{part}").strip("-").lower()
                    yield {
                        "id": f"SG-IFCSG-{rev}/space-values/{slug}",
                        "title": f"IFC+SG Space Values | AGF_Name | {dev_use} (part {part})",
                        "source_sheet": "Space Values",
                        "ifc_entity": "IfcSpace",
                        "agencies": "URA",
                        "discipline": "ARC",
                        "record_kind": "controlled vocabulary",
                        "source_url": url,
                        "text": (
                            f"Property: SGPset_SpaceArea_GFA.AGF_Name (IFC4 Entity: IfcSpace, SubType: *AREA_GFA)\n"
                            f"AGF_DevelopmentUse: {dev_use}\n"
                            f"Controlled AGF_Name values ({len(batch)} items):\n"
                            + "\n".join(f"- {v}" for v in batch)
                        ),
                    }
        else:
            vals = [val for val, _ in entries]
            chunk_size = 60
            for part, batch in enumerate(_chunk(vals, chunk_size), 1):
                suffix = f" (part {part})" if len(vals) > chunk_size else ""
                slug = re.sub(r"[^a-zA-Z0-9]+", "-", f"{prop}-{part}").strip("-").lower()
                yield {
                    "id": f"SG-IFCSG-{rev}/space-values/{slug}",
                    "title": f"IFC+SG Space Values | {prop}{suffix}",
                    "source_sheet": "Space Values",
                    "ifc_entity": "IfcSpace",
                    "agencies": "All",
                    "discipline": "ARC",
                    "record_kind": "controlled vocabulary",
                    "source_url": url,
                    "text": (
                        f"Property: {prop} (IFC4 Entity: IfcSpace)\n"
                        f"Controlled values ({len(batch)} items):\n"
                        + "\n".join(f"- {v}" for v in batch)
                    ),
                }

    # 4. Industrial Activity Type Enum (SS593 Annex A)
    ind_rows = [
        (_norm_cell(r[0]), _norm_cell(r[1]))
        for r in list(wb["Industrial Activity Type Enum"].iter_rows(values_only=True))[1:]
        if _norm_cell(r[0]) or _norm_cell(r[1])
    ]
    for part, batch in enumerate(_chunk(ind_rows, 40), 1):
        yield {
            "id": f"SG-IFCSG-{rev}/industrial-enum/part-{part}",
            "title": f"IFC+SG Industrial Activity Type Enum | SS593 Annex A (part {part})",
            "source_sheet": "Industrial Activity Type Enum",
            "ifc_entity": "IfcSpace",
            "agencies": "NEA, SCDF, URA",
            "discipline": "ARC",
            "record_kind": "controlled vocabulary",
            "source_url": url,
            "text": (
                "Controlled Enum Values for Industrial Activity Type (SS593 Annex A):\n"
                + "\n".join(f"- {code}: {desc}" for desc, code in batch)
            ),
        }


def boundary(lines, marker):
    pattern = re.compile(r"^" + re.escape(marker) + r"(?=\s|$)")
    for index, line in enumerate(lines):
        if pattern.match(line):
            return index
    raise ValueError(f"Missing PDF text marker {marker!r}")


def select_passage(lines, spec):
    start = boundary(lines, spec["start"])
    selected = lines[start:]
    if "until" in spec:
        selected = selected[:1 + boundary(selected[1:], spec["until"])]
    if "item" in spec:
        # A lettered item inherits the parent sentence, including its trigger.
        first_item = boundary(selected, "(a)")
        selected_item = boundary(selected, f"({spec['item']})")
        following = selected[selected_item + 1:]
        end = next((i for i, line in enumerate(following) if re.match(r"^\([a-z]\)\s", line)), len(following))
        selected = selected[:first_item] + selected[selected_item:selected_item + 1 + end]
    passage = " ".join(selected)
    passage = re.sub(r"(?<=\w)- (?=[a-z])", "-", passage)
    for expected in spec["verify"]:
        if expected.casefold() not in passage.casefold():
            raise ValueError(f"{spec['ref']}, page {spec['page']}: missing {expected!r} in selected text")
    return passage


def record(reference, page, kind, text):
    edition = EDITION["edition"]
    version = EDITION["version"]
    return {
        "id": f"SG-BCA-COA{edition}-v{version}/{reference}",
        "title": f"BCA {edition} v{version} | {reference} | p. {page}",
        "code_ref": reference,
        "pdf_page": str(page),
        "record_kind": kind,
        "source_url": f"{EDITION['pdf']}#page={page}",
        "text": text,
    }


def records_for(reader, scope):
    if scope == "full":
        for page, source_page in enumerate(reader.pages, 1):
            text = (source_page.extract_text() or "").strip()
            if not text:
                text = "Image-only page. Open the source PDF for visual review."
            yield record(f"PDF page {page}", page, "source page with mixed content", text)
        return
    specs = json.loads((EVIDENCE / "pilot.json").read_text(encoding="utf-8"))
    pages = {}
    for spec in specs:
        page = spec["page"]
        if page not in pages:
            pages[page] = [" ".join(line.split()) for line in reader.pages[page - 1].extract_text().splitlines() if line.strip()]
        passage = select_passage(pages[page], spec)
        if "navigation" in spec:
            passage += "\n\nEditor's navigation note: " + spec["navigation"]
        yield record(spec["ref"], page, spec["kind"], passage)


SG_DOMAIN_CONTEXT = (
    'Domain context: These records come from Singapore building regulations. '
    '"BCA" always means Singapore\'s Building and Construction Authority '
    '(never Building Code of Australia). "SCDF" means the Singapore Civil Defence Force.\n\n'
)

IFCSG_DOMAIN_CONTEXT = (
    'Domain context: These records come from Singapore\'s CORENET X IFC+SG Industry Mapping File '
    '(CoP 3.1 Edition). "BCA" is Singapore\'s Building and Construction Authority (never Building Code of Australia), '
    '"SCDF" is Singapore Civil Defence Force, "URA" is Urban Redevelopment Authority, "PUB" is Singapore\'s National Water Agency, '
    '"NEA" is National Environment Agency, "LTA" is Land Transport Authority, and "NParks" is National Parks Board. '
    'Preserve exact IFC4 entity names (e.g., IfcSpace, IfcDoor, IfcSanitaryTerminal), exact *USERDEFINED subtypes '
    '(e.g., *WATERCLOSET, *VISUALALARM, *ACCESSIBLEROUTE), exact property set and property names '
    '(e.g., SGPset_Space.LargerAccessible, SGPset_DoorDimension.ClearWidth), data types, and controlled enum values.\n\n'
)


def initialize_engine(scope, provider="gemini"):
    root = ENGINE / scope
    if (root / "settings.yaml").is_file():
        return  # Preserve model, endpoint and prompt changes made by the user.
    executable = shutil.which("graphrag") or shutil.which("graphrag", path=str(Path(sys.executable).parent))
    if not executable:
        raise ValueError("Install requirements.txt with this Python interpreter, then rerun.")
    with TemporaryDirectory(dir=ENGINE) as scratch:
        staged = Path(scratch) / "engine"
        staged.mkdir()
        subprocess.run([executable, "init", "--root", str(staged), "--model", "gpt-4.1-mini",
                        "--embedding", "text-embedding-3-large"], check=True)
        config_file = staged / "settings.yaml"
        config = yaml.safe_load(config_file.read_text(encoding="utf-8"))
        if provider == "gemini":
            config["completion_models"]["default_completion_model"] = {
                "model_provider": "gemini",
                "model": "gemini-3.8-flash",
                "auth_method": "api_key",
                "api_key": "${GEMINI_API_KEY}",
                "retry": {
                    "type": "exponential_backoff",
                    "max_retries": 5,
                    "base_delay": 2.0,
                    "max_delay": 60.0,
                },
                "rate_limit": {
                    "type": "sliding_window",
                    "period_in_seconds": 60,
                    "requests_per_period": 120,
                },
            }
            config["embedding_models"]["default_embedding_model"] = {
                "model_provider": "gemini",
                "model": "gemini-embedding-2",
                "auth_method": "api_key",
                "api_key": "${GEMINI_API_KEY}",
                "retry": {
                    "type": "exponential_backoff",
                    "max_retries": 5,
                    "base_delay": 2.0,
                    "max_delay": 60.0,
                },
                "rate_limit": {
                    "type": "sliding_window",
                    "period_in_seconds": 60,
                    "requests_per_period": 300,
                },
            }
            (staged / ".env").write_text("GEMINI_API_KEY=<YOUR_GEMINI_API_KEY>\n", encoding="utf-8")
        config["input"] = {"type": "jsonl", "id_column": "id", "title_column": "title", "text_column": "text"}
        config["input_storage"]["base_dir"] = f"../../02_evidence/output/{scope}"
        if scope == "multicode":
            config["chunking"]["prepend_metadata"] = [
                "title", "authority", "source_locator", "record_kind", "applies_when"
            ]
        elif scope == "ifcsg":
            config["chunking"]["prepend_metadata"] = [
                "title", "source_sheet", "ifc_entity", "agencies", "discipline", "record_kind"
            ]
        elif scope == "scdf":
            config["chunking"]["prepend_metadata"] = [
                "title", "authority", "chapter", "code_ref", "pdf_page"
            ]
        else:
            config["chunking"]["prepend_metadata"] = ["title", "code_ref", "pdf_page", "record_kind"]

        if scope == "ifcsg":
            config["extract_graph"]["entity_types"] = [
                "agency", "discipline", "identified component", "ifc entity", "ifc subtype",
                "property set", "property", "enum value", "authoring representation", "space category",
            ]
        else:
            config["extract_graph"]["entity_types"] = [
                "clause", "building use", "space", "building element", "system",
                "component", "measurement", "condition", "table", "figure",
            ]

        if scope in {"full", "scdf"}:
            config.setdefault("extract_graph", {})["max_gleanings"] = 0
            config.setdefault("cluster_graph", {})["max_cluster_size"] = 25
        config.setdefault("cluster_graph", {})["use_lcc"] = False
        config_file.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

        domain_note = IFCSG_DOMAIN_CONTEXT if scope == "ifcsg" else SG_DOMAIN_CONTEXT
        prompt_file = staged / config["extract_graph"]["prompt"]
        original = prompt_file.read_text(encoding="utf-8")
        if scope == "ifcsg":
            guidance = (
                "Link each identified component to its IFC4 entity, IFC subtypes, governing agencies, "
                "disciplines, authoring tool representations, property sets, exact property names, "
                "data types/units, and controlled enum values.\n\n"
            )
        else:
            guidance = (
                "For regulatory material, preserve complete clause identifiers and subparagraph letters. "
                "Bind each measurement and unit to its object, scope and conditions. Retain mandatory "
                "or advisory wording. Treat captions and editorial navigation as source locators. "
                "Only describe a cross-reference as explicit when it occurs in the Code text.\n\n"
            )
        prompt_file.write_text(domain_note + guidance + original, encoding="utf-8")

        community_prompt = staged / config["community_reports"]["graph_prompt"]
        if community_prompt.is_file():
            community_prompt.write_text(
                domain_note + community_prompt.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        staged.rename(root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scope", choices=["pilot", "full", "multicode", "ifcsg", "scdf"])
    parser.add_argument("--pdf", type=Path, help="Use an already downloaded copy of the pinned BCA or SCDF PDF.")
    parser.add_argument("--xlsx", type=Path, help="Use an already downloaded copy of the pinned IFC+SG Excel file.")
    parser.add_argument(
        "--provider",
        choices=["gemini", "openai"],
        default="gemini",
        help="Default LLM/embedding provider written into newly initialized GraphRAG projects.",
    )
    args = parser.parse_args()
    if args.scope == "multicode":
        if args.pdf or args.xlsx:
            parser.error("--pdf and --xlsx are not used by the multicode scope.")
        rows = list(read_graph()[0].values())
    elif args.scope == "ifcsg":
        if args.pdf:
            parser.error("--pdf is used only by the pilot, full, and scdf PDF scopes.")
        wb, digest = open_ifcsg_workbook(args.xlsx)
        save(
            SOURCE / "output" / "ifcsg_check.md",
            f"pass\n\n{IFCSG_EDITION['filename']} ({IFCSG_EDITION['edition']}, {IFCSG_EDITION['revision_date']}). SHA-256 {digest}.\n".encode(),
        )
        rows = list(records_for_ifcsg(wb))
    elif args.scope == "scdf":
        if args.xlsx:
            parser.error("--xlsx is used only by the ifcsg scope.")
        reader, digest = open_scdf_edition(args.pdf)
        save(
            SOURCE / "output" / "scdf_check.md",
            f"pass\n\n{SCDF_EDITION['page_count']} PDF pages ({SCDF_EDITION['filename']}, {SCDF_EDITION['revision_date']}). SHA-256 {digest}.\n".encode(),
        )
        rows = list(records_for_scdf(reader))
    else:
        if args.xlsx:
            parser.error("--xlsx is used only by the ifcsg scope.")
        reader = open_edition(args.pdf)
        save(SOURCE / "output" / "check.md",
             f"pass\n\n{EDITION['page_count']} PDF pages. SHA-256 {EDITION['sha256']}.\n".encode())
        rows = list(records_for(reader, args.scope))
    if len({r["id"] for r in rows}) != len(rows) or not rows:
        raise ValueError("The corpus must have distinct source IDs and at least one record.")
    payload = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows).encode()
    output = EVIDENCE / "output" / args.scope
    save(output / "records.jsonl", payload)
    save(output / "check.md", f"pass\n\n{len(rows)} records. Input SHA-256 {sha256(payload).hexdigest()}.\n".encode())
    initialize_engine(args.scope, provider=args.provider)
    print(f"Prepared {len(rows)} records. GraphRAG project: 03_graphrag/{args.scope}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error)) from error
