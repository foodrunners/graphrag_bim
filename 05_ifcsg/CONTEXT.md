# Stage 05 — IFC+SG BIM bridge (CORENET X CoP 3.1)

## Purpose
Connect Singapore regulatory clauses (BCA Accessibility Code 2025 v1.1, SCDF Fire Code 2023, BCA Approved Document V7.08, and future agency codes) to the full official **CORENET X IFC+SG** mapping across all 7 agencies (`BCA`, `SCDF`, `URA`, `PUB`, `NEA`, `LTA`, `NParks`).

## Inputs
- Official CORENET X Excel workbook pinned in [01_source/ifcsg_edition.json](../01_source/ifcsg_edition.json) (`industry-mapping-09-2026.xlsx`, 25 Sep 2026).
- Deterministic IFC+SG Parquet tables & `gemini-embedding-2` vectors in `03_graphrag/ifcsg/output/`.
- Indexed 116-page BCA GraphRAG entities & vectors in `03_graphrag/full/output/`.
- Verified clause-to-BIM check rules in [bridge.json](bridge.json).

## Process
1. **Build & embed the full multi-agency IFC+SG graph:**
   `python _tools/build_ifcsg_graph.py build --embed --match-bca`
   Produces exact `entities.parquet`, `relationships.parquet`, `parameters.parquet` (`1,112` rows), `space_values.parquet` (`1,405` rows), `industrial_enums.parquet` (`155` rows), LanceDB vectors, and `output/bca_to_ifcsg_matches.csv` (`2,738` ranked BCA → IFC+SG candidate links).
2. **Validate the verified bridge rules:**
   `python _tools/ifcsg_bridge.py validate`
3. **Query offline or semantically:**
   - Offline exact search (`$0`): `python _tools/build_ifcsg_graph.py find "water closet"`
   - Vector search (`gemini-embedding-2`): `python _tools/build_ifcsg_graph.py search "wheelchair ramp gradient"`
   - Topic / IFC entity checklists: `python _tools/ifcsg_bridge.py checklist washroom` · `python _tools/ifcsg_bridge.py entity IfcSpace`
4. **Inspect a real `.ifc` file** *(when available; requires `pip install ifcopenshell`)*:
   `python _tools/ifcsg_bridge.py inspect-ifc path/to/model.ifc --topic washroom`

## Evaluation method discipline
Every check in [bridge.json](bridge.json) declares how it is verified:
- `property_lookup`: directly readable from an IFC attribute or verified `SGPset_*` / `Pset_*` parameter.
- `geometry_clearance`: requires deterministic 3D/2D measurement from IFC solids/placements (`IfcSpace` area alone is not enough for unobstructed clear zones).
- `submittal_or_drawing`: cannot be proven from IFC geometry alone (e.g. colour contrast, signage artwork, FCC wiring diagram) and stays open until checked against submittals.

## Outputs (gitignored)
- `output/check.md` (bridge validation)
- `output/bca_to_ifcsg_matches.csv` (ranked vector matches from BCA 116-page entities to CORENET X IFC+SG)

## Check
`python _tools/ifcsg_bridge.py validate` prints `pass` with zero errors and `python -m unittest discover -s tests` passes.
