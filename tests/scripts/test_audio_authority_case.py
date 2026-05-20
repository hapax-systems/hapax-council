"""Tests for scripts/check-audio-authority-case.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check-audio-authority-case.py"


def test_authority_case_runs_without_error() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"


def test_strict_mode_fails_on_missing_fields(tmp_path: Path) -> None:
    task_dir = tmp_path / "active"
    task_dir.mkdir()
    bad_task = task_dir / "audio-bad-task.md"
    bad_task.write_text(
        "---\n"
        "type: cc-task\n"
        "task_id: audio-bad-task\n"
        "tags:\n"
        "  - audio\n"
        "---\n"
        "# Missing authority_case, parent_spec, mutation_scope_refs\n"
    )

    import importlib.util

    spec = importlib.util.spec_from_file_location("check_audio_authority_case", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    original_vault = None
    try:
        spec.loader.exec_module(mod)
        original_vault = mod.ACTIVE_TASKS_VAULT
        mod.ACTIVE_TASKS_VAULT = task_dir
        errors = mod.validate_task_note(bad_task, strict=True)
    finally:
        if original_vault is not None:
            mod.ACTIVE_TASKS_VAULT = original_vault
    assert any("ERROR" in e for e in errors)
    assert any("authority_case" in e for e in errors)


def test_wrong_authority_case_prefix(tmp_path: Path) -> None:
    task = tmp_path / "audio-wrong-prefix.md"
    task.write_text(
        "---\n"
        "type: cc-task\n"
        "task_id: audio-wrong-prefix\n"
        "tags:\n"
        "  - audio\n"
        "authority_case: CASE-VISUAL-SOMETHING\n"
        "parent_spec: some-spec.md\n"
        "mutation_scope_refs:\n"
        "  - config/audio-routing.yaml\n"
        "---\n"
        "# Wrong prefix\n"
    )

    import importlib.util

    spec = importlib.util.spec_from_file_location("check_audio_authority_case2", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    errors = mod.validate_task_note(task, strict=True)
    assert any("CASE-AUDIO-" in e for e in errors)


def test_non_audio_task_skipped(tmp_path: Path) -> None:
    task = tmp_path / "visual-task.md"
    task.write_text(
        "---\ntype: cc-task\ntask_id: visual-task\ntags:\n  - visual\n---\n# Not audio\n"
    )

    import importlib.util

    spec = importlib.util.spec_from_file_location("check_audio_authority_case3", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    errors = mod.validate_task_note(task, strict=True)
    assert errors == []
