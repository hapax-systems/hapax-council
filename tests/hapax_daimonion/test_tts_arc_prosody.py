"""Arc-level prosody for sustained hosting (segment-audio-remainder AC#3).

Hosting passes a segment ``role`` + ``arc_position`` into the synth request so
delivery can shape with position in the segment arc. The modulation is a
CONTINUOUS controller of expressiveness (exaggeration rises smoothly toward the
arc peak), not a per-beat preset table — bounded so delivery stays natural.
"""

from __future__ import annotations

import numpy as np

from agents.hapax_daimonion.tts import (
    _CHATTERBOX_EXAGGERATION,
    TTSManager,
    _arc_prosody,
)


def test_arc_prosody_none_returns_base() -> None:
    assert _arc_prosody(None, base_exag=0.5, base_cfg=0.3) == (0.5, 0.3)


def test_arc_prosody_expressiveness_rises_with_position() -> None:
    lo_exag, _ = _arc_prosody(0.0, base_exag=0.5, base_cfg=0.3)
    hi_exag, _ = _arc_prosody(1.0, base_exag=0.5, base_cfg=0.3)
    assert hi_exag > lo_exag


def test_arc_prosody_is_bounded_and_clamps_out_of_range_position() -> None:
    over, _ = _arc_prosody(5.0, base_exag=0.95, base_cfg=0.3)
    at_one, _ = _arc_prosody(1.0, base_exag=0.95, base_cfg=0.3)
    assert over == at_one  # clamped to 1.0
    assert 0.0 <= over <= 1.0  # exaggeration never leaves the valid range


def test_synthesize_forwards_role_and_arc_to_chatterbox(monkeypatch) -> None:  # noqa: ANN001
    mgr = TTSManager()
    mgr._backend = "chatterbox"
    seen: dict[str, object] = {}

    def _fake(text, *, interview_mode=False, role=None, arc_position=None):  # noqa: ANN001
        seen.update(text=text, role=role, arc_position=arc_position, interview_mode=interview_mode)
        return b"\x00\x00"

    monkeypatch.setattr(mgr, "_synthesize_chatterbox", _fake)
    mgr.synthesize("hello there", role="lecture", arc_position=0.7)

    assert seen["role"] == "lecture"
    assert seen["arc_position"] == 0.7


class _FakeWav:
    def squeeze(self):  # noqa: ANN201
        return self

    def cpu(self):  # noqa: ANN201
        return self

    def numpy(self):  # noqa: ANN201
        return np.array([0.1, 0.2, 0.1], dtype=np.float32)


def test_chatterbox_exaggeration_rises_with_arc_position(monkeypatch) -> None:  # noqa: ANN001
    mgr = TTSManager()
    mgr._backend = "chatterbox"
    captured: list[float] = []

    class _FakeModel:
        def generate(self, text, *, audio_prompt_path=None, exaggeration=None, cfg_weight=None):  # noqa: ANN001
            captured.append(exaggeration)
            return _FakeWav()

    monkeypatch.setattr(mgr, "_get_chatterbox", lambda: _FakeModel())

    mgr._synthesize_chatterbox("hi", arc_position=0.0)
    mgr._synthesize_chatterbox("hi", arc_position=1.0)

    assert captured[0] == _CHATTERBOX_EXAGGERATION  # arc 0 → base
    assert captured[1] > captured[0]  # arc peak → more expressive
