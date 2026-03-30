"""health_monitor package -- Deterministic stack health check suite.

Re-exports all public names for backward compatibility. All existing imports
from ``agents.health_monitor`` continue to work unchanged.
"""

from __future__ import annotations

# ── Ensure all check modules register themselves ────────────────────────────
from . import checks as _checks  # noqa: F401

# ── Individual check functions (imported by test files) ─────────────────────
from .checks.auth import check_langfuse_auth as check_langfuse_auth  # noqa: F401
from .checks.auth import check_litellm_auth as check_litellm_auth  # noqa: F401
from .checks.budget import check_daily_spend as check_daily_spend  # noqa: F401
from .checks.connectivity import (  # noqa: F401
    check_gdrive_sync_freshness as check_gdrive_sync_freshness,
)
from .checks.connectivity import (
    check_n8n_health as check_n8n_health,
)
from .checks.connectivity import (
    check_ntfy as check_ntfy,
)
from .checks.connectivity import (
    check_obsidian_sync as check_obsidian_sync,
)
from .checks.connectivity import (
    check_phone_connected as check_phone_connected,
)
from .checks.connectivity import (
    check_tailscale as check_tailscale,
)
from .checks.connectivity import (
    check_watch_connected as check_watch_connected,
)
from .checks.credentials import check_pass_entries as check_pass_entries  # noqa: F401
from .checks.credentials import check_pass_store as check_pass_store  # noqa: F401
from .checks.disk import check_disk_usage as check_disk_usage  # noqa: F401
from .checks.docker import (  # noqa: F401
    check_agents_containers as check_agents_containers,
)
from .checks.docker import (
    check_compose_file as check_compose_file,
)
from .checks.docker import (
    check_docker_containers as check_docker_containers,
)
from .checks.docker import (
    check_docker_daemon as check_docker_daemon,
)
from .checks.edge import check_pi_fleet as check_pi_fleet  # noqa: F401
from .checks.endpoints import check_service_endpoints as check_service_endpoints  # noqa: F401
from .checks.gpu import check_gpu_available as check_gpu_available  # noqa: F401
from .checks.gpu import check_gpu_temperature as check_gpu_temperature  # noqa: F401
from .checks.gpu import check_gpu_vram as check_gpu_vram  # noqa: F401
from .checks.latency import check_postgres_latency as check_postgres_latency  # noqa: F401
from .checks.latency import check_service_latency as check_service_latency  # noqa: F401
from .checks.models_ollama import check_ollama_models as check_ollama_models  # noqa: F401
from .checks.profiles import check_profile_files as check_profile_files  # noqa: F401
from .checks.profiles import check_profile_staleness as check_profile_staleness  # noqa: F401
from .checks.qdrant import check_qdrant_collections as check_qdrant_collections  # noqa: F401
from .checks.qdrant import check_qdrant_health as check_qdrant_health  # noqa: F401
from .checks.queues import check_n8n_executions as check_n8n_executions  # noqa: F401
from .checks.queues import check_rag_retry_queue as check_rag_retry_queue  # noqa: F401
from .checks.secrets import check_env_secrets as check_env_secrets  # noqa: F401
from .checks.systemd import check_systemd_drift as check_systemd_drift  # noqa: F401
from .checks.systemd import check_systemd_services as check_systemd_services  # noqa: F401
from .checks.voice import check_voice_services as check_voice_services  # noqa: F401
from .checks.voice import check_voice_socket as check_voice_socket  # noqa: F401
from .checks.voice import check_voice_vram_lock as check_voice_vram_lock  # noqa: F401

# ── Constants (imported by tests and other agents) ──────────────────────────
from .constants import CORE_CONTAINERS as CORE_CONTAINERS  # noqa: F401
from .constants import PASS_ENTRIES as PASS_ENTRIES  # noqa: F401
from .constants import REQUIRED_QDRANT_COLLECTIONS as REQUIRED_QDRANT_COLLECTIONS  # noqa: F401
from .constants import REQUIRED_SECRETS as REQUIRED_SECRETS  # noqa: F401

# ── Models ──────────────────────────────────────────────────────────────────
from .models import CheckResult as CheckResult  # noqa: F401
from .models import GroupResult as GroupResult  # noqa: F401
from .models import HealthReport as HealthReport  # noqa: F401
from .models import Status as Status  # noqa: F401
from .models import build_group_result as build_group_result  # noqa: F401
from .models import worst_status as worst_status  # noqa: F401

# ── Output / fixes ──────────────────────────────────────────────────────────
from .output import HISTORY_FILE as HISTORY_FILE  # noqa: F401
from .output import KEEP_HISTORY_LINES as KEEP_HISTORY_LINES  # noqa: F401
from .output import MAX_HISTORY_LINES as MAX_HISTORY_LINES  # noqa: F401
from .output import format_history as format_history  # noqa: F401
from .output import format_human as format_human  # noqa: F401
from .output import rotate_history as rotate_history  # noqa: F401
from .output import run_fixes as run_fixes  # noqa: F401
from .output import run_fixes_v2 as run_fixes_v2  # noqa: F401

# ── Registry ────────────────────────────────────────────────────────────────
from .registry import CHECK_REGISTRY as CHECK_REGISTRY  # noqa: F401
from .registry import check_group as check_group  # noqa: F401

# ── Runner ──────────────────────────────────────────────────────────────────
from .runner import quick_check as quick_check  # noqa: F401
from .runner import run_checks as run_checks  # noqa: F401

# ── Snapshot ────────────────────────────────────────────────────────────────
from .snapshot import write_infra_snapshot as write_infra_snapshot  # noqa: F401

# ── Utilities (imported by introspect.py, fix_capabilities, etc.) ───────────
from .utils import http_get as http_get  # noqa: F401
from .utils import run_cmd as run_cmd  # noqa: F401
