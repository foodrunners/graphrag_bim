# Stage 01 — Verify regulatory sources

## Inputs
- **BCA Accessibility Code 2025 v1.1 (PDF):** pinned URL, page count (`116`), and SHA-256 in [edition.json](edition.json).
- **CORENET X IFC+SG Industry Mapping File (Excel, CoP 3.1 / 25 Sep 2026):** pinned URL, sheets, and SHA-256 in [ifcsg_edition.json](ifcsg_edition.json).
- **Multi-agency registry:** [sources.json](sources.json) tracks every active source across BCA, SCDF, and CORENET X (`source_id`, `document_id`, version, checked date, applicability rule).

## Process
- BCA PDF: `python _tools/prepare.py full` (or `pilot`, optionally `--pdf path/to/code.pdf`).
- CORENET X IFC+SG Excel: `python _tools/prepare.py ifcsg` (or `--xlsx path/to/file.xlsx`) and `python _tools/build_ifcsg_graph.py build`.
- For any project review, record building use, works type (new build vs. A&A), and first plan submission date before applying a code edition.

## Outputs (gitignored)
- `output/code.pdf` and `output/check.md`
- `output/ifcsg_industry_mapping_09_2026.xlsx` and `output/ifcsg_check.md`

## Check
Both loaders verify exact SHA-256 hashes before processing. If an agency publishes a newer revision, inspect its Amendment History or Change Log before updating the pinned JSON files.
