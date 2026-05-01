"""Tests for hooks/scripts/session-summary.sh.

The hook is a Stop hook (one-shot at session end) that reads
``$HOME/.cache/axiom-audit/<today>.jsonl`` and emits a one-line summary
of how many axiom-audit edits were tracked. Stdout-only; never blocks.
The hook was untested.
"""

from __future__ import annotations

import datetime as _dt
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "session-summary.sh"


def _today() -> str:
    return _dt.date.today().isoformat()


def _run(home: Path) -> subprocess.CompletedProcess[str]:
    """Run the hook with HOME pointed at ``home`` so the audit-file lookup
    is sandboxed (the production hook reads $HOME/.cache/axiom-audit/...)."""
    return subprocess.run(
        ["bash", str(HOOK)],
        env={"PATH": "/usr/bin:/bin", "HOME": str(home)},
        capture_output=True,
        text=True,
        check=False,
    )


def _seed_audit(home: Path, lines: int) -> Path:
    """Create the day's audit jsonl with ``lines`` entries under ``home``."""
    audit_dir = home / ".cache" / "axiom-audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_file = audit_dir / f"{_today()}.jsonl"
    audit_file.write_text("".join(f'{{"i":{i}}}\n' for i in range(lines)))
    return audit_file


# ── Empty / no-activity path ────────────────────────────────────────


class TestNoActivity:
    def test_emits_no_activity_when_dir_absent(self, tmp_path: Path) -> None:
        result = _run(tmp_path)
        assert result.returncode == 0
        assert "no activity logged" in result.stdout

    def test_emits_no_activity_when_today_file_absent(self, tmp_path: Path) -> None:
        """Even with the audit dir present, an absent today-file → no-activity."""
        (tmp_path / ".cache" / "axiom-audit").mkdir(parents=True)
        (tmp_path / ".cache" / "axiom-audit" / "2024-01-01.jsonl").write_text("old\n")
        result = _run(tmp_path)
        assert result.returncode == 0
        assert "no activity logged" in result.stdout


# ── Active path: today's audit file present ────────────────────────


class TestActiveSummary:
    def test_reports_count_for_one_edit(self, tmp_path: Path) -> None:
        _seed_audit(tmp_path, 1)
        result = _run(tmp_path)
        assert result.returncode == 0
        assert "1 edits tracked" in result.stdout

    def test_reports_count_for_many_edits(self, tmp_path: Path) -> None:
        _seed_audit(tmp_path, 42)
        result = _run(tmp_path)
        assert result.returncode == 0
        assert "42 edits tracked" in result.stdout

    def test_reports_zero_for_empty_audit_file(self, tmp_path: Path) -> None:
        """An empty file (created but never written to) → 0 edits."""
        _seed_audit(tmp_path, 0)
        result = _run(tmp_path)
        assert result.returncode == 0
        assert "0 edits tracked" in result.stdout


# ── Hook integrity ─────────────────────────────────────────────────


class TestHookIntegrity:
    def test_hook_is_executable(self) -> None:
        import os

        assert os.access(HOOK, os.X_OK)

    def test_hook_uses_bash_shebang(self) -> None:
        body = HOOK.read_text(encoding="utf-8")
        assert body.startswith("#!/usr/bin/env bash")

    def test_hook_never_blocks(self) -> None:
        """Stop hook is informational; pin that no exit lines are non-zero."""
        body = HOOK.read_text(encoding="utf-8")
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith("exit "):
                assert stripped.endswith("0"), f"Stop hook must only exit 0: {line!r}"
