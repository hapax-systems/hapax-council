"""The frontmatter parser uses libyaml's safe loader where it exists.

Every task-store index build parses the frontmatter of every task row, and one
cc-claim builds that index several times, so the pure-Python loader made each
claim cost close to a minute of CPU. These tests pin the three things the C
loader must not change: the parsed values, the error path and the safety
boundary.
"""

from __future__ import annotations

import pytest
import yaml

from shared import frontmatter
from shared.frontmatter import parse_frontmatter_with_diagnostics

# Scalars where YAML resolvers are known to disagree between implementations,
# plus the shapes task rows actually use (folded multi-line predicates, nested
# route metadata, flow mappings, timestamps written quoted and unquoted).
PARITY_FIXTURES = [
    "created_at: '2026-10-15T16:40:52Z'\nupdated_at: 2026-10-15T20:37:02Z\nday: 2026-10-15\n",
    "mode: 0755\nocto: 0o17\nhexa: 0x1F\nsexa: 1:30\nfloaty: 1e3\nnan: .nan\ninf: -.inf\n",
    "a: null\nb: ~\nc:\nd: 'null'\n",
    "y: yes\nn: no\non: on\noff: off\nt: true\nf: False\n",
    "base: &b {quality_floor: frontier_required, risk: T2}\nroute: *b\nmerged:\n  <<: *b\n  risk: T3\n",
    "dup: first\ndup: second\n",
    "exit_predicate: >-\n  RULING: the Crow, line one\n  and line two\n\n  a new paragraph\ntags: [cc-task, p1, hearth]\n",
    "route_metadata:\n  risk_flags: {governance_sensitive: true, privacy_or_secret_sensitive: false}\n"
    "  route_constraints: {allowed_platforms: [claude, codex], prohibited_platforms: [api]}\n",
    'title: "Bring monocle and necesse fully up to date: Prism, \\u00e9 and \\"quotes\\""\nempty: \'\'\n',
    "pr: 5164\npr_repo: hapax-systems/hapax-council\nwsjf: 8.5\nneg: -3\n",
]


def _note(yaml_text: str) -> str:
    return f"---\n{yaml_text}---\n# body\n"


@pytest.mark.parametrize("yaml_text", PARITY_FIXTURES)
def test_parsed_values_equal_the_pure_python_safe_loader(yaml_text: str) -> None:
    result = parse_frontmatter_with_diagnostics(_note(yaml_text))
    assert result.error_kind is None
    expected = yaml.load(yaml_text, Loader=yaml.SafeLoader)  # noqa: S506 - SafeLoader is the reference
    assert result.frontmatter == expected


def test_uses_the_c_safe_loader_when_libyaml_is_present() -> None:
    if not getattr(yaml, "__with_libyaml__", False):
        pytest.skip("libyaml is not available in this interpreter")
    assert frontmatter._safe_yaml_loader() is yaml.CSafeLoader


def test_falls_back_to_the_pure_python_safe_loader_without_libyaml(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delattr(yaml, "CSafeLoader", raising=False)
    assert frontmatter._safe_yaml_loader() is yaml.SafeLoader
    result = parse_frontmatter_with_diagnostics(_note("status: offered\n"))
    assert result.frontmatter == {"status": "offered"}


def test_the_parser_loads_through_the_selected_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    used: list[bool] = []

    class RecordingLoader(yaml.SafeLoader):
        def __init__(self, stream):  # type: ignore[no-untyped-def]
            used.append(True)
            super().__init__(stream)

    monkeypatch.setattr(frontmatter, "_safe_yaml_loader", lambda: RecordingLoader)
    result = parse_frontmatter_with_diagnostics(_note("status: offered\n"))
    assert result.frontmatter == {"status": "offered"}
    assert used, "parse_frontmatter_with_diagnostics bypassed _safe_yaml_loader()"


def test_malformed_yaml_still_maps_to_yaml_error() -> None:
    result = parse_frontmatter_with_diagnostics(_note("status: [offered\nkey: : bad\n"))
    assert result.frontmatter is None
    assert result.error_kind == "yaml_error"
    assert result.error_message


def test_python_tags_are_still_refused() -> None:
    # A safe loader rejects any python/* tag; an unsafe or full loader would build the tuple.
    result = parse_frontmatter_with_diagnostics(_note("value: !!python/tuple [1, 2]\n"))
    assert result.frontmatter is None
    assert result.error_kind == "yaml_error"


def test_non_mapping_frontmatter_is_still_refused() -> None:
    result = parse_frontmatter_with_diagnostics(_note("- just\n- a list\n"))
    assert result.frontmatter is None
    assert result.error_kind == "not_mapping"
