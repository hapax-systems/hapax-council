"""Tests for the live quota/resource telemetry writer (routing Phase 0.4)."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-quota-telemetry-writer"
FIXTURES = REPO_ROOT / "config" / "quota-spend-ledger-fixtures.json"
NOW = "2026-06-10T00:00:00Z"


def _fake_nvidia_smi(tmp_path: Path, body: str) -> Path:
    stub = tmp_path / "fake-nvidia-smi"
    stub.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    stub.chmod(0o755)
    return stub


def _run_writer(
    tmp_path: Path,
    *extra_args: str,
    nvidia_body: str = "echo '1000, 32000'",
) -> tuple[subprocess.CompletedProcess[str], Path]:
    out = tmp_path / "out" / "quota-spend-ledger-live.json"
    relay = tmp_path / "relay-receipts"
    relay.mkdir(exist_ok=True)
    stub = _fake_nvidia_smi(tmp_path, nvidia_body)
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--skip-receipts",
            "--now",
            NOW,
            "--out",
            str(out),
            "--relay-receipt-dir",
            str(relay),
            "--nvidia-smi",
            str(stub),
            "--json",
            *extra_args,
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
    )
    return result, out


def _wall_receipt(relay: Path, role: str, resets_at: str) -> None:
    (relay / f"{role}-quota-wall.yaml").write_text(
        f"""role: {role}
status: quota_blocked
detected_at: 2026-06-09T23:00:00Z
signal_kind: rate_limit_event
rate_limit_type: seven_day
resets_at: {resets_at}
is_overage: False
action: exit_clean_await_restart
""",
        encoding="utf-8",
    )


def test_writes_valid_live_ledger_with_fresh_captured_at(tmp_path: Path) -> None:
    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["captured_at"] == NOW
    assert payload["ledger_id"].startswith("quota-spend-ledger-live-")
    assert payload["local_resource_state"] == "green"

    # The output revalidates through the fail-closed loader.
    sys.path.insert(0, str(REPO_ROOT))
    from shared.quota_spend_ledger import load_quota_spend_ledger

    ledger = load_quota_spend_ledger(out)
    states = {
        snapshot.route_id: snapshot.subscription_quota_state.value
        for snapshot in ledger.quota_snapshots
    }
    assert states["claude.headless.full"] == "fresh"
    assert states["codex.headless.full"] == "fresh"
    assert states["gemini.headless.full"] == "fresh"
    assert states["litellm.local.command-r-35b"] == "fresh"


def test_governance_records_carry_over_unchanged(tmp_path: Path) -> None:
    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    live = json.loads(out.read_text(encoding="utf-8"))
    base = json.loads(FIXTURES.read_text(encoding="utf-8"))
    for key in (
        "transition_budgets",
        "spend_receipts",
        "spend_gate_decisions",
        "provider_dependencies",
        "artifact_provenance",
        "renewal_records",
        "authority_source",
        "paid_api_budget_freshness_ttl_s",
    ):
        assert live[key] == base[key], f"{key} must not be rewritten by telemetry"


def test_unexpired_quota_wall_marks_platform_exhausted(tmp_path: Path) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _wall_receipt(relay, "theta", "2026-06-10T06:00:00Z")
    _wall_receipt(relay, "cx-amber", "2026-06-09T06:00:00Z")  # expired -> ignored

    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["claude.headless.full"] == "exhausted"
    assert states["codex.headless.full"] == "fresh"
    summary = json.loads(result.stdout)
    assert summary["quota_walls"] == {"claude": 1}


def test_resource_probe_failure_fails_closed_to_unknown(tmp_path: Path) -> None:
    result, out = _run_writer(tmp_path, nvidia_body="exit 9")

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["local_resource_state"] == "unknown"
    states = {
        snapshot["route_id"]: snapshot["subscription_quota_state"]
        for snapshot in payload["quota_snapshots"]
    }
    assert states["litellm.local.command-r-35b"] == "unknown"


def test_vram_pressure_degrades_resource_state(tmp_path: Path) -> None:
    result, out = _run_writer(tmp_path, nvidia_body="echo '31000, 32000'")

    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["local_resource_state"] in {"yellow", "red"}


def test_unusable_base_ledger_fails_without_writing(tmp_path: Path) -> None:
    bad_base = tmp_path / "bad-base.json"
    bad_base.write_text("{not json", encoding="utf-8")

    result, out = _run_writer(tmp_path, "--base", str(bad_base))

    assert result.returncode == 1
    assert "base ledger unusable" in result.stderr
    assert not out.exists()


def test_output_is_private_and_atomic(tmp_path: Path) -> None:
    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    mode = stat.S_IMODE(out.stat().st_mode)
    assert mode == 0o600
    leftovers = [p for p in out.parent.iterdir() if p.name != out.name]
    assert leftovers == []


def test_no_secret_material_in_output(tmp_path: Path) -> None:
    result, out = _run_writer(tmp_path)

    assert result.returncode == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    for token in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "LITELLM_API_KEY",
        "pass show",
        "hapax-secrets.env",
    ):
        assert token not in text
