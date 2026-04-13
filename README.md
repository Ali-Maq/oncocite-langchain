# CIViC LangGraph Migration

This folder contains the LangGraph implementation of the CIViC evidence extraction pipeline, migrated from Claude Agent SDK.

## Purpose

Migrate from Anthropic's Claude Agent SDK to LangGraph to enable:
- Use of GLM-4 and Qwen3-VL models via Fireworks AI API
- Same prompts, tools, and business logic as original implementation
- Thread-based checkpointing for resume capability
- Enhanced observability with retry policies and circuit breakers

## Quick Start

```bash
# Navigate to migration folder
cd langgraph_migration

# Install dependencies with uv
uv sync

# Run extraction on a paper
uv run python scripts/run_extraction.py <paper_id>

# Or directly with client.py
uv run python client.py <pdf_path>
```

## Project Structure

```
langgraph_migration/
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

## Features

### Core Pipeline
- **Reader**: Qwen3-VL vision model extracts structured content from PDF pages
- **Planner**: Analyzes paper and creates extraction strategy
- **Extractor**: Extracts evidence items with provenance metadata
- **Critic**: Validates items, may request revisions (max 3 iterations)
- **Normalizer**: Maps entities to standard ontologies (Entrez, DOID, RxNorm, NCIt)

### Enhanced Features
- **Retry with Circuit Breaker**: Automatic retries with exponential backoff
- **Provenance Tracking**: Each evidence item includes source page, verbatim quote, confidence score
- **Graph Visualization**: Export Mermaid diagrams of pipeline
- **State History**: Access full execution history for debugging
- **Map-Reduce Normalization**: Parallel entity lookups with ordering preservation
- **Human-in-the-Loop**: Optional review checkpoint (commented out by default)

## Migration Status

- [x] Phase 0: Environment Setup
- [x] Phase 1: Foundation (State, LLM, Checkpointing)
- [x] Phase 2: Tools Migration
- [x] Phase 3: Graphs Implementation
- [x] Phase 4: Client Integration
- [x] Phase 5: Observability
- [x] Phase 6: Cleanup & Validation

## Usage Examples

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
