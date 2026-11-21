"""Follow explicit references within the reviewed pilot and list gaps for PDF review."""

import argparse
import json
from pathlib import Path
import re


RECORDS = Path(__file__).resolve().parents[1] / "02_evidence" / "output" / "pilot" / "records.jsonl"


def pilot_records():
    if not RECORDS.is_file():
        raise ValueError("Run python _tools/prepare.py pilot first.")
    return [json.loads(line) for line in RECORDS.read_text(encoding="utf-8").splitlines()]


def follow(records, seeds):
    by_ref = {r["code_ref"]: r for r in records}
    missing = set(seeds) - by_ref.keys()
    if missing:
        raise ValueError(f"Outside the pilot. Inspect the full PDF for: {', '.join(sorted(missing))}")
    queue = list(seeds)
    seen = set()
    lines = []
    while queue:
        ref = queue.pop(0)
        if ref in seen:
            continue
        seen.add(ref)
        row = by_ref[ref]
        if row["record_kind"] != "mandatory clause":
            continue
        source_text = row["text"].split("\n\nEditor's navigation note:", 1)[0]
        # The six selected clauses use singular 'clause' and 'Figure' citations.
        # Applying this grammar to the whole Code would require further review.
        for kind, number in re.findall(r"\b(clause|Figure)\s+(\d+(?:\.\d+)*(?:\([a-z]\))?)", source_text, re.I):
            target = f"Figure {number}" if kind.casefold() == "figure" else number
            matches = [key for key in by_ref if key == target or key.startswith((target + ".", target + "("))]
            if not matches:
                lines.append(f"{ref} cites {target} | outside pilot, open {row['source_url']} for context")
            for match in matches:
                lines.append(f"{ref} cites {target} | {match}, p. {by_ref[match]['pdf_page']}")
                if match not in seen:
                    queue.append(match)
    return lines


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("references", nargs="+", help="Pilot clause IDs, e.g. '5.2.2(d)'.")
    args = parser.parse_args()
    try:
        for result in follow(pilot_records(), args.references):
            print(result)
    except ValueError as error:
        parser.exit(1, f"{error}\n")
