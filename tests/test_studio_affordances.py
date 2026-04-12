"""Test that studio control and output affordances are registered."""

from shared.affordance_registry import AFFORDANCE_DOMAINS, ALL_AFFORDANCES


def test_studio_control_affordances_exist():
    studio = AFFORDANCE_DOMAINS.get("studio", [])
    control_names = [
        r.name
        for r in studio
        if any(
            k in r.name
            for k in [
                "activate",
                "adjust",
                "select",
                "toggle",
                "bind",
                "add_effect",
                "remove_effect",
            ]
        )
    ]
    assert len(control_names) >= 8, f"Expected >=8 studio control affordances, got {control_names}"


def test_output_affordances_exist():
    output_names = [r.name for r in ALL_AFFORDANCES if r.name.startswith("studio.output_")]
    assert len(output_names) >= 3, f"Expected >=3 output affordances, got {output_names}"


def test_studio_control_descriptions_are_gibson_verbs():
    studio = AFFORDANCE_DOMAINS.get("studio", [])
    controls = [r for r in studio if r.daemon == "compositor"]
    for r in controls:
        assert len(r.description) >= 15, f"{r.name} description too short"
        # Gibson verbs: transform, fine-tune, enable, shift, choose, connect, insert, remove, start, capture, display, route
        assert not r.description.startswith("API"), f"{r.name} description leaks implementation"


def test_no_duplicate_names_after_additions():
    names = [r.name for r in ALL_AFFORDANCES]
    dupes = [n for n in names if names.count(n) > 1]
    assert len(names) == len(set(names)), f"Duplicate affordance names: {set(dupes)}"


def test_toggle_livestream_affordance_registered():
    """CC1 — stream-as-affordance.

    Beta-side registration; the compositor-side RTMP handler is alpha's
    A7 prerequisite per the 2026-04-12 work-stream split. The capability
    must require consent because broadcasting room imagery to a public
    destination is materially different from local-only routing — axiom
    interpersonal_transparency.
    """
    studio = AFFORDANCE_DOMAINS.get("studio", [])
    livestream = [r for r in studio if r.name == "studio.toggle_livestream"]
    assert len(livestream) == 1, "studio.toggle_livestream should be registered exactly once"
    cap = livestream[0]
    assert cap.daemon == "compositor", "handler lives in studio_compositor (alpha owns the trigger)"
    assert cap.operational.consent_required is True, (
        "livestream affordance must require consent — axiom interpersonal_transparency"
    )
    assert cap.operational.latency_class == "slow", (
        "RTMP handshake takes seconds, not milliseconds — keeps the recruiter from "
        "starvation-cycling start/stop on a fast tier"
    )
    assert "broadcast" in cap.description.lower() or "stream" in cap.description.lower(), (
        "description should make the streaming intent obvious to the embedding model"
    )
