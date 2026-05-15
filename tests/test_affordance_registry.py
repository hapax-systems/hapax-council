"""Test that the centralized affordance registry covers all domains."""

from shared.affordance_registry import AFFORDANCE_DOMAINS, ALL_AFFORDANCES


def test_all_domains_present():
    expected = {
        "env",
        "body",
        "studio",
        "space",
        "digital",
        "knowledge",
        "social",
        "system",
        "world",
        "narration",
        "chat",
    }
    assert set(AFFORDANCE_DOMAINS.keys()) == expected


def test_all_affordances_have_descriptions():
    for record in ALL_AFFORDANCES:
        assert len(record.description) >= 15, f"{record.name} has too-short description"
        assert record.daemon, f"{record.name} missing daemon"


def test_affordance_names_are_dot_namespaced():
    for record in ALL_AFFORDANCES:
        if record.name in ("shader_graph", "visual_chain", "fortress_visual_response"):
            continue  # legacy names don't use dots
        assert "." in record.name, f"{record.name} is not dot-namespaced"


def test_no_duplicate_names():
    names = [r.name for r in ALL_AFFORDANCES]
    dupes = [n for n in names if names.count(n) > 1]
    assert len(names) == len(set(names)), f"Duplicate affordance names: {dupes}"


def test_world_affordances_do_not_use_interpersonal_consent_for_network_access():
    world = [r for r in ALL_AFFORDANCES if r.name.startswith("world.")]
    for r in world:
        assert r.operational.requires_network, f"{r.name} should require network"
        assert not r.operational.consent_required, (
            f"{r.name} should not conflate network authorization with interpersonal consent"
        )


def test_web_knowledge_does_not_use_interpersonal_consent_for_network_access():
    web = [
        r
        for r in ALL_AFFORDANCES
        if r.name in ("knowledge.web_search", "knowledge.wikipedia", "knowledge.image_search")
    ]
    for r in web:
        assert r.operational.requires_network, f"{r.name} should require network"
        assert not r.operational.consent_required, (
            f"{r.name} should not conflate network authorization with interpersonal consent"
        )


def test_unscoped_consent_affordances_are_deliberate_fail_closed_catalog_entries():
    # Static registry rows do not know which non-operator subject is present.
    # Until a runtime surface enriches a candidate with concrete consent scope,
    # AffordancePipeline must block these consent_required rows fail-closed.
    expected_unscoped = {
        "studio.toggle_livestream",
        "lore_ward.interactive_lore_query",
    }
    unscoped = {
        r.name
        for r in ALL_AFFORDANCES
        if r.operational.consent_required
        and (not r.operational.consent_person_id or not r.operational.consent_data_category)
    }

    assert unscoped == expected_unscoped
