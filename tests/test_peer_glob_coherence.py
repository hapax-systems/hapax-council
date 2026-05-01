"""Tests for the peer-glob coherence lint (P-8).

Verifies the lint passes against the live repo, and that synthesized
drift fixtures fail with a useful error message. Self-contained per
project conventions (no shared conftest fixtures).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LINT_SCRIPT = REPO_ROOT / "scripts" / "check-peer-glob-coherence.py"

COHERENT_BODY = (
    "#!/usr/bin/env bash\n"
    'for c in "$vault_root/active/$task_id-"*.md; do :; done\n'
    'if [[ -f "$vault_root/active/$task_id.md" ]]; then :; fi\n'
)


def _run_lint(repo_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(LINT_SCRIPT), "--repo-root", str(repo_root)],
        capture_output=True,
        text=True,
        check=False,
    )


def _seed_coherent_repo(root: Path) -> None:
    (root / "scripts").mkdir(parents=True)
    (root / "hooks" / "scripts").mkdir(parents=True)
    for relpath in (
        "scripts/cc-claim",
        "scripts/cc-close",
        "hooks/scripts/cc-task-gate.sh",
    ):
        (root / relpath).write_text(COHERENT_BODY, encoding="utf-8")


def test_lint_passes_against_current_repo() -> None:
    """Pin: cc-claim, cc-close, and cc-task-gate.sh stay coherent on main."""

    proc = _run_lint(REPO_ROOT)
    assert proc.returncode == 0, (
        f"lint failed against the live repo:\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
    assert "all coherent" in proc.stdout


def test_lint_passes_on_coherent_fixture(tmp_path: Path) -> None:
    """Drift-detector negative control: identical patterns → green."""

    _seed_coherent_repo(tmp_path)
    proc = _run_lint(tmp_path)
    assert proc.returncode == 0
    assert "all coherent" in proc.stdout


def test_lint_detects_missing_dash_drift(tmp_path: Path) -> None:
    """Primary glob without dash (`$task_id*.md`) should fail."""

    _seed_coherent_repo(tmp_path)
    drifted = (
        "#!/usr/bin/env bash\n"
        'for c in "$vault_root/active/$task_id"*.md; do :; done\n'
        'if [[ -f "$vault_root/active/$task_id.md" ]]; then :; fi\n'
    )
    (tmp_path / "scripts" / "cc-claim").write_text(drifted, encoding="utf-8")

    proc = _run_lint(tmp_path)

    assert proc.returncode == 1
    assert "scripts/cc-claim" in proc.stderr
    assert "missing primary glob" in proc.stderr


def test_lint_detects_missing_fallback_drift(tmp_path: Path) -> None:
    """Primary present but bare ``$task_id.md`` fallback missing → fail."""

    _seed_coherent_repo(tmp_path)
    drifted = '#!/usr/bin/env bash\nfor c in "$vault_root/active/$task_id-"*.md; do :; done\n'
    (tmp_path / "scripts" / "cc-close").write_text(drifted, encoding="utf-8")

    proc = _run_lint(tmp_path)

    assert proc.returncode == 1
    assert "scripts/cc-close" in proc.stderr
    assert "missing fallback" in proc.stderr


def test_lint_detects_missing_member_file(tmp_path: Path) -> None:
    """A peer-group member that doesn't exist at all is still flagged."""

    (tmp_path / "scripts").mkdir(parents=True)
    (tmp_path / "hooks" / "scripts").mkdir(parents=True)
    # Only seed two of the three members.
    (tmp_path / "scripts" / "cc-claim").write_text(COHERENT_BODY, encoding="utf-8")
    (tmp_path / "scripts" / "cc-close").write_text(COHERENT_BODY, encoding="utf-8")

    proc = _run_lint(tmp_path)

    assert proc.returncode == 1
    assert "hooks/scripts/cc-task-gate.sh" in proc.stderr
    assert "file missing" in proc.stderr


def test_lint_reports_all_drift_in_one_run(tmp_path: Path) -> None:
    """Multiple drifted members produce all errors in one run, not just the first."""

    _seed_coherent_repo(tmp_path)
    drifted_no_primary = (
        "#!/usr/bin/env bash\n"
        'for c in "$vault_root/active/$task_id"*.md; do :; done\n'
        'if [[ -f "$vault_root/active/$task_id.md" ]]; then :; fi\n'
    )
    drifted_no_fallback = (
        '#!/usr/bin/env bash\nfor c in "$vault_root/active/$task_id-"*.md; do :; done\n'
    )
    (tmp_path / "scripts" / "cc-claim").write_text(drifted_no_primary, encoding="utf-8")
    (tmp_path / "scripts" / "cc-close").write_text(drifted_no_fallback, encoding="utf-8")

    proc = _run_lint(tmp_path)

    assert proc.returncode == 1
    assert "scripts/cc-claim" in proc.stderr
    assert "scripts/cc-close" in proc.stderr
    assert "missing primary glob" in proc.stderr
    assert "missing fallback" in proc.stderr
