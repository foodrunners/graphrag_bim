# Stage 03 — GraphRAG indexing, vector search, and Obsidian export

## Two Build Tracks (Same Output Contract)

Before indexing any new code or mapping file, choose which track to run:

| Track | How `entities.parquet` & `relationships.parquet` are built | Embeddings (`lancedb/`) | Typical cost | When to choose |
|---|---|---|---|---|
| **Track A — Microsoft GraphRAG** (`graphrag index`) | External chat API (`gemini-3.8-flash`) extracts entities, merges descriptions, and writes community reports (`max_gleanings: 0`, `max_cluster_size: 25`, `use_lcc: false`). | `gemini-embedding-2` via GraphRAG | `~$10–$25` per 100–500p PDF (with cost settings) | Unstructured PDFs where you specifically want Microsoft's `graphrag query --method local\|global` CLI and cluster summary reports. |
| **Track B — Local / Antigravity Builder** (Python + Antigravity) | Python parser + Antigravity review build exact `entities.parquet` and `relationships.parquet` locally (zero chat-API calls). | `gemini-embedding-2` via Google API (`litellm`) | `~$0.01–$0.50` per source | Structured Excel/CSV schemas (mandatory) **and** numbered regulatory PDFs when you want exact clause trees with ~98% lower API cost. |

Both tracks write the exact same Parquet + LanceDB schema under `03_graphrag/<scope>/output/`, so `_tools/ui_app.py`, `_tools/export_obsidian.py`, and Stage 05 cross-matching work identically on every scope.

## Built Scopes

| Scope | Track Used | Source | Output Size / Counts |
|---|---|---|---|
| `full` | Track A | BCA Accessibility Code 2025 v1.1 (116p PDF) | `2,807` entities, `4,277` links, `767` reports + LanceDB (`~$11.35`) |
| `scdf` | Track A | SCDF Fire Code 2023 (540p PDF, 7 Jul 2026) | `13,727` entities, `20,214` links, `1,937` reports + LanceDB (`~$43.63`) |
| `multicode` | Track A | Curated BCA + SCDF + Approved Doc (11 records) | `74` entities, `95` links, `18` reports + LanceDB |
| `ifcsg` | Track B | CORENET X IFC+SG Excel (25 Sep 2026, all 7 agencies) | `277` entities, `751` links, `1,112` parameters, `1,405` space values, `155` SS593 enums + LanceDB (`<$0.05`) |

## Commands
- **Track A indexing + live ASCII monitor:**
  `graphrag index --root 03_graphrag/<scope>`
  `python _tools/watch_index.py <scope>`
- **Track A natural-language Q&A:**
  `graphrag query --root 03_graphrag/<scope> --method local "<question>"`
- **Track B build + embed + cross-match:**
  `python _tools/build_ifcsg_graph.py build --embed --match-bca`
  `python _tools/build_ifcsg_graph.py match-scdf`
- **Local browser UI (BCA + SCDF + IFC+SG side by side, `$0`):**
  `python _tools/ui_app.py --host 127.0.0.1 --port 8000`
- **Export graphs to Obsidian Graph View:**
  `python _tools/export_obsidian.py --scope all` · `python _tools/export_obsidian.py --scope scdf --min-degree 8`

## Portable backup across machines
`03_graphrag/{full,multicode,ifcsg,scdf}/` is gitignored so `.env` keys and large caches stay off GitHub. Back up only the `output/` folders as clean zips (`sg_bim_graphrag_output_2026.zip` + `sg_scdf2023_graphrag_output_2026.zip`, never `.env` or `cache/`).

## Check
Verify `entities.parquet`, `relationships.parquet`, and `lancedb/entity_description.lance` exist with non-zero rows, then verify cited clauses against source PDFs/Excel before recording findings in [04 Review](../04_review/CONTEXT.md).
