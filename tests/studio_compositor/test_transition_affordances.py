"""Tests for Phase 7 transition primitives + random_mode wiring (#166).

Spec: ``docs/superpowers/plans/2026-04-20-preset-variety-plan.md`` Phase 7
(research §5.5). Five primitives are registered as affordance records and
``random_mode`` recruits one per chain change.

These tests assert:

- Each primitive produces the expected sequence of mutated graphs and
  total step count when run with a capture-writer + no-op sleep.
- Each primitive yields a distinct mutation sequence so the surface
  visually distinguishes between them.
- ``random_mode._select_transition`` returns the recruitment-bias
  capability when ``recent-recruitment.json`` carries a fresh
  ``transition.*`` entry, falling back to uniform sampling otherwise.
- ``compositional_affordances`` registers all 5 transitions in the
  catalog so the seed script can embed them in Qdrant.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from agents.studio_compositor import random_mode
from agents.studio_compositor.transition_primitives import (
    DITHER_FLIPS,
    FADE_STEPS,
    MIN_TRANSITION_BRIGHTNESS,
    NETSPLIT_IN_STEPS,
    NETSPLIT_OUT_STEPS,
    PRIMITIVES,
    TICKER_STEPS,
    TRANSITION_NAMES,
    cut_hard,
    dither_noise,
    fade_smooth,
    netsplit_burst,
    ticker_scroll,
)


def _no_sleep(_seconds: float) -> None:
    return None


def _capture() -> tuple[list[dict], Callable[[dict], None]]:
    out: list[dict] = []
    return out, out.append


def _graph_with_brightness(brightness: float) -> dict:
    return {"nodes": {"cg": {"type": "colorgrade", "params": {"brightness": brightness}}}}


# ── primitive tests ────────────────────────────────────────────────────────


def test_fade_smooth_produces_24_steps_with_outgoing() -> None:
    captured, writer = _capture()
    fade_smooth(_graph_with_brightness(1.0), _graph_with_brightness(1.0), writer, _no_sleep)
    assert len(captured) == FADE_STEPS * 2  # out 12 + in 12


def test_fade_smooth_produces_12_steps_without_outgoing() -> None:
    captured, writer = _capture()
    fade_smooth(None, _graph_with_brightness(1.0), writer, _no_sleep)
    assert len(captured) == FADE_STEPS  # in only


def test_fade_smooth_brightness_descends_then_ascends() -> None:
    captured, writer = _capture()
    fade_smooth(_graph_with_brightness(1.0), _graph_with_brightness(1.0), writer, _no_sleep)
    out_phase = [g["nodes"]["cg"]["params"]["brightness"] for g in captured[:FADE_STEPS]]
    in_phase = [g["nodes"]["cg"]["params"]["brightness"] for g in captured[FADE_STEPS:]]
    assert out_phase == sorted(out_phase, reverse=True)
    assert in_phase == sorted(in_phase)
    assert out_phase[-1] == pytest.approx(MIN_TRANSITION_BRIGHTNESS)
    assert in_phase[-1] == pytest.approx(1.0)


def test_cut_hard_writes_exactly_once() -> None:
    captured, writer = _capture()
    cut_hard(_graph_with_brightness(1.0), _graph_with_brightness(1.0), writer, _no_sleep)
    assert len(captured) == 1
    assert captured[0]["nodes"]["cg"]["params"]["brightness"] == pytest.approx(1.0)


def test_cut_hard_works_without_outgoing_graph() -> None:
    captured, writer = _capture()
    cut_hard(None, _graph_with_brightness(1.0), writer, _no_sleep)
    assert len(captured) == 1


def test_netsplit_burst_emits_bounded_floor_hold() -> None:
    captured, writer = _capture()
    netsplit_burst(_graph_with_brightness(1.0), _graph_with_brightness(1.0), writer, _no_sleep)
    expected = NETSPLIT_OUT_STEPS + 1 + NETSPLIT_IN_STEPS
    assert len(captured) == expected
    # The middle write is a bounded floor pulse, never a black frame.
    assert captured[NETSPLIT_OUT_STEPS]["nodes"]["cg"]["params"]["brightness"] == pytest.approx(
        MIN_TRANSITION_BRIGHTNESS
    )


def test_ticker_scroll_uses_sigmoid_curve() -> None:
    captured, writer = _capture()
    ticker_scroll(_graph_with_brightness(1.0), _graph_with_brightness(1.0), writer, _no_sleep)
    assert len(captured) == TICKER_STEPS * 2
    in_phase = [g["nodes"]["cg"]["params"]["brightness"] for g in captured[TICKER_STEPS:]]
    # Sigmoid signature: midpoint sample is meaningfully above the linear
    # 0.5 line for the second half (steeper rise after midpoint).
    midpoint = in_phase[TICKER_STEPS // 2]
    # On a linear ramp, position 6/12 = 0.5. The sigmoid here is steeper
    # so the same position-index should be > 0.5.
    assert midpoint > 0.5


def test_dither_noise_alternates_then_settles() -> None:
    captured, writer = _capture()
    out = _graph_with_brightness(0.5)
    in_g = _graph_with_brightness(0.9)
    dither_noise(out, in_g, writer, _no_sleep)
    assert len(captured) == DITHER_FLIPS + 1  # flips + final settle
    # Final write must always be the incoming graph at full brightness
    assert captured[-1]["nodes"]["cg"]["params"]["brightness"] == pytest.approx(0.9)


def test_dither_noise_no_outgoing_only_writes_settle() -> None:
    captured, writer = _capture()
    dither_noise(None, _graph_with_brightness(1.0), writer, _no_sleep)
    assert len(captured) == 1


def test_primitives_registry_keys_match_transition_names() -> None:
    assert set(PRIMITIVES.keys()) == set(TRANSITION_NAMES)
    assert len(TRANSITION_NAMES) == 5


def test_primitive_outputs_are_pairwise_distinct() -> None:
    """Two different primitives must produce different mutation streams.

    This catches accidental aliasing if someone refactors a primitive
    into a thin wrapper around fade_smooth (which would silently
    collapse chain-level vocabulary back to the historical default).
    """
    out_g = _graph_with_brightness(1.0)
    in_g = _graph_with_brightness(1.0)
    streams: dict[str, list[float]] = {}
    for name, fn in PRIMITIVES.items():
        captured, writer = _capture()
        fn(out_g, in_g, writer, _no_sleep)
        streams[name] = [g["nodes"]["cg"]["params"]["brightness"] for g in captured]
    seen: set[tuple[float, ...]] = set()
    for name, stream in streams.items():
        sig = tuple(stream)
        assert sig not in seen, f"{name} produced an aliased mutation stream"
        seen.add(sig)


def test_transition_primitives_do_not_blank_colorgrade_brightness() -> None:
    out_g = _graph_with_brightness(1.0)
    in_g = _graph_with_brightness(1.0)
    for fn in PRIMITIVES.values():
        captured, writer = _capture()
        fn(out_g, in_g, writer, _no_sleep)
        brightnesses = [g["nodes"]["cg"]["params"]["brightness"] for g in captured]
        assert min(brightnesses) >= MIN_TRANSITION_BRIGHTNESS


# ── compositional_affordances catalog ──────────────────────────────────────


def test_transitions_registered_in_catalog() -> None:
    from shared.compositional_affordances import COMPOSITIONAL_CAPABILITIES, by_family

    transitions = by_family("transition")
    names = {c.name for c in transitions}
    assert names == set(TRANSITION_NAMES)
    # All must declare visual medium so the modality inference routes them
    # to the visual surface, not to the auditory or notification fan-out.
    for cap in transitions:
        assert cap.operational.medium == "visual"
    # And all must live in the global catalog (not a separate list).
    catalog_names = {c.name for c in COMPOSITIONAL_CAPABILITIES}
    assert set(TRANSITION_NAMES).issubset(catalog_names)


# ── random_mode selection wiring ───────────────────────────────────────────


def _shm_isolated(tmp_path: Path) -> Path:
    """Patch random_mode.SHM to a tmp dir for hermetic recruitment tests."""
    return tmp_path


def test_select_transition_falls_back_to_uniform_when_no_recruitment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(random_mode, "SHM", tmp_path)
    name, fn = random_mode._select_transition()
    assert name in TRANSITION_NAMES
    assert fn is PRIMITIVES[name]


def test_select_transition_prefers_recruited_transition_within_cooldown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(random_mode, "SHM", tmp_path)
    payload: dict[str, Any] = {
        "families": {
            "transition.netsplit.burst": {"last_recruited_ts": time.time()},
        }
    }
    (tmp_path / "recent-recruitment.json").write_text(json.dumps(payload), encoding="utf-8")
    name, fn = random_mode._select_transition()
    assert name == "transition.netsplit.burst"
    assert fn is netsplit_burst


def test_select_transition_ignores_stale_recruitment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(random_mode, "SHM", tmp_path)
    payload = {
        "families": {
            "transition.cut.hard": {
                # Older than the cooldown window
                "last_recruited_ts": time.time() - random_mode._TRANSITION_BIAS_COOLDOWN_S - 5,
            },
        }
    }
    (tmp_path / "recent-recruitment.json").write_text(json.dumps(payload), encoding="utf-8")
    # With a stale recruitment we fall back to uniform — patch random.choice
    # so the assertion is deterministic.
    with patch(
        "agents.studio_compositor.random_mode.random.choice", return_value="transition.fade.smooth"
    ):
        name, _ = random_mode._select_transition()
    assert name == "transition.fade.smooth"


def test_select_transition_picks_newest_when_multiple_recruited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(random_mode, "SHM", tmp_path)
    now = time.time()
    payload = {
        "families": {
            "transition.fade.smooth": {"last_recruited_ts": now - 5},
            "transition.dither.noise": {"last_recruited_ts": now - 1},
        }
    }
    (tmp_path / "recent-recruitment.json").write_text(json.dumps(payload), encoding="utf-8")
    name, _ = random_mode._select_transition()
    assert name == "transition.dither.noise"


def test_select_transition_ignores_unknown_capability_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(random_mode, "SHM", tmp_path)
    payload = {
        "families": {
            "transition.bogus.unknown": {"last_recruited_ts": time.time()},
        }
    }
    (tmp_path / "recent-recruitment.json").write_text(json.dumps(payload), encoding="utf-8")
    with patch(
        "agents.studio_compositor.random_mode.random.choice", return_value="transition.fade.smooth"
    ):
        name, _ = random_mode._select_transition()
    assert name == "transition.fade.smooth"


def test_random_mode_no_hardcoded_rotation() -> None:
    """Success criterion from plan §Phase 7: no ordered rotation lives
    in random_mode.py."""
    src = Path(random_mode.__file__).read_text(encoding="utf-8")
    # Catch any pattern like ``transition_idx = (transition_idx + 1) %``
    # or similar imperative cycling.
    forbidden = ["% len(TRANSITION_NAMES)", "transition_idx", "next_transition"]
    for token in forbidden:
        assert token not in src, f"hardcoded rotation token {token!r} found in random_mode.py"
