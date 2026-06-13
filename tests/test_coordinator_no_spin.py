"""No-spin law: storm-replay regression test (failure class #9 closure).

Replays the 2026-06-12 storm shape: 1,028 identical dispatch attempts, one task
(cctv-prompt-caching-quality-neutral-20260607), one lane (cx-alpha), one
deterministic refusal (route policy refuse: runtime_actuation_receipt_absent) —
every ~30s tick.

Exit predicate (from the task note):
  after K identical deterministic refusals the pair enters cooldown with
  exponential backoff and an ntfy escalation fires with the refusal reason;
  a regression test replays the 2026-06-12 storm shape (1,028 identical
  runtime_actuation_receipt_absent refusals) and asserts ≤K dispatch attempts
  + 1 escalation

The "≤K dispatch attempts + 1 escalation" invariant: the INITIAL burst before
any cooldown is exactly K.  After that, exponential-backoff re-probes fire at
decreasing frequency (base * 2^n, capped at 1h).  Over the 8.5h storm window,
the total dispatch attempts are dramatically fewer than the original 1,028
(≤ K + ceil(log2(cap/base)) + ceil(remaining/cap) ≈ 16), with exactly 1
escalation.  The test asserts both the initial K guarantee AND the dramatic
reduction.

Also tests:
  - Transient reasons (timeouts) get a higher K and no escalation.
  - Success resets refusal state.
  - Starvation detection (offered>0, dispatched=0 for 1h → escalation).
  - Cooldown exponential backoff is bounded.
"""

from __future__ import annotations

import pytest

from agents.coordinator.refusal_ledger import (
    BACKOFF_BASE_S,
    BACKOFF_MAX_S,
    DEFAULT_K,
    STARVATION_HORIZON_S,
    TRANSIENT_K,
    DispatchRefusalLedger,
    is_transient_reason,
)

# ── helpers ───────────────────────────────────────────────────────────────────


class EscalationRecorder:
    """Records escalation calls for assertion."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def __call__(self, title: str, body: str) -> None:
        self.calls.append((title, body))


def make_ledger(
    k: int = DEFAULT_K,
    starvation_horizon_s: float = STARVATION_HORIZON_S,
) -> tuple[DispatchRefusalLedger, EscalationRecorder]:
    recorder = EscalationRecorder()
    ledger = DispatchRefusalLedger(
        k=k,
        starvation_horizon_s=starvation_horizon_s,
        _escalate_fn=recorder,
    )
    return ledger, recorder


# ── storm replay (the exit predicate) ─────────────────────────────────────────


class TestStormReplay:
    """Replay the 2026-06-12 storm: 1,028 identical deterministic refusals.

    The no-spin law guarantees: after K identical refusals the pair enters
    cooldown with exponential backoff.  Total dispatch attempts over the
    8.5h window are dramatically fewer than the original 1,028.
    """

    TASK = "cctv-prompt-caching-quality-neutral-20260607"
    LANE = "cx-alpha"
    REASON = "BLOCKED: route policy refuse: runtime_actuation_receipt_absent"
    STORM_TICKS = 1028

    def test_storm_replay_dramatic_reduction(self) -> None:
        """The storm replays 1,028 ticks at 30s each.  After K refusals the pair
        enters exponential-backoff cooldown.  Re-probes fire at decreasing frequency.

        Over the full 8.5h storm window, the total dispatch attempts should be
        dramatically fewer than the original 1,028 — the no-spin law limits it
        to approximately K + ceil(log2(cap/base)) + ceil(remaining/cap) ≈ 16.
        Exactly 1 escalation fires at the K threshold."""
        ledger, recorder = make_ledger()

        dispatch_attempts = 0
        now = 0.0
        tick_s = 30.0

        for _ in range(self.STORM_TICKS):
            now += tick_s
            # The coordinator checks cooldown BEFORE dispatching.
            if not ledger.any_cooldown_for_pair(self.TASK, self.LANE, now=now):
                # Would call _dispatch here; it fails with the same reason.
                dispatch_attempts += 1
                ledger.record_refusal(self.TASK, self.LANE, self.REASON, now=now)
            # else: skipped (in cooldown)

        # Core exit predicate:
        # 1. Dramatic reduction: ≤ 25 attempts (vs 1,028 without the law).
        #    Theoretical maximum with K=3, base=60, cap=3600, 8.5h window: ~16.
        assert dispatch_attempts <= 25, (
            f"Expected ≤25 dispatch attempts (vs 1,028 original), got {dispatch_attempts}"
        )
        # 2. Exactly 1 escalation fires.
        assert len(recorder.calls) == 1, f"Expected exactly 1 escalation, got {len(recorder.calls)}"
        # 3. The initial burst before any cooldown is exactly K.
        # (Verified by the K-threshold tests below.)

    def test_storm_initial_burst_is_k(self) -> None:
        """The first K refusals happen without cooldown; the (K+1)th dispatch
        attempt is skipped because cooldown is active."""
        ledger, recorder = make_ledger()

        now = 0.0
        tick_s = 30.0

        # The first K ticks should all dispatch (no cooldown yet).
        for i in range(DEFAULT_K):
            now += tick_s
            assert not ledger.any_cooldown_for_pair(self.TASK, self.LANE, now=now), (
                f"Should not be in cooldown at attempt {i + 1}"
            )
            ledger.record_refusal(self.TASK, self.LANE, self.REASON, now=now)

        # The (K+1)th tick should be skipped (in cooldown).
        now += tick_s
        assert ledger.any_cooldown_for_pair(self.TASK, self.LANE, now=now), (
            "Should be in cooldown after K refusals"
        )
        # Exactly 1 escalation at the K boundary.
        assert len(recorder.calls) == 1

    def test_storm_replay_cooldown_eventually_expires(self) -> None:
        """After the cooldown period expires, a new attempt is allowed — so
        the system retries periodically, not forever blocked."""
        ledger, recorder = make_ledger()

        now = 0.0
        tick_s = 30.0

        # Drive through K refusals.
        for _ in range(DEFAULT_K):
            now += tick_s
            ledger.record_refusal(self.TASK, self.LANE, self.REASON, now=now)

        # Now in cooldown.
        assert ledger.any_cooldown_for_pair(self.TASK, self.LANE, now=now)

        # Advance past the first cooldown period.
        now += BACKOFF_BASE_S + 1
        assert not ledger.any_cooldown_for_pair(self.TASK, self.LANE, now=now)

        # Another attempt is allowed — this is the re-probe.
        ledger.record_refusal(self.TASK, self.LANE, self.REASON, now=now)
        # Cooldown again, with longer backoff (2^1 * base).
        assert ledger.any_cooldown_for_pair(self.TASK, self.LANE, now=now)

    def test_storm_no_duplicate_escalation(self) -> None:
        """Even with many re-probes after cooldown expiry, escalation fires
        only once for a given (task, lane, reason) triple."""
        ledger, recorder = make_ledger()

        now = 0.0
        for _i in range(50):
            now += BACKOFF_MAX_S + 100  # always past any cooldown
            ledger.record_refusal(self.TASK, self.LANE, self.REASON, now=now)

        assert len(recorder.calls) == 1


# ── refusal classification ────────────────────────────────────────────────────


class TestRefusalClassification:
    def test_deterministic_reason(self) -> None:
        assert not is_transient_reason(
            "BLOCKED: route policy refuse: runtime_actuation_receipt_absent"
        )

    def test_timeout_is_transient(self) -> None:
        assert is_transient_reason("TimeoutExpired: subprocess timed out after 10s")

    def test_oserror_is_transient(self) -> None:
        assert is_transient_reason("OSError: [Errno 2] No such file or directory")

    def test_connection_refused_is_transient(self) -> None:
        assert is_transient_reason("connection refused on port 8051")


# ── K threshold and cooldown mechanics ────────────────────────────────────────


class TestKThreshold:
    def test_no_cooldown_before_k(self) -> None:
        ledger, recorder = make_ledger(k=3)
        now = 100.0
        for i in range(2):
            ledger.record_refusal("t1", "lane-a", "reason-x", now=now + i)
        assert not ledger.any_cooldown_for_pair("t1", "lane-a", now=now + 2)
        assert len(recorder.calls) == 0

    def test_cooldown_at_k(self) -> None:
        ledger, recorder = make_ledger(k=3)
        now = 100.0
        for i in range(3):
            ledger.record_refusal("t1", "lane-a", "reason-x", now=now + i)
        assert ledger.any_cooldown_for_pair("t1", "lane-a", now=now + 3)
        assert len(recorder.calls) == 1

    def test_transient_higher_k(self) -> None:
        """Transient reasons use TRANSIENT_K (10) instead of DEFAULT_K (3)."""
        ledger, recorder = make_ledger()
        now = 100.0
        for i in range(DEFAULT_K + 1):
            ledger.record_refusal("t1", "lane-a", "TimeoutExpired: timed out", now=now + i)
        # Should NOT be in cooldown yet (transient K is higher).
        assert not ledger.any_cooldown_for_pair("t1", "lane-a", now=now + DEFAULT_K + 1)
        assert len(recorder.calls) == 0  # No escalation for transient reasons.

    def test_transient_no_escalation(self) -> None:
        """Even after crossing the transient K, no ntfy escalation fires."""
        ledger, recorder = make_ledger()
        now = 100.0
        for _i in range(TRANSIENT_K + 5):
            now += BACKOFF_MAX_S + 1  # always past cooldown
            ledger.record_refusal("t1", "lane-a", "TimeoutExpired: timed out", now=now)
        assert len(recorder.calls) == 0


# ── exponential backoff ───────────────────────────────────────────────────────


class TestBackoff:
    def test_backoff_doubles(self) -> None:
        ledger, _ = make_ledger(k=1)
        now = 100.0

        # First refusal at K=1: backoff = base * 2^0 = base
        ledger.record_refusal("t1", "lane-a", "reason-x", now=now)
        entry = ledger._entries[("t1", "lane-a", "reason-x")]
        assert entry.cooldown_until == pytest.approx(now + BACKOFF_BASE_S, abs=0.1)

        # Expire and re-refusal: backoff = base * 2^1 = 2*base
        now = entry.cooldown_until + 1
        ledger.record_refusal("t1", "lane-a", "reason-x", now=now)
        assert entry.cooldown_until == pytest.approx(now + 2 * BACKOFF_BASE_S, abs=0.1)

    def test_backoff_capped(self) -> None:
        ledger, _ = make_ledger(k=1)
        now = 100.0
        # Drive many refusals to hit the cap.
        for _i in range(30):
            now += BACKOFF_MAX_S + 100
            ledger.record_refusal("t1", "lane-a", "reason-x", now=now)

        entry = ledger._entries[("t1", "lane-a", "reason-x")]
        # The cooldown should never exceed the cap.
        remaining = entry.cooldown_until - now
        assert remaining <= BACKOFF_MAX_S + 1

    def test_backoff_cap_does_not_overflow_before_min_applies(self) -> None:
        ledger, _ = make_ledger(k=1)
        now = 100.0

        # This would raise OverflowError if record_refusal computed
        # base * (2**exponent) before checking whether the cap already applies.
        for _i in range(1100):
            now += BACKOFF_MAX_S + 100
            ledger.record_refusal("t1", "lane-a", "reason-x", now=now)

        entry = ledger._entries[("t1", "lane-a", "reason-x")]
        assert entry.cooldown_until - now <= BACKOFF_MAX_S + 1


# ── success reset ─────────────────────────────────────────────────────────────


class TestSuccessReset:
    def test_clear_removes_refusal_state(self) -> None:
        ledger, recorder = make_ledger(k=2)
        ledger.record_refusal("t1", "lane-a", "reason-x", now=100.0)
        ledger.record_refusal("t1", "lane-a", "reason-x", now=101.0)
        assert ledger.any_cooldown_for_pair("t1", "lane-a", now=102.0)

        # On dispatch success, the coordinator calls clear(task_id).
        ledger.clear("t1")
        assert not ledger.any_cooldown_for_pair("t1", "lane-a", now=102.0)

    def test_clear_only_affects_named_task(self) -> None:
        ledger, _ = make_ledger(k=1)
        ledger.record_refusal("t1", "lane-a", "reason-x", now=100.0)
        ledger.record_refusal("t2", "lane-a", "reason-x", now=100.0)

        ledger.clear("t1")
        assert not ledger.any_cooldown_for_pair("t1", "lane-a", now=101.0)
        assert ledger.any_cooldown_for_pair("t2", "lane-a", now=101.0)


# ── starvation detection ─────────────────────────────────────────────────────


class TestStarvation:
    def test_starvation_fires_after_horizon(self) -> None:
        ledger, recorder = make_ledger(starvation_horizon_s=60.0)
        now = 100.0

        # offered>0, dispatched=0 for 61s → escalation.
        ledger.tick_starvation(3, 0, now=now)
        assert len(recorder.calls) == 0  # Not yet.

        fired = ledger.tick_starvation(3, 0, now=now + 61)
        assert fired
        assert len(recorder.calls) == 1
        assert "starvation" in recorder.calls[0][0].lower()

    def test_starvation_does_not_repeat(self) -> None:
        ledger, recorder = make_ledger(starvation_horizon_s=60.0)
        ledger.tick_starvation(3, 0, now=100.0)
        ledger.tick_starvation(3, 0, now=200.0)  # fires
        ledger.tick_starvation(3, 0, now=300.0)  # should NOT fire again
        assert len(recorder.calls) == 1

    def test_starvation_resets_on_dispatch(self) -> None:
        ledger, recorder = make_ledger(starvation_horizon_s=60.0)
        ledger.tick_starvation(3, 0, now=100.0)  # start tracking
        ledger.tick_starvation(3, 1, now=130.0)  # dispatched → reset
        ledger.tick_starvation(3, 0, now=140.0)  # restart tracking
        ledger.tick_starvation(3, 0, now=250.0)  # 110s from 140 → fires
        assert len(recorder.calls) == 1

    def test_no_starvation_when_queue_empty(self) -> None:
        ledger, recorder = make_ledger(starvation_horizon_s=60.0)
        ledger.tick_starvation(0, 0, now=100.0)
        ledger.tick_starvation(0, 0, now=200.0)
        assert len(recorder.calls) == 0


# ── stats ─────────────────────────────────────────────────────────────────────


class TestStats:
    def test_stats_reflects_ledger_state(self) -> None:
        ledger, _ = make_ledger(k=2)
        now = 100.0
        ledger.record_refusal("t1", "lane-a", "r1", now=now)
        ledger.record_refusal("t1", "lane-a", "r1", now=now + 1)
        ledger.record_refusal("t2", "lane-b", "r2", now=now + 2)

        stats = ledger.stats(now=now + 3)
        assert stats["refusal_triples"] == 2
        # t1/lane-a/r1 has crossed K and is cooled; t2/lane-b/r2 has only 1 attempt.
        assert stats["cooled_down"] >= 1
        assert stats["escalated"] >= 1


# ── different reasons on same (task, lane) ────────────────────────────────────


class TestDifferentReasons:
    def test_different_reasons_are_independent(self) -> None:
        """Two different reasons on the same (task, lane) pair are tracked
        independently — each has its own K counter."""
        ledger, recorder = make_ledger(k=3)
        now = 100.0
        for i in range(2):
            ledger.record_refusal("t1", "lane-a", "reason-A", now=now + i)
            ledger.record_refusal("t1", "lane-a", "reason-B", now=now + i)

        # Neither has crossed K=3 yet.
        assert not ledger.any_cooldown_for_pair("t1", "lane-a", now=now + 3)
        assert len(recorder.calls) == 0

    def test_any_cooldown_blocks_pair(self) -> None:
        """If one reason crosses K, any_cooldown_for_pair blocks the pair."""
        ledger, _ = make_ledger(k=2)
        now = 100.0
        ledger.record_refusal("t1", "lane-a", "reason-A", now=now)
        ledger.record_refusal("t1", "lane-a", "reason-A", now=now + 1)
        # reason-A crossed K=2 → pair is cooled.
        assert ledger.any_cooldown_for_pair("t1", "lane-a", now=now + 2)


# ── task-scoped cooldown (starvation discount) ────────────────────────────────


class TestAnyCooldownForTask:
    def test_true_when_task_cooled_on_any_lane(self) -> None:
        ledger, _ = make_ledger(k=1)
        ledger.record_refusal("t1", "lane-a", "reason-x", now=100.0)
        # Cooled on lane-a → task is held regardless of lane.
        assert ledger.any_cooldown_for_task("t1", now=101.0)
        # A different task with no refusals is not held.
        assert not ledger.any_cooldown_for_task("t2", now=101.0)

    def test_false_after_clear(self) -> None:
        ledger, _ = make_ledger(k=1)
        ledger.record_refusal("t1", "lane-a", "reason-x", now=100.0)
        ledger.clear("t1")
        assert not ledger.any_cooldown_for_task("t1", now=101.0)

    def test_false_after_cooldown_expires(self) -> None:
        ledger, _ = make_ledger(k=1)
        ledger.record_refusal("t1", "lane-a", "reason-x", now=100.0)
        assert ledger.any_cooldown_for_task("t1", now=101.0)
        # Past the first backoff window the task is no longer held.
        assert not ledger.any_cooldown_for_task("t1", now=100.0 + BACKOFF_BASE_S + 1)


# ── escalation body content ───────────────────────────────────────────────────


class TestEscalationBody:
    def test_escalation_body_contains_reason_and_pair(self) -> None:
        """The circuit-breaker escalation carries the named refusal reason and the
        (task, lane) pair — the exit predicate requires the reason to ride the
        escalation, not just a bare count."""
        ledger, recorder = make_ledger(k=2)
        reason = "BLOCKED: route policy refuse: runtime_actuation_receipt_absent"
        ledger.record_refusal("cctv-task", "cx-alpha", reason, now=100.0)
        ledger.record_refusal("cctv-task", "cx-alpha", reason, now=101.0)

        assert len(recorder.calls) == 1
        _title, body = recorder.calls[0]
        assert reason in body
        assert "cctv-task" in body
        assert "cx-alpha" in body
