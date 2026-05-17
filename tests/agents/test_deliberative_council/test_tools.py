from __future__ import annotations

from pathlib import Path

import pytest

from agents.deliberative_council.members import ToolLevel, build_member
from agents.deliberative_council.tools import grep_evidence, read_source


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

    def test_none_tool_level_no_tools(self) -> None:
        agent = build_member("opus", ToolLevel.NONE)
        assert agent is not None
        assert agent._function_toolset.tools == {}
