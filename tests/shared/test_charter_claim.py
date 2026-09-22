"""Charter grants a child and obligates one. Absence is a report, not a refusal."""

from shared.charter_claim import (
    child_may_mint,
    covers,
    obligation_breaches,
    residue_without_active_lease,
    write_obligation_report,
)

_CHARTER = """---
claim_form: charter
task_id: charter-demo
charter_scope:
  - shared/route_metadata_schema.py
  - tests/shared/
---
"""

_CHILD = """---
task_id: child-demo
parent_charter: charter-demo
mutation_scope_refs:
  - shared/route_metadata_schema.py
---
"""


def test_child_inside_charter_may_mint() -> None:
    assert child_may_mint(_CHARTER, _CHILD) is True


def test_child_wider_than_charter_may_not_mint() -> None:
    wider = _CHILD.replace(
        "  - shared/route_metadata_schema.py\n",
        "  - shared/route_metadata_schema.py\n  - axioms/constitution.md\n",
    )
    assert child_may_mint(_CHARTER, wider) is False


def test_child_without_scope_may_not_mint() -> None:
    empty = _CHILD.replace(
        "mutation_scope_refs:\n  - shared/route_metadata_schema.py\n", "mutation_scope_refs: []\n"
    )
    assert child_may_mint(_CHARTER, empty) is False


def test_ordinary_claim_is_not_a_charter() -> None:
    ordinary = _CHARTER.replace("claim_form: charter\n", "claim_form: task\n")
    assert child_may_mint(ordinary, _CHILD) is False


def test_missing_child_is_written_as_a_report(tmp_path) -> None:
    breaches = obligation_breaches(
        ["shared/"],
        [],
        ["shared/route_metadata_schema.py", "docs/unrelated.md"],
    )
    destination = tmp_path / "reports" / "obligation.jsonl"
    write_obligation_report(destination, breaches, charter_id="charter-demo")
    line = destination.read_text(encoding="utf-8").strip()
    assert "shared/route_metadata_schema.py" in line
    assert "docs/unrelated.md" not in line


def test_missing_child_is_a_reported_breach_not_a_write_refusal() -> None:
    breaches = obligation_breaches(
        ["shared/"],
        [],
        ["shared/route_metadata_schema.py", "docs/unrelated.md"],
    )
    assert breaches == ["shared/route_metadata_schema.py"]


def test_path_escape_is_not_inside_the_charter() -> None:
    assert covers("shared", "shared/../axioms/constitution.md") is False
    assert covers("shared", "/shared/file.py") is False
    assert covers("shared", "shared/charter_claim.py") is True


def test_missing_identity_cannot_mint() -> None:
    nameless = _CHARTER.replace("task_id: charter-demo\n", "task_id:\n")
    assert child_may_mint(nameless, _CHILD) is False
    unlinked = _CHILD.replace("parent_charter: charter-demo\n", "parent_charter:\n")
    assert child_may_mint(_CHARTER, unlinked) is False


def test_missing_lease_holds_a_live_task_and_archives_a_terminal_one() -> None:
    assert residue_without_active_lease("in_progress") == "hold"
    assert residue_without_active_lease("missing") == "hold"
    assert residue_without_active_lease("closed") == "archive"


def test_child_scope_discharges_the_obligation() -> None:
    breaches = obligation_breaches(
        ["shared/"],
        [["shared/route_metadata_schema.py"]],
        ["shared/route_metadata_schema.py"],
    )
    assert breaches == []
