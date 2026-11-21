# Prepare traceable records

## Inputs

The source stage supplies `../01_source/output/code.pdf`. The pilot selectors and verification tokens are in [pilot.json](pilot.json).

For the multi-code scope, [multicode.json](multicode.json) contains the selected source summaries, applicability and locators. [links.csv](links.csv) records the source node, relation, target, basis and supporting clause for each link. `python _tools/prepare.py multicode` validates those endpoints and builds the combined JSONL input.

## Process

The preparation command reads each selected passage with its parent condition. It labels source text, editorial navigation, table rows, figure locators and edition history. The full scope reads all physical pages and labels each page as mixed content. Each JSONL row has a stable ID, a BCA locator, a PDF page, a source URL and its text.

## Outputs

`output/pilot/records.jsonl` or `output/full/records.jsonl`, alongside a `check.md`. The matching GraphRAG project reads this file directly.

## Check

The loader checks that IDs are distinct and expected pilot wording survives extraction. To add a table row or figure, inspect its layout and legend on the source page, then add its selector. Keep each condition and unit with the requirement that uses it.
