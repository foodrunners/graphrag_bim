# Roadmap & Next Steps

Current branch: `feat/ifcsg-semantic-layer` (GitHub: `https://github.com/foodrunners/graphrag_bim`)

## Done
- [x] **BCA Code on Accessibility 2025 v1.1 (116 pages)** indexed with `gemini-3.8-flash` + `gemini-embedding-2` (`2,807` entities, `4,277` relationships, `767` communities, `cluster_graph.use_lcc: false`).
- [x] **Multi-code starter (`multicode`)** indexed across BCA Accessibility Code, SCDF Fire Code 2023, and BCA Approved Document V7.08.
- [x] **Full CORENET X IFC+SG (Sep 2026, CoP 3.1)** compiled deterministically from `industry-mapping-09-2026.xlsx` across all 7 agencies (`BCA`, `SCDF`, `URA`, `PUB`, `NEA`, `LTA`, `NParks`) — `277` graph nodes, `751` links, `1,112` exact parameters, `1,405` Space Values, `155` SS593 enums — embedded with `gemini-embedding-2` and cross-matched to BCA (`2,738` ranked matches).
- [x] **Obsidian Graph View export** (`_tools/export_obsidian.py`) + color-coded `.obsidian/graph.json`.
- [x] **Portable index backup zip** (`sg_bim_graphrag_output_2026.zip`, `50.89 MB`, zero `.env`/cache) ready for Google Drive.
- [x] **Local Search UI Workbench** (`_tools/ui_app.py` at `http://localhost:8000`) showing Design Requirements alongside IFC+SG Model Requirements.

## Next Steps (In Order)
1. **Test the local UI (`http://localhost:8000`)**
   - Search `toilet`, `ramp`, `door`, `lift`, `alarm`, `railing`, `parking`, `refuse` and verify both sides: BCA design clauses/dimensions AND CORENET X IFC+SG entities/subtypes/`SGPset_*` parameters across agencies.
   - Note any missing synonyms, UI tweaks, or extra bridge checks to promote into `05_ifcsg/bridge.json`.
2. **Merge & sync GitHub**
   - Commit `_tools/ui_app.py` + `ROADMAP.md` to `feat/ifcsg-semantic-layer`, push, and merge PR into `main` on `foodrunners/graphrag_bim`.
   - Upload `sg_bim_graphrag_output_2026.zip` to Google Drive for use on other computers.
3. **Add SCDF Fire Code 2023 (live HTML chapters)**
   - Build `_tools/fetch_scdf.py` to pull live SCDF Fire Code 2023 HTML chapters (starting with Chapter 2 Means of Escape & Chapter 6 Firefighting Systems) into per-clause JSONL with live URLs.
   - Top up Gemini AI Studio prepayment credits, then run `graphrag index --root 03_graphrag/scdf` and cross-match against the existing CORENET X IFC+SG vectors.
   - Repeat later for BCA Approved Document, URA GFA Handbook, PUB COP, and NEA COPEH.
4. **Live `.ifc` BIM checking (`IfcOpenShell`)**
   - Obtain a sample CORENET X `.ifc` model, install `ifcopenshell`, and wire `inspect-ifc` into Stage 05 → Stage 04 (and the local UI) to run real `GlobalId` pass/fail checks.
