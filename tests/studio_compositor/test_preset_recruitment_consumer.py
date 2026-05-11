"""Tests for the preset-recruitment → transition-primitive bridge (Phase 7b of #166).

The consumer reads ``recent-recruitment.json`` for a fresh
``preset.bias`` family, picks a preset within it, then dispatches one
of the five transition primitives on a daemon thread. These tests
exercise the dispatch shape (selection + threading + cooldown +
single-flight + state tracking) without leaning on the live SHM
surface.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from agents.studio_compositor import preset_recruitment_consumer as prc
from agents.studio_compositor.transition_primitives import PRIMITIVES, TRANSITION_NAMES


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test gets a fresh module-state + a tmp recruitment file."""
    monkeypatch.setattr(prc, "RECRUITMENT_FILE", tmp_path / "recent-recruitment.json")
    prc._reset_state_for_tests()
    yield
    prc._reset_state_for_tests()


def _write_recruitment(
    path: Path,
    family: str,
    ts: float | None = None,
    *,
    ttl_s: float | None = None,
) -> None:
    if ts is None:
        ts = time.time()
    entry = {"family": family, "last_recruited_ts": ts}
    if ttl_s is not None:
        entry["ttl_s"] = ttl_s
    payload = {"families": {"preset.bias": entry}}
    path.write_text(json.dumps(payload), encoding="utf-8")


def _wait_for_thread(name: str = "preset-transition", timeout: float = 2.0) -> None:
    """Block until the named daemon thread exits — avoids racy assertions."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        active = [t for t in threading.enumerate() if t.name == name]
        if not active:
            return
        time.sleep(0.01)


# ── selection ──────────────────────────────────────────────────────────────


def test_select_transition_falls_back_to_uniform() -> None:
    name, fn = prc._select_transition()
    assert name in TRANSITION_NAMES
    assert fn is PRIMITIVES[name]


def test_select_transition_prefers_recruited_within_cooldown(tmp_path: Path) -> None:
    payload = {
        "families": {
            "transition.netsplit.burst": {"last_recruited_ts": time.time()},
        }
    }
    prc.RECRUITMENT_FILE.write_text(json.dumps(payload), encoding="utf-8")
    name, fn = prc._select_transition()
    assert name == "transition.netsplit.burst"
    assert fn is PRIMITIVES["transition.netsplit.burst"]


def test_select_transition_ignores_stale_recruited(tmp_path: Path) -> None:
    payload = {
        "families": {
            "transition.cut.hard": {
                "last_recruited_ts": time.time() - prc._TRANSITION_BIAS_COOLDOWN_S - 5,
            },
        }
    }
    prc.RECRUITMENT_FILE.write_text(json.dumps(payload), encoding="utf-8")
    with patch(
        "agents.studio_compositor.preset_recruitment_consumer.random.choice",
        return_value="transition.fade.smooth",
    ):
        name, _ = prc._select_transition()
    assert name == "transition.fade.smooth"


# ── single-flight + threading ──────────────────────────────────────────────


def test_run_transition_async_dispatches_on_thread() -> None:
    captured_writes: list[dict] = []
    fn_calls: list[tuple] = []

    def _fake_fn(
        out: dict | None,
        in_g: dict,
        writer: Callable[[dict], None],
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        fn_calls.append((out, in_g))
        writer({"node": "from-fake-fn"})

    out_g: dict[str, Any] = {"id": "out"}
    in_g: dict[str, Any] = {"id": "in"}
    with patch.object(prc, "_write_mutation", side_effect=captured_writes.append):
        prc._run_transition_async("transition.fade.smooth", _fake_fn, out_g, in_g)
        _wait_for_thread()
    assert len(fn_calls) == 1
    assert fn_calls[0] == (out_g, in_g)
    assert captured_writes == [{"node": "from-fake-fn"}]


def test_run_transition_async_single_flight_degrades_to_cut(tmp_path: Path) -> None:
    """A second activation that races an in-flight primitive must hard-cut
    instead of interleaving its writes."""
    started = threading.Event()
    blocker = threading.Event()
    captured_writes: list[dict] = []

    def _slow_fn(
        out: dict | None,
        in_g: dict,
        writer: Callable[[dict], None],
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        started.set()
        blocker.wait(timeout=2.0)
        writer({"node": "slow-fn"})

    def _fast_fn(
        out: dict | None,
        in_g: dict,
        writer: Callable[[dict], None],
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        # Should never be called — the lock is held by the slow primitive.
        writer({"node": "fast-fn"})

    in_g_a: dict[str, Any] = {"id": "A"}
    in_g_b: dict[str, Any] = {"id": "B"}
    with patch.object(prc, "_write_mutation", side_effect=captured_writes.append):
        prc._run_transition_async("transition.fade.smooth", _slow_fn, None, in_g_a)
        assert started.wait(timeout=1.0)
        # While the slow primitive holds the lock, dispatch a second one.
        prc._run_transition_async("transition.cut.hard", _fast_fn, in_g_a, in_g_b)
        # Wait for the fast-path runner to finish (it should hard-cut).
        time.sleep(0.05)
        # Now release the slow primitive and let it finish.
        blocker.set()
        _wait_for_thread()
    # Expected sequence: hard-cut wrote in_g_b (the lock-rejected dispatch),
    # then slow-fn wrote its own marker. Order is hard-cut first because the
    # fast runner doesn't wait on the lock.
    assert {"id": "B"} in captured_writes
    assert {"node": "slow-fn"} in captured_writes
    assert {"node": "fast-fn"} not in captured_writes


# ── process_preset_recruitment integration ────────────────────────────────


def test_process_no_recruitment_file_returns_false() -> None:
    assert prc.process_preset_recruitment() is False


def test_process_unknown_family_returns_false(tmp_path: Path) -> None:
    _write_recruitment(prc.RECRUITMENT_FILE, "no-such-family")
    assert prc.process_preset_recruitment() is False


def test_process_accepts_selector_family_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The live consumer must accept selector-supported aliases.

    ``audio-abstract`` is offered by the director prompt and resolves to
    ``neutral-ambient`` in ``preset_family_selector``. The consumer used
    to reject it before the selector could see it, making the live
    recruitment path narrower than the tested catalog.
    """
    _write_recruitment(prc.RECRUITMENT_FILE, "audio-abstract")
    fake_graph: dict[str, Any] = {"nodes": {}, "marker": "alias-graph"}
    seen_families: list[str] = []

    def _fake_pick(family: str, **_kwargs: Any) -> tuple[str, dict[str, Any]]:
        seen_families.append(family)
        return "nightvision", fake_graph

    monkeypatch.setenv("HAPAX_SEGMENT_BIAS_DISABLED", "1")
    monkeypatch.setattr(prc, "pick_and_load_mutated", _fake_pick)
    monkeypatch.setattr(
        prc,
        "_select_transition",
        lambda: ("transition.cut.hard", PRIMITIVES["transition.cut.hard"]),
    )
    captured_writes: list[dict] = []
    monkeypatch.setattr(prc, "_write_mutation", captured_writes.append)

    assert prc.process_preset_recruitment() is True
    _wait_for_thread()
    assert seen_families == ["audio-abstract"]
    assert any(g.get("marker") == "alias-graph" for g in captured_writes)


def test_process_dispatches_transition_on_first_recruitment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: write a recruitment file with a known family, expect the
    consumer to dispatch a transition primitive on a background thread."""
    from agents.studio_compositor.preset_family_selector import family_names

    fam = next(iter(family_names()))
    _write_recruitment(prc.RECRUITMENT_FILE, fam)
    fake_graph: dict[str, Any] = {"nodes": {}, "marker": "fake-graph"}

    monkeypatch.setattr(prc, "pick_and_load_mutated", lambda *a, **kw: ("fake-preset", fake_graph))
    captured_writes: list[dict] = []
    monkeypatch.setattr(prc, "_write_mutation", captured_writes.append)
    # Pin the transition pick so the assertion is deterministic.
    monkeypatch.setattr(
        prc,
        "_select_transition",
        lambda: ("transition.cut.hard", PRIMITIVES["transition.cut.hard"]),
    )

    assert prc.process_preset_recruitment() is True
    _wait_for_thread()
    # cut.hard writes exactly once with the fake graph
    assert any(g.get("marker") == "fake-graph" for g in captured_writes)


def test_process_honors_fx_autonomous_mutation_disable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agents.studio_compositor.preset_family_selector import family_names

    fam = next(iter(family_names()))
    ts = time.time()
    _write_recruitment(prc.RECRUITMENT_FILE, fam, ts=ts)
    monkeypatch.setenv("HAPAX_FX_AUTONOMOUS_MUTATIONS", "0")
    monkeypatch.setattr(
        prc,
        "pick_and_load_mutated",
        lambda *a, **kw: pytest.fail("disabled recruitment must not pick a preset"),
    )

    assert prc.process_preset_recruitment() is False
    assert prc._last_recruitment_ts_seen == ts


def test_disabled_fx_autonomous_mutation_logs_once_per_recruitment(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from agents.studio_compositor.preset_family_selector import family_names

    fam = next(iter(family_names()))
    ts = time.time()
    _write_recruitment(prc.RECRUITMENT_FILE, fam, ts=ts)
    monkeypatch.setenv("HAPAX_FX_AUTONOMOUS_MUTATIONS", "0")
    caplog.set_level("INFO", logger=prc.log.name)

    assert prc.process_preset_recruitment() is False
    assert prc.process_preset_recruitment() is False

    messages = [
        record.getMessage()
        for record in caplog.records
        if "preset recruitment suppressed by HAPAX_FX_AUTONOMOUS_MUTATIONS=0" in record.getMessage()
    ]
    assert len(messages) == 1
    assert prc._last_recruitment_ts_seen == ts


def test_disabled_fx_autonomous_mutation_consumes_stale_recruitment_silently(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from agents.studio_compositor.preset_family_selector import family_names

    fam = next(iter(family_names()))
    ts = time.time() - 30.0
    _write_recruitment(prc.RECRUITMENT_FILE, fam, ts=ts, ttl_s=1.0)
    monkeypatch.setenv("HAPAX_FX_AUTONOMOUS_MUTATIONS", "0")
    caplog.set_level("INFO", logger=prc.log.name)

    assert prc.process_preset_recruitment() is False
    assert prc.process_preset_recruitment() is False

    messages = [
        record.getMessage()
        for record in caplog.records
        if "preset recruitment suppressed by HAPAX_FX_AUTONOMOUS_MUTATIONS=0" in record.getMessage()
    ]
    assert messages == []
    assert prc._last_recruitment_ts_seen == ts


def test_process_rejects_expired_recruitment_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    from agents.studio_compositor.preset_family_selector import family_names

    fam = next(iter(family_names()))
    _write_recruitment(prc.RECRUITMENT_FILE, fam, ts=time.time() - 30.0, ttl_s=1.0)
    monkeypatch.setattr(
        prc,
        "pick_and_load_mutated",
        lambda *a, **kw: pytest.fail("stale recruitment must not pick a preset"),
    )

    assert prc.process_preset_recruitment() is False


def test_process_accepts_fresh_recruitment_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    from agents.studio_compositor.preset_family_selector import family_names

    fam = next(iter(family_names()))
    _write_recruitment(prc.RECRUITMENT_FILE, fam, ts=time.time() - 1.0, ttl_s=30.0)
    fake_graph: dict[str, Any] = {"nodes": {}, "marker": "fresh-ttl"}
    monkeypatch.setattr(prc, "pick_and_load_mutated", lambda *a, **kw: ("p", fake_graph))
    monkeypatch.setattr(
        prc,
        "_select_transition",
        lambda: ("transition.cut.hard", PRIMITIVES["transition.cut.hard"]),
    )
    captured_writes: list[dict] = []
    monkeypatch.setattr(prc, "_write_mutation", captured_writes.append)

    assert prc.process_preset_recruitment() is True
    _wait_for_thread()
    assert any(g.get("marker") == "fresh-ttl" for g in captured_writes)


def test_process_rejects_recruitment_timestamp_too_far_in_future(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agents.studio_compositor.preset_family_selector import family_names

    fam = next(iter(family_names()))
    _write_recruitment(
        prc.RECRUITMENT_FILE,
        fam,
        ts=time.time() + prc._MAX_RECRUITMENT_FUTURE_S + 10.0,
        ttl_s=30.0,
    )
    monkeypatch.setattr(
        prc,
        "pick_and_load_mutated",
        lambda *a, **kw: pytest.fail("future recruitment must not pick a preset"),
    )

    assert prc.process_preset_recruitment() is False


def test_single_write_transition_env_forces_cut_hard(monkeypatch: pytest.MonkeyPatch) -> None:
    from agents.studio_compositor.preset_family_selector import family_names

    fam = next(iter(family_names()))
    _write_recruitment(prc.RECRUITMENT_FILE, fam)
    fake_graph: dict[str, Any] = {"nodes": {}, "marker": "single-write"}

    monkeypatch.setenv(prc._SINGLE_WRITE_TRANSITIONS_ENV, "1")
    monkeypatch.setattr(prc, "pick_and_load_mutated", lambda *a, **kw: ("p", fake_graph))
    monkeypatch.setattr(
        prc,
        "_select_transition",
        lambda: pytest.fail("single-write containment must bypass transition selection"),
    )
    captured_writes: list[dict] = []
    monkeypatch.setattr(prc, "_write_mutation", captured_writes.append)

    assert prc.process_preset_recruitment() is True
    _wait_for_thread()
    assert captured_writes == [fake_graph]


def test_process_cooldown_blocks_repeat_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    from agents.studio_compositor.preset_family_selector import family_names

    fam = next(iter(family_names()))
    _write_recruitment(prc.RECRUITMENT_FILE, fam)
    monkeypatch.setattr(prc, "pick_and_load_mutated", lambda *a, **kw: ("p", {"nodes": {}}))
    monkeypatch.setattr(
        prc,
        "_select_transition",
        lambda: ("transition.cut.hard", PRIMITIVES["transition.cut.hard"]),
    )
    monkeypatch.setattr(prc, "_write_mutation", lambda _g: None)

    assert prc.process_preset_recruitment() is True
    _wait_for_thread()
    # Second tick before cooldown elapses → no dispatch
    _write_recruitment(prc.RECRUITMENT_FILE, fam, ts=time.time() + 0.001)
    assert prc.process_preset_recruitment() is False


def test_process_tracks_last_graph_for_transition_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The consumer must remember the previously-activated graph so the
    next transition's ``out`` argument is the right one."""
    from agents.studio_compositor.preset_family_selector import family_names

    fam = next(iter(family_names()))
    graph_a: dict[str, Any] = {"id": "A"}
    graph_b: dict[str, Any] = {"id": "B"}

    monkeypatch.setattr(
        prc,
        "_select_transition",
        lambda: ("transition.cut.hard", PRIMITIVES["transition.cut.hard"]),
    )
    monkeypatch.setattr(prc, "_write_mutation", lambda _g: None)

    seen_out: list[dict | None] = []

    def _spy_run(name, fn, out, in_g):
        seen_out.append(out)
        # Don't actually start a thread — easier to assert.
        prc._last_graph_activated = in_g

    monkeypatch.setattr(prc, "_run_transition_async", _spy_run)

    monkeypatch.setattr(prc, "pick_and_load_mutated", lambda *a, **kw: ("p1", graph_a))
    _write_recruitment(prc.RECRUITMENT_FILE, fam)
    assert prc.process_preset_recruitment() is True
    assert seen_out[-1] is None  # first dispatch has no prior graph

    # Bypass cooldown for the test
    prc._last_activation_t = time.monotonic() - prc.COOLDOWN_S - 1
    monkeypatch.setattr(prc, "pick_and_load_mutated", lambda *a, **kw: ("p2", graph_b))
    _write_recruitment(prc.RECRUITMENT_FILE, fam, ts=time.time() + 1.0)
    assert prc.process_preset_recruitment() is True
    assert seen_out[-1] is graph_a  # second dispatch carries the prior graph


# ── Defensive readers — non-dict JSON root ──────────────────────────────


class TestReadersRejectNonDictRoot:
    """Pin both SHM read sites against non-dict JSON roots.

    ``_read_recruited_transition`` (line 126) and
    ``process_preset_recruitment`` (line 219) called ``data.get(...)``
    outside the json.loads except clause; a writer producing valid
    JSON whose root is null, a list, a string, or a number raised
    AttributeError out of the compositor preset-recruitment path.
    Same corruption-class as #2627, #2631, #2632, #2633, #2636.
    """

    @pytest.mark.parametrize(
        "payload,kind",
        [("null", "null"), ('"string"', "string"), ("[1,2]", "list"), ("42", "int")],
    )
    def test_read_recruited_transition_non_dict_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: str, kind: str
    ):
        path = tmp_path / "recruitment.json"
        path.write_text(payload)
        monkeypatch.setattr(prc, "RECRUITMENT_FILE", path)
        assert prc._read_recruited_transition() is None, f"non-dict root={kind} must yield None"

    @pytest.mark.parametrize(
        "payload,kind",
        [("null", "null"), ('"string"', "string"), ("[1,2]", "list"), ("42", "int")],
    )
    def test_process_preset_recruitment_non_dict_returns_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: str, kind: str
    ):
        path = tmp_path / "recruitment.json"
        path.write_text(payload)
        monkeypatch.setattr(prc, "RECRUITMENT_FILE", path)
        assert prc.process_preset_recruitment() is False, f"non-dict root={kind} must yield False"

    def test_process_preset_recruitment_non_dict_families_returns_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """``payload[\"families\"]`` could itself be non-dict — tests the
        chained .get() failure mode where ``payload`` is dict but
        ``payload['families']`` is a list/string/number."""
        path = tmp_path / "recruitment.json"
        path.write_text('{"families": ["mixer", "desk"]}')
        monkeypatch.setattr(prc, "RECRUITMENT_FILE", path)
        assert prc.process_preset_recruitment() is False
