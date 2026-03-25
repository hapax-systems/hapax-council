"""Tests for enforced agent wrapper."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_run_enforced_passes_clean_output():
    from shared.governance.enforced_agent import run_enforced

    mock_result = MagicMock()
    mock_result.output = "System health is nominal."

    mock_agent = AsyncMock()
    mock_agent.run = AsyncMock(return_value=mock_result)

    with patch("shared.governance.enforced_agent.enforce_output") as mock_enforce:
        mock_enforce.return_value = MagicMock(allowed=True, violations=[])
        output = await run_enforced(mock_agent, "check health", agent_id="test")

    assert output == "System health is nominal."
    mock_enforce.assert_called_once()


@pytest.mark.asyncio
async def test_run_enforced_raises_on_t0_block():
    from shared.governance.enforced_agent import AxiomViolationError, run_enforced

    mock_result = MagicMock()
    mock_result.output = "I think Sarah should improve her communication skills."

    mock_agent = AsyncMock()
    mock_agent.run = AsyncMock(return_value=mock_result)

    violation = MagicMock(tier="T0", pattern_id="out-mg-feedback-001")
    with patch("shared.governance.enforced_agent.enforce_output") as mock_enforce:
        mock_enforce.return_value = MagicMock(allowed=False, violations=[violation])
        with pytest.raises(AxiomViolationError):
            await run_enforced(mock_agent, "generate feedback", agent_id="test")


@pytest.mark.asyncio
async def test_run_enforced_allows_structured_output():
    """Non-string outputs (Pydantic models) are serialized for checking."""
    from shared.governance.enforced_agent import run_enforced

    mock_model = MagicMock()
    mock_model.model_dump_json = MagicMock(return_value='{"summary": "all clear"}')

    mock_result = MagicMock()
    mock_result.output = mock_model

    mock_agent = AsyncMock()
    mock_agent.run = AsyncMock(return_value=mock_result)

    with patch("shared.governance.enforced_agent.enforce_output") as mock_enforce:
        mock_enforce.return_value = MagicMock(allowed=True, violations=[])
        output = await run_enforced(mock_agent, "check", agent_id="test")

    assert output is mock_model
