"""health_monitor.py — Deterministic stack health check suite.

Zero LLM calls. Runs parallel async checks against Docker, GPU, systemd,
Qdrant, profiles, HTTP endpoints, credentials, and disk. Returns structured
results with severity levels and remediation commands.

Usage:
    uv run python -m agents.health_monitor                     # Full check, human output
    uv run python -m agents.health_monitor --json              # Machine-readable JSON
    uv run python -m agents.health_monitor --check docker,gpu  # Specific groups only
    uv run python -m agents.health_monitor --fix               # Run remediation for failures
    uv run python -m agents.health_monitor --fix --yes         # Skip confirmation
    uv run python -m agents.health_monitor --verbose           # Show detail fields
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import shlex
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel

try:
    from shared import langfuse_config  # noqa: F401
except ImportError:
    pass
from opentelemetry import trace

_tracer = trace.get_tracer(__name__)

log = logging.getLogger("agents.health_monitor")


# ── Schemas ──────────────────────────────────────────────────────────────────


class Status(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"


class CheckResult(BaseModel):
    name: str
    group: str
    status: Status
    message: str
    detail: str | None = None
    remediation: str | None = None
    duration_ms: int = 0
    tier: int = 1  # ServiceTier value (0=critical, 1=important, 2=observability, 3=optional)


class GroupResult(BaseModel):
    group: str
    status: Status
    checks: list[CheckResult]
    healthy_count: int = 0
    degraded_count: int = 0
    failed_count: int = 0


class HealthReport(BaseModel):
    timestamp: str
    hostname: str
    overall_status: Status
    groups: list[GroupResult]
    total_checks: int = 0
    healthy_count: int = 0
    degraded_count: int = 0
    failed_count: int = 0
    duration_ms: int = 0
    summary: str = ""


# ── Constants ────────────────────────────────────────────────────────────────

from shared.config import (
    AI_AGENTS_DIR,
    AXIOM_AUDIT_DIR,
    CLAUDE_CONFIG_DIR,
    HAPAX_HOME,
    LLM_STACK_DIR,
    PASSWORD_STORE_DIR,
    PROFILES_DIR,
    RAG_INGEST_STATE_DIR,
    RAG_SOURCES_DIR,
    load_expected_timers,
)

WATCH_STATE_DIR: Path = HAPAX_HOME / "hapax-state" / "watch"
COMPOSE_FILE = LLM_STACK_DIR / "docker-compose.yml"
AGENTS_COMPOSE_FILE = AI_AGENTS_DIR / "docker-compose.yml"
PASSWORD_STORE = PASSWORD_STORE_DIR

CORE_CONTAINERS = {"qdrant", "ollama", "postgres", "litellm"}
REQUIRED_QDRANT_COLLECTIONS = {
    "documents",
    "samples",
    "claude-memory",
    "profile-facts",
    "axiom-precedents",
}
PASS_ENTRIES = [
    "api/anthropic",
    "api/google",
    "litellm/master-key",
    "langfuse/public-key",
    "langfuse/secret-key",
]

# Check group → list of async check functions
CHECK_REGISTRY: dict[str, list[Callable[[], Coroutine[None, None, list[CheckResult]]]]] = {}


def check_group(group: str):
    """Decorator to register check functions under a group name."""

    def decorator(fn: Callable[[], Coroutine[None, None, list[CheckResult]]]):
        CHECK_REGISTRY.setdefault(group, []).append(fn)
        return fn

    return decorator


# ── Utilities ────────────────────────────────────────────────────────────────


def worst_status(*statuses: Status) -> Status:
    """Return the most severe status from the given statuses."""
    if Status.FAILED in statuses:
        return Status.FAILED
    if Status.DEGRADED in statuses:
        return Status.DEGRADED
    return Status.HEALTHY


async def run_cmd(
    cmd: list[str],
    timeout: float = 10.0,
) -> tuple[int, str, str]:
    """Run a command asynchronously and return (returncode, stdout, stderr)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return (
            proc.returncode or 0,
            stdout.decode("utf-8", errors="replace").strip(),
            stderr.decode("utf-8", errors="replace").strip(),
        )
    except TimeoutError:
        try:
            proc.kill()  # type: ignore[possibly-undefined]
        except ProcessLookupError:
            pass
        return (1, "", f"Command timed out after {timeout}s")
    except FileNotFoundError:
        return (127, "", f"Command not found: {cmd[0]}")
    except Exception as e:
        return (1, "", str(e))


async def http_get(url: str, timeout: float = 3.0) -> tuple[int, str]:
    """HTTP GET returning (status_code, body). Runs in executor to avoid blocking."""

    def _fetch() -> tuple[int, str]:
        req = Request(url)
        try:
            with urlopen(req, timeout=timeout) as resp:
                return (resp.status, resp.read().decode("utf-8", errors="replace"))
        except URLError as e:
            return (0, str(e))
        except Exception as e:
            return (0, str(e))

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _fetch)


def _timed(start: float) -> int:
    """Return elapsed milliseconds since start."""
    return int((time.monotonic() - start) * 1000)


# ── Docker checks ────────────────────────────────────────────────────────────


@check_group("docker")
async def check_docker_daemon() -> list[CheckResult]:
    t = time.monotonic()
    rc, out, err = await run_cmd(["docker", "info", "--format", "{{.ServerVersion}}"])
    if rc == 0 and out:
        return [
            CheckResult(
                name="docker.daemon",
                group="docker",
                status=Status.HEALTHY,
                message=f"Docker {out}",
                duration_ms=_timed(t),
            )
        ]
    return [
        CheckResult(
            name="docker.daemon",
            group="docker",
            status=Status.FAILED,
            message="Docker daemon unreachable",
            detail=err or out,
            remediation="sudo systemctl start docker",
            duration_ms=_timed(t),
        )
    ]


@check_group("docker")
async def check_compose_file() -> list[CheckResult]:
    t = time.monotonic()
    if COMPOSE_FILE.is_file():
        return [
            CheckResult(
                name="docker.compose_file",
                group="docker",
                status=Status.HEALTHY,
                message=str(COMPOSE_FILE),
                duration_ms=_timed(t),
            )
        ]
    return [
        CheckResult(
            name="docker.compose_file",
            group="docker",
            status=Status.FAILED,
            message=f"Compose file missing: {COMPOSE_FILE}",
            remediation=f"ls -la {COMPOSE_FILE.parent}/",
            duration_ms=_timed(t),
        )
    ]


@check_group("docker")
async def check_docker_containers() -> list[CheckResult]:
    t = time.monotonic()
    rc, out, err = await run_cmd(
        [
            "docker",
            "compose",
            "-f",
            str(COMPOSE_FILE),
            "ps",
            "--format",
            "json",
        ]
    )
    if rc != 0:
        return [
            CheckResult(
                name="docker.containers",
                group="docker",
                status=Status.FAILED,
                message="docker compose ps failed",
                detail=err or out,
                duration_ms=_timed(t),
            )
        ]

    results: list[CheckResult] = []
    if not out:
        return [
            CheckResult(
                name="docker.containers",
                group="docker",
                status=Status.FAILED,
                message="No containers found",
                remediation=f"cd {COMPOSE_FILE.parent} && docker compose up -d",
                duration_ms=_timed(t),
            )
        ]

    # NDJSON: one JSON object per line
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            container = json.loads(line)
        except json.JSONDecodeError:
            continue

        name = container.get("Name", container.get("Service", "unknown"))
        service = container.get("Service", name)
        state = container.get("State", "unknown").lower()
        health = container.get("Health", "").lower()

        is_core = service in CORE_CONTAINERS
        running = state == "running"

        if running and health in ("healthy", "", "starting"):
            status = Status.HEALTHY
            msg = f"running ({health})" if health else "running"
        elif running and health == "unhealthy":
            status = Status.DEGRADED
            msg = "running (unhealthy)"
        else:
            status = Status.FAILED if is_core else Status.DEGRADED
            msg = f"not running ({state})" if not is_core else f"not running ({state}) — CORE"

        remediation = None
        if not running:
            remediation = f"cd {COMPOSE_FILE.parent} && docker compose up -d {shlex.quote(service)}"

        results.append(
            CheckResult(
                name=f"docker.{service}",
                group="docker",
                status=status,
                message=msg,
                remediation=remediation,
                duration_ms=_timed(t),
            )
        )

    return results


@check_group("docker")
async def check_agents_containers() -> list[CheckResult]:
    """Agents migrated from Docker to systemd user services."""
    t = time.monotonic()
    return [
        CheckResult(
            name="docker.agents_compose",
            group="docker",
            status=Status.HEALTHY,
            message="agents run as systemd user services (not Docker)",
            duration_ms=_timed(t),
        )
    ]


# ── GPU checks ───────────────────────────────────────────────────────────────


async def _nvidia_smi(query: str) -> tuple[int, str, str]:
    """Try nvidia-smi, fall back to /usr/bin/nvidia-smi."""
    rc, out, err = await run_cmd(
        [
            "nvidia-smi",
            f"--query-gpu={query}",
            "--format=csv,noheader,nounits",
        ]
    )
    if rc == 127:
        rc, out, err = await run_cmd(
            [
                "/usr/bin/nvidia-smi",
                f"--query-gpu={query}",
                "--format=csv,noheader,nounits",
            ]
        )
    return rc, out, err


@check_group("gpu")
async def check_gpu_available() -> list[CheckResult]:
    t = time.monotonic()
    rc, out, err = await _nvidia_smi("driver_version,name")
    if rc == 0 and out:
        parts = [p.strip() for p in out.split(",")]
        driver = parts[0] if parts else "?"
        gpu_name = parts[1] if len(parts) > 1 else "?"
        return [
            CheckResult(
                name="gpu.available",
                group="gpu",
                status=Status.HEALTHY,
                message=f"{gpu_name} (driver {driver})",
                duration_ms=_timed(t),
            )
        ]
    return [
        CheckResult(
            name="gpu.available",
            group="gpu",
            status=Status.FAILED,
            message="GPU not detected",
            detail=err or out,
            remediation="nvidia-smi",
            duration_ms=_timed(t),
        )
    ]


@check_group("gpu")
async def check_gpu_vram() -> list[CheckResult]:
    t = time.monotonic()
    rc, out, err = await _nvidia_smi("memory.used,memory.total,memory.free")
    if rc != 0:
        return [
            CheckResult(
                name="gpu.vram",
                group="gpu",
                status=Status.FAILED,
                message="Cannot query VRAM",
                detail=err,
                duration_ms=_timed(t),
            )
        ]

    parts = [p.strip() for p in out.split(",")]
    if len(parts) < 3:
        return [
            CheckResult(
                name="gpu.vram",
                group="gpu",
                status=Status.DEGRADED,
                message=f"Unexpected nvidia-smi output: {out}",
                duration_ms=_timed(t),
            )
        ]

    try:
        used, total, free = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return [
            CheckResult(
                name="gpu.vram",
                group="gpu",
                status=Status.DEGRADED,
                message=f"Cannot parse VRAM values: {out}",
                duration_ms=_timed(t),
            )
        ]

    pct = (used / total * 100) if total > 0 else 0
    if pct < 90:
        status = Status.HEALTHY
    elif pct < 95:
        status = Status.DEGRADED
    else:
        status = Status.FAILED

    msg = f"{used}MiB / {total}MiB ({pct:.0f}% used, {free}MiB free)"

    # Try to get loaded Ollama models for detail
    detail = None
    try:
        code, body = await http_get("http://localhost:11434/api/ps", timeout=2.0)
        if code == 200:
            data = json.loads(body)
            models = data.get("models", [])
            if models:
                model_names = [m.get("name", "?") for m in models]
                detail = f"Loaded Ollama models: {', '.join(model_names)}"
            else:
                detail = "No Ollama models currently loaded"
    except Exception:
        pass

    return [
        CheckResult(
            name="gpu.vram",
            group="gpu",
            status=status,
            message=msg,
            detail=detail,
            remediation="docker exec ollama ollama stop <model>"
            if status != Status.HEALTHY
            else None,
            duration_ms=_timed(t),
        )
    ]


@check_group("gpu")
async def check_gpu_temperature() -> list[CheckResult]:
    t = time.monotonic()
    rc, out, err = await _nvidia_smi("temperature.gpu")
    if rc != 0:
        return [
            CheckResult(
                name="gpu.temperature",
                group="gpu",
                status=Status.FAILED,
                message="Cannot query temperature",
                detail=err,
                duration_ms=_timed(t),
            )
        ]
    try:
        temp = int(out.strip())
    except ValueError:
        return [
            CheckResult(
                name="gpu.temperature",
                group="gpu",
                status=Status.DEGRADED,
                message=f"Cannot parse temperature: {out}",
                duration_ms=_timed(t),
            )
        ]

    if temp < 80:
        status = Status.HEALTHY
    elif temp < 90:
        status = Status.DEGRADED
    else:
        status = Status.FAILED

    return [
        CheckResult(
            name="gpu.temperature",
            group="gpu",
            status=status,
            message=f"{temp}°C",
            duration_ms=_timed(t),
        )
    ]


# ── Systemd checks ──────────────────────────────────────────────────────────


@check_group("systemd")
async def check_systemd_services() -> list[CheckResult]:
    services = [
        ("rag-ingest.service", True, "systemctl --user restart rag-ingest"),
        ("profile-update.timer", True, "systemctl --user enable --now profile-update.timer"),
        ("digest.timer", True, "systemctl --user enable --now digest.timer"),
        ("knowledge-maint.timer", True, "systemctl --user enable --now knowledge-maint.timer"),
        ("midi-route.service", False, None),
        ("gcalendar-sync.timer", True, "systemctl --user restart gcalendar-sync"),
        ("gdrive-sync.timer", True, "systemctl --user restart gdrive-sync"),
        ("gmail-sync.timer", True, "systemctl --user restart gmail-sync"),
        ("youtube-sync.timer", True, "systemctl --user restart youtube-sync"),
        ("chrome-sync.timer", True, "systemctl --user restart chrome-sync"),
        ("claude-code-sync.timer", True, "systemctl --user restart claude-code-sync"),
        ("obsidian-sync.timer", True, "systemctl --user restart obsidian-sync"),
    ]
    results: list[CheckResult] = []

    for unit, required, fix_cmd in services:
        t = time.monotonic()
        rc, out, err = await run_cmd(["systemctl", "--user", "is-active", unit])
        active = out.strip() == "active"

        detail = None
        # For timers, also check enabled status and next trigger
        if unit.endswith(".timer"):
            rc_en, out_en, _ = await run_cmd(["systemctl", "--user", "is-enabled", unit])
            enabled = out_en.strip() == "enabled"

            if not enabled:
                results.append(
                    CheckResult(
                        name=f"systemd.{unit}",
                        group="systemd",
                        status=Status.FAILED if required else Status.HEALTHY,
                        message="not enabled",
                        remediation=fix_cmd,
                        duration_ms=_timed(t),
                    )
                )
                continue

            # Parse next trigger time
            rc_t, out_t, _ = await run_cmd(
                [
                    "systemctl",
                    "--user",
                    "list-timers",
                    unit,
                    "--no-pager",
                ]
            )
            if rc_t == 0 and out_t:
                # Try to extract the NEXT column from the timer listing
                lines = out_t.strip().splitlines()
                if len(lines) >= 2:
                    detail = lines[1].strip()

        if active:
            status = Status.HEALTHY
            msg = "active"
        elif required:
            status = Status.FAILED
            msg = out.strip() or "inactive"
        else:
            status = Status.HEALTHY
            msg = f"{out.strip() or 'inactive'} (optional)"

        results.append(
            CheckResult(
                name=f"systemd.{unit}",
                group="systemd",
                status=status,
                message=msg,
                detail=detail,
                remediation=fix_cmd if not active and required else None,
                duration_ms=_timed(t),
            )
        )

        # For active timers, also check if the triggered service is in failed state
        if active and unit.endswith(".timer"):
            svc = unit.replace(".timer", ".service")
            t2 = time.monotonic()
            rc_s, out_s, _ = await run_cmd(["systemctl", "--user", "is-failed", svc])
            if out_s.strip() == "failed":
                results.append(
                    CheckResult(
                        name=f"systemd.{svc}",
                        group="systemd",
                        status=Status.DEGRADED,
                        message="last run failed (timer will retry)",
                        remediation=f"systemctl --user reset-failed {svc} && systemctl --user start {svc}",
                        duration_ms=_timed(t2),
                    )
                )

    return results


@check_group("systemd")
async def check_systemd_drift() -> list[CheckResult]:
    """Verify deployed systemd units match repo source."""
    t = time.monotonic()
    from shared.config import SYSTEMD_USER_DIR

    repo_units = AI_AGENTS_DIR / "systemd" / "units"
    deployed_dir = SYSTEMD_USER_DIR

    if not repo_units.exists():
        return [
            CheckResult(
                name="systemd.drift",
                group="systemd",
                status=Status.HEALTHY,
                message="No repo units directory found (skipped)",
                duration_ms=_timed(t),
            )
        ]

    drifted = []
    for unit_file in sorted(repo_units.iterdir()):
        if unit_file.suffix not in (".service", ".timer"):
            continue
        deployed = deployed_dir / unit_file.name
        if not deployed.exists():
            drifted.append(f"{unit_file.name}: not deployed")
        elif unit_file.read_text() != deployed.read_text():
            drifted.append(f"{unit_file.name}: content differs")

    if drifted:
        return [
            CheckResult(
                name="systemd.drift",
                group="systemd",
                status=Status.DEGRADED,
                message=f"Systemd drift: {', '.join(drifted[:3])}{'...' if len(drifted) > 3 else ''}",
                remediation="cd ~/projects/ai-agents && make install-systemd",
                duration_ms=_timed(t),
            )
        ]
    return [
        CheckResult(
            name="systemd.drift",
            group="systemd",
            status=Status.HEALTHY,
            message=f"All {sum(1 for f in repo_units.iterdir() if f.suffix in ('.service', '.timer'))} units match deployed",
            duration_ms=_timed(t),
        )
    ]


# ── Qdrant checks ────────────────────────────────────────────────────────────


@check_group("qdrant")
async def check_qdrant_health() -> list[CheckResult]:
    t = time.monotonic()
    code, body = await http_get("http://localhost:6333/healthz")
    if code == 200:
        return [
            CheckResult(
                name="qdrant.health",
                group="qdrant",
                status=Status.HEALTHY,
                message="Qdrant healthy",
                duration_ms=_timed(t),
            )
        ]
    return [
        CheckResult(
            name="qdrant.health",
            group="qdrant",
            status=Status.FAILED,
            message=f"Qdrant unreachable (HTTP {code})",
            detail=body[:200] if body else None,
            remediation=f"cd {COMPOSE_FILE.parent} && docker compose up -d qdrant",
            duration_ms=_timed(t),
        )
    ]


@check_group("qdrant")
async def check_qdrant_collections() -> list[CheckResult]:
    t = time.monotonic()
    code, body = await http_get("http://localhost:6333/collections")
    if code != 200:
        return [
            CheckResult(
                name="qdrant.collections",
                group="qdrant",
                status=Status.FAILED,
                message="Cannot list collections",
                detail=body[:200] if body else None,
                duration_ms=_timed(t),
            )
        ]

    try:
        data = json.loads(body)
        existing = {c["name"] for c in data.get("result", {}).get("collections", [])}
    except (json.JSONDecodeError, KeyError):
        return [
            CheckResult(
                name="qdrant.collections",
                group="qdrant",
                status=Status.DEGRADED,
                message="Cannot parse collections response",
                duration_ms=_timed(t),
            )
        ]

    results: list[CheckResult] = []
    for coll in sorted(REQUIRED_QDRANT_COLLECTIONS):
        if coll in existing:
            # Fetch point count
            detail = None
            c2, b2 = await http_get(f"http://localhost:6333/collections/{coll}")
            if c2 == 200:
                try:
                    cdata = json.loads(b2)
                    points = cdata.get("result", {}).get("points_count", "?")
                    detail = f"{points} points"
                except (json.JSONDecodeError, KeyError):
                    pass
            results.append(
                CheckResult(
                    name=f"qdrant.{coll}",
                    group="qdrant",
                    status=Status.HEALTHY,
                    message="exists",
                    detail=detail,
                    duration_ms=_timed(t),
                )
            )
        else:
            results.append(
                CheckResult(
                    name=f"qdrant.{coll}",
                    group="qdrant",
                    status=Status.FAILED,
                    message="missing",
                    remediation=(
                        f"curl -X PUT http://localhost:6333/collections/{coll} "
                        f"-H 'Content-Type: application/json' "
                        f'-d \'{{"vectors": {{"size": 768, "distance": "Cosine"}}}}\''
                    ),
                    duration_ms=_timed(t),
                )
            )

    return results


# ── Profile checks ───────────────────────────────────────────────────────────


@check_group("profiles")
async def check_profile_files() -> list[CheckResult]:
    t = time.monotonic()
    files = {
        ".state.json": Status.FAILED,
        "operator-profile.json": Status.FAILED,
    }
    results: list[CheckResult] = []

    for filename, severity_if_missing in files.items():
        path = PROFILES_DIR / filename
        if not path.is_file():
            results.append(
                CheckResult(
                    name=f"profiles.{filename}",
                    group="profiles",
                    status=severity_if_missing,
                    message=f"missing: {path}",
                    remediation=(
                        f'cd {PROFILES_DIR.parent} && eval "$(<.envrc)" && '
                        "uv run python -m agents.profiler --auto"
                    ),
                    duration_ms=_timed(t),
                )
            )
            continue

        # Validate JSON parse
        try:
            text = path.read_text()
            json.loads(text)
            results.append(
                CheckResult(
                    name=f"profiles.{filename}",
                    group="profiles",
                    status=Status.HEALTHY,
                    message=f"valid JSON ({len(text)} bytes)",
                    duration_ms=_timed(t),
                )
            )
        except (json.JSONDecodeError, OSError) as e:
            results.append(
                CheckResult(
                    name=f"profiles.{filename}",
                    group="profiles",
                    status=Status.DEGRADED,
                    message=f"invalid JSON: {e}",
                    duration_ms=_timed(t),
                )
            )

    return results


@check_group("profiles")
async def check_profile_staleness() -> list[CheckResult]:
    t = time.monotonic()
    state_file = PROFILES_DIR / ".state.json"
    if not state_file.is_file():
        return [
            CheckResult(
                name="profiles.staleness",
                group="profiles",
                status=Status.FAILED,
                message="No state file — cannot determine staleness",
                duration_ms=_timed(t),
            )
        ]

    try:
        data = json.loads(state_file.read_text())
        last_run_str = data.get("last_run")
        if not last_run_str:
            return [
                CheckResult(
                    name="profiles.staleness",
                    group="profiles",
                    status=Status.DEGRADED,
                    message="No last_run timestamp in state file",
                    duration_ms=_timed(t),
                )
            ]

        last_run = datetime.fromisoformat(last_run_str)
        now = datetime.now(UTC)
        # Make last_run tz-aware if it isn't
        if last_run.tzinfo is None:
            last_run = last_run.replace(tzinfo=UTC)
        age_hours = (now - last_run).total_seconds() / 3600

        if age_hours < 24:
            status = Status.HEALTHY
        elif age_hours < 72:
            status = Status.DEGRADED
        else:
            status = Status.FAILED

        msg = f"last run {age_hours:.0f}h ago"
        remediation = None
        if status != Status.HEALTHY:
            remediation = (
                f'cd {PROFILES_DIR.parent} && eval "$(<.envrc)" && '
                "uv run python -m agents.profiler --auto"
            )

        return [
            CheckResult(
                name="profiles.staleness",
                group="profiles",
                status=status,
                message=msg,
                remediation=remediation,
                duration_ms=_timed(t),
            )
        ]
    except (json.JSONDecodeError, OSError, ValueError) as e:
        return [
            CheckResult(
                name="profiles.staleness",
                group="profiles",
                status=Status.DEGRADED,
                message=f"Cannot parse state: {e}",
                duration_ms=_timed(t),
            )
        ]


# ── Endpoint checks ─────────────────────────────────────────────────────────


@check_group("endpoints")
async def check_service_endpoints() -> list[CheckResult]:
    endpoints = [
        ("endpoints.litellm", "http://localhost:4000/health/liveliness", True),
        ("endpoints.ollama", "http://localhost:11434/api/tags", True),
        ("endpoints.langfuse", "http://localhost:3000/", False),
        ("endpoints.open-webui", "http://localhost:8080/health", False),
    ]

    async def _check_one(name: str, url: str, is_core: bool) -> CheckResult:
        t = time.monotonic()
        code, body = await http_get(url, timeout=3.0)
        if 200 <= code < 400:
            return CheckResult(
                name=name,
                group="endpoints",
                status=Status.HEALTHY,
                message=f"HTTP {code}",
                duration_ms=_timed(t),
            )
        svc = name.split(".")[-1]
        return CheckResult(
            name=name,
            group="endpoints",
            status=Status.FAILED if is_core else Status.DEGRADED,
            message=f"unreachable (HTTP {code})" if code else "unreachable",
            detail=body[:200] if body and code == 0 else None,
            remediation=f"cd {COMPOSE_FILE.parent} && docker compose up -d {shlex.quote(svc)}",
            duration_ms=_timed(t),
        )

    tasks = [_check_one(name, url, core) for name, url, core in endpoints]
    return list(await asyncio.gather(*tasks))


# ── Credential checks ───────────────────────────────────────────────────────


@check_group("credentials")
async def check_pass_store() -> list[CheckResult]:
    t = time.monotonic()
    if PASSWORD_STORE.is_dir():
        return [
            CheckResult(
                name="credentials.pass_store",
                group="credentials",
                status=Status.HEALTHY,
                message=str(PASSWORD_STORE),
                duration_ms=_timed(t),
            )
        ]
    return [
        CheckResult(
            name="credentials.pass_store",
            group="credentials",
            status=Status.FAILED,
            message=f"Password store missing: {PASSWORD_STORE}",
            remediation="pass init <gpg-id>",
            duration_ms=_timed(t),
        )
    ]


@check_group("credentials")
async def check_pass_entries() -> list[CheckResult]:
    t = time.monotonic()
    results: list[CheckResult] = []
    for entry in PASS_ENTRIES:
        gpg_file = PASSWORD_STORE / f"{entry}.gpg"
        if gpg_file.is_file():
            results.append(
                CheckResult(
                    name=f"credentials.{entry}",
                    group="credentials",
                    status=Status.HEALTHY,
                    message="present",
                    duration_ms=_timed(t),
                )
            )
        else:
            results.append(
                CheckResult(
                    name=f"credentials.{entry}",
                    group="credentials",
                    status=Status.FAILED,
                    message="missing",
                    remediation=f"pass insert {shlex.quote(entry)}",
                    duration_ms=_timed(t),
                )
            )
    return results


# ── Disk checks ──────────────────────────────────────────────────────────────


@check_group("disk")
async def check_disk_usage() -> list[CheckResult]:
    t = time.monotonic()
    rc, out, err = await run_cmd(["df", "--output=pcent", "/home"])
    if rc != 0:
        return [
            CheckResult(
                name="disk.home",
                group="disk",
                status=Status.DEGRADED,
                message="Cannot check disk usage",
                detail=err,
                duration_ms=_timed(t),
            )
        ]

    lines = out.strip().splitlines()
    if len(lines) < 2:
        return [
            CheckResult(
                name="disk.home",
                group="disk",
                status=Status.DEGRADED,
                message=f"Unexpected df output: {out}",
                duration_ms=_timed(t),
            )
        ]

    try:
        pct = int(lines[-1].strip().rstrip("%"))
    except ValueError:
        return [
            CheckResult(
                name="disk.home",
                group="disk",
                status=Status.DEGRADED,
                message=f"Cannot parse disk usage: {lines[-1]}",
                duration_ms=_timed(t),
            )
        ]

    if pct < 85:
        status = Status.HEALTHY
    elif pct < 95:
        status = Status.DEGRADED
    else:
        status = Status.FAILED

    return [
        CheckResult(
            name="disk.home",
            group="disk",
            status=status,
            message=f"/home {pct}% used",
            remediation="docker system prune -f" if status != Status.HEALTHY else None,
            duration_ms=_timed(t),
        )
    ]


# ── Model checks ─────────────────────────────────────────────────────────────

EXPECTED_OLLAMA_MODELS = [
    "nomic-embed-text-v2-moe",
    "qwen3.5:27b",
    "qwen3:8b",
]


@check_group("models")
async def check_ollama_models() -> list[CheckResult]:
    """Verify expected Ollama models are pulled."""
    t = time.monotonic()
    code, body = await http_get("http://localhost:11434/api/tags", timeout=5.0)
    if code != 200:
        return [
            CheckResult(
                name="models.ollama_api",
                group="models",
                status=Status.FAILED,
                message="Cannot list Ollama models",
                detail=body[:200] if body else None,
                duration_ms=_timed(t),
            )
        ]

    try:
        data = json.loads(body)
        pulled = {m["name"].split(":")[0] for m in data.get("models", [])}
        # Also keep full name:tag for exact matching
        pulled_full = {m["name"] for m in data.get("models", [])}
    except (json.JSONDecodeError, KeyError):
        return [
            CheckResult(
                name="models.ollama_api",
                group="models",
                status=Status.DEGRADED,
                message="Cannot parse model list",
                duration_ms=_timed(t),
            )
        ]

    results: list[CheckResult] = []
    for model in EXPECTED_OLLAMA_MODELS:
        base = model.split(":")[0]
        if model in pulled_full or base in pulled:
            results.append(
                CheckResult(
                    name=f"models.{base}",
                    group="models",
                    status=Status.HEALTHY,
                    message="pulled",
                    duration_ms=_timed(t),
                )
            )
        else:
            results.append(
                CheckResult(
                    name=f"models.{base}",
                    group="models",
                    status=Status.DEGRADED,
                    message="not pulled",
                    remediation=f"docker exec ollama ollama pull {shlex.quote(model)}",
                    duration_ms=_timed(t),
                )
            )

    return results


# ── Auth validation checks ───────────────────────────────────────────────────


@check_group("auth")
async def check_litellm_auth() -> list[CheckResult]:
    """Validate LiteLLM API key actually works (not just file existence)."""
    t = time.monotonic()
    # Try to list models via LiteLLM — requires valid auth
    api_key, _ = _get_secret("LITELLM_API_KEY", "litellm/master-key")
    if not api_key or api_key == "changeme":
        return [
            CheckResult(
                name="auth.litellm",
                group="auth",
                status=Status.DEGRADED,
                message="LITELLM_API_KEY not available (env or pass)",
                detail="Set via: export LITELLM_API_KEY=$(pass show litellm/master-key)",
                duration_ms=_timed(t),
            )
        ]

    def _check() -> tuple[int, str]:
        req = Request(
            "http://localhost:4000/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        try:
            with urlopen(req, timeout=5) as resp:
                return (resp.status, resp.read().decode("utf-8", errors="replace"))
        except URLError as e:
            return (0, str(e))
        except Exception as e:
            return (0, str(e))

    loop = asyncio.get_running_loop()
    code, body = await loop.run_in_executor(None, _check)

    if code == 200:
        try:
            model_count = len(json.loads(body).get("data", []))
            return [
                CheckResult(
                    name="auth.litellm",
                    group="auth",
                    status=Status.HEALTHY,
                    message=f"authenticated ({model_count} models)",
                    duration_ms=_timed(t),
                )
            ]
        except (json.JSONDecodeError, KeyError):
            pass
        return [
            CheckResult(
                name="auth.litellm",
                group="auth",
                status=Status.HEALTHY,
                message="authenticated",
                duration_ms=_timed(t),
            )
        ]

    return [
        CheckResult(
            name="auth.litellm",
            group="auth",
            status=Status.FAILED,
            message=f"auth failed (HTTP {code})",
            detail=body[:200] if body else None,
            remediation="pass show litellm/master-key",
            duration_ms=_timed(t),
        )
    ]


@check_group("auth")
async def check_langfuse_auth() -> list[CheckResult]:
    """Validate Langfuse credentials work."""
    t = time.monotonic()
    pk, _ = _get_secret("LANGFUSE_PUBLIC_KEY", "langfuse/public-key")
    sk, _ = _get_secret("LANGFUSE_SECRET_KEY", "langfuse/secret-key")

    if not pk or not sk:
        return [
            CheckResult(
                name="auth.langfuse",
                group="auth",
                status=Status.DEGRADED,
                message="Langfuse keys not available (env or pass)",
                detail='Load via: eval "$(<.envrc)" in ai-agents dir',
                duration_ms=_timed(t),
            )
        ]

    import base64

    def _check() -> tuple[int, str]:
        creds = base64.b64encode(f"{pk}:{sk}".encode()).decode()
        req = Request(
            "http://localhost:3000/api/public/health",
            headers={"Authorization": f"Basic {creds}"},
        )
        try:
            with urlopen(req, timeout=5) as resp:
                return (resp.status, resp.read().decode("utf-8", errors="replace"))
        except URLError as e:
            return (0, str(e))
        except Exception as e:
            return (0, str(e))

    loop = asyncio.get_running_loop()
    code, body = await loop.run_in_executor(None, _check)

    if code == 200:
        return [
            CheckResult(
                name="auth.langfuse",
                group="auth",
                status=Status.HEALTHY,
                message="authenticated",
                duration_ms=_timed(t),
            )
        ]

    return [
        CheckResult(
            name="auth.langfuse",
            group="auth",
            status=Status.DEGRADED,
            message=f"auth failed (HTTP {code})",
            detail=body[:200] if body else None,
            duration_ms=_timed(t),
        )
    ]


# ── Connectivity checks (multi-channel access) ──────────────────────────────


@check_group("connectivity")
async def check_tailscale() -> list[CheckResult]:
    """Check Tailscale VPN connectivity."""
    t = time.monotonic()
    rc, out, err = await run_cmd(["tailscale", "status", "--json"])
    if rc != 0:
        if "not found" in (err or ""):
            # Tailscale not installed yet — planned infrastructure, not a failure
            return [
                CheckResult(
                    name="connectivity.tailscale",
                    group="connectivity",
                    status=Status.HEALTHY,
                    message="not installed (planned)",
                    duration_ms=_timed(t),
                )
            ]
        return [
            CheckResult(
                name="connectivity.tailscale",
                group="connectivity",
                status=Status.DEGRADED,
                message=f"tailscale error (rc={rc})",
                detail=(err or out or "")[:200],
                duration_ms=_timed(t),
            )
        ]

    try:
        import json as _json

        data = _json.loads(out)
        self_status = data.get("Self", {}).get("Online", False)
        peer_count = len([p for p in data.get("Peer", {}).values() if p.get("Online")])
        if self_status:
            return [
                CheckResult(
                    name="connectivity.tailscale",
                    group="connectivity",
                    status=Status.HEALTHY,
                    message=f"online, {peer_count} peer(s)",
                    duration_ms=_timed(t),
                )
            ]
        return [
            CheckResult(
                name="connectivity.tailscale",
                group="connectivity",
                status=Status.DEGRADED,
                message="tailscale offline",
                remediation="sudo tailscale up",
                duration_ms=_timed(t),
            )
        ]
    except Exception as e:
        return [
            CheckResult(
                name="connectivity.tailscale",
                group="connectivity",
                status=Status.DEGRADED,
                message=f"tailscale status parse error: {e}",
                duration_ms=_timed(t),
            )
        ]


@check_group("connectivity")
async def check_ntfy() -> list[CheckResult]:
    """Check ntfy push notification service reachability."""
    t = time.monotonic()
    ntfy_url = os.environ.get("NTFY_BASE_URL", "http://localhost:8090")
    code, body = await http_get(f"{ntfy_url}/v1/health", timeout=3.0)
    if 200 <= code < 400:
        return [
            CheckResult(
                name="connectivity.ntfy",
                group="connectivity",
                status=Status.HEALTHY,
                message=f"HTTP {code}",
                duration_ms=_timed(t),
            )
        ]
    return [
        CheckResult(
            name="connectivity.ntfy",
            group="connectivity",
            status=Status.DEGRADED,
            message=f"ntfy unreachable (HTTP {code})" if code else "ntfy unreachable",
            detail=body[:200] if body else None,
            remediation=f"cd {COMPOSE_FILE.parent} && docker compose --profile full up -d ntfy",
            duration_ms=_timed(t),
        )
    ]


@check_group("connectivity")
async def check_n8n_health() -> list[CheckResult]:
    """Check n8n workflow automation health endpoint."""
    t = time.monotonic()
    code, body = await http_get("http://localhost:5678/healthz", timeout=3.0)
    if 200 <= code < 400:
        return [
            CheckResult(
                name="connectivity.n8n",
                group="connectivity",
                status=Status.HEALTHY,
                message=f"HTTP {code}",
                duration_ms=_timed(t),
            )
        ]
    return [
        CheckResult(
            name="connectivity.n8n",
            group="connectivity",
            status=Status.DEGRADED,
            message=f"n8n unreachable (HTTP {code})" if code else "n8n unreachable",
            remediation=f"cd {COMPOSE_FILE.parent} && docker compose --profile full up -d n8n",
            duration_ms=_timed(t),
        )
    ]


@check_group("connectivity")
async def check_obsidian_sync() -> list[CheckResult]:
    """Check Obsidian desktop app is running (sync runs within the app)."""
    t = time.monotonic()
    rc, out, err = await run_cmd(["pgrep", "-x", "obsidian"])
    if rc == 0:
        return [
            CheckResult(
                name="connectivity.obsidian",
                group="connectivity",
                status=Status.HEALTHY,
                message="running",
                duration_ms=_timed(t),
            )
        ]
    return [
        CheckResult(
            name="connectivity.obsidian",
            group="connectivity",
            status=Status.DEGRADED,
            message="not running (desktop app)",
            duration_ms=_timed(t),
        )
    ]


@check_group("connectivity")
async def check_gdrive_sync_freshness() -> list[CheckResult]:
    """Check Google Drive sync freshness by examining rclone sync target mtime."""
    t = time.monotonic()
    gdrive_dir = RAG_SOURCES_DIR / "gdrive"
    if not gdrive_dir.exists():
        return [
            CheckResult(
                name="connectivity.gdrive-sync",
                group="connectivity",
                status=Status.HEALTHY,
                message="not configured",
                duration_ms=_timed(t),
            )
        ]

    # Check gdrive sync state freshness (runs as systemd timer or manual)
    state_file = Path.home() / ".cache" / "gdrive-sync" / "state.json"
    if state_file.exists():
        age_hours = (time.time() - state_file.stat().st_mtime) / 3600
        if age_hours > 24:
            return [
                CheckResult(
                    name="connectivity.gdrive-sync",
                    group="connectivity",
                    status=Status.DEGRADED,
                    message=f"gdrive sync state is {age_hours:.0f}h old",
                    remediation="cd ~/projects/hapax-council && uv run python -m agents.gdrive_sync --auto",
                    duration_ms=_timed(t),
                )
            ]

    return [
        CheckResult(
            name="connectivity.gdrive-sync",
            group="connectivity",
            status=Status.HEALTHY,
            message="sync-pipeline container running",
            duration_ms=_timed(t),
        )
    ]


@check_group("connectivity")
async def check_watch_connected() -> list[CheckResult]:
    """Check if Pixel Watch is streaming sensor data (non-critical, tier 3)."""
    t = time.monotonic()
    conn_file = WATCH_STATE_DIR / "connection.json"
    if not conn_file.exists():
        return [
            CheckResult(
                name="connectivity.watch",
                group="connectivity",
                status=Status.HEALTHY,
                message="not configured",
                duration_ms=_timed(t),
                tier=3,
            )
        ]
    try:
        data = json.loads(conn_file.read_text())
    except (json.JSONDecodeError, OSError):
        return [
            CheckResult(
                name="connectivity.watch",
                group="connectivity",
                status=Status.DEGRADED,
                message="connection.json unreadable",
                duration_ms=_timed(t),
                tier=3,
            )
        ]
    age = time.time() - data.get("last_seen_epoch", 0)
    battery = data.get("battery_pct", "?")
    if age > 300:
        return [
            CheckResult(
                name="connectivity.watch",
                group="connectivity",
                status=Status.DEGRADED,
                message=f"Watch last seen {age / 60:.0f}m ago (battery {battery}%)",
                duration_ms=_timed(t),
                tier=3,
            )
        ]
    return [
        CheckResult(
            name="connectivity.watch",
            group="connectivity",
            status=Status.HEALTHY,
            message=f"Watch connected, battery {battery}%",
            duration_ms=_timed(t),
            tier=3,
        )
    ]


@check_group("connectivity")
async def check_phone_connected() -> list[CheckResult]:
    """Check if Pixel 10 phone is sending heartbeats (non-critical, tier 3)."""
    t = time.monotonic()
    conn_file = WATCH_STATE_DIR / "phone_connection.json"
    if not conn_file.exists():
        return [
            CheckResult(
                name="connectivity.phone",
                group="connectivity",
                status=Status.HEALTHY,
                message="not configured",
                duration_ms=_timed(t),
                tier=3,
            )
        ]
    try:
        data = json.loads(conn_file.read_text())
    except (json.JSONDecodeError, OSError):
        return [
            CheckResult(
                name="connectivity.phone",
                group="connectivity",
                status=Status.DEGRADED,
                message="phone_connection.json unreadable",
                duration_ms=_timed(t),
                tier=3,
            )
        ]
    age = time.time() - data.get("last_seen_epoch", 0)
    battery = data.get("battery_pct", "?")
    if age > 300:
        return [
            CheckResult(
                name="connectivity.phone",
                group="connectivity",
                status=Status.DEGRADED,
                message=f"Phone last seen {age / 60:.0f}m ago (battery {battery}%)",
                duration_ms=_timed(t),
                tier=3,
            )
        ]
    return [
        CheckResult(
            name="connectivity.phone",
            group="connectivity",
            status=Status.HEALTHY,
            message=f"Phone connected, battery {battery}%",
            duration_ms=_timed(t),
            tier=3,
        )
    ]


# ── Latency checks ──────────────────────────────────────────────────────────


async def _tcp_connect_ms(host: str, port: int, timeout: float = 3.0) -> float | None:
    """Measure TCP connect time in milliseconds. Returns None on failure."""
    import socket as _socket

    loop = asyncio.get_running_loop()

    def _connect() -> float | None:
        sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            t0 = time.monotonic()
            sock.connect((host, port))
            return (time.monotonic() - t0) * 1000
        except (TimeoutError, OSError):
            return None
        finally:
            sock.close()

    return await loop.run_in_executor(None, _connect)


async def _http_latency_ms(url: str, timeout: float = 3.0) -> float | None:
    """Measure HTTP response time in milliseconds. Returns None on failure.

    Times the HTTP call inside the executor thread to exclude thread pool
    queue wait time, which can be significant under contention.
    """

    def _timed_fetch() -> float | None:
        req = Request(url)
        t0 = time.monotonic()
        try:
            with urlopen(req, timeout=timeout) as resp:
                resp.read()
                if 200 <= resp.status < 400:
                    return (time.monotonic() - t0) * 1000
        except Exception:
            pass
        return None

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _timed_fetch)


LATENCY_THRESHOLDS = {
    "latency.litellm": ("http://localhost:4000/health/liveliness", 200.0),
    "latency.qdrant": ("http://localhost:6333/healthz", 100.0),
    "latency.ollama": ("http://localhost:11434/api/tags", 500.0),
}


def _get_threshold(check_name: str, default: float) -> float:
    """Load threshold override if available, else return default."""
    try:
        from shared.threshold_tuner import get_threshold

        return get_threshold(check_name, default)
    except Exception:
        return default


@check_group("latency")
async def check_service_latency() -> list[CheckResult]:
    """Check HTTP response times for core services."""
    results: list[CheckResult] = []
    for name, (url, default_ms) in LATENCY_THRESHOLDS.items():
        t = time.monotonic()
        threshold_ms = _get_threshold(name, default_ms)
        latency = await _http_latency_ms(url)
        if latency is None:
            results.append(
                CheckResult(
                    name=name,
                    group="latency",
                    status=Status.FAILED,
                    message="unreachable",
                    duration_ms=_timed(t),
                )
            )
        elif latency > threshold_ms:
            results.append(
                CheckResult(
                    name=name,
                    group="latency",
                    status=Status.DEGRADED,
                    message=f"{latency:.0f}ms (threshold: {threshold_ms:.0f}ms)",
                    duration_ms=_timed(t),
                )
            )
        else:
            results.append(
                CheckResult(
                    name=name,
                    group="latency",
                    status=Status.HEALTHY,
                    message=f"{latency:.0f}ms",
                    duration_ms=_timed(t),
                )
            )
    return results


@check_group("latency")
async def check_postgres_latency() -> list[CheckResult]:
    """Check PostgreSQL TCP connect time."""
    t = time.monotonic()
    latency = await _tcp_connect_ms("localhost", 5432)
    threshold = 50.0
    if latency is None:
        return [
            CheckResult(
                name="latency.postgres",
                group="latency",
                status=Status.FAILED,
                message="unreachable",
                duration_ms=_timed(t),
            )
        ]
    if latency > threshold:
        return [
            CheckResult(
                name="latency.postgres",
                group="latency",
                status=Status.DEGRADED,
                message=f"{latency:.0f}ms (threshold: {threshold:.0f}ms)",
                duration_ms=_timed(t),
            )
        ]
    return [
        CheckResult(
            name="latency.postgres",
            group="latency",
            status=Status.HEALTHY,
            message=f"{latency:.0f}ms",
            duration_ms=_timed(t),
        )
    ]


# ── Secret validation ────────────────────────────────────────────────────────

REQUIRED_SECRETS = {
    "LITELLM_API_KEY": "litellm/master-key",
    "LANGFUSE_PUBLIC_KEY": "langfuse/public-key",
    "LANGFUSE_SECRET_KEY": "langfuse/secret-key",
    "ANTHROPIC_API_KEY": "api/anthropic",
}


def _pass_show(path: str) -> str:
    """Try to read a secret from pass. Returns empty string on failure."""
    try:
        result = subprocess.run(
            ["pass", "show", path],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return ""


def _get_secret(env_var: str, pass_path: str) -> tuple[str, str]:
    """Get secret from env var, falling back to pass. Returns (value, source)."""
    val = os.environ.get(env_var, "")
    if val:
        return val, "env"
    val = _pass_show(pass_path)
    if val:
        return val, "pass"
    return "", ""


@check_group("secrets")
async def check_env_secrets() -> list[CheckResult]:
    """Validate required secrets are accessible (env var or pass store)."""
    results: list[CheckResult] = []
    for var, pass_path in REQUIRED_SECRETS.items():
        t = time.monotonic()
        val, source = _get_secret(var, pass_path)
        if not val:
            results.append(
                CheckResult(
                    name=f"secrets.{var.lower()}",
                    group="secrets",
                    status=Status.FAILED,
                    message=f"{var} not set (env or pass)",
                    duration_ms=_timed(t),
                )
            )
        elif len(val) < 8:
            results.append(
                CheckResult(
                    name=f"secrets.{var.lower()}",
                    group="secrets",
                    status=Status.DEGRADED,
                    message=f"{var} suspiciously short ({len(val)} chars, via {source})",
                    duration_ms=_timed(t),
                )
            )
        else:
            results.append(
                CheckResult(
                    name=f"secrets.{var.lower()}",
                    group="secrets",
                    status=Status.HEALTHY,
                    message=f"{var} ok ({len(val)} chars, via {source})",
                    duration_ms=_timed(t),
                )
            )
    return results


# ── Queue/backlog monitoring ─────────────────────────────────────────────────


@check_group("queues")
async def check_rag_retry_queue() -> list[CheckResult]:
    """Check RAG ingestion retry queue depth."""
    t = time.monotonic()
    retry_file = RAG_INGEST_STATE_DIR / "retry-queue.jsonl"
    if not retry_file.exists():
        return [
            CheckResult(
                name="queues.rag-retry",
                group="queues",
                status=Status.HEALTHY,
                message="no retry queue",
                duration_ms=_timed(t),
            )
        ]
    try:
        lines = [l for l in retry_file.read_text().splitlines() if l.strip()]
        depth = len(lines)
        if depth > 50:
            return [
                CheckResult(
                    name="queues.rag-retry",
                    group="queues",
                    status=Status.DEGRADED,
                    message=f"{depth} items pending retry",
                    duration_ms=_timed(t),
                )
            ]
        return [
            CheckResult(
                name="queues.rag-retry",
                group="queues",
                status=Status.HEALTHY,
                message=f"{depth} items" if depth else "empty",
                duration_ms=_timed(t),
            )
        ]
    except OSError as e:
        return [
            CheckResult(
                name="queues.rag-retry",
                group="queues",
                status=Status.DEGRADED,
                message=f"could not read queue: {e}",
                duration_ms=_timed(t),
            )
        ]


@check_group("queues")
async def check_n8n_executions() -> list[CheckResult]:
    """Check n8n for waiting/stuck executions."""
    t = time.monotonic()
    code, body = await http_get("http://localhost:5678/healthz", timeout=3.0)
    if code == 0:
        return [
            CheckResult(
                name="queues.n8n-executions",
                group="queues",
                status=Status.DEGRADED,
                message="n8n unreachable",
                duration_ms=_timed(t),
            )
        ]
    return [
        CheckResult(
            name="queues.n8n-executions",
            group="queues",
            status=Status.HEALTHY,
            message="n8n responsive",
            duration_ms=_timed(t),
        )
    ]


# ── Budget tracking ──────────────────────────────────────────────────────────

DAILY_BUDGET_USD = 5.0


@check_group("budget")
async def check_daily_spend() -> list[CheckResult]:
    """Check LiteLLM daily spend against budget."""
    t = time.monotonic()
    try:
        code, body = await http_get(
            "http://localhost:4000/spend/report?group_by=api_key", timeout=5.0
        )
        if code != 200:
            return [
                CheckResult(
                    name="budget.daily-spend",
                    group="budget",
                    status=Status.HEALTHY,
                    message="spend endpoint unavailable (non-blocking)",
                    duration_ms=_timed(t),
                )
            ]
        data = json.loads(body)
        # LiteLLM spend report returns list of spend entries
        total = sum(entry.get("spend", 0) for entry in (data if isinstance(data, list) else []))
        if total > DAILY_BUDGET_USD:
            return [
                CheckResult(
                    name="budget.daily-spend",
                    group="budget",
                    status=Status.DEGRADED,
                    message=f"${total:.2f} spent (budget: ${DAILY_BUDGET_USD:.2f})",
                    duration_ms=_timed(t),
                )
            ]
        return [
            CheckResult(
                name="budget.daily-spend",
                group="budget",
                status=Status.HEALTHY,
                message=f"${total:.2f} / ${DAILY_BUDGET_USD:.2f}",
                duration_ms=_timed(t),
            )
        ]
    except Exception as e:
        return [
            CheckResult(
                name="budget.daily-spend",
                group="budget",
                status=Status.HEALTHY,
                message=f"could not check spend: {e}",
                duration_ms=_timed(t),
            )
        ]


# ── Capacity checks ─────────────────────────────────────────────────────────


@check_group("capacity")
async def check_capacity_forecasts() -> list[CheckResult]:
    """Alert when any resource is forecast to exhaust within 7 days."""
    t = time.monotonic()
    try:
        from shared.capacity import forecast_exhaustion

        forecasts = forecast_exhaustion()
        if not forecasts:
            return [
                CheckResult(
                    name="capacity.forecast",
                    group="capacity",
                    status=Status.HEALTHY,
                    message="insufficient data for forecast",
                    duration_ms=_timed(t),
                )
            ]
        results = []
        for f in forecasts:
            if f.is_warning(threshold_days=7.0):
                results.append(
                    CheckResult(
                        name=f"capacity.{f.resource}",
                        group="capacity",
                        status=Status.DEGRADED,
                        message=f"{f.resource}: ~{f.days_to_exhaustion:.0f} days to exhaustion",
                        duration_ms=_timed(t),
                    )
                )
            else:
                results.append(
                    CheckResult(
                        name=f"capacity.{f.resource}",
                        group="capacity",
                        status=Status.HEALTHY,
                        message=f"{f.resource}: {f.trend}",
                        duration_ms=_timed(t),
                    )
                )
        return results
    except Exception as e:
        return [
            CheckResult(
                name="capacity.forecast",
                group="capacity",
                status=Status.HEALTHY,
                message=f"forecast unavailable: {e}",
                duration_ms=_timed(t),
            )
        ]


# ── Axiom infrastructure checks ──────────────────────────────────────────────


@check_group("axioms")
async def check_axiom_registry() -> list[CheckResult]:
    """Check axiom enforcement infrastructure is operational."""
    results = []
    t = time.monotonic()

    # Check registry exists and is parseable
    try:
        from shared.axiom_registry import AXIOMS_PATH, load_axioms

        registry_file = AXIOMS_PATH / "registry.yaml"
        if registry_file.exists():
            axioms = load_axioms()
            if axioms:
                results.append(
                    CheckResult(
                        name="axiom.registry",
                        group="axioms",
                        status=Status.HEALTHY,
                        message=f"Registry loaded: {len(axioms)} active axiom(s)",
                        duration_ms=_timed(t),
                    )
                )
            else:
                results.append(
                    CheckResult(
                        name="axiom.registry",
                        group="axioms",
                        status=Status.DEGRADED,
                        message="Registry exists but no active axioms found",
                        duration_ms=_timed(t),
                    )
                )
        else:
            results.append(
                CheckResult(
                    name="axiom.registry",
                    group="axioms",
                    status=Status.DEGRADED,
                    message="Axiom registry not found",
                    detail=str(registry_file),
                    duration_ms=_timed(t),
                )
            )
    except Exception as e:
        results.append(
            CheckResult(
                name="axiom.registry",
                group="axioms",
                status=Status.FAILED,
                message="Cannot check axiom registry",
                detail=str(e),
                duration_ms=_timed(t),
            )
        )

    # Check precedent collection exists in Qdrant
    t2 = time.monotonic()
    try:
        from shared.config import get_qdrant

        client = get_qdrant()
        collections = [c.name for c in client.get_collections().collections]
        if "axiom-precedents" in collections:
            info = client.get_collection("axiom-precedents")
            count = info.points_count
            results.append(
                CheckResult(
                    name="axiom.precedents",
                    group="axioms",
                    status=Status.HEALTHY,
                    message=f"Precedent collection: {count} point(s)",
                    duration_ms=_timed(t2),
                )
            )
        else:
            results.append(
                CheckResult(
                    name="axiom.precedents",
                    group="axioms",
                    status=Status.DEGRADED,
                    message="axiom-precedents collection not found in Qdrant",
                    remediation="Run: uv run python -c 'from shared.axiom_precedents import PrecedentStore; PrecedentStore().ensure_collection()'",
                    duration_ms=_timed(t2),
                )
            )
    except Exception as e:
        results.append(
            CheckResult(
                name="axiom.precedents",
                group="axioms",
                status=Status.FAILED,
                message="Cannot check precedent collection",
                detail=str(e),
                duration_ms=_timed(t2),
            )
        )

    # Check implications exist for active axioms
    t3 = time.monotonic()
    try:
        from shared.axiom_registry import load_axioms as _load_axioms
        from shared.axiom_registry import load_implications

        active = _load_axioms()
        if active:
            missing = [a.id for a in active if not load_implications(a.id)]
            if not missing:
                results.append(
                    CheckResult(
                        name="axiom.implications",
                        group="axioms",
                        status=Status.HEALTHY,
                        message="All active axioms have implication files",
                        duration_ms=_timed(t3),
                    )
                )
            else:
                results.append(
                    CheckResult(
                        name="axiom.implications",
                        group="axioms",
                        status=Status.DEGRADED,
                        message=f"Missing implications for: {', '.join(missing)}",
                        remediation=f"Run: uv run python -m shared.axiom_derivation --axiom {missing[0]}",
                        duration_ms=_timed(t3),
                    )
                )
    except Exception as e:
        results.append(
            CheckResult(
                name="axiom.implications",
                group="axioms",
                status=Status.FAILED,
                message="Cannot check axiom implications",
                detail=str(e),
                duration_ms=_timed(t3),
            )
        )

    # Check supremacy — domain T0 blocks vs constitutional T0 blocks
    t4 = time.monotonic()
    try:
        from shared.axiom_registry import validate_supremacy

        tensions = validate_supremacy()
        if not tensions:
            results.append(
                CheckResult(
                    name="axiom.supremacy",
                    group="axioms",
                    status=Status.HEALTHY,
                    message="No domain T0 tensions (or no domain axioms)",
                    duration_ms=_timed(t4),
                )
            )
        else:
            ids = ", ".join(t.domain_impl_id for t in tensions)
            results.append(
                CheckResult(
                    name="axiom.supremacy",
                    group="axioms",
                    status=Status.DEGRADED,
                    message=f"{len(tensions)} domain T0 block(s) need operator review: {ids}",
                    remediation="Run: /axiom-review to create precedents acknowledging these",
                    duration_ms=_timed(t4),
                )
            )
    except Exception as e:
        results.append(
            CheckResult(
                name="axiom.supremacy",
                group="axioms",
                status=Status.FAILED,
                message="Cannot check axiom supremacy",
                detail=str(e),
                duration_ms=_timed(t4),
            )
        )

    return results


@check_group("axioms")
async def check_axiom_hooks_active() -> list[CheckResult]:
    """Check that axiom enforcement hooks are firing (audit trail has recent entries)."""
    results = []
    t = time.monotonic()

    audit_dir = AXIOM_AUDIT_DIR
    if not audit_dir.exists():
        results.append(
            CheckResult(
                name="axiom.hooks_active",
                group="axioms",
                status=Status.DEGRADED,
                message="Audit directory missing — hooks may never have fired",
                remediation="Run: cd ~/projects/hapax-system && ./install.sh",
                duration_ms=_timed(t),
            )
        )
        return results

    # Check for audit files from today or yesterday
    from datetime import timedelta

    today = datetime.now(UTC).date()
    yesterday = today - timedelta(days=1)
    today_file = audit_dir / f"{today.isoformat()}.jsonl"
    yesterday_file = audit_dir / f"{yesterday.isoformat()}.jsonl"

    if today_file.exists():
        lines = sum(1 for _ in today_file.open())
        results.append(
            CheckResult(
                name="axiom.hooks_active",
                group="axioms",
                status=Status.HEALTHY,
                message=f"Audit trail active: {lines} entries today",
                duration_ms=_timed(t),
            )
        )
    elif yesterday_file.exists():
        results.append(
            CheckResult(
                name="axiom.hooks_active",
                group="axioms",
                status=Status.HEALTHY,
                message="Audit trail active (last entry yesterday)",
                duration_ms=_timed(t),
            )
        )
    else:
        # Check if any files exist at all
        any_files = list(audit_dir.glob("*.jsonl"))
        if any_files:
            newest = max(any_files, key=lambda p: p.stat().st_mtime)
            results.append(
                CheckResult(
                    name="axiom.hooks_active",
                    group="axioms",
                    status=Status.DEGRADED,
                    message=f"Audit trail stale — newest: {newest.name}",
                    remediation="Verify hooks in ~/.claude/settings.json are configured",
                    duration_ms=_timed(t),
                )
            )
        else:
            results.append(
                CheckResult(
                    name="axiom.hooks_active",
                    group="axioms",
                    status=Status.DEGRADED,
                    message="No audit trail entries found",
                    remediation="Run: cd ~/projects/hapax-system && ./install.sh && restart Claude Code",
                    duration_ms=_timed(t),
                )
            )

    return results


@check_group("axioms")
async def check_axiom_settings() -> list[CheckResult]:
    """Check that axiom hooks are properly configured in Claude Code settings."""
    results = []
    t = time.monotonic()

    settings_file = CLAUDE_CONFIG_DIR / "settings.json"
    if not settings_file.exists():
        results.append(
            CheckResult(
                name="axiom.settings",
                group="axioms",
                status=Status.DEGRADED,
                message="Claude Code settings.json not found",
                remediation="Run: cd ~/projects/hapax-system && ./install.sh",
                duration_ms=_timed(t),
            )
        )
        return results

    try:
        settings = json.loads(settings_file.read_text())
        hooks = settings.get("hooks", {})

        # Check for PreToolUse axiom-scan hook
        pre_hooks = hooks.get("PreToolUse", [])
        has_scan = any(
            "axiom-scan.sh" in h.get("command", "")
            for entry in pre_hooks
            for h in entry.get("hooks", [])
        )

        # Check for PostToolUse audit hook
        post_hooks = hooks.get("PostToolUse", [])
        has_audit = any(
            "axiom-audit.sh" in h.get("command", "")
            for entry in post_hooks
            for h in entry.get("hooks", [])
        )

        if has_scan and has_audit:
            results.append(
                CheckResult(
                    name="axiom.settings",
                    group="axioms",
                    status=Status.HEALTHY,
                    message="Hooks configured: scan (PreToolUse) + audit (PostToolUse)",
                    duration_ms=_timed(t),
                )
            )
        else:
            missing = []
            if not has_scan:
                missing.append("axiom-scan (PreToolUse)")
            if not has_audit:
                missing.append("axiom-audit (PostToolUse)")
            results.append(
                CheckResult(
                    name="axiom.settings",
                    group="axioms",
                    status=Status.DEGRADED,
                    message=f"Missing hooks: {', '.join(missing)}",
                    remediation="Run: cd ~/projects/hapax-system && ./install.sh",
                    duration_ms=_timed(t),
                )
            )
    except (json.JSONDecodeError, OSError) as e:
        results.append(
            CheckResult(
                name="axiom.settings",
                group="axioms",
                status=Status.FAILED,
                message="Cannot parse settings.json",
                detail=str(e),
                duration_ms=_timed(t),
            )
        )

    return results


@check_group("axioms")
async def check_axiom_ef_zero_config() -> list[CheckResult]:
    """Check that agents are runnable with zero required configuration (ex-init-001)."""
    results = []
    t = time.monotonic()

    agents_dir = AI_AGENTS_DIR / "agents"
    if not agents_dir.exists():
        results.append(
            CheckResult(
                name="axiom.ef_zero_config",
                group="axioms",
                status=Status.FAILED,
                message="Agents directory not found",
                detail=str(agents_dir),
                duration_ms=_timed(t),
            )
        )
        return results

    # Agents that should be runnable with no required args
    # research takes a positional query arg (acceptable — it's the input, not config)
    from shared.agent_registry import get_registry

    zero_config_agents = [a.id for a in get_registry().zero_config_agents()]

    violations = []
    for agent_name in zero_config_agents:
        agent_file = agents_dir / f"{agent_name}.py"
        if not agent_file.exists():
            continue
        # Quick check: look for required=True in add_argument that's not a flag
        content = agent_file.read_text()
        import re

        # Find add_argument calls with positional args (no -- prefix) that are required
        # Positional args are those without -- prefix and without default
        for match in re.finditer(r'add_argument\(\s*["\']([^-][^"\']*)["\']', content):
            arg_name = match.group(1)
            # Check if it has a default
            line_start = content.rfind("\n", 0, match.start()) + 1
            line_end = content.find("\n", match.end())
            line = content[line_start:line_end]
            if "default=" not in line and "nargs=" not in line:
                violations.append(f"{agent_name}: required positional arg '{arg_name}'")

    if not violations:
        results.append(
            CheckResult(
                name="axiom.ef_zero_config",
                group="axioms",
                status=Status.HEALTHY,
                message=f"All {len(zero_config_agents)} routine agents are zero-config runnable",
                duration_ms=_timed(t),
            )
        )
    else:
        results.append(
            CheckResult(
                name="axiom.ef_zero_config",
                group="axioms",
                status=Status.DEGRADED,
                message=f"ex-init-001 gap: {len(violations)} agent(s) require positional args",
                detail="; ".join(violations),
                remediation="Add defaults or make arguments optional with flags",
                duration_ms=_timed(t),
            )
        )

    return results


@check_group("axioms")
async def check_axiom_ef_automated_routines() -> list[CheckResult]:
    """Check that recurring agents have systemd timers (ex-routine-001/007)."""
    results = []
    t = time.monotonic()

    # Single source of truth: systemd/expected-timers.yaml
    expected_timers = load_expected_timers()

    # Check which timers are loaded
    rc, stdout, _ = await run_cmd(
        ["systemctl", "--user", "list-timers", "--no-pager", "--plain"],
        timeout=5.0,
    )

    if rc != 0:
        results.append(
            CheckResult(
                name="axiom.ef_automated",
                group="axioms",
                status=Status.FAILED,
                message="Cannot check systemd timers",
                duration_ms=_timed(t),
            )
        )
        return results

    missing = []
    for agent_name, timer_name in expected_timers.items():
        if timer_name not in stdout:
            missing.append(f"{agent_name} ({timer_name})")

    if not missing:
        results.append(
            CheckResult(
                name="axiom.ef_automated",
                group="axioms",
                status=Status.HEALTHY,
                message=f"All {len(expected_timers)} recurring agents have active timers",
                duration_ms=_timed(t),
            )
        )
    else:
        results.append(
            CheckResult(
                name="axiom.ef_automated",
                group="axioms",
                status=Status.DEGRADED,
                message=f"ex-routine-001 gap: {len(missing)} agent(s) missing timers",
                detail="; ".join(missing),
                remediation="Enable timers: systemctl --user enable --now <timer>",
                duration_ms=_timed(t),
            )
        )

    return results


@check_group("axioms")
async def check_axiom_ef_notifications() -> list[CheckResult]:
    """Check that alert infrastructure exists for proactive notification (ex-attention-001)."""
    results = []
    t = time.monotonic()

    # Check notify.py exists
    notify_file = AI_AGENTS_DIR / "shared" / "notify.py"
    if not notify_file.exists():
        results.append(
            CheckResult(
                name="axiom.ef_notifications",
                group="axioms",
                status=Status.FAILED,
                message="shared/notify.py not found — no proactive alert mechanism",
                duration_ms=_timed(t),
            )
        )
        return results

    # Check ntfy is reachable (the primary notification channel)
    status_code, _ = await http_get("http://127.0.0.1:8090/v1/health", timeout=2.0)
    if status_code == 200:
        results.append(
            CheckResult(
                name="axiom.ef_notifications",
                group="axioms",
                status=Status.HEALTHY,
                message="Notification infrastructure operational (ntfy + notify.py)",
                duration_ms=_timed(t),
            )
        )
    else:
        results.append(
            CheckResult(
                name="axiom.ef_notifications",
                group="axioms",
                status=Status.DEGRADED,
                message="ntfy not reachable — proactive alerts degraded",
                detail=f"HTTP status: {status_code}",
                remediation="Check: docker compose -f ~/llm-stack/docker-compose.yml ps ntfy",
                duration_ms=_timed(t),
            )
        )

    return results


# ── Voice daemon checks ──────────────────────────────────────────────────────

VOICE_VRAM_LOCK = Path.home() / ".cache" / "hapax-voice" / "vram.lock"


def _voice_socket_path() -> str:
    """Return expected path for the hapax-voice hotkey socket."""
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return f"{runtime_dir}/hapax-voice.sock"


@check_group("voice")
async def check_voice_services() -> list[CheckResult]:
    """Check hapax-voice.service and its dependencies are active."""
    services = [
        ("hapax-voice.service", True, "systemctl --user restart hapax-voice"),
        ("pipewire.service", True, "systemctl --user restart pipewire"),
    ]
    results: list[CheckResult] = []

    for unit, required, fix_cmd in services:
        t = time.monotonic()
        rc, out, err = await run_cmd(["systemctl", "--user", "is-active", unit])
        active = out.strip() == "active"

        if active:
            status = Status.HEALTHY
            msg = "active"
        elif required:
            status = Status.FAILED
            msg = out.strip() or "inactive"
        else:
            status = Status.DEGRADED
            msg = f"{out.strip() or 'inactive'} (Bluetooth speaker unavailable)"

        results.append(
            CheckResult(
                name=f"voice.{unit}",
                group="voice",
                status=status,
                message=msg,
                remediation=fix_cmd if not active else None,
                duration_ms=_timed(t),
            )
        )

    return results


@check_group("voice")
async def check_voice_socket() -> list[CheckResult]:
    """Check the hotkey Unix socket exists."""
    t = time.monotonic()
    sock_path = _voice_socket_path()

    if Path(sock_path).exists():
        return [
            CheckResult(
                name="voice.hotkey_socket",
                group="voice",
                status=Status.HEALTHY,
                message=f"socket exists at {sock_path}",
                duration_ms=_timed(t),
            )
        ]
    return [
        CheckResult(
            name="voice.hotkey_socket",
            group="voice",
            status=Status.DEGRADED,
            message=f"socket not found at {sock_path}",
            detail="Hotkey commands will not work until daemon creates the socket",
            remediation="systemctl --user restart hapax-voice",
            duration_ms=_timed(t),
        )
    ]


@check_group("voice")
async def check_voice_vram_lock() -> list[CheckResult]:
    """Check VRAM lockfile isn't stale (PID should be alive if lock exists)."""
    t = time.monotonic()

    if not VOICE_VRAM_LOCK.exists():
        return [
            CheckResult(
                name="voice.vram_lock",
                group="voice",
                status=Status.HEALTHY,
                message="no lock held",
                duration_ms=_timed(t),
            )
        ]

    try:
        pid = int(VOICE_VRAM_LOCK.read_text().strip())
        os.kill(pid, 0)  # signal 0 = check existence
        return [
            CheckResult(
                name="voice.vram_lock",
                group="voice",
                status=Status.HEALTHY,
                message=f"lock held by PID {pid} (alive)",
                duration_ms=_timed(t),
            )
        ]
    except PermissionError:
        # Process exists but owned by different user — still valid
        return [
            CheckResult(
                name="voice.vram_lock",
                group="voice",
                status=Status.HEALTHY,
                message=f"lock held by PID {pid} (alive, different user)",
                duration_ms=_timed(t),
            )
        ]
    except (ValueError, ProcessLookupError, OSError):
        return [
            CheckResult(
                name="voice.vram_lock",
                group="voice",
                status=Status.DEGRADED,
                message="stale VRAM lockfile (holder process dead)",
                detail=f"Lock at {VOICE_VRAM_LOCK}",
                remediation=f"rm {VOICE_VRAM_LOCK}",
                duration_ms=_timed(t),
            )
        ]


# ── Skill health checks ──────────────────────────────────────────────────────


@check_group("skills")
async def check_skill_syntax() -> list[CheckResult]:
    """Validate Claude Code skill definitions are syntactically valid."""
    t = time.monotonic()
    try:
        from shared.sufficiency_probes import _check_skill_syntax

        met, evidence = _check_skill_syntax()
        status = Status.HEALTHY if met else Status.DEGRADED
        return [
            CheckResult(
                name="skills.syntax",
                group="skills",
                status=status,
                message=evidence,
                remediation="Fix skill YAML frontmatter or embedded Python syntax"
                if not met
                else None,
                duration_ms=_timed(t),
            )
        ]
    except Exception as e:
        return [
            CheckResult(
                name="skills.syntax",
                group="skills",
                status=Status.FAILED,
                message=f"Skill syntax check error: {e}",
                duration_ms=_timed(t),
            )
        ]


# ── Trace correlation checks ─────────────────────────────────────────────────


@check_group("traces")
async def check_langfuse_error_spikes() -> list[CheckResult]:
    """G4: Correlate Langfuse error traces with service health."""
    t = time.monotonic()

    try:
        from shared.langfuse_client import LANGFUSE_PK, query_recent_errors
    except ImportError:
        return []

    if not LANGFUSE_PK:
        return [
            CheckResult(
                name="traces.langfuse_errors",
                group="traces",
                status=Status.HEALTHY,
                message="Langfuse credentials not configured (skipped)",
                duration_ms=_timed(t),
                tier=2,
            )
        ]

    services = ["cockpit", "briefing", "health", "drift", "scout", "voice"]
    results: list[CheckResult] = []

    for svc in services:
        try:
            errors = query_recent_errors(svc, hours=1)
        except Exception:
            continue

        if len(errors) > 5:
            status = Status.DEGRADED
            msg = f"{svc}: {len(errors)} error traces in last hour"
            top_msgs = "; ".join(e.get("message", "")[:60] for e in errors[:3] if e.get("message"))
            results.append(
                CheckResult(
                    name=f"traces.{svc}_errors",
                    group="traces",
                    status=status,
                    message=msg,
                    detail=top_msgs or None,
                    duration_ms=_timed(t),
                    tier=2,
                )
            )

    if not results:
        results.append(
            CheckResult(
                name="traces.langfuse_errors",
                group="traces",
                status=Status.HEALTHY,
                message="No error spikes in Langfuse traces",
                duration_ms=_timed(t),
                tier=2,
            )
        )

    return results


# ── Backup checks ────────────────────────────────────────────────────────────

RESTIC_REPO = Path("/data/backups/restic")
BACKUP_STALE_H = 36
BACKUP_FAILED_H = 72


@check_group("backup")
async def check_backup_freshness() -> list[CheckResult]:
    """GAP-13: Check local restic backup recency via repo mtime."""
    t = time.monotonic()

    # Check multiple indicators of last backup activity
    candidates = [
        RESTIC_REPO / "locks",
        RESTIC_REPO / "snapshots",
        RESTIC_REPO / "index",
    ]
    latest_mtime: float | None = None
    checked_path = ""
    for p in candidates:
        if p.exists():
            try:
                mtime = p.stat().st_mtime
                if latest_mtime is None or mtime > latest_mtime:
                    latest_mtime = mtime
                    checked_path = str(p)
            except OSError:
                continue

    if latest_mtime is None:
        return [
            CheckResult(
                name="backup.restic_freshness",
                group="backup",
                status=Status.FAILED,
                message="Restic repo not found or empty",
                detail=f"Checked: {RESTIC_REPO}",
                remediation="systemctl --user start hapax-backup-local.service",
                duration_ms=_timed(t),
                tier=2,
            )
        ]

    age_h = (time.time() - latest_mtime) / 3600
    if age_h > BACKUP_FAILED_H:
        status = Status.FAILED
        msg = f"Backup {age_h:.0f}h old (>{BACKUP_FAILED_H}h)"
    elif age_h > BACKUP_STALE_H:
        status = Status.DEGRADED
        msg = f"Backup {age_h:.0f}h old (>{BACKUP_STALE_H}h)"
    else:
        status = Status.HEALTHY
        msg = f"Backup {age_h:.1f}h old"

    return [
        CheckResult(
            name="backup.restic_freshness",
            group="backup",
            status=status,
            message=msg,
            detail=f"Latest activity in {checked_path}",
            remediation="systemctl --user start hapax-backup-local.service"
            if status != Status.HEALTHY
            else None,
            duration_ms=_timed(t),
            tier=2,
        )
    ]


# ── Sync checks ─────────────────────────────────────────────────────────────

SYNC_STALE_H = 24
SYNC_FAILED_H = 72


def _get_sync_agents() -> dict[str, Path]:
    """Derive sync agent state file paths from the agent registry.

    Convention: agent_id "gmail_sync" → cache dir "gmail-sync" → state.json.
    Falls back to hardcoded list if registry is unavailable.
    """
    try:
        from shared.agent_registry import AgentCategory, get_registry

        registry = get_registry()
        sync_agents = registry.agents_by_category(AgentCategory.SYNC)
        result: dict[str, Path] = {}
        for agent in sync_agents:
            # Convention: agent_id underscores → hyphens for cache dir
            cache_name = agent.id.replace("_", "-")
            # Strip trailing "-sync" for the display name
            display_name = (
                cache_name.removesuffix("-sync") if cache_name.endswith("-sync") else cache_name
            )
            result[display_name] = Path.home() / ".cache" / cache_name / "state.json"
        return result
    except Exception:
        # Fallback if registry unavailable
        return {
            name: Path.home() / ".cache" / f"{name}-sync" / "state.json"
            for name in [
                "gmail",
                "gcalendar",
                "gdrive",
                "youtube",
                "obsidian",
                "chrome",
                "claude-code",
            ]
        }


@check_group("sync")
async def check_sync_freshness() -> list[CheckResult]:
    """GAP-14: Check sync agent state file recency (derived from agent registry)."""
    t = time.monotonic()
    results: list[CheckResult] = []

    for agent_name, state_path in sorted(_get_sync_agents().items()):
        if not state_path.exists():
            results.append(
                CheckResult(
                    name=f"sync.{agent_name}_freshness",
                    group="sync",
                    status=Status.DEGRADED,
                    message=f"{agent_name} sync state file missing",
                    detail=str(state_path),
                    remediation=f"systemctl --user start {agent_name}-sync.service",
                    duration_ms=_timed(t),
                    tier=3,
                )
            )
            continue

        try:
            mtime = state_path.stat().st_mtime
        except OSError as e:
            results.append(
                CheckResult(
                    name=f"sync.{agent_name}_freshness",
                    group="sync",
                    status=Status.DEGRADED,
                    message=f"{agent_name} state file unreadable: {e}",
                    duration_ms=_timed(t),
                    tier=3,
                )
            )
            continue

        age_h = (time.time() - mtime) / 3600
        if age_h > SYNC_FAILED_H:
            status = Status.FAILED
            msg = f"{agent_name} sync {age_h:.0f}h stale (>{SYNC_FAILED_H}h)"
        elif age_h > SYNC_STALE_H:
            status = Status.DEGRADED
            msg = f"{agent_name} sync {age_h:.0f}h stale (>{SYNC_STALE_H}h)"
        else:
            status = Status.HEALTHY
            msg = f"{agent_name} sync {age_h:.1f}h ago"

        results.append(
            CheckResult(
                name=f"sync.{agent_name}_freshness",
                group="sync",
                status=status,
                message=msg,
                detail=str(state_path),
                remediation=f"systemctl --user start {agent_name}-sync.service"
                if status != Status.HEALTHY
                else None,
                duration_ms=_timed(t),
                tier=3,
            )
        )

    return results


# ── Runner ───────────────────────────────────────────────────────────────────


def build_group_result(group: str, checks: list[CheckResult]) -> GroupResult:
    statuses = [c.status for c in checks]
    h = sum(1 for s in statuses if s == Status.HEALTHY)
    d = sum(1 for s in statuses if s == Status.DEGRADED)
    f = sum(1 for s in statuses if s == Status.FAILED)
    return GroupResult(
        group=group,
        status=worst_status(*statuses) if statuses else Status.HEALTHY,
        checks=checks,
        healthy_count=h,
        degraded_count=d,
        failed_count=f,
    )


async def run_checks(
    groups: list[str] | None = None,
) -> HealthReport:
    """Run all (or selected) check groups and build a HealthReport."""
    start = time.monotonic()
    target_groups = groups or list(CHECK_REGISTRY.keys())

    # Gather all check functions for requested groups
    all_fns: list[tuple[str, Callable]] = []
    for g in target_groups:
        for fn in CHECK_REGISTRY.get(g, []):
            all_fns.append((g, fn))

    # Run all checks in parallel
    async def _run_one(group: str, fn: Callable) -> tuple[str, list[CheckResult]]:
        try:
            results = await fn()
            return (group, results)
        except Exception as e:
            return (
                group,
                [
                    CheckResult(
                        name=f"{group}.error",
                        group=group,
                        status=Status.FAILED,
                        message=f"Check crashed: {e}",
                        duration_ms=0,
                    )
                ],
            )

    tasks = [_run_one(g, fn) for g, fn in all_fns]
    try:
        raw_results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True), timeout=90.0
        )
    except TimeoutError:
        log.error("Health checks timed out after 90s")
        raw_results = [
            (
                "timeout",
                [
                    CheckResult(
                        name="checks.timeout",
                        group="timeout",
                        status=Status.FAILED,
                        message="Health checks timed out after 90s",
                        duration_ms=90000,
                    )
                ],
            )
        ]
    # Unwrap any exceptions from return_exceptions=True
    cleaned_results = []
    for r in raw_results:
        if isinstance(r, Exception):
            cleaned_results.append(
                (
                    "error",
                    [
                        CheckResult(
                            name="checks.exception",
                            group="error",
                            status=Status.FAILED,
                            message=f"Check exception: {r}",
                            duration_ms=0,
                        )
                    ],
                )
            )
        else:
            cleaned_results.append(r)
    raw_results = cleaned_results

    # Group results and annotate tiers
    from shared.service_tiers import ServiceTier, tier_for_check

    grouped: dict[str, list[CheckResult]] = {}
    for g, checks in raw_results:
        for c in checks:
            c.tier = int(tier_for_check(c.name, c.group))
        grouped.setdefault(g, []).extend(checks)

    group_results = []
    for g in target_groups:
        if g in grouped:
            group_results.append(build_group_result(g, grouped[g]))

    # Aggregate with tier-weighted overall status
    all_checks = [c for gr in group_results for c in gr.checks]
    all_statuses = [c.status for c in all_checks]
    h = sum(1 for s in all_statuses if s == Status.HEALTHY)
    d = sum(1 for s in all_statuses if s == Status.DEGRADED)
    f = sum(1 for s in all_statuses if s == Status.FAILED)

    # Tier-weighted: if only OPTIONAL (T3) checks fail, cap at DEGRADED
    failed_checks = [c for c in all_checks if c.status == Status.FAILED]
    if failed_checks and all(c.tier >= ServiceTier.OPTIONAL for c in failed_checks):
        overall = Status.DEGRADED
    else:
        overall = worst_status(*all_statuses) if all_statuses else Status.HEALTHY
    elapsed = _timed(start)

    summary = f"{h}/{len(all_checks)} healthy"
    if d:
        summary += f", {d} degraded"
    if f:
        summary += f", {f} failed"

    return HealthReport(
        timestamp=datetime.now(UTC).isoformat(),
        hostname=socket.gethostname(),
        overall_status=overall,
        groups=group_results,
        total_checks=len(all_checks),
        healthy_count=h,
        degraded_count=d,
        failed_count=f,
        duration_ms=elapsed,
        summary=summary,
    )


# ── quick_check() — pre-flight for other agents ─────────────────────────────


async def quick_check(
    required_services: list[str] | None = None,
) -> tuple[bool, list[CheckResult]]:
    """Fast pre-flight: HTTP endpoint checks only for named services.

    Returns (all_ok, results). Timeout 3s per endpoint.
    Default services: litellm, qdrant.
    """
    service_urls = {
        "litellm": "http://localhost:4000/health/liveliness",
        "qdrant": "http://localhost:6333/healthz",
        "ollama": "http://localhost:11434/api/tags",
        "langfuse": "http://localhost:3000/",
        "open-webui": "http://localhost:8080/health",
    }

    targets = required_services or ["litellm", "qdrant"]
    results: list[CheckResult] = []

    async def _check(name: str) -> CheckResult:
        url = service_urls.get(name)
        if not url:
            return CheckResult(
                name=f"preflight.{name}",
                group="preflight",
                status=Status.FAILED,
                message=f"Unknown service: {name}",
            )
        t = time.monotonic()
        code, body = await http_get(url, timeout=3.0)
        if 200 <= code < 400:
            return CheckResult(
                name=f"preflight.{name}",
                group="preflight",
                status=Status.HEALTHY,
                message="reachable",
                duration_ms=_timed(t),
            )
        return CheckResult(
            name=f"preflight.{name}",
            group="preflight",
            status=Status.FAILED,
            message=f"unreachable (HTTP {code})",
            detail=body[:200] if body and code == 0 else None,
            duration_ms=_timed(t),
        )

    tasks = [_check(name) for name in targets]
    results = list(await asyncio.gather(*tasks))
    all_ok = all(r.status == Status.HEALTHY for r in results)
    return all_ok, results


# ── Formatters ───────────────────────────────────────────────────────────────

_STATUS_ICON = {
    Status.HEALTHY: "[OK]  ",
    Status.DEGRADED: "[WARN]",
    Status.FAILED: "[FAIL]",
}

_STATUS_COLOR = {
    Status.HEALTHY: "\033[32m",  # green
    Status.DEGRADED: "\033[33m",  # yellow
    Status.FAILED: "\033[31m",  # red
}
_RESET = "\033[0m"


def format_human(report: HealthReport, verbose: bool = False, color: bool = True) -> str:
    """Format report as human-readable text."""
    lines: list[str] = []

    # Header
    overall = report.overall_status.value.upper()
    if color:
        c = _STATUS_COLOR[report.overall_status]
        header = f"Stack Health: {c}{overall}{_RESET} ({report.summary}) [{report.duration_ms / 1000:.1f}s]"
    else:
        header = f"Stack Health: {overall} ({report.summary}) [{report.duration_ms / 1000:.1f}s]"
    lines.append(header)
    lines.append("")

    for gr in report.groups:
        group_label = gr.group
        group_status = gr.status.value.upper()
        if color:
            c = _STATUS_COLOR[gr.status]
            lines.append(f"[{group_label}] {c}{group_status}{_RESET}")
        else:
            lines.append(f"[{group_label}] {group_status}")

        for check in gr.checks:
            icon = _STATUS_ICON[check.status]
            if color:
                c = _STATUS_COLOR[check.status]
                prefix = f"  {c}{icon}{_RESET}"
            else:
                prefix = f"  {icon}"

            # Pad name to align messages
            name_display = check.name
            padding = max(1, 35 - len(name_display))
            dots = "." * padding
            lines.append(f"{prefix} {name_display} {dots} {check.message}")

            if verbose and check.detail:
                lines.append(f"         {check.detail}")

            if check.remediation and check.status != Status.HEALTHY:
                lines.append(f"         Fix: {check.remediation}")

        lines.append("")

    return "\n".join(lines)


# ── Fix mode ─────────────────────────────────────────────────────────────────


async def run_fixes(report: HealthReport, yes: bool = False) -> int:
    """Run remediation commands for failed/degraded checks.

    Returns count of fixes attempted.
    """
    fixable = [
        c for gr in report.groups for c in gr.checks if c.remediation and c.status != Status.HEALTHY
    ]
    if not fixable:
        print("No remediations available.")
        return 0

    print(f"\n{len(fixable)} fixable issue(s):\n")
    for c in fixable:
        icon = _STATUS_ICON[c.status]
        print(f"  {icon} {c.name}: {c.message}")
        print(f"         Run: {c.remediation}")
    print()

    if not yes:
        try:
            answer = input("Run these fixes? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            return 0
        if answer not in ("y", "yes"):
            print("Aborted.")
            return 0

    # Sort fixable checks by service dependency order
    try:
        from shared.service_graph import remediation_order

        service_names = []
        for c in fixable:
            # Extract service name from check name (e.g. "docker.qdrant" → "qdrant")
            parts = c.name.split(".", 1)
            service_names.append(parts[1] if len(parts) > 1 else parts[0])
        ordered = remediation_order(service_names)
        name_to_order = {n: i for i, n in enumerate(ordered)}
        fixable.sort(key=lambda c: name_to_order.get(c.name.split(".", 1)[-1], len(ordered)))
    except Exception:
        pass  # fall back to original order

    count = 0
    for c in fixable:
        assert c.remediation is not None
        print(f"  Running: {c.remediation}")
        rc, out, err = await run_cmd(["bash", "-c", c.remediation], timeout=30.0)
        if rc == 0:
            print("    OK")
        else:
            print(f"    Failed (rc={rc}): {err or out}")
        count += 1

    return count


async def run_fixes_v2(report: HealthReport, mode: str = "apply") -> int:
    """Run LLM-evaluated fix pipeline.

    Modes: apply (auto-execute safe), dry_run (evaluate only), interactive (prompt each).
    Returns count of proposals processed.
    """
    from shared.fix_capabilities import load_builtin_capabilities
    from shared.fix_capabilities.pipeline import run_fix_pipeline

    load_builtin_capabilities()
    try:
        result = await asyncio.wait_for(run_fix_pipeline(report, mode=mode), timeout=120.0)
    except TimeoutError:
        log.error("Fix pipeline timed out after 120s")
        print("Fix pipeline timed out after 120s")
        return 0

    if result.total == 0:
        print("No fix proposals generated.")
        return 0

    for outcome in result.outcomes:
        if outcome.executed and outcome.execution_result:
            icon = "OK" if outcome.execution_result.success else "FAIL"
            print(f"  [{icon}] {outcome.check_name}: {outcome.execution_result.message}")
            if outcome.proposal:
                print(f"         Rationale: {outcome.proposal.rationale}")
        elif outcome.notified:
            print(f"  [HELD] {outcome.check_name}: destructive — notification sent")
            if outcome.proposal:
                print(
                    f"         Proposed: {outcome.proposal.action_name}({outcome.proposal.params})"
                )
        elif outcome.rejected_reason:
            print(f"  [SKIP] {outcome.check_name}: {outcome.rejected_reason}")
        elif mode == "dry_run" and outcome.proposal:
            print(
                f"  [DRY ] {outcome.check_name}: would run {outcome.proposal.action_name}({outcome.proposal.params})"
            )
            print(f"         Rationale: {outcome.proposal.rationale}")

    return result.total


# ── History ──────────────────────────────────────────────────────────────────

HISTORY_FILE = PROFILES_DIR / "health-history.jsonl"
INFRA_SNAPSHOT_FILE = PROFILES_DIR / "infra-snapshot.json"

MAX_HISTORY_LINES = 10_000
KEEP_HISTORY_LINES = 5_000

_STATUS_SYMBOLS = {"healthy": "OK", "degraded": "!!", "failed": "XX"}


def rotate_history() -> None:
    """Truncate health history if it exceeds MAX_HISTORY_LINES (atomic)."""
    if not HISTORY_FILE.is_file():
        return
    lines = HISTORY_FILE.read_text().strip().splitlines()
    if len(lines) <= MAX_HISTORY_LINES:
        return
    trimmed = lines[-KEEP_HISTORY_LINES:]
    import tempfile

    fd, tmp = tempfile.mkstemp(dir=HISTORY_FILE.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(trimmed) + "\n")
        os.replace(tmp, HISTORY_FILE)
        log.info("Rotated health history: %d → %d lines", len(lines), len(trimmed))
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


_SYSTEM_TIMERS = {"pop-upgrade-notify", "launchpadlib-cache-clean"}


def _collect_all_timers() -> list[dict]:
    """Query systemd for all hapax user timers with schedule data."""
    timers = []
    try:
        result = subprocess.run(
            ["systemctl", "--user", "list-timers", "--all", "--no-pager", "--output=json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            for entry in json.loads(result.stdout):
                unit = entry.get("unit", "")
                bare_name = unit.removesuffix(".timer")
                if bare_name in _SYSTEM_TIMERS:
                    continue
                activates = entry.get("activates", "")
                next_us = entry.get("next", 0)
                last_us = entry.get("last", 0)
                next_fire = (
                    datetime.fromtimestamp(next_us / 1_000_000, tz=UTC).isoformat()
                    if next_us
                    else "-"
                )
                last_fired = (
                    datetime.fromtimestamp(last_us / 1_000_000, tz=UTC).isoformat()
                    if last_us
                    else "-"
                )
                timers.append(
                    {
                        "unit": unit.removesuffix(".timer"),
                        "type": "systemd",
                        "activates": activates,
                        "status": "active" if next_us else "inactive",
                        "next_fire": next_fire,
                        "last_fired": last_fired,
                    }
                )
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as e:
        log.debug("Timer collection failed, falling back to unit files: %s", e)

    # Fallback: if JSON output not supported, parse text output
    if not timers:
        try:
            result = subprocess.run(
                ["systemctl", "--user", "list-timers", "--all", "--no-pager"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().splitlines()[1:]:  # skip header
                    if not line.strip() or line.startswith(" ") and "timers listed" in line:
                        continue
                    # Format: NEXT LEFT LAST PASSED UNIT ACTIVATES
                    parts = line.split()
                    if len(parts) >= 2:
                        unit = next((p for p in parts if p.endswith(".timer")), None)
                        if unit and unit.removesuffix(".timer") not in _SYSTEM_TIMERS:
                            # Extract NEXT (first 3-4 fields) and LAST
                            next_str = " ".join(parts[:3]) if parts[0] != "-" else "-"
                            timers.append(
                                {
                                    "unit": unit.removesuffix(".timer"),
                                    "type": "systemd",
                                    "status": "active" if parts[0] != "-" else "inactive",
                                    "next_fire": next_str,
                                    "last_fired": "-",
                                }
                            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    return timers


def write_infra_snapshot(report: HealthReport) -> None:
    """Write infrastructure snapshot for cockpit-api container to read.

    The cockpit-api runs in Docker without access to docker/systemctl/nvidia-smi.
    This function extracts infrastructure data from health check results and
    writes it to a JSON file that cockpit data collectors read instead.
    """
    containers: list[dict] = []
    timers: list[dict] = []
    gpu: dict | None = None

    for group in report.groups:
        for check in group.checks:
            name = check.name

            # Docker containers: extract from docker.* checks
            if name.startswith("docker.") and name not in (
                "docker.daemon",
                "docker.compose_file",
                "docker.containers",
                "docker.agents_compose",
                "docker.agents_containers",
            ):
                service = name.split(".", 1)[1]
                # Normalize health to simple label the frontend expects
                raw_health = check.message.lower()
                if "healthy" in raw_health:
                    health = "healthy"
                elif "unhealthy" in raw_health:
                    health = "unhealthy"
                elif "starting" in raw_health:
                    health = "starting"
                else:
                    health = check.message
                containers.append(
                    {
                        "service": service,
                        "name": service,
                        "state": "running" if check.status == Status.HEALTHY else "not running",
                        "health": health,
                    }
                )

            # GPU: extract from gpu.* checks
            elif name == "gpu.vram":
                # Parse VRAM from message like "6732/24576 MiB (27.4%)"
                msg = check.message
                loaded_models = []
                if check.detail and "Loaded Ollama models:" in check.detail:
                    loaded_models = [m.strip() for m in check.detail.split(":", 1)[1].split(",")]
                try:
                    import re

                    nums = re.findall(r"(\d+)\s*MiB", msg)
                    used = int(nums[0])
                    total = int(nums[1])
                    gpu = {
                        "used_mb": used,
                        "total_mb": total,
                        "free_mb": total - used,
                        "loaded_models": loaded_models,
                        "message": msg,
                    }
                except (ValueError, IndexError):
                    gpu = {"message": msg, "loaded_models": loaded_models}

    # Collect ALL systemd timers with real schedule data
    timers = _collect_all_timers()

    # Add container cron jobs (sync-pipeline)
    from shared.cycle_mode import get_cycle_mode

    cycle = get_cycle_mode()
    crontab = AI_AGENTS_DIR / "sync-pipeline" / f"crontab.{cycle}"
    if not crontab.exists():
        crontab = AI_AGENTS_DIR / "sync-pipeline" / "crontab.prod"
    if crontab.exists():
        for line in crontab.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 6:
                schedule = " ".join(parts[:5])
                agent = parts[-1].rsplit("/", 1)[-1] if "/" in parts[-1] else parts[-1]
                timers.append(
                    {
                        "unit": agent,
                        "type": "container-cron",
                        "schedule": schedule,
                        "status": "active",
                        "next_fire": schedule,
                        "last_fired": "-",
                    }
                )

    snapshot = {
        "timestamp": report.timestamp,
        "cycle_mode": cycle,
        "containers": containers,
        "timers": timers,
        "gpu": gpu,
    }

    try:
        import tempfile

        # Atomic write via rename
        fd, tmp = tempfile.mkstemp(dir=PROFILES_DIR, suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(snapshot, f)
        os.replace(tmp, INFRA_SNAPSHOT_FILE)
    except Exception as e:
        log.warning("Failed to write infra snapshot: %s", e)


def format_history(n: int = 20) -> str:
    """Read recent health history entries and format for display."""
    if not HISTORY_FILE.is_file():
        return "No health history found. History is recorded by the health-watchdog timer."

    entries = []
    for line in HISTORY_FILE.read_text().strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    if not entries:
        return "Health history file is empty."

    recent = entries[-n:]
    lines = [f"Health History (last {len(recent)} of {len(entries)} entries):", ""]

    for e in recent:
        ts = e.get("timestamp", "?")[:19].replace("T", " ")
        status = e.get("status", "?")
        sym = _STATUS_SYMBOLS.get(status, "??")
        h, d, f = e.get("healthy", 0), e.get("degraded", 0), e.get("failed", 0)
        dur = e.get("duration_ms", 0)
        failed_checks = e.get("failed_checks", [])
        detail = f"  [{', '.join(failed_checks)}]" if failed_checks else ""
        lines.append(f"  [{sym}] {ts}  {h}ok {d}warn {f}fail  {dur}ms{detail}")

    # Summary stats
    total = len(entries)
    healthy_runs = sum(1 for e in entries if e.get("status") == "healthy")
    lines.append("")
    lines.append(
        f"Uptime: {healthy_runs}/{total} runs healthy ({100 * healthy_runs // total if total else 0}%)"
    )

    # Most frequently failing checks
    from collections import Counter

    fail_counts: Counter[str] = Counter()
    for e in entries:
        for c in e.get("failed_checks", []):
            fail_counts[c] += 1
    if fail_counts:
        lines.append("Most frequent issues:")
        for check, count in fail_counts.most_common(5):
            lines.append(f"  {check}: {count}/{total} runs")

    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────────────────────────────


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stack health monitor — zero LLM calls, parallel async checks",
        prog="python -m agents.health_monitor",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON",
    )
    parser.add_argument(
        "--check",
        metavar="GROUPS",
        help="Comma-separated check groups (docker,gpu,systemd,qdrant,profiles,endpoints,credentials,disk)",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Run remediation commands for failures",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip confirmation for --fix",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Auto-apply safe fixes via LLM pipeline (for watchdog timer)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Evaluate fixes but don't execute (shows what would happen)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detail fields for all checks",
    )
    parser.add_argument(
        "--history",
        metavar="N",
        nargs="?",
        const=20,
        type=int,
        help="Show last N health check results from history (default: 20)",
    )

    args = parser.parse_args()

    if args.history is not None:
        print(format_history(args.history))
        return

    groups = None
    if args.check:
        groups = [g.strip() for g in args.check.split(",") if g.strip()]
        unknown = set(groups) - set(CHECK_REGISTRY.keys())
        if unknown:
            print(f"Unknown check groups: {', '.join(sorted(unknown))}", file=sys.stderr)
            print(f"Available: {', '.join(sorted(CHECK_REGISTRY.keys()))}", file=sys.stderr)
            sys.exit(1)

    with _tracer.start_as_current_span(
        "health_monitor.check",
        attributes={"agent.name": "health_monitor", "agent.repo": "hapax-council"},
    ):
        report = await run_checks(groups)

        # Write infra snapshot for cockpit-api container (full runs only)
        if groups is None:
            write_infra_snapshot(report)

        if args.json:
            print(report.model_dump_json(indent=2))
        else:
            color = sys.stdout.isatty()
            print(format_human(report, verbose=args.verbose, color=color))

        if args.apply or args.dry_run:
            mode = "dry_run" if args.dry_run else "apply"
            await run_fixes_v2(report, mode=mode)
        elif args.fix:
            await run_fixes(report, yes=args.yes)

        # Rotate history if needed
        try:
            rotate_history()
        except Exception as e:
            log.warning("History rotation failed: %s", e)

        # Exit code reflects overall status
        if report.overall_status == Status.FAILED:
            sys.exit(2)
        elif report.overall_status == Status.DEGRADED:
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
