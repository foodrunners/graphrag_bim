# Roadmap & Next Steps

Current branch: `feat/ifcsg-semantic-layer` (GitHub: `https://github.com/foodrunners/graphrag_bim`)

## Done
- [x] **BCA Code on Accessibility 2025 v1.1 (116 pages)** indexed with `gemini-3.8-flash` + `gemini-embedding-2` (`2,807` entities, `4,277` relationships, `767` communities, `cluster_graph.use_lcc: false`).
- [x] **Multi-code starter (`multicode`)** indexed across BCA Accessibility Code, SCDF Fire Code 2023, and BCA Approved Document V7.08.
- [x] **Full CORENET X IFC+SG (Sep 2026, CoP 3.1)** compiled deterministically from `industry-mapping-09-2026.xlsx` across all 7 agencies (`BCA`, `SCDF`, `URA`, `PUB`, `NEA`, `LTA`, `NParks`) — `277` graph nodes, `751` links, `1,112` exact parameters, `1,405` Space Values, `155` SS593 enums — embedded with `gemini-embedding-2` and cross-matched to BCA (`2,738` ranked matches).
- [x] **SCDF Fire Code 2023 (7 Jul 2026 consolidated PDF, 540 pages)** pinned (`01_source/scdf_edition.json`), extracted to `02_evidence/output/scdf/records.jsonl`, initialized for GraphRAG (`03_graphrag/scdf/`), and wired live into the local workbench UI (`http://127.0.0.1:8000`).
- [x] **Obsidian Graph View export** (`_tools/export_obsidian.py`) + color-coded `.obsidian/graph.json`.
- [x] **Portable index backup zip** (`sg_bim_graphrag_output_2026.zip`, `50.89 MB`, zero `.env`/cache) ready for Google Drive.
- [x] **Local Search UI Workbench** (`_tools/ui_app.py` at `http://127.0.0.1:8000`) showing BCA Design Requirements + SCDF Fire Code (540p) alongside CORENET X IFC+SG Model Requirements.

## Large-PDF Cost Settings (Remember for Future PDFs)
- In `03_graphrag/<scope>/settings.yaml` (now automatic in `_tools/prepare.py` for `full` and `scdf`):
  - `extract_graph.max_gleanings: 0` (single extraction pass per chunk instead of re-reading every chunk twice)
  - `cluster_graph.max_cluster_size: 25` (fewer, larger topic clusters → ~60% fewer community reports; all entities/links stay 100% intact)
  - `cluster_graph.use_lcc: false` (keeps all disconnected chapters searchable)

## Next Steps (In Order)
1. **Test the updated local UI (`http://127.0.0.1:8000`)**
   - Search `toilet`, `ramp`, `door`, `lift`, `alarm`, `staircase`, `refuse` and check the new **SCDF Fire Code (540p)** tab alongside BCA COA 2025 v1.1 and CORENET X IFC+SG.
2. **Optional — GraphRAG LLM indexing of SCDF Fire Code (`03_graphrag/scdf`)**
   - Once Gemini AI Studio credits are topped up, run `graphrag index --root 03_graphrag/scdf` (either full 540 pages or selected key chapters like Ch. 2 Means of Escape & Ch. 6 Firefighting Systems) and cross-match to IFC+SG.
3. **Add BCA Approved Document V7.08 PDF & expand `05_ifcsg/bridge.json`**
   - Ingest BCA Approved Document V7.08 (Staircases, Lighting, Ventilation, Safety from Falling) and add verified checks for lifts, doors, staircases, corridors, and parking lots.
4. **Merge `feat/ifcsg-semantic-layer` → `main` on GitHub** and refresh Google Drive zip once SCDF/Approved Doc indexes are built.
5. **Live `.ifc` model checking (`IfcOpenShell`)**
   - Obtain a sample CORENET X `.ifc` model, install `ifcopenshell`, and wire `inspect-ifc` into Stage 05 → Stage 04 (and the local UI) to run real `GlobalId` pass/fail checks.
