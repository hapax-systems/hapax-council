"""The garage-door row template carries a complete adoptability block (A5).

If a field is added to shared.adoptability_gate.ACCEPTANCE_FIELDS or RECEIPT_FIELDS,
this test forces the template to follow — the two cannot drift.
"""

from __future__ import annotations

from pathlib import Path

from shared import adoptability_gate as gate

TEMPLATE = Path(__file__).parent.parent / "config" / "cc-task-templates" / "garage-door.md"


def test_template_is_a_garage_door_row_with_every_required_field() -> None:
    frontmatter, refusals = gate.lint_frontmatter_text(TEMPLATE.read_text(encoding="utf-8"))
    assert frontmatter is not None
    assert gate.is_garage_door(frontmatter)
    assert refusals == []
    block = frontmatter["adoptability"]
    assert set(block) >= set(gate.RECEIPT_FIELDS) | set(gate.ACCEPTANCE_FIELDS) | {"receipt"}


def test_template_install_surface_binds_no_estate_noun() -> None:
    frontmatter, _ = gate.lint_frontmatter_text(TEMPLATE.read_text(encoding="utf-8"))
    assert frontmatter is not None
    assert gate.estate_bindings(frontmatter) == []
