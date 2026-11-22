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

## Stage 03 Indexing Options (Choose Track A or Track B for Each New Code)
- **Track A — Microsoft GraphRAG (`graphrag index`):** Uses `gemini-3.8-flash` + `gemini-embedding-2` with `max_gleanings: 0`, `max_cluster_size: 25`, `use_lcc: false` (already default in `_tools/prepare.py`). Best when you want Microsoft's `graphrag query --method local|global` CLI and community reports.
- **Track B — Local / Antigravity Builder + `gemini-embedding-2`:** Uses Python parsers + Antigravity review to build the exact same `entities.parquet` & `relationships.parquet` locally (zero chat-API cost), then calls Google's API only for `gemini-embedding-2` (`~$0.01–$0.50`). Mandatory for structured Excel files and available as a low-cost option for future numbered PDFs (BCA Approved Document V7.08, URA, PUB, NEA).

## Next Steps (In Order — Starting on Laptop #2)
1. **Interactive Knowledge Graph Explorer UI (inside `_tools/ui_app.py`)**
   - Add a **Force-Directed Graph Visualization** tab (clean Obsidian-style nodes-and-edges map filtered to the active search query — color-coded by BCA / SCDF / CORENET X IFC+SG, clickable nodes, zoom/pan, and **Export PNG** for slides & promos) + an in-app Q&A search bar so you don't need the coding chat window to search.
2. **Merge `feat/ifcsg-semantic-layer` → `main` on GitHub** (`https://github.com/foodrunners/graphrag_bim`).
3. **Add BCA Approved Document V7.08 PDF using Track B** (Local/Antigravity builder + `gemini-embedding-2` for `~$0.20`) and expand `05_ifcsg/bridge.json` verified checks.
4. **Live `.ifc` model checking (`IfcOpenShell`)**
   - Load a sample CORENET X `.ifc` model into Stage 05 → Stage 04 and the browser UI to run real `GlobalId` pass/fail checks.

## Laptop #2 Quick Setup Checklist
1. `git clone -b feat/ifcsg-semantic-layer https://github.com/foodrunners/graphrag_bim.git`
2. `cd graphrag_bim` → `py -3.12 -m venv .venv` → `.\.venv\Scripts\activate` → `python -m pip install -r requirements.txt`
3. Download both zips from Google Drive into the repo root and unzip in place:
   - `sg_bim_graphrag_output_2026.zip` (`full`, `multicode`, `ifcsg` outputs + cross-match CSVs + SCDF JSONL)
   - `sg_scdf2023_graphrag_output_2026.zip` (`scdf` 540-page output)
4. Run `python _tools/ui_app.py` → open `http://127.0.0.1:8000` (works immediately for `$0`, offline!).
5. Optional: run `python _tools/prepare.py full`, `multicode`, `ifcsg`, `scdf` (only needed if you want local PDFs/Excel + `settings.yaml` to run `graphrag query`), then add `GEMINI_API_KEY` into `.env`.
6. Optional: run `python _tools/export_obsidian.py --scope all` to regenerate Obsidian Graph View notes on Laptop #2.
