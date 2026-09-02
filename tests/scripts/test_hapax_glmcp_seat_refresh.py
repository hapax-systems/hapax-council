"""The GLM review seat's passive admission receipt lives 15 minutes; with no producer to renew it
the seat had been expired since 2026-08-04 and every council review dossier was refused as seated
by a blocked family — 40 open PRs admitted nothing for four weeks (memory
`glm-review-seat-expires-every-15-minutes`, L-158). `scripts/hapax-glmcp-seat-refresh` is that
producer; `hapax-glmcp-seat-refresh.timer` runs it every five minutes.

These tests RUN the script against stubbed reviewer / admission / telemetry-writer scripts in a
throwaway HOME (review finding on #4624: text greps of the script were not behaviour tests), so
the freshness guard, the retry loop, the no-mint-on-failure rule, the PAYG guard, the redaction and
the writer's exit-code handling are each exercised through the real code path without a network
call."""

from __future__ import annotations

import os
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "hapax-glmcp-seat-refresh"
SERVICE = REPO / "systemd" / "units" / "hapax-glmcp-seat-refresh.service"
TIMER = REPO / "systemd" / "units" / "hapax-glmcp-seat-refresh.timer"

REVIEWER_OK = (
    'echo "PAYG=${HAPAX_GLMCP_REVIEW_PAYG_FALLBACK:-unset}" >> "$HOME/reviewer-env"\necho OK\n'
)
REVIEWER_ALWAYS_FAILS_SILENTLY = "exit 1\n"
REVIEWER_FAILS_TWICE_LOUDLY = (
    'n=$(cat "$HOME/attempts" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$HOME/attempts"\n'
    'if [ "$n" -lt 3 ]; then\n'
    '  echo "Authorization: Bearer abc123" >&2\n'
    '  echo "api_key = zzz9" >&2\n'
    "  exit 1\n"
    "fi\n"
    "echo OK\n"
)


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


def _stub(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    path.chmod(0o755)


def _harness(
    tmp_path: Path,
    *,
    reviewer: str = REVIEWER_OK,
    writer_rc: int = 0,
    receipt: str | None = None,
) -> tuple[Path, Path]:
    """A throwaway HOME plus a fake council root whose three scripts record what they were asked."""
    home = tmp_path / "home"
    council = tmp_path / "council"
    scripts = council / "scripts"
    scripts.mkdir(parents=True)
    receipts = home / ".cache" / "hapax" / "relay" / "receipts"
    receipts.mkdir(parents=True)
    _stub(scripts / "hapax-glmcp-reviewer", reviewer)
    _stub(
        scripts / "hapax-glmcp-quota-admission",
        'printf "%s\\n" "$*" >> "$HOME/admission-calls"\necho "receipt ok"\n',
    )
    _stub(
        scripts / "hapax-quota-telemetry-writer",
        f'echo "wrote live ledger"\necho "capability receipts DEGRADED for one provider"\nexit {writer_rc}\n',
    )
    if receipt is not None:
        (receipts / "glmcp-quota-admission.yaml").write_text(receipt, encoding="utf-8")
    return home, council


def _run(home: Path, council: Path) -> subprocess.CompletedProcess[str]:
    env = {
        "HOME": str(home),
        "HAPAX_COUNCIL": str(council),
        "PATH": os.environ["PATH"],
        "TMPDIR": str(home),
        "HAPAX_GLMCP_SEAT_RETRY_SLEEP": "0",
    }
    return subprocess.run(
        ["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=120
    )


def _receipt_observed(seconds_ago: int) -> str:
    observed = datetime.now(UTC) - timedelta(seconds=seconds_ago)
    return (
        "schema: hapax.glmcp_quota_admission.v1\nstatus: quota_available\n"
        f"observed_at: {observed.strftime('%Y-%m-%dT%H:%M:%SZ')}\nstale_after_seconds: 900\n"
    )


def _witnesses(home: Path) -> list[Path]:
    return sorted((home / ".cache" / "hapax" / "glmcp-admission-witness").glob("*.yaml"))


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


def test_a_fresh_receipt_skips_the_round_trip(tmp_path: Path) -> None:
    home, council = _harness(tmp_path, receipt=_receipt_observed(60))
    result = _run(home, council)
    assert result.returncode == 0, result.stderr
    assert "no round-trip" in result.stdout
    assert not (home / "admission-calls").exists()
    assert _witnesses(home) == []


def test_a_stale_receipt_round_trips_writes_a_witness_and_mints(tmp_path: Path) -> None:
    home, council = _harness(tmp_path, receipt=_receipt_observed(20 * 60))
    result = _run(home, council)
    assert result.returncode == 0, result.stderr
    assert "roundtrip attempt 1: exit=0" in result.stdout
    witnesses = _witnesses(home)
    assert len(witnesses) == 1
    witness = witnesses[0].read_text(encoding="utf-8")
    assert "schema: hapax.glmcp_admission_witness.v1" in witness
    assert "prompt_or_output_persisted: false" in witness
    assert "secret_value_persisted: false" in witness
    assert "model: glm-5.2" in witness
    calls = (home / "admission-calls").read_text(encoding="utf-8")
    assert "observe-success --evidence-ref glmcp-reviewer-roundtrip-ok-" in calls
    assert "--supported-tool hapax-glmcp-reviewer" in calls
    assert "--model glm-5.2" in calls


def test_a_malformed_receipt_falls_through_to_a_round_trip_instead_of_wedging(
    tmp_path: Path,
) -> None:
    """No observed_at used to make the guard's grep fail under errexit on every timer run."""
    home, council = _harness(tmp_path, receipt="schema: x\nstatus: quota_available\n")
    result = _run(home, council)
    assert result.returncode == 0, result.stderr
    assert (home / "admission-calls").exists()


def test_the_probe_disables_the_reviewers_payg_fallback(tmp_path: Path) -> None:
    """An exhausted Coding Plan answered by API credit must not mint a Coding Plan receipt."""
    home, council = _harness(tmp_path)
    result = _run(home, council)
    assert result.returncode == 0, result.stderr
    assert (home / "reviewer-env").read_text(encoding="utf-8").strip() == "PAYG=0"


def test_three_failed_round_trips_mint_nothing_and_name_the_next_action(tmp_path: Path) -> None:
    """Empty stderr on a failure used to end the retry loop under pipefail after one attempt."""
    home, council = _harness(tmp_path, reviewer=REVIEWER_ALWAYS_FAILS_SILENTLY)
    result = _run(home, council)
    assert result.returncode == 2
    assert "roundtrip attempt 3: exit=1" in result.stdout
    assert "glm seat NOT refreshed" in result.stderr
    assert "do not mint" in result.stderr
    assert _witnesses(home) == []
    assert not (home / "admission-calls").exists()


def test_transient_failures_are_retried_and_the_reviewers_stderr_is_redacted(
    tmp_path: Path,
) -> None:
    home, council = _harness(tmp_path, reviewer=REVIEWER_FAILS_TWICE_LOUDLY)
    result = _run(home, council)
    assert result.returncode == 0, result.stderr
    assert "roundtrip attempt 3: exit=0" in result.stdout
    assert "Bearer<redacted>" in result.stdout
    assert "api_key<redacted>" in result.stdout
    assert "abc123" not in result.stdout + result.stderr
    assert "zzz9" not in result.stdout + result.stderr
    assert (home / "admission-calls").exists()


def test_writer_degradation_is_printed_and_the_seat_still_counts_as_refreshed(
    tmp_path: Path,
) -> None:
    """Exit 3 from the telemetry writer means the live ledger was written and an ancillary
    receipt refresh degraded; the receipt is already minted, so the run is a success that SAYS
    what degraded instead of filtering it out and then failing on pipefail."""
    home, council = _harness(tmp_path, writer_rc=3)
    result = _run(home, council)
    assert result.returncode == 0, result.stderr
    assert "capability receipts DEGRADED for one provider" in result.stdout
    assert "capability receipts degraded (exit 3)" in result.stdout
    assert (home / "admission-calls").exists()


def test_writer_failure_after_minting_is_loud_and_names_the_next_action(tmp_path: Path) -> None:
    home, council = _harness(tmp_path, writer_rc=1)
    result = _run(home, council)
    assert result.returncode == 3
    assert "telemetry writer failed (exit 1)" in result.stderr
    assert "Next:" in result.stderr
    assert (home / "admission-calls").exists()


def test_model_is_pinned_to_what_the_admission_cli_accepts() -> None:
    """The systemd user environment carries HAPAX_GLMCP_REVIEW_MODEL; the admission CLI on main
    accepts exactly glm-5.2. The witness and the receipt must name the model that was called."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'model="glm-5.2"' in text
    assert 'export HAPAX_GLMCP_REVIEW_MODEL="$model"' in text


def test_unit_pair_executes_from_the_activation_worktree() -> None:
    """A unit that runs a mutable development checkout is a finding (review on #4624): the
    estate's convention is the governed source-activation worktree, and the script's own default
    root must agree with the unit."""
    service = SERVICE.read_text(encoding="utf-8")
    exec_start = _unit_value(service, "Service", "ExecStart") or ""
    assert exec_start == (
        "%h/.cache/hapax/source-activation/worktree/scripts/hapax-glmcp-seat-refresh"
    )
    assert "projects" not in exec_start
    assert "tmp" not in exec_start
    assert "source-activation/worktree" in SCRIPT.read_text(encoding="utf-8")
    assert _unit_value(service, "Service", "Type") == "oneshot"
    assert _unit_value(service, "Service", "MemoryMax") is not None
    assert int(_unit_value(service, "Service", "TimeoutStartSec") or 0) >= 600
    assert "5 minutes" in (_unit_value(service, "Unit", "Description") or "")
    timer = TIMER.read_text(encoding="utf-8")
    assert _unit_value(timer, "Install", "WantedBy") == "timers.target"
    assert "5 minutes" in (_unit_value(timer, "Unit", "Description") or "")
