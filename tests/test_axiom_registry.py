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
