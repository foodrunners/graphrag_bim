# Verify the Code edition

## Inputs

The edition, official download address, commencement circular and expected fingerprint are in [edition.json](edition.json). The optional working input is an existing local copy of that PDF.

The multi-code scope reads [sources.json](sources.json). Each source has an authority, document ID, version, checked date and applicability notes. A null commencement date requires resolving the current provision and relevant circular for the project. The checked date records when the content was reviewed.

## Process

From the workspace root, run `python _tools/prepare.py pilot` or `python _tools/prepare.py full`. One command performs the source and evidence stages in order. For a project review, record the building use, works type and date the first plans were submitted or were required.

## Outputs

`output/code.pdf` and `output/check.md`.

## Check

The loader verifies the byte fingerprint and page count before publishing the source. A different edition calls for checking the amendment history and the locators used by this workspace.
