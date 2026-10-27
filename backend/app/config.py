"""Application configuration loaded from environment variables."""
from __future__ import annotations

import os
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


ROOT_DIR = Path(__file__).resolve().parents[2]          # project root
DATA_DIR = Path(_env("GRAPHAGENT_DATA_DIR", str(ROOT_DIR / "data"))).resolve()
REPOS_DIR = DATA_DIR / "repos"
WORKSPACES_DIR = DATA_DIR / "workspaces"
GRAPHS_DIR = DATA_DIR / "graphs"
DB_PATH = DATA_DIR / "graphagent.db"
EXAMPLES_DIR = ROOT_DIR / "examples"

OPENAI_API_KEY = _env("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL = _env("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
OPENAI_MODEL = _env("GRAPHAGENT_MODEL", "gpt-4o-mini")
# Explicit override: GRAPHAGENT_MOCK_LLM=1 forces mock, =0 forces openai (requires key).
_MOCK_RAW = _env("GRAPHAGENT_MOCK_LLM", "")
if _MOCK_RAW == "":
    LLM_MODE = "openai" if OPENAI_API_KEY else "mock"
else:
    LLM_MODE = "mock" if _env_bool("GRAPHAGENT_MOCK_LLM", True) else "openai"

# Isolation: auto -> docker when the daemon + image are usable, else local.
ISOLATION = _env("GRAPHAGENT_ISOLATION", "auto")        # auto | docker | local
DOCKER_IMAGE = _env("GRAPHAGENT_DOCKER_IMAGE", "graphagent-runner:latest")

# Default run budgets (overridable per run through the API).
DEFAULT_MAX_ITERATIONS = _env_int("GRAPHAGENT_MAX_ITERATIONS", 3)
DEFAULT_TOOL_BUDGET = _env_int("GRAPHAGENT_TOOL_BUDGET", 60)
DEFAULT_TOKEN_BUDGET = _env_int("GRAPHAGENT_TOKEN_BUDGET", 60000)
DEFAULT_TIMEOUT_SEC = _env_int("GRAPHAGENT_TIMEOUT_SEC", 600)
STAGE_MAX_STEPS = _env_int("GRAPHAGENT_STAGE_MAX_STEPS", 14)
TEST_TIMEOUT_SEC = _env_int("GRAPHAGENT_TEST_TIMEOUT_SEC", 180)

# Per-model USD prices per million tokens (prompt, completion) for cost estimates.
PRICING = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "o4-mini": (1.10, 4.40),
    "gpt-5-mini": (0.25, 2.00),
}
DEFAULT_PRICE = (0.50, 1.50)

CORS_ORIGINS = [o for o in _env("GRAPHAGENT_CORS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o]


def ensure_dirs() -> None:
    for d in (DATA_DIR, REPOS_DIR, WORKSPACES_DIR, GRAPHS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def price_for(model: str) -> tuple[float, float]:
    for key, price in PRICING.items():
        if model.startswith(key):
            return price
    return DEFAULT_PRICE
