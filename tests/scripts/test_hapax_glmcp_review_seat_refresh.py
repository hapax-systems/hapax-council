"""Behaviour tests for ``scripts/hapax-glmcp-review-seat-refresh`` — the accepted-release GLM review-seat
refresher (seat task ``glmcp-review-admission-accepted-release-producer-20261003``).

Each test RUNS the real bash script against stubbed reviewer / admission / telemetry-writer / receipts
tools in a throwaway ``HOME`` and a fake activation root (review finding on #4624: grepping the script
is not a behaviour test), so the root guard, the pinned Coding Plan first route, the freshness
skip, the no-mint-on-failure rule and the mint-on-success chain are each exercised through the real
code path without a network call. The wrapper invokes every tool as
``$W/.venv/bin/python $W/scripts/<tool>``, so the fake root supplies a ``.venv/bin/python`` shim that
execs its first argument under bash and the tool stubs are ordinary bash scripts.
"""

from __future__ import annotations

import io
import json
import os
import shlex
import subprocess
import sys
import urllib.error
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "hapax-glmcp-review-seat-refresh"
SERVICE = REPO / "systemd" / "units" / "hapax-glmcp-review-seat-refresh.service"
TIMER = REPO / "systemd" / "units" / "hapax-glmcp-review-seat-refresh.timer"
ACTIVATION_ROOT = "%h/.cache/hapax/source-activation/worktree"
ENDPOINT = "https://api.z.ai/api/coding/paas/v4"

PAYG_ENDPOINT = "https://api.z.ai/api/paas/v4"
BUDGET = "tb-20260924-zai-glm-payg-balance-burn"
CASE = "CASE-CAPACITY-ROUTING-GLMCP-PAYG-20260706"
PLAN_DIAGNOSTIC = (
    f"echo 'hapax-glmcp-reviewer: Coding Plan reply endpoint={ENDPOINT} model=glm-5.2' >&2\n"
)

# The reviewer stub records the pinned environment it was handed and drains the blind-review prompt
# on stdin before replying, so endpoint, model and fallback configuration are observable.
REVIEWER_OK = (
    "cat >/dev/null 2>&1 || true\n"
    'printf "PAYG=%s\\n" "${HAPAX_GLMCP_REVIEW_PAYG_FALLBACK:-unset}" >> "$HOME/reviewer-env"\n'
    'printf "BASE=%s\\n" "${HAPAX_GLMCP_REVIEW_BASE_URL:-unset}" >> "$HOME/reviewer-env"\n'
    'printf "MODEL=%s\\n" "${HAPAX_GLMCP_REVIEW_MODEL:-unset}" >> "$HOME/reviewer-env"\n'
    "echo OK\n" + PLAN_DIAGNOSTIC
)
REVIEWER_FAILS = "cat >/dev/null 2>&1 || true\nexit 1\n"
# Fails the first attempt, succeeds the second — exercises the bounded retry loop.
REVIEWER_FAILS_THEN_OK = (
    'n=$(cat "$HOME/attempts" 2>/dev/null || echo 0)\n'
    'n=$((n + 1)); printf "%s" "$n" > "$HOME/attempts"\n'
    "cat >/dev/null 2>&1 || true\n"
    'if [ "$n" -lt 2 ]; then exit 1; fi\n'
    "echo OK\n" + PLAN_DIAGNOSTIC
)


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
    _stub(
        venvbin / "python",
        f'if [ "$1" = "-" ]; then exec {shlex.quote(sys.executable)} "$@"; fi\nexec bash "$@"\n',
    )
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


def test_plan_serves_without_payg_despite_ambient_selection(tmp_path: Path) -> None:
    """Supersedes the PAYG-OFF pin: Crow ruling 20261013T224102Z, operator 22:38Z."""
    home, env = _provider_harness(tmp_path, "plan")
    env.update(
        HAPAX_GLMCP_REVIEW_BASE_URL=PAYG_ENDPOINT,
        HAPAX_GLMCP_REVIEW_PAYG_BASE_URL="https://api.z.ai/ambient",
        HAPAX_GLMCP_REVIEW_PAYG_FALLBACK="1",
        HAPAX_GLMCP_REVIEW_ALLOW_BASE_URL_OVERRIDE="1",
        HAPAX_GLMCP_REVIEW_MODEL="glm-5.3",
    )
    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert _requests(home) == [ENDPOINT]
    assert not list(_relay_receipt(home).parent.glob("glmcp-payg-spend-*.yaml"))
    admission = (home / "admission-calls").read_text()
    assert f"--endpoint {ENDPOINT}" in admission
    assert "--primary-error-class" not in admission


def test_payg_stdout_without_spend_receipt_mints_nothing(tmp_path: Path) -> None:
    # A buggy reviewer reports PAYG success but has lost its spend witness.
    reviewer = f"""cat >/dev/null
echo OK
echo 'hapax-glmcp-reviewer: PAYG fallback used endpoint={PAYG_ENDPOINT} model=glm-5.3 served_model=glm-5.3 primary_error_class=quota_exhausted spend_gate=eligible_active_budget budget_id={BUDGET} spend_receipt=glmcp-payg-spend-missing.yaml' >&2
"""
    home, env = _harness(tmp_path, reviewer=reviewer)
    result = _run(env)
    assert result.returncode == 2, result.stderr
    assert not (home / "admission-calls").exists()
    assert not _relay_receipt(home).exists()


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
        "route_id: glmcp.review.direct\n"
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
    assert f"ExecStart={ACTIVATION_ROOT}/scripts/hapax-glmcp-review-seat-refresh" in service
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


def _fresh_relay(home: Path, *, status: str, route: str, ttl: str) -> None:
    _relay_receipt(home).write_text(
        "schema: hapax.glmcp_quota_admission.v1\n"
        f"status: {status}\n"
        f"route_id: {route}\n"
        f"observed_at: {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
        f"stale_after_seconds: {ttl}\n",
        encoding="utf-8",
    )


def test_relay_ttl_is_never_shell_evaluated(tmp_path: Path) -> None:
    """Major 1 (codex, security): the relay TTL reaches bash arithmetic, so a crafted
    ``stale_after_seconds`` must never be shell-evaluated, and a non-numeric TTL fails closed
    (the seat refreshes rather than trusting it)."""
    home, env = _harness(tmp_path)
    marker = home / "INJECTED"
    _fresh_relay(
        home, status="quota_available", route="glmcp.review.direct", ttl=f'x[$(touch "{marker}")]'
    )
    result = _run(env)
    assert not marker.exists(), "the relay TTL must never be shell-evaluated (arithmetic injection)"
    # Fail closed: a non-numeric TTL is not trusted, so the seat refreshes (the round trip runs).
    assert (home / "reviewer-env").exists(), "a non-numeric TTL must fail closed to a refresh"
    assert result.returncode == 0, result.stderr


def test_freshness_skip_requires_quota_available_status(tmp_path: Path) -> None:
    """Major 2 (codex): a fresh receipt whose status is not ``quota_available`` (a hold/wall) must
    NOT authorize a skip; the seat refreshes."""
    home, env = _harness(tmp_path)
    _fresh_relay(home, status="quota_blocked", route="glmcp.review.direct", ttl="900")
    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert (home / "reviewer-env").exists(), "a non-available status must not authorize a skip"


def test_freshness_skip_requires_expected_route(tmp_path: Path) -> None:
    """Major 2 (codex): a fresh positive receipt for a DIFFERENT route must not authorize a skip."""
    home, env = _harness(tmp_path)
    _fresh_relay(home, status="quota_available", route="glmcp.something.else", ttl="900")
    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert (home / "reviewer-env").exists(), "another route's receipt must not authorize a skip"


def test_admission_failure_exits_5(tmp_path: Path) -> None:
    """Major 3 (claude-1): exercise the exit-5 branch (admission fails after a good round trip)."""
    home, env = _harness(tmp_path, admission_rc=1)
    assert _run(env).returncode == 5


def test_ledger_fold_failure_exits_3(tmp_path: Path) -> None:
    """Major 3: exercise the exit-3 branch (ledger fold fails after the admission was minted)."""
    home, env = _harness(tmp_path, writer_rc=1)
    assert _run(env).returncode == 3


def test_receipt_refresh_failure_exits_6(tmp_path: Path) -> None:
    """Major 3: exercise the exit-6 branch (glmcp receipt refresh fails after the fold)."""
    home, env = _harness(tmp_path, receipts_rc=1)
    assert _run(env).returncode == 6


def test_retry_loop_recovers_from_a_transient_failure(tmp_path: Path) -> None:
    """Major 3: exercise the bounded retry loop — a transient first-attempt failure then success."""
    home, env = _harness(tmp_path, reviewer=REVIEWER_FAILS_THEN_OK)
    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert (home / "attempts").read_text(encoding="utf-8").strip() == "2"
    assert _relay_receipt(home).exists()


def _provider_harness(tmp_path: Path, scenario: str) -> tuple[Path, dict[str, str]]:
    """Real reviewer, live-ledger gate, spend writer and reconciler; fake HTTP + key only."""
    home, env = _harness(
        tmp_path,
        reviewer=f"exec {shlex.quote(sys.executable)} {shlex.quote(__file__)} --fake-provider\n",
    )
    _stub(
        Path(env["HAPAX_COUNCIL"]) / "scripts/hapax-glmcp-quota-admission",
        'printf "admission %s\\n" "$*" >> "$HOME/admission-calls"\n'
        f'exec {shlex.quote(sys.executable)} {shlex.quote(str(REPO / "scripts/hapax-glmcp-quota-admission"))} "$@"\n',
    )
    env["SEAT_TEST_SCENARIO"] = scenario
    env["HAPAX_QUOTA_SPEND_LEDGER_LIVE"] = str(home / "ledger.json")
    ledger = json.loads((REPO / "config/quota-spend-ledger-fixtures.json").read_text())
    now = datetime.now(UTC)
    ledger["captured_at"] = now.isoformat()
    budget = next(b for b in ledger["transition_budgets"] if b["budget_id"] == BUDGET)
    budget.update(
        budget_id=BUDGET,
        created_at=(now - timedelta(hours=1)).isoformat(),
        expires_at=(now + timedelta(days=1)).isoformat(),
        subscription_path_checked_at=now.isoformat(),
    )
    for other in ledger["transition_budgets"]:
        if other is not budget and "glmcp-review-direct" in other.get("profiles_allowed", []):
            other["lifecycle_state"] = "retired"
    (home / "ledger.json").write_text(json.dumps(ledger))
    return home, env


def _requests(home: Path) -> list[str]:
    return (home / "requests").read_text().splitlines()


def test_fresh_quota_wall_mints_receipted_payg_form(tmp_path: Path) -> None:
    home, env = _provider_harness(tmp_path, "quota")
    result = _run(env)
    assert result.returncode == 0, (
        result.stderr + (home / ".cache/hapax/relay/glmcp-review-seat-refresh.log").read_text()
    )
    assert _requests(home) == [ENDPOINT, PAYG_ENDPOINT]
    receipts = list(_relay_receipt(home).parent.glob("glmcp-payg-spend-*.yaml"))
    assert len(receipts) == 1
    receipt = receipts[0].read_text()
    assert "schema: hapax.glmcp_payg_spend.v1" in receipt
    assert "status: spend_reconciled" in receipt
    assert f"budget_id: {BUDGET}" in receipt
    assert f"authority_case: {CASE}" in receipt
    args = (home / "admission-calls").read_text()
    assert f"--endpoint {PAYG_ENDPOINT} --model glm-5.3" in args
    assert "--primary-error-class quota_exhausted" in args
    assert f"--quota-wall-evidence-ref {receipts[0].name}" in args
    assert (home / "calls").read_text().splitlines() == [
        "writer --json --skip-receipts",
        "receipts --platform glmcp",
    ]


@pytest.mark.parametrize("scenario", ["missing", "stale", "wrong-task", "frozen", "wrong-schema"])
def test_unusable_paid_receipt_never_admits(tmp_path: Path, scenario: str) -> None:
    home, env = _provider_harness(tmp_path, scenario)
    result = _run(env)
    assert _requests(home) == [ENDPOINT, PAYG_ENDPOINT]
    assert result.returncode == 2, result.stderr
    assert not (home / "admission-calls").exists()
    assert not (home / "calls").exists()


@pytest.mark.parametrize(
    "field,value", [("budget_id", "different-budget"), ("authority_case", "CASE-DIFFERENT")]
)
def test_wrong_budget_or_case_refuses_before_paid_request(
    tmp_path: Path, field: str, value: str
) -> None:
    home, env = _provider_harness(tmp_path, "quota")
    ledger_path = home / "ledger.json"
    ledger = json.loads(ledger_path.read_text())
    next(b for b in ledger["transition_budgets"] if b["budget_id"] == BUDGET)[field] = value
    ledger_path.write_text(json.dumps(ledger))
    result = _run(env)
    assert result.returncode == 2, result.stderr
    assert set(_requests(home)) == {ENDPOINT}
    assert not (home / "admission-calls").exists()
    assert not list(_relay_receipt(home).parent.glob("glmcp-payg-spend-*.yaml"))


def test_non_quota_failure_never_uses_payg(tmp_path: Path) -> None:
    home, env = _provider_harness(tmp_path, "non-quota")
    assert _run(env).returncode == 2
    assert set(_requests(home)) == {ENDPOINT}
    assert not (home / "admission-calls").exists()


def test_producer_pins_budget_and_case(tmp_path: Path) -> None:
    home, env = _harness(
        tmp_path,
        reviewer=REVIEWER_OK
        + 'printf "%s\\n%s\\n" "$HAPAX_GLMCP_REVIEW_REQUIRED_BUDGET_ID" "$HAPAX_GLMCP_REVIEW_REQUIRED_AUTHORITY_CASE" > "$HOME/bindings"\n',
    )
    env.update(
        HAPAX_GLMCP_REVIEW_REQUIRED_BUDGET_ID="ambient-budget",
        HAPAX_GLMCP_REVIEW_REQUIRED_AUTHORITY_CASE="CASE-AMBIENT",
    )
    assert _run(env).returncode == 0
    assert (home / "bindings").read_text().splitlines() == [BUDGET, CASE]


@pytest.mark.parametrize("binding", ["BUDGET_ID", "AUTHORITY_CASE", None])
def test_reviewer_binding_before_reservation_and_unset_compatibility(
    tmp_path: Path, binding: str | None
) -> None:
    home, env = _provider_harness(tmp_path, "quota")
    env.update(
        HAPAX_GLMCP_REVIEW_PAYG_FALLBACK="1",
        HAPAX_GLMCP_REVIEW_MODEL="glm-5.2",
        HAPAX_GLMCP_REVIEW_TASK_ID="glmcp-review-seat-payg-producer-20261013",
    )
    if binding:
        env["HAPAX_GLMCP_REVIEW_REQUIRED_" + binding] = "mismatch"
    result = subprocess.run(
        [sys.executable, __file__, "--fake-provider"],
        input="Blind fixture",
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    receipts = list(_relay_receipt(home).parent.glob("glmcp-payg-spend-*.yaml"))
    ledger = json.loads((home / "ledger.json").read_text())
    reservations = [
        r for r in ledger["spend_receipts"] if r["task_id"] == env["HAPAX_GLMCP_REVIEW_TASK_ID"]
    ]
    if binding:
        assert result.returncode == 1, result.stderr
        assert "differs from caller binding" in result.stderr
        assert _requests(home) == [ENDPOINT]
        assert receipts == []
        assert reservations == []
    else:
        assert result.returncode == 0, result.stderr
        assert _requests(home) == [ENDPOINT, PAYG_ENDPOINT]
        assert len(receipts) == len(reservations) == 1


def _fake_provider_main() -> None:
    # This subprocess has a throwaway HOME and ledger. No real secret reader or transport is used.
    sys.path.insert(0, str(REPO))
    from test_hapax_glmcp_reviewer import FakeResponse, _load_module

    module = _load_module()
    home = Path.home()
    scenario = os.environ["SEAT_TEST_SCENARIO"]

    def fake_open(request: object, *, timeout: float) -> FakeResponse:
        endpoint = request.full_url.removesuffix("/chat/completions")
        with (home / "requests").open("a") as stream:
            stream.write(endpoint + "\n")
        if endpoint == ENDPOINT and scenario != "plan":
            code = "1303" if scenario == "non-quota" else "1310"
            raise urllib.error.HTTPError(
                request.full_url,
                429,
                "fixture",
                {},
                io.BytesIO(json.dumps({"error": {"code": code, "message": "fixture"}}).encode()),
            )
        assert endpoint in (ENDPOINT, PAYG_ENDPOINT), "ambient endpoint escaped the pins"
        if endpoint == PAYG_ENDPOINT:
            # Reservation must exist BEFORE the fake paid request, as well as after reconciliation.
            receipts = list(_relay_receipt(home).parent.glob("glmcp-payg-spend-*.yaml"))
            assert len(receipts) == 1
            assert "status: spend_estimated" in receipts[0].read_text()
        return FakeResponse(
            {
                "model": "glm-5.3" if endpoint == PAYG_ENDPOINT else "glm-5.2",
                "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 1},
            }
        )

    module.open_no_redirect = fake_open
    try:
        reply = module.call_glm(sys.stdin.read(), module.load_config(), "test-only-key")
    except module.ApiError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from exc
    for receipt in _relay_receipt(home).parent.glob("glmcp-payg-spend-*.yaml"):
        body = receipt.read_text()
        if scenario == "missing":
            receipt.unlink()
            continue
        if scenario == "stale":
            body = body.replace(os.environ["HAPAX_GLMCP_REVIEW_TASK_HASH"], "sha256:" + "0" * 64)
        if scenario == "wrong-task":
            body = body.replace(os.environ["HAPAX_GLMCP_REVIEW_TASK_ID"], "different-task")
        if scenario == "frozen":
            body = body.replace("status: spend_reconciled", "status: spend_frozen")
        if scenario == "wrong-schema":
            body = body.replace("hapax.glmcp_payg_spend.v1", "different.schema.v1")
        receipt.write_text(body)
    print(reply)


if __name__ == "__main__":
    assert sys.argv[1:] == ["--fake-provider"]
    _fake_provider_main()
