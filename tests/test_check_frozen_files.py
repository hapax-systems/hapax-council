"""Tests for the LRR Phase 1 item 4 frozen-file pre-commit hook.

The script is at ``scripts/check-frozen-files.py`` (hyphenated). Imported
via ``importlib.util``. Each test isolates the registry + deviations
directory via monkeypatch onto a tempdir + chdir.

Spec: docs/superpowers/specs/2026-04-14-lrr-phase-1-research-registry-design.md
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch


def _load_script():
    """Import scripts/check-frozen-files.py as a module."""
    spec_path = Path(__file__).resolve().parent.parent / "scripts" / "check-frozen-files.py"
    spec = importlib.util.spec_from_file_location("check_frozen_files_module", spec_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_frozen_files_module"] = module
    spec.loader.exec_module(module)
    return module


def _init_git_repo(tmp_path: Path) -> None:
    """Initialize a git repo so `git diff --cached` works."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=tmp_path,
        check=True,
    )


def _stage_file(tmp_path: Path, relative_path: str, content: str) -> None:
    """Create + git add a file in the tmp_path repo."""
    full = tmp_path / relative_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)
    subprocess.run(["git", "add", relative_path], cwd=tmp_path, check=True)


class TestNoActiveCondition:
    """When the registry isn't initialized, the hook must not block commits."""

    def test_returns_zero_when_current_file_missing(self, tmp_path: Path):
        script = _load_script()
        registry = tmp_path / "registry"
        with (
            patch.object(script, "REGISTRY_DIR", registry),
            patch.object(script, "CURRENT_FILE", registry / "current.txt"),
        ):
            assert script.main([]) == 0

    def test_returns_zero_when_current_file_empty(self, tmp_path: Path):
        script = _load_script()
        registry = tmp_path / "registry"
        registry.mkdir()
        (registry / "current.txt").write_text("")
        with (
            patch.object(script, "REGISTRY_DIR", registry),
            patch.object(script, "CURRENT_FILE", registry / "current.txt"),
        ):
            assert script.main([]) == 0


class TestEmptyFrozenList:
    """A condition with empty frozen_files list does not block any commit."""

    def test_empty_frozen_list_allows_all(self, tmp_path: Path, monkeypatch):
        script = _load_script()
        registry = tmp_path / "registry"
        registry.mkdir()
        (registry / "current.txt").write_text("cond-test-001\n")
        cond_dir = registry / "cond-test-001"
        cond_dir.mkdir()
        (cond_dir / "condition.yaml").write_text("condition_id: cond-test-001\nfrozen_files: []\n")
        _init_git_repo(tmp_path)
        _stage_file(tmp_path, "any-file.py", "print('hi')\n")
        monkeypatch.chdir(tmp_path)
        with (
            patch.object(script, "REGISTRY_DIR", registry),
            patch.object(script, "CURRENT_FILE", registry / "current.txt"),
        ):
            assert script.main([]) == 0


class TestFrozenViolation:
    """Editing a frozen file without a deviation must block the commit."""

    def test_frozen_file_edit_returns_one(self, tmp_path: Path, monkeypatch, capsys):
        script = _load_script()
        registry = tmp_path / "registry"
        registry.mkdir()
        (registry / "current.txt").write_text("cond-test-001\n")
        cond_dir = registry / "cond-test-001"
        cond_dir.mkdir()
        (cond_dir / "condition.yaml").write_text(
            "condition_id: cond-test-001\n"
            "frozen_files:\n"
            "  - agents/hapax_daimonion/grounding_ledger.py\n"
        )
        _init_git_repo(tmp_path)
        _stage_file(
            tmp_path,
            "agents/hapax_daimonion/grounding_ledger.py",
            "# experiment-frozen change\n",
        )
        monkeypatch.chdir(tmp_path)
        with (
            patch.object(script, "REGISTRY_DIR", registry),
            patch.object(script, "CURRENT_FILE", registry / "current.txt"),
            patch.object(script, "DEVIATIONS_DIR", tmp_path / "research/protocols/deviations"),
        ):
            result = script.main([])
        assert result == 1
        out = capsys.readouterr().err
        assert "FROZEN-FILE VIOLATION" in out
        assert "agents/hapax_daimonion/grounding_ledger.py" in out

    def test_non_frozen_file_edit_returns_zero(self, tmp_path: Path, monkeypatch):
        script = _load_script()
        registry = tmp_path / "registry"
        registry.mkdir()
        (registry / "current.txt").write_text("cond-test-001\n")
        cond_dir = registry / "cond-test-001"
        cond_dir.mkdir()
        (cond_dir / "condition.yaml").write_text(
            "condition_id: cond-test-001\n"
            "frozen_files:\n"
            "  - agents/hapax_daimonion/grounding_ledger.py\n"
        )
        _init_git_repo(tmp_path)
        _stage_file(tmp_path, "scripts/some-other-file.py", "print('not frozen')\n")
        monkeypatch.chdir(tmp_path)
        with (
            patch.object(script, "REGISTRY_DIR", registry),
            patch.object(script, "CURRENT_FILE", registry / "current.txt"),
        ):
            assert script.main([]) == 0


class TestDeviationOverride:
    """A deviation file that mentions every touched frozen path lets the commit through."""

    def test_matching_deviation_allows_commit(self, tmp_path: Path, monkeypatch, capsys):
        script = _load_script()
        registry = tmp_path / "registry"
        registry.mkdir()
        (registry / "current.txt").write_text("cond-test-001\n")
        cond_dir = registry / "cond-test-001"
        cond_dir.mkdir()
        (cond_dir / "condition.yaml").write_text(
            "condition_id: cond-test-001\n"
            "frozen_files:\n"
            "  - agents/hapax_daimonion/grounding_ledger.py\n"
        )
        # Create a deviation that mentions the frozen file path.
        deviations = tmp_path / "research/protocols/deviations"
        deviations.mkdir(parents=True)
        (deviations / "DEVIATION-100.md").write_text(
            "# Deviation 100\n\n"
            "Touches `agents/hapax_daimonion/grounding_ledger.py` for a structural\n"
            "refactor with no behavioral change. Validity-safe.\n"
        )
        _init_git_repo(tmp_path)
        _stage_file(
            tmp_path,
            "agents/hapax_daimonion/grounding_ledger.py",
            "# refactor\n",
        )
        monkeypatch.chdir(tmp_path)
        with (
            patch.object(script, "REGISTRY_DIR", registry),
            patch.object(script, "CURRENT_FILE", registry / "current.txt"),
            patch.object(script, "DEVIATIONS_DIR", deviations),
        ):
            result = script.main([])
        assert result == 0
        out = capsys.readouterr().out
        assert "DEVIATION-100" in out

    def test_unrelated_deviation_does_not_cover(self, tmp_path: Path, monkeypatch):
        script = _load_script()
        registry = tmp_path / "registry"
        registry.mkdir()
        (registry / "current.txt").write_text("cond-test-001\n")
        cond_dir = registry / "cond-test-001"
        cond_dir.mkdir()
        (cond_dir / "condition.yaml").write_text(
            "condition_id: cond-test-001\n"
            "frozen_files:\n"
            "  - agents/hapax_daimonion/grounding_ledger.py\n"
        )
        # Deviation about a different file.
        deviations = tmp_path / "research/protocols/deviations"
        deviations.mkdir(parents=True)
        (deviations / "DEVIATION-100.md").write_text(
            "# Deviation 100\n\nThis touches `some_other_file.py` only.\n"
        )
        _init_git_repo(tmp_path)
        _stage_file(
            tmp_path,
            "agents/hapax_daimonion/grounding_ledger.py",
            "# unrelated change\n",
        )
        monkeypatch.chdir(tmp_path)
        with (
            patch.object(script, "REGISTRY_DIR", registry),
            patch.object(script, "CURRENT_FILE", registry / "current.txt"),
            patch.object(script, "DEVIATIONS_DIR", deviations),
        ):
            assert script.main([]) == 1


class TestMultiDeviationCoverage:
    """Phase 1 audit H3 fix regression pins.

    Before the fix, ``_find_covering_deviation`` required a SINGLE
    deviation to mention all touched frozen files. A legitimate
    multi-deviation scenario (two independent deviations each covering
    one file, a commit that touches both files) would be rejected. The
    fix walks every deviation and records the first that mentions each
    file, accepting iff every file has at least one covering deviation.
    """

    def test_two_files_covered_by_two_deviations_allows_commit(
        self, tmp_path: Path, monkeypatch, capsys
    ):
        script = _load_script()
        registry = tmp_path / "registry"
        registry.mkdir()
        (registry / "current.txt").write_text("cond-test-001\n")
        cond_dir = registry / "cond-test-001"
        cond_dir.mkdir()
        (cond_dir / "condition.yaml").write_text(
            "condition_id: cond-test-001\n"
            "frozen_files:\n"
            "  - agents/hapax_daimonion/persona.py\n"
            "  - agents/hapax_daimonion/conversational_policy.py\n"
        )
        deviations = tmp_path / "research/protocols/deviations"
        deviations.mkdir(parents=True)
        (deviations / "DEVIATION-001.md").write_text(
            "# Deviation 001\n\nTouches `agents/hapax_daimonion/persona.py` only.\n"
        )
        (deviations / "DEVIATION-002.md").write_text(
            "# Deviation 002\n\nTouches `agents/hapax_daimonion/conversational_policy.py` only.\n"
        )
        _init_git_repo(tmp_path)
        _stage_file(tmp_path, "agents/hapax_daimonion/persona.py", "# change\n")
        _stage_file(
            tmp_path,
            "agents/hapax_daimonion/conversational_policy.py",
            "# change\n",
        )
        monkeypatch.chdir(tmp_path)
        with (
            patch.object(script, "REGISTRY_DIR", registry),
            patch.object(script, "CURRENT_FILE", registry / "current.txt"),
            patch.object(script, "DEVIATIONS_DIR", deviations),
        ):
            assert script.main([]) == 0
        out = capsys.readouterr().out
        assert "DEVIATION-001" in out and "DEVIATION-002" in out
        # Multi-deviation summary must report both deviation filenames.
        assert "2 deviation(s)" in out or "2 deviations" in out

    def test_single_deviation_covering_all_files_still_works(
        self, tmp_path: Path, monkeypatch, capsys
    ):
        """The single-deviation case must not regress on the H3 fix."""
        script = _load_script()
        registry = tmp_path / "registry"
        registry.mkdir()
        (registry / "current.txt").write_text("cond-test-001\n")
        cond_dir = registry / "cond-test-001"
        cond_dir.mkdir()
        (cond_dir / "condition.yaml").write_text(
            "condition_id: cond-test-001\n"
            "frozen_files:\n"
            "  - agents/hapax_daimonion/persona.py\n"
            "  - agents/hapax_daimonion/conversational_policy.py\n"
        )
        deviations = tmp_path / "research/protocols/deviations"
        deviations.mkdir(parents=True)
        (deviations / "DEVIATION-100.md").write_text(
            "# Deviation 100\n\n"
            "Coordinated change to `agents/hapax_daimonion/persona.py` and "
            "`agents/hapax_daimonion/conversational_policy.py` for a linked "
            "refactor.\n"
        )
        _init_git_repo(tmp_path)
        _stage_file(tmp_path, "agents/hapax_daimonion/persona.py", "# change\n")
        _stage_file(
            tmp_path,
            "agents/hapax_daimonion/conversational_policy.py",
            "# change\n",
        )
        monkeypatch.chdir(tmp_path)
        with (
            patch.object(script, "REGISTRY_DIR", registry),
            patch.object(script, "CURRENT_FILE", registry / "current.txt"),
            patch.object(script, "DEVIATIONS_DIR", deviations),
        ):
            assert script.main([]) == 0
        out = capsys.readouterr().out
        assert "DEVIATION-100" in out

    def test_one_file_uncovered_rejects_even_with_other_covered(self, tmp_path: Path, monkeypatch):
        """If any touched file lacks coverage, the commit must still be blocked."""
        script = _load_script()
        registry = tmp_path / "registry"
        registry.mkdir()
        (registry / "current.txt").write_text("cond-test-001\n")
        cond_dir = registry / "cond-test-001"
        cond_dir.mkdir()
        (cond_dir / "condition.yaml").write_text(
            "condition_id: cond-test-001\n"
            "frozen_files:\n"
            "  - agents/hapax_daimonion/persona.py\n"
            "  - agents/hapax_daimonion/conversational_policy.py\n"
        )
        deviations = tmp_path / "research/protocols/deviations"
        deviations.mkdir(parents=True)
        # Only persona.py has a covering deviation; the policy file does not.
        (deviations / "DEVIATION-001.md").write_text(
            "# Deviation 001\n\nTouches `agents/hapax_daimonion/persona.py`.\n"
        )
        _init_git_repo(tmp_path)
        _stage_file(tmp_path, "agents/hapax_daimonion/persona.py", "# change\n")
        _stage_file(
            tmp_path,
            "agents/hapax_daimonion/conversational_policy.py",
            "# change\n",
        )
        monkeypatch.chdir(tmp_path)
        with (
            patch.object(script, "REGISTRY_DIR", registry),
            patch.object(script, "CURRENT_FILE", registry / "current.txt"),
            patch.object(script, "DEVIATIONS_DIR", deviations),
        ):
            assert script.main([]) == 1


class TestPathPrefixMatching:
    """Frozen entries ending in `/` match all files under that directory."""

    def test_directory_prefix_blocks_files_below(self, tmp_path: Path, monkeypatch):
        script = _load_script()
        registry = tmp_path / "registry"
        registry.mkdir()
        (registry / "current.txt").write_text("cond-test-001\n")
        cond_dir = registry / "cond-test-001"
        cond_dir.mkdir()
        (cond_dir / "condition.yaml").write_text(
            "condition_id: cond-test-001\nfrozen_files:\n  - agents/hapax_daimonion/proofs/\n"
        )
        _init_git_repo(tmp_path)
        _stage_file(
            tmp_path,
            "agents/hapax_daimonion/proofs/RESEARCH-STATE.md",
            "# update\n",
        )
        monkeypatch.chdir(tmp_path)
        with (
            patch.object(script, "REGISTRY_DIR", registry),
            patch.object(script, "CURRENT_FILE", registry / "current.txt"),
            patch.object(script, "DEVIATIONS_DIR", tmp_path / "no-deviations"),
        ):
            assert script.main([]) == 1


class TestFileIsFrozenHelper:
    """Direct unit tests for _file_is_frozen."""

    def test_exact_match(self):
        script = _load_script()
        assert script._file_is_frozen("a/b.py", ["a/b.py"]) is True

    def test_prefix_match_with_trailing_slash(self):
        script = _load_script()
        assert script._file_is_frozen("a/b/c.py", ["a/b/"]) is True

    def test_prefix_without_trailing_slash_does_not_match(self):
        script = _load_script()
        # No trailing slash on entry → no prefix match
        assert script._file_is_frozen("a/b/c.py", ["a/b"]) is False

    def test_no_match(self):
        script = _load_script()
        assert script._file_is_frozen("x.py", ["a/b.py", "c/"]) is False


class TestProbeMode:
    """LRR Phase 1 item 4b — ``--probe <path>`` pre-edit query mode.

    Per the spec, the probe is a direct path check (no staged state
    consulted). Exit 0 = path is safe to edit (not frozen OR covered
    by deviation); exit 2 = path is declined by the probe (frozen +
    uncovered, OR registry-uninitialized).
    """

    def _setup_registry(self, tmp_path: Path, frozen: list[str]) -> tuple:
        """Create a registry + active condition. Returns (registry, deviations)."""
        registry = tmp_path / "registry"
        condition_dir = registry / "cond-test-001"
        condition_dir.mkdir(parents=True)
        (registry / "current.txt").write_text("cond-test-001")
        condition_yaml_body = "frozen_files:\n"
        for f in frozen:
            condition_yaml_body += f"  - {f}\n"
        (condition_dir / "condition.yaml").write_text(condition_yaml_body)
        deviations = tmp_path / "deviations"
        deviations.mkdir()
        return registry, deviations

    def test_probe_unfrozen_path_returns_zero(self, tmp_path: Path):
        script = _load_script()
        registry, deviations = self._setup_registry(
            tmp_path, ["agents/hapax_daimonion/grounding_ledger.py"]
        )
        with (
            patch.object(script, "REGISTRY_DIR", registry),
            patch.object(script, "CURRENT_FILE", registry / "current.txt"),
            patch.object(script, "DEVIATIONS_DIR", deviations),
        ):
            assert script._probe("docs/research/test.md") == 0

    def test_probe_frozen_path_returns_two(self, tmp_path: Path):
        script = _load_script()
        registry, deviations = self._setup_registry(
            tmp_path, ["agents/hapax_daimonion/grounding_ledger.py"]
        )
        with (
            patch.object(script, "REGISTRY_DIR", registry),
            patch.object(script, "CURRENT_FILE", registry / "current.txt"),
            patch.object(script, "DEVIATIONS_DIR", deviations),
        ):
            assert script._probe("agents/hapax_daimonion/grounding_ledger.py") == 2

    def test_probe_frozen_path_with_deviation_returns_zero(self, tmp_path: Path):
        script = _load_script()
        registry, deviations = self._setup_registry(
            tmp_path, ["agents/hapax_daimonion/grounding_ledger.py"]
        )
        (deviations / "DEVIATION-999.md").write_text(
            "DEVIATION-999\n\npaths: agents/hapax_daimonion/grounding_ledger.py\n"
        )
        with (
            patch.object(script, "REGISTRY_DIR", registry),
            patch.object(script, "CURRENT_FILE", registry / "current.txt"),
            patch.object(script, "DEVIATIONS_DIR", deviations),
        ):
            assert script._probe("agents/hapax_daimonion/grounding_ledger.py") == 0

    def test_probe_uninitialized_registry_returns_two(self, tmp_path: Path):
        script = _load_script()
        registry = tmp_path / "registry"
        with (
            patch.object(script, "REGISTRY_DIR", registry),
            patch.object(script, "CURRENT_FILE", registry / "current.txt"),
            patch.object(script, "DEVIATIONS_DIR", tmp_path / "deviations"),
        ):
            assert script._probe("docs/research/test.md") == 2

    def test_probe_empty_frozen_list_returns_zero(self, tmp_path: Path):
        script = _load_script()
        registry, deviations = self._setup_registry(tmp_path, [])
        with (
            patch.object(script, "REGISTRY_DIR", registry),
            patch.object(script, "CURRENT_FILE", registry / "current.txt"),
            patch.object(script, "DEVIATIONS_DIR", deviations),
        ):
            assert script._probe("agents/hapax_daimonion/grounding_ledger.py") == 0

    def test_probe_prefix_match(self, tmp_path: Path):
        script = _load_script()
        registry, deviations = self._setup_registry(tmp_path, ["agents/hapax_daimonion/"])
        with (
            patch.object(script, "REGISTRY_DIR", registry),
            patch.object(script, "CURRENT_FILE", registry / "current.txt"),
            patch.object(script, "DEVIATIONS_DIR", deviations),
        ):
            assert script._probe("agents/hapax_daimonion/grounding_ledger.py") == 2
            assert script._probe("docs/research/test.md") == 0

    def test_probe_invocation_via_main(self, tmp_path: Path):
        """End-to-end test: invoke main() with explicit argv containing --probe."""
        script = _load_script()
        registry, deviations = self._setup_registry(
            tmp_path, ["agents/hapax_daimonion/grounding_ledger.py"]
        )
        with (
            patch.object(script, "REGISTRY_DIR", registry),
            patch.object(script, "CURRENT_FILE", registry / "current.txt"),
            patch.object(script, "DEVIATIONS_DIR", deviations),
        ):
            assert script.main(["--probe", "docs/research/test.md"]) == 0

    def test_probe_invocation_via_main_rejected(self, tmp_path: Path):
        """End-to-end test: invoke main() with --probe on a frozen path."""
        script = _load_script()
        registry, deviations = self._setup_registry(
            tmp_path, ["agents/hapax_daimonion/grounding_ledger.py"]
        )
        with (
            patch.object(script, "REGISTRY_DIR", registry),
            patch.object(script, "CURRENT_FILE", registry / "current.txt"),
            patch.object(script, "DEVIATIONS_DIR", deviations),
        ):
            assert script.main(["--probe", "agents/hapax_daimonion/grounding_ledger.py"]) == 2
