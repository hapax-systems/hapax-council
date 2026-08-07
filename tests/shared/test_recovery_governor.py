"""Unit tests for shared.recovery_governor — the control-theory stability gate.

The governor forces the closed recovery loop contractive (loop-gain G<1) by
composing three sub-unity limiters: per-target AIMD backoff × a global
token-bucket × the #3850 PSI throttle, plus an in-flight concurrency cap and a
fail-open-to-permit floor that can never become a deny-sink (NEVER-FREEZE).

These tests pin the pure, deterministic core first (no IO), then the stateful
permit/record path, the PSI integration, escalation, fail-open observability,
shadow/enforce gating on coordinator CPUWeight, and the batch permit API.
"""

from __future__ import annotations

import signal
import types
from pathlib import Path

import pytest

from shared import recovery_governor as rg

# ── Pure: AIMD backoff ───────────────────────────────────────────────────────


def test_aimd_nominal_delays_double_per_attempt() -> None:
    params = rg.RecoveryParams()
    delays = [rg.aimd_backoff_delay(attempt, params) for attempt in range(5)]
    assert delays == [30.0, 60.0, 120.0, 240.0, 480.0]


def test_aimd_delay_is_capped() -> None:
    params = rg.RecoveryParams()
    # 30 * 2**7 = 3840 > CAP 1800 → clamped.
    assert rg.aimd_backoff_delay(7, params) == params.cap_s == 1800.0


def test_aimd_base_doubles_under_paced() -> None:
    # PSI 'paced' doubles the AIMD BASE (the proportional band).
    base = rg.RecoveryParams()
    paced = rg.params_for_state("paced", base)
    assert paced.base_s == base.base_s * 2.0
    assert rg.aimd_backoff_delay(0, paced) == 60.0


# ── Pure: token bucket ───────────────────────────────────────────────────────


def test_bucket_grants_up_to_burst_then_denies_at_one_instant() -> None:
    params = rg.RecoveryParams()
    state = rg.BucketState(tokens=float(params.bucket_burst), updated=1000.0)
    granted = 0
    for _ in range(50):  # fire 50 permits in one instant
        ok, state = rg.bucket_take(
            state, now=1000.0, rate=params.bucket_rate, burst=params.bucket_burst
        )
        granted += int(ok)
    assert granted == params.bucket_burst == 3


def test_bucket_refills_one_per_interval() -> None:
    params = rg.RecoveryParams()
    state = rg.BucketState(tokens=0.0, updated=0.0)
    # 10s later, exactly one token has refilled at rate 1/10s.
    ok, state = rg.bucket_take(state, now=10.0, rate=params.bucket_rate, burst=params.bucket_burst)
    assert ok
    ok2, _ = rg.bucket_take(state, now=10.0, rate=params.bucket_rate, burst=params.bucket_burst)
    assert not ok2  # the refilled token was just spent


def test_bucket_rate_default_is_one_per_ten_seconds() -> None:
    assert rg.RecoveryParams().bucket_rate == 0.1


# ── Pure: RecoveryParams tabulated constants ─────────────────────────────────


def test_recovery_params_defaults_match_design_table() -> None:
    p = rg.RecoveryParams()
    assert p.base_s == 30.0
    assert p.multiplier == 2.0
    assert p.cap_s == 1800.0
    assert p.max_attempts == 5
    assert p.bucket_burst == 3
    assert p.critical_reserve == 1
    assert p.max_concurrent_relaunch == 3
    # MF1: PSI-unreadable degraded bucket is TIGHTER than open, not equal to it.
    assert p.degraded_rate < p.bucket_rate
    assert p.degraded_burst < p.bucket_burst


def test_params_for_state_closed_suspends_noncritical() -> None:
    p = rg.params_for_state("closed", rg.RecoveryParams())
    assert p.suspend_noncritical is True


def test_params_for_state_paced_halves_bucket_rate() -> None:
    base = rg.RecoveryParams()
    paced = rg.params_for_state("paced", base)
    assert paced.bucket_rate == base.bucket_rate * 0.5


# ── Stateful governor: permit / record / AIMD reset ──────────────────────────


def _gov(tmp: Path, *, state: str = "open", readable: bool = True, **kw):
    """A governor wired to a tmp state dir with injected, deterministic deps.

    Any dep can be overridden via ``kw`` (e.g. ``notify_fn=`` to capture ntfy).
    """
    defaults = dict(
        state_dir=tmp,
        admission_fn=lambda: types.SimpleNamespace(state=state),
        psi_readable_fn=lambda: readable,
        jitter_fn=lambda delay: delay,  # no jitter → next_eligible = now + nominal
        critical_validator_fn=lambda target: True,
        notify_fn=lambda *a, **k: None,
        mint_fn=lambda target, detail: tmp / f"escalation-{target}.md",
        shielded_fn=lambda: True,
        mode="enforce",
    )
    defaults.update(kw)
    return rg.RecoveryGovernor(**defaults)


def test_permit_grants_under_open_until_burst_exhausted(tmp_path: Path) -> None:
    gov = _gov(tmp_path)
    grants = [gov.permit(f"lane:{i}", now=1000.0).permitted for i in range(50)]
    assert sum(grants) == rg.RecoveryParams().bucket_burst == 3  # fleet-wide cap


def test_record_fail_then_backoff_denies_same_target(tmp_path: Path) -> None:
    gov = _gov(tmp_path)
    assert gov.permit("lane:beta", now=0.0).permitted
    gov.record_outcome("lane:beta", success=False, now=0.0)
    # within the first nominal delay (30s) the same target is in backoff
    denied = gov.permit("lane:beta", now=10.0)
    assert not denied.permitted
    assert "backoff" in denied.reason


def test_aimd_next_eligible_doubles_per_recorded_fail(tmp_path: Path) -> None:
    gov = _gov(tmp_path)
    deltas = []
    t = 0.0
    for _ in range(5):
        gov.record_outcome("lane:x", success=False, now=t)
        entry = gov.backoff_entry("lane:x")
        deltas.append(round(entry.next_eligible - t))
        t = entry.next_eligible  # advance past the backoff so attempt climbs
    assert deltas == [30, 60, 120, 240, 480]


def test_record_success_resets_attempt_to_zero(tmp_path: Path) -> None:
    gov = _gov(tmp_path)
    gov.record_outcome("lane:y", success=False, now=0.0)
    gov.record_outcome("lane:y", success=False, now=100.0)
    assert gov.backoff_entry("lane:y").attempt == 2
    gov.record_outcome("lane:y", success=True, now=200.0)  # reset-on-success
    assert gov.backoff_entry("lane:y").attempt == 0


# ── MF2: in-flight concurrency cap (rate ≠ concurrency) ──────────────────────


def test_concurrency_cap_denies_beyond_max_in_flight(tmp_path: Path) -> None:
    # Burst is 3 and the concurrency cap is 3; grant 3, then a refilled token
    # must still be denied because 3 relaunches are already in flight.
    gov = _gov(tmp_path)
    for i in range(3):
        assert gov.permit(f"lane:{i}", now=0.0).permitted
    # 100s later the bucket has refilled, but nothing has reported done.
    denied = gov.permit("lane:new", now=100.0)
    assert not denied.permitted
    assert "concurrency" in denied.reason


def test_recording_outcome_frees_an_in_flight_slot(tmp_path: Path) -> None:
    gov = _gov(tmp_path)
    for i in range(3):
        gov.permit(f"lane:{i}", now=0.0)
    gov.record_outcome("lane:0", success=True, now=50.0)  # frees a slot
    assert gov.permit("lane:new", now=100.0).permitted


# ── PSI throttle: paced halves rate, closed suspends non-critical ────────────


def test_paced_halves_the_bucket_rate(tmp_path: Path) -> None:
    # open refills 1 token / 10s; paced refills 1 / 20s. At t=10s after a drain,
    # open would grant, paced must not.
    open_gov = _gov(tmp_path / "o", state="open")
    paced_gov = _gov(tmp_path / "p", state="paced")
    for g in (open_gov, paced_gov):
        for i in range(3):
            g.permit(f"lane:{i}", now=0.0)  # drain burst
        # free the concurrency slots so the bucket is the only gate
        for i in range(3):
            g.record_outcome(f"lane:{i}", success=True, now=0.0)
    assert open_gov.permit("lane:z", now=10.0).permitted
    assert not paced_gov.permit("lane:z", now=10.0).permitted


def test_closed_suspends_noncritical_but_grants_one_critical(tmp_path: Path) -> None:
    gov = _gov(tmp_path, state="closed")
    assert not gov.permit("lane:normal", now=0.0).permitted  # suspended
    crit = [gov.permit("coordinator", critical=True, now=0.0).permitted for _ in range(5)]
    assert sum(crit) == rg.RecoveryParams().critical_reserve == 1  # exactly the reserve


def test_escalated_target_is_severed_from_the_loop(tmp_path: Path) -> None:
    # After MAX_ATTEMPTS fails the target stops receiving recovery (proof step 3).
    gov = _gov(tmp_path)
    t = 0.0
    for _ in range(rg.RecoveryParams().max_attempts):
        gov.record_outcome("lane:broken", success=False, now=t)
        t = gov.backoff_entry("lane:broken").next_eligible
    # far in the future, past any backoff, still denied — it's escalated out.
    denied = gov.permit("lane:broken", now=t + 10_000.0)
    assert not denied.permitted
    assert "escalat" in denied.reason


# ── MF1: PSI-unreadable TIGHTENS the bucket (degraded ≠ open) ─────────────────


def test_psi_unreadable_tightens_bucket_to_degraded_burst(tmp_path: Path) -> None:
    # Fail-open must NOT keep the open-mode rate on the box that starved its
    # coordinator. PSI-unreadable → degraded bucket (burst 1), not burst 3.
    gov = _gov(tmp_path, readable=False)
    grants = [gov.permit(f"lane:{i}", now=0.0).permitted for i in range(5)]
    assert sum(grants) == rg.RecoveryParams().degraded_burst == 1


def test_psi_unreadable_still_permits_eventually_never_a_sink(tmp_path: Path) -> None:
    # NEVER-FREEZE: degraded is tighter, not closed — recovery still flows.
    gov = _gov(tmp_path, readable=False)
    assert gov.permit("lane:a", now=0.0).permitted  # 1st within degraded burst
    assert gov.permit("lane:b", now=60.0).permitted  # refills 1/30s → granted


# ── MF6: a degraded/broken governor is OBSERVABLE, not silent ────────────────


def test_psi_unreadable_emits_failopen_signal(tmp_path: Path) -> None:
    events: list = []
    gov = _gov(tmp_path, readable=False, notify_fn=lambda *a, **k: events.append(a))
    gov.permit("lane:x", now=0.0)
    assert gov.failopen_count() >= 1  # counter bumped
    assert events  # rate-limited ntfy fired — never a silent revert


def test_governor_internal_error_fails_open_to_permit_and_is_observable(tmp_path: Path) -> None:
    def boom() -> bool:
        raise RuntimeError("simulated broken governor")

    events: list = []
    gov = _gov(tmp_path, notify_fn=lambda *a, **k: events.append(a), psi_readable_fn=boom)
    grant = gov.permit("lane:x", now=0.0)
    assert grant.permitted  # never a deny-sink
    assert gov.failopen_count() >= 1 and events


# ── MF5: interim critical predicate uses only signals that exist today ────────


def test_critical_predicate_coordinator_dead_is_critical() -> None:
    assert rg._interim_critical_predicate("coordinator", coordinator_alive_fn=lambda: False)


def test_critical_predicate_coordinator_alive_is_not_critical() -> None:
    assert not rg._interim_critical_predicate("coordinator", coordinator_alive_fn=lambda: True)


def test_critical_predicate_dead_p0_lane_is_critical() -> None:
    assert rg._interim_critical_predicate(
        "lane:beta", pid_alive_fn=lambda role: False, priority_fn=lambda role: "p0"
    )


def test_critical_predicate_live_p0_lane_is_not_critical() -> None:
    # A heartbeating P0 lane is doing its job — recovering it would be the storm.
    assert not rg._interim_critical_predicate(
        "lane:beta", pid_alive_fn=lambda role: True, priority_fn=lambda role: "p0"
    )


def test_critical_predicate_dead_low_priority_lane_is_not_critical() -> None:
    assert not rg._interim_critical_predicate(
        "lane:beta", pid_alive_fn=lambda role: False, priority_fn=lambda role: "p3"
    )


# ── Escalation mints a real cc-task via the sanctioned path ──────────────────


def test_escalation_mints_a_valid_cc_task(tmp_path: Path) -> None:
    import yaml

    path = rg._mint_escalation_task("lane:beta", "reached MAX_ATTEMPTS=5", tasks_dir=tmp_path)
    assert path.exists()
    text = path.read_text()
    meta = yaml.safe_load(text.split("---", 2)[1])
    assert meta["type"] == "cc-task"
    assert meta["status"] == "offered"
    assert "lane:beta" in text


def test_escalation_is_idempotent_one_file_per_target(tmp_path: Path) -> None:
    p1 = rg._mint_escalation_task("lane:beta", "x", tasks_dir=tmp_path)
    p2 = rg._mint_escalation_task("lane:beta", "y", tasks_dir=tmp_path)
    assert p1 == p2  # re-mint overwrites, never spams the queue
    assert len(list(tmp_path.glob("recovery-escalation-*.md"))) == 1


# ── Bounded-kill contract: safe_kill rejects process-group kills ──────────────


def test_safe_kill_rejects_nonpositive_pid() -> None:
    # kill(-pgid) is the exit-144 cascade; reject it at the type boundary.
    with pytest.raises((ValueError, AssertionError)):
        rg.safe_kill(-1234, signal.SIGTERM)
    with pytest.raises((ValueError, AssertionError)):
        rg.safe_kill(0, signal.SIGTERM)


def test_safe_kill_calls_os_kill_with_exact_pid() -> None:
    calls: list = []
    rg.safe_kill(4321, signal.SIGTERM, kill_fn=lambda p, s: calls.append((p, s)))
    assert calls == [(4321, signal.SIGTERM)]


# ── MF4: enforcement is gated on the coordinator being shielded (CPUWeight) ───


def test_coordinator_shielded_true_when_cpuweight_raised() -> None:
    assert rg.coordinator_shielded(show_fn=lambda: "CPUWeight=10000")


def test_coordinator_shielded_false_when_unset_or_default() -> None:
    assert not rg.coordinator_shielded(show_fn=lambda: "CPUWeight=[not set]")
    assert not rg.coordinator_shielded(show_fn=lambda: "CPUWeight=100")


def test_enforce_downgrades_to_shadow_until_coordinator_shielded(tmp_path: Path) -> None:
    shielded = _gov(tmp_path / "s", shielded_fn=lambda: True, mode="enforce")
    unshielded = _gov(tmp_path / "u", shielded_fn=lambda: False, mode="enforce")
    assert shielded.effective_mode() == "enforce"
    assert unshielded.effective_mode() == "shadow"  # not stalled — non-binding


def test_default_mode_is_shadow(tmp_path: Path) -> None:
    assert _gov(tmp_path, mode="shadow").effective_mode() == "shadow"


# ── MF3: batch permit API (one PSI read / state load per tick) ───────────────


def test_permit_batch_admits_subset_in_one_call(tmp_path: Path) -> None:
    gov = _gov(tmp_path)
    grants = gov.permit_batch([f"lane:{i}" for i in range(10)], now=0.0)
    assert len(grants) == 10
    assert sum(g.permitted for g in grants) == rg.RecoveryParams().bucket_burst == 3


# ── CLI: exit codes 0 (permit) / 75 (backoff) / 2 (closed) ───────────────────


def test_cli_permit_grants_exit_zero(tmp_path: Path) -> None:
    gov = _gov(tmp_path, mode="enforce", now_fn=lambda: 0.0)
    assert rg.main(["--permit", "lane:a"], governor=gov) == rg.PERMIT


def test_cli_permit_in_backoff_exits_seventyfive(tmp_path: Path) -> None:
    gov = _gov(tmp_path, mode="enforce", now_fn=lambda: 0.0)
    rg.main(["--permit", "lane:a"], governor=gov)
    rg.main(["--record", "lane:a", "fail"], governor=gov)
    assert rg.main(["--permit", "lane:a"], governor=gov) == rg.BACKOFF


def test_cli_permit_closed_exits_two(tmp_path: Path) -> None:
    gov = _gov(tmp_path, state="closed", mode="enforce", now_fn=lambda: 0.0)
    assert rg.main(["--permit", "lane:a"], governor=gov) == rg.CLOSED


def test_cli_shadow_mode_always_permits_nonbinding(tmp_path: Path) -> None:
    # Shadow → the site acts as today (exit 0) while the would-be grant is ledgered.
    gov = _gov(tmp_path, state="closed", mode="shadow", now_fn=lambda: 0.0)
    assert rg.main(["--permit", "lane:a"], governor=gov) == rg.PERMIT


def test_cli_record_exits_zero(tmp_path: Path) -> None:
    gov = _gov(tmp_path, mode="enforce", now_fn=lambda: 0.0)
    assert rg.main(["--record", "lane:a", "ok"], governor=gov) == 0


def test_cli_state_prints_word_and_exit_code(tmp_path: Path, capsys) -> None:
    gov = _gov(tmp_path, state="paced", mode="enforce", now_fn=lambda: 0.0)
    code = rg.main(["--state"], governor=gov)
    assert capsys.readouterr().out.strip() == "paced"
    assert code == 1  # open=0, paced=1, closed=2


def test_cli_fail_open_when_psi_and_shm_both_unavailable(tmp_path, monkeypatch) -> None:
    # The headline NEVER-FREEZE acceptance criterion: PSI unreadable AND the
    # state dir unwritable → still PERMIT (exit 0), never a deny-sink.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))  # redirect fail-open fallback
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file, not a dir")
    dead_dir = blocker / "sub"  # mkdir under a file always fails
    gov = _gov(dead_dir, readable=False, mode="enforce", now_fn=lambda: 0.0)
    assert rg.main(["--permit", "lane:a"], governor=gov) == rg.PERMIT


def test_cli_governor_off_permits(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(rg.OFF_ENV, "1")
    gov = _gov(tmp_path, state="closed", mode="enforce", now_fn=lambda: 0.0)
    assert rg.main(["--permit", "lane:a"], governor=gov) == rg.PERMIT  # legacy revert


# ── CLI: bounded-kill verb + governor-health stats ───────────────────────────


def test_cli_kill_invokes_safe_kill(tmp_path, monkeypatch) -> None:
    calls: list = []
    monkeypatch.setattr(rg.os, "kill", lambda p, s: calls.append((p, s)))
    gov = _gov(tmp_path)
    assert rg.main(["--kill", "12345"], governor=gov) == 0
    assert calls == [(12345, signal.SIGTERM)]


def test_cli_kill_refuses_process_group(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(rg.os, "kill", lambda p, s: None)
    gov = _gov(tmp_path)
    with pytest.raises(ValueError):
        rg.main(["--kill", "-1"], governor=gov)


def test_cli_stats_reports_failopen_count(tmp_path, capsys) -> None:
    import json as _json

    gov = _gov(tmp_path, readable=False, now_fn=lambda: 0.0)  # forces a fail-open event
    gov.permit("lane:x", now=0.0)
    assert rg.main(["--stats"], governor=gov) == 0
    stats = _json.loads(capsys.readouterr().out)
    assert stats["failopen_count"] >= 1
    assert stats["effective_mode"] in ("shadow", "enforce")
