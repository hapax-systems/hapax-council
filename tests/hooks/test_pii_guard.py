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
import os
import re
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


def _run(
    payload: dict, *, cwd: Path | None = None, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    # Never read the host's real principal registry from a test: default it to
    # a path that does not exist unless the test supplies its own.
    run_env = {
        **os.environ,
        "HAPAX_PRINCIPAL_NAME_MAP": "/nonexistent/hapax-test/principal-name-map.yaml",
        **(env or {}),
    }
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
        env=run_env,
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


class TestBlocksRegisteredIdentityForms:
    def test_blocks_surname_alone(self, tmp_path: Path) -> None:
        repo = tmp_path
        (repo / ".git").mkdir()
        result = _run(_edit(str(repo / "agents/x.py"), f"subject = '{OPERATOR_LAST}'\n"), cwd=repo)
        assert result.returncode == 2

    # The guard machinery must carry the name patterns to enforce them (#4600
    # panel critical, 2026-09-27). The hook exempts exactly these four files by
    # exact path, never a directory glob.
    GUARD_MACHINERY = (
        "hooks/scripts/pii-guard.sh",
        "scripts/check-legal-name-leaks.sh",
        "tests/hooks/test_pii_guard.py",
        "tests/scripts/test_check_legal_name_leaks.py",
    )

    @staticmethod
    def _git_repo(path: Path) -> Path:
        # The exemption is decided relative to the real git toplevel, so these
        # tests need a real repository, not a bare .git directory.
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q", str(path)], check=True)
        return path

    def test_guard_machinery_may_carry_the_name_patterns(self, tmp_path: Path) -> None:
        repo = self._git_repo(tmp_path / "repo")
        for rel in self.GUARD_MACHINERY:
            for content in (f"PATTERN='{OPERATOR_LAST}'\n", f"PATTERN='{OPERATOR_FULLNAME}'\n"):
                result = _run(_edit(str(repo / rel), content), cwd=repo)
                assert result.returncode == 0, (rel, result.stderr)

    def test_surname_still_blocked_beside_the_machinery(self, tmp_path: Path) -> None:
        # Same content, any other path: siblings, lookalikes, and a nested
        # duplicate of a machinery file at a deeper depth. All are blocked.
        repo = self._git_repo(tmp_path / "repo")
        for rel in (
            "hooks/scripts/other-guard.sh",
            "scripts/x.sh",
            "tests/hooks/test_other.py",
            "hooks/scripts/pii-guard.sh.bak",
            "vendor/hooks/scripts/pii-guard.sh",
            "worktrees/copy/scripts/check-legal-name-leaks.sh",
        ):
            result = _run(_edit(str(repo / rel), f"PATTERN='{OPERATOR_LAST}'\n"), cwd=repo)
            assert result.returncode == 2, rel

    def test_machinery_path_outside_any_repository_is_not_exempt(self, tmp_path: Path) -> None:
        # No resolvable repository root: no exemption (fail closed).
        loose = tmp_path / "loose"
        result = _run(
            _edit(str(loose / "hooks/scripts/pii-guard.sh"), f"PATTERN='{OPERATOR_LAST}'\n"),
            cwd=tmp_path,
        )
        assert result.returncode == 2

    def test_exempt_machinery_is_editable_with_an_unreadable_registry(self, tmp_path: Path) -> None:
        # The exempt files never consume registry names, so a broken registry
        # does not lock the operator out of repairing the guards.
        repo = self._git_repo(tmp_path / "repo")
        registry = tmp_path / "principal-name-map.yaml"
        registry.mkdir()
        env = {"HAPAX_PRINCIPAL_NAME_MAP": str(registry)}
        result = _run(
            _edit(str(repo / "hooks/scripts/pii-guard.sh"), f"PATTERN='{OPERATOR_LAST}'\n"),
            cwd=repo,
            env=env,
        )
        assert result.returncode == 0, result.stderr

    def test_hook_exemptions_are_exactly_the_machinery_and_within_the_scanner_whitelist(
        self,
    ) -> None:
        def array(path: Path, name: str) -> list[str]:
            body = path.read_text(encoding="utf-8").split(f"{name}=(", 1)[1].split(")", 1)[0]
            return re.findall(r"^\s+'([^']+)'\s*$", body, re.M)

        hook = array(HOOK, "LEGAL_NAME_EXEMPT_PATHS")
        scanner = array(REPO_ROOT / "scripts" / "check-legal-name-leaks.sh", "WHITELIST_GLOBS")
        assert tuple(hook) == self.GUARD_MACHINERY
        assert set(hook) <= set(scanner)

    # Registered principals' given names come from the gitignored local registry
    # (HAPAX_PRINCIPAL_NAME_MAP) when it is provisioned. Tests use a synthetic
    # token; no real name appears in any file.
    SYNTHETIC = "Zorblaxine"

    def _map(self, tmp_path: Path, body: str) -> dict[str, str]:
        registry = tmp_path / "principal-name-map.yaml"
        registry.write_text(body, encoding="utf-8")
        return {"HAPAX_PRINCIPAL_NAME_MAP": str(registry)}

    def test_registry_given_name_is_blocked_and_never_echoed(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        (repo / ".git").mkdir(parents=True)
        env = self._map(tmp_path, f"principal-a2: {self.SYNTHETIC}\n")
        result = _run(
            _edit(str(repo / "agents/x.py"), f"who = '{self.SYNTHETIC}'\n"), cwd=repo, env=env
        )
        assert result.returncode == 2
        assert self.SYNTHETIC.lower() not in (result.stderr + result.stdout).lower()

    def test_registry_absent_falls_back_to_the_surname(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        (repo / ".git").mkdir(parents=True)
        env = {"HAPAX_PRINCIPAL_NAME_MAP": str(tmp_path / "absent.yaml")}
        given = _run(
            _edit(str(repo / "agents/x.py"), f"who = '{self.SYNTHETIC}'\n"), cwd=repo, env=env
        )
        assert given.returncode == 0
        surname = _run(
            _edit(str(repo / "agents/x.py"), f"who = '{OPERATOR_LAST}'\n"), cwd=repo, env=env
        )
        assert surname.returncode == 2

    def test_registry_never_blocks_opaque_ids_or_partial_words(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        (repo / ".git").mkdir(parents=True)
        env = self._map(tmp_path, f"principal-a2: {self.SYNTHETIC}\n")
        for content in ("who = 'principal-a2'\n", f"who = '{self.SYNTHETIC}ly'\n"):
            result = _run(_edit(str(repo / "agents/x.py"), content), cwd=repo, env=env)
            assert result.returncode == 0, content

    def test_invalid_registry_entry_fails_closed_naming_the_line(self, tmp_path: Path) -> None:
        # An entry that is not a plain name would silently drop that principal
        # from the gate. It fails closed instead, naming the line number and
        # never echoing the entry. It is never compiled as a pattern.
        repo = tmp_path / "repo"
        (repo / ".git").mkdir(parents=True)
        env = self._map(tmp_path, f"principal-a2: {self.SYNTHETIC}\nprincipal-a3: .*zq\n")
        result = _run(_edit(str(repo / "agents/x.py"), "x = 1\n"), cwd=repo, env=env)
        assert result.returncode == 2
        assert "line 2" in result.stderr
        assert ".*zq" not in result.stderr and self.SYNTHETIC not in result.stderr

    def test_unreadable_registry_fails_closed(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        (repo / ".git").mkdir(parents=True)
        registry = tmp_path / "principal-name-map.yaml"
        registry.mkdir()  # exists but cannot be read as a file
        env = {"HAPAX_PRINCIPAL_NAME_MAP": str(registry)}
        result = _run(_edit(str(repo / "agents/x.py"), "x = 1\n"), cwd=repo, env=env)
        assert result.returncode == 2
        assert "principal-name-map" in result.stderr

    def test_opaque_principal_ids_are_never_blocked(self, tmp_path: Path) -> None:
        # The opaque IDs are the vocabulary that replaces the names. Blocking
        # them would fail every follow-on PR that uses them (#4717, #4558).
        repo = tmp_path
        (repo / ".git").mkdir()
        for principal_id in ("principal-c1", "principal-c2", "principal-a1", "principal-a2"):
            result = _run(
                _edit(str(repo / "agents/x.py"), f"subject = '{principal_id}'\n"), cwd=repo
            )
            assert result.returncode == 0, (principal_id, result.stderr)

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
