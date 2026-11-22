# Pipeline: from code files to BIM compliance review

The unit of work is a design question for a stated building use, location, and plan submission date. Code editions and the CORENET X IFC+SG mapping are shared across projects; each project review records its own measurements and open items.

| Stage | Handoff |
|---|---|
| [01 Source](01_source/CONTEXT.md) | Verified source files and SHA-256 hashes (`edition.json`, `scdf_edition.json`, `ifcsg_edition.json`, `sources.json`) |
| [02 Evidence](02_evidence/CONTEXT.md) | JSONL records with exact page/clause locators |
| [03 GraphRAG](03_graphrag/CONTEXT.md) | Standardized Parquet graph (`entities.parquet`, `relationships.parquet`) + `3,072`-dim `gemini-embedding-2` LanceDB vectors (built via **Track A** or **Track B**) + Obsidian export |
| [04 Review](04_review/CONTEXT.md) | Clause-cited pass/fail/open findings tied to project drawings or IFC `GlobalId`s |
| [05 IFC+SG](05_ifcsg/CONTEXT.md) | Verified CORENET X `Ifc*` entities, `*USERDEFINED` subtypes, `SGPset_*` properties, cross-matched code links, and `IfcOpenShell` inspection hooks |

## Stage 03 Output Contract (Why Both Tracks Plug In Cleanly)
Every scope under `03_graphrag/<scope>/output/` exposes the same core files:
- `entities.parquet` (`id`, `human_readable_id`, `title`, `type`, `description`, `text_unit_ids`, `frequency`, `degree`)
- `relationships.parquet` (`id`, `human_readable_id`, `source`, `target`, `description`, `weight`, `combined_degree`, `text_unit_ids`)
- `lancedb/entity_description.lance` (`3,072`-dim normalized `gemini-embedding-2` vectors)

Because both **Track A** (Microsoft `graphrag index`) and **Track B** (Local Python / Antigravity builder + `gemini-embedding-2`) write that exact contract, `_tools/ui_app.py`, `_tools/export_obsidian.py`, and Stage 05 vector cross-matching work identically on both.

## Key engineering rules
1. **Pick Track A or Track B explicitly** before indexing any new source (never run Track A on structured Excel tables).
2. **Keep `cluster_graph.use_lcc: false`** in Track A `settings.yaml` so disconnected chapters/topics are never dropped, and use `max_gleanings: 0` + `max_cluster_size: 25` on large PDFs to keep API costs controlled.
3. **Always verify source pages & measurements.** Vector matches and LLM answers are starting points — confirm exact clause wording, tables, figures, and `SGPset_*` definitions before issuing a project finding.
