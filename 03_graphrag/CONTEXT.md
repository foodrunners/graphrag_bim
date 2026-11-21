# Retrieve evidence using GraphRAG

## Inputs

Use `../02_evidence/output/pilot/records.jsonl` or `../02_evidence/output/full/records.jsonl` for the matching project. Its generated `settings.yaml` carries the model selection, regulatory entity types and input path.

The multi-code project reads `../02_evidence/output/multicode/records.jsonl`. Use `python _tools/preview.py multicode --find alarm` for noun-phrase retrieval with reviewed link expansion. For direct clause tracing, use `python _tools/multicode.py washroom` or `python _tools/multicode.py ramp`.

## Process

1. Run the [local graph preview or model-backed query](../README.md) for the selected scope.
2. Record the BCA identifiers and pages returned. For the pilot, run `python _tools/clause_trace.py '5.1.3(d)'` with the actual seed IDs. It expands explicit clause and figure references against available pilot records. Follow any remaining references in the official PDF.
3. Save the identifiers with the review question. Proposed relationships from the model and noun-phrase co-occurrences are leads for the page check.

## Outputs

`pilot/preview/check.md` or `full/preview/check.md` holds preview findings. The model index writes to that scope's `output/`. Capture the model's answer as a candidate for [04 Review](../04_review/CONTEXT.md).

## Check

The preview verifies that every source has a text unit, every text unit carries its page and every graph edge resolves to known text units. For a model answer, a reviewer opens the cited pages and resolves its explicit cross-references.
