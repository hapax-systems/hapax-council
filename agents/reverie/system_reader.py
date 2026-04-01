"""System reader — safe read-only operations for the visual surface.

Executes bounded, read-only system queries and injects results into
the Reverie visual surface via content_injector. All operations are
non-mutating and respect governance boundaries.

SAFE: local filesystem reads (hapax paths only), local service queries,
systemd status, system metrics, git status, docker status, process lists.

UNSAFE (never): writes, service control, arbitrary shell, external network,
PII, secrets, corporate data.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from agents.reverie.content_injector import inject_text

log = logging.getLogger("reverie.system_reader")

# Allowed filesystem read roots
ALLOWED_ROOTS = [
    Path.home() / ".cache" / "hapax",
    Path.home() / ".cache" / "hapax-daimonion",
    Path.home() / "hapax-state",
    Path("/dev/shm"),
]


def _path_allowed(path: Path) -> bool:
    """Check if a path is within allowed read roots."""
    resolved = path.resolve()
    return any(resolved.is_relative_to(root) for root in ALLOWED_ROOTS)


def read_file(source_id: str, path: str | Path, **kwargs) -> bool:
    """Read a file and inject its content onto the visual surface."""
    p = Path(path)
    if not _path_allowed(p):
        log.warning("Blocked read outside allowed roots: %s", p)
        return False
    if not p.exists():
        return inject_text(source_id, f"Not found: {p.name}", **kwargs)
    try:
        text = p.read_text(encoding="utf-8", errors="replace")[:1000]
        return inject_text(source_id, text, **kwargs)
    except Exception:
        log.debug("Failed to read %s", p, exc_info=True)
        return False


def read_json(source_id: str, path: str | Path, keys: list[str] | None = None, **kwargs) -> bool:
    """Read a JSON file, optionally extract specific keys, inject as text."""
    p = Path(path)
    if not _path_allowed(p):
        log.warning("Blocked read outside allowed roots: %s", p)
        return False
    if not p.exists():
        return False
    try:
        data = json.loads(p.read_text())
        if keys:
            data = {k: data[k] for k in keys if k in data}
        text = json.dumps(data, indent=2)[:800]
        return inject_text(source_id, text, **kwargs)
    except Exception:
        log.debug("Failed to read JSON %s", p, exc_info=True)
        return False


def systemd_status(source_id: str, unit: str, **kwargs) -> bool:
    """Read systemd user unit status and inject as text."""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "status", unit, "--no-pager"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        text = result.stdout[:600] if result.stdout else result.stderr[:600]
        return inject_text(source_id, text, **kwargs)
    except Exception:
        log.debug("Failed to read systemd status for %s", unit, exc_info=True)
        return False


def system_metrics(source_id: str, **kwargs) -> bool:
    """Read CPU, memory, GPU metrics and inject as text."""
    lines = []

    # GPU via nvidia-smi
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split(", ")
            if len(parts) >= 4:
                lines.append(f"GPU: {parts[0]}%  VRAM: {parts[1]}/{parts[2]}MiB  {parts[3]}°C")
    except Exception:
        pass

    # Disk
    try:
        result = subprocess.run(
            ["df", "-h", "/"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            disk_line = result.stdout.strip().split("\n")[-1].split()
            if len(disk_line) >= 5:
                lines.append(f"Disk: {disk_line[2]}/{disk_line[1]} ({disk_line[4]})")
    except Exception:
        pass

    # Load average
    try:
        load = Path("/proc/loadavg").read_text().split()[:3]
        lines.append(f"Load: {' '.join(load)}")
    except Exception:
        pass

    if not lines:
        return False
    return inject_text(source_id, "\n".join(lines), **kwargs)


_DEFAULT_REPO = Path.home() / "projects" / "hapax-council"


def git_status(
    source_id: str,
    repo_path: str | Path | None = None,
    **kwargs,
) -> bool:
    """Read git log and status from a repo."""
    if repo_path is None:
        repo_path = _DEFAULT_REPO
    try:
        log_result = subprocess.run(
            ["git", "-C", str(repo_path), "log", "--oneline", "-5"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        status_result = subprocess.run(
            ["git", "-C", str(repo_path), "status", "--short"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        text = (
            f"Recent:\n{log_result.stdout.strip()}\n\n"
            f"Status:\n{status_result.stdout.strip() or '(clean)'}"
        )
        return inject_text(source_id, text[:600], **kwargs)
    except Exception:
        log.debug("Failed to read git status", exc_info=True)
        return False


def docker_status(source_id: str, **kwargs) -> bool:
    """Read running Docker containers."""
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return False
        return inject_text(source_id, result.stdout.strip()[:600], **kwargs)
    except Exception:
        log.debug("Failed to read docker status", exc_info=True)
        return False


def process_list(source_id: str, filter_str: str = "hapax", **kwargs) -> bool:
    """Read filtered process list."""
    try:
        result = subprocess.run(
            ["pgrep", "-a", filter_str],
            capture_output=True,
            text=True,
            timeout=5,
        )
        text = (
            result.stdout.strip()[:600]
            if result.stdout
            else f"No processes matching '{filter_str}'"
        )
        return inject_text(source_id, text, **kwargs)
    except Exception:
        log.debug("Failed to read process list", exc_info=True)
        return False


def qdrant_info(source_id: str, collection: str = "affordances", **kwargs) -> bool:
    """Read Qdrant collection info."""
    try:
        from agents._config import get_qdrant

        client = get_qdrant()
        info = client.get_collection(collection)
        text = f"{collection}: {info.points_count} points, {info.vectors_count} vectors"
        return inject_text(source_id, text, **kwargs)
    except Exception:
        log.debug("Failed to read Qdrant %s", collection, exc_info=True)
        return False
