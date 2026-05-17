from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.deliberative_council.members import MODEL_TOOL_LEVELS, ToolLevel, build_member
from agents.deliberative_council.tools import (
    FULL_TOOLS,
    RESTRICTED_TOOLS,
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
        assert len(FULL_TOOLS) == 6
        assert len(RESTRICTED_TOOLS) == 2
