from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.messages import CachePoint, UserPromptPart

from agents.deliberative_council.members import (
    MODEL_TOOL_LEVELS,
    CCTVLiteLLMChatModel,
    ToolLevel,
    build_member,
    cache_control_ttl_for_alias,
    cache_policy_for_alias,
    model_settings_for_alias,
    normalize_model_alias,
)
from agents.deliberative_council.tools import (
    FULL_TOOLS,
    RESTRICTED_TOOLS,
    git_diff,
    git_provenance,
    grep_evidence,
    qdrant_lookup,
    read_source,
    vault_read,
    web_verify,
)


class TestReadSource:
    @pytest.mark.asyncio
    async def test_existing_file(self, tmp_path: Path) -> None:
        f = tmp_path / "test.md"
        f.write_text("hello world")
        result = await read_source(None, str(f))
        assert "hello world" in result

    @pytest.mark.asyncio
    async def test_missing_file_graceful(self) -> None:
        result = await read_source(None, "/nonexistent/zzzz/path.md")
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_truncates_long_files(self, tmp_path: Path) -> None:
        f = tmp_path / "big.md"
        f.write_text("x" * 10000)
        result = await read_source(None, str(f))
        assert len(result) <= 4200


class TestGrepEvidence:
    @pytest.mark.asyncio
    async def test_finds_pattern(self) -> None:
        result = await grep_evidence(None, "get_model", "shared")
        assert "get_model" in result or "config.py" in result

    @pytest.mark.asyncio
    async def test_no_match_graceful(self) -> None:
        result = await grep_evidence(None, "zzz_nonexistent_pattern_zzz", "shared")
        assert "no match" in result.lower() or result.strip() == ""


class TestGitProvenance:
    @pytest.mark.asyncio
    async def test_returns_metadata(self) -> None:
        result = await git_provenance(None, "shared/config.py")
        assert result.strip() != ""
        assert "No git history" not in result

    @pytest.mark.asyncio
    async def test_missing_file_graceful(self) -> None:
        result = await git_provenance(None, "nonexistent_zzz.py")
        assert "No git history" in result or result.strip() == ""


class TestWebVerify:
    @pytest.mark.asyncio
    async def test_routes_through_perplexity(self) -> None:
        mock_result = MagicMock()
        mock_result.output = "Verified: claim is supported"
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value=mock_result)
        with (
            patch("pydantic_ai.Agent", return_value=mock_agent),
            patch("shared.config.get_model") as mock_get_model,
        ):
            result = await web_verify(None, "test claim")
            mock_get_model.assert_called_once_with("web-research")
            assert "Verified" in result

    @pytest.mark.asyncio
    async def test_times_out_gracefully(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A slow Perplexity provider must degrade to "no external evidence", never
        # starve the member's research budget into the TimeoutError cascade
        # (verified diagnosis 2026-06-14).
        import agents.deliberative_council.tools as tools_mod

        monkeypatch.setattr(tools_mod, "_WEB_VERIFY_TIMEOUT_S", 0.05)

        async def _hang(*_a: object, **_k: object) -> object:
            import asyncio

            await asyncio.sleep(5)
            return MagicMock()

        mock_agent = MagicMock()
        mock_agent.run = _hang
        with (
            patch("pydantic_ai.Agent", return_value=mock_agent),
            patch("shared.config.get_model"),
        ):
            result = await web_verify(None, "slow claim")
        assert "timed out" in result.lower()


class TestQdrantLookup:
    @pytest.mark.asyncio
    async def test_returns_results(self) -> None:
        mock_result = MagicMock()
        mock_result.score = 0.85
        mock_result.payload = {"text": "relevant content here"}
        mock_client = MagicMock()
        mock_client.search.return_value = [mock_result]
        with (
            patch("shared.config.embed", return_value=[0.1] * 768),
            patch("qdrant_client.QdrantClient", return_value=mock_client),
        ):
            result = await qdrant_lookup(None, "test query")
            assert "0.85" in result
            assert "relevant content" in result

    @pytest.mark.asyncio
    async def test_error_graceful(self) -> None:
        with patch("shared.config.embed", side_effect=ConnectionError("down")):
            result = await qdrant_lookup(None, "test")
            assert "error" in result.lower()


class TestVaultRead:
    @pytest.mark.asyncio
    async def test_returns_content(self, tmp_path: Path) -> None:
        note = tmp_path / "test-note.md"
        note.write_text("# Test Note\nContent here")
        with patch("agents.deliberative_council.tools.VAULT_DIR", tmp_path):
            result = await vault_read(None, "test-note.md")
            assert "Test Note" in result
            assert "Content here" in result

    @pytest.mark.asyncio
    async def test_missing_note_graceful(self) -> None:
        result = await vault_read(None, "nonexistent/zzz.md")
        assert "not found" in result.lower()


class TestBuildMember:
    def test_full_tool_level(self) -> None:
        agent = build_member("opus", ToolLevel.FULL)
        assert agent is not None

    def test_restricted_tool_level(self) -> None:
        agent = build_member("local-fast", ToolLevel.RESTRICTED)
        assert agent is not None

    def test_default_tool_level_for_local(self) -> None:
        agent = build_member("local-fast")
        assert agent is not None

    def test_command_r_restricted_toolset(self) -> None:
        assert MODEL_TOOL_LEVELS.get("local-fast") == ToolLevel.RESTRICTED

    def test_tool_counts(self) -> None:
        assert git_diff in FULL_TOOLS

    def test_legacy_cctv_aliases_normalize_to_canonical_routes(self) -> None:
        assert normalize_model_alias("claude-opus") == "opus"
        assert normalize_model_alias("claude-sonnet") == "balanced"
        assert normalize_model_alias("gemini-pro") == "gemini-3-pro"

    def test_cache_policy_is_family_gated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HAPAX_CCTV_PROMPT_CACHE", raising=False)
        assert cache_control_ttl_for_alias("opus") == "5m"
        assert cache_control_ttl_for_alias("gemini-3-pro") == "300s"
        assert cache_control_ttl_for_alias("local-fast") is None
        assert cache_control_ttl_for_alias("web-research") is None
        assert cache_control_ttl_for_alias("mistral-large") is None
        assert cache_policy_for_alias("gemini-3-pro")["cache_control_ttl"] == "300s"
        assert cache_policy_for_alias("gemini-3-pro")["cache_control_ttl_setting"] == "5m"

    def test_cache_policy_normalizes_one_hour_ttl(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HAPAX_CCTV_PROMPT_CACHE", raising=False)
        monkeypatch.setenv("HAPAX_CCTV_PROMPT_CACHE_TTL", "1h")
        assert cache_control_ttl_for_alias("opus") == "1h"
        assert cache_control_ttl_for_alias("gemini-3-pro") == "3600s"
        assert cache_policy_for_alias("gemini-3-pro")["cache_control_ttl"] == "3600s"
        assert cache_policy_for_alias("gemini-3-pro")["cache_control_ttl_setting"] == "1h"

    def test_cache_policy_can_be_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HAPAX_CCTV_PROMPT_CACHE", "0")
        assert cache_control_ttl_for_alias("opus") is None
        assert cache_policy_for_alias("opus")["cache_control"] is False
        assert cache_policy_for_alias("opus")["cache_control_ttl_setting"] is None

    def test_openai_cache_settings_only_for_openai_family(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agents.deliberative_council import members

        monkeypatch.setitem(members.MODEL_FAMILIES, "openai-reviewer", "openai")
        monkeypatch.setenv("HAPAX_CCTV_OPENAI_PROMPT_CACHE_RETENTION", "24h")

        settings = model_settings_for_alias("openai-reviewer")

        assert settings == {
            "openai_prompt_cache_key": "cctv-deliberative-council:openai-reviewer",
            "openai_prompt_cache_retention": "24h",
        }
        assert model_settings_for_alias("opus") == {}

    @pytest.mark.asyncio
    async def test_litellm_model_maps_cache_point_to_previous_text_block(self) -> None:
        from pydantic_ai.providers.litellm import LiteLLMProvider

        model = CCTVLiteLLMChatModel(
            "claude-sonnet",
            provider=LiteLLMProvider(api_base="http://litellm.invalid", api_key="test"),
        )
        part = UserPromptPart(
            content=(
                "stable rubric prefix",
                CachePoint(ttl="1h"),
                "dynamic claim material",
            )
        )

        mapped = await model._map_user_prompt(part)

        assert mapped["content"][0]["text"] == "stable rubric prefix"
        assert mapped["content"][0]["cache_control"] == {
            "type": "ephemeral",
            "ttl": "1h",
        }
        assert mapped["content"][1]["text"] == "dynamic claim material"
        assert "cache_control" not in mapped["content"][1]
        assert len(FULL_TOOLS) == 7
        assert len(RESTRICTED_TOOLS) == 2

    def test_none_tool_level_no_tools(self) -> None:
        agent = build_member("opus", ToolLevel.NONE)
        assert agent is not None
        assert agent._function_toolset.tools == {}
