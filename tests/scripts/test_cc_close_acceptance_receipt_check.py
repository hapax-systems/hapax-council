"""Acceptance-receipt closure gate (routing Phase 0.2).

cc-close must BLOCK closing a frontier_review_required (review-floor) task
as ``done`` unless a signed acceptance receipt — acceptor, verdict,
timestamp, artifact — exists beside the note as ``<task_id>.acceptance.yaml``
with verdict ``accepted``. Non-review-floor closures are untouched.

Covers both surfaces:
- ``scripts/cc-close-acceptance-receipt-check.py`` gate() unit behavior
- ``scripts/cc-close`` end-to-end (the demonstrated acceptance criterion)
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import textwrap
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
CC_CLOSE = REPO_ROOT / "scripts" / "cc-close"
CHECKER = REPO_ROOT / "scripts" / "cc-close-acceptance-receipt-check.py"

VALID_RECEIPT = textwrap.dedent(
    """\
    acceptor: operator
    verdict: accepted
    timestamp: 2026-06-10T17:00:00Z
    artifact: https://github.com/hapax-systems/hapax-council/pull/4100
    """
)


def _load_checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("cc_close_acceptance_receipt_check", CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_note(
    directory: Path,
    task_id: str,
    *,
    quality_floor: str = "frontier_review_required",
    status: str = "in_progress",
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{task_id}.md"
    path.write_text(
        textwrap.dedent(
            f"""\
            ---
            type: cc-task
            task_id: {task_id}
            title: "{task_id}"
            status: {status}
            assigned_to: test-role
            quality_floor: {quality_floor}
            completed_at:
            updated_at:
            pr:
            ---

            # {task_id}

            ## Session log
            """
        ),
        encoding="utf-8",
    )
    return path


class TestCheckerGate:
    def test_blocks_review_floor_note_without_receipt(self, tmp_path: Path) -> None:
        checker = _load_checker()
        note = _write_note(tmp_path, "task-r")

        code, message = checker.gate(note)

        assert code == 2
        assert "missing_acceptance_receipt" in message
        assert "task-r.acceptance.yaml" in message

    def test_passes_review_floor_note_with_valid_receipt(self, tmp_path: Path) -> None:
        checker = _load_checker()
        note = _write_note(tmp_path, "task-r")
        (tmp_path / "task-r.acceptance.yaml").write_text(VALID_RECEIPT, encoding="utf-8")

        code, _ = checker.gate(note)

        assert code == 0

    def test_blocks_rejected_verdict(self, tmp_path: Path) -> None:
        checker = _load_checker()
        note = _write_note(tmp_path, "task-r")
        (tmp_path / "task-r.acceptance.yaml").write_text(
            VALID_RECEIPT.replace("verdict: accepted", "verdict: rejected"),
            encoding="utf-8",
        )

        code, message = checker.gate(note)

        assert code == 2
        assert "acceptance_receipt_verdict_not_accepted:rejected" in message

    def test_passes_non_review_floor_note_without_receipt(self, tmp_path: Path) -> None:
        checker = _load_checker()
        note = _write_note(tmp_path, "task-n", quality_floor="frontier_required")

        code, _ = checker.gate(note)

        assert code == 0

    def test_bypass_env_disables_gate(self, tmp_path: Path, monkeypatch: object) -> None:
        checker = _load_checker()
        note = _write_note(tmp_path, "task-r")
        monkeypatch.setenv("HAPAX_ACCEPTANCE_RECEIPT_GATE_OFF", "1")  # type: ignore[attr-defined]

        code, message = checker.gate(note)

        assert code == 0
        assert "HAPAX_ACCEPTANCE_RECEIPT_GATE_OFF" in message

    def test_fails_open_on_missing_note(self, tmp_path: Path) -> None:
        checker = _load_checker()

        code, message = checker.gate(tmp_path / "absent.md")

        assert code == 0
        assert "fail-OPEN" in message


def _vault(home: Path) -> Path:
    root = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    (root / "active").mkdir(parents=True, exist_ok=True)
    (root / "closed").mkdir(parents=True, exist_ok=True)
    return root


def _run_close(home: Path, task_id: str, **extra_env: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("HAPAX_ACCEPTANCE_RECEIPT_GATE_OFF", None)
    env.update(
        HOME=str(home),
        HAPAX_AGENT_NAME="test-role",
        HAPAX_AGENT_ROLE="test-role",
        # Neutralize unrelated done-path gates so this file tests ONLY the
        # acceptance-receipt gate end-to-end.
        HAPAX_RAPID_CLOSE_OFF="1",
        HAPAX_PR_MERGE_GATE_OFF="1",
        HAPAX_ARTIFACT_DISPOSITION_GATE_OFF="1",
        HAPAX_CC_HYGIENE_OFF="1",
        **extra_env,
    )
    return subprocess.run(
        ["bash", str(CC_CLOSE), task_id, "--status", "done"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


class TestCcCloseEndToEnd:
    def test_cc_close_blocks_review_floor_task_without_receipt(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        vault = _vault(home)
        _write_note(vault / "active", "task-r")

        result = _run_close(home, "task-r")

        assert result.returncode != 0
        assert "missing_acceptance_receipt" in result.stderr
        assert (vault / "active" / "task-r.md").exists()
        assert not (vault / "closed" / "task-r.md").exists()

    def test_cc_close_closes_review_floor_task_with_receipt_and_moves_it(
        self, tmp_path: Path
    ) -> None:
        home = tmp_path / "home"
        vault = _vault(home)
        _write_note(vault / "active", "task-r")
        (vault / "active" / "task-r.acceptance.yaml").write_text(VALID_RECEIPT, encoding="utf-8")

        result = _run_close(home, "task-r")

        assert result.returncode == 0, result.stderr
        assert (vault / "closed" / "task-r.md").exists()
        # The receipt travels with the note so it stays "alongside".
        assert (vault / "closed" / "task-r.acceptance.yaml").exists()
        assert not (vault / "active" / "task-r.acceptance.yaml").exists()

    def test_cc_close_unaffected_for_non_review_floor_task(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        vault = _vault(home)
        _write_note(vault / "active", "task-n", quality_floor="frontier_required")

        result = _run_close(home, "task-n")

        assert result.returncode == 0, result.stderr
        assert (vault / "closed" / "task-n.md").exists()

    def test_cc_close_withdrawn_skips_receipt_gate(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        vault = _vault(home)
        _write_note(vault / "active", "task-r")
        env = os.environ.copy()
        env.update(
            HOME=str(home),
            HAPAX_AGENT_NAME="test-role",
            HAPAX_AGENT_ROLE="test-role",
        )
        result = subprocess.run(
            ["bash", str(CC_CLOSE), "task-r", "--status", "withdrawn"],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert (vault / "closed" / "task-r.md").exists()
