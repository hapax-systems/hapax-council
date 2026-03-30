"""Documentation freshness and screen context drift checks."""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from opentelemetry import trace

from .config import AI_AGENTS_DIR, HAPAX_HOME
from .docs import DOC_FILES, EXPECTED_DEVICES
from .models import DriftItem

log = logging.getLogger("drift_detector")
_tracer = trace.get_tracer(__name__)


def check_doc_freshness() -> list[DriftItem]:
    """Check whether documentation files are potentially stale."""
    with _tracer.start_as_current_span("drift.check_doc_freshness"):
        stale_threshold = timedelta(days=30)
        now = datetime.now(UTC)
        items: list[DriftItem] = []
        home = str(HAPAX_HOME)

        latest_system_change: datetime | None = None

        health_history = AI_AGENTS_DIR / "profiles" / "health-history.jsonl"
        if health_history.is_file():
            try:
                with open(health_history, "rb") as f:
                    f.seek(0, 2)
                    size = f.tell()
                    if size > 0:
                        f.seek(max(0, size - 1024))
                        last_lines = f.read().decode("utf-8", errors="replace").strip().splitlines()
                        if last_lines:
                            entry = json.loads(last_lines[-1])
                            ts = entry.get("timestamp", "")
                            if ts:
                                dt = datetime.fromisoformat(ts)
                                if latest_system_change is None or dt > latest_system_change:
                                    latest_system_change = dt
            except (OSError, json.JSONDecodeError, ValueError):
                pass

        try:
            result = subprocess.run(
                ["docker", "ps", "--format", "{{.CreatedAt}}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().splitlines():
                    try:
                        parts = line.strip().split()
                        if len(parts) >= 3:
                            dt_str = f"{parts[0]} {parts[1]} {parts[2]}"
                            dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S %z")
                            if latest_system_change is None or dt > latest_system_change:
                                latest_system_change = dt
                    except (ValueError, IndexError):
                        continue
        except (OSError, subprocess.TimeoutExpired):
            pass

        if latest_system_change is None:
            return items

        for path in DOC_FILES:
            if not path.is_file():
                continue

            doc_last_modified: datetime | None = None
            try:
                result = subprocess.run(
                    ["git", "log", "-1", "--format=%aI", "--", str(path)],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    cwd=str(path.parent),
                )
                if result.returncode == 0 and result.stdout.strip():
                    doc_last_modified = datetime.fromisoformat(result.stdout.strip())
            except (OSError, subprocess.TimeoutExpired, ValueError):
                pass

            if doc_last_modified is None:
                try:
                    mtime = path.stat().st_mtime
                    doc_last_modified = datetime.fromtimestamp(mtime, tz=UTC)
                except OSError:
                    continue

            age = now - doc_last_modified
            if age > stale_threshold and latest_system_change > doc_last_modified:
                short_path = str(path).replace(home, "~")
                days_old = age.days
                items.append(
                    DriftItem(
                        severity="low",
                        category="stale_doc",
                        doc_file=short_path,
                        doc_claim=f"Last updated {days_old} days ago ({doc_last_modified.strftime('%Y-%m-%d')})",
                        reality=f"System state changed more recently ({latest_system_change.strftime('%Y-%m-%d')})",
                        suggestion=f"Review {short_path} for accuracy — not updated in {days_old} days",
                    )
                )

        return items


def check_screen_context_drift() -> list[DriftItem]:
    """Check if screen analyzer context file has drifted from live state."""
    import datetime as dt_mod

    context_path = Path.home() / ".local" / "share" / "hapax-daimonion" / "screen_context.md"
    items: list[DriftItem] = []

    if not context_path.exists():
        items.append(
            DriftItem(
                severity="medium",
                category="missing_doc",
                doc_file=str(context_path).replace(str(Path.home()), "~"),
                doc_claim="Screen analyzer context file should exist",
                reality="File not found",
                suggestion="Run: uv run python scripts/generate_screen_context.py",
            )
        )
        return items

    file_mtime = dt_mod.datetime.fromtimestamp(context_path.stat().st_mtime, tz=dt_mod.UTC)
    age_days = (dt_mod.datetime.now(tz=dt_mod.UTC) - file_mtime).days
    if age_days > 7:
        items.append(
            DriftItem(
                severity="low",
                category="stale_doc",
                doc_file=str(context_path).replace(str(Path.home()), "~"),
                doc_claim=f"Screen context last generated {age_days} days ago",
                reality="Context may not reflect current system state",
                suggestion="Regenerate: uv run python scripts/generate_screen_context.py",
            )
        )

    content = context_path.read_text()
    try:
        llm_stack = Path.home() / "llm-stack"
        result = subprocess.run(
            ["docker", "compose", "ps", "--format", "{{.Name}}"],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(llm_stack) if llm_stack.exists() else None,
        )
        live_services = set(result.stdout.strip().splitlines())
        missing_from_doc = [s for s in live_services if s and s not in content]
        if missing_from_doc:
            items.append(
                DriftItem(
                    severity="medium",
                    category="config_mismatch",
                    doc_file=str(context_path).replace(str(Path.home()), "~"),
                    doc_claim="Screen context should list all running services",
                    reality=f"Services not in context: {', '.join(sorted(missing_from_doc)[:5])}",
                    suggestion="Regenerate: uv run python scripts/generate_screen_context.py",
                )
            )
    except Exception as exc:
        log.debug("Docker check failed for screen context drift: %s", exc)

    for label, dev_path in EXPECTED_DEVICES.items():
        if not Path(dev_path).exists():
            items.append(
                DriftItem(
                    severity="low",
                    category="config_mismatch",
                    doc_file="hardware/webcam",
                    doc_claim=f"{label} should be available at {dev_path}",
                    reality=f"{label} not detected at expected device path",
                    suggestion=f"Check USB connection for {label}, or update EXPECTED_DEVICES in drift_detector.py",
                )
            )

    return items
