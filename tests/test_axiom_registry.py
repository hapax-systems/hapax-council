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


# ── load_precedents (cc-task: axioms-loader-add-load-precedents) ─────


@pytest.fixture
def precedent_registry(tmp_path):
    """Registry with seed + standalone precedent files for one axiom."""
    impls = tmp_path / "implications"
    impls.mkdir()
    precedents = tmp_path / "precedents"
    seed = precedents / "seed"
    seed.mkdir(parents=True)
    # Seed file with two rows for `target_axiom` + one for `other_axiom`.
    (seed / "test-seeds.yaml").write_text(
        "precedents:\n"
        "  - id: sp-test-001\n"
        "    axiom_id: target_axiom\n"
        '    situation: "First seed."\n'
        "    decision: compliant\n"
        "    tier: T1\n"
        '    created: "2026-01-01"\n'
        "    authority: operator\n"
        "  - id: sp-test-002\n"
        "    axiom_id: target_axiom\n"
        '    situation: "Second seed."\n'
        "    decision: non-compliant\n"
        "    tier: T0\n"
        '    created: "2026-01-02"\n'
        "    authority: operator\n"
        "  - id: sp-other-001\n"
        "    axiom_id: other_axiom\n"
        '    situation: "Different axiom."\n'
        "    decision: compliant\n"
        '    created: "2026-01-03"\n'
        "    authority: operator\n"
    )
    # Standalone-schema file for target_axiom.
    (precedents / "sp-test-standalone-001.yaml").write_text(
        "precedent_id: sp-test-standalone-001\n"
        "axiom_id: target_axiom\n"
        'short_name: "standalone-test"\n'
        'situation: "Standalone case."\n'
        "decision: compliant\n"
        "tier: T2\n"
        'created: "2026-02-01"\n'
        "authority: operator\n"
        "secondary_axioms: [other_axiom]\n"
    )
    # Standalone for a different axiom — must not be returned.
    (precedents / "sp-other-standalone-001.yaml").write_text(
        "precedent_id: sp-other-standalone-001\n"
        "axiom_id: other_axiom\n"
        'situation: "Different."\n'
        "decision: compliant\n"
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


def test_load_precedents_returns_seed_rows_for_axiom(precedent_registry):
    from shared.axiom_registry import load_precedents

    out = load_precedents("target_axiom", path=precedent_registry)
    ids = {p.id for p in out}
    assert "sp-test-001" in ids
    assert "sp-test-002" in ids
    assert "sp-test-standalone-001" in ids


def test_load_precedents_filters_other_axiom(precedent_registry):
    from shared.axiom_registry import load_precedents

    out = load_precedents("target_axiom", path=precedent_registry)
    ids = {p.id for p in out}
    assert "sp-other-001" not in ids
    assert "sp-other-standalone-001" not in ids
    assert all(p.axiom_id == "target_axiom" for p in out)


def test_load_precedents_carries_full_metadata(precedent_registry):
    from shared.axiom_registry import load_precedents

    out = load_precedents("target_axiom", path=precedent_registry)
    standalone = next(p for p in out if p.id == "sp-test-standalone-001")
    assert standalone.tier == "T2"
    assert standalone.decision == "compliant"
    assert standalone.created == "2026-02-01"
    assert standalone.authority == "operator"
    assert standalone.secondary_axioms == ("other_axiom",)


def test_load_precedents_skips_rows_without_axiom_id(tmp_path):
    """A list-schema row without axiom_id is skipped silently."""
    from shared.axiom_registry import load_precedents

    seed = tmp_path / "precedents" / "seed"
    seed.mkdir(parents=True)
    (seed / "broken.yaml").write_text(
        "precedents:\n"
        "  - id: sp-good\n"
        "    axiom_id: target\n"
        '    situation: "Good."\n'
        "    decision: compliant\n"
        "  - id: sp-bad\n"
        # axiom_id missing
        '    situation: "Bad."\n'
        "    decision: compliant\n"
    )
    out = load_precedents("target", path=tmp_path)
    ids = {p.id for p in out}
    assert "sp-good" in ids
    assert "sp-bad" not in ids


def test_load_precedents_missing_dir(tmp_path):
    from shared.axiom_registry import load_precedents

    assert load_precedents("anything", path=tmp_path) == []


def test_load_precedents_falls_back_to_parent_doc_axiom_id(tmp_path):
    """Single-axiom seed files declare ``axiom_id`` once at the top
    of the document; rows inherit. The loader must fall back to the
    parent-doc axiom_id when a row doesn't carry its own.

    Production examples: ``axioms/precedents/seed/single-user-seeds.yaml``,
    ``executive-function-seeds.yaml``, ``management-seeds.yaml``.
    """
    from shared.axiom_registry import load_precedents

    seed = tmp_path / "precedents" / "seed"
    seed.mkdir(parents=True)
    (seed / "inherited.yaml").write_text(
        "axiom_id: parent_axiom\n"
        "precedents:\n"
        "  - id: sp-bare-001\n"
        '    situation: "First bare row."\n'
        "    decision: compliant\n"
        "    tier: T1\n"
        "  - id: sp-bare-002\n"
        '    situation: "Second bare row."\n'
        "    decision: compliant\n"
        "    tier: T0\n"
    )
    out = load_precedents("parent_axiom", path=tmp_path)
    ids = {p.id for p in out}
    assert "sp-bare-001" in ids
    assert "sp-bare-002" in ids
    assert all(p.axiom_id == "parent_axiom" for p in out)


def test_load_precedents_per_row_axiom_id_overrides_parent(tmp_path):
    """When a row declares its own axiom_id (multi-axiom seed shape),
    it overrides the parent-doc axiom_id. Mixed files are valid."""
    from shared.axiom_registry import load_precedents

    seed = tmp_path / "precedents" / "seed"
    seed.mkdir(parents=True)
    (seed / "mixed.yaml").write_text(
        "axiom_id: parent_axiom\n"
        "precedents:\n"
        "  - id: sp-inherits\n"
        '    situation: "Inherits parent."\n'
        "    decision: compliant\n"
        "  - id: sp-overrides\n"
        "    axiom_id: other_axiom\n"
        '    situation: "Overrides to other."\n'
        "    decision: compliant\n"
    )
    parent_out = load_precedents("parent_axiom", path=tmp_path)
    parent_ids = {p.id for p in parent_out}
    assert "sp-inherits" in parent_ids
    assert "sp-overrides" not in parent_ids

    other_out = load_precedents("other_axiom", path=tmp_path)
    other_ids = {p.id for p in other_out}
    assert "sp-overrides" in other_ids
    assert "sp-inherits" not in other_ids


def test_load_precedents_real_tree_resolves_known_ids():
    """Smoke against the production axioms/precedents/ tree.

    `single_user` and `management_governance` axioms each have at
    least one standalone precedent file plus seed entries; both
    must be discoverable via the loader. This pins both seed shapes:
    sp-su-001..004 use parent-doc inheritance; sp-arch-* use per-row
    axiom_id; sp-su-005 is standalone-schema.
    """
    from shared.axiom_registry import AXIOMS_PATH, load_precedents

    su = load_precedents("single_user", path=AXIOMS_PATH)
    su_ids = {p.id for p in su}
    # The standalone sp-su-005-worktree-isolation must appear.
    assert "sp-su-005-worktree-isolation" in su_ids
    # Inherited seed entries (single-user-seeds.yaml uses parent-doc
    # axiom_id) must appear.
    assert "sp-su-001" in su_ids
    assert "sp-su-004" in su_ids
    # Per-row seed entries (architecture-seeds.yaml has rows targeting
    # single_user) must appear.
    assert any(p.id.startswith("sp-arch-") for p in su)

    mg = load_precedents("management_governance", path=AXIOMS_PATH)
    mg_ids = {p.id for p in mg}
    assert "sp-hsea-mg-001" in mg_ids
    assert "sp-mgmt-001" in mg_ids  # inherited from management-seeds.yaml top-level

    ef = load_precedents("executive_function", path=AXIOMS_PATH)
    ef_ids = {p.id for p in ef}
    # executive-function-seeds.yaml uses parent-doc axiom_id.
    assert "sp-ef-001" in ef_ids


# ── Implication.linkage (cc-task: coherence-orphan-implications-catalog follow-up) ──


def test_implication_linkage_default_empty(tmp_path):
    """Implications without an explicit `linkage` field default to empty
    string — meaning they SHOULD have a constitutive rule feeding them."""
    impl_dir = tmp_path / "implications"
    impl_dir.mkdir()
    (impl_dir / "test_axiom.yaml").write_text(
        "axiom_id: test_axiom\n"
        "implications:\n"
        "  - id: ta-001\n"
        "    tier: T0\n"
        '    text: "No linkage declared."\n'
        "    enforcement: block\n"
        "    canon: textualist\n"
    )
    impls = load_implications("test_axiom", path=tmp_path)
    assert len(impls) == 1
    assert impls[0].linkage == ""


def test_implication_linkage_code_direct_explicit(tmp_path):
    """List-schema rows can declare `linkage: code-direct` to opt out of
    coherence orphan-tracking."""
    impl_dir = tmp_path / "implications"
    impl_dir.mkdir()
    (impl_dir / "test_axiom.yaml").write_text(
        "axiom_id: test_axiom\n"
        "implications:\n"
        "  - id: ta-001\n"
        "    tier: T0\n"
        '    text: "Code-direct."\n'
        "    enforcement: block\n"
        "    canon: textualist\n"
        "    linkage: code-direct\n"
    )
    impls = load_implications("test_axiom", path=tmp_path)
    assert impls[0].linkage == "code-direct"


def test_standalone_schema_linkage_field(tmp_path):
    """Standalone-schema files carry `linkage` at top level same as
    other Implication fields. Pins that the four production standalone
    files annotated with `linkage: code-direct` round-trip cleanly."""
    impl_dir = tmp_path / "implications"
    impl_dir.mkdir()
    (impl_dir / "cd-impl.yaml").write_text(
        "implication_id: cd-001\n"
        "axiom_id: target\n"
        "linkage: code-direct\n"
        "tier: T0\n"
        'text: "Standalone code-direct."\n'
        "enforcement: block\n"
    )
    impls = load_implications("target", path=tmp_path)
    assert len(impls) == 1
    assert impls[0].linkage == "code-direct"


def test_check_coherence_skips_code_direct_implications(tmp_path):
    """coherence.check_coherence skips implications with
    linkage='code-direct' from the orphan tally."""
    from shared.coherence import check_coherence

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
    # One regular impl (orphan, expected to flag) + one code-direct
    # (should NOT flag).
    (impl_dir / "test_axiom.yaml").write_text(
        "axiom_id: test_axiom\n"
        "implications:\n"
        "  - id: ta-orphan\n"
        "    tier: T0\n"
        '    text: "Orphan."\n'
        "    enforcement: block\n"
        "    canon: textualist\n"
        "  - id: ta-code-direct\n"
        "    tier: T0\n"
        '    text: "Code-direct."\n'
        "    enforcement: block\n"
        "    canon: textualist\n"
        "    linkage: code-direct\n"
    )
    # Empty constitutive-rules so neither impl gets linked.
    (tmp_path / "constitutive-rules.yaml").write_text("rules: []\n")
    report = check_coherence(axioms_path=tmp_path)
    orphan_ids = {g.source_id for g in report.gaps if g.gap_type == "orphan_implication"}
    assert "ta-orphan" in orphan_ids
    assert "ta-code-direct" not in orphan_ids


def test_check_coherence_real_tree_drops_4_standalone_orphans():
    """After annotating the 4 standalone implications with
    linkage: code-direct, the production-tree orphan count must drop
    by 4 — no longer flagging cb-officium-data-boundary,
    it-irreversible-broadcast, mg-drafting-visibility-001,
    su-non-formal-referent-001."""
    from shared.coherence import check_coherence

    report = check_coherence()
    orphan_ids = {g.source_id for g in report.gaps if g.gap_type == "orphan_implication"}
    for not_orphan in (
        "cb-officium-data-boundary",
        "it-irreversible-broadcast",
        "mg-drafting-visibility-001",
        "su-non-formal-referent-001",
    ):
        assert not_orphan not in orphan_ids, (
            f"{not_orphan} should be excluded as code-direct, but appears in orphan tally"
        )


def test_check_coherence_real_tree_drops_su_and_it_cluster_orphans():
    """Phase 5 of the orphan-train: 3 single_user + 2
    interpersonal_transparency impls annotated as code-direct.

    su-* code-direct: su-auth-001, su-privacy-001, su-decision-001.
    it-* code-direct: it-attribution-001, it-audit-001.

    Pins that paper-rule it-* impls (it-inspect-001, it-revoke-001,
    it-scope-001, it-backend-001, it-inference-001) remain as
    legitimate orphans.
    """
    from shared.coherence import check_coherence

    report = check_coherence()
    orphan_ids = {g.source_id for g in report.gaps if g.gap_type == "orphan_implication"}
    code_direct = (
        "su-auth-001",
        "su-privacy-001",
        "su-decision-001",
        "it-attribution-001",
        "it-audit-001",
    )
    for not_orphan in code_direct:
        assert not_orphan not in orphan_ids, (
            f"{not_orphan} should be excluded as code-direct, but appears in orphan tally"
        )
    paper_rules = (
        "it-inspect-001",
        "it-revoke-001",
        "it-scope-001",
        "it-backend-001",
        "it-inference-001",
    )
    for orphan in paper_rules:
        assert orphan in orphan_ids, (
            f"{orphan} has no code references; should remain orphan but doesn't appear"
        )


def test_implication_status_default_active():
    """Implications without explicit `status` default to 'active'."""
    from shared.axiom_registry import load_implications

    # Use any production implication; sample one from the corpus.
    impls = load_implications("single_user")
    assert impls, "production single_user impls should load"
    # All non-retired impls have status='active'.
    actives = [i for i in impls if i.status == "active"]
    assert actives  # at least some are active
    for impl in actives:
        assert impl.status == "active"


def test_implication_status_retired_excluded_from_orphan_tally():
    """Phase 3 of the orphan-train: 3 retired impls (cb-extensible-001,
    cb-parity-001, mg-prep-001) annotated with status: retired must
    be excluded from the orphan tally entirely.
    """
    from shared.coherence import check_coherence

    report = check_coherence()
    orphan_ids = {g.source_id for g in report.gaps if g.gap_type == "orphan_implication"}
    retired = ("cb-extensible-001", "cb-parity-001", "mg-prep-001")
    for ret in retired:
        assert ret not in orphan_ids, (
            f"{ret} is status: retired; must be excluded from orphan tally"
        )


def test_check_coherence_real_tree_drops_16_ex_cluster_orphans():
    """Phase 4 of the orphan-train: 16 executive_function impls
    annotated as code-direct (all verified text-referenced in
    `agents/_sufficiency_probes.py`, `agents/drift_detector/probes_*.py`,
    `agents/manifests/hapax_daimonion.yaml`, and
    `agents/studio_compositor/structural_director.py`).
    """
    from shared.coherence import check_coherence

    report = check_coherence()
    orphan_ids = {g.source_id for g in report.gaps if g.gap_type == "orphan_implication"}
    code_direct = (
        "ex-alert-001",
        "ex-alert-004",
        "ex-attention-001",
        "ex-cognitive-009",
        "ex-delib-001",
        "ex-delib-002",
        "ex-delib-003",
        "ex-delib-004",
        "ex-err-001",
        "ex-init-001",
        "ex-memory-010",
        "ex-prose-001",
        "ex-routine-001",
        "ex-routine-007",
        "ex-skill-health-001",
        "ex-state-001",
    )
    for not_orphan in code_direct:
        assert not_orphan not in orphan_ids, (
            f"{not_orphan} should be excluded as code-direct, but appears in orphan tally"
        )


def test_check_coherence_real_tree_drops_3_mg_cluster_orphans():
    """The management_governance cluster (mg-boundary-001/002,
    mg-cadence-001) is text-referenced in `shared/axiom_patterns.txt`,
    `scripts/run_deliberations.py`, `agents/hapax_daimonion/governor.py`,
    and `agents/drift_detector/sufficiency_probes.py`. After
    annotating with linkage: code-direct, these 3 must NOT appear in
    the production-tree orphan tally.

    mg-selfreport-001, mg-deterministic-001, mg-bridge-001,
    mg-prep-001 stay as legitimate orphans (no code references) —
    real wiring backlog.
    """
    from shared.coherence import check_coherence

    report = check_coherence()
    orphan_ids = {g.source_id for g in report.gaps if g.gap_type == "orphan_implication"}
    code_direct = ("mg-boundary-001", "mg-boundary-002", "mg-cadence-001")
    for not_orphan in code_direct:
        assert not_orphan not in orphan_ids, (
            f"{not_orphan} should be excluded as code-direct, but appears in orphan tally"
        )
    # mg-prep-001 was retired in Phase 3 (status: retired); the other
    # 3 remain as legitimate orphans pending Phase 2 wiring or Phase 3
    # retirement of their own.
    legitimate_orphans = (
        "mg-selfreport-001",
        "mg-deterministic-001",
        "mg-bridge-001",
    )
    for orphan in legitimate_orphans:
        assert orphan in orphan_ids, (
            f"{orphan} has no code references; should remain orphan but doesn't appear"
        )
    assert "mg-prep-001" not in orphan_ids, (
        "mg-prep-001 should be retired (status:retired); must not appear in orphan tally"
    )


def test_check_coherence_real_tree_drops_5_cb_cluster_orphans():
    """The corporate_boundary cluster (cb-data-001, cb-degrade-001,
    cb-key-001, cb-llm-001, cb-secret-scan-001) is text-referenced in
    `agents/_sufficiency_probes.py` + `agents/drift_detector/probes_boundary.py`
    + manifests. After annotating with linkage: code-direct, these 5
    must NOT appear in the production-tree orphan tally.

    cb-extensible-001 and cb-parity-001 stay as legitimate orphans
    (no code references found).
    """
    from shared.coherence import check_coherence

    report = check_coherence()
    orphan_ids = {g.source_id for g in report.gaps if g.gap_type == "orphan_implication"}
    code_direct = (
        "cb-data-001",
        "cb-degrade-001",
        "cb-key-001",
        "cb-llm-001",
        "cb-secret-scan-001",
    )
    for not_orphan in code_direct:
        assert not_orphan not in orphan_ids, (
            f"{not_orphan} should be excluded as code-direct, but appears in orphan tally"
        )
    # cb-extensible-001 and cb-parity-001 were retired in the Phase 3
    # dead-letter retirement batch (status: retired). They no longer
    # appear in the orphan tally — that is the intended behavior.
    retired = ("cb-extensible-001", "cb-parity-001")
    for ret in retired:
        assert ret not in orphan_ids, (
            f"{ret} should be retired (status:retired); must not appear in orphan tally"
        )
