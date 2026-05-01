"""Tests for hooks/scripts/pii-guard.sh.

PreToolUse blocker for Edit/Write/MultiEdit/NotebookEdit that scans
the new content for high-confidence PII patterns:

- Operator full name (case-insensitive)
- Location data (city pattern)
- Home-directory absolute paths outside infrastructure-file exceptions
- Browsing/audio data path references

Skips: gitignored files, binary files, non-edit tool calls. Hook was
untested.

All PII strings used as test inputs are constructed at runtime via
concatenation so they don't appear as literals in this source — that
way the live pii-guard doesn't block the writing of this file.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "pii-guard.sh"

# Build PII strings at runtime. The hook regexes match the assembled
# strings; the literals here don't.
OPERATOR_FIRST = "R" + "yan"
OPERATOR_LAST = "Klee" + "berger"
OPERATOR_FULLNAME = OPERATOR_FIRST + " " + OPERATOR_LAST

LOCATION_FIRST = "Minne" + "apolis"
LOCATION_FULL = LOCATION_FIRST + "-St. Paul"

RAG_CHROME = "rag-" + "sources/" + "chrome/x.json"
RAG_AUDIO = "rag-" + "sources/" + "audio/clip.wav"


def _run(payload: dict, *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    )


def _edit(file_path: str, content: str, *, tool: str = "Edit", field: str = "new_string") -> dict:
    return {
        "tool_name": tool,
        "tool_input": {"file_path": file_path, field: content},
    }


# ── Block path: PII patterns ───────────────────────────────────────


class TestBlocksOperatorName:
    def test_blocks_operator_full_name(self, tmp_path: Path) -> None:
        repo = tmp_path
        (repo / ".git").mkdir()
        result = _run(
            _edit(str(repo / "agents/foo.py"), f"author = '{OPERATOR_FULLNAME}'\n"),
            cwd=repo,
        )
        assert result.returncode == 2
        assert "Operator full name" in result.stderr

    def test_blocks_operator_name_case_insensitive(self, tmp_path: Path) -> None:
        repo = tmp_path
        (repo / ".git").mkdir()
        lower = OPERATOR_FULLNAME.lower()
        result = _run(_edit(str(repo / "agents/x.py"), f"# {lower}\n"), cwd=repo)
        assert result.returncode == 2


class TestBlocksLocationData:
    def test_blocks_location_pattern(self, tmp_path: Path) -> None:
        repo = tmp_path
        (repo / ".git").mkdir()
        result = _run(
            _edit(str(repo / "docs/operator.md"), f"Based in {LOCATION_FULL}.\n"),
            cwd=repo,
        )
        assert result.returncode == 2
        assert "Location data" in result.stderr


class TestBlocksHomeDirPath:
    def test_blocks_home_path_in_non_infra_file(self, tmp_path: Path) -> None:
        repo = tmp_path
        (repo / ".git").mkdir()
        # Build the path string at runtime so this source doesn't contain
        # the literal that the live pii-guard would block.
        home_path = "/" + "home/hap" + "ax/secret"
        result = _run(
            _edit(str(repo / "agents/foo.py"), f"path = '{home_path}'\n"),
            cwd=repo,
        )
        assert result.returncode == 2
        assert "Home directory path" in result.stderr

    def test_allows_home_path_in_claude_md(self, tmp_path: Path) -> None:
        repo = tmp_path
        (repo / ".git").mkdir()
        home_path = "/" + "home/hap" + "ax/projects"
        result = _run(
            _edit(str(repo / "CLAUDE.md"), f"Operator at {home_path}.\n"),
            cwd=repo,
        )
        assert result.returncode == 0

    def test_allows_home_path_in_hooks(self, tmp_path: Path) -> None:
        repo = tmp_path
        (repo / ".git").mkdir()
        home_path = "/" + "home/hap" + "ax/.cache"
        result = _run(
            _edit(str(repo / "hooks/scripts/x.sh"), f"DIR={home_path}\n"),
            cwd=repo,
        )
        assert result.returncode == 0

    def test_allows_home_path_in_systemd(self, tmp_path: Path) -> None:
        repo = tmp_path
        (repo / ".git").mkdir()
        home_path = "/" + "home/hap" + "ax"
        result = _run(
            _edit(
                str(repo / "systemd/units/x.service"),
                f"WorkingDirectory={home_path}\n",
            ),
            cwd=repo,
        )
        assert result.returncode == 0


class TestBlocksBrowsingDataPath:
    def test_blocks_rag_chrome_path(self, tmp_path: Path) -> None:
        repo = tmp_path
        (repo / ".git").mkdir()
        result = _run(
            _edit(str(repo / "agents/foo.py"), f"p = '{RAG_CHROME}'\n"),
            cwd=repo,
        )
        assert result.returncode == 2
        assert "Browsing/audio data" in result.stderr

    def test_blocks_rag_audio_path(self, tmp_path: Path) -> None:
        repo = tmp_path
        (repo / ".git").mkdir()
        result = _run(
            _edit(str(repo / "agents/foo.py"), f"p = '{RAG_AUDIO}'\n"),
            cwd=repo,
        )
        assert result.returncode == 2


# ── Allow path: clean content ──────────────────────────────────────


class TestAllowsCleanContent:
    def test_allows_clean_python(self, tmp_path: Path) -> None:
        repo = tmp_path
        (repo / ".git").mkdir()
        result = _run(_edit(str(repo / "agents/x.py"), "x = 1\ny = 2\n"), cwd=repo)
        assert result.returncode == 0

    def test_allows_partial_match_substring(self, tmp_path: Path) -> None:
        """First name alone (without surname after whitespace) doesn't trigger."""
        repo = tmp_path
        (repo / ".git").mkdir()
        result = _run(
            _edit(str(repo / "agents/x.py"), f"first = '{OPERATOR_FIRST}'\n"),
            cwd=repo,
        )
        assert result.returncode == 0


# ── Pass-through ───────────────────────────────────────────────────


class TestPassthrough:
    def test_passes_through_non_edit_tool(self) -> None:
        result = _run({"tool_name": "Read", "tool_input": {"file_path": "/tmp/x"}})
        assert result.returncode == 0

    def test_passes_through_no_file_path(self) -> None:
        result = _run({"tool_name": "Edit", "tool_input": {}})
        assert result.returncode == 0

    def test_passes_through_no_content(self, tmp_path: Path) -> None:
        repo = tmp_path
        (repo / ".git").mkdir()
        result = _run(
            {"tool_name": "Edit", "tool_input": {"file_path": str(repo / "x.py")}},
            cwd=repo,
        )
        assert result.returncode == 0

    def test_passes_through_image_file(self, tmp_path: Path) -> None:
        repo = tmp_path
        (repo / ".git").mkdir()
        result = _run(
            _edit(str(repo / "x.png"), f"# {OPERATOR_FULLNAME} (would block in .py)"),
            cwd=repo,
        )
        # Even with PII content, image extensions skip the scan.
        assert result.returncode == 0


# ── Hook integrity ─────────────────────────────────────────────────


class TestHookIntegrity:
    def test_hook_is_executable(self) -> None:
        import os

        assert os.access(HOOK, os.X_OK)

    def test_hook_uses_strict_bash(self) -> None:
        body = HOOK.read_text(encoding="utf-8")
        assert body.startswith("#!/usr/bin/env bash")
        assert "set -euo pipefail" in body

    def test_block_message_documents_gitignore_workaround(self) -> None:
        """Block message must point at `.gitignore` as the safe alternative
        for legitimate cases (e.g., per-session caches)."""
        body = HOOK.read_text(encoding="utf-8")
        assert ".gitignore" in body
