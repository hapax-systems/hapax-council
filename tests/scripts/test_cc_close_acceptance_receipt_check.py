"""Acceptance-receipt closure gate (routing Phase 0.2).

cc-close must BLOCK closing a frontier_review_required (review-floor) task
as ``done`` unless a signed acceptance receipt — acceptor, verdict,
timestamp, artifact — exists beside the note as ``<task_id>.acceptance.yaml``
with verdict ``accepted``. Non-review-floor closures are untouched.

A note that EXISTS but cannot be read is not an absent one: it may declare
the review floor, so the gate fails CLOSED on an unreadable note and names
the case. Only a genuinely missing note fails open (no note, no task).

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

import pytest

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

    def test_missing_note_pass_names_the_missing_case(self, tmp_path: Path) -> None:
        # Requirement 3: the pass must name which case occurred, so the operator
        # can tell absence from corruption.
        checker = _load_checker()

        code, message = checker.gate(tmp_path / "absent.md")

        assert code == 0
        assert "missing" in message
        assert "unreadable" not in message

    def test_fails_closed_on_unreadable_note(self, tmp_path: Path, monkeypatch: object) -> None:
        """A present-but-unreadable note must never read as absent.

        The rest of the module already applies that rule — to the receipt, to
        the flag value, to route_metadata, to the frontmatter document; the note
        file was the one exception, and an unreadable review-floor row closed
        unreviewed (cc-close-gate-unreadable-note-fail-open-20260914). Simulated
        OSError witness: the transient-NFS shape.
        """
        checker = _load_checker()
        note = _write_note(tmp_path, "task-r")
        real_read_text = Path.read_text

        def _deny_note(self: Path, *args: object, **kwargs: object) -> str:
            if self == note:
                raise PermissionError(13, "Permission denied", str(self))
            return real_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", _deny_note)  # type: ignore[attr-defined]

        code, message = checker.gate(note)

        assert code == 2
        assert "unreadable" in message
        assert "missing" not in message
        assert str(note) in message
        # The refusal must carry its own next action (executive_function).
        assert "HAPAX_ACCEPTANCE_RECEIPT_GATE_OFF" in message

    def test_fails_closed_on_permission_denied_note(self, tmp_path: Path) -> None:
        """The permissions witness: mode-000 is the shape an ACL/NFS denial takes."""
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            pytest.skip("root reads through permission bits — no denial to witness")
        checker = _load_checker()
        note = _write_note(tmp_path, "task-r")
        note.chmod(0)

        code, message = checker.gate(note)

        assert code == 2
        assert "unreadable" in message


HEAD_A = "a" * 40
HEAD_B = "b" * 40
PR_REPO = "hapax-systems/hapax-council"


def _write_pr_note(
    directory: Path, task_id: str, *, pr: str = "4668", pr_repo: str = PR_REPO
) -> Path:
    note = _write_note(directory, task_id)
    text = note.read_text(encoding="utf-8").replace("pr:\n", f"pr: {pr}\npr_repo: {pr_repo}\n", 1)
    note.write_text(text, encoding="utf-8")
    return note


def _bound_receipt(*, head_sha: str | None = HEAD_A, pr: str | None = "4668") -> str:
    lines = [VALID_RECEIPT.rstrip("\n")]
    if pr is not None:
        lines.append(f"pr: {pr}")
    if head_sha is not None:
        lines.append(f"head_sha: {head_sha}")
    return "\n".join(lines) + "\n"


class _Lookup:
    """Records every PR-head lookup so a test can assert the network was (not) consulted."""

    def __init__(self, head: str | None) -> None:
        self.head = head
        self.calls: list[tuple[str, str]] = []

    def __call__(self, pr_number: str, repo: str) -> str | None:
        self.calls.append((pr_number, repo))
        return self.head


class TestReceiptHeadBinding:
    """A receipt accepts ONE revision; a later head of the same PR is unreviewed.

    Measured on PR 4668: a round-1 receipt satisfied cc-close twenty review rounds
    later, because the gate never read head_sha.
    """

    def test_stale_head_receipt_refuses(self, tmp_path: Path) -> None:
        checker = _load_checker()
        note = _write_pr_note(tmp_path, "task-r")
        (tmp_path / "task-r.acceptance.yaml").write_text(_bound_receipt(), encoding="utf-8")
        lookup = _Lookup(HEAD_B)

        code, message = checker.gate(note, head_lookup=lookup)

        assert code == 2
        assert f"acceptance_receipt_stale_head:receipt={HEAD_A}:current={HEAD_B}" in message
        assert "re-run acceptance on the current head" in message
        assert lookup.calls == [("4668", PR_REPO)]

    def test_fresh_head_receipt_passes(self, tmp_path: Path) -> None:
        checker = _load_checker()
        note = _write_pr_note(tmp_path, "task-r")
        (tmp_path / "task-r.acceptance.yaml").write_text(_bound_receipt(), encoding="utf-8")

        code, message = checker.gate(note, head_lookup=_Lookup(HEAD_A))

        assert code == 0, message
        assert HEAD_A[:12] in message

    def test_head_comparison_ignores_hex_case(self, tmp_path: Path) -> None:
        checker = _load_checker()
        note = _write_pr_note(tmp_path, "task-r")
        (tmp_path / "task-r.acceptance.yaml").write_text(
            _bound_receipt(head_sha=HEAD_A.upper()), encoding="utf-8"
        )

        code, message = checker.gate(note, head_lookup=_Lookup(HEAD_A))

        assert code == 0, message

    def test_missing_head_sha_refuses_when_pr_declared(self, tmp_path: Path) -> None:
        checker = _load_checker()
        note = _write_pr_note(tmp_path, "task-r")
        (tmp_path / "task-r.acceptance.yaml").write_text(
            _bound_receipt(head_sha=None), encoding="utf-8"
        )
        lookup = _Lookup(HEAD_A)

        code, message = checker.gate(note, head_lookup=lookup)

        assert code == 2
        assert "acceptance_receipt_missing_field:head_sha" in message
        assert lookup.calls == []

    def test_abbreviated_head_sha_refuses(self, tmp_path: Path) -> None:
        checker = _load_checker()
        note = _write_pr_note(tmp_path, "task-r")
        (tmp_path / "task-r.acceptance.yaml").write_text(
            _bound_receipt(head_sha=HEAD_A[:9]), encoding="utf-8"
        )

        code, message = checker.gate(note, head_lookup=_Lookup(HEAD_A))

        assert code == 2
        assert f"acceptance_receipt_head_sha_malformed:{HEAD_A[:9]}" in message

    def test_receipt_for_another_pr_refuses(self, tmp_path: Path) -> None:
        checker = _load_checker()
        note = _write_pr_note(tmp_path, "task-r", pr="4668")
        (tmp_path / "task-r.acceptance.yaml").write_text(
            _bound_receipt(pr="4669"), encoding="utf-8"
        )

        code, message = checker.gate(note, head_lookup=_Lookup(HEAD_A))

        assert code == 2
        assert "acceptance_receipt_pr_mismatch:receipt=4669:task=4668" in message

    def test_unverifiable_current_head_refuses(self, tmp_path: Path) -> None:
        checker = _load_checker()
        note = _write_pr_note(tmp_path, "task-r")
        (tmp_path / "task-r.acceptance.yaml").write_text(_bound_receipt(), encoding="utf-8")

        code, message = checker.gate(note, head_lookup=_Lookup(None))

        assert code == 2
        assert f"acceptance_receipt_current_head_unverifiable:{PR_REPO}#4668" in message

    def test_malformed_lookup_answer_is_unverifiable_not_a_match(self, tmp_path: Path) -> None:
        checker = _load_checker()
        note = _write_pr_note(tmp_path, "task-r")
        (tmp_path / "task-r.acceptance.yaml").write_text(_bound_receipt(), encoding="utf-8")

        code, message = checker.gate(note, head_lookup=_Lookup(""))

        assert code == 2
        assert "acceptance_receipt_current_head_unverifiable" in message

    def test_missing_pr_repo_refuses_without_guessing(self, tmp_path: Path) -> None:
        checker = _load_checker()
        note = _write_pr_note(tmp_path, "task-r", pr_repo="null")
        (tmp_path / "task-r.acceptance.yaml").write_text(_bound_receipt(), encoding="utf-8")
        lookup = _Lookup(HEAD_A)

        code, message = checker.gate(note, head_lookup=lookup)

        assert code == 2
        assert "acceptance_receipt_pr_repo_missing" in message
        assert lookup.calls == []

    def test_receipt_pr_binds_when_note_declares_none(self, tmp_path: Path) -> None:
        checker = _load_checker()
        note = _write_note(tmp_path, "task-r")
        (tmp_path / "task-r.acceptance.yaml").write_text(_bound_receipt(), encoding="utf-8")
        lookup = _Lookup(HEAD_B)

        code, message = checker.gate(note, cli_repo=PR_REPO, head_lookup=lookup)

        assert code == 2
        assert "acceptance_receipt_stale_head" in message
        assert lookup.calls == [("4668", PR_REPO)]

    def test_cli_pr_binds_when_note_declares_none(self, tmp_path: Path) -> None:
        checker = _load_checker()
        note = _write_note(tmp_path, "task-r")
        (tmp_path / "task-r.acceptance.yaml").write_text(VALID_RECEIPT, encoding="utf-8")

        code, message = checker.gate(
            note, cli_pr="4668", cli_repo=PR_REPO, head_lookup=_Lookup(HEAD_A)
        )

        assert code == 2
        assert "acceptance_receipt_missing_field:head_sha" in message

    def test_pr_less_row_passes_and_says_why(self, tmp_path: Path) -> None:
        checker = _load_checker()
        note = _write_note(tmp_path, "task-r")
        (tmp_path / "task-r.acceptance.yaml").write_text(VALID_RECEIPT, encoding="utf-8")
        lookup = _Lookup(HEAD_A)

        code, message = checker.gate(note, head_lookup=lookup)

        assert code == 0
        assert "no PR declared" in message
        assert lookup.calls == []

    def test_malformed_pr_number_refuses_without_lookup(self, tmp_path: Path) -> None:
        checker = _load_checker()
        note = _write_pr_note(tmp_path, "task-r", pr="12x")
        (tmp_path / "task-r.acceptance.yaml").write_text(_bound_receipt(pr=None), encoding="utf-8")
        lookup = _Lookup(HEAD_A)

        code, message = checker.gate(note, head_lookup=lookup)

        assert code == 2
        assert "acceptance_receipt_pr_malformed:12x" in message
        assert lookup.calls == []

    def test_malformed_pr_repo_refuses_without_lookup(self, tmp_path: Path) -> None:
        checker = _load_checker()
        note = _write_pr_note(tmp_path, "task-r", pr_repo="garbage")
        (tmp_path / "task-r.acceptance.yaml").write_text(_bound_receipt(), encoding="utf-8")
        lookup = _Lookup(HEAD_A)

        code, message = checker.gate(note, head_lookup=lookup)

        assert code == 2
        assert "acceptance_receipt_pr_repo_malformed:garbage" in message
        assert "pr_repo: <owner>/<name>" in message
        assert lookup.calls == []


class TestReceiptReloadAfterValidation:
    """The gate validates the receipt, then re-reads it to bind the head.

    The receipt can change between the two reads. Whatever the re-read finds, it must
    refuse with a typed blocker, never crash and never pass. ``acceptance_receipt_blockers``
    is stubbed to report the first read as valid so that each re-read case is reached
    deterministically.
    """

    def _gate_on_reload(
        self, tmp_path: Path, monkeypatch: object, receipt_text: str | None
    ) -> tuple[int, str, _Lookup]:
        checker = _load_checker()
        monkeypatch.setattr(checker, "acceptance_receipt_blockers", lambda *_a: ())  # type: ignore[attr-defined]
        note = _write_pr_note(tmp_path, "task-r")
        if receipt_text is not None:
            (tmp_path / "task-r.acceptance.yaml").write_text(receipt_text, encoding="utf-8")
        lookup = _Lookup(HEAD_A)
        code, message = checker.gate(note, head_lookup=lookup)
        return code, message, lookup

    def test_receipt_truncated_to_empty_refuses_typed(
        self, tmp_path: Path, monkeypatch: object
    ) -> None:
        code, message, lookup = self._gate_on_reload(tmp_path, monkeypatch, "")

        assert code == 2
        assert "acceptance_receipt_malformed:not_a_mapping:NoneType" in message
        assert lookup.calls == []

    def test_receipt_no_longer_a_mapping_refuses_typed(
        self, tmp_path: Path, monkeypatch: object
    ) -> None:
        code, message, lookup = self._gate_on_reload(tmp_path, monkeypatch, "- a\n- b\n")

        assert code == 2
        assert "acceptance_receipt_malformed:not_a_mapping:list" in message
        assert lookup.calls == []

    def test_receipt_unparseable_on_reload_refuses_typed(
        self, tmp_path: Path, monkeypatch: object
    ) -> None:
        code, message, lookup = self._gate_on_reload(tmp_path, monkeypatch, "acceptor: [\n")

        assert code == 2
        assert "acceptance_receipt_malformed:" in message
        assert "Error" in message
        assert lookup.calls == []

    def test_receipt_vanished_on_reload_refuses_typed(
        self, tmp_path: Path, monkeypatch: object
    ) -> None:
        code, message, lookup = self._gate_on_reload(tmp_path, monkeypatch, None)

        assert code == 2
        assert "acceptance_receipt_malformed:FileNotFoundError" in message
        assert lookup.calls == []


def _vault(home: Path) -> Path:
    root = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    (root / "active").mkdir(parents=True, exist_ok=True)
    (root / "closed").mkdir(parents=True, exist_ok=True)
    return root


def _fake_gh(directory: Path, head: str) -> str:
    """A `gh` on PATH that answers every PR-head query with ``head``; returns the new PATH."""

    bin_dir = directory / "fake-bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(f"#!/usr/bin/env bash\necho {head}\n", encoding="utf-8")
    gh.chmod(0o755)
    return f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"


def _run_close(
    home: Path, task_id: str, *extra_args: str, **extra_env: str
) -> subprocess.CompletedProcess[str]:
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
        ["bash", str(CC_CLOSE), task_id, "--status", "done", *extra_args],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


class TestCcCloseHeadBindingEndToEnd:
    def test_cc_close_refuses_stale_head_receipt_legibly(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        vault = _vault(home)
        _write_pr_note(vault / "active", "task-r")
        (vault / "active" / "task-r.acceptance.yaml").write_text(_bound_receipt(), encoding="utf-8")

        result = _run_close(home, "task-r", PATH=_fake_gh(tmp_path, HEAD_B))

        assert result.returncode == 2
        assert f"acceptance_receipt_stale_head:receipt={HEAD_A}:current={HEAD_B}" in result.stderr
        assert "re-run acceptance on the current head" in result.stderr
        assert (vault / "active" / "task-r.md").exists()
        assert not (vault / "closed" / "task-r.md").exists()

    def test_cc_close_closes_with_fresh_head_receipt(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        vault = _vault(home)
        _write_pr_note(vault / "active", "task-r")
        (vault / "active" / "task-r.acceptance.yaml").write_text(_bound_receipt(), encoding="utf-8")

        result = _run_close(home, "task-r", PATH=_fake_gh(tmp_path, HEAD_A))

        assert result.returncode == 0, result.stderr
        assert (vault / "closed" / "task-r.md").exists()

    def test_cc_close_passes_its_pr_argument_to_the_receipt_gate(self, tmp_path: Path) -> None:
        # The note declares no PR and the receipt names none: only `--pr` puts a PR in
        # play. If cc-close did not forward it, this would close as a PR-less row.
        home = tmp_path / "home"
        vault = _vault(home)
        note = _write_note(vault / "active", "task-r")
        note.write_text(
            note.read_text(encoding="utf-8").replace("pr:\n", f"pr:\npr_repo: {PR_REPO}\n", 1),
            encoding="utf-8",
        )
        (vault / "active" / "task-r.acceptance.yaml").write_text(VALID_RECEIPT, encoding="utf-8")

        result = _run_close(home, "task-r", "--pr", "4668", PATH=_fake_gh(tmp_path, HEAD_A))

        assert result.returncode == 2
        assert "acceptance_receipt_missing_field:head_sha" in result.stderr
        assert (vault / "active" / "task-r.md").exists()


class TestCcCloseEndToEnd:
    def test_cc_close_blocks_on_unreadable_note(self, tmp_path: Path) -> None:
        """End-to-end: cc-close must REFUSE done when the note cannot be read.

        Pre-fix this closed unreviewed: the gate failed OPEN on the OSError and
        the move's own read crash (exit 1, no next action) was the only thing
        that stopped it. Post-fix the gate itself refuses with the named case.
        """
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            pytest.skip("root reads through permission bits — no denial to witness")
        home = tmp_path / "home"
        vault = _vault(home)
        note = _write_note(vault / "active", "task-r")
        note.chmod(0)

        result = _run_close(home, "task-r")

        assert result.returncode == 2
        assert "unreadable" in result.stderr
        assert (vault / "active" / "task-r.md").exists()
        assert not (vault / "closed" / "task-r.md").exists()

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
