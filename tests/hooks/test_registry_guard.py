"""Tests for hooks/scripts/registry-guard.sh.

PreToolUse blocker for edits to protected constitutional files:
``axioms/registry.yaml`` and any ``domains/**/.yaml``. These files
encode constitutional state that must go through human review; the
hook prevents automated sessions from modifying them.

The hook was untested.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "registry-guard.sh"


def _run(payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )


def _edit(file_path: str, *, tool: str = "Edit") -> dict:
    return {"tool_name": tool, "tool_input": {"file_path": file_path}}


# ── Block path: protected constitutional files ─────────────────────


class TestBlocksRegistry:
    def test_blocks_axioms_registry_absolute(self) -> None:
        result = _run(_edit("/home/hapax/projects/hapax-council/axioms/registry.yaml"))
        assert result.returncode == 2
        assert "BLOCKED" in result.stderr
        assert "axioms/registry.yaml" in result.stderr

    def test_blocks_axioms_registry_relative(self) -> None:
        result = _run(_edit("axioms/registry.yaml"))
        assert result.returncode == 2

    def test_blocks_axioms_registry_in_worktree(self) -> None:
        """Worktrees prefix paths like `hapax-council--zeta/axioms/registry.yaml`;
        the hook must catch the trailing pattern regardless of prefix."""
        result = _run(_edit("/home/hapax/projects/hapax-council--zeta/axioms/registry.yaml"))
        assert result.returncode == 2

    def test_blocks_with_write_tool(self) -> None:
        result = _run(_edit("axioms/registry.yaml", tool="Write"))
        assert result.returncode == 2

    def test_blocks_with_multiedit_tool(self) -> None:
        result = _run(_edit("axioms/registry.yaml", tool="MultiEdit"))
        assert result.returncode == 2


class TestBlocksDomains:
    def test_blocks_domains_yaml_top_level(self) -> None:
        result = _run(_edit("domains/research.yaml"))
        assert result.returncode == 2
        assert "Domain axiom files" in result.stderr

    def test_blocks_domains_yaml_nested(self) -> None:
        result = _run(_edit("domains/sub/research.yaml"))
        assert result.returncode == 2

    def test_blocks_domains_yaml_absolute(self) -> None:
        result = _run(_edit("/home/hapax/projects/hapax-council/domains/x.yaml"))
        assert result.returncode == 2


# ── Allow path: not protected ──────────────────────────────────────


class TestAllows:
    def test_allows_axioms_subfile_other_than_registry(self) -> None:
        """`axioms/precedents/some.yaml` is NOT registry.yaml; only registry
        is gated."""
        result = _run(_edit("axioms/precedents/some-precedent.yaml"))
        assert result.returncode == 0
        assert result.stderr == ""

    def test_allows_axioms_implications_yaml(self) -> None:
        result = _run(_edit("axioms/implications/x.yaml"))
        assert result.returncode == 0

    def test_allows_axioms_md_file(self) -> None:
        """`axioms/something.md` is documentation, not registry."""
        result = _run(_edit("axioms/something.md"))
        assert result.returncode == 0

    def test_allows_domains_non_yaml(self) -> None:
        """`domains/research.md` is markdown, not yaml — not gated."""
        result = _run(_edit("domains/research.md"))
        assert result.returncode == 0

    def test_allows_unrelated_file(self) -> None:
        result = _run(_edit("agents/hapax_daimonion/main.py"))
        assert result.returncode == 0


# ── Pass-through for non-mutating tools ────────────────────────────


class TestPassthrough:
    def test_passes_through_read_tool(self) -> None:
        """The hook gates only file-mutating tools; Read of registry.yaml is
        fine."""
        result = _run({"tool_name": "Read", "tool_input": {"file_path": "axioms/registry.yaml"}})
        assert result.returncode == 0

    def test_passes_through_bash_tool(self) -> None:
        """Even `cat axioms/registry.yaml` via Bash is fine — Bash isn't gated."""
        result = _run({"tool_name": "Bash", "tool_input": {"command": "cat axioms/registry.yaml"}})
        assert result.returncode == 0

    def test_passes_through_edit_with_no_path(self) -> None:
        result = _run({"tool_name": "Edit", "tool_input": {}})
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

    def test_block_message_documents_human_review(self) -> None:
        """Block message must explain that human review is required —
        the operator needs to know why automated edits are refused."""
        body = HOOK.read_text(encoding="utf-8")
        assert "human review" in body
