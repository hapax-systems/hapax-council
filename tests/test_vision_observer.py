"""Tests for the standalone vision observer."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from shared.fix_capabilities.background_admission import BackgroundCapabilityAdmission


@pytest.mark.asyncio
async def test_observe_writes_observation(tmp_path: Path):
    """Observer reads frame, calls LLM, writes observation to SHM."""
    frame_dir = tmp_path / "hapax-visual"
    frame_dir.mkdir()
    (frame_dir / "frame.jpg").write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")

    imagination_dir = tmp_path / "hapax-dmn"
    imagination_dir.mkdir()
    (imagination_dir / "imagination-current.json").write_text(
        json.dumps({"narrative": "warm drifting colors"})
    )

    output_dir = tmp_path / "hapax-vision"

    with patch(
        "agents.vision_observer.__main__._call_vision_model",
        new_callable=AsyncMock,
        return_value="soft amber gradients with gentle movement",
    ):
        from agents.vision_observer.__main__ import observe

        await observe(
            frame_path=frame_dir / "frame.jpg",
            imagination_path=imagination_dir / "imagination-current.json",
            output_dir=output_dir,
        )

    assert (output_dir / "observation.txt").exists()
    assert "amber" in (output_dir / "observation.txt").read_text()
    status = json.loads((output_dir / "status.json").read_text())
    assert "timestamp" in status


@pytest.mark.asyncio
async def test_observe_skips_missing_frame(tmp_path: Path):
    """Observer does nothing when frame.jpg is missing."""
    output_dir = tmp_path / "hapax-vision"

    from agents.vision_observer.__main__ import observe

    await observe(
        frame_path=tmp_path / "nonexistent.jpg",
        imagination_path=tmp_path / "also-missing.json",
        output_dir=output_dir,
    )

    assert not output_dir.exists() or not (output_dir / "observation.txt").exists()


@pytest.mark.asyncio
async def test_observe_tolerates_missing_imagination(tmp_path: Path):
    """Observer works with no imagination context — passes empty narrative."""
    frame_dir = tmp_path / "hapax-visual"
    frame_dir.mkdir()
    (frame_dir / "frame.jpg").write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")

    output_dir = tmp_path / "hapax-vision"

    with patch(
        "agents.vision_observer.__main__._call_vision_model",
        new_callable=AsyncMock,
        return_value="dark surface with faint noise",
    ) as mock_call:
        from agents.vision_observer.__main__ import observe

        await observe(
            frame_path=frame_dir / "frame.jpg",
            imagination_path=tmp_path / "nonexistent.json",
            output_dir=output_dir,
        )

    # Should have been called with empty narrative
    _, kwargs = mock_call.call_args
    assert kwargs.get("narrative") == "" or mock_call.call_args[0][1] == ""


@pytest.mark.asyncio
async def test_vision_model_call_refuses_without_admission():
    """Provider vision calls must not construct a client unless admission passes."""
    from agents.vision_observer.__main__ import _call_vision_model

    denied = BackgroundCapabilityAdmission(
        capability_name="vision_observer.surface_description.llm",
        route_id="api.headless.provider_gateway",
        model_alias="gemini-flash",
        admitted=False,
        denied_reason="provider_model_descriptor_mismatch",
        reason_codes=("provider_model_descriptor_mismatch",),
        mutation_surface="provider_spend",
        quality_floor="frontier_required",
    )
    with (
        patch("agents.vision_observer.__main__.admit_background_capability", return_value=denied),
        patch("openai.AsyncOpenAI") as mock_client_cls,
    ):
        result = await _call_vision_model("ZmFrZQ==", "")

    assert result == ""
    mock_client_cls.assert_not_called()
