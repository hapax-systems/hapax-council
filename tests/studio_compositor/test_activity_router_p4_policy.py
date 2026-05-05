"""P4 router-policy pins for the activity-reveal ward family."""

from __future__ import annotations

from typing import Any

from agents.studio_compositor.activity_reveal_ward import ActivityRevealMixin
from agents.studio_compositor.activity_router import (
    ACTIVITY_ROUTER_POLICY_ENV,
    ActivityRouter,
    RouterConfig,
    RouterPolicy,
)
from agents.studio_compositor.compositor import StudioCompositor


class _PolicyWard(ActivityRevealMixin):
    WARD_ID = "policy-base"
    SOURCE_KIND = "cairo"
    priority = 0

    def __init__(self, *, score: float = 0.5, want: bool = True, mand: bool = False) -> None:
        super().__init__(start_poll_thread=False)
        self.score = score
        self.want = want
        self.mand = mand

    def _compute_claim_score(self) -> float:
        return self.score

    def _want_visible(self) -> bool:
        return self.want

    def _mandatory_invisible(self) -> bool:
        return self.mand

    def _claim_source_refs(self) -> tuple[str, ...]:
        return (f"{type(self).WARD_ID}:fixture",)

    def _describe_source_registration(self) -> dict[str, Any]:
        return {"id": type(self).WARD_ID, "kind": type(self).SOURCE_KIND}


class _A(_PolicyWard):
    WARD_ID = "policy-a"


class _B(_PolicyWard):
    WARD_ID = "policy-b"


class _High(_PolicyWard):
    WARD_ID = "policy-high"
    priority = 20


class _Low(_PolicyWard):
    WARD_ID = "policy-low"
    priority = 5


class _LexA(_PolicyWard):
    WARD_ID = "a-policy-tie"
    priority = 10


class _LexB(_PolicyWard):
    WARD_ID = "b-policy-tie"
    priority = 10


def _stop_all(*wards: ActivityRevealMixin) -> None:
    for ward in wards:
        ward.stop()


def test_activity_router_policy_unconstrained_allows_concurrent() -> None:
    a = _A()
    b = _B()
    router = ActivityRouter(
        [a, b],
        config=RouterConfig(policy=RouterPolicy.UNCONSTRAINED),
    )
    try:
        state = router.tick(now=10.0)
    finally:
        router.stop()
        _stop_all(a, b)

    assert router.policy is RouterPolicy.UNCONSTRAINED
    assert state.want_visible_ids == ("policy-a", "policy-b")
    assert state.policy_blocked_ids == ()


def test_activity_router_policy_first_wins_blocks_second() -> None:
    a = _A()
    b = _B()
    router = ActivityRouter(
        [a, b],
        config=RouterConfig(policy=RouterPolicy.FIRST_WINS),
    )
    try:
        first = router.tick(now=10.0)
        second = router.tick(now=11.0)
    finally:
        router.stop()
        _stop_all(a, b)

    assert first.want_visible_ids == ("policy-a",)
    assert first.policy_blocked_ids == ("policy-b",)
    assert second.want_visible_ids == ("policy-a",)
    assert second.policy_blocked_ids == ("policy-b",)


def test_activity_router_policy_priority_scored_highest_priority_then_lex() -> None:
    low = _Low()
    high = _High()
    tie_b = _LexB()
    tie_a = _LexA()
    priority_router = ActivityRouter(
        [low, high],
        config=RouterConfig(policy=RouterPolicy.PRIORITY_SCORED),
    )
    tie_router = ActivityRouter(
        [tie_b, tie_a],
        config=RouterConfig(policy=RouterPolicy.PRIORITY_SCORED),
    )
    try:
        priority_state = priority_router.tick(now=20.0)
        tie_state = tie_router.tick(now=20.0)
    finally:
        priority_router.stop()
        tie_router.stop()
        _stop_all(low, high, tie_b, tie_a)

    assert priority_state.want_visible_ids == ("policy-high",)
    assert priority_state.policy_blocked_ids == ("policy-low",)
    assert tie_state.want_visible_ids == ("a-policy-tie",)
    assert tie_state.policy_blocked_ids == ("b-policy-tie",)


def test_activity_router_policy_env_override(monkeypatch) -> None:
    monkeypatch.setenv(ACTIVITY_ROUTER_POLICY_ENV, "first-wins")
    assert RouterConfig().policy is RouterPolicy.FIRST_WINS


def test_activity_router_tick_integration_surface_calls_router() -> None:
    class _FakeRouter:
        def __init__(self) -> None:
            self.calls = 0

        def tick(self) -> None:
            self.calls += 1

    compositor = object.__new__(StudioCompositor)
    fake = _FakeRouter()
    compositor._running = True
    compositor._activity_router = fake

    assert StudioCompositor._activity_router_tick(compositor) is True
    assert fake.calls == 1


def test_activity_router_builder_collects_activity_reveal_sources() -> None:
    class _Backend:
        def __init__(self, source: ActivityRevealMixin) -> None:
            self._source = source

    class _Registry:
        def __init__(self, source: ActivityRevealMixin) -> None:
            self._backends = {"policy-a": _Backend(source)}

        def ids(self) -> list[str]:
            return list(self._backends)

    class _Layout:
        sources: tuple[object, ...] = ()

    ward = _A()
    compositor = object.__new__(StudioCompositor)
    try:
        router = StudioCompositor._build_activity_router(compositor, _Layout(), _Registry(ward))
    finally:
        ward.stop()

    assert router is not None
    try:
        assert router.describe()["ward_ids"] == ["policy-a"]
    finally:
        router.stop()
