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


def test_consent_required_on_world_affordances():
    world = [r for r in ALL_AFFORDANCES if r.name.startswith("world.")]
    for r in world:
        assert r.operational.consent_required, f"{r.name} should require consent"


def test_consent_required_on_web_knowledge():
    web = [
        r
        for r in ALL_AFFORDANCES
        if r.name in ("knowledge.web_search", "knowledge.wikipedia", "knowledge.image_search")
    ]
    for r in web:
        assert r.operational.consent_required, f"{r.name} should require consent"
        assert r.operational.requires_network, f"{r.name} should require network"
