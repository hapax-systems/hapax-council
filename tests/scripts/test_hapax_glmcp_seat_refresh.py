"""The GLM review seat's passive admission receipt lives 15 minutes; with no producer to renew it
the seat had been expired since 2026-08-04 and every council review dossier was refused as seated
by a blocked family — 40 open PRs admitted nothing for four weeks (memory
`glm-review-seat-expires-every-15-minutes`, L-158). `scripts/hapax-glmcp-seat-refresh` is that
producer; `hapax-glmcp-seat-refresh.timer` runs it every five minutes. These tests pin the
properties that keep the seat from lapsing again, without making a network call."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "hapax-glmcp-seat-refresh"
SERVICE = REPO / "systemd" / "units" / "hapax-glmcp-seat-refresh.service"
TIMER = REPO / "systemd" / "units" / "hapax-glmcp-seat-refresh.timer"


def _unit_value(text: str, section: str, key: str) -> str | None:
    in_section = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_section = stripped == f"[{section}]"
            continue
        if in_section and "=" in stripped:
            unit_key, _, value = stripped.partition("=")
            if unit_key.strip() == key:
                return value.strip()
    return None


def test_script_exists_is_executable_and_parses() -> None:
    assert SCRIPT.is_file()
    assert SCRIPT.stat().st_mode & 0o111, "must be executable"
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True, capture_output=True, timeout=10)


def test_refresh_threshold_keeps_the_receipt_under_its_15_minute_life() -> None:
    """The receipt's stale_after_seconds is 900. The timer fires every 300 s; refreshing whenever
    the receipt is older than 300 s bounds its age below ~600 s, so it never lapses between two
    autoqueue cycles (measured 2026-08-04: a lapse mid-queue dequeued a green PR)."""
    text = SCRIPT.read_text(encoding="utf-8")
    m = re.search(r"age >= 0 && age < (\d+)", text)
    assert m, "freshness guard missing"
    assert int(m.group(1)) <= 300
    on_unit_active = _unit_value(TIMER.read_text(encoding="utf-8"), "Timer", "OnUnitActiveSec")
    assert on_unit_active == "5min"


def test_round_trip_is_retried_and_never_minted_on_failure() -> None:
    """A transient provider error must not lapse the seat (three attempts), and a failed
    round-trip must not mint a receipt (exit 2 before the witness is written)."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert re.search(r"for attempt in 1 2 3; do", text)
    assert "glm seat NOT refreshed" in text
    assert text.index("glm seat NOT refreshed") < text.index("observe-success")


def test_model_is_pinned_to_what_the_admission_cli_accepts() -> None:
    """The systemd user environment carries HAPAX_GLMCP_REVIEW_MODEL; the admission CLI on main
    accepts exactly glm-5.2. The witness and the receipt must name the model that was called."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'model="glm-5.2"' in text
    assert 'export HAPAX_GLMCP_REVIEW_MODEL="$model"' in text


def test_nothing_secret_shaped_is_persisted_or_echoed() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "prompt_or_output_persisted: false" in text
    assert "secret_value_persisted: false" in text
    # the reviewer's stderr is echoed only through the redacting sed
    assert re.search(r"sed -E 's/\(api\[_-\]\?key\|token\|secret\|password\|bearer\)", text)


def test_unit_pair_executes_the_source_controlled_script() -> None:
    service = SERVICE.read_text(encoding="utf-8")
    assert _unit_value(service, "Service", "ExecStart") == (
        "/".join(("", "home", "hapax", "projects", "hapax-council"))
        + "/scripts/hapax-glmcp-seat-refresh"
    )
    assert _unit_value(service, "Service", "Type") == "oneshot"
    assert _unit_value(service, "Service", "MemoryMax") is not None
    assert "tmp" not in (_unit_value(service, "Service", "ExecStart") or "")
    assert _unit_value(TIMER.read_text(encoding="utf-8"), "Install", "WantedBy") == "timers.target"
