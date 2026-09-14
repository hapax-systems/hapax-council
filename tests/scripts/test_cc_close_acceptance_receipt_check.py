"""Acceptance-receipt closure gate (routing Phase 0.2).

cc-close must BLOCK closing a receipt-ARMED task as ``done`` unless a signed
acceptance receipt — acceptor, verdict, timestamp, artifact — exists beside the
note as ``<task_id>.acceptance.yaml`` with verdict ``accepted``.

Armed = the ``frontier_review_required`` floor OR a declared
``review_requirement.independent_review_required`` (each read top-level and in
the ``route_metadata`` mirror). Not floor-only: a row may demand independent
review under any floor. Only a row with neither declaration is untouched.

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
    independent_review_required: bool | None = None,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{task_id}.md"
    review_block = ""
    if independent_review_required is not None:
        review_block = textwrap.dedent(
            f"""\
            review_requirement:
              support_artifact_allowed: true
              independent_review_required: {str(independent_review_required).lower()}
              authoritative_acceptor_profile: frontier_full
            """
        )
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
            """
        )
        + review_block
        + textwrap.dedent(
            f"""\
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


class TestIndependentReviewRequirement:
    """``review_requirement.independent_review_required`` must be load-bearing.

    Measured defect 2026-09-13T21:53Z: ``openchamber-bounded-pilot-20260913``
    carried ``quality_floor: verification_receipt`` together with
    ``review_requirement.independent_review_required: true`` and closed on the
    first plain ``cc-close`` with no acceptance receipt and no review. The
    receipt gate keyed solely on the ``frontier_review_required`` floor, so a
    row could declare independent review mandatory and close without it — a
    control that reads as protective and is not load-bearing.
    """

    def test_blocks_verification_receipt_floor_when_independent_review_required(
        self, tmp_path: Path
    ) -> None:
        """The epsilon case: non-review floor + independent review demanded."""
        checker = _load_checker()
        note = _write_note(
            tmp_path,
            "task-v",
            quality_floor="verification_receipt",
            independent_review_required=True,
        )

        code, message = checker.gate(note)

        assert code == 2
        assert "missing_acceptance_receipt" in message

    def test_refusal_names_the_review_requirement_not_just_the_receipt(
        self, tmp_path: Path
    ) -> None:
        """executive_function: the refusal must say WHY the gate applies.

        A lane reading a generic receipt error on a ``verification_receipt``
        row cannot tell whether the gate misfired or its own row demands
        review, so the message has to name the requirement that triggered it.
        """
        checker = _load_checker()
        note = _write_note(
            tmp_path,
            "task-v",
            quality_floor="verification_receipt",
            independent_review_required=True,
        )

        _, message = checker.gate(note)

        assert "independent_review_required" in message

    def test_passes_when_independent_review_required_and_receipt_present(
        self, tmp_path: Path
    ) -> None:
        checker = _load_checker()
        note = _write_note(
            tmp_path,
            "task-v",
            quality_floor="verification_receipt",
            independent_review_required=True,
        )
        (tmp_path / "task-v.acceptance.yaml").write_text(VALID_RECEIPT, encoding="utf-8")

        code, _ = checker.gate(note)

        assert code == 0

    def test_independent_review_false_does_not_arm_the_gate(self, tmp_path: Path) -> None:
        """Explicit ``false`` must stay a pass — this widens enforcement, not scope."""
        checker = _load_checker()
        note = _write_note(
            tmp_path,
            "task-n",
            quality_floor="verification_receipt",
            independent_review_required=False,
        )

        code, _ = checker.gate(note)

        assert code == 0

    def test_absent_review_requirement_block_does_not_arm_the_gate(self, tmp_path: Path) -> None:
        """Regression: rows with no review_requirement at all close as before."""
        checker = _load_checker()
        note = _write_note(tmp_path, "task-n", quality_floor="verification_receipt")

        code, _ = checker.gate(note)

        assert code == 0

    def test_frontier_floor_refusal_still_names_the_floor(self, tmp_path: Path) -> None:
        """Requirement 4: frontier_review_required behaviour is unchanged.

        Both triggers share one receipt path, so this pins that widening the
        trigger did not rewrite the original refusal's wording.
        """
        checker = _load_checker()
        note = _write_note(tmp_path, "task-r")

        code, message = checker.gate(note)

        assert code == 2
        assert "missing_acceptance_receipt" in message
        assert "frontier_review_required" in message

    def test_schema_truthy_string_arms_the_gate(self, tmp_path: Path) -> None:
        """The critical: a schema-valid demand spelled as a string must arm.

        ``ReviewRequirement.independent_review_required`` is a coercing pydantic
        ``bool``, so ``"true"`` validates as demanding review. The gate reads raw
        frontmatter, where it is the string ``'true'`` — an identity test against
        Python ``True`` let exactly this row close unreviewed.
        """
        checker = _load_checker()
        note = tmp_path / "task-s.md"
        note.write_text(
            textwrap.dedent(
                """\
                ---
                type: cc-task
                task_id: task-s
                status: in_progress
                quality_floor: verification_receipt
                review_requirement:
                  independent_review_required: "true"
                ---

                # task-s
                """
            ),
            encoding="utf-8",
        )

        code, message = checker.gate(note)

        assert code == 2
        assert "independent_review_required" in message

    def test_malformed_declaration_arms_and_says_so(self, tmp_path: Path) -> None:
        """An unreadable requirement must not read as no requirement."""
        checker = _load_checker()
        note = tmp_path / "task-m.md"
        note.write_text(
            textwrap.dedent(
                """\
                ---
                type: cc-task
                task_id: task-m
                status: in_progress
                quality_floor: verification_receipt
                review_requirement:
                  independent_review_required: maybe
                ---

                # task-m
                """
            ),
            encoding="utf-8",
        )

        code, message = checker.gate(note)

        assert code == 2
        assert "malformed" in message
        assert "not a recognized" in message

    def test_malformed_container_refusal_does_not_blame_the_flag(self, tmp_path: Path) -> None:
        """The flag may be valid; the enclosing shape is the failure.

        For ``review_requirement: [{independent_review_required: true}]`` the
        value is already ``true``. Telling the operator to fix it sends them to
        change something correct.
        """
        checker = _load_checker()
        note = tmp_path / "task-c.md"
        note.write_text(
            textwrap.dedent(
                """\
                ---
                type: cc-task
                task_id: task-c
                status: in_progress
                quality_floor: verification_receipt
                review_requirement:
                  - independent_review_required: true
                ---

                # task-c
                """
            ),
            encoding="utf-8",
        )

        code, message = checker.gate(note)

        assert code == 2
        assert "malformed_container" in message
        assert "is not a" in message and "mapping" in message
        assert "do not change the" in message
        # The flag-value diagnosis must NOT appear: it would misdirect the fix.
        assert "not a recognized boolean" not in message

    def test_combined_triggers_emit_both_sentences(self, tmp_path: Path) -> None:
        """Legibility: a row armed twice is told both reasons."""
        checker = _load_checker()
        note = _write_note(
            tmp_path,
            "task-b",
            quality_floor="frontier_review_required",
            independent_review_required=True,
        )

        _, message = checker.gate(note)

        assert "quality_floor is frontier_review_required" in message
        assert "independent_review_required" in message

    def test_refusal_names_the_sanctioned_bypass(self, tmp_path: Path) -> None:
        """A newly load-bearing gate must name its escape hatch."""
        checker = _load_checker()
        note = _write_note(
            tmp_path,
            "task-v",
            quality_floor="verification_receipt",
            independent_review_required=True,
        )

        _, message = checker.gate(note)

        assert "HAPAX_ACCEPTANCE_RECEIPT_GATE_OFF" in message

    def test_both_triggers_share_the_receipt_path(self, tmp_path: Path) -> None:
        """The shared-path test: one receipt satisfies either trigger."""
        checker = _load_checker()
        floor_note = _write_note(tmp_path / "a", "task-r")
        (tmp_path / "a" / "task-r.acceptance.yaml").write_text(VALID_RECEIPT, encoding="utf-8")
        review_note = _write_note(
            tmp_path / "b",
            "task-v",
            quality_floor="verification_receipt",
            independent_review_required=True,
        )
        (tmp_path / "b" / "task-v.acceptance.yaml").write_text(VALID_RECEIPT, encoding="utf-8")

        assert checker.gate(floor_note)[0] == 0
        assert checker.gate(review_note)[0] == 0


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

    def test_cc_close_blocks_independent_review_row_under_non_review_floor(
        self, tmp_path: Path
    ) -> None:
        """The demonstrated acceptance criterion, end to end.

        Reproduces ``openchamber-bounded-pilot-20260913`` exactly: a
        ``verification_receipt`` row demanding independent review, closed with
        a plain ``cc-close`` and no bypass. Before the fix this returned 0 and
        moved the note to closed/ with no receipt and no review.
        """
        home = tmp_path / "home"
        vault = _vault(home)
        _write_note(
            vault / "active",
            "task-v",
            quality_floor="verification_receipt",
            independent_review_required=True,
        )

        result = _run_close(home, "task-v")

        assert result.returncode != 0
        assert "missing_acceptance_receipt" in result.stderr
        assert "independent_review_required" in result.stderr
        assert (vault / "active" / "task-v.md").exists()
        assert not (vault / "closed" / "task-v.md").exists()

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
        env.update(HOME=str(home), HAPAX_AGENT_ROLE="test-role")
        result = subprocess.run(
            ["bash", str(CC_CLOSE), "task-r", "--status", "withdrawn"],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert (vault / "closed" / "task-r.md").exists()
