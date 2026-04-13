# OncoCITE — LangChain implementation

Companion code for the OncoCITE manuscript (Research Square preprint,
[DOI 10.21203/rs.3.rs-9160944/v1](https://doi.org/10.21203/rs.3.rs-9160944/v1)):
a multi-agent AI system for source-grounded extraction and harmonization
of clinical genomic evidence from full-text oncology publications,
designed to support reconstruction of the CIViC knowledge base.

This repository is the **LangChain** implementation referenced in
Section 6 (Code Availability) of the manuscript. The orchestration uses
LangGraph `StateGraph`s over LangChain `@tool` functions, runs against
open models served by Fireworks AI (GLM-4 for reasoning, Qwen3-VL for
PDF vision), and ships with an **MCP server** exposing all 22 tools from
Supplementary Table S15. A sibling implementation built on the Claude
Agent SDK lives at
[Ali-Maq/civic-extraction-agent](https://github.com/Ali-Maq/civic-extraction-agent).

## Highlights

- **Multi-agent pipeline** — Reader → Planner → Extractor → Critic →
  Normalizer, with a Critic-driven refinement loop capped at 3 iterations
  (Section 2.2, Supplementary Figure S2)
- **Source-grounded evidence** — every item carries a verbatim quote,
  source page reference, and a 0–1 confidence score
- **45-field JSON schema** — 25 Tier-1 extraction fields + 20 Tier-2
  normalization fields (Supplementary Tables S17 and S18)
- **Ontology normalization** — MyGene, MyVariant, EBI OLS (DOID / NCIt /
  EFO / HPO), RxNorm, ClinicalTrials.gov, NCBI ID Converter
  (Supplementary Table S21)
- **MCP server** — all 22 paper-spec tools exposed over stdio
  (Supplementary Table S15); any MCP-compatible client can drive the
  pipeline end-to-end
- **Reproducibility harness** — SQLite-backed LangGraph checkpointing,
  retry policies with circuit breakers, Mermaid graph visualization,
  deterministic inference settings

## Quick start

Requires Python 3.11+ and [`uv`](https://docs.astral.sh/uv/) (or plain
`pip`), plus a Fireworks AI API key.

```bash
git clone https://github.com/Ali-Maq/oncocite-langchain.git
cd oncocite-langchain

# Option 1 — uv (recommended)
uv sync
cp .env.example .env   # edit FIREWORKS_API_KEY=fw_...

# Option 2 — plain pip (matches Supplementary Note S2.3)
pip install -r requirements.txt

# Run extraction on a bundled validation paper
python run_extraction.py \
    --input test_paper/triplet/PMID_18528420/PMID_18528420.pdf \
    --output outputs/
```

Outputs land in `outputs/{paper_id}/{YYYYMMDD_HHMMSS}/{paper_id}_extraction.json`.

## MCP server (22 tools, Supplementary Table S15)

The extraction and normalization pipeline is exposed as a Model Context
Protocol server communicating over stdio. Launch it directly:

```bash
python -m mcp_server
```

To wire it into Claude Desktop or another MCP client, point the client
at `python -m mcp_server` with the repository root as the working
directory. See [`skills/oncocite.skill.json`](skills/oncocite.skill.json)
for a ready-made skill manifest listing all 22 tools.

## Docker

```bash
docker build -t oncocite-langchain:latest .
docker run --rm \
    -e FIREWORKS_API_KEY="$FIREWORKS_API_KEY" \
    -v $(pwd)/test_paper:/app/data \
    -v $(pwd)/outputs:/app/outputs \
    oncocite-langchain:latest \
    --input /app/data/triplet/PMID_18528420/PMID_18528420.pdf \
    --output /app/outputs
```

Or via compose:

```bash
docker compose run --rm oncocite \
    --input test_paper/triplet/PMID_18528420/PMID_18528420.pdf \
    --output outputs/
```

## Reproducing the validation corpus

`test_paper/` bundles all 15 papers evaluated in the manuscript:

- `test_paper/triplet/` — 10 retrospective Multiple Myeloma papers
  (CIViC-indexed) with source PDF, curator ground truth, OncoCITE
  extraction, and three-way validation analysis (Section 2.6,
  Supplementary Note S1)
- `test_paper/prospective/` — 5 prospective-application papers (2022–2024)
  with 0% CIViC coverage at extraction time (Section 2.8,
  Supplementary Note S1.8)

See [`test_paper/README.md`](test_paper/README.md) for the full corpus
description and reproduction commands.

## Pipeline wrappers

- [`pipelines/nextflow/oncocite.nf`](pipelines/nextflow/oncocite.nf) —
  DSL2 Nextflow workflow
- [`pipelines/snakemake/Snakefile`](pipelines/snakemake/Snakefile) —
  Snakemake workflow

Both accept a directory of PDFs and emit per-paper
`*_extraction.json` following the 45-field schema.

## Repository layout

```
oncocite-langchain/
├── run_extraction.py        # Paper-spec CLI entry point (--input / --output)
├── client.py                # Programmatic entry point (CivicExtractionClient)
├── config/                  # Settings, paths, env-var loading
├── graphs/                  # LangGraph StateGraph definitions (Reader, Extractor)
├── runtime/                 # LLM client, checkpointing, retry/circuit breaker, visualization
├── tools/                   # LangChain @tool functions (superset of Table S15)
├── hooks/                   # LangChain callback handlers (audit log)
├── mcp_server/              # FastMCP wrapper — 22 tools from Table S15 over stdio
├── skills/                  # Claude-desktop skill manifest
├── pipelines/               # Nextflow and Snakemake wrappers
├── scripts/                 # Additional CLIs (paper_id lookups, resume-from-checkpoint)
├── tests/                   # pytest suite
├── test_paper/              # 15-paper validation corpus
│   ├── triplet/             # 10 retrospective MM papers
│   └── prospective/         # 5 prospective papers
├── Dockerfile
├── docker-compose.yml
├── requirements.txt         # pinned deps (generated from uv.lock)
├── pyproject.toml
├── LICENSE                  # MIT
└── ARCHITECTURE.md / COMPARISON.md  # Design documentation
```

## Python API

```python
import asyncio
from client import CivicExtractionClient

client = CivicExtractionClient(verbose=True)
result = asyncio.run(client.run_extraction(
    pdf_path="test_paper/triplet/PMID_18528420/PMID_18528420.pdf",
    paper_id="PMID_18528420",
    max_iterations=3,
))
print(f"Extracted {len(result['final_extractions'])} evidence items")
```

## Citation

```
Quidwai M., Thibaud S., Shasha D., Jagannath S., Parekh S., Laganà A.
OncoCITE: Multimodal Multi-Agent Reconstruction of Clinical Oncology
Knowledge Bases from Scientific Literature. Research Square (2026).
DOI: 10.21203/rs.3.rs-9160944/v1
```

## License

[MIT](LICENSE) — matching Section 6 (Code Availability) of the manuscript.
