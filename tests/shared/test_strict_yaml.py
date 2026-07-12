from __future__ import annotations

import pytest

from shared.frontmatter import parse_frontmatter_with_diagnostics
from shared.strict_yaml import strict_safe_load


def test_strict_safe_load_rejects_duplicate_mapping_keys() -> None:
    with pytest.raises(ValueError, match="duplicate key"):
        strict_safe_load("assigned_to: cx-red\nassigned_to: unassigned\n")


def test_strict_safe_load_rejects_unhashable_mapping_keys() -> None:
    with pytest.raises(ValueError, match="unhashable mapping key"):
        strict_safe_load("? [a, b]\n: value\n")


def test_canonical_frontmatter_parser_fails_closed_on_duplicate_keys() -> None:
    result = parse_frontmatter_with_diagnostics(
        "---\nstatus: claimed\nassigned_to: cx-red\nassigned_to: unassigned\n---\nbody\n"
    )

    assert result.ok is False
    assert result.error_kind == "yaml_error"
