"""
Configuration Settings for LangGraph Migration
===============================================

All paths, API keys, and constants in one place.
Load from environment variables with sensible defaults.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file in langgraph_migration folder
_this_dir = Path(__file__).resolve().parent
_migration_dir = _this_dir.parent
load_dotenv(_migration_dir / ".env")

# =============================================================================
# PATHS
# =============================================================================

# Base directory is the original project root (parent of langgraph_migration/)
BASE_DIR = _migration_dir.parent

def _get_abs_path(env_var: str, default_path: Path) -> Path:
    """Ensure path is absolute, resolving relative paths against BASE_DIR."""
    val = os.getenv(env_var)
    if val:
        p = Path(val)
        return p if p.is_absolute() else BASE_DIR / p
    return default_path

# Data paths (from environment or defaults)
PAPERS_DIR = _get_abs_path("PAPERS_DIR", BASE_DIR / "data" / "papers")
GROUND_TRUTH_PATH = _get_abs_path(
    "GROUND_TRUTH_PATH",
    BASE_DIR / "data" / "ground_truth" / "all_combined_extracted_data_refined.xlsx"
)
OUTPUTS_DIR = _get_abs_path("OUTPUTS_DIR", BASE_DIR / "outputs")
LOGS_DIR = _get_abs_path("LOGS_DIR", BASE_DIR / "logs")

# Ensure output directories exist
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# =============================================================================
# EXTRACTION SETTINGS
# =============================================================================

# Maximum number of Extractor-Critic iterations before forcing completion
MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "4"))

# Maximum conversation turns for the agent
MAX_TURNS = int(os.getenv("MAX_TURNS", "50"))

# Maximum number of PDF pages to process
# Set to None to process ALL pages (no limit)
# Previously was 20, but we want to process all pages in the PDF
MAX_PAGES = None  # No limit - process all pages

# Number of pages to send per chunk to vision model
# Using 1 page at a time for:
# 1. Better extraction quality per page
# 2. More focused context for vision model
# 3. Can be parallelized in future
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1"))

# =============================================================================
# FIREWORKS AI / LLM SETTINGS
# =============================================================================

# Fireworks API configuration
FIREWORKS_API_KEY = os.getenv("FIREWORKS_API_KEY", "")
FIREWORKS_BASE_URL = os.getenv("FIREWORKS_BASE_URL", "https://api.fireworks.ai/inference/v1")
FIREWORKS_MODEL_NAME = os.getenv("FIREWORKS_MODEL_NAME", "accounts/fireworks/models/glm-4p7")

# Vision model for Reader phase (multimodal - supports images)
FIREWORKS_VISION_MODEL = os.getenv(
    "FIREWORKS_VISION_MODEL",
    "accounts/fireworks/models/qwen3-vl-235b-a22b-thinking"
)

# Model settings
DEFAULT_MODEL = FIREWORKS_MODEL_NAME
DEFAULT_MAX_TOKENS = int(os.getenv("DEFAULT_MAX_TOKENS", "4096"))
DEFAULT_TEMPERATURE = float(os.getenv("DEFAULT_TEMPERATURE", "0.6"))

# =============================================================================
# QWEN3-VL IMAGE BUDGET (PIXELS)
# =============================================================================
# Qwen3-VL official processor suggests controlling the visual token budget by
# min/max pixels. With ~32x spatial compression, 256–1280 visual tokens per
# image translates roughly to 256*32*32 (262,144) to 1280*32*32 (1,310,720)
# pixels. We clamp rendered page images to this range to match recommended
# budgets while preserving aspect ratio.
QWEN_IMAGE_MIN_PIXELS = int(os.getenv("QWEN_IMAGE_MIN_PIXELS", str(256 * 32 * 32)))   # 262,144
QWEN_IMAGE_MAX_PIXELS = int(os.getenv("QWEN_IMAGE_MAX_PIXELS", str(1280 * 32 * 32))) # 1,310,720

# =============================================================================
# READER RENDERING / CONCURRENCY
# =============================================================================
# Rendering strategy for Reader. Options:
#   - "moderate": adaptive single image per page within pixel budget
#   - "max_dpi": single image per page at fixed DPI (no clamp)
#   - "tiled": full page (moderate) + grid of high-DPI tiles per page
READER_RENDER_MODE = os.getenv("READER_RENDER_MODE", "tiled").lower()

# Tiling parameters (used when READER_RENDER_MODE == 'tiled')
TILE_ROWS = int(os.getenv("TILE_ROWS", "2"))
TILE_COLS = int(os.getenv("TILE_COLS", "3"))
TILE_OVERLAP = float(os.getenv("TILE_OVERLAP", "0.08"))  # 8% overlap
TILE_DPI = int(os.getenv("TILE_DPI", "300"))

# Reader concurrency (per-page LLM calls in flight)
READER_CONCURRENCY = int(os.getenv("READER_CONCURRENCY", "4"))

# JSON validation retry (per page)
JSON_RETRY_ON_FAIL = os.getenv("JSON_RETRY_ON_FAIL", "true").lower() == "true"

# =============================================================================
# LANGGRAPH SETTINGS
# =============================================================================

# Checkpoint backend: "memory" for development, "sqlite" for production
# Changed default to "sqlite" for persistence across runs (resume capability)
LANGGRAPH_CHECKPOINT_BACKEND = os.getenv("LANGGRAPH_CHECKPOINT_BACKEND", "sqlite")

# SQLite checkpoint path (only used if backend is "sqlite")
LANGGRAPH_CHECKPOINT_PATH = OUTPUTS_DIR / "langgraph_checkpoints.db"

# =============================================================================
# API SETTINGS (for normalization lookups)
# =============================================================================

# MyGene.info API
MYGENE_API_URL = "https://mygene.info/v3"

# MyVariant.info API
MYVARIANT_API_URL = "https://myvariant.info/v1"

# Ontology Lookup Service (OLS)
OLS_API_URL = "https://www.ebi.ac.uk/ols/api"

# API timeout in seconds
API_TIMEOUT = int(os.getenv("API_TIMEOUT", "15"))

# =============================================================================
# DEBUG
# =============================================================================

VERBOSE = os.getenv("VERBOSE", "true").lower() == "true"
