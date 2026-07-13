"""Acceptance-receipt closure gate (routing Phase 0.2).

cc-close must BLOCK closing a frontier_review_required (review-floor) task
as ``done`` unless a signed acceptance receipt — acceptor, verdict,
timestamp, artifact — exists beside the note as ``<task_id>.acceptance.yaml``
with verdict ``accepted``. Non-review-floor closures are untouched.

This module covers the pure checker. Governed terminal-close integration is
tested through ``shared.sdlc_close``; the retired shell mutation path is not a
valid acceptance-receipt integration surface.
"""

from __future__ import annotations

import importlib.util
import textwrap
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
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

    def test_canon_bound_close_uses_the_ordinary_acceptance_receipt_contract(
        self, tmp_path: Path, monkeypatch: object
    ) -> None:
        checker = _load_checker()
        note = _write_note(tmp_path, "task-close")
        (tmp_path / "task-close.acceptance.yaml").write_text(
            VALID_RECEIPT,
            encoding="utf-8",
        )
        monkeypatch.setenv("HAPAX_CANON_BOUND_CLOSE_ENFORCEMENT", "1")  # type: ignore[attr-defined]

        code, message = checker.gate(note)

        assert code == 0, message
        assert "valid acceptance receipt" in message

    def test_canon_bound_close_ignores_raw_bypass(
        self, tmp_path: Path, monkeypatch: object
    ) -> None:
        checker = _load_checker()
        note = _write_note(tmp_path, "task-close")
        monkeypatch.setenv("HAPAX_CANON_BOUND_CLOSE_ENFORCEMENT", "1")  # type: ignore[attr-defined]
        monkeypatch.setenv("HAPAX_ACCEPTANCE_RECEIPT_GATE_OFF", "1")  # type: ignore[attr-defined]

        code, message = checker.gate(note)

        assert code == 2
        assert "missing_acceptance_receipt" in message
        assert "raw bypass is ignored" in message

    def test_canon_bound_non_review_floor_does_not_invent_a_receipt_contract(
        self, tmp_path: Path, monkeypatch: object
    ) -> None:
        checker = _load_checker()
        note = _write_note(tmp_path, "task-close", quality_floor="frontier_required")
        monkeypatch.setenv("HAPAX_CANON_BOUND_CLOSE_ENFORCEMENT", "1")  # type: ignore[attr-defined]

        code, message = checker.gate(note)

        assert code == 0
        assert "does not apply" in message

    def test_canon_bound_close_fails_closed_on_missing_note(
        self, tmp_path: Path, monkeypatch: object
    ) -> None:
        checker = _load_checker()
        monkeypatch.setenv("HAPAX_CANON_BOUND_CLOSE_ENFORCEMENT", "1")  # type: ignore[attr-defined]

        code, message = checker.gate(tmp_path / "absent.md")

        assert code == 2
        assert "fail-CLOSED" in message
