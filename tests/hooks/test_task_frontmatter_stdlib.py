from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from shared.strict_yaml import strict_safe_load

MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "hooks" / "scripts" / "task_frontmatter_stdlib.py"
)
SPEC = importlib.util.spec_from_file_location("task_frontmatter_stdlib_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
stdlib_yaml = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = stdlib_yaml
SPEC.loader.exec_module(stdlib_yaml)


def _canonical(content: str) -> dict:
    front = content.split("---", 2)[1]
    value = strict_safe_load(front)
    assert isinstance(value, dict)
    return value


def test_supported_governance_subset_matches_canonical_fields() -> None:
    content = """---
status: claimed
assigned_to: codex/cx-red
route_metadata:
  risk_flags: {governance_sensitive: true, public_claim_sensitive: false}
mutation_scope_refs:
- cc-task:demo
- shared/
implementation_authorized: true
---

## Session Log
"""

    parsed = stdlib_yaml.parse_frontmatter_document(content).fields
    canonical = _canonical(content)

    for key in ("status", "assigned_to", "implementation_authorized"):
        assert stdlib_yaml.scalar_text(parsed[key]) == stdlib_yaml.scalar_text(canonical[key])
    assert (
        stdlib_yaml.string_list(parsed["mutation_scope_refs"]) == canonical["mutation_scope_refs"]
    )
    assert parsed["route_metadata"] == canonical["route_metadata"]


@pytest.mark.parametrize(
    "frontmatter",
    [
        "status: claimed\nroute_metadata: {\n",
        "status: claimed\nroute_metadata:\n  quality: one\n  quality: two\n",
        "parent_spec: |foo\n",
        "tags: [|]\n",
    ],
)
def test_malformed_or_nested_duplicate_is_rejected_by_both_parsers(frontmatter: str) -> None:
    content = f"---\n{frontmatter}---\n"
    with pytest.raises(ValueError):
        stdlib_yaml.parse_frontmatter_document(content)
    with pytest.raises(ValueError):
        strict_safe_load(frontmatter)


@pytest.mark.parametrize(
    "frontmatter",
    [
        "defaults: &defaults\n  status: claimed\ncopy: *defaults\n",
        "status: !!str claimed\n",
        "release_note: |\n  unsupported folded content\n",
        "release_note: |\n",
        "release_note: >-\n  unsupported folded content\n",
        "tags:\n  - |\n",
    ],
)
def test_unproven_yaml_features_fail_closed_even_when_canonical_accepts(
    frontmatter: str,
) -> None:
    strict_safe_load(frontmatter)
    with pytest.raises(stdlib_yaml.FrontmatterSubsetError):
        stdlib_yaml.parse_frontmatter_document(f"---\n{frontmatter}---\n")


def test_parser_module_has_no_optional_yaml_dependency() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "import yaml" not in source
    assert "from yaml" not in source
