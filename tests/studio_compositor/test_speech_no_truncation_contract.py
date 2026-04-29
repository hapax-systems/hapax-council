"""Speech completeness regressions for studio compositor speech paths."""

from __future__ import annotations

from agents.studio_compositor.director_loop import DirectorLoop


class _FakeTtsClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def synthesize(self, text: str, use_case: str) -> bytes:
        self.calls.append((text, use_case))
        return b"pcm"


def test_director_synthesize_passes_full_long_react_text_to_tts() -> None:
    director = DirectorLoop.__new__(DirectorLoop)
    fake_tts = _FakeTtsClient()
    director._tts_client = fake_tts
    long_text = " ".join(f"word{i}" for i in range(120))

    assert director._synthesize(long_text) == b"pcm"

    assert fake_tts.calls == [(long_text, "conversation")]
    spoken_text, _use_case = fake_tts.calls[0]
    assert "..." not in spoken_text
    assert "…" not in spoken_text
