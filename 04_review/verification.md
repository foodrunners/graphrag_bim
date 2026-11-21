# Results from the BCA source

Run on 20 November 2026 using Python 3.12 and Microsoft GraphRAG 3.3.0. The loader matched BCA's 116-page PDF to the [pinned SHA-256 fingerprint](../01_source/edition.json).

| Scope tested | Documents | Text units | Noun-phrase nodes | Co-occurrence edges |
|---|---:|---:|---:|---:|
| Selected clauses and supporting records | 9 | 9 | 46 | 216 |
| Whole PDF, one record per page | 116 | 116 | 1,310 | 34,848 |

The graph preview used Microsoft's input, chunking and noun-phrase extraction workflows. Each document produced a traceable text unit, each unit carried a page number, and all relationship text-unit IDs resolved. The node and edge counts describe co-occurring phrases.

## Retrieval test

For the term `alarm`, the pilot ranked §5.8.4.3 (p. 81), §5.2.2(d) (p. 63) and §5.8.4.1 (p. 81). Following the explicit citation from §5.2.2(d) to §5.8.4 added §5.8.4.2. That provision supplies the mounting-height, contrast and sign requirements. The full-page preview ranked pages 81, 63 and 85.

Starting separately at §5.1.3(d) reached the selected room-size and alarm provisions through §5.2. The trace also identified Figure 44 on page 65 and flagged Figure 43 as outside the pilot. Inspect adjoining provisions in the full PDF when the design question extends beyond this slice.

## Model-backed search

The standard model configuration and CLI syntax were checked locally. Execution here covered the local graph and clause tracing. Running the generative index, embeddings and natural-language query requires configured model endpoints. The [worked review](example.md) uses verified source pages and synthetic project evidence.
