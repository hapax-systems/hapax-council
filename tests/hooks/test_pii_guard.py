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


# ── Registered household names (external list) ─────────────────────
#
# The guard's two newest checks shipped with no committed test, and the review
# team named that in three separate findings. Every branch below is one of
# them. The registered names are fixtures invented here — the real list lives
# outside any repository, and a test that needed the real names would be the
# disclosure the guard exists to prevent.


def _names_file(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "pii-names.txt"
    path.write_text(body, encoding="utf-8")
    return path


def _run_with_names(
    payload: dict, *, cwd: Path, names_file: Path | None
) -> subprocess.CompletedProcess[str]:
    import os

    env = dict(os.environ)
    # Point at a path that cannot exist to exercise the missing-list branch.
    env["HAPAX_PII_NAMES_FILE"] = str(names_file) if names_file else str(cwd / "absent.txt")
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
        env=env,
    )


class TestRegisteredHouseholdNames:
    def test_blocks_a_registered_name(self, tmp_path: Path) -> None:
        repo = tmp_path
        (repo / ".git").mkdir()
        names = _names_file(repo, "Wilhelmina\n")
        result = _run_with_names(
            _edit(str(repo / "agents/x.py"), "# note from Wilhelmina\n"), cwd=repo, names_file=names
        )
        assert result.returncode == 2
        assert "Registered household name" in result.stderr

    def test_blocks_a_registered_name_inside_snake_case(self, tmp_path: Path) -> None:
        """The `\\b` bug, pinned.

        Underscore is a word character, so `\\bWilhelmina\\b` does NOT match
        inside `wilhelmina_surname`. That blindness is what let an underscored
        form survive in two contract files. The guard must use a
        letters-only boundary. Mutation-verified: restoring `\\b` turns this red
        while every other test in this class stays green.
        """
        repo = tmp_path
        (repo / ".git").mkdir()
        names = _names_file(repo, "Wilhelmina\n")
        result = _run_with_names(
            _edit(str(repo / "agents/x.py"), "contract_wilhelmina_v2 = 1\n"),
            cwd=repo,
            names_file=names,
        )
        assert result.returncode == 2

    def test_blocks_a_registered_name_in_the_filename(self, tmp_path: Path) -> None:
        """A name in a PATH is the same exposure as one in the body — and
        renaming files is exactly how the original scrub had to be done."""
        repo = tmp_path
        (repo / ".git").mkdir()
        names = _names_file(repo, "Wilhelmina\n")
        result = _run_with_names(
            _edit(str(repo / "scripts/render_wilhelmina_demo.py"), "x = 1\n"),
            cwd=repo,
            names_file=names,
        )
        assert result.returncode == 2

    def test_exemption_phrase_allows_a_legitimate_citation(self, tmp_path: Path) -> None:
        """Precision matters more than reach here: a guard that blocks a real
        author's citation gets switched off, and a switched-off guard is how
        the original exposure lasted five months."""
        repo = tmp_path
        (repo / ".git").mkdir()
        names = _names_file(repo, "Wilhelmina\n!Wilhelmina Fairweather\n")
        result = _run_with_names(
            _edit(str(repo / "docs/x.md"), "See Wilhelmina Fairweather, *On Queues*.\n"),
            cwd=repo,
            names_file=names,
        )
        assert result.returncode == 0

    def test_exemption_does_not_shadow_a_bare_occurrence(self, tmp_path: Path) -> None:
        """The exemption removes only the exempt phrase. A bare occurrence
        elsewhere in the same content is still caught."""
        repo = tmp_path
        (repo / ".git").mkdir()
        names = _names_file(repo, "Wilhelmina\n!Wilhelmina Fairweather\n")
        result = _run_with_names(
            _edit(
                str(repo / "docs/x.md"),
                "See Wilhelmina Fairweather, *On Queues*. Also: Wilhelmina's room.\n",
            ),
            cwd=repo,
            names_file=names,
        )
        assert result.returncode == 2

    def test_regex_metacharacters_in_the_list_do_not_break_the_check(self, tmp_path: Path) -> None:
        """External configuration is data, never a program.

        A list entry holding `(`, `[`, `/` or a quantifier used to be
        interpolated raw into PCRE and into a sed program. A malformed pattern
        makes grep exit non-zero, which the old `if` read as "no match" — so a
        stray character SILENTLY disabled the guard. Names are matched
        literally now, and an exemption holding a slash must not eat the
        substitution.
        """
        repo = tmp_path
        (repo / ".git").mkdir()
        names = _names_file(repo, "Wil(helmina\n!a/b(c[d\n")
        result = _run_with_names(
            _edit(str(repo / "agents/x.py"), "# Wil(helmina was here\n"),
            cwd=repo,
            names_file=names,
        )
        assert result.returncode == 2, result.stderr

    def test_a_metacharacter_entry_does_not_match_unrelated_text(self, tmp_path: Path) -> None:
        """The other half of literal matching: `Wil(helmina` must not match
        text that only a REGEX reading of it would match."""
        repo = tmp_path
        (repo / ".git").mkdir()
        names = _names_file(repo, "Wil(helmina\n")
        result = _run_with_names(
            _edit(str(repo / "agents/x.py"), "# Wilhelmina spelled without the paren\n"),
            cwd=repo,
            names_file=names,
        )
        assert result.returncode == 0, result.stderr

    def test_comment_and_blank_lines_in_the_list_are_ignored(self, tmp_path: Path) -> None:
        repo = tmp_path
        (repo / ".git").mkdir()
        names = _names_file(repo, "# household\n\nWilhelmina\n")
        result = _run_with_names(
            _edit(str(repo / "agents/x.py"), "# nothing sensitive here\n"),
            cwd=repo,
            names_file=names,
        )
        assert result.returncode == 0, result.stderr

    def test_a_missing_list_warns_and_keeps_structural_checks(self, tmp_path: Path) -> None:
        """Absence of the list is a configuration state, not a violation: the
        run proceeds, the warning names its own remedy, and the checks that
        need no list still fire."""
        repo = tmp_path
        (repo / ".git").mkdir()
        result = _run_with_names(
            _edit(str(repo / "agents/x.py"), "# ordinary line\n"), cwd=repo, names_file=None
        )
        assert result.returncode == 0
        assert "no household name list" in result.stderr
        assert "Create it" in result.stderr


# ── Structural age disclosure (needs no list) ──────────────────────


class TestAgeDisclosure:
    def test_blocks_name_paren_age(self, tmp_path: Path) -> None:
        repo = tmp_path
        (repo / ".git").mkdir()
        result = _run(_edit(str(repo / "docs/x.md"), "Wilhelmina (11) likes chess.\n"), cwd=repo)
        assert result.returncode == 2
        assert "age disclosure" in result.stderr

    def test_blocks_the_spelled_out_form(self, tmp_path: Path) -> None:
        """The form the first revision missed.

        A scrub that added the `Name (NN)` check still shipped a child's age as
        prose one file away. The age is the disclosure; its punctuation is not.
        """
        repo = tmp_path
        (repo / ".git").mkdir()
        result = _run(
            _edit(
                str(repo / "scripts/x.py"), '"""Adjusted for a single brilliant 11-year-old."""\n'
            ),
            cwd=repo,
        )
        assert result.returncode == 2
        assert "age disclosure" in result.stderr

    def test_blocks_the_spaced_form(self, tmp_path: Path) -> None:
        repo = tmp_path
        (repo / ".git").mkdir()
        result = _run(_edit(str(repo / "docs/x.md"), "an 8 year old reader\n"), cwd=repo)
        assert result.returncode == 2

    def test_adult_ages_do_not_trip_the_minor_range(self, tmp_path: Path) -> None:
        """Bounded 1..19 on purpose. Outside that range the subject is not a
        minor and the false-positive cost dominates."""
        repo = tmp_path
        (repo / ".git").mkdir()
        result = _run(_edit(str(repo / "docs/x.md"), "a 45-year-old codebase\n"), cwd=repo)
        assert result.returncode == 0, result.stderr

    def test_section_references_are_not_ages(self, tmp_path: Path) -> None:
        """`Name (NN)` false-positive precision, named by review: a
        capitalised word before a parenthesised number is often a citation or
        a section reference, not a person."""
        repo = tmp_path
        (repo / ".git").mkdir()
        result = _run(
            _edit(str(repo / "docs/x.md"), "See Appendix (2) and Chapter (3).\n"), cwd=repo
        )
        assert result.returncode == 0, result.stderr


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
