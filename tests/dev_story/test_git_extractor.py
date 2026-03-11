"""Tests for git history extraction."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agents.dev_story.git_extractor import (
    extract_commits,
    parse_log_line,
    parse_numstat_line,
)


def test_parse_log_line_standard():
    line = "abc123|2026-03-10 10:00:00 -0500|feat: add something"
    commit = parse_log_line(line)
    assert commit is not None
    assert commit.hash == "abc123"
    assert commit.author_date == "2026-03-10 10:00:00 -0500"
    assert commit.message == "feat: add something"


def test_parse_log_line_with_pipe_in_message():
    line = "abc123|2026-03-10 10:00:00 -0500|feat: add x | y support"
    commit = parse_log_line(line)
    assert commit.message == "feat: add x | y support"


def test_parse_log_line_malformed():
    assert parse_log_line("not a valid line") is None
    assert parse_log_line("") is None


def test_parse_numstat_line_standard():
    line = "15\t3\tshared/config.py"
    result = parse_numstat_line(line)
    assert result is not None
    insertions, deletions, path = result
    assert insertions == 15
    assert deletions == 3
    assert path == "shared/config.py"


def test_parse_numstat_line_binary():
    line = "-\t-\timage.png"
    result = parse_numstat_line(line)
    assert result is not None
    insertions, deletions, path = result
    assert insertions == 0
    assert deletions == 0


def test_parse_numstat_line_empty():
    assert parse_numstat_line("") is None
    assert parse_numstat_line("\n") is None


@patch("agents.dev_story.git_extractor.subprocess.run")
def test_extract_commits_parses_output(mock_run):
    mock_run.return_value = MagicMock(
        stdout=(
            "abc123|2026-03-10 10:00:00 -0500|feat: add something\n"
            "5\t2\tshared/config.py\n"
            "10\t0\tagents/foo.py\n"
            "\n"
            "def456|2026-03-10 10:05:00 -0500|fix: broken thing\n"
            "3\t1\tagents/foo.py\n"
            "\n"
        ),
        returncode=0,
    )
    commits, files = extract_commits("/tmp/repo")
    assert len(commits) == 2
    assert commits[0].hash == "abc123"
    assert commits[0].files_changed == 2
    assert commits[0].insertions == 15
    assert commits[0].deletions == 2
    assert len(files) == 3
    assert files[0].file_path == "shared/config.py"
    assert files[0].operation == "M"


@patch("agents.dev_story.git_extractor.subprocess.run")
def test_extract_commits_with_since(mock_run):
    mock_run.return_value = MagicMock(stdout="", returncode=0)
    extract_commits("/tmp/repo", since="2026-03-01")
    cmd = mock_run.call_args[0][0]
    assert "--since=2026-03-01" in cmd


@patch("agents.dev_story.git_extractor.subprocess.run")
def test_extract_commits_handles_empty_output(mock_run):
    mock_run.return_value = MagicMock(stdout="", returncode=0)
    commits, files = extract_commits("/tmp/repo")
    assert commits == []
    assert files == []
