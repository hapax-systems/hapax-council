from __future__ import annotations

from agents.hapax_daimonion import daily_segment_prep as prep
from shared.segment_live_event_quality import (
    compare_live_event_quality,
    evaluate_segment_live_event_quality,
)


def _report(script: list[str]) -> dict:
    beats = ["hook", "body", "close"]
    actionability = prep.validate_segment_actionability(script, beats)
    layout = prep.validate_layout_responsibility(actionability["beat_action_intents"])
    contract = prep.build_segment_prep_contract(
        programme_id="live-event-test",
        role="tier_list",
        topic="Live event test",
        segment_beats=beats,
        script=script,
        actionability=actionability,
        layout_responsibility=layout,
        source_refs=["source:live-event-test:receipt"],
    )
    actionability = prep.validate_segment_actionability(script, beats, prep_contract=contract)
    layout = prep.validate_layout_responsibility(actionability["beat_action_intents"])
    contract = prep.build_segment_prep_contract(
        programme_id="live-event-test",
        role="tier_list",
        topic="Live event test",
        segment_beats=beats,
        script=script,
        actionability=actionability,
        layout_responsibility=layout,
        source_refs=["source:live-event-test:receipt"],
        model_contract=contract,
    )
    return evaluate_segment_live_event_quality(
        script,
        beats,
        actionability["beat_action_intents"],
        layout["beat_layout_intents"],
        role="tier_list",
        segment_prep_contract=contract,
    )


def test_generic_metadata_complete_script_fails_live_event_gate() -> None:
    report = _report(
        [
            "This topic is important and many people discuss it.",
            "Another point follows with more careful discussion.",
            "In conclusion, this has been a useful overview.",
        ]
    )

    assert report["ok"] is False
    assert report["band"] == "generic"


def test_grounded_visible_reveal_passes_good_band() -> None:
    report = _report(
        [
            "Number 1 is the source receipt because the source changes confidence when the "
            "manifest is visible.",
            "Now compare the manifest with the ranking rule. Place the receipt gate in S-tier "
            "because the trace changes the ranking and makes the chart inspectable.",
            "So return to the opening receipt and drop it in chat if the S-tier placement follows, "
            "because the payoff is whether the visible chart narrows the claim.",
        ]
    )

    assert report["ok"] is True
    assert report["band"] in {"good", "excellent"}


def test_pairwise_prefers_grounded_live_event_over_generic() -> None:
    generic = _report(
        [
            "This topic is important and many people discuss it.",
            "Another point follows with more careful discussion.",
            "In conclusion, this has been a useful overview.",
        ]
    )
    grounded = _report(
        [
            "Number 1 is the source receipt because the source changes confidence when visible.",
            "Now compare the source trace with the ranking rule. Place the receipt gate in S-tier.",
            "So return to the opening receipt and drop it in chat if the chart narrows the claim.",
        ]
    )

    assert compare_live_event_quality(grounded, generic) == 1


def test_action_refs_do_not_count_as_source_mechanic() -> None:
    script = [
        "Number 1 is the receipt because the visible chart changes.",
        "Now compare the action trace. Place Alpha in S-tier.",
        "So return to the opening chart and drop it in chat.",
    ]
    report = evaluate_segment_live_event_quality(
        script,
        ["hook", "body", "close"],
        [
            {
                "beat_index": 0,
                "intents": [
                    {
                        "kind": "tier_chart",
                        "evidence_refs": ["action:tier_chart:Alpha"],
                    }
                ],
            }
        ],
        [
            {
                "beat_index": 0,
                "needs": ["tier_visual"],
                "evidence_refs": ["action:tier_chart:Alpha"],
            }
        ],
        role="tier_list",
        segment_prep_contract=None,
    )

    assert report["ok"] is False
    assert report["observed"]["source_ref_count"] == 0
    assert "source_as_mechanic" in {item["reason"] for item in report["violations"]}
