"""Charter grants a child and obligates one. Absence is a report, not a refusal."""

from shared.charter_claim import child_may_mint, obligation_breaches

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
    empty = _CHILD.replace("mutation_scope_refs:\n  - shared/route_metadata_schema.py\n", "mutation_scope_refs: []\n")
    assert child_may_mint(_CHARTER, empty) is False


def test_ordinary_claim_is_not_a_charter() -> None:
    ordinary = _CHARTER.replace("claim_form: charter\n", "claim_form: task\n")
    assert child_may_mint(ordinary, _CHILD) is False


def test_missing_child_is_a_reported_breach_not_a_write_refusal() -> None:
    breaches = obligation_breaches(
        ["shared/"],
        [],
        ["shared/route_metadata_schema.py", "docs/unrelated.md"],
    )
    assert breaches == ["shared/route_metadata_schema.py"]


def test_child_scope_discharges_the_obligation() -> None:
    breaches = obligation_breaches(
        ["shared/"],
        [["shared/route_metadata_schema.py"]],
        ["shared/route_metadata_schema.py"],
    )
    assert breaches == []
