# Stage 03 — GraphRAG indexing, vector search, and Obsidian export

## Scopes

| Scope | Source type | How it is built | Output tables |
|---|---|---|---|
| `full` | Unstructured 116-page BCA PDF | `graphrag index --root 03_graphrag/full` (`gemini-3.8-flash` + `gemini-embedding-2`, `use_lcc: false`) | `2,807` entities, `4,277` links, `767` communities + LanceDB vectors |
| `multicode` | Curated BCA + SCDF + Approved Doc | `graphrag index --root 03_graphrag/multicode` + `_tools/multicode.py` | `74` entities, `95` links, `18` communities + LanceDB vectors |
| `ifcsg` | Structured CORENET X Excel (all 7 agencies) | `python _tools/build_ifcsg_graph.py build --embed --match-bca` (exact Python build + `gemini-embedding-2`) | `277` entities, `751` links, `1,112` parameters, `1,405` space values, `155` SS593 enums + LanceDB vectors |

## Commands
- **Natural-language Q&A on indexed PDFs:**
  `graphrag query --root 03_graphrag/full --method local "<question>"`
- **Offline exact lookup on IFC+SG (`$0`, no API calls):**
  `python _tools/build_ifcsg_graph.py find "washroom alarm door"`
- **Semantic vector search on IFC+SG (uses `gemini-embedding-2`):**
  `python _tools/build_ifcsg_graph.py search "refuse chute drainage NEA PUB"`
- **Export graphs to Obsidian Graph View:**
  `python _tools/export_obsidian.py --scope all` (or `--scope full --filter washroom`)

## Portable backup across machines
`03_graphrag/{full,multicode,ifcsg}/` is gitignored so API keys (`.env`) and large caches stay off GitHub. To carry your compiled indexes to another machine without re-indexing, zip ONLY the `output/` folders (`03_graphrag/{full,multicode,ifcsg}/output/`) — never `.env` or `cache/`.

## Check
Verify `entities.parquet`, `relationships.parquet`, and `lancedb/entity_description.lance` exist and match expected counts, and verify cited clauses against the source PDF/Excel before using them in [04 Review](../04_review/CONTEXT.md).
