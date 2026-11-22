# Singapore multi-code BIM review (ICM + GraphRAG + IFC+SG)

This workspace turns Singapore building codes and the CORENET X IFC+SG Excel mapping into clause-cited BIM design checks. Read the [pipeline](CONTEXT.md) for the stage order and [README](README.md) for setup and commands.

| Task | Open |
|---|---|
| Verify source PDFs, Excel files, and SHA-256 hashes | [01 Source](01_source/CONTEXT.md) |
| Build JSONL records from PDFs, Excel, or curated tables | [02 Evidence](02_evidence/CONTEXT.md) |
| Build graph & vectors (choose Track A or Track B) + Obsidian export | [03 GraphRAG](03_graphrag/CONTEXT.md) |
| Trace washroom or ramp rules across BCA and SCDF | [Multi-code review](04_review/multicode.md) |
| Check project drawings or BIM data against clauses | [04 Review](04_review/CONTEXT.md) |
| Map clauses to IFC+SG entities, `SGPset_*` properties, and BIM checks | [05 IFC+SG](05_ifcsg/CONTEXT.md) |
| Inspect worked example, metrics, or next steps | [Worked review](04_review/example.md) · [verification](04_review/verification.md) · [ROADMAP](ROADMAP.md) |

## Stage 03 Build Rule — Choose Your Track Before Indexing Any New Source
Both tracks write the **same Parquet + LanceDB output contract** (`entities.parquet`, `relationships.parquet`, `lancedb/entity_description.lance`) so `ui_app.py`, `export_obsidian.py`, and Stage 05 IFC+SG cross-matching work identically:

- **Track A — Microsoft GraphRAG (`graphrag index`):** Calls `gemini-3.8-flash` + `gemini-embedding-2` (with `max_gleanings: 0`, `max_cluster_size: 25`, `use_lcc: false`). Use when you specifically want Microsoft's `graphrag query --method local|global` CLI and automated community reports on unstructured PDFs.
- **Track B — Local / Antigravity Builder + `gemini-embedding-2`:** Builds `entities.parquet` & `relationships.parquet` with Python parsers + Antigravity review (zero chat-API calls), then runs `gemini-embedding-2` only (`~$0.01–$0.50` per source). Default for structured Excel/CSV files and cost-sensitive numbered code PDFs.

Always ask the user which track (Track A or Track B) they want before indexing a new regulatory document. Read the contract for the current stage and verify its check output before moving on.
