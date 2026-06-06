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
    "hapax-pi1": {
        "role": "ir-desk",
        "expected_services": ["hapax-ir-edge"],
    },
    "hapax-pi2": {
        "role": "ir-room",
        "expected_services": ["hapax-ir-edge"],
    },
    "hapax-pi4": {
        "role": "sentinel",
        "expected_services": ["hapax-sentinel", "hapax-watch-backup"],
    },
    "hapax-pi5": {
        "role": "rag-edge",
        "expected_services": ["hapax-rag-edge", "hapax-gdrive-pull.timer"],
    },
    "hapax-pi6": {
        "role": "ir-overhead",
        "expected_services": ["hapax-ir-edge"],
    },
}

COMPOSE_FILE = LLM_STACK_DIR / "docker-compose.yml"
AGENTS_COMPOSE_FILE = AI_AGENTS_DIR / "docker-compose.yml"
PASSWORD_STORE = PASSWORD_STORE_DIR

CORE_CONTAINERS = {"qdrant", "ollama", "postgres", "litellm"}
PODIUM_THIN_CLIENT_CORE_CONTAINERS = {"qdrant", "postgres", "redis", "litellm"}
PODIUM_THIN_CLIENT_PROFILE_ALIASES = {
    "podium-thin-client",
    "podium-core",
    "thin-client",
    "thinclient",
}
APPENDIX_OWNED_OBSERVABILITY_SERVICES = {
    "minio",
    "langfuse",
    "langfuse-worker",
    "clickhouse",
    "prometheus",
    "grafana",
}
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

RESTIC_REPO = Path(os.environ.get("HAPAX_RESTIC_REPO", "/mnt/nas/backups/restic"))
BACKUP_STALE_H = 36
BACKUP_FAILED_H = 72

SYNC_STALE_H = 24
SYNC_FAILED_H = 72

LATENCY_THRESHOLDS = {
    "latency.litellm": (f"{LITELLM_BASE}/health/liveliness", 200.0),
    "latency.qdrant": (f"{QDRANT_URL}/healthz", 100.0),
    "latency.ollama": (f"{OLLAMA_URL}/api/tags", 500.0),
}


def llm_stack_profile() -> str:
    """Return the local LLM stack profile for health-monitor policy."""
    explicit = os.environ.get("HAPAX_LLM_STACK_PROFILE") or os.environ.get(
        "HAPAX_HEALTH_MONITOR_PROFILE"
    )
    if explicit:
        return explicit.strip().lower()
    if _podium_core_profile_dropin_active():
        return "podium-thin-client"
    return "default"


def podium_thin_client_enabled() -> bool:
    """Return true when podium should treat observability as appendix-owned."""
    return llm_stack_profile() in PODIUM_THIN_CLIENT_PROFILE_ALIASES


def core_containers() -> set[str]:
    """Return required local compose containers for the current profile."""
    if podium_thin_client_enabled():
        return set(PODIUM_THIN_CLIENT_CORE_CONTAINERS)
    return set(CORE_CONTAINERS)


def appendix_owned_observability_service(service: str) -> bool:
    """Return true when a compose service belongs on appendix in thin-client mode."""
    return service in APPENDIX_OWNED_OBSERVABILITY_SERVICES


def local_ollama_required() -> bool:
    """Return true when local Ollama is part of this host's health contract."""
    return not podium_thin_client_enabled()


def latency_thresholds() -> dict[str, tuple[str, float]]:
    """Return HTTP latency thresholds for services required on this host."""
    thresholds = dict(LATENCY_THRESHOLDS)
    if not local_ollama_required():
        thresholds.pop("latency.ollama", None)
    return thresholds


def langfuse_endpoint_url() -> str:
    """Return the Langfuse health URL appropriate for the local stack profile."""
    explicit = os.environ.get("HAPAX_LANGFUSE_HEALTH_URL")
    if explicit:
        return explicit.strip()
    if podium_thin_client_enabled():
        base = (
            os.environ.get("HAPAX_APPENDIX_LANGFUSE_URL")
            or os.environ.get("APPENDIX_LANGFUSE_URL")
            or os.environ.get("LANGFUSE_HOST")
            or "http://192.168.68.50:3000"
        )
        return f"{base.strip().rstrip('/')}/api/public/health"
    return os.environ.get("HAPAX_LOCAL_LANGFUSE_URL", "http://localhost:3000/").strip()


def _podium_core_profile_dropin_active() -> bool:
    dropin = SYSTEMD_USER_DIR / "llm-stack.service.d" / "podium-core-profile.conf"
    try:
        text = dropin.read_text(encoding="utf-8")
    except OSError:
        return False
    return "docker-compose.podium-thinclient.yml" in text or "--profile core" in text
