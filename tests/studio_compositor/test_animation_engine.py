"""Tests for the ward animation engine."""

from __future__ import annotations

import time

import pytest

from agents.studio_compositor import animation_engine as ae


@pytest.fixture(autouse=True)
def _redirect_path(monkeypatch, tmp_path):
    monkeypatch.setattr(ae, "WARD_ANIMATION_STATE_PATH", tmp_path / "ward-animation-state.json")
    ae.clear_animation_cache()
    yield
    ae.clear_animation_cache()


class TestEvaluateTransition:
    def test_zero_duration_returns_target_immediately(self):
        t = ae.Transition("w", "alpha", 0.0, 1.0, 0.0, "linear", time.time())
        assert ae.evaluate_transition(t, time.time()) == 1.0

    def test_progress_before_start_returns_from_value(self):
        now = time.time()
        t = ae.Transition("w", "alpha", 0.0, 1.0, 1.0, "linear", now + 5.0)
        assert ae.evaluate_transition(t, now) == 0.0

    def test_progress_after_end_returns_target(self):
        now = time.time()
        t = ae.Transition("w", "alpha", 0.0, 1.0, 0.5, "linear", now - 10.0)
        assert ae.evaluate_transition(t, now) == 1.0

    def test_linear_midpoint(self):
        now = time.time()
        t = ae.Transition("w", "alpha", 0.0, 1.0, 1.0, "linear", now)
        assert ae.evaluate_transition(t, now + 0.5) == pytest.approx(0.5)

    def test_ease_out_quad_midpoint(self):
        # ease-out-quad at progress=0.5 → 0.75 (1 - (1-0.5)^2)
        now = time.time()
        t = ae.Transition("w", "alpha", 0.0, 1.0, 1.0, "ease-out-quad", now)
        assert ae.evaluate_transition(t, now + 0.5) == pytest.approx(0.75)

    def test_unknown_easing_falls_back_to_linear(self):
        now = time.time()
        t = ae.Transition("w", "alpha", 0.0, 1.0, 1.0, "no-such-easing", now)
        assert ae.evaluate_transition(t, now + 0.5) == pytest.approx(0.5)


class TestIsExpired:
    def test_within_grace_window_not_expired(self):
        now = time.time()
        t = ae.Transition("w", "alpha", 0.0, 1.0, 0.5, "linear", now - 0.6)
        assert not ae.is_expired(t, now, grace_s=0.5)

    def test_past_grace_window_expired(self):
        now = time.time()
        t = ae.Transition("w", "alpha", 0.0, 1.0, 0.5, "linear", now - 2.0)
        assert ae.is_expired(t, now, grace_s=0.5)


class TestAppendAndEvaluate:
    def test_append_then_evaluate_returns_active_value(self):
        now = time.time()
        t = ae.Transition("album", "alpha", 0.0, 1.0, 1.0, "linear", now)
        ae.append_transitions([t])
        ae.clear_animation_cache()
        out = ae.evaluate_all(now=now + 0.5)
        assert out["album"]["alpha"] == pytest.approx(0.5)

    def test_unsupported_property_rejected_at_write(self):
        now = time.time()
        t = ae.Transition("album", "made_up_property", 0.0, 1.0, 1.0, "linear", now)
        ae.append_transitions([t])
        # File should be empty (or not exist, depending on filter timing)
        out = ae.evaluate_all(now=now + 0.5)
        assert "album" not in out

    def test_overlapping_transitions_latest_wins(self):
        now = time.time()
        first = ae.Transition("album", "alpha", 0.0, 0.5, 2.0, "linear", now - 0.1)
        ae.append_transitions([first])
        second = ae.Transition("album", "alpha", 0.0, 1.0, 2.0, "linear", now)
        ae.append_transitions([second])
        ae.clear_animation_cache()
        out = ae.evaluate_all(now=now + 1.0)
        # Second transition should win — its value at progress=0.5 = 0.5
        assert out["album"]["alpha"] == pytest.approx(0.5)

    def test_expired_entries_pruned_on_next_write(self):
        now = time.time()
        old = ae.Transition("album", "alpha", 0.0, 1.0, 0.1, "linear", now - 100.0)
        fresh = ae.Transition("album", "scale", 1.0, 1.2, 1.0, "linear", now)
        ae.append_transitions([old])
        ae.append_transitions([fresh])
        # File should have only one transition (the old one was pruned at second write)
        import json

        raw = json.loads(ae.WARD_ANIMATION_STATE_PATH.read_text())
        assert len(raw["transitions"]) == 1
        assert raw["transitions"][0]["property"] == "scale"


# ── Defensive _safe_load_raw — non-dict JSON root ──────────────────────


@pytest.mark.parametrize(
    "payload,kind",
    [("null", "null"), ('"a"', "string"), ("[1,2]", "list"), ("42", "int")],
)
def test_safe_load_raw_non_dict_returns_empty(tmp_path, payload, kind):
    """Pin _safe_load_raw against non-dict JSON roots. Two callers
    (publish_transitions, _load_active_transitions) call raw.get('transitions')
    immediately; non-dict root previously raised AttributeError."""
    ae.WARD_ANIMATION_STATE_PATH.write_text(payload)
    ae.clear_animation_cache()
    assert ae._safe_load_raw() == {}, f"non-dict root={kind} must yield {{}}"


@pytest.mark.parametrize(
    "payload,kind",
    [("null", "null"), ('"a"', "string"), ("[1,2]", "list"), ("42", "int")],
)
def test_publish_transitions_survives_corrupt_existing_state(tmp_path, payload, kind):
    """End-to-end: publish_transitions reads existing state via _safe_load_raw.
    A corrupt non-dict existing state must not crash the publish."""
    ae.WARD_ANIMATION_STATE_PATH.write_text(payload)
    ae.clear_animation_cache()
    # Must not raise — the corrupt file gets overwritten on first publish.
    now = time.time()
    fresh = ae.Transition("album", "alpha", 0.0, 1.0, 1.0, "linear", now)
    ae.append_transitions([fresh])
    # Verify the publish succeeded.
    import json

    raw = json.loads(ae.WARD_ANIMATION_STATE_PATH.read_text())
    assert "transitions" in raw
    assert any(t["property"] == "alpha" for t in raw["transitions"])
