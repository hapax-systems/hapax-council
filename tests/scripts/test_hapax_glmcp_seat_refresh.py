"""Behaviour tests for ``scripts/hapax-glmcp-seat-refresh`` — the accepted-release GLM review-seat
refresher (seat task ``glmcp-review-admission-accepted-release-producer-20261003``).

Each test RUNS the real bash script against stubbed reviewer / admission / telemetry-writer / receipts
tools in a throwaway ``HOME`` and a fake activation root (review finding on #4624: grepping the script
is not a behaviour test), so the root guard, the pins (PAYG off, Coding Plan endpoint), the freshness
skip, the no-mint-on-failure rule and the mint-on-success chain are each exercised through the real
code path without a network call. The wrapper invokes every tool as
``$W/.venv/bin/python $W/scripts/<tool>``, so the fake root supplies a ``.venv/bin/python`` shim that
execs its first argument under bash and the tool stubs are ordinary bash scripts.
"""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "hapax-glmcp-seat-refresh"
SERVICE = REPO / "systemd" / "units" / "hapax-glmcp-seat-refresh.service"
TIMER = REPO / "systemd" / "units" / "hapax-glmcp-seat-refresh.timer"
ACTIVATION_ROOT = "%h/.cache/hapax/source-activation/worktree"
ENDPOINT = "https://api.z.ai/api/coding/paas/v4"

# The reviewer stub records the pinned environment it was handed and drains the blind-review prompt
# on stdin before replying, so the pins (PAYG off, endpoint, model) are checkable after a run.
REVIEWER_OK = (
    "cat >/dev/null 2>&1 || true\n"
    'printf "PAYG=%s\\n" "${HAPAX_GLMCP_REVIEW_PAYG_FALLBACK:-unset}" >> "$HOME/reviewer-env"\n'
    'printf "BASE=%s\\n" "${HAPAX_GLMCP_REVIEW_BASE_URL:-unset}" >> "$HOME/reviewer-env"\n'
    'printf "MODEL=%s\\n" "${HAPAX_GLMCP_REVIEW_MODEL:-unset}" >> "$HOME/reviewer-env"\n'
    "echo OK\n"
)
REVIEWER_FAILS = "cat >/dev/null 2>&1 || true\nexit 1\n"


def _stub(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    path.chmod(0o755)


def _harness(
    tmp_path: Path,
    *,
    reviewer: str = REVIEWER_OK,
    admission_rc: int = 0,
    writer_rc: int = 0,
    receipts_rc: int = 0,
) -> tuple[Path, dict[str, str]]:
    """A throwaway HOME plus a fake activation root whose scripts record what they were asked."""
    home = tmp_path / "home"
    root = tmp_path / "root"
    scripts = root / "scripts"
    venvbin = root / ".venv" / "bin"
    for directory in (scripts, venvbin, home / ".cache" / "hapax" / "relay" / "receipts"):
        directory.mkdir(parents=True)
    # `python <script> [args...]` -> run the bash stub with the args, preserving stdin.
    _stub(venvbin / "python", 'exec bash "$@"\n')
    _stub(scripts / "hapax-glmcp-reviewer", reviewer)
    # The admission stub records the call AND writes the relay admission (what a real mint does), so a
    # false mint is detectable; it honours HAPAX_RELAY_RECEIPT_DIR exactly as the real tool does.
    _stub(
        scripts / "hapax-glmcp-quota-admission",
        'printf "admission %s\\n" "$*" >> "$HOME/admission-calls"\n'
        'dir="${HAPAX_RELAY_RECEIPT_DIR:-$HOME/.cache/hapax/relay/receipts}"\n'
        'printf "schema: hapax.glmcp_quota_admission.v1\\nstatus: quota_available\\n" '
        '> "$dir/glmcp-quota-admission.yaml"\n'
        f"exit {admission_rc}\n",
    )
    _stub(
        scripts / "hapax-quota-telemetry-writer",
        f'printf "writer %s\\n" "$*" >> "$HOME/calls"\nexit {writer_rc}\n',
    )
    _stub(
        scripts / "hapax-platform-capability-receipts",
        f'printf "receipts %s\\n" "$*" >> "$HOME/calls"\nexit {receipts_rc}\n',
    )
    env = {
        "HOME": str(home),
        "PATH": os.environ["PATH"],
        "HAPAX_COUNCIL": str(root),
        "HAPAX_GLMCP_SEAT_ROOT_OVERRIDE": "1",
        "HAPAX_GLMCP_SEAT_RETRY_SLEEP": "0",
    }
    return home, env


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60
    )


def _relay_receipt(home: Path) -> Path:
    return home / ".cache" / "hapax" / "relay" / "receipts" / "glmcp-quota-admission.yaml"


def test_unsafe_case_reviewer_failure_mints_nothing(tmp_path: Path) -> None:
    """REQUIRED (seat ruling): a failed round trip gives exit 2 and NO admission receipt — the seat
    is left to lapse rather than minting an admission for a call the Coding Plan never served."""
    home, env = _harness(tmp_path, reviewer=REVIEWER_FAILS)
    result = _run(env)
    assert result.returncode == 2, result.stderr
    assert not _relay_receipt(home).exists(), "no admission may be minted when the round trip fails"
    assert not (home / "admission-calls").exists(), "observe-success must not run after a failure"


def test_happy_path_mints_then_folds_then_refreshes(tmp_path: Path) -> None:
    home, env = _harness(tmp_path)
    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert _relay_receipt(home).exists()
    calls = (home / "calls").read_text(encoding="utf-8")
    assert "writer --json --skip-receipts" in calls
    assert "receipts --platform glmcp" in calls


def test_pins_payg_off_and_coding_plan_endpoint(tmp_path: Path) -> None:
    """REQUIRED (seat ruling): PAYG fallback off and the Coding Plan endpoint are pinned."""
    home, env = _harness(tmp_path)
    result = _run(env)
    assert result.returncode == 0, result.stderr
    reviewer_env = (home / "reviewer-env").read_text(encoding="utf-8")
    assert "PAYG=0" in reviewer_env
    assert f"BASE={ENDPOINT}" in reviewer_env


def test_root_guard_refuses_foreign_tree_without_override(tmp_path: Path) -> None:
    home, env = _harness(tmp_path)
    del env["HAPAX_GLMCP_SEAT_ROOT_OVERRIDE"]
    result = _run(env)
    assert result.returncode == 4, result.stderr
    assert not (home / "admission-calls").exists()


def test_freshness_skip_does_no_round_trip(tmp_path: Path) -> None:
    home, env = _harness(tmp_path)
    _relay_receipt(home).write_text(
        "schema: hapax.glmcp_quota_admission.v1\nstatus: quota_available\n"
        f"observed_at: {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
        "stale_after_seconds: 900\n",
        encoding="utf-8",
    )
    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert not (home / "reviewer-env").exists(), "a fresh seat must skip the round trip"
    assert not (home / "admission-calls").exists()


def test_units_run_from_activation_worktree(tmp_path: Path) -> None:
    service = SERVICE.read_text(encoding="utf-8")
    assert f"ExecStart={ACTIVATION_ROOT}/scripts/hapax-glmcp-seat-refresh" in service
    assert f"WorkingDirectory={ACTIVATION_ROOT}" in service
    # The frozen-tree redirect must not return via the unit environment: no Environment= directive
    # may set HAPAX_COUNCIL or the root override (a mention in a comment is fine).
    env_directives = [ln for ln in service.splitlines() if ln.strip().startswith("Environment=")]
    assert not any("HAPAX_COUNCIL" in ln for ln in env_directives)
    assert not any("HAPAX_GLMCP_SEAT_ROOT_OVERRIDE" in ln for ln in env_directives)
    timer = TIMER.read_text(encoding="utf-8")
    assert "OnUnitActiveSec=5min" in timer
    # Enable-only: deploy enables but does not start it, so the seat installs (starts) it only after
    # independent review (seat ruling 2026-10-03) and a merge never auto-starts the round-trip timer.
    assert any(
        ln.strip().lower().startswith("# hapax-timer-enable-only:") for ln in timer.splitlines()
    )
    assert "[Install]" in timer
