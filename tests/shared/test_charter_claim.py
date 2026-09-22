"""A charter lets the coordinator continue. A missing unit is a report, not a stop."""

from shared.charter_claim import (
    child_may_mint,
    covers,
    obligation_breaches,
    record_unit,
    sidecar_belongs_to,
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


def test_recording_a_unit_does_not_require_a_new_claim(tmp_path) -> None:
    destination = tmp_path / "units.jsonl"
    record_unit(destination, charter_id="charter-demo", unit_id="unit-1")
    record_unit(destination, charter_id="charter-demo", unit_id="unit-1")
    lines = [line for line in destination.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1
    assert "unit-1" in lines[0]


def test_missing_child_is_written_as_a_report(tmp_path) -> None:
    breaches = obligation_breaches(
        ["shared/"],
        [],
        ["shared/route_metadata_schema.py", "docs/unrelated.md"],
    )
    destination = tmp_path / "reports" / "obligation.jsonl"
    write_obligation_report(destination, breaches, charter_id="charter-demo")
    write_obligation_report(destination, breaches, charter_id="charter-demo")
    lines = [line for line in destination.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1
    assert "shared/route_metadata_schema.py" in lines[0]
    assert "docs/unrelated.md" not in lines[0]


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


def test_sidecar_match_is_the_parsed_task_id(tmp_path) -> None:
    active = tmp_path / "cc-active-task-grok"
    active.write_text("charter-demo\n", encoding="utf-8")
    neighbor = tmp_path / "cc-active-task-other"
    neighbor.write_text("charter-demo-extra\n", encoding="utf-8")
    epoch = tmp_path / "cc-claim-epoch-grok"
    epoch.write_text("123 charter-demo\n", encoding="utf-8")
    dispatch = tmp_path / "cc-claim-dispatch-grok.json"
    dispatch.write_text('{"task_id": "charter-demo"}\n', encoding="utf-8")
    assert sidecar_belongs_to(active, "charter-demo") is True
    assert sidecar_belongs_to(neighbor, "charter-demo") is False
    assert sidecar_belongs_to(epoch, "charter-demo") is True
    assert sidecar_belongs_to(dispatch, "charter-demo") is True


def test_child_scope_discharges_the_obligation() -> None:
    breaches = obligation_breaches(
        ["shared/"],
        [["shared/route_metadata_schema.py"]],
        ["shared/route_metadata_schema.py"],
    )
    assert breaches == []
