# Singapore multi-code BIM review (ICM + GraphRAG + IFC+SG)

This workspace turns Singapore building codes and the official CORENET X IFC+SG Excel mapping into clause-cited BIM design checks. Read the [pipeline](CONTEXT.md) for the stage order and [README](README.md) for setup and commands.

| Task | Open |
|---|---|
| Verify source PDFs, Excel files, and SHA-256 hashes | [01 Source](01_source/CONTEXT.md) |
| Build JSONL inputs from PDFs, Excel, or curated tables | [02 Evidence](02_evidence/CONTEXT.md) |
| Run GraphRAG indexing, vector search, or Obsidian export | [03 GraphRAG](03_graphrag/CONTEXT.md) |
| Trace washroom or ramp rules across BCA and SCDF | [Multi-code review](04_review/multicode.md) |
| Check project drawings or BIM data against clauses | [04 Review](04_review/CONTEXT.md) |
| Map clauses to IFC+SG entities, `SGPset_*` properties, and BIM checks | [05 IFC+SG](05_ifcsg/CONTEXT.md) |
| Inspect worked example or run metrics | [Worked review](04_review/example.md) or [verification](04_review/verification.md) |

## Two-track indexing rule
- **Unstructured regulatory PDFs** (BCA Accessibility Code, future SCDF Fire Code / BCA Approved Document): extract pages with `_tools/prepare.py`, then index with `graphrag index` (`gemini-3.8-flash` + `gemini-embedding-2`, `cluster_graph.use_lcc: false`).
- **Structured Excel tables** (CORENET X IFC+SG mapping): compile directly to exact Parquet tables with `_tools/build_ifcsg_graph.py build --embed --match-bca` (do **not** burn chat LLM calls re-extracting structured columns).

Read the contract for the current stage and verify its check output before moving to the next stage.
