"""V5 weave wk1 d4 — polysemic-audit CI gate verify script (epsilon).

Pins the behavior of ``scripts/verify-polysemic-audit.py``: walks
artifact directories + invokes ``audit_artifact()`` per file +
exit-1 on any concern. Mirrors the
``tests/governance/test_verify_redaction_transforms.py`` shape.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "verify-polysemic-audit.py"


def _run(*paths: Path) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(SCRIPT)]
    if paths:
        cmd.extend(["--paths", *(str(p) for p in paths)])
    return subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT)


class TestScriptExists:
    def test_script_present(self) -> None:
        assert SCRIPT.exists()

    def test_script_executable_via_python(self) -> None:
        result = _run()
        # Either passes (no artifacts or all clean) or fails with
        # well-formed exit code 1; never crashes (no Python tracebacks).
        assert result.returncode in (0, 1), result.stderr


class TestEmptyDirectory:
    def test_empty_dir_passes(self, tmp_path: Path) -> None:
        result = _run(tmp_path)
        assert result.returncode == 0
        assert "no artifacts" in result.stdout.lower() or "passed" in result.stdout.lower()


class TestCleanArtifact:
    def test_single_register_artifact_passes(self, tmp_path: Path) -> None:
        # All-AI register; no legal/safety cross-domain.
        (tmp_path / "ok.md").write_text(
            "Model governance and prompt governance are the orchestrator layers.",
            encoding="utf-8",
        )
        result = _run(tmp_path)
        assert result.returncode == 0


class TestFlaggedArtifact:
    def test_cross_domain_artifact_fails(self, tmp_path: Path) -> None:
        # Legal + AI proximity for "compliance" — should flag.
        (tmp_path / "bad.md").write_text(
            "GDPR compliance and HIPAA compliance govern our data flows. "
            "The model's compliance with operator directives is gate-enforced.",
            encoding="utf-8",
        )
        result = _run(tmp_path)
        assert result.returncode == 1
        assert "compliance" in (result.stdout + result.stderr).lower()


class TestProductionArtifactsClean:
    """Pin: the artifacts already in ``docs/audience/`` pass the
    audit. Catches regressions if a future doc PR introduces
    cross-domain proximity without explicit register-shift.

    Skips gracefully when ``docs/audience/`` doesn't exist yet
    (eg. on a freshly-cloned worktree)."""

    def test_production_audience_passes(self) -> None:
        audience_dir = REPO_ROOT / "docs" / "audience"
        if not audience_dir.is_dir():
            return
        result = _run(audience_dir)
        assert result.returncode == 0, (
            f"Production docs/audience/ has polysemic-audit concerns:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
