"""Gate-0A conformance for support-only dispatch refusal observations."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from agents.coordinator.refusal_ledger import (
    DEFAULT_K,
    SUPPORT_EFFECT_STATE,
    SUPPORT_HOLD_REASON,
    TRANSIENT_K,
    DispatchRefusalLedger,
    is_transient_reason,
)


@dataclass
class EscalationRecorder:
    calls: list[tuple[str, str]] = field(default_factory=list)

    def __call__(self, title: str, body: str) -> None:
        self.calls.append((title, body))


def make_ledger(**kwargs: object) -> tuple[DispatchRefusalLedger, EscalationRecorder]:
    recorder = EscalationRecorder()
    return DispatchRefusalLedger(_escalate_fn=recorder, **kwargs), recorder


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("TimeoutExpired: dispatcher timed out", True),
        ("temporary connection refused", True),
        ("BLOCKED: route policy refuse: upstream timeout", False),
        ("validation failed", False),
    ],
)
def test_reason_classification_is_diagnostic_only(
    reason: str, expected: bool
) -> None:
    assert is_transient_reason(reason) is expected


def test_deterministic_observations_become_visible_hold_without_effect() -> None:
    ledger, recorder = make_ledger()
    entry = None
    for attempt in range(DEFAULT_K):
        entry = ledger.record_refusal(
            "task-a",
            "cx-alpha",
            "BLOCKED: no admitted execution lease",
            now=float(attempt + 1),
        )

    assert entry is not None
    assert entry.attempts == DEFAULT_K
    assert entry.hold_visible is True
    assert entry.effect_state == SUPPORT_EFFECT_STATE
    assert entry.hold_reason == SUPPORT_HOLD_REASON
    assert entry.may_authorize is False
    assert entry.cooldown_until == 0.0
    assert entry.escalated is False
    assert ledger.any_cooldown_for_pair("task-a", "cx-alpha", now=99.0) is False
    assert ledger.any_cooldown_for_task("task-a", now=99.0) is False
    assert recorder.calls == []


def test_transient_observations_use_visibility_threshold_not_cooldown() -> None:
    ledger, recorder = make_ledger()
    for attempt in range(TRANSIENT_K):
        entry = ledger.record_refusal(
            "task-a",
            "cx-alpha",
            "TimeoutExpired: dispatcher timed out",
            now=float(attempt + 1),
        )

    assert entry.transient is True
    assert entry.hold_visible is True
    assert entry.cooldown_until == 0.0
    assert recorder.calls == []


def test_storm_remains_observable_but_cannot_suppress_or_escalate() -> None:
    ledger, recorder = make_ledger()
    for tick in range(1, 1029):
        assert ledger.any_cooldown_for_pair("task-a", "cx-alpha", now=float(tick)) is False
        ledger.record_refusal(
            "task-a",
            "cx-alpha",
            "BLOCKED: route policy refuse",
            now=float(tick),
        )

    stats = ledger.stats(now=2000.0)
    assert stats["observations"] == 1028
    assert stats["visible_holds"] == 1
    assert stats["cooled_down"] == 0
    assert stats["escalated"] == 0
    assert recorder.calls == []


def test_starvation_shape_becomes_hold_without_notification() -> None:
    ledger, recorder = make_ledger(starvation_horizon_s=60.0)
    assert ledger.tick_starvation(3, 0, now=100.0) is False
    assert ledger.tick_starvation(3, 0, now=161.0) is False

    stats = ledger.stats()
    assert stats["starvation_active"] is True
    assert stats["starvation_hold_visible"] is True
    assert stats["starvation_escalated"] is False
    assert recorder.calls == []


def test_starvation_support_resets_after_progress() -> None:
    ledger, _ = make_ledger(starvation_horizon_s=0.0)
    ledger.tick_starvation(1, 0, now=1.0)
    ledger.tick_starvation(1, 0, now=2.0)
    assert ledger.stats()["starvation_hold_visible"] is True

    ledger.tick_starvation(1, 1, now=3.0)
    stats = ledger.stats()
    assert stats["starvation_active"] is False
    assert stats["starvation_hold_visible"] is False


def test_clear_is_bounded_to_named_task() -> None:
    ledger, _ = make_ledger()
    ledger.record_refusal("task-a", "cx-alpha", "reason-a", now=1.0)
    ledger.record_refusal("task-b", "cx-alpha", "reason-b", now=1.0)

    ledger.clear("task-a")
    assert ("task-a", "cx-alpha", "reason-a") not in ledger._entries
    assert ("task-b", "cx-alpha", "reason-b") in ledger._entries


@pytest.mark.parametrize(
    ("args", "reason"),
    [
        (("", "cx-alpha", "reason"), "task_id"),
        (("task-a", "", "reason"), "lane"),
        (("task-a", "cx-alpha", ""), "reason"),
    ],
)
def test_invalid_identity_is_rejected(
    args: tuple[str, str, str], reason: str
) -> None:
    ledger, _ = make_ledger()
    with pytest.raises(ValueError, match=f"dispatch_refusal_{reason}_invalid"):
        ledger.record_refusal(*args, now=1.0)


@pytest.mark.parametrize("now", [float("nan"), float("inf"), -1.0, True])
def test_invalid_observation_time_is_rejected(now: float) -> None:
    ledger, _ = make_ledger()
    with pytest.raises(ValueError, match="dispatch_refusal_observed_at_invalid"):
        ledger.record_refusal("task-a", "cx-alpha", "reason", now=now)


def test_compatibility_escalation_methods_are_inert() -> None:
    ledger, recorder = make_ledger()
    ledger._fire_escalation("task-a", "cx-alpha", "reason", 3)
    ledger._fire_starvation_escalation(2, 3600.0)
    assert recorder.calls == []
