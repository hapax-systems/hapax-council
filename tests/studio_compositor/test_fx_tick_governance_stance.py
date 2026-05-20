"""Regression pins for the halftone-monoculture fix (researcher audit 2026-05-03).

Three pinned behaviours:

1. ``fx_tick._read_stimmung_stance`` reads ``overall_stance`` from the
   stimmung state.json (falling back to ``"nominal"`` on missing /
   parse-error / unknown values, with ``seeking`` folded back to
   ``nominal`` because the ``_STATE_MATRIX`` has no ``seeking`` row).
2. ``preset_recruitment_consumer.process_preset_recruitment(compositor)``
   extends ``compositor._user_preset_hold_until`` by ``RECRUITMENT_HOLD_S``
   on a successful dispatch — so the 30 fps governance tick can't clobber
   a recruitment-driven preset within 33 ms.
3. ``metrics.record_preset_load_failed`` increments a labelled
   Prometheus counter (was a silent DEBUG swallow before).
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from agents.studio_compositor import fx_tick
from agents.studio_compositor import metrics as compositor_metrics
from agents.studio_compositor import preset_recruitment_consumer as prc

# ── _read_stimmung_stance ──────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_stance_cache() -> None:
    """Reset the module-level cache + path between tests."""
    fx_tick._stance_cache = (0.0, "nominal")
    yield
    fx_tick._stance_cache = (0.0, "nominal")


def _write_stimmung(path: Path, stance: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"overall_stance": stance}), encoding="utf-8")


@pytest.mark.parametrize(
    "stance,expected",
    [
        ("nominal", "nominal"),
        ("cautious", "cautious"),
        ("degraded", "degraded"),
        ("critical", "critical"),
        ("seeking", "nominal"),  # folded back — no _STATE_MATRIX row
        ("NOMINAL", "nominal"),  # case-insensitive
        ("not_a_real_stance", "nominal"),  # unknown → fallback
    ],
)
def test_read_stimmung_stance_maps_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stance: str,
    expected: str,
) -> None:
    state_path = tmp_path / "state.json"
    _write_stimmung(state_path, stance)
    monkeypatch.setattr(fx_tick, "_STIMMUNG_STATE_PATH", state_path)
    assert fx_tick._read_stimmung_stance() == expected


def test_read_stimmung_stance_missing_file_returns_nominal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fx_tick, "_STIMMUNG_STATE_PATH", tmp_path / "nope.json")
    assert fx_tick._read_stimmung_stance() == "nominal"


def test_read_stimmung_stance_malformed_returns_nominal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text("not json {{{", encoding="utf-8")
    monkeypatch.setattr(fx_tick, "_STIMMUNG_STATE_PATH", state_path)
    assert fx_tick._read_stimmung_stance() == "nominal"


def test_read_stimmung_stance_caches_30s(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Second read inside the cache window MUST NOT re-stat the file —
    otherwise the 30 fps governance tick re-parses 30 times/sec."""
    state_path = tmp_path / "state.json"
    _write_stimmung(state_path, "degraded")
    monkeypatch.setattr(fx_tick, "_STIMMUNG_STATE_PATH", state_path)
    first = fx_tick._read_stimmung_stance()
    assert first == "degraded"
    # Mutate the file. If the cache is honoured, we still see "degraded"
    # (the file-read should be skipped on the second call).
    _write_stimmung(state_path, "critical")
    second = fx_tick._read_stimmung_stance()
    assert second == "degraded"


def test_read_stimmung_stance_cache_expires(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = tmp_path / "state.json"
    _write_stimmung(state_path, "degraded")
    monkeypatch.setattr(fx_tick, "_STIMMUNG_STATE_PATH", state_path)
    assert fx_tick._read_stimmung_stance() == "degraded"
    # Force the cache to expire.
    fx_tick._stance_cache = (
        time.monotonic() - fx_tick._STANCE_CACHE_TTL_S - 1.0,
        "degraded",
    )
    _write_stimmung(state_path, "critical")
    assert fx_tick._read_stimmung_stance() == "critical"


# ── recruitment hold ───────────────────────────────────────────────────────


@pytest.fixture
def _isolated_recruit_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prc, "RECRUITMENT_FILE", tmp_path / "recent-recruitment.json")
    prc._reset_state_for_tests()
    yield
    prc._reset_state_for_tests()


def _write_recruitment(path: Path, family: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"families": {"preset.bias": {"family": family, "last_recruited_ts": time.time()}}}
    path.write_text(json.dumps(payload), encoding="utf-8")


def _wait_for_transition_thread(timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        active = [thread for thread in threading.enumerate() if thread.name == "preset-transition"]
        if not active:
            return
        time.sleep(0.01)


def test_process_preset_recruitment_extends_hold_when_compositor_passed(
    _isolated_recruit_state, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A successful recruitment dispatch MUST extend
    ``compositor._user_preset_hold_until`` by at least the cooldown
    so the 30 fps governance tick stops reverting the chain."""
    from agents.studio_compositor.preset_family_selector import family_names
    from agents.studio_compositor.transition_primitives import PRIMITIVES

    fam = next(iter(family_names()))
    _write_recruitment(prc.RECRUITMENT_FILE, fam)
    monkeypatch.setattr(
        prc,
        "policy_eligible_presets_for_family",
        lambda _family, **_kwargs: ("p",),
    )
    monkeypatch.setattr(prc, "pick_and_load_mutated", lambda *a, **kw: ("p", {"nodes": {}}))
    monkeypatch.setattr(
        prc,
        "_select_transition",
        lambda: ("transition.cut.hard", PRIMITIVES["transition.cut.hard"]),
    )
    monkeypatch.setattr(prc, "_write_mutation", lambda _g: None)

    class _FakeCompositor:
        _user_preset_hold_until = 0.0

    fake = _FakeCompositor()
    before = time.monotonic()
    assert prc.process_preset_recruitment(fake) is True
    after = time.monotonic()
    _wait_for_transition_thread()

    # Hold MUST be in [before + RECRUITMENT_HOLD_S, after + RECRUITMENT_HOLD_S].
    assert fake._user_preset_hold_until >= before + prc.RECRUITMENT_HOLD_S - 0.05
    assert fake._user_preset_hold_until <= after + prc.RECRUITMENT_HOLD_S + 0.05
    # Hold MUST be at least the cooldown — otherwise the governance tick
    # could clobber the chain before the next recruitment can re-fire.
    assert prc.RECRUITMENT_HOLD_S >= prc.COOLDOWN_S


def test_process_preset_recruitment_no_compositor_still_dispatches(
    _isolated_recruit_state, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Backward-compat: omitting the ``compositor`` argument still
    dispatches the transition (existing tests depend on this)."""
    from agents.studio_compositor.preset_family_selector import family_names
    from agents.studio_compositor.transition_primitives import PRIMITIVES

    fam = next(iter(family_names()))
    _write_recruitment(prc.RECRUITMENT_FILE, fam)
    monkeypatch.setattr(
        prc,
        "policy_eligible_presets_for_family",
        lambda _family, **_kwargs: ("p",),
    )
    monkeypatch.setattr(prc, "pick_and_load_mutated", lambda *a, **kw: ("p", {"nodes": {}}))
    monkeypatch.setattr(
        prc,
        "_select_transition",
        lambda: ("transition.cut.hard", PRIMITIVES["transition.cut.hard"]),
    )
    monkeypatch.setattr(prc, "_write_mutation", lambda _g: None)
    assert prc.process_preset_recruitment() is True
    _wait_for_transition_thread()


def test_process_preset_recruitment_no_dispatch_no_hold_extension(
    _isolated_recruit_state, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When no recruitment is pending, the hold MUST NOT be extended."""

    class _FakeCompositor:
        _user_preset_hold_until = 0.0

    fake = _FakeCompositor()
    assert prc.process_preset_recruitment(fake) is False
    assert fake._user_preset_hold_until == 0.0


# ── preset-load-failed counter ─────────────────────────────────────────────


def test_record_preset_load_failed_counter_increments() -> None:
    """``record_preset_load_failed`` MUST increment the labelled counter
    so the 64% load-fail rate becomes visible in dashboards."""
    counter = compositor_metrics.HAPAX_COMPOSITOR_PRESET_LOAD_FAILED_TOTAL
    assert counter is not None, "metric must be registered after _init_metrics()"

    # Read pre-state (best-effort — prometheus_client samples are
    # process-wide; we only need to verify a delta).
    sample_name = "hapax_compositor_preset_load_failed_total"
    before_value = 0.0
    for metric in counter.collect():
        for sample in metric.samples:
            if (
                sample.name == sample_name
                and sample.labels.get("preset") == "halftone_preset"
                and sample.labels.get("reason") == "ValidationError"
            ):
                before_value = sample.value
    compositor_metrics.record_preset_load_failed(preset="halftone_preset", reason="ValidationError")
    after_value = 0.0
    for metric in counter.collect():
        for sample in metric.samples:
            if (
                sample.name == sample_name
                and sample.labels.get("preset") == "halftone_preset"
                and sample.labels.get("reason") == "ValidationError"
            ):
                after_value = sample.value
    assert after_value - before_value == pytest.approx(1.0, abs=1e-9)


def test_record_preset_load_failed_safe_when_metric_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Helper MUST be a no-op (not crash) if Prometheus is unavailable
    and the counter never got initialised."""
    monkeypatch.setattr(compositor_metrics, "HAPAX_COMPOSITOR_PRESET_LOAD_FAILED_TOTAL", None)
    # Should not raise.
    compositor_metrics.record_preset_load_failed(preset="x", reason="y")


def test_tick_governance_honors_autonomous_fx_disable(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeSelector:
        def evaluate(self, **_kwargs):
            raise AssertionError("governance selector must not run when autonomous FX is disabled")

    class _FakeOverlay:
        _data = type(
            "_Data",
            (),
            {
                "desk_activity": "active",
                "music_genre": "",
            },
        )()

    fake = type(
        "_FakeCompositor",
        (),
        {
            "_graph_runtime": object(),
            "_atmospheric_selector": _FakeSelector(),
            "_overlay_state": _FakeOverlay(),
            "_user_preset_hold_until": 0.0,
        },
    )()
    monkeypatch.setenv("HAPAX_FX_AUTONOMOUS_MUTATIONS", "0")

    fx_tick.tick_governance(fake, 1.0)


def test_tick_governance_backs_off_failed_atmospheric_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeSelector:
        def __init__(self) -> None:
            self.marked: list[str] = []

        def evaluate(self, **_kwargs):
            return "bad_preset"

        def mark_load_failed(self, preset: str) -> None:
            self.marked.append(preset)

    class _FakeOverlay:
        _data = type(
            "_Data",
            (),
            {
                "desk_activity": "idle",
                "music_genre": "",
            },
        )()

    fake = type(
        "_FakeCompositor",
        (),
        {
            "_graph_runtime": object(),
            "_atmospheric_selector": _FakeSelector(),
            "_overlay_state": _FakeOverlay(),
            "_user_preset_hold_until": 0.0,
            "_current_preset_name": "clean",
            "_idle_start": None,
        },
    )()
    calls: list[str] = []

    monkeypatch.setattr(fx_tick, "_preset_load_failure_until", {})
    monkeypatch.setattr(fx_tick, "_degraded_active", lambda: False)
    monkeypatch.setattr(fx_tick, "_autonomous_fx_mutations_enabled", lambda: True)
    monkeypatch.setattr(
        "agents.studio_compositor.effects.get_available_preset_names",
        lambda: {"bad_preset"},
    )
    monkeypatch.setattr(
        "agents.studio_compositor.effects.try_graph_preset",
        lambda _compositor, name: calls.append(name) and False,
    )

    fx_tick.tick_governance(fake, 1.0)
    fx_tick.tick_governance(fake, 1.0)

    assert calls == ["bad_preset"]
    assert fake._atmospheric_selector.marked == ["bad_preset"]


def test_tick_governance_uses_stateful_gestural_layer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agents.effect_graph.visual_governance import GesturalOffsetLayer

    class _FakeSelector:
        def evaluate(self, **_kwargs):
            return None

    class _FakeOverlay:
        _data = type(
            "_Data",
            (),
            {
                "desk_activity": "scratching",
                "music_genre": "",
                "gaze_direction": "hardware",
                "person_count": 2,
            },
        )()

    class _FakeGraph:
        nodes = {"trail": object(), "bloom": object(), "drift": object()}

    class _FakeGraphRuntime:
        current_graph = _FakeGraph()

    class _FakeCompositor:
        _graph_runtime = _FakeGraphRuntime()
        _atmospheric_selector = _FakeSelector()
        _overlay_state = _FakeOverlay()
        _user_preset_hold_until = 0.0
        _current_preset_name = "clean"
        _idle_start = None
        _gestural_offset_layer = GesturalOffsetLayer()

        def __init__(self) -> None:
            self.changes: list[tuple[str, dict[str, float]]] = []

        def _on_graph_params_changed(self, node_id: str, params: dict[str, float]) -> None:
            self.changes.append((node_id, params))

    now = 100.0
    fake = _FakeCompositor()

    monkeypatch.setattr(fx_tick, "_degraded_active", lambda: False)
    monkeypatch.setattr(fx_tick, "_autonomous_fx_mutations_enabled", lambda: True)
    monkeypatch.setattr(fx_tick, "_read_stimmung_stance", lambda: "nominal")
    monkeypatch.setattr(fx_tick.time, "monotonic", lambda: now)
    monkeypatch.setattr(
        "agents.studio_compositor.effects.get_available_preset_names",
        lambda: set(),
    )

    fx_tick.tick_governance(fake, 1.0)
    assert fake.changes == []

    now = 100.5
    fx_tick.tick_governance(fake, 1.0)

    trail_updates = [params["opacity"] for node, params in fake.changes if node == "trail"]
    assert trail_updates == [pytest.approx(0.2 * 1.2 * 0.6 * 0.5)]
