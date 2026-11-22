# Pipeline: from code files to BIM compliance review

The unit of work is a design question for a stated building use, location, and plan submission date. Code editions and the CORENET X IFC+SG mapping are shared across projects; each project review records its own measurements and open items.

| Stage | Track | Handoff |
|---|---|---|
| [01 Source](01_source/CONTEXT.md) | PDFs + Excel | Verified source files and SHA-256 hashes (`edition.json`, `ifcsg_edition.json`, `sources.json`) |
| [02 Evidence](02_evidence/CONTEXT.md) | PDFs + Curated | Searchable JSONL records with exact page/clause locators |
| [03 GraphRAG](03_graphrag/CONTEXT.md) | Unstructured PDFs / Deterministic Excel | Indexed Parquet graphs (`full`, `multicode`, `ifcsg`), `gemini-embedding-2` LanceDB vectors, and Obsidian graph exports |
| [04 Review](04_review/CONTEXT.md) | Design review | Clause-cited pass/fail/open findings tied to project drawings or IFC `GlobalId`s |
| [05 IFC+SG](05_ifcsg/CONTEXT.md) | BIM bridge | Verified CORENET X `Ifc*` entities, `*USERDEFINED` subtypes, `SGPset_*` properties, auto-matched BCA links, and `IfcOpenShell` inspection hooks |

## Key engineering rules
1. **Use LLMs only for prose PDFs.** Structured Excel tables (like CORENET X IFC+SG) are parsed deterministically into exact Parquet tables, then embedded with `gemini-embedding-2` so both graphs share the same 3,072-dim vector space.
2. **Keep `cluster_graph.use_lcc: false`** in GraphRAG `settings.yaml` so disconnected chapters/topics (e.g., washrooms vs. ramps) are never dropped from communities or local search.
3. **Always verify source pages & measurements.** Vector matches and LLM answers are starting points — confirm exact clause wording, tables, figures, and `SGPset_*` definitions before issuing a project finding.
