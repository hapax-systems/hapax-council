"""Tests for HARDM communicative-anchoring (task #160).

Research doc: ``docs/research/hardm-communicative-anchoring.md``.

Pins:
- Salience bias math: voice → ≥0.5; SEEKING + guest consent → ≥0.7.
- Unskippable threshold (0.7) forces HARDM into the choreographer's
  pending-transitions queue every tick.
- TTS begin/end round-trip through ``write_emphasis`` /
  ``_read_emphasis_state``.
- ``parse_point_at_hardm`` string parser — valid, out-of-range, bogus.
- Operator-cue file write, director reads + deletes it.
- Brightness modulation: ``speaking`` emphasis brightens active cells,
  never idle (``muted``) cells.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import cairo
import pytest

from agents.studio_compositor import hardm_source as hs
from agents.studio_compositor.hardm_source import (
    BIAS_CONSENT_GUEST,
    BIAS_SELF_REFERENCE,
    BIAS_STANCE_SEEKING,
    BIAS_VOICE_ACTIVE,
    SURFACE_H,
    SURFACE_W,
    UNSKIPPABLE_BIAS,
    HardmDotMatrix,
    _read_emphasis_state,
    current_salience_bias,
    parse_point_at_hardm,
    should_force_hardm_in_rotation,
    write_emphasis,
    write_operator_cue,
)

# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def sandbox(monkeypatch, tmp_path):
    """Redirect every module-level path constant into tmp_path."""
    monkeypatch.setattr(hs, "VOICE_STATE_FILE", tmp_path / "voice-state.json")
    monkeypatch.setattr(hs, "HARDM_EMPHASIS_FILE", tmp_path / "hardm-emphasis.json")
    monkeypatch.setattr(hs, "STIMMUNG_STATE_FILE", tmp_path / "stimmung.json")
    monkeypatch.setattr(hs, "CONSENT_CONTRACTS_DIR", tmp_path / "contracts")
    monkeypatch.setattr(hs, "DIRECTOR_INTENT_JSONL", tmp_path / "director-intent.jsonl")
    monkeypatch.setattr(hs, "OPERATOR_CUE_FILE", tmp_path / "operator-cue.json")
    monkeypatch.setattr(hs, "SIGNAL_FILE", tmp_path / "hardm-cell-signals.json")
    (tmp_path / "contracts").mkdir()
    return tmp_path


def _set_hapax_emphasis(tmp_path: Path, state: str, *, age_s: float = 0.0) -> None:
    target = tmp_path / "hardm-emphasis.json"
    target.write_text(json.dumps({"emphasis": state, "ts": time.time() - age_s}))


def _set_operator_vad(tmp_path: Path, active: bool) -> None:
    (tmp_path / "voice-state.json").write_text(json.dumps({"operator_speech_active": active}))


def _set_stance(tmp_path: Path, stance: str) -> None:
    (tmp_path / "stimmung.json").write_text(json.dumps({"overall_stance": stance}))


def _add_guest_contract(tmp_path: Path, name: str = "guest-alice") -> None:
    (tmp_path / "contracts" / f"{name}.yaml").write_text("granted: true\n")


def _write_director_intent(tmp_path: Path, narrative: str) -> None:
    target = tmp_path / "director-intent.jsonl"
    target.write_text(json.dumps({"narrative_text": narrative}) + "\n")


# ── Salience bias math ──────────────────────────────────────────────────


class TestSalienceBias:
    def test_quiescent_is_zero(self, sandbox) -> None:
        bias = current_salience_bias(emit_metric=False)
        assert bias == 0.0

    def test_voice_active_adds_half(self, sandbox) -> None:
        _set_hapax_emphasis(sandbox, "speaking")
        bias = current_salience_bias(emit_metric=False)
        assert bias == pytest.approx(BIAS_VOICE_ACTIVE)

    def test_operator_vad_triggers_voice_bias(self, sandbox) -> None:
        _set_operator_vad(sandbox, True)
        bias = current_salience_bias(emit_metric=False)
        assert bias >= BIAS_VOICE_ACTIVE

    def test_seeking_stance_adds_contribution(self, sandbox) -> None:
        _set_stance(sandbox, "seeking")
        bias = current_salience_bias(emit_metric=False)
        assert bias == pytest.approx(BIAS_STANCE_SEEKING)

    def test_guest_consent_adds_contribution(self, sandbox) -> None:
        _add_guest_contract(sandbox)
        bias = current_salience_bias(emit_metric=False)
        assert bias == pytest.approx(BIAS_CONSENT_GUEST)

    def test_self_reference_adds_contribution(self, sandbox) -> None:
        _write_director_intent(sandbox, "Hapax thinks the grid is humming.")
        bias = current_salience_bias(emit_metric=False)
        assert bias == pytest.approx(BIAS_SELF_REFERENCE)

    def test_voice_plus_seeking_plus_guest_exceeds_threshold(self, sandbox) -> None:
        _set_hapax_emphasis(sandbox, "speaking")
        _set_stance(sandbox, "seeking")
        _add_guest_contract(sandbox)
        bias = current_salience_bias(emit_metric=False)
        # 0.5 + 0.2 + 0.2 = 0.9 > unskippable 0.7
        assert bias > UNSKIPPABLE_BIAS
        assert bias == pytest.approx(BIAS_VOICE_ACTIVE + BIAS_STANCE_SEEKING + BIAS_CONSENT_GUEST)

    def test_bias_caps_at_one(self, sandbox) -> None:
        _set_hapax_emphasis(sandbox, "speaking")
        _set_stance(sandbox, "seeking")
        _add_guest_contract(sandbox)
        _write_director_intent(sandbox, "I notice the stance has shifted.")
        bias = current_salience_bias(emit_metric=False)
        # 0.5 + 0.2 + 0.2 + 0.3 = 1.2 → clamped to 1.0.
        assert bias == pytest.approx(1.0)

    def test_stale_emphasis_not_counted(self, sandbox) -> None:
        _set_hapax_emphasis(sandbox, "speaking", age_s=10.0)
        bias = current_salience_bias(emit_metric=False)
        assert bias == 0.0

    def test_nominal_stance_not_counted(self, sandbox) -> None:
        _set_stance(sandbox, "nominal")
        bias = current_salience_bias(emit_metric=False)
        assert bias == 0.0

    def test_non_guest_contract_not_counted(self, sandbox) -> None:
        (sandbox / "contracts" / "operator.yaml").write_text("granted: true")
        bias = current_salience_bias(emit_metric=False)
        assert bias == 0.0


# ── Unskippable threshold ───────────────────────────────────────────────


class TestUnskippable:
    def test_should_force_below_threshold(self, sandbox) -> None:
        assert should_force_hardm_in_rotation(bias=0.5) is False

    def test_should_force_above_threshold(self, sandbox) -> None:
        assert should_force_hardm_in_rotation(bias=0.71) is True

    def test_should_force_at_threshold_is_false(self, sandbox) -> None:
        assert should_force_hardm_in_rotation(bias=0.7) is False

    def test_should_force_reads_live_bias_when_omitted(self, sandbox) -> None:
        _set_hapax_emphasis(sandbox, "speaking")
        _set_stance(sandbox, "seeking")
        _add_guest_contract(sandbox)
        assert should_force_hardm_in_rotation() is True


# ── Choreographer integration ───────────────────────────────────────────


class TestChoreographerIntegration:
    """When bias > 0.7 and no HARDM entry is pending, choreographer
    synthesizes one at the current salience score."""

    def test_synthesizes_when_bias_high(self, sandbox, monkeypatch, tmp_path) -> None:
        from agents.studio_compositor.homage import BITCHX_PACKAGE
        from agents.studio_compositor.homage.choreographer import Choreographer

        _set_hapax_emphasis(sandbox, "speaking")
        _set_stance(sandbox, "seeking")
        _add_guest_contract(sandbox)

        choreo = Choreographer(
            pending_file=tmp_path / "pending.json",
            uniforms_file=tmp_path / "uniforms.json",
            shader_reading_file=tmp_path / "shader.json",
            substrate_package_file=tmp_path / "substrate.json",
            consent_safe_flag_file=tmp_path / "consent-safe.json",
            voice_register_file=tmp_path / "voice-register.json",
            structural_intent_file=tmp_path / "structural-intent.json",
        )

        result = choreo.reconcile(BITCHX_PACKAGE, now=100.0)

        planned_ids = [p.source_id for p in result.planned]
        assert "hardm_dot_matrix" in planned_ids, (
            "Expected unskippable HARDM synthesis at bias > 0.7."
        )

    def test_no_synthesis_when_bias_low(self, sandbox, tmp_path) -> None:
        from agents.studio_compositor.homage import BITCHX_PACKAGE
        from agents.studio_compositor.homage.choreographer import Choreographer

        choreo = Choreographer(
            pending_file=tmp_path / "pending.json",
            uniforms_file=tmp_path / "uniforms.json",
            shader_reading_file=tmp_path / "shader.json",
            substrate_package_file=tmp_path / "substrate.json",
            consent_safe_flag_file=tmp_path / "consent-safe.json",
            voice_register_file=tmp_path / "voice-register.json",
            structural_intent_file=tmp_path / "structural-intent.json",
        )
        result = choreo.reconcile(BITCHX_PACKAGE, now=100.0)
        planned_ids = [p.source_id for p in result.planned]
        assert "hardm_dot_matrix" not in planned_ids


# ── TTS emphasis file round-trip ────────────────────────────────────────


class TestEmphasisRoundTrip:
    def test_write_speaking_then_read(self, sandbox) -> None:
        write_emphasis("speaking")
        assert _read_emphasis_state() == "speaking"

    def test_write_quiescent_then_read(self, sandbox) -> None:
        write_emphasis("quiescent")
        assert _read_emphasis_state() == "quiescent"

    def test_missing_file_is_quiescent(self, sandbox) -> None:
        assert _read_emphasis_state() == "quiescent"

    def test_stale_payload_is_quiescent(self, sandbox) -> None:
        _set_hapax_emphasis(sandbox, "speaking", age_s=10.0)
        assert _read_emphasis_state() == "quiescent"

    def test_production_stream_round_trip(self, sandbox) -> None:
        """ProductionStream.produce_t1 writes speaking → quiescent."""
        from agents.hapax_daimonion.cpal.production_stream import ProductionStream

        class _FakeOutput:
            writes: list[bytes] = []

            def write(self, pcm: bytes) -> None:
                type(self).writes.append(pcm)
                assert _read_emphasis_state() == "speaking"

        ps = ProductionStream(audio_output=_FakeOutput())
        ps.produce_t1(pcm_data=b"\x00" * 48)
        assert _read_emphasis_state() == "quiescent"

    def test_mark_t3_start_end_emphasis(self, sandbox) -> None:
        from agents.hapax_daimonion.cpal.production_stream import ProductionStream

        ps = ProductionStream()
        ps.mark_t3_start()
        assert _read_emphasis_state() == "speaking"
        ps.mark_t3_end()
        assert _read_emphasis_state() == "quiescent"

    def test_interrupt_resets_emphasis(self, sandbox) -> None:
        from agents.hapax_daimonion.cpal.production_stream import ProductionStream

        ps = ProductionStream()
        ps.mark_t3_start()
        assert _read_emphasis_state() == "speaking"
        ps.interrupt()
        assert _read_emphasis_state() == "quiescent"


# ── Sidechat parser ─────────────────────────────────────────────────────


class TestSidechatParser:
    def test_valid_cell_parses(self) -> None:
        assert parse_point_at_hardm("point-at-hardm 9") == 9

    def test_spaced_form_parses(self) -> None:
        assert parse_point_at_hardm("point at hardm 42") == 42

    def test_case_insensitive(self) -> None:
        assert parse_point_at_hardm("POINT-AT-HARDM 7") == 7

    def test_surrounding_whitespace_ok(self) -> None:
        assert parse_point_at_hardm("   point-at-hardm   5   ") == 5

    def test_cell_zero_valid(self) -> None:
        assert parse_point_at_hardm("point-at-hardm 0") == 0

    def test_cell_max_valid(self) -> None:
        assert parse_point_at_hardm("point-at-hardm 255") == 255

    def test_cell_out_of_range_rejected(self) -> None:
        assert parse_point_at_hardm("point-at-hardm 256") is None

    def test_non_integer_cell_rejected(self) -> None:
        assert parse_point_at_hardm("point-at-hardm banana") is None

    def test_missing_cell_rejected(self) -> None:
        assert parse_point_at_hardm("point-at-hardm") is None

    def test_non_hardm_command_returns_none(self) -> None:
        assert parse_point_at_hardm("link https://x.com") is None

    def test_empty_string(self) -> None:
        assert parse_point_at_hardm("") is None


class TestOperatorCueWrite:
    def test_write_populates_fields(self, sandbox) -> None:
        write_operator_cue(9)
        target = sandbox / "operator-cue.json"
        assert target.exists()
        payload = json.loads(target.read_text())
        assert payload["cue"] == "point-at-hardm"
        assert payload["cell"] == 9
        # cell 9 is in row 0 (since row = cell // 16 = 0). Row 0 = midi_active.
        assert payload["signal_name"] == "midi_active"

    def test_row_9_signal_name(self, sandbox) -> None:
        # Cell 150 → row 9 → director_stance
        write_operator_cue(150)
        payload = json.loads((sandbox / "operator-cue.json").read_text())
        assert payload["signal_name"] == "director_stance"


# ── Render-time brightness modulation ───────────────────────────────────


def _cell_pixel(surface, row, col):
    stride = surface.get_stride()
    data = surface.get_data()
    from agents.studio_compositor.hardm_source import CELL_SIZE_PX

    x = col * CELL_SIZE_PX + CELL_SIZE_PX // 2
    y = row * CELL_SIZE_PX + CELL_SIZE_PX // 2
    idx = y * stride + x * 4
    return (data[idx], data[idx + 1], data[idx + 2], data[idx + 3])


class TestBrightnessModulation:
    def test_speaking_brightens_active_cell(self, sandbox) -> None:
        """Row 0 = midi_active. Emphasis=speaking brightens the cyan
        channels relative to quiescent."""
        (sandbox / "hardm-cell-signals.json").write_text(
            json.dumps({"generated_at": time.time(), "signals": {"midi_active": True}})
        )

        surface_q = cairo.ImageSurface(cairo.FORMAT_ARGB32, SURFACE_W, SURFACE_H)
        HardmDotMatrix().render_content(
            cairo.Context(surface_q), SURFACE_W, SURFACE_H, t=0.0, state={}
        )
        q_b, q_g, q_r, _ = _cell_pixel(surface_q, 0, 5)

        write_emphasis("speaking")
        surface_s = cairo.ImageSurface(cairo.FORMAT_ARGB32, SURFACE_W, SURFACE_H)
        HardmDotMatrix().render_content(
            cairo.Context(surface_s), SURFACE_W, SURFACE_H, t=0.0, state={}
        )
        s_b, s_g, s_r, _ = _cell_pixel(surface_s, 0, 5)

        assert s_b >= q_b
        assert s_g >= q_g
        assert (s_b > q_b) or (s_g > q_g)

    def test_speaking_does_not_brighten_idle(self, sandbox) -> None:
        """Idle (muted) cells must NOT brighten — per-cell information
        content requires muted staying visibly muted."""
        (sandbox / "hardm-cell-signals.json").write_text(
            json.dumps({"generated_at": time.time(), "signals": {"midi_active": False}})
        )

        surface_q = cairo.ImageSurface(cairo.FORMAT_ARGB32, SURFACE_W, SURFACE_H)
        HardmDotMatrix().render_content(
            cairo.Context(surface_q), SURFACE_W, SURFACE_H, t=0.0, state={}
        )
        q = _cell_pixel(surface_q, 0, 5)

        write_emphasis("speaking")
        surface_s = cairo.ImageSurface(cairo.FORMAT_ARGB32, SURFACE_W, SURFACE_H)
        HardmDotMatrix().render_content(
            cairo.Context(surface_s), SURFACE_W, SURFACE_H, t=0.0, state={}
        )
        s = _cell_pixel(surface_s, 0, 5)

        assert s == q
