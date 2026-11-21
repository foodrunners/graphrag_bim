# Singapore multi-code BIM review with ICM and GraphRAG

Start with the [architecture diagram](architecture/SG_MultiCode_Architecture.svg). The multi-code scope brings together selected provisions from the BCA Accessibility Code, SCDF Fire Code and BCA Approved Document. It contains 11 source-linked summaries and 15 typed relationships. The BCA page index and the earlier washroom pilot are also available.

## Try the two cross-code questions

Unzip the workspace and run these commands from its root. The clause traces use standard Python and require no model credentials.

```bash
python _tools/multicode.py washroom
python _tools/multicode.py ramp
python -m unittest discover -s tests
```

To run Microsoft GraphRAG over the same records, use a Python 3.12 virtual environment.

```bash
python -m pip install -r requirements.txt
python _tools/prepare.py multicode
python _tools/preview.py multicode --find alarm
```

The preview finds source records through noun-phrase co-occurrence and expands matching topics using the reviewed links. To run model-backed search, configure the completion and embedding endpoints in `03_graphrag/multicode`, run `graphrag index --root 03_graphrag/multicode`, then query that root with `--method local`. The standard Microsoft query uses its own index. Attach the matching output from `multicode.py` when preparing a source-checked answer with the ICM review step.

Open the [cross-code findings and expansion guide](04_review/multicode.md) for the two design examples, the input schema and the next source to add.

## Existing BCA scopes

Use this workspace to answer a design question with a chain of BCA clauses, the relevant PDF pages and the project evidence a reviewer still needs. Open [the worked washroom review](04_review/example.md) to see the result before installing anything.

The input is Singapore BCA's *Code on Accessibility in the Built Environment 2025*, version 1.1, dated 1 March 2026. BCA identifies the additions to §5.1.3 and the alarm terminology in §5.2.2 as editorial amendments. The commencement circular uses the date the first set of plans was submitted or would have been required. Its threshold is 1 November 2025. [Official PDF and revision history](https://go.gov.sg/bca-coa2025) · [Commencement circular, paragraph 5](https://www1.bca.gov.sg/docs/default-source/docs-corp-news-and-publications/circulars/circular---code-on-accessibility-in-the-built-environment-2025.pdf)

## Run the pilot

From the unzipped workspace root in macOS, Linux or WSL, use Python 3.12.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python _tools/prepare.py pilot
python _tools/preview.py pilot --find alarm
python _tools/clause_trace.py '5.1.3(d)'
```

Preparation retrieves the official PDF, checks its SHA-256 fingerprint and extracts six clauses, a table row, a figure caption and the amendment history. Subparagraphs keep their parent condition. If you already hold the same PDF, use `python _tools/prepare.py pilot --pdf /path/to/code.pdf`. Source material is fetched on your machine. BCA sets out its terms of use on PDF page 2.

The preview runs Microsoft GraphRAG's document loading, chunking and noun-phrase graph extraction on your machine. The first run downloads language resources. No model key is needed. The search matches noun phrases containing your term, follows their co-occurrence edges back to source documents and then follows explicit Code references within the pilot. [Recorded results from both scopes](04_review/verification.md)

## Ask a natural-language question

Preparation runs `graphrag init` and configures the JSONL reader, citation metadata, regulatory entity types, full-graph clustering (`cluster_graph.use_lcc: false` so disconnected code chapters stay searchable), and Singapore BCA/SCDF domain grounding prompts. By default, `_tools/prepare.py` configures **Google Gemini** (`gemini-3.8-flash` + `gemini-embedding-2` via LiteLLM); pass `--provider openai` if you prefer the stock OpenAI defaults (`gpt-4.1-mini` and `text-embedding-3-large`).

Add your API key locally in `03_graphrag/<scope>/.env` (see `.env.example`; real `.env` files are gitignored):

```env
GEMINI_API_KEY=your-google-ai-studio-key
```

Then index and query any prepared scope (`multicode`, `pilot`, or `full`):

```bash
graphrag index --root 03_graphrag/full
graphrag query --root 03_graphrag/full --method local \
  "For a new place of worship with toilets on Level 2, which washroom and emergency assistance alarm evidence should I request? Cite each BCA clause and PDF page. Identify evidence still needed."
```

## Continuing development on another machine

```bash
git clone <your-github-repo-url>
cd SG_MultiCode_ICM_GraphRAG
py -3.12 -m venv .venv            # or python3.12 -m venv .venv on macOS/Linux
.venv\Scripts\activate            # or source .venv/bin/activate
python -m pip install -r requirements.txt
python _tools/prepare.py multicode
python _tools/prepare.py full
```

Then add `GEMINI_API_KEY` to `03_graphrag/multicode/.env` and `03_graphrag/full/.env`. To skip re-indexing the 116-page BCA PDF on a second machine, transfer a zip of `03_graphrag/full/output/` (never `.env` or `cache/`) and extract it into `03_graphrag/full/output/` before running `graphrag query`.

Use local search for a particular space, component or clause. Global search summarises themes across a larger corpus. For both, open the source pages and follow each explicit cross-reference before issuing a project finding. GraphRAG's internal citation IDs can be resolved through its text units and document records. The input also puts the BCA reference and page into each chunk. [Query methods](https://microsoft.github.io/graphrag/query/overview/) · [GraphRAG CLI](https://microsoft.github.io/graphrag/cli/)

## Use the complete Code

```bash
python _tools/prepare.py full
python _tools/preview.py full --find alarm
```

This builds a separate project at `03_graphrag/full` with one source record per PDF page. For natural-language questions, configure that project's models and use the same index and query commands with `--root 03_graphrag/full`. Full-page text supports discovery. A page can contain clauses, exceptions, advisory boxes, tables and diagrams. Inspect adjoining pages for continued clauses and check dimension arrows, legends and table headings in the original PDF. Expand the selectors in [pilot.json](02_evidence/pilot.json) for repeatable clause-level checks.

## Use ICM with your agent

Open this directory in Codex and give it the prompt below. The root [AGENTS.md](AGENTS.md) routes the agent to a numbered stage. Each stage specifies its inputs, output and check.

> Use this ICM workspace to review the larger washroom on Level 2 of a new place of worship. Retrieve the relevant provisions, follow any explicit BCA references and check the source pages. Write the review using the evidence template. For every open item, name the drawing, schedule or system record that would resolve it.

To use RinDig's scaffolding skill when extending this workspace, install it in your project and ask Codex to add the next review topic under the same stage contracts.

```bash
git clone https://github.com/RinDig/icm-architect .agents/skills/icm-architect
```

[ICM Architect](https://github.com/RinDig/icm-architect) · [Microsoft GraphRAG 3.3.0](https://pypi.org/project/graphrag/3.3.0/)
