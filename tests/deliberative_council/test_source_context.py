"""Tests for deliberative_council.source_context — source ref resolution."""

from __future__ import annotations

from pathlib import Path

from agents.deliberative_council.source_context import (
    populate_source_context,
    resolve_source_context,
)


def test_resolve_bare_file(tmp_path: Path) -> None:
    (tmp_path / "shared").mkdir()
    (tmp_path / "shared" / "config.py").write_text("# config\nfoo = 1\nbar = 2\n")
    result = resolve_source_context("shared/config.py", workspace_root=tmp_path)
    assert "foo = 1" in result
    assert "bar = 2" in result


def test_resolve_file_with_line(tmp_path: Path) -> None:
    (tmp_path / "agents").mkdir()
    lines = [f"line {i}" for i in range(1, 101)]
    (tmp_path / "agents" / "example.py").write_text("\n".join(lines))
    result = resolve_source_context("agents/example.py:50", workspace_root=tmp_path)
    assert "50: line 50" in result
    assert "31: line 31" in result  # window starts ~20 lines before


def test_resolve_file_with_line_range(tmp_path: Path) -> None:
    (tmp_path / "agents").mkdir()
    lines = [f"line {i}" for i in range(1, 101)]
    (tmp_path / "agents" / "example.py").write_text("\n".join(lines))
    result = resolve_source_context("agents/example.py:40-60", workspace_root=tmp_path)
    assert "40: line 40" in result
    assert "60: line 60" in result


def test_resolve_nonexistent_returns_empty(tmp_path: Path) -> None:
    result = resolve_source_context("nonexistent/file.py", workspace_root=tmp_path)
    assert result == ""


def test_resolve_truncates_large_files(tmp_path: Path) -> None:
    (tmp_path / "big.py").write_text("x" * 20000)
    result = resolve_source_context("big.py", workspace_root=tmp_path, max_chars=500)
    assert len(result) <= 520  # budget + truncation marker
    assert "[truncated]" in result


def test_populate_source_context_returns_content(tmp_path: Path) -> None:
    (tmp_path / "shared").mkdir()
    (tmp_path / "shared" / "stimmung.py").write_text("class SystemStimmung:\n    pass\n")
    result = populate_source_context(
        "The stimmung system tracks state",
        "shared/stimmung.py",
        workspace_root=tmp_path,
    )
    assert "SystemStimmung" in result
