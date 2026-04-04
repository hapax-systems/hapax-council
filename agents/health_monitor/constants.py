"""Constants and paths shared across health check modules."""

from __future__ import annotations

import os
from pathlib import Path

# ── Vendored from shared/config.py ──────────────────────────────────────────
LITELLM_BASE: str = os.environ.get(
    "LITELLM_API_BASE",
    os.environ.get("LITELLM_BASE_URL", "http://localhost:4000"),
)
QDRANT_URL: str = os.environ.get("QDRANT_URL", "http://localhost:6333")
OLLAMA_URL: str = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

HAPAX_HOME: Path = Path(os.environ.get("HAPAX_HOME", str(Path.home())))
HAPAX_CACHE_DIR: Path = HAPAX_HOME / ".cache"
HAPAX_PROJECTS_DIR: Path = HAPAX_HOME / "projects"
LLM_STACK_DIR: Path = HAPAX_HOME / "llm-stack"
CLAUDE_CONFIG_DIR: Path = HAPAX_HOME / ".claude"
PASSWORD_STORE_DIR: Path = HAPAX_HOME / ".password-store"
RAG_SOURCES_DIR: Path = HAPAX_HOME / "documents" / "rag-sources"

AXIOM_AUDIT_DIR: Path = HAPAX_CACHE_DIR / "axiom-audit"
RAG_INGEST_STATE_DIR: Path = HAPAX_CACHE_DIR / "rag-ingest"

HAPAX_COUNCIL_DIR: Path = HAPAX_PROJECTS_DIR / "hapax-council"
AI_AGENTS_DIR: Path = HAPAX_COUNCIL_DIR  # legacy alias
PROFILES_DIR: Path = Path(__file__).resolve().parent.parent.parent / "profiles"
SYSTEMD_USER_DIR: Path = Path.home() / ".config" / "systemd" / "user"

WATCH_STATE_DIR: Path = HAPAX_HOME / "hapax-state" / "watch"
EDGE_STATE_DIR: Path = HAPAX_HOME / "hapax-state" / "edge"

# Raspberry Pi fleet -- expected nodes and their primary roles
PI_FLEET: dict[str, dict] = {
    "hapax-pi4": {
        "role": "sentinel",
        "expected_services": ["hapax-sentinel", "hapax-watch-backup"],
    },
    "hapax-pi5": {
        "role": "rag-edge",
        "expected_services": ["hapax-rag-edge", "hapax-gdrive-pull.timer"],
    },
}

COMPOSE_FILE = LLM_STACK_DIR / "docker-compose.yml"
AGENTS_COMPOSE_FILE = AI_AGENTS_DIR / "docker-compose.yml"
PASSWORD_STORE = PASSWORD_STORE_DIR

CORE_CONTAINERS = {"qdrant", "ollama", "postgres", "litellm"}
REQUIRED_QDRANT_COLLECTIONS = {
    "documents",
    "profile-facts",
    "axiom-precedents",
    "operator-corrections",
    "operator-episodes",
    "operator-patterns",
    "studio-moments",
}
PASS_ENTRIES = [
    "api/anthropic",
    "api/google",
    "litellm/master-key",
    "langfuse/public-key",
    "langfuse/secret-key",
]

EXPECTED_OLLAMA_MODELS = [
    "nomic-embed-cpu",
]

REQUIRED_SECRETS = {
    "LITELLM_API_KEY": "litellm/master-key",
    "LANGFUSE_PUBLIC_KEY": "langfuse/public-key",
    "LANGFUSE_SECRET_KEY": "langfuse/secret-key",
    "ANTHROPIC_API_KEY": "api/anthropic",
}

DAILY_BUDGET_USD = 5.0

VOICE_VRAM_LOCK = Path.home() / ".cache" / "hapax-daimonion" / "vram.lock"

RESTIC_REPO = Path("/data/backups/restic")
BACKUP_STALE_H = 36
BACKUP_FAILED_H = 72

SYNC_STALE_H = 24
SYNC_FAILED_H = 72

LATENCY_THRESHOLDS = {
    "latency.litellm": (f"{LITELLM_BASE}/health/liveliness", 200.0),
    "latency.qdrant": (f"{QDRANT_URL}/healthz", 100.0),
    "latency.ollama": (f"{OLLAMA_URL}/api/tags", 500.0),
}
