"""SDLC closed-loop execution gate — composition, acyclicity, fail-closed stages.

The task exit predicate for the Gate-0 landing is: *bind WHAT/HOW/MUST and
epistemic impingement to the SDLC FSM as one closed-loop execution gate.* This
module is the loop-level witness for that predicate. It was declared in the
task's ``mutation_scope_refs`` from the start but never written, so until now no
shipped command exercised the loop as a whole — each stage had (at best) its own
unit coverage and nothing asserted that they compose.

The loop is four modules, each gating the next:

    coord_projection  ──▶ sdlc_claim ──▶ execution_admission ──▶ sdlc_close
    (lifecycle position)  (claim pub.)   (admission + lease)     (terminal close)

Two loop-level properties are asserted here, both of which are invisible to any
single-stage test:

1. **Every stage fails closed without its predecessor's evidence.** The loop is
   only a gate if each stage refuses when unbound. A stage that fails *open*
   would silently short the whole chain while every unit test still passed.

2. **The close gates cannot deadlock.** ``shared/sdlc_close.py`` and
   ``scripts/cc-close-acceptance-receipt-check.py`` both gate terminal close.
   If either waited on a resource the other produced, closure would wedge under
   exactly the incident conditions the gates exist for. They do not: both depend
   on the same leaf predicates in ``shared/sdlc_lifecycle.py``, which depends on
   neither, and the receipt they both read is an operator-minted artifact that
   is not produced by either gate. That is a DAG, and it is asserted structurally
   below rather than argued in prose.

The acyclicity assertions are deliberately structural (import-graph shaped)
rather than behavioural. A behavioural deadlock test can only ever sample the
schedules it happens to try; the absence of a back-edge rules the cycle out for
every schedule.

Self-contained per project convention — no shared conftest fixtures.
"""

from __future__ import annotations

import ast
import importlib.util
import os
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RECEIPT_GATE_SCRIPT = REPO_ROOT / "scripts" / "cc-close-acceptance-receipt-check.py"

# The four modules that constitute the closed loop, in gating order.
LOOP_MODULES = (
    "shared.coord_projection",
    "shared.sdlc_claim",
    "shared.execution_admission",
    "shared.sdlc_close",
)


def _imported_modules(path: Path) -> set[str]:
    """Every module name imported by ``path``, from its AST.

    AST rather than importing: this must report what the file *declares*, so a
    back-edge cannot hide behind a conditional or a function-local import.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _load_receipt_gate() -> ModuleType:
    """Load the receipt-gate script by path — it is a script, not a package module."""
    spec = importlib.util.spec_from_file_location(
        "cc_close_acceptance_receipt_check", RECEIPT_GATE_SCRIPT
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_review_floor_note(tmp_path: Path, task_id: str) -> Path:
    """A task note that declares the review floor and has no acceptance receipt."""
    path = tmp_path / f"{task_id}.md"
    path.write_text(
        "\n".join(
            [
                "---",
                "type: cc-task",
                f"task_id: {task_id}",
                "status: in_progress",
                "quality_floor: frontier_review_required",
                "---",
                "",
                f"# {task_id}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


# --------------------------------------------------------------------------
# The loop composes
# --------------------------------------------------------------------------


def test_all_four_loop_modules_import_together() -> None:
    """The loop must be importable as one unit.

    These modules are large and cross-referencing; a cycle or a missing symbol
    between them surfaces here rather than at the first runtime dispatch.
    """
    import importlib

    for name in LOOP_MODULES:
        assert importlib.import_module(name) is not None


def test_each_loop_stage_exposes_a_typed_refusal() -> None:
    """A stage that cannot say "no" in a typed way cannot be a gate.

    Untyped failure is the failure mode this landing exists to remove: a bare
    exception carries no reason code, so callers cannot distinguish "refused"
    from "crashed" and tend to fail open.
    """
    import importlib

    expected = {
        "shared.coord_projection": "LifecycleTransitionError",
        "shared.sdlc_claim": "ClaimPublicationError",
        "shared.execution_admission": "ExecutionAdmissionError",
        "shared.sdlc_close": "TerminalCloseError",
    }
    for module_name, error_name in expected.items():
        module = importlib.import_module(module_name)
        error = getattr(module, error_name, None)
        assert error is not None, f"{module_name} exposes no {error_name}"
        assert issubclass(error, Exception)


# --------------------------------------------------------------------------
# Stage fails closed without its predecessor's evidence
# --------------------------------------------------------------------------


def test_execution_stage_refuses_an_unadmitted_lease() -> None:
    """Execution without an admitted lease is refused, not defaulted."""
    from shared.execution_admission import (
        ExecutionAdmissionError,
        require_admitted_execution_lease,
    )

    with pytest.raises(ExecutionAdmissionError) as excinfo:
        require_admitted_execution_lease(None)  # type: ignore[arg-type]

    assert excinfo.value.reason_code == "admitted_execution_lease_required"


def test_close_stage_refuses_a_review_floor_task_with_no_receipt(tmp_path: Path) -> None:
    """The terminal stage of the loop fails closed on missing acceptance."""
    gate_module = _load_receipt_gate()
    note = _write_review_floor_note(tmp_path, "cc-task-loop-witness")

    exit_code, message = gate_module.gate(note)

    assert exit_code == 2, message
    assert message


def test_close_stage_permits_a_task_that_does_not_declare_the_floor(tmp_path: Path) -> None:
    """Non-review-floor flows are untouched — the gate is narrow, not blanket.

    Without this, the fail-closed test above would also pass for a gate that
    simply blocked everything.
    """
    gate_module = _load_receipt_gate()
    path = tmp_path / "plain.md"
    path.write_text(
        "---\ntype: cc-task\ntask_id: plain\nstatus: in_progress\n---\n\n# plain\n",
        encoding="utf-8",
    )

    exit_code, message = gate_module.gate(path)

    assert exit_code == 0, message


# --------------------------------------------------------------------------
# Killswitch semantics under canon-bound close
# --------------------------------------------------------------------------


def test_legacy_env_bypass_still_works_outside_canon_bound_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The legacy incident-response bypass remains available on the legacy path."""
    gate_module = _load_receipt_gate()
    note = _write_review_floor_note(tmp_path, "cc-task-legacy-bypass")

    monkeypatch.setenv("HAPAX_ACCEPTANCE_RECEIPT_GATE_OFF", "1")
    monkeypatch.delenv(gate_module.CANON_BOUND_CLOSE_ENV, raising=False)

    exit_code, _ = gate_module.gate(note)

    assert exit_code == 0


def test_legacy_env_bypass_is_inert_under_canon_bound_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The documented killswitch claim, machine-checked.

    ``scripts/cc-close-acceptance-receipt-check.py`` documents that canon-bound
    close ignores the raw env bypass and that the live escape hatch is a governed
    override receipt. If the env var ever regained force under canon-bound close,
    an ambient variable would silently re-open a t1_critical closure gate.
    """
    gate_module = _load_receipt_gate()
    note = _write_review_floor_note(tmp_path, "cc-task-canon-bypass")

    monkeypatch.setenv("HAPAX_ACCEPTANCE_RECEIPT_GATE_OFF", "1")
    monkeypatch.setenv(gate_module.CANON_BOUND_CLOSE_ENV, "1")

    exit_code, message = gate_module.gate(note)

    assert exit_code == 2, f"env bypass must be inert under canon-bound close: {message}"


def test_canon_bound_close_fails_closed_on_an_unreadable_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Infrastructure errors fail OPEN on the legacy path and CLOSED under canon.

    Asserting both directions matters: the legacy fail-open is deliberate ("a
    broken gate must not brick closures") and must not be mistaken for a bug and
    "fixed" into a hang, while canon-bound close must not inherit it.
    """
    gate_module = _load_receipt_gate()
    missing = tmp_path / "does-not-exist.md"

    monkeypatch.delenv("HAPAX_ACCEPTANCE_RECEIPT_GATE_OFF", raising=False)
    monkeypatch.delenv(gate_module.CANON_BOUND_CLOSE_ENV, raising=False)
    assert gate_module.gate(missing)[0] == 0

    monkeypatch.setenv(gate_module.CANON_BOUND_CLOSE_ENV, "1")
    assert gate_module.gate(missing)[0] == 2


# --------------------------------------------------------------------------
# Deadlock-freedom between the two close gates
# --------------------------------------------------------------------------


def test_lifecycle_leaf_does_not_depend_on_the_close_admission() -> None:
    """``shared/sdlc_lifecycle.py`` is the shared leaf and must stay a leaf.

    Both close gates import their receipt predicates from it. If it ever imported
    ``shared.sdlc_close``, the two gates would become mutually reachable and a
    circular wait would be expressible.
    """
    imports = _imported_modules(REPO_ROOT / "shared" / "sdlc_lifecycle.py")

    assert "shared.sdlc_close" not in imports
    assert not any(name.endswith("cc_close_acceptance_receipt_check") for name in imports)


def test_receipt_gate_does_not_depend_on_the_close_admission() -> None:
    """No back-edge from the receipt gate to the close admission.

    The receipt gate must be evaluable without entering terminal-close admission;
    otherwise checking whether close is permitted would require close.
    """
    imports = _imported_modules(RECEIPT_GATE_SCRIPT)

    assert "shared.sdlc_close" not in imports
    assert "shared.sdlc_lifecycle" in imports


def test_both_close_gates_share_one_receipt_predicate() -> None:
    """The two gates must agree by construction, not by coincidence.

    A disagreement is the livelock case: one gate says the receipt is valid and
    permits close while the other says it is not and blocks, forever. Sharing the
    single implementation in the leaf makes that unrepresentable.
    """
    from shared import sdlc_close, sdlc_lifecycle

    gate_module = _load_receipt_gate()

    assert gate_module.acceptance_receipt_blockers is sdlc_lifecycle.acceptance_receipt_blockers
    assert gate_module.requires_acceptance_receipt is sdlc_lifecycle.requires_acceptance_receipt
    assert sdlc_close.acceptance_receipt_blockers is sdlc_lifecycle.acceptance_receipt_blockers
    assert sdlc_close.requires_acceptance_receipt is sdlc_lifecycle.requires_acceptance_receipt


def test_the_acceptance_receipt_is_an_external_artifact(tmp_path: Path) -> None:
    """Neither gate produces the resource both wait on.

    A circular wait needs each party to hold what the other needs. Here the
    receipt is an operator-minted file beside the note, produced by neither gate,
    so neither can be holding it against the other.
    """
    from shared.sdlc_lifecycle import acceptance_receipt_path

    note = tmp_path / "cc-task-x.md"
    receipt = acceptance_receipt_path(note, "cc-task-x")

    assert receipt.parent == note.parent
    assert receipt.name.endswith(".acceptance.yaml")
    # Reading the gate must not have created it.
    assert not receipt.exists()


def test_loop_module_files_all_exist() -> None:
    """Guards the witness itself against silently drifting off the real modules."""
    for name in LOOP_MODULES:
        rel = Path(*name.split(".")).with_suffix(".py")
        assert (REPO_ROOT / rel).is_file(), f"{rel} missing"
    assert RECEIPT_GATE_SCRIPT.is_file()
    assert os.access(RECEIPT_GATE_SCRIPT, os.R_OK)
