"""The GLM review seat's passive admission receipt lives 15 minutes; with no producer to renew it
the seat had been expired since 2026-08-04 and every council review dossier was refused as seated
by a blocked family — 40 open PRs admitted nothing for four weeks (memory
`glm-review-seat-expires-every-15-minutes`, L-158). `scripts/hapax-glmcp-seat-refresh` is that
producer; `hapax-glmcp-seat-refresh.timer` schedules it after each service completion.

These tests RUN the script against stubbed reviewer / admission / telemetry-writer scripts in a
throwaway HOME (review finding on #4624: text greps of the script were not behaviour tests), so
the freshness guard, the root guard, the pins, the retry loop, the no-mint-on-failure rule, the
redaction and the writer's exit-code handling are each exercised through the real code path
without a network call."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "hapax-glmcp-seat-refresh"
RECEIPTS_SCRIPT = REPO / "scripts" / "hapax-platform-capability-receipts"
SERVICE = REPO / "systemd" / "units" / "hapax-glmcp-seat-refresh.service"
TIMER = REPO / "systemd" / "units" / "hapax-glmcp-seat-refresh.timer"
UNIT = REPO / "systemd" / "units" / "hapax-glmcp-seat-refresh.service"
ACTIVATION_ROOT = "%h/.cache/hapax/source-activation/worktree"

REVIEWER_OK = (
    'echo "PAYG=${HAPAX_GLMCP_REVIEW_PAYG_FALLBACK:-unset}" >> "$HOME/reviewer-env"\n'
    'echo "BASE=${HAPAX_GLMCP_REVIEW_BASE_URL:-unset}" >> "$HOME/reviewer-env"\n'
    'echo "SECRET=${HAPAX_GLMCP_REVIEW_SECRET_ENTRY:-unset}" >> "$HOME/reviewer-env"\n'  # pragma: allowlist secret
    'echo "OVERRIDE=${HAPAX_GLMCP_REVIEW_ALLOW_SECRET_ENTRY_OVERRIDE:-unset}" >> "$HOME/reviewer-env"\n'  # pragma: allowlist secret
    "echo OK\n"
)
REVIEWER_ALWAYS_FAILS_SILENTLY = "exit 1\n"
REVIEWER_FAILS_WITH_OUTPUT = "echo NOT_OK\nexit 23\n"
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


def _glmcp_receipt_json(
    *,
    status: str,
    remaining: int,
    age: int,
    now: datetime,
    receipt_stale: bool = False,
) -> str:
    """A complete glmcp platform-capability receipt built through the production model.

    The dispatcher reads this document through its loader (schema, platform, skew, duration syntax,
    freshness), and since round 8 so does the seat refresher, so the fixture must be a receipt the
    loader accepts — not three fields in a dict (review finding on #4624, round 8). The quota
    surface was observed ``age`` seconds ago with ``remaining`` seconds of stale_after left at that
    moment; the receipt itself lives 24 h so that only the quota surface decides freshness.
    """
    from shared.platform_capability_receipts import (
        CliEvidence,
        EvidenceStatus,
        PlatformCapabilityReceipt,
        ProviderDocsEvidence,
        SurfaceEvidence,
        WrapperEvidence,
    )

    observed = now - timedelta(seconds=age)
    observed_ok = status == "observed"
    quota = SurfaceEvidence(
        status=EvidenceStatus(status),
        source="local_receipt_probe",
        observed_at=observed,
        stale_after=f"{remaining}s",
        evidence_refs=["local:glmcp:quota-admission-receipt:glmcp.review.direct:present"]
        if observed_ok
        else [],
        reason_codes=[] if observed_ok else ["account_live_quota_receipt_absent"],
    )
    # ``receipt_stale`` makes the RECEIPT stale (observed two hours ago, lives one hour) while its
    # quota surface still reads fresh: exactly the document a field-picking guard would trust and
    # the dispatcher's loader drops.
    receipt = PlatformCapabilityReceipt(
        receipt_id=f"test-glmcp-{int(observed.timestamp())}",
        platform="glmcp",
        routes=["glmcp.review.direct"],
        observed_at=(now - timedelta(hours=2)) if receipt_stale else observed,
        stale_after="1h" if receipt_stale else "24h",
        cli=CliEvidence(binary="hapax-glmcp-reviewer", available=True, version="test"),
        wrapper=WrapperEvidence(
            path="scripts/hapax-glmcp-reviewer", exists=True, executable=True, sha256="abc123"
        ),
        capability=SurfaceEvidence(
            status=EvidenceStatus.OBSERVED,
            source="test",
            observed_at=observed,
            stale_after="24h",
            evidence_refs=["test:glmcp:capability"],
        ),
        resource=SurfaceEvidence(
            status=EvidenceStatus.OBSERVED,
            source="test",
            observed_at=observed,
            stale_after="24h",
            evidence_refs=["test:glmcp:resource"],
        ),
        quota=quota,
        provider_docs=ProviderDocsEvidence(
            refs=["test:glmcp:provider-docs"], fetched_at=observed, stale_after="30d"
        ),
    )
    return json.dumps(receipt.model_dump(mode="json"))


def _harness(
    tmp_path: Path,
    *,
    reviewer: str = REVIEWER_OK,
    writer_rc: int = 0,
    admission_rc: int = 0,
    receipt_status: str | None = None,
    receipt_remaining: int = 0,
    receipt_age: int = 0,
    relay_receipt_observed_ago: int | None = None,
    refreshed_remaining: int | None = 900,
    malformed_receipt: bool = False,
    receipt_stale: bool = False,
    now: datetime | None = None,
) -> tuple[Path, Path]:
    """A throwaway HOME plus a fake council root whose scripts record what they were asked.

    ``receipt_status`` writes the dispatcher's own glmcp platform-capability receipt with that quota
    status, generated ``receipt_age`` seconds ago and carrying ``receipt_remaining`` seconds of
    stale_after at generation. ``relay_receipt_observed_ago`` writes a raw admission receipt (the
    thing the guard must NOT trust on its own). ``refreshed_remaining`` is what the stubbed
    capability-receipt refresh leaves on disk after the writer (None: it leaves the old receipt).
    ``malformed_receipt`` writes the pre-round-8 three-field document the loader rejects. The
    receipts script's ``--show`` is the real one, run against this HOME's receipt directory.
    """
    home = tmp_path / "home"
    council = tmp_path / "council"
    scripts = council / "scripts"
    scripts.mkdir(parents=True)
    (home / ".cache" / "hapax" / "relay" / "receipts").mkdir(parents=True)
    receipts_dir = home / ".cache" / "hapax" / "platform-capability-receipts"
    receipts_dir.mkdir(parents=True)
    _stub(scripts / "hapax-glmcp-reviewer", reviewer)
    _stub(
        scripts / "hapax-glmcp-quota-admission",
        'printf "%s\\n" "$*" >> "$HOME/admission-calls"\n'
        'printf "admission %s\\n" "$*" >> "$HOME/calls"\n'
        f'echo "receipt ok"\nexit {admission_rc}\n',
    )
    _stub(
        scripts / "hapax-quota-telemetry-writer",
        'printf "writer %s\\n" "$*" >> "$HOME/calls"\n'
        'echo "wrote live ledger"\necho "capability receipts DEGRADED for one provider"\n'
        f"exit {writer_rc}\n",
    )
    _stub(
        scripts / "hapax-platform-capability-receipts",
        'printf "receipts %s\\n" "$*" >> "$HOME/calls"\n'
        'case " $* " in\n'
        '  *" --show "*) exec "$HAPAX_TEST_PYTHON" "$HAPAX_TEST_RECEIPTS_SCRIPT" "$@" ;;\n'
        "  *)\n"
        '    if [ -f "$HOME/refreshed-receipt.json" ]; then\n'
        '      cp "$HOME/refreshed-receipt.json" "$HOME/.cache/hapax/platform-capability-receipts/glmcp.json"\n'
        "    fi\n"
        '    echo "glmcp: wrote (stub)"\n'
        '    exit "${HAPAX_TEST_RECEIPTS_RC:-0}"\n'
        "    ;;\n"
        "esac\n",
    )
    now = now or datetime.now(UTC)
    if malformed_receipt:
        (receipts_dir / "glmcp.json").write_text(
            json.dumps(
                {
                    "platform": "glmcp",
                    "observed_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "quota": {
                        "status": "observed",
                        "observed_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "stale_after": "900s",
                    },
                }
            ),
            encoding="utf-8",
        )
    elif receipt_status is not None:
        (receipts_dir / "glmcp.json").write_text(
            _glmcp_receipt_json(
                status=receipt_status,
                remaining=receipt_remaining,
                age=receipt_age,
                now=now,
                receipt_stale=receipt_stale,
            ),
            encoding="utf-8",
        )
    if refreshed_remaining is not None:
        (home / "refreshed-receipt.json").write_text(
            _glmcp_receipt_json(status="observed", remaining=refreshed_remaining, age=1, now=now),
            encoding="utf-8",
        )
    if relay_receipt_observed_ago is not None:
        observed = now - timedelta(seconds=relay_receipt_observed_ago)
        (
            home / ".cache" / "hapax" / "relay" / "receipts" / "glmcp-quota-admission.yaml"
        ).write_text(
            "schema: hapax.glmcp_quota_admission.v1\nstatus: quota_available\n"
            f"observed_at: {observed.strftime('%Y-%m-%dT%H:%M:%SZ')}\nstale_after_seconds: 900\n",
            encoding="utf-8",
        )
    return home, council


def _run(
    home: Path,
    council: Path,
    *,
    allow_root: bool = True,
    receipts_rc: int = 0,
    path: str | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {
        "HOME": str(home),
        "HAPAX_COUNCIL": str(council),
        "PATH": path or os.environ["PATH"],
        "TMPDIR": str(home),
        "HAPAX_GLMCP_SEAT_RETRY_SLEEP": "0",
        # The stubbed receipts script delegates --show to the real one, in this interpreter.
        "HAPAX_TEST_PYTHON": sys.executable,
        "HAPAX_TEST_RECEIPTS_SCRIPT": str(RECEIPTS_SCRIPT),
        "HAPAX_TEST_RECEIPTS_RC": str(receipts_rc),
        # Inherited values that must never reach the probe (review findings on #4624, rounds 3–4).
        "HAPAX_GLMCP_REVIEW_BASE_URL": "https://evil.example/paas/v4",
        "HAPAX_GLMCP_REVIEW_SECRET_ENTRY": "glmcp/someone-elses-key",  # pragma: allowlist secret
        "HAPAX_GLMCP_REVIEW_ALLOW_SECRET_ENTRY_OVERRIDE": "1",  # pragma: allowlist secret
    }
    if allow_root:
        env["HAPAX_GLMCP_SEAT_ROOT_OVERRIDE"] = "1"
    return subprocess.run(
        ["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=120
    )


def _witnesses(home: Path) -> list[Path]:
    return sorted((home / ".cache" / "hapax" / "glmcp-admission-witness").glob("*.yaml"))


def test_script_exists_is_executable_and_parses() -> None:
    assert SCRIPT.is_file()
    assert SCRIPT.stat().st_mode & 0o111, "must be executable"
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True, capture_output=True, timeout=10)


def _envelope(tmp_path: Path) -> dict[str, int]:
    home, council = _harness(tmp_path)
    proc = subprocess.run(
        ["bash", str(SCRIPT), "--envelope"],
        env={
            "HOME": str(home),
            "HAPAX_COUNCIL": str(council),
            "PATH": os.environ["PATH"],
            "HAPAX_GLMCP_SEAT_ROOT_OVERRIDE": "1",
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_post_mint_tail_starts_at_admissions_observed_at(tmp_path: Path) -> None:
    e = _envelope(tmp_path)
    # observe_success stamps observed_at BEFORE validation and the atomic write. Charge
    # its entire deadline, including kill grace, plus all four possible diagnostic filters.
    tail = (
        e["admission_timeout_s"]
        + e["writer_timeout_s"]
        + e["receipts_timeout_s"]
        + e["show_timeout_s"]
        + 4 * e["timeout_kill_after_s"]
        + 4 * (e["filter_timeout_s"] + e["timeout_kill_after_s"])
        + e["post_mint_process_launch_slack_s"]
        + e["post_mint_file_io_slack_s"]
        + e["post_mint_scheduler_slack_s"]
        + e["post_check_shutdown_s"]
        + e["service_safety_margin_s"]
    )
    assert e["post_mint_tail_s"] == tail
    assert tail + e["seat_skip_min_remaining_s"] < 900


def test_preflight_refuses_old_deadlines_before_provider_call(tmp_path: Path, monkeypatch) -> None:
    e = _envelope(tmp_path / "envelope")
    home, council = _harness(tmp_path / "run")
    unsafe = tmp_path / "unsafe-refresh"
    unsafe.write_text(
        SCRIPT.read_text()
        .replace(f"ADMISSION_TIMEOUT_S={e['admission_timeout_s']}", "ADMISSION_TIMEOUT_S=35")
        .replace(f"WRITER_TIMEOUT_S={e['writer_timeout_s']}", "WRITER_TIMEOUT_S=90")
    )
    monkeypatch.setattr(sys.modules[__name__], "SCRIPT", unsafe)
    result = _run(home, council)
    assert result.returncode == 7, result.stdout + result.stderr
    assert "OVERRUN_RENEWAL_ENVELOPE_S=" in result.stderr
    assert "POST_MINT_TAIL_S=" in result.stderr
    assert "roundtrip attempt" not in result.stdout
    assert not (home / "admission-calls").exists()


def test_delayed_admission_completion_keeps_original_observed_at(tmp_path: Path) -> None:
    e = _envelope(tmp_path / "envelope")
    epoch = int(datetime.now(UTC).timestamp())
    home, council = _harness(tmp_path / "run", refreshed_remaining=None)
    delay = e["admission_timeout_s"] - 1
    (home / "clock").write_text(str(epoch))
    (home / "admission-receipt.json").write_text(
        _glmcp_receipt_json(
            status="observed", remaining=900, age=0, now=datetime.fromtimestamp(epoch, UTC)
        )
    )
    # The receipt fixture is stamped when admission observes success. Only afterward does
    # admission finish its delayed validation/write; publication must preserve that age.
    _stub(
        council / "scripts/hapax-glmcp-quota-admission",
        f'echo {epoch} > "$HOME/admission-observed-at"\n'
        f'echo {epoch + delay} > "$HOME/clock"\n'
        'cp "$HOME/admission-receipt.json" "$HOME/refreshed-receipt.json"\n'
        'echo "receipt ok"\n',
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    date = shutil.which("date")
    _stub(
        bin_dir / "date",
        f'if [ "$*" = "-u +%s" ]; then cat "$HOME/clock"; else exec "{date}" "$@"; fi\n',
    )
    result = _run(home, council, path=f"{bin_dir}:{os.environ['PATH']}")
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"{900 - delay}s remain on the accepted glmcp receipt" in result.stdout
    assert (
        int((home / "clock").read_text()) - int((home / "admission-observed-at").read_text())
        == delay
    )


@pytest.mark.parametrize(
    "diagnostic",
    [
        # Synthetic sentinels: the redaction under test must remove them; none is a credential.
        '{"api_key": "DUMMY_REVIEW_SENTINEL"}',  # pragma: allowlist secret
        '{"password": "DUMMY_REVIEW_SENTINEL SECOND_SENTINEL"}',  # pragma: allowlist secret
        r'{"token": "DUMMY_REVIEW_SENTINEL \"SECOND_SENTINEL\""}',  # pragma: allowlist secret
        "password='DUMMY_REVIEW_SENTINEL SECOND_SENTINEL'",  # pragma: allowlist secret
        'api_key="DUMMY_REVIEW_SENTINEL SECOND_SENTINEL"',  # pragma: allowlist secret
        "token=DUMMY_REVIEW_SENTINEL",  # pragma: allowlist secret
        "secret: DUMMY_REVIEW_SENTINEL",  # pragma: allowlist secret
        "Authorization: Bearer DUMMY_REVIEW_SENTINEL",  # pragma: allowlist secret
        'password="DUMMY_REVIEW_SENTINEL\nSECOND_SENTINEL"',  # pragma: allowlist secret
        'password="DUMMY_REVIEW_SENTINEL SECOND_SENTINEL',  # pragma: allowlist secret
    ],
    ids=[
        "json-key",
        "json-spaces",
        "json-escaped",
        "single-quotes",
        "double-quotes",
        "equals",
        "colon",
        "bearer",
        "multiline",
        "unterminated",
    ],
)
def test_diagnostic_credentials_are_completely_redacted(tmp_path: Path, diagnostic: str) -> None:
    home, council = _harness(
        tmp_path, reviewer=f"cat >&2 <<'DIAGNOSTIC'\n{diagnostic}\nDIAGNOSTIC\nexit 1\n"
    )
    result = _run(home, council)
    assert result.returncode == 2
    output = result.stdout + result.stderr
    assert "<redacted>" in output
    assert "DUMMY_REVIEW_SENTINEL" not in output
    assert "SECOND_SENTINEL" not in output


@pytest.mark.parametrize("stderr_present", [False, True])
@pytest.mark.parametrize(
    "reason",
    [
        "receipt_absent",
        "receipt_invalid:ValueError",
        "receipt_stale_or_superseded",
        "receipt_dir_unloadable:PermissionError",
    ],
)
def test_show_rejection_warns_with_reason_remedy_and_sanitized_stderr(
    tmp_path: Path, reason: str, stderr_present: bool
) -> None:
    home, council = _harness(tmp_path, reviewer=REVIEWER_ALWAYS_FAILS_SILENTLY)
    payload = json.dumps(
        {
            "receipts": [
                {
                    "platform": "glmcp",
                    "accepted": False,
                    "reason": reason
                    + ' {"api_key": "DUMMY_REASON_SENTINEL"}',  # pragma: allowlist secret
                }
            ],
            "unrelated": "DUMMY_UNRELATED_SENTINEL",
        }
    )
    _stub(
        council / "scripts/hapax-platform-capability-receipts",
        f"cat <<'REJECTION'\n{payload}\nREJECTION\n"
        + (
            "echo 'stderr detail token=DUMMY_STDERR_SENTINEL' >&2\n" if stderr_present else ""
        )  # pragma: allowlist secret
        + "exit 1\n",
    )
    result = _run(home, council)
    assert result.returncode == 2
    assert f"--show WARNING: {reason}" in result.stderr
    assert "Next:" in result.stderr
    assert "hapax-platform-capability-receipts --platform glmcp" in result.stderr
    assert ("stderr detail" in result.stderr) == stderr_present
    assert "DUMMY_" not in result.stdout + result.stderr
    assert "roundtrip attempt 3:" in result.stdout


def test_refresh_threshold_is_derived_from_every_stage_and_a_skip_cannot_lapse(
    tmp_path: Path,
) -> None:
    """The threshold covers bounded commands and every non-command wall-clock term.

    Review round 11 found that the old arithmetic stopped at 540 s of nominal command time plus
    the 60 s timer window. This recomputes the complete service chain, proves it fits the unit's
    exact whole-service ceiling, and then derives the skip and overrun invariants from that ceiling.
    """
    e = _envelope(tmp_path)
    review = (
        e["review_attempts"] * e["review_attempt_timeout_s"]
        + (e["review_attempts"] - 1) * e["review_retry_sleep_s"]
    )
    core_commands = (
        e["show_timeout_s"]
        + review
        + e["admission_timeout_s"]
        + e["writer_timeout_s"]
        + e["receipts_timeout_s"]
        + e["show_timeout_s"]
    )
    kill_envelope = e["timed_command_count"] * e["timeout_kill_after_s"]
    filter_envelope = e["filter_invocations_max"] * (
        e["filter_timeout_s"] + e["timeout_kill_after_s"]
    )
    accounted_service = (
        core_commands
        + kill_envelope
        + filter_envelope
        + e["process_launch_slack_s"]
        + e["file_io_slack_s"]
        + e["service_scheduler_slack_s"]
        + e["service_safety_margin_s"]
    )
    service = accounted_service + e["service_bound_reserve_s"]
    chain = (
        e["post_check_shutdown_s"]
        + e["timer_accuracy_s"]
        + e["timer_scheduler_slack_s"]
        + service
        + e["no_lapse_safety_margin_s"]
    )
    post_mint_tail = (
        e["admission_timeout_s"]
        + e["writer_timeout_s"]
        + e["receipts_timeout_s"]
        + e["show_timeout_s"]
        + e["post_mint_timed_command_count"] * e["timeout_kill_after_s"]
        + e["post_mint_filter_invocations_max"]
        * (e["filter_timeout_s"] + e["timeout_kill_after_s"])
        + e["post_mint_process_launch_slack_s"]
        + e["post_mint_file_io_slack_s"]
        + e["post_mint_scheduler_slack_s"]
        + e["post_check_shutdown_s"]
        + e["service_safety_margin_s"]
    )
    assert e["review_envelope_s"] == review
    assert e["core_command_envelope_s"] == core_commands
    assert e["timeout_kill_envelope_s"] == kill_envelope
    assert e["filter_envelope_s"] == filter_envelope
    assert e["accounted_service_chain_s"] == accounted_service
    assert accounted_service <= e["whole_service_bound_s"]
    assert e["service_envelope_s"] == service
    assert service == e["whole_service_bound_s"] == 600
    assert e["chain_envelope_s"] == chain
    assert e["post_mint_tail_s"] == post_mint_tail
    assert e["seat_refresh_threshold_s"] == e["timer_inactive_delay_s"] + chain
    assert e["seat_skip_min_remaining_s"] == (
        e["seat_refresh_threshold_s"] + e["receipt_rounding_guard_s"]
    )
    assert e["overrun_renewal_envelope_s"] == (post_mint_tail + e["seat_skip_min_remaining_s"])
    assert e["review_attempts"] == 3
    # a skip must be possible at all inside the seat's life, or the guard is dead code
    assert e["seat_refresh_threshold_s"] < e["seat_life_s"]
    # Even a prior run which minted before its worst-case tail must leave enough life for the
    # completion-relative delay and the entire next renewal.
    assert e["overrun_renewal_envelope_s"] < e["seat_life_s"], e
    assert e["seat_visible_min_s"] == e["seat_skip_min_remaining_s"]
    assert e["review_inner_timeout_s"] < e["review_attempt_timeout_s"]
    assert e["service_safety_margin_s"] > 0
    assert e["no_lapse_safety_margin_s"] > 0
    timer = TIMER.read_text(encoding="utf-8")
    assert _unit_value(timer, "Timer", "OnUnitActiveSec") is None
    assert (
        _unit_value(timer, "Timer", "OnUnitInactiveSec") == "30s"
        and e["timer_inactive_delay_s"] == 30
    )
    assert _unit_value(timer, "Timer", "AccuracySec") == "30s" and e["timer_accuracy_s"] == 30
    script = SCRIPT.read_text(encoding="utf-8")
    assert "remaining > SEAT_SKIP_MIN_REMAINING_S" in script
    assert "remaining <= SEAT_VISIBLE_MIN_S" in script
    for stage in (
        "ADMISSION_TIMEOUT_S",
        "WRITER_TIMEOUT_S",
        "RECEIPTS_TIMEOUT_S",
        "REVIEW_ATTEMPT_TIMEOUT_S",
    ):
        assert f'bounded_timeout "${stage}"' in script, stage


def test_an_overrunning_oneshot_cannot_consume_the_next_activation(tmp_path: Path) -> None:
    """Replay the review's overrun on the production budgets and timer wire semantics.

    The prior service starts 300 s before the old periodic firing, mints 180 s before it, and
    remains active for its bounded post-mint tail. OnUnitActiveSec consumes the firing; its next
    period plus a worst-case renewal exposes a lapse. OnUnitInactiveSec has no firing while the
    service is active and schedules only after completion, so the same path renews before expiry.
    """
    e = _envelope(tmp_path)
    timer = TIMER.read_text(encoding="utf-8")

    def seconds(value: str) -> int:
        for suffix, multiplier in (("min", 60), ("s", 1)):
            if value.endswith(suffix):
                return int(value.removesuffix(suffix)) * multiplier
        raise AssertionError(f"unsupported timer duration: {value}")

    def next_start(timer_text: str, previous_start: int, previous_finish: int) -> int:
        """Apply systemd's active-relative vs inactive-relative timer semantics to one overrun."""
        accuracy = seconds(_unit_value(timer_text, "Timer", "AccuracySec") or "")
        active_delay = _unit_value(timer_text, "Timer", "OnUnitActiveSec")
        inactive_delay = _unit_value(timer_text, "Timer", "OnUnitInactiveSec")
        assert (active_delay is None) != (inactive_delay is None), timer_text
        if inactive_delay is not None:
            trigger = previous_finish + seconds(inactive_delay)
        else:
            period = seconds(active_delay or "")
            trigger = previous_start + period
            while trigger < previous_finish:
                trigger += period  # an elapse while active is consumed, not queued
        return trigger + accuracy

    old_period_s = 300
    missed_firing_at = 0
    previous_start_at = missed_firing_at - old_period_s
    receipt_minted_at = missed_firing_at - 180
    previous_finish_at = receipt_minted_at + e["post_mint_tail_s"]
    receipt_expires_at = receipt_minted_at + e["seat_life_s"]
    assert previous_start_at < receipt_minted_at < missed_firing_at < previous_finish_at
    assert previous_finish_at - previous_start_at <= e["service_envelope_s"]

    # The removed OnUnitActiveSec wiring consumes t=0 because the target is active, then waits for
    # its next period. Include AccuracySec and a full service-to-visible envelope on both paths.
    old_timer = timer.replace("OnUnitInactiveSec=30s", "OnUnitActiveSec=5min")
    old_next_start_at = next_start(old_timer, previous_start_at, previous_finish_at)
    old_next_visible_at = old_next_start_at + e["service_envelope_s"]
    assert old_next_visible_at > receipt_expires_at  # reproduces the review's lapse

    new_next_start_at = next_start(timer, previous_start_at, previous_finish_at)
    assert new_next_start_at == (
        previous_finish_at + e["timer_inactive_delay_s"] + e["timer_accuracy_s"]
    )
    new_next_visible_at = new_next_start_at + e["service_envelope_s"]
    assert new_next_visible_at < receipt_expires_at


def test_an_unsafe_envelope_is_refused_and_names_every_term(tmp_path: Path) -> None:
    home, council = _harness(tmp_path)
    unsafe_script = tmp_path / "unsafe-seat-refresh"
    unsafe_script.write_text(
        SCRIPT.read_text(encoding="utf-8").replace("WRITER_TIMEOUT_S=60", "WRITER_TIMEOUT_S=207"),
        encoding="utf-8",
    )
    proc = subprocess.run(
        ["bash", str(unsafe_script), "--envelope"],
        env={
            "HOME": str(home),
            "HAPAX_COUNCIL": str(council),
            "PATH": os.environ["PATH"],
            "HAPAX_GLMCP_SEAT_ROOT_OVERRIDE": "1",
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 7, proc.stderr
    for term in (
        "ACCOUNTED_SERVICE_CHAIN_S",
        "WHOLE_SERVICE_BOUND_S=600",
        "TimeoutStartSec",
        "CORE_COMMAND_ENVELOPE_S",
        "TIMEOUT_KILL_ENVELOPE_S",
        "FILTER_ENVELOPE_S",
        "PROCESS_LAUNCH_SLACK_S",
        "FILE_IO_SLACK_S",
        "SERVICE_SCHEDULER_SLACK_S",
        "SERVICE_SAFETY_MARGIN_S",
    ):
        assert term in proc.stderr, (term, proc.stderr)


def test_a_hostile_retry_override_is_refused_before_any_round_trip(tmp_path: Path) -> None:
    """The retry sleep is a test-only knob; an inherited value could stretch the envelope past the
    threshold and the unit's budget (review finding on #4624, round 9)."""
    for hostile in ("abc", "999", "-1"):
        home, council = _harness(tmp_path / hostile.strip("-"))
        env = {
            "HOME": str(home),
            "HAPAX_COUNCIL": str(council),
            "PATH": os.environ["PATH"],
            "HAPAX_GLMCP_SEAT_ROOT_OVERRIDE": "1",
            "HAPAX_GLMCP_SEAT_RETRY_SLEEP": hostile,
        }
        proc = subprocess.run(
            ["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60
        )
        assert proc.returncode == 7, (hostile, proc.stderr)
        assert "HAPAX_GLMCP_SEAT_RETRY_SLEEP" in proc.stderr and "unset it" in proc.stderr
        calls = (home / "calls").read_text() if (home / "calls").exists() else ""
        assert not any(line.startswith(("admission", "writer")) for line in calls.splitlines())
        assert "roundtrip attempt" not in proc.stdout, "no reviewer call may run"


def test_the_unit_unsets_the_retry_override() -> None:
    unit = UNIT.read_text(encoding="utf-8")
    unset = _unit_value(unit, "Service", "UnsetEnvironment") or ""
    assert "HAPAX_GLMCP_SEAT_RETRY_SLEEP" in unset.split()


def test_missing_jq_is_named_rather_than_read_as_a_stale_seat(tmp_path: Path) -> None:
    """A broken parser used to look exactly like a stale receipt and trigger a provider call every
    five minutes without saying why (review finding on #4624, round 9)."""
    home, council = _harness(
        tmp_path, receipt_status="observed", receipt_remaining=900, receipt_age=10
    )
    bin_dir = tmp_path / "bin-without-jq"
    bin_dir.mkdir()
    for tool in (
        "bash",
        "timeout",
        "date",
        "sed",
        "grep",
        "head",
        "cut",
        "tr",
        "mktemp",
        "rm",
        "wc",
        "printf",
        "hostname",
        "cat",
        "mkdir",
        "python3",
    ):
        real = shutil.which(tool)
        if real:
            (bin_dir / tool).symlink_to(real)
    env = {
        "HOME": str(home),
        "HAPAX_COUNCIL": str(council),
        "PATH": str(bin_dir),
        "TMPDIR": str(home),
        "HAPAX_GLMCP_SEAT_ROOT_OVERRIDE": "1",
        "HAPAX_GLMCP_SEAT_RETRY_SLEEP": "0",
        "HAPAX_TEST_PYTHON": sys.executable,
        "HAPAX_TEST_RECEIPTS_SCRIPT": str(RECEIPTS_SCRIPT),
        "HAPAX_TEST_RECEIPTS_RC": "0",
    }
    proc = subprocess.run(
        ["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=120
    )
    assert "jq is not on PATH" in proc.stderr, proc.stderr
    assert proc.returncode != 0


def test_a_dispatcher_receipt_with_time_to_spare_skips_the_round_trip(tmp_path: Path) -> None:
    # 890 s remain: inside the 30 s window after a mint in which a skip is provably safe.
    home, council = _harness(
        tmp_path, receipt_status="observed", receipt_remaining=900, receipt_age=10
    )
    result = _run(home, council)
    assert result.returncode == 0, result.stderr
    assert "no round-trip" in result.stdout
    assert not (home / "admission-calls").exists()
    assert _witnesses(home) == []


def test_a_dispatcher_receipt_about_to_lapse_round_trips(tmp_path: Path) -> None:
    # generated 600 s ago with 900 s to live: 300 s remain, under the derived threshold
    home, council = _harness(
        tmp_path, receipt_status="observed", receipt_remaining=900, receipt_age=600
    )
    result = _run(home, council)
    assert result.returncode == 0, result.stderr
    assert "roundtrip attempt 1: exit=0" in result.stdout
    assert (home / "admission-calls").exists()


def test_a_receipt_between_the_old_and_new_thresholds_is_refreshed(tmp_path: Path) -> None:
    """The next activation's initial --show can consume another SHOW_TIMEOUT_S. A receipt in that
    exact interval was skipped by the old threshold even though the following run could not finish
    the chain before it lapsed."""
    e = _envelope(tmp_path / "envelope")
    expected_chain = (
        e["timer_accuracy_s"]
        + e["show_timeout_s"]
        + e["review_attempts"] * e["review_attempt_timeout_s"]
        + (e["review_attempts"] - 1) * e["review_retry_sleep_s"]
        + e["admission_timeout_s"]
        + e["writer_timeout_s"]
        + e["receipts_timeout_s"]
        + e["show_timeout_s"]
    )
    new_threshold = e["timer_inactive_delay_s"] + expected_chain
    old_threshold = new_threshold - e["show_timeout_s"]
    remaining = (old_threshold + new_threshold) // 2
    assert old_threshold < remaining < new_threshold

    home, council = _harness(
        tmp_path / "run", receipt_status="observed", receipt_remaining=remaining, receipt_age=0
    )
    result = _run(home, council)
    assert result.returncode == 0, result.stderr
    assert "no round-trip" not in result.stdout
    assert "roundtrip attempt 1: exit=0" in result.stdout
    assert (home / "admission-calls").exists()


def test_a_receipt_with_exactly_threshold_plus_one_second_is_refreshed(
    tmp_path: Path,
) -> None:
    """One integer second is not enough clearance to skip: it can be consumed immediately by
    receipt rounding and the post-check shutdown before the completion-relative timer starts."""
    e = _envelope(tmp_path / "envelope")
    fixed_epoch = int(datetime.now(UTC).timestamp())
    fixed_now = datetime.fromtimestamp(fixed_epoch, UTC)
    home, council = _harness(
        tmp_path / "run",
        receipt_status="observed",
        receipt_remaining=e["seat_refresh_threshold_s"] + 1,
        receipt_age=0,
        now=fixed_now,
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    date = shutil.which("date")
    assert date is not None
    _stub(
        bin_dir / "date",
        f'if [ "$*" = "-u +%s" ]; then echo "{fixed_epoch}"; else exec "{date}" "$@"; fi\n',
    )
    env_path = f"{bin_dir}:{os.environ['PATH']}"
    result = _run(home, council, path=env_path)
    assert result.returncode == 0, result.stderr
    assert "no round-trip" not in result.stdout
    assert "roundtrip attempt 1: exit=0" in result.stdout
    assert (home / "admission-calls").exists()


def test_an_unobservable_dispatcher_receipt_round_trips_whatever_its_age(tmp_path: Path) -> None:
    """The dispatcher's receipt says the seat is NOT admitted: a fresh raw relay receipt beside it
    changes nothing (the validator rejected it, so the dispatcher rejects it)."""
    home, council = _harness(
        tmp_path,
        receipt_status="unobservable",
        receipt_remaining=900,
        receipt_age=10,
        relay_receipt_observed_ago=30,
    )
    result = _run(home, council)
    assert result.returncode == 0, result.stderr
    assert "no round-trip" not in result.stdout
    assert (home / "admission-calls").exists()


def test_a_raw_relay_receipt_alone_no_longer_counts_as_fresh(tmp_path: Path) -> None:
    home, council = _harness(tmp_path, relay_receipt_observed_ago=60)
    result = _run(home, council)
    assert result.returncode == 0, result.stderr
    assert "no round-trip" not in result.stdout
    assert (home / "admission-calls").exists()


def test_no_dispatcher_receipt_round_trips(tmp_path: Path) -> None:
    home, council = _harness(tmp_path)
    result = _run(home, council)
    assert result.returncode == 0, result.stderr
    assert (home / "admission-calls").exists()


def test_a_root_other_than_the_activation_worktree_is_refused(tmp_path: Path) -> None:
    """An inherited HAPAX_COUNCIL must not redirect receipt minting to a mutable tree."""
    home, council = _harness(tmp_path)
    result = _run(home, council, allow_root=False)
    assert result.returncode == 4
    assert "REFUSED" in result.stderr
    assert "activation worktree" in result.stderr
    assert "Next:" in result.stderr
    assert not (home / "admission-calls").exists()
    assert not (home / "reviewer-env").exists()


def test_a_stale_seat_round_trips_writes_a_witness_and_mints(tmp_path: Path) -> None:
    home, council = _harness(
        tmp_path, receipt_status="observed", receipt_remaining=900, receipt_age=850
    )
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
    assert "endpoint: https://api.z.ai/api/coding/paas/v4" in witness
    calls = (home / "admission-calls").read_text(encoding="utf-8")
    assert "observe-success --evidence-ref glmcp-reviewer-roundtrip-ok-" in calls
    assert "--supported-tool hapax-glmcp-reviewer" in calls
    assert "--endpoint https://api.z.ai/api/coding/paas/v4" in calls
    assert "--model glm-5.2" in calls


def test_the_probe_pins_payg_off_the_endpoint_and_the_credential(tmp_path: Path) -> None:
    """An exhausted Coding Plan answered by API credit, another endpoint, or another credential
    must not mint a Coding Plan receipt — whatever the inherited environment says."""
    home, council = _harness(tmp_path)
    result = _run(home, council)
    assert result.returncode == 0, result.stderr
    seen = set((home / "reviewer-env").read_text(encoding="utf-8").split())
    assert "PAYG=0" in seen
    assert "BASE=https://api.z.ai/api/coding/paas/v4" in seen
    assert "SECRET=glmcp/api-key" in seen  # pragma: allowlist secret
    assert "OVERRIDE=unset" in seen
    assert not any(line.startswith("BASE=https://evil") for line in seen)
    assert not any("someone-elses" in line for line in seen)


def test_three_failed_round_trips_mint_nothing_and_name_the_next_action(tmp_path: Path) -> None:
    """Empty stderr on a failure used to end the retry loop under pipefail after one attempt."""
    home, council = _harness(tmp_path, reviewer=REVIEWER_ALWAYS_FAILS_SILENTLY)
    result = _run(home, council)
    assert result.returncode == 2
    assert "roundtrip attempt 3: exit=1" in result.stdout
    assert result.stdout.count("roundtrip attempt") == 3
    assert "glm seat NOT refreshed" in result.stderr
    assert "do not mint" in result.stderr
    assert _witnesses(home) == []
    assert not (home / "admission-calls").exists()


def test_a_failed_round_trip_that_emits_output_mints_nothing_and_names_its_exit(
    tmp_path: Path,
) -> None:
    """PIPESTATUS must be captured in the shell that ran the pipeline, before counting output."""
    script = SCRIPT.read_text(encoding="utf-8")
    assert 'bytes="$(printf' not in script
    assert "rc=${PIPESTATUS[1]}" in script
    home, council = _harness(tmp_path, reviewer=REVIEWER_FAILS_WITH_OUTPUT)
    result = _run(home, council)
    assert result.returncode == 2
    assert "roundtrip attempt 3: exit=23 output_bytes=7" in result.stdout
    assert "reviewer round-trip failed (exit 23, 7 bytes)" in result.stderr
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
    """Exit 3 from the telemetry writer means the live ledger was written but the capability
    receipt refresh degraded — and since round 6 that receipt is what the dispatcher (and this
    guard) read, so the seat is NOT visible: a failure that prints the writer's diagnostics and
    names the next action (review finding on #4624, round 6)."""
    home, council = _harness(tmp_path, writer_rc=3)
    result = _run(home, council)
    assert result.returncode == 6
    assert "capability receipts DEGRADED for one provider" in result.stdout
    assert "glm seat NOT visible" in result.stderr
    assert "hapax-platform-capability-receipts --platform glmcp" in result.stderr
    assert (home / "admission-calls").exists()


def test_admission_failure_after_a_good_round_trip_is_loud_and_names_the_next_action(
    tmp_path: Path,
) -> None:
    """Under errexit a failed admission write used to end the script with no line at all."""
    home, council = _harness(tmp_path, admission_rc=1)
    result = _run(home, council)
    assert result.returncode == 5
    assert "NOT admitted" in result.stderr
    assert "observe-success --evidence-ref glmcp-reviewer-roundtrip-ok-" in result.stderr
    assert "Next:" in result.stderr
    assert len(_witnesses(home)) == 1


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


def test_unit_pair_executes_from_the_activation_worktree_and_strips_inherited_overrides(
    tmp_path: Path,
) -> None:
    """A unit that runs a mutable development checkout is a finding (review on #4624); the
    estate's convention is the governed source-activation worktree. The pins live in the script's
    defaults because systemd does not expand specifiers inside Environment= (measured
    2026-09-02: `Environment=X=%h/y` arrives literally), and the unit strips the inherited
    user-manager values that could override them."""
    service = SERVICE.read_text(encoding="utf-8")
    exec_start = _unit_value(service, "Service", "ExecStart") or ""
    assert exec_start == f"{ACTIVATION_ROOT}/scripts/hapax-glmcp-seat-refresh"
    assert "projects" not in exec_start
    assert "tmp" not in exec_start
    assert "source-activation/worktree" in SCRIPT.read_text(encoding="utf-8")
    for line in service.splitlines():
        if line.startswith("Environment="):
            assert "%" not in line, f"specifiers are not expanded in Environment=: {line}"
    unset = _unit_value(service, "Service", "UnsetEnvironment") or ""
    for name in (
        "HAPAX_COUNCIL",
        "HAPAX_GLMCP_REVIEW_BASE_URL",
        "HAPAX_GLMCP_REVIEW_SECRET_ENTRY",  # pragma: allowlist secret
        "HAPAX_GLMCP_REVIEW_ALLOW_SECRET_ENTRY_OVERRIDE",  # pragma: allowlist secret
        "HAPAX_GLMCP_SEAT_ROOT_OVERRIDE",
        # the receipt and ledger writers honour these; the seat must read where they wrote
        "HAPAX_PLATFORM_CAPABILITY_RECEIPT_DIR",
        "HAPAX_QUOTA_SPEND_LEDGER_LIVE",
        # the admission writer and the telemetry writer both honour this one; an inherited value
        # would mint the admission somewhere the ledger never reads (review finding, round 8)
        "HAPAX_RELAY_RECEIPT_DIR",
    ):
        assert name in unset.split(), name
    assert _unit_value(service, "Service", "Type") == "oneshot"
    assert _unit_value(service, "Service", "MemoryMax") is not None
    service_budget = int(_unit_value(service, "Service", "TimeoutStartSec") or 0)
    envelope = _envelope(tmp_path)
    assert service_budget == envelope["whole_service_bound_s"] == 600
    assert (
        int(_unit_value(service, "Service", "TimeoutStopSec") or 0)
        == envelope["post_check_shutdown_s"]
    )
    assert _unit_value(service, "Service", "KillMode") == "control-group"
    assert _unit_value(service, "Service", "SendSIGKILL") == "yes"
    # ...and the budget is only a budget if every step in it is bounded.
    script = SCRIPT.read_text(encoding="utf-8")
    assert 'timeout --signal=TERM --kill-after="${TIMEOUT_KILL_AFTER_S}s" "${timeout_s}s"' in script
    assert 'bounded_timeout "$REVIEW_ATTEMPT_TIMEOUT_S" "$H/scripts/hapax-glmcp-reviewer"' in script
    assert (
        'bounded_timeout "$ADMISSION_TIMEOUT_S" "$H/scripts/hapax-glmcp-quota-admission"' in script
    )
    assert (
        'bounded_timeout "$WRITER_TIMEOUT_S" "$H/scripts/hapax-quota-telemetry-writer" --skip-receipts'
        in script
    )
    assert (
        'bounded_timeout "$RECEIPTS_TIMEOUT_S" "$H/scripts/hapax-platform-capability-receipts" --platform glmcp'
        in script
    )
    assert (
        'bounded_timeout "$SHOW_TIMEOUT_S" "$H/scripts/hapax-platform-capability-receipts" --show'
        in script
    )
    assert 'bounded_timeout "$FILTER_TIMEOUT_S" python3 -c' in script
    assert "bounded no-lapse envelope" in (_unit_value(service, "Unit", "Description") or "")
    timer = TIMER.read_text(encoding="utf-8")
    assert _unit_value(timer, "Install", "WantedBy") == "timers.target"
    assert "After each completion" in (_unit_value(timer, "Unit", "Description") or "")


# ---------------------------------------------------------------------------
# Round 8 (review findings on #4624): the writer's default run refreshed every capability receipt
# BEFORE rebuilding the ledger — so the glmcp receipt it minted carried the previous seat's
# remaining lifetime and the freshness shortcut never fired (measured 2026-09-03: 30 round-trips
# in 36 runs, zero "no round-trip") — and spent a Codex exec-auth sentinel on every call. The
# writer now runs ledger-only, the glmcp receipt is derived from the fresh ledger afterwards, and
# the seat counts as refreshed only when the dispatcher's loader accepts that receipt.
# ---------------------------------------------------------------------------


def _calls(home: Path) -> list[str]:
    return (home / "calls").read_text(encoding="utf-8").splitlines()


def test_writer_runs_ledger_only_and_the_glm_receipt_is_derived_afterwards(
    tmp_path: Path,
) -> None:
    home, council = _harness(tmp_path)
    result = _run(home, council)
    assert result.returncode == 0, result.stderr
    calls = _calls(home)
    writer = [c for c in calls if c.startswith("writer ")]
    assert writer == ["writer --skip-receipts"], calls
    refresh = [c for c in calls if c.startswith("receipts ") and "--show" not in c]
    assert refresh == ["receipts --platform glmcp"], calls
    assert not any("--all" in c or "--codex-exec-auth-probe" in c for c in calls), calls
    assert calls.index(writer[0]) < calls.index(refresh[0])
    assert "glm seat visible to the dispatcher" in result.stdout


def test_a_seat_the_dispatcher_cannot_see_after_the_refresh_is_a_failure(tmp_path: Path) -> None:
    """The stubbed refresh leaves the old receipt (50 s left): a writer exit of zero is not a seat."""
    home, council = _harness(
        tmp_path,
        receipt_status="observed",
        receipt_remaining=900,
        receipt_age=850,
        refreshed_remaining=None,
    )
    result = _run(home, council)
    assert result.returncode == 6
    assert "glm seat NOT visible" in result.stderr
    assert "--show --platform glmcp" in result.stderr
    assert "Next:" in result.stderr
    assert (home / "admission-calls").exists()


def test_a_new_receipt_without_a_full_next_renewal_window_is_refused(tmp_path: Path) -> None:
    """A refresh is not success when its receipt cannot survive the delay plus the next run."""
    e = _envelope(tmp_path / "envelope")
    home, council = _harness(
        tmp_path / "run",
        refreshed_remaining=e["seat_refresh_threshold_s"],
    )
    result = _run(home, council)
    assert result.returncode == 6
    assert f"more than {e['seat_visible_min_s']} s left" in result.stderr
    assert "glm seat visible to the dispatcher" not in result.stdout


def test_a_failed_glm_receipt_refresh_after_minting_is_loud(tmp_path: Path) -> None:
    home, council = _harness(tmp_path)
    result = _run(home, council, receipts_rc=1)
    assert result.returncode == 6
    assert "could not be refreshed from the new ledger" in result.stderr
    assert "Next:" in result.stderr


def test_a_receipt_the_dispatchers_loader_rejects_does_not_skip_the_round_trip(
    tmp_path: Path,
) -> None:
    """Three plausible fields in a JSON file are not a receipt; the guard reads through the loader."""
    home, council = _harness(tmp_path, malformed_receipt=True)
    result = _run(home, council)
    assert result.returncode == 0, result.stderr
    assert "no round-trip" not in result.stdout
    assert (home / "admission-calls").exists()


def test_a_stale_receipt_with_a_fresh_looking_quota_surface_does_not_skip(tmp_path: Path) -> None:
    """The receipt itself expired an hour ago; its quota surface still says 900 s. A guard that
    picked the quota fields out of the JSON would skip; the dispatcher's loader drops the receipt,
    so the seat round-trips."""
    home, council = _harness(
        tmp_path,
        receipt_status="observed",
        receipt_remaining=900,
        receipt_age=5,
        receipt_stale=True,
    )
    result = _run(home, council)
    assert result.returncode == 0, result.stderr
    assert "no round-trip" not in result.stdout
    assert (home / "admission-calls").exists()


def test_show_reports_the_accepted_receipt_and_rejects_a_malformed_one(tmp_path: Path) -> None:
    receipts_dir = tmp_path / "receipts"
    receipts_dir.mkdir()
    now = datetime.now(UTC)
    (receipts_dir / "glmcp.json").write_text(
        _glmcp_receipt_json(status="observed", remaining=900, age=5, now=now), encoding="utf-8"
    )
    shown = subprocess.run(
        [
            sys.executable,
            str(RECEIPTS_SCRIPT),
            "--show",
            "--platform",
            "glmcp",
            "--json",
            "--receipt-dir",
            str(receipts_dir),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert shown.returncode == 0, shown.stderr
    payload = json.loads(shown.stdout)
    (row,) = payload["receipts"]
    assert row["accepted"] is True
    assert row["quota"]["status"] == "observed"
    assert row["quota"]["stale_after"] == "900s"

    (receipts_dir / "glmcp.json").write_text('{"platform": "glmcp", "quota": {}}', encoding="utf-8")
    rejected = subprocess.run(
        [
            sys.executable,
            str(RECEIPTS_SCRIPT),
            "--show",
            "--platform",
            "glmcp",
            "--json",
            "--receipt-dir",
            str(receipts_dir),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert rejected.returncode == 1
    (row,) = json.loads(rejected.stdout)["receipts"]
    assert row["accepted"] is False
    assert row["reason"].startswith("receipt_invalid")
