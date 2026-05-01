# tests/test_axiom_registry.py
"""Tests for shared.axiom_registry."""

import pytest

from shared.axiom_registry import (
    get_axiom,
    load_axioms,
    load_implications,
    validate_supremacy,
)


@pytest.fixture
def sample_registry(tmp_path):
    """Create a minimal registry for testing."""
    reg = tmp_path / "registry.yaml"
    reg.write_text(
        "version: 1\n"
        "axioms:\n"
        "  - id: test_axiom\n"
        '    text: "Test axiom text."\n'
        "    weight: 80\n"
        "    type: hardcoded\n"
        '    created: "2026-01-01"\n'
        "    status: active\n"
        "    supersedes: null\n"
        "  - id: retired_axiom\n"
        '    text: "Old axiom."\n'
        "    weight: 50\n"
        "    type: softcoded\n"
        '    created: "2025-01-01"\n'
        "    status: retired\n"
        "    supersedes: null\n"
    )
    impl_dir = tmp_path / "implications"
    impl_dir.mkdir()
    (impl_dir / "test_axiom.yaml").write_text(
        "axiom_id: test_axiom\n"
        "derived_at: '2026-01-01'\n"
        "model: test-model\n"
        "derivation_version: 1\n"
        "implications:\n"
        "  - id: ta-001\n"
        "    tier: T0\n"
        '    text: "No multi-user auth"\n'
        "    enforcement: block\n"
        "    canon: textualist\n"
        "  - id: ta-002\n"
        "    tier: T2\n"
        '    text: "Prefer single-user defaults"\n'
        "    enforcement: warn\n"
        "    canon: purposivist\n"
    )
    return tmp_path


def test_load_axioms_returns_active_only(sample_registry):
    axioms = load_axioms(path=sample_registry)
    assert len(axioms) == 1
    assert axioms[0].id == "test_axiom"
    assert axioms[0].weight == 80
    assert axioms[0].type == "hardcoded"


def test_load_axioms_missing_path(tmp_path):
    axioms = load_axioms(path=tmp_path / "nonexistent")
    assert axioms == []


def test_get_axiom_found(sample_registry):
    axiom = get_axiom("test_axiom", path=sample_registry)
    assert axiom is not None
    assert axiom.text.strip() == "Test axiom text."


def test_get_axiom_not_found(sample_registry):
    assert get_axiom("nonexistent", path=sample_registry) is None


def test_load_implications(sample_registry):
    impls = load_implications("test_axiom", path=sample_registry)
    assert len(impls) == 2
    assert impls[0].id == "ta-001"
    assert impls[0].tier == "T0"
    assert impls[0].enforcement == "block"
    assert impls[1].tier == "T2"


def test_load_implications_missing_file(sample_registry):
    impls = load_implications("nonexistent", path=sample_registry)
    assert impls == []


def test_mode_defaults_to_compatibility(sample_registry):
    """When mode is absent from YAML, defaults to 'compatibility'."""
    impls = load_implications("test_axiom", path=sample_registry)
    for impl in impls:
        assert impl.mode == "compatibility"


def test_level_defaults_to_component(sample_registry):
    """When level is absent from YAML, defaults to 'component'."""
    impls = load_implications("test_axiom", path=sample_registry)
    for impl in impls:
        assert impl.level == "component"


def test_axiom_scope_defaults_to_constitutional(sample_registry):
    """Missing scope field defaults to 'constitutional'."""
    axioms = load_axioms(path=sample_registry)
    assert axioms[0].scope == "constitutional"


def test_axiom_domain_defaults_to_none(sample_registry):
    """Missing domain field defaults to None."""
    axioms = load_axioms(path=sample_registry)
    assert axioms[0].domain is None


@pytest.fixture
def multi_scope_registry(tmp_path):
    """Registry with both constitutional and domain axioms."""
    reg = tmp_path / "registry.yaml"
    reg.write_text(
        "version: 2\n"
        "axioms:\n"
        "  - id: const_axiom\n"
        '    text: "Constitutional axiom."\n'
        "    weight: 100\n"
        "    type: hardcoded\n"
        '    created: "2026-01-01"\n'
        "    status: active\n"
        "    scope: constitutional\n"
        "    domain: null\n"
        "  - id: mgmt_axiom\n"
        '    text: "Management domain axiom."\n'
        "    weight: 85\n"
        "    type: softcoded\n"
        '    created: "2026-01-01"\n'
        "    status: active\n"
        "    scope: domain\n"
        "    domain: management\n"
        "  - id: music_axiom\n"
        '    text: "Music domain axiom."\n'
        "    weight: 80\n"
        "    type: softcoded\n"
        '    created: "2026-01-01"\n'
        "    status: active\n"
        "    scope: domain\n"
        "    domain: music\n"
    )
    # Create implications for supremacy testing
    impl_dir = tmp_path / "implications"
    impl_dir.mkdir()
    (impl_dir / "const_axiom.yaml").write_text(
        "axiom_id: const_axiom\n"
        "implications:\n"
        "  - id: ca-001\n"
        "    tier: T0\n"
        '    text: "No multi-user auth"\n'
        "    enforcement: block\n"
        "    canon: textualist\n"
    )
    (impl_dir / "mgmt_axiom.yaml").write_text(
        "axiom_id: mgmt_axiom\n"
        "implications:\n"
        "  - id: mg-001\n"
        "    tier: T0\n"
        '    text: "Never generate feedback language"\n'
        "    enforcement: block\n"
        "    canon: purposivist\n"
        "  - id: mg-002\n"
        "    tier: T1\n"
        '    text: "Deterministic data collection"\n'
        "    enforcement: review\n"
        "    canon: purposivist\n"
    )
    return tmp_path


def test_load_axioms_filter_by_scope(multi_scope_registry):
    """scope='domain' filters correctly."""
    domain = load_axioms(path=multi_scope_registry, scope="domain")
    assert len(domain) == 2
    assert all(a.scope == "domain" for a in domain)

    const = load_axioms(path=multi_scope_registry, scope="constitutional")
    assert len(const) == 1
    assert const[0].id == "const_axiom"


def test_load_axioms_filter_by_domain(multi_scope_registry):
    """domain='management' filters correctly."""
    mgmt = load_axioms(path=multi_scope_registry, domain="management")
    assert len(mgmt) == 1
    assert mgmt[0].id == "mgmt_axiom"


def test_load_axioms_no_filter_returns_all(multi_scope_registry):
    """Default returns both scopes."""
    all_axioms = load_axioms(path=multi_scope_registry)
    assert len(all_axioms) == 3


def test_validate_supremacy_empty_when_no_domains(sample_registry):
    """Returns [] with only constitutional axioms."""
    tensions = validate_supremacy(path=sample_registry)
    assert tensions == []


def test_validate_supremacy_detects_domain_t0_blocks(multi_scope_registry):
    """T0 domain blocks produce one tension per domain T0 block."""
    tensions = validate_supremacy(path=multi_scope_registry)
    assert len(tensions) == 1  # mg-001 is the only domain T0 block
    assert tensions[0].domain_impl_id == "mg-001"
    assert "ca-001" in tensions[0].constitutional_impl_id
    assert "operator review" in tensions[0].note


def test_explicit_mode_and_level(tmp_path):
    """Explicit mode/level values in YAML are loaded correctly."""
    reg = tmp_path / "registry.yaml"
    reg.write_text(
        "version: 1\n"
        "axioms:\n"
        "  - id: test_ax\n"
        '    text: "Test"\n'
        "    weight: 50\n"
        "    type: hardcoded\n"
        '    created: "2026-01-01"\n'
        "    status: active\n"
    )
    impl_dir = tmp_path / "implications"
    impl_dir.mkdir()
    (impl_dir / "test_ax.yaml").write_text(
        "axiom_id: test_ax\n"
        "implications:\n"
        "  - id: tx-001\n"
        "    tier: T0\n"
        '    text: "Must provide zero-config"\n'
        "    enforcement: block\n"
        "    canon: purposivist\n"
        "    mode: sufficiency\n"
        "    level: system\n"
        "  - id: tx-002\n"
        "    tier: T1\n"
        '    text: "Must not add auth"\n'
        "    enforcement: review\n"
        "    canon: textualist\n"
        "    mode: compatibility\n"
        "    level: subsystem\n"
    )
    impls = load_implications("test_ax", path=tmp_path)
    assert len(impls) == 2
    assert impls[0].mode == "sufficiency"
    assert impls[0].level == "system"
    assert impls[1].mode == "compatibility"
    assert impls[1].level == "subsystem"


# ── Standalone-schema discovery (cc-task: axioms-loader-discovers-standalone-impls) ──


@pytest.fixture
def standalone_registry(tmp_path):
    """Registry with one list-schema and three standalone-schema files,
    matching the production shape that motivated the audit."""
    reg = tmp_path / "registry.yaml"
    reg.write_text(
        "version: 1\n"
        "axioms:\n"
        "  - id: test_axiom\n"
        '    text: "Test"\n'
        "    weight: 80\n"
        "    type: hardcoded\n"
        '    created: "2026-01-01"\n'
        "    status: active\n"
    )
    impl_dir = tmp_path / "implications"
    impl_dir.mkdir()
    # List-schema entry, parent-axiom-named filename.
    (impl_dir / "test_axiom.yaml").write_text(
        "axiom_id: test_axiom\n"
        "implications:\n"
        "  - id: ta-list-001\n"
        "    tier: T0\n"
        '    text: "List entry."\n'
        "    enforcement: block\n"
        "    canon: textualist\n"
    )
    # Standalone-schema entry, implication-named filename.
    (impl_dir / "ta-standalone-001.yaml").write_text(
        "implication_id: ta-standalone-001\n"
        "axiom_id: test_axiom\n"
        "tier: T1\n"
        "enforcement: review\n"
        "canon: purposivist\n"
        "mode: sufficiency\n"
        "level: system\n"
        'text: "Standalone entry."\n'
    )
    # Standalone-schema entry whose axiom_id is DIFFERENT — must not be
    # discovered when querying for `test_axiom`.
    (impl_dir / "other-axiom-impl.yaml").write_text(
        "implication_id: oth-001\n"
        "axiom_id: other_axiom\n"
        "tier: T0\n"
        'text: "Belongs to other axiom."\n'
    )
    return tmp_path


def test_load_implications_merges_list_and_standalone_schemas(standalone_registry):
    impls = load_implications("test_axiom", path=standalone_registry)
    impl_ids = {i.id for i in impls}
    assert "ta-list-001" in impl_ids  # list-schema regression
    assert "ta-standalone-001" in impl_ids  # standalone-schema discovered
    assert len(impls) == 2


def test_standalone_schema_axiom_id_filter(standalone_registry):
    """Standalone files whose axiom_id != requested are not returned."""
    impls = load_implications("test_axiom", path=standalone_registry)
    assert all(i.axiom_id == "test_axiom" for i in impls)
    assert "oth-001" not in {i.id for i in impls}


def test_standalone_schema_carries_full_metadata(standalone_registry):
    """Standalone-schema rows roundtrip every field through Implication."""
    impls = load_implications("test_axiom", path=standalone_registry)
    standalone = next(i for i in impls if i.id == "ta-standalone-001")
    assert standalone.tier == "T1"
    assert standalone.enforcement == "review"
    assert standalone.canon == "purposivist"
    assert standalone.mode == "sufficiency"
    assert standalone.level == "system"
    assert standalone.text == "Standalone entry."
    assert standalone.axiom_id == "test_axiom"


def test_standalone_only_axiom_returns_only_standalone(tmp_path):
    """An axiom with NO list-schema file but a standalone entry still
    returns the standalone implication."""
    impl_dir = tmp_path / "implications"
    impl_dir.mkdir()
    (impl_dir / "lone-impl.yaml").write_text(
        'implication_id: lone-001\naxiom_id: lone_axiom\ntier: T0\ntext: "Only one."\n'
    )
    impls = load_implications("lone_axiom", path=tmp_path)
    assert len(impls) == 1
    assert impls[0].id == "lone-001"


def test_load_implications_missing_implications_dir_returns_empty(tmp_path):
    """No `implications/` directory → empty list (covers the early-return
    path; pre-fix the loader fell through to the file-not-found case
    which had the same behavior, but the new code is explicit)."""
    assert load_implications("anything", path=tmp_path) == []


def test_standalone_schema_skips_malformed_entry(tmp_path):
    """A malformed standalone file (missing axiom_id) is silently
    skipped; other entries still load."""
    impl_dir = tmp_path / "implications"
    impl_dir.mkdir()
    (impl_dir / "good.yaml").write_text(
        'implication_id: good-001\naxiom_id: target\ntier: T0\ntext: "Good."\n'
    )
    (impl_dir / "bad.yaml").write_text(
        "implication_id: bad-001\n"
        # axiom_id missing — should be skipped
        "tier: T0\n"
        'text: "Bad."\n'
    )
    impls = load_implications("target", path=tmp_path)
    assert len(impls) == 1
    assert impls[0].id == "good-001"


def test_real_implications_directory_discovers_all_four_standalone(tmp_path, monkeypatch):
    """Smoke against the production axioms/implications/ tree.

    The four standalone files identified by the audit all map to known
    axioms:

        - cb-officium-data-boundary.yaml       → corporate_boundary
        - it-irreversible-broadcast.yaml       → interpersonal_transparency
        - mg-drafting-visibility-001.yaml      → management_governance
        - non-formal-referent-policy.yaml      → single_user

    Each must now be discoverable via the canonical loader.
    """
    from shared.axiom_registry import AXIOMS_PATH

    expected = {
        "corporate_boundary": "cb-officium-data-boundary",
        "interpersonal_transparency": "it-irreversible-broadcast",
        "management_governance": "mg-drafting-visibility-001",
        "single_user": "su-non-formal-referent-001",
    }
    for axiom_id, expected_impl_id in expected.items():
        impls = load_implications(axiom_id, path=AXIOMS_PATH)
        impl_ids = {i.id for i in impls}
        assert expected_impl_id in impl_ids, (
            f"axiom {axiom_id!r}: expected {expected_impl_id!r} in {sorted(impl_ids)}"
        )
