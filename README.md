# OncoCITE — LangGraph / LangChain Extraction Pipeline

Companion code for the OncoCITE manuscript
([Research Square preprint, DOI 10.21203/rs.3.rs-9160944/v1](https://doi.org/10.21203/rs.3.rs-9160944/v1)):
a multi-agent system for source-grounded extraction and harmonization of
clinical genomic evidence from full-text oncology publications, intended
to support reconstruction of the CIViC knowledge base.

The pipeline is implemented as LangGraph `StateGraph`s orchestrating
LangChain `@tool` functions, and runs against open models served by
Fireworks AI (GLM-4 for reasoning, Qwen3-VL for vision over PDF pages).

## Features

- **Reader**: Qwen3-VL vision model extracts structured content from PDF pages
- **Planner → Extractor → Critic → Normalizer** agent loop with up to 4 critic-driven revision rounds
- **Provenance tracking**: every evidence item carries source page, verbatim quote, and a confidence score
- **Map-Reduce normalization**: parallel entity lookups against MyGene, MyVariant, and the EBI Ontology Lookup Service
- **Retry + circuit breaker** on LLM calls; SQLite-backed LangGraph checkpointing for resume
- **Graph visualization** (Mermaid) and full state-history export for debugging

## Quick Start

Requires Python 3.12, [`uv`](https://docs.astral.sh/uv/), and a Fireworks AI API key.

```bash
git clone https://github.com/Ali-Maq/oncocite-langchain.git
cd oncocite-langchain

# Install dependencies (creates .venv/)
uv sync

# Configure your API key
cp .env.example .env
# edit .env and set FIREWORKS_API_KEY=fw_...

# Run extraction on one of the 11 bundled validation papers
uv run python scripts/run_extraction.py PMID_18528420

# Or point at your own PDF corpus
uv run python scripts/run_extraction.py <paper_id> \
    --papers-dir /path/to/papers \
    --output-dir /path/to/outputs
```

Outputs land in `outputs/{paper_id}/{YYYYMMDD_HHMMSS}/`.

## Reproducing the Multiple Myeloma validation

The `test_paper/triplet/` directory ships 11 PMID-indexed PDFs with
matching curator ground-truth JSON — the same corpus used for the
three-way evaluation framework in the manuscript:

```
test_paper/triplet/
  PMID_11050000/  PMID_11050000.pdf  PMID_11050000_ground_truth.json  ...
  PMID_12483530/  ...
  ...
```

To re-run end-to-end extraction across all 11 papers:

```bash
for pmid in $(ls test_paper/triplet); do
    uv run python scripts/run_extraction.py "$pmid"
done
```

## Project Structure

```
oncocite-langchain/
├── pyproject.toml          # Project configuration and dependencies
├── .python-version         # Python 3.12
├── .env                    # Environment configuration (Fireworks API)
├── client.py               # Main entry point (CivicExtractionClient)
│
├── graphs/                 # LangGraph StateGraph definitions
│   ├── __init__.py
│   ├── state.py            # ExtractionGraphState, EvidenceProvenance TypedDicts
│   ├── prompts.py          # Agent prompts with provenance requirements
│   ├── reader_graph.py     # Phase 1: Vision → Structured Text
│   └── extraction_graph.py # Phase 2: Planner → Extractor → Critic → Normalizer
│
├── runtime/                # Runtime utilities
│   ├── __init__.py
│   ├── llm.py              # LLM client factory (GLM-4, Qwen3-VL via Fireworks)
│   ├── checkpointing.py    # LangGraph checkpointer factory
│   ├── retry.py            # Retry policies with circuit breaker pattern
│   ├── visualization.py    # Graph visualization (Mermaid) and state history
│   └── map_reduce.py       # Parallel normalization with ordering preservation
│
├── config/                 # Configuration
│   ├── __init__.py
│   └── settings.py         # Environment and path settings
│
├── tools/                  # LangChain @tool functions
│   ├── __init__.py
│   ├── context.py          # ToolContext for state access in tools
│   ├── tool_registry.py    # get_*_tools() functions per agent
│   ├── paper_content_tools.py  # save_paper_content, get_paper_content
│   ├── extraction_tools.py # save_extraction_plan, save_evidence_items, etc.
│   ├── validation_tools.py # validate_evidence_item, check_actionability
│   ├── normalization_tools.py  # lookup_* tools for external APIs
│   └── schemas.py          # TIER_1_FIELDS, REQUIRED_FIELDS
│
├── hooks/                  # Observability
│   ├── __init__.py
│   └── logging_callbacks.py    # LangChain BaseCallbackHandler for logging
│
├── scripts/                # CLI entry points
│   └── run_extraction.py   # Main CLI script
│
└── test/                   # Test files and outputs
    ├── run_full_pipeline_test.py
    ├── test_e2e_with_new_features.py
    └── e2e_outputs/        # Test run artifacts
```

## Configuration

Create `.env` file with your Fireworks API settings:

```bash
# Fireworks AI Configuration
FIREWORKS_API_KEY=your_api_key_here
FIREWORKS_BASE_URL=https://api.fireworks.ai/inference/v1
FIREWORKS_MODEL_NAME=accounts/fireworks/models/glm-4p7
FIREWORKS_VISION_MODEL=accounts/fireworks/models/qwen3-vl-235b-a22b-thinking

# Extraction Settings
MAX_ITERATIONS=3
MAX_PAGES=20
```

## Output Files

Each extraction run creates timestamped output files:
```
outputs/
└── {paper_id}_{YYYYMMDD_HHMMSS}_extraction.json
```

The extraction JSON contains:
- `paper_id`, `pdf_path`, `timestamp`, `duration_seconds`
- `extraction.evidence_items` - Final normalized evidence items
- `paper_info` - Title, authors, journal, year
- `extraction_plan` - Planner's strategy
- `critique` - Critic's assessment
- `summary` - Statistics (item count, coverage, iterations)

## Agent Pipeline

- **Reader** — Qwen3-VL vision model reads PDF pages and emits structured content
- **Planner** — analyzes the paper and produces an extraction strategy
- **Extractor** — emits evidence items with full provenance metadata
- **Critic** — validates items and may request revisions (up to `MAX_ITERATIONS` rounds)
- **Normalizer** — maps entities to Entrez / DOID / RxNorm / NCIt via MyGene, MyVariant, and OLS

## Python API

### Basic Extraction
```python
from client import CivicExtractionClient

client = CivicExtractionClient(verbose=True)
result = await client.run_extraction(
    pdf_path="paper.pdf",
    paper_id="PMID_12345",
    max_iterations=3,
)
print(f"Extracted {len(result['final_extractions'])} evidence items")
```

### With Visualization
```python
from runtime.visualization import save_graph_visualization
from graphs.extraction_graph import build_extraction_graph

graph = build_extraction_graph()
save_graph_visualization(graph, "extraction_graph.md", title="CIViC Pipeline")
```

### Get Retry Statistics
```python
from runtime.llm import get_llm_retry_stats
stats = get_llm_retry_stats()
print(f"Total retries: {stats['total_retries']}")
```

## Architecture

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for a detailed design walkthrough of
the state graphs, tool registry, and checkpointing layer, and
[`COMPARISON.md`](COMPARISON.md) for a node-by-node comparison with the
original agent implementation described in the manuscript.

## Citation

If you use this code, please cite the OncoCITE preprint:

> Quidwai M., Thibaud S., Shasha D., Jagannath S., Parekh S., Laganà A.
> *OncoCITE: Multimodal Multi-Agent Reconstruction of Clinical Oncology
> Knowledge Bases from Scientific Literature.* Research Square (2026).
> DOI: [10.21203/rs.3.rs-9160944/v1](https://doi.org/10.21203/rs.3.rs-9160944/v1)

## License

Released under the terms in [`LICENSE`](LICENSE) (CC BY 4.0, matching the
preprint license).
