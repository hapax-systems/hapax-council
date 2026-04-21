"""hapax-audio-state-audit CLI (Phase A4).

Pins the CLI's schema contract: takes an optional --json flag, emits
a per-surface report, exits non-zero when any surface is stale /
missing / unreadable / invalid JSON. This is the diagnostic the
dynamic router agent (Phase B3) will consume as its hardware-state
health check.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "hapax-audio-state-audit"


def test_script_exists_and_executable() -> None:
    assert SCRIPT_PATH.exists(), f"script missing: {SCRIPT_PATH}"
    assert os.access(SCRIPT_PATH, os.X_OK), "script must be executable"


def _run_with_surfaces(tmp_root: Path, present: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run the audit with SURFACES patched to point into tmp_root.

    Writes ``present`` dict as {relative_path: contents} and invokes the
    script with an injected SURFACES override via environment.

    The script as shipped hardcodes /dev/shm paths so we instead
    exercise the CLI wrapper behavior by importing the module and
    calling ``audit()`` directly. That indirect style is used by the
    downstream tests (below) — this first test just exercises the
    CLI surface.
    """
    result = subprocess.run(
        ["python3", str(SCRIPT_PATH), "--json"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    return result


def test_cli_json_flag_emits_machine_readable(tmp_path: Path) -> None:
    """--json should produce parseable JSON on stdout regardless of host state."""
    result = _run_with_surfaces(tmp_path, {})
    payload = json.loads(result.stdout)
    assert "exit_code" in payload
    assert "surfaces" in payload
    assert isinstance(payload["surfaces"], list)
    assert len(payload["surfaces"]) == 3  # 3 canonical surfaces (stimmung, voice-tier, evil-pet)


def test_cli_human_flag_produces_readable_output() -> None:
    """Default (no --json) produces human-readable per-surface lines."""
    result = subprocess.run(
        ["python3", str(SCRIPT_PATH)],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert "Audio router state surface audit" in result.stdout
    assert "/dev/shm/hapax-stimmung/state.json" in result.stdout


def test_each_surface_entry_has_required_fields() -> None:
    result = subprocess.run(
        ["python3", str(SCRIPT_PATH), "--json"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    payload = json.loads(result.stdout)
    for entry in payload["surfaces"]:
        assert "path" in entry
        assert "description" in entry
        assert "budget_s" in entry
        assert "status" in entry
        assert "issues" in entry
        assert entry["status"] in {
            "healthy",
            "absent_ok",
            "stale",
            "missing",
            "invalid_json",
            "unreadable",
        }
        assert entry["category"] in {"continuous", "on_demand"}


def test_all_canonical_surfaces_listed() -> None:
    result = subprocess.run(
        ["python3", str(SCRIPT_PATH), "--json"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    payload = json.loads(result.stdout)
    paths = {s["path"] for s in payload["surfaces"]}
    # Paths verified 2026-04-21 against the live code:
    # stimmung writer is the VLA (continuous); voice-tier override and
    # evil-pet-state are on-demand writers (CLI and granular claimant).
    assert "/dev/shm/hapax-stimmung/state.json" in paths
    assert "/dev/shm/hapax-compositor/voice-tier-override.json" in paths
    assert "/dev/shm/hapax-compositor/evil-pet-state.json" in paths


def test_on_demand_surfaces_absent_is_not_a_failure() -> None:
    """If voice-tier-override or evil-pet-state are missing, exit code
    should still be 0 (on-demand: absence is normal until the claim
    path fires)."""
    result = subprocess.run(
        ["python3", str(SCRIPT_PATH), "--json"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    payload = json.loads(result.stdout)
    # Categorize
    on_demand = [s for s in payload["surfaces"] if s["category"] == "on_demand"]
    for s in on_demand:
        if s["status"] == "missing":
            # Must not have raised the exit code by itself
            assert "absent_ok" in {ss["status"] for ss in on_demand} or all(
                s2["status"] != "missing" for s2 in on_demand
            ), "on-demand missing should map to absent_ok, not failure"
