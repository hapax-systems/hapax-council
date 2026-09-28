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

import pytest

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

    def test_dangling_registry_symlink_fails_closed(self, tmp_path: Path) -> None:
        # A configured registry whose symlink target is gone is not "absent":
        # treating it so would silently drop every registered given name.
        repo = tmp_path / "repo"
        (repo / ".git").mkdir(parents=True)
        registry = tmp_path / "principal-name-map.yaml"
        registry.symlink_to(tmp_path / "gone.yaml")
        env = {"HAPAX_PRINCIPAL_NAME_MAP": str(registry)}
        result = _run(_edit(str(repo / "agents/x.py"), "x = 1\n"), cwd=repo, env=env)
        assert result.returncode == 2
        assert "principal-name-map" in result.stderr

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
#
# THE AGES BELOW ARE THE PATTERN'S BOUNDARIES, NOT ANYONE'S.
#
# The first draft of these tests used the two ages the scrub had just removed. A test file in a
# public repository asserting those exact numbers republishes, in a new file, the disclosure the
# guard exists to prevent — and it does so under a heading that explains what they are. Caught in
# review; the correction is the same convention this file already applies to names, which its own
# docstring states: nothing that would be a disclosure appears as a literal here.
#
# So the in-range cases are the ENDS of the guard's 1..19 window plus its midpoint. That carries
# no household information and is strictly better coverage than two interior points: an off-by-one
# at either boundary now fails, and an interior pair would not have caught it.
MINOR_AGE_LOW = "1"
MINOR_AGE_MID = "14"
MINOR_AGE_HIGH = "19"
ADULT_AGE = "45"


class TestAgeDisclosure:
    def test_blocks_name_paren_age(self, tmp_path: Path) -> None:
        repo = tmp_path
        (repo / ".git").mkdir()
        result = _run(
            _edit(str(repo / "docs/x.md"), f"Wilhelmina ({MINOR_AGE_MID}) likes chess.\n"),
            cwd=repo,
        )
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
                str(repo / "scripts/x.py"),
                f'"""Adjusted for a single brilliant {MINOR_AGE_MID}-year-old."""\n',
            ),
            cwd=repo,
        )
        assert result.returncode == 2
        assert "age disclosure" in result.stderr

    def test_blocks_the_spaced_form(self, tmp_path: Path) -> None:
        repo = tmp_path
        (repo / ".git").mkdir()
        result = _run(
            _edit(str(repo / "docs/x.md"), f"an {MINOR_AGE_LOW} year old reader\n"), cwd=repo
        )
        assert result.returncode == 2

    def test_blocks_the_upper_boundary_of_the_minor_range(self, tmp_path: Path) -> None:
        """19 is inside the window; an off-by-one here is a silent hole."""
        repo = tmp_path
        (repo / ".git").mkdir()
        result = _run(
            _edit(str(repo / "docs/x.md"), f"a {MINOR_AGE_HIGH}-year-old reader\n"), cwd=repo
        )
        assert result.returncode == 2

    def test_adult_ages_do_not_trip_the_minor_range(self, tmp_path: Path) -> None:
        """Bounded 1..19 on purpose. Outside that range the subject is not a
        minor and the false-positive cost dominates."""
        repo = tmp_path
        (repo / ".git").mkdir()
        result = _run(
            _edit(str(repo / "docs/x.md"), f"a {ADULT_AGE}-year-old codebase\n"), cwd=repo
        )
        assert result.returncode == 0, result.stderr

    def test_just_above_the_minor_range_does_not_trip(self, tmp_path: Path) -> None:
        """The other boundary. 20 must not match, or the window is not what it says."""
        repo = tmp_path
        (repo / ".git").mkdir()
        result = _run(_edit(str(repo / "docs/x.md"), "a 20-year-old codebase\n"), cwd=repo)
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


# ── Tools that were on the allowlist and never scanned ─────────────


class TestMultiEditAndNotebookEditAreActuallyScanned:
    """Both tools sat on the allowlist while their payloads were never read.

    `MultiEdit` carries content in `edits[].new_string` and `NotebookEdit` in
    `new_source` under `notebook_path`. The extraction read neither, so each
    call fell through the empty-content exit and returned 0 for content `Edit`
    blocked. Reproduced by direct execution before the fix — the guard was not
    bypassed, it was never asked the question, which is the same shape as the
    five-month exposure itself.
    """

    def test_multiedit_content_is_scanned(self, tmp_path: Path) -> None:
        repo = tmp_path
        (repo / ".git").mkdir()
        result = _run(
            {
                "tool_name": "MultiEdit",
                "tool_input": {
                    "file_path": str(repo / "docs/x.md"),
                    "edits": [
                        {"new_string": "harmless"},
                        {"new_string": f"an {MINOR_AGE_MID}-year-old reader"},
                    ],
                },
            },
            cwd=repo,
        )
        assert result.returncode == 2, result.stdout + result.stderr
        assert "age disclosure" in result.stderr

    def test_notebookedit_content_and_path_are_scanned(self, tmp_path: Path) -> None:
        repo = tmp_path
        (repo / ".git").mkdir()
        result = _run(
            {
                "tool_name": "NotebookEdit",
                "tool_input": {
                    "notebook_path": str(repo / "notebooks/x.ipynb"),
                    "new_source": f"an {MINOR_AGE_MID}-year-old reader",
                },
            },
            cwd=repo,
        )
        assert result.returncode == 2, result.stdout + result.stderr

    def test_multiedit_clean_content_still_passes(self, tmp_path: Path) -> None:
        repo = tmp_path
        (repo / ".git").mkdir()
        result = _run(
            {
                "tool_name": "MultiEdit",
                "tool_input": {
                    "file_path": str(repo / "agents/x.py"),
                    "edits": [{"new_string": "x = 1"}, {"new_string": "y = 2"}],
                },
            },
            cwd=repo,
        )
        assert result.returncode == 0, result.stderr


# ── Volume independence ────────────────────────────────────────────


class TestTheGateDoesNotDependOnVolume:
    def test_many_candidates_still_block(self, tmp_path: Path) -> None:
        """The fail-open I shipped in the precision fix, pinned.

        `grep -oP ... | grep -qvP ...` under `set -o pipefail`: the `-q`
        consumer exits on its first hit, SIGPIPEs the producer, and the
        pipeline status becomes 141, so the `if` is false. One candidate
        blocked; fifty thousand passed. A gate whose verdict depends on input
        size is worse than no gate — it passes exactly the large mechanical
        writes least likely to have been read by a human.
        """
        repo = tmp_path
        (repo / ".git").mkdir()
        body = " ".join(f"Wilhelmina ({i % 90 + 1})" for i in range(50_000))
        result = _run(_edit(str(repo / "docs/x.md"), body), cwd=repo)
        assert result.returncode == 2, "the age gate went fail-open at volume"

    def test_many_structure_words_still_pass(self, tmp_path: Path) -> None:
        """The same volume, on the exempt side: precision must not decay either."""
        repo = tmp_path
        (repo / ".git").mkdir()
        body = " ".join(f"Appendix ({i % 90 + 1})" for i in range(50_000))
        result = _run(_edit(str(repo / "docs/x.md"), body), cwd=repo)
        assert result.returncode == 0, result.stderr


# ── Filename protection survives the content-shaped exits ──────────


class TestFilenameIsCheckedBeforeContentExits:
    """A skip that is right about CONTENT must not silently skip the PATH.

    The binary-extension skip and the empty-content exit both preceded the
    filename check, so a registered name could be introduced as an image
    filename or an empty file while the code claimed filenames were protected.
    """

    def test_registered_name_in_an_image_filename_is_blocked(self, tmp_path: Path) -> None:
        repo = tmp_path
        (repo / ".git").mkdir()
        names = _names_file(repo, "Wilhelmina\n")
        result = _run_with_names(
            _edit(str(repo / "assets/wilhelmina-portrait.png"), "binary-ish"),
            cwd=repo,
            names_file=names,
        )
        assert result.returncode == 2, result.stdout + result.stderr
        assert "FILENAME" in result.stderr

    def test_registered_name_in_an_empty_write_is_blocked(self, tmp_path: Path) -> None:
        repo = tmp_path
        (repo / ".git").mkdir()
        names = _names_file(repo, "Wilhelmina\n")
        result = _run_with_names(
            _edit(str(repo / "docs/wilhelmina.md"), ""), cwd=repo, names_file=names
        )
        assert result.returncode == 2, result.stdout + result.stderr

    def test_a_clean_image_filename_still_skips(self, tmp_path: Path) -> None:
        repo = tmp_path
        (repo / ".git").mkdir()
        names = _names_file(repo, "Wilhelmina\n")
        result = _run_with_names(
            _edit(str(repo / "assets/diagram.png"), f"# {OPERATOR_FULLNAME}"),
            cwd=repo,
            names_file=names,
        )
        assert result.returncode == 0, result.stderr


# ── Degraded coverage leaves an auditable trace ────────────────────


class TestDegradedCoverageIsRecorded:
    def test_missing_list_writes_a_degradation_receipt(self, tmp_path: Path) -> None:
        """Absence of the list is durable, so the stderr warning repeats forever
        and gets tuned out. A half-disabled guard must not look identical to a
        working one in an audit."""
        import os

        repo = tmp_path
        (repo / ".git").mkdir()
        state = tmp_path / "state"
        env = dict(os.environ)
        env["HAPAX_PII_NAMES_FILE"] = str(repo / "absent.txt")
        env["XDG_STATE_HOME"] = str(state)
        result = subprocess.run(
            ["bash", str(HOOK)],
            input=json.dumps(_edit(str(repo / "agents/x.py"), "x = 1\n")),
            capture_output=True,
            text=True,
            check=False,
            cwd=repo,
            env=env,
        )
        assert result.returncode == 0
        receipt = state / "hapax" / "pii-guard-degraded.jsonl"
        assert receipt.is_file(), "a degraded guard must leave a durable trace"
        assert "household_name_list_absent" in receipt.read_text(encoding="utf-8")

    @pytest.mark.parametrize(
        ("path", "content", "case"),
        [
            ("assets/photo.png", "binary-ish", "binary extension"),
            ("agents/empty.py", "", "empty content"),
        ],
    )
    def test_the_early_exits_still_record_the_degradation(
        self, tmp_path: Path, path: str, content: str, case: str
    ) -> None:
        """The writes that exit early are degraded too, and used to leave no trace.

        The receipt sat BELOW the binary-extension skip and the empty-content exit, so a `.png`
        or an empty write ran with known-name protection off and recorded nothing. The receipt
        exists so that "was known-name protection on for that mutation?" has an answer which does
        not depend on who was reading stderr — and for these two shapes the answer was silence,
        which reads as "protected" and meant "not checked, not recorded".
        """
        import os

        repo = tmp_path
        (repo / ".git").mkdir()
        state = tmp_path / "state"
        env = dict(os.environ)
        env["HAPAX_PII_NAMES_FILE"] = str(repo / "absent.txt")
        env["XDG_STATE_HOME"] = str(state)

        result = subprocess.run(
            ["bash", str(HOOK)],
            input=json.dumps(_edit(str(repo / path), content)),
            capture_output=True,
            text=True,
            check=False,
            cwd=repo,
            env=env,
        )

        assert result.returncode == 0
        receipt = state / "hapax" / "pii-guard-degraded.jsonl"
        assert receipt.is_file(), f"{case} exited before recording the degradation"
        assert "household_name_list_absent" in receipt.read_text(encoding="utf-8")


# ── Shell writes ───────────────────────────────────────────────────


class TestBashCommandsAreScanned:
    """A shell write reaches tracked files without ever being an Edit.

    Scanning the command TEXT is an honest partial — it catches the literal
    case, which is how the original exposure was written, and cannot see
    content assembled from variables or read from another file. The limit is
    asserted here so nobody reads this class as full coverage.

    The shell path runs the SAME battery as the Edit path. Its first version
    ran its own pair of patterns while Edit ran five, so a registered
    household name in `echo "..." > file` passed while the identical string
    through Edit blocked — which tool a caller reached for decided whether a
    child's name was protected. Divergent guards for one hazard are worse
    than a single gap, because the gap at least behaves the same way twice.
    """

    def test_blocks_an_age_in_a_shell_command(self, tmp_path: Path) -> None:
        result = _run(
            {
                "tool_name": "Bash",
                "tool_input": {"command": f"echo 'a {MINOR_AGE_MID}-year-old reader' > docs/x.md"},
            },
            cwd=tmp_path,
        )
        assert result.returncode == 2, result.stdout + result.stderr
        assert "shell command" in result.stderr

    def test_blocks_the_operator_name_in_a_shell_command(self, tmp_path: Path) -> None:
        result = _run(
            {
                "tool_name": "Bash",
                "tool_input": {"command": f"printf '%s' '{OPERATOR_FULLNAME}' >> notes.md"},
            },
            cwd=tmp_path,
        )
        assert result.returncode == 2

    def test_a_registered_name_in_a_shell_command_is_blocked(self, tmp_path: Path) -> None:
        """The divergence, pinned. This passed while the same string via Edit blocked."""
        names = _names_file(tmp_path, "Wilhelmina\n")
        result = _run_with_names(
            {
                "tool_name": "Bash",
                "tool_input": {"command": 'echo "note from Wilhelmina" > docs/x.md'},
            },
            cwd=tmp_path,
            names_file=names,
        )
        assert result.returncode == 2, result.stdout + result.stderr
        assert "Registered household name" in result.stderr

    def test_a_name_paren_age_in_a_shell_command_is_blocked(self, tmp_path: Path) -> None:
        """The other check the shell path did not have."""
        result = _run(
            {
                "tool_name": "Bash",
                "tool_input": {"command": f'echo "Wilhelmina ({MINOR_AGE_MID})" > docs/x.md'},
            },
            cwd=tmp_path,
        )
        assert result.returncode == 2, result.stdout + result.stderr
        assert "age disclosure" in result.stderr

    def test_allows_an_ordinary_shell_command(self, tmp_path: Path) -> None:
        result = _run(
            {"tool_name": "Bash", "tool_input": {"command": "git status --short"}}, cwd=tmp_path
        )
        assert result.returncode == 0, result.stderr

    def test_indirect_content_is_a_stated_limit_not_a_claim(self, tmp_path: Path) -> None:
        """Pins the boundary: content the command does not spell out is NOT seen.

        If a future change makes this pass by blocking, the docstring in the
        hook is then wrong and must be updated with it — that is the point of
        asserting a limitation rather than leaving it implied.
        """
        result = _run(
            {"tool_name": "Bash", "tool_input": {"command": "cat source.txt > dest.md"}},
            cwd=tmp_path,
        )
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
