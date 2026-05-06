"""Tests for content-prep consultation calibration surfaces."""

from __future__ import annotations

from shared.segment_prep_consultation import (
    FRAMEWORK_VOCABULARY_TERMS,
    build_consultation_manifest,
    build_live_event_viability,
    build_readback_obligations,
    build_source_consequence_map,
    framework_vocabulary_hits,
    nonsterile_force_ok,
    validate_consultation_manifest,
    validate_live_event_viability,
    validate_readback_obligations,
    validate_source_consequence_map,
)


def test_consultation_manifest_requires_role_standards_and_advisory_boundary() -> None:
    manifest = build_consultation_manifest("tier_list")

    report = validate_consultation_manifest(manifest, role="tier_list")

    assert report["ok"] is True
    assert manifest["standards_are_advisory"] is True
    assert manifest["prompt_facing_vocabulary_allowed"] is False
    assert manifest["role_standard_refs"]
    assert manifest["exemplar_refs"]
    assert manifest["counterexample_refs"]
    assert "quality_range:excellent_canary:v1" in manifest["quality_range_refs"]


def test_source_consequence_rejects_decorative_citation() -> None:
    script = ["Zuboff appears in the source list. The segment has a topic."]

    source_map = build_source_consequence_map(script)

    assert source_map == []
    assert validate_source_consequence_map(source_map)["ok"] is False


def test_source_consequence_accepts_source_that_changes_claim() -> None:
    script = [
        "Zuboff argues extraction changes the chart, so the ranking places "
        "surveillance capitalism in S-tier because evidence alters the stakes."
    ]

    source_map = build_source_consequence_map(script)

    assert validate_source_consequence_map(source_map)["ok"] is True
    assert source_map[0]["advisory_only"] is True


def test_live_event_viability_requires_visible_or_doable_action_range() -> None:
    script = [
        "Place Alpha in S-tier because Zuboff changes the stakes.",
        "Compare Alpha against Beta because the source limits the claim.",
    ]
    report = build_live_event_viability(
        script,
        actionability={
            "beat_action_intents": [
                {
                    "beat_index": 0,
                    "intents": [
                        {"kind": "rank", "target": "Alpha"},
                        {"kind": "show_evidence", "target": "vault:zuboff-note"},
                    ],
                },
                {
                    "beat_index": 1,
                    "intents": [{"kind": "compare", "target": "Alpha/Beta"}],
                },
            ]
        },
        layout={
            "beat_layout_intents": [
                {"needs": ["ranked_list_visible", "evidence_visible"]},
                {"needs": ["comparison_visible"]},
            ]
        },
        role="tier_list",
    )

    assert validate_live_event_viability(report)["ok"] is True

    weak = build_live_event_viability(
        ["Zuboff is mentioned, and the segment continues."],
        actionability={
            "beat_action_intents": [
                {"beat_index": 0, "intents": [{"kind": "spoken_argument", "target": "topic"}]}
            ]
        },
        layout={"beat_layout_intents": []},
        role="tier_list",
    )
    assert validate_live_event_viability(weak)["ok"] is False


def test_readback_obligations_are_proposal_only_and_non_static() -> None:
    obligations = build_readback_obligations(
        [
            {
                "beat_id": "rank_alpha",
                "needs": ["ranked_list_visible", "evidence_visible"],
                "expected_effects": ["ranked_list_legible", "evidence_on_screen"],
                "evidence_refs": ["vault:zuboff-note"],
                "source_affordances": ["asset:source-card"],
                "default_static_success_allowed": False,
            }
        ]
    )

    assert validate_readback_obligations(obligations)["ok"] is True
    assert obligations[0]["proposal_only"] is True
    assert obligations[0]["runtime_must_receipt"] is True


def test_framework_vocabulary_is_review_only_not_spoken_script() -> None:
    assert "eligibility gate" in FRAMEWORK_VOCABULARY_TERMS

    hits = framework_vocabulary_hits(
        "This eligibility gate proves the consultation_manifest passed."
    )

    assert "eligibility gate" in hits
    assert "consultation_manifest" in hits


def test_nonsterile_force_allows_argument_without_human_inner_life() -> None:
    ok = nonsterile_force_ok(
        [
            "Place Zuboff in S-tier because the source changes the claim, "
            "limits the easy story, and gives the ranking consequence."
        ],
        personage_violations=[],
    )
    bad = nonsterile_force_ok(
        ["I trust this source because my taste prefers it."],
        personage_violations=["I trust this source because my taste prefers it."],
    )

    assert ok["ok"] is True
    assert bad["ok"] is False
