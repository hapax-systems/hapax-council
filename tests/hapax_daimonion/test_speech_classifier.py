from unittest.mock import AsyncMock

from agents.hapax_daimonion.speech_classifier import (
    BackchannelSignal,
    DuringProductionClassifier,
    FloorClaim,
)


def _fake_frames(duration_s: float = 0.5) -> list[bytes]:
    """Generate fake speech frames for given duration."""
    n_frames = int(duration_s / 0.03)  # 30ms per frame
    return [b"\x00\x01" * 480] * n_frames


class TestDuringProductionClassifier:
    async def test_backchannel_from_transcript(self):
        stt = AsyncMock(return_value="yeah")
        c = DuringProductionClassifier(stt=stt)
        result = await c.classify(_fake_frames(0.5))
        assert isinstance(result, BackchannelSignal)
        assert result.transcript == "yeah"

    async def test_floor_claim_from_transcript(self):
        stt = AsyncMock(return_value="actually I wanted to ask about the drift items")
        c = DuringProductionClassifier(stt=stt)
        result = await c.classify(_fake_frames(2.0))
        assert isinstance(result, FloorClaim)
        assert "drift" in result.transcript

    async def test_fallback_short_duration_is_backchannel(self):
        stt = AsyncMock(side_effect=TimeoutError)
        c = DuringProductionClassifier(stt=stt)
        result = await c.classify(_fake_frames(0.4))
        assert isinstance(result, BackchannelSignal)

    async def test_fallback_long_duration_is_floor_claim(self):
        stt = AsyncMock(side_effect=TimeoutError)
        c = DuringProductionClassifier(stt=stt)
        result = await c.classify(_fake_frames(1.5))
        assert isinstance(result, FloorClaim)

    async def test_empty_transcript_is_backchannel(self):
        stt = AsyncMock(return_value="")
        c = DuringProductionClassifier(stt=stt)
        result = await c.classify(_fake_frames(0.3))
        assert isinstance(result, BackchannelSignal)

    async def test_phatic_variations(self):
        c = DuringProductionClassifier(stt=AsyncMock())
        for token in ["mm-hm", "uh-huh", "okay", "right", "sure", "got it", "I see", "go on"]:
            c._stt.return_value = token
            result = await c.classify(_fake_frames(0.5))
            assert isinstance(result, BackchannelSignal), f"'{token}' should be backchannel"
