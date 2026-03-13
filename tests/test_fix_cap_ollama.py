"""Tests for shared.fix_capabilities.ollama_cap — Ollama capability module."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from shared.fix_capabilities.base import (
    Capability,
    ExecutionResult,
    FixProposal,
    ProbeResult,
    Safety,
)
from shared.fix_capabilities.ollama_cap import OllamaCapability


@pytest.fixture
def cap() -> OllamaCapability:
    return OllamaCapability()


# ── Metadata ─────────────────────────────────────────────────────────────────


class TestOllamaCapabilityMetadata:
    def test_name(self, cap: OllamaCapability) -> None:
        assert cap.name == "ollama"

    def test_check_groups(self, cap: OllamaCapability) -> None:
        assert cap.check_groups == {"gpu", "models"}

    def test_is_capability(self, cap: OllamaCapability) -> None:
        assert isinstance(cap, Capability)


# ── Probe (gather_context) ───────────────────────────────────────────────────


class TestOllamaProbe:
    @pytest.mark.asyncio
    async def test_gather_context_success(self, cap: OllamaCapability) -> None:
        """When Ollama API responds 200 with models, probe returns them."""
        api_response = json.dumps(
            {
                "models": [
                    {"name": "qwen2.5-coder:32b", "size": 18_000_000_000},
                    {"name": "deepseek-r1:14b", "size": 9_000_000_000},
                ]
            }
        )
        with patch(
            "shared.fix_capabilities.ollama_cap.http_get",
            new_callable=AsyncMock,
            return_value=(200, api_response),
        ):
            result = await cap.gather_context(None)

        assert isinstance(result, ProbeResult)
        assert result.capability == "ollama"
        assert len(result.raw["models"]) == 2
        assert result.raw["models"][0]["name"] == "qwen2.5-coder:32b"
        assert result.raw["models"][1]["name"] == "deepseek-r1:14b"
        assert "error" not in result.raw

    @pytest.mark.asyncio
    async def test_gather_context_unreachable(self, cap: OllamaCapability) -> None:
        """When Ollama is unreachable, probe returns empty models + error."""
        with patch(
            "shared.fix_capabilities.ollama_cap.http_get",
            new_callable=AsyncMock,
            return_value=(0, "Connection refused"),
        ):
            result = await cap.gather_context(None)

        assert isinstance(result, ProbeResult)
        assert result.capability == "ollama"
        assert result.raw["models"] == []
        assert "error" in result.raw
        assert "Connection refused" in result.raw["error"]


# ── Actions ──────────────────────────────────────────────────────────────────


class TestOllamaActions:
    def test_available_actions(self, cap: OllamaCapability) -> None:
        actions = cap.available_actions()
        assert len(actions) == 2
        names = {a.name for a in actions}
        assert names == {"stop_model", "pull_model"}
        for a in actions:
            assert a.safety == Safety.SAFE

    def test_validate_stop_model_valid(self, cap: OllamaCapability) -> None:
        proposal = FixProposal(
            capability="ollama",
            action_name="stop_model",
            params={"model_name": "qwen2.5-coder:32b"},
            safety=Safety.SAFE,
        )
        assert cap.validate(proposal) is True

    def test_validate_unknown_action(self, cap: OllamaCapability) -> None:
        proposal = FixProposal(
            capability="ollama",
            action_name="restart_model",
            params={"model_name": "qwen2.5-coder:32b"},
            safety=Safety.SAFE,
        )
        assert cap.validate(proposal) is False

    def test_validate_missing_param(self, cap: OllamaCapability) -> None:
        proposal = FixProposal(
            capability="ollama",
            action_name="stop_model",
            params={},
            safety=Safety.SAFE,
        )
        assert cap.validate(proposal) is False


# ── Execute ──────────────────────────────────────────────────────────────────


class TestOllamaExecute:
    @pytest.mark.asyncio
    async def test_execute_stop_model_success(self, cap: OllamaCapability) -> None:
        proposal = FixProposal(
            capability="ollama",
            action_name="stop_model",
            params={"model_name": "qwen2.5-coder:32b"},
            safety=Safety.SAFE,
        )
        with patch(
            "shared.fix_capabilities.ollama_cap.run_cmd",
            new_callable=AsyncMock,
            return_value=(0, "model stopped", ""),
        ) as mock_cmd:
            result = await cap.execute(proposal)

        assert isinstance(result, ExecutionResult)
        assert result.success is True
        assert "qwen2.5-coder:32b" in result.message
        mock_cmd.assert_called_once_with(
            ["docker", "exec", "ollama", "ollama", "stop", "qwen2.5-coder:32b"],
            timeout=30.0,
        )

    @pytest.mark.asyncio
    async def test_execute_stop_model_failure(self, cap: OllamaCapability) -> None:
        proposal = FixProposal(
            capability="ollama",
            action_name="stop_model",
            params={"model_name": "qwen2.5-coder:32b"},
            safety=Safety.SAFE,
        )
        with patch(
            "shared.fix_capabilities.ollama_cap.run_cmd",
            new_callable=AsyncMock,
            return_value=(1, "", "model not found"),
        ):
            result = await cap.execute(proposal)

        assert isinstance(result, ExecutionResult)
        assert result.success is False
        assert "model not found" in result.message or "model not found" in result.output
