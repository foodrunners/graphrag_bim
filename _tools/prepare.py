"""Prepare the pinned BCA PDF as a private JSONL input to Microsoft GraphRAG."""

import argparse
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
            pages[page] = [" ".join(line.split()) for line in reader.pages[page-1].extract_text().splitlines() if line.strip()]
        passage = select_passage(pages[page], spec)
        if "navigation" in spec:
            passage += "\n\nEditor's navigation note: " + spec["navigation"]
        yield record(spec["ref"], page, spec["kind"], passage)


SG_DOMAIN_CONTEXT = (
    'Domain context: These records come from Singapore building regulations. '
    '"BCA" always means Singapore\'s Building and Construction Authority '
    '(never Building Code of Australia). "SCDF" means the Singapore Civil Defence Force.\n\n'
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
        config["chunking"]["prepend_metadata"] = ["title", "code_ref", "pdf_page", "record_kind"]
        if scope == "multicode":
            config["chunking"]["prepend_metadata"] = [
                "title", "authority", "source_locator", "record_kind", "applies_when"
            ]
        config["extract_graph"]["entity_types"] = [
            "clause", "building use", "space", "building element", "system",
            "component", "measurement", "condition", "table", "figure",
        ]
        config.setdefault("cluster_graph", {})["use_lcc"] = False
        config_file.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        prompt_file = staged / config["extract_graph"]["prompt"]
        original = prompt_file.read_text(encoding="utf-8")
        prompt_file.write_text(
            SG_DOMAIN_CONTEXT
            + "For regulatory material, preserve complete clause identifiers and subparagraph letters. "
            "Bind each measurement and unit to its object, scope and conditions. Retain mandatory "
            "or advisory wording. Treat captions and editorial navigation as source locators. "
            "Only describe a cross-reference as explicit when it occurs in the Code text.\n\n" + original,
            encoding="utf-8",
        )
        community_prompt = staged / config["community_reports"]["graph_prompt"]
        if community_prompt.is_file():
            community_prompt.write_text(
                SG_DOMAIN_CONTEXT + community_prompt.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        staged.rename(root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scope", choices=["pilot", "full", "multicode"])
    parser.add_argument("--pdf", type=Path, help="Use an already downloaded copy of the pinned BCA PDF.")
    parser.add_argument(
        "--provider",
        choices=["gemini", "openai"],
        default="gemini",
        help="Default LLM/embedding provider written into newly initialized GraphRAG projects.",
    )
    args = parser.parse_args()
    if args.scope == "multicode":
        if args.pdf:
            parser.error("--pdf is used only by the pilot and full BCA PDF scopes.")
        rows = list(read_graph()[0].values())
    else:
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
