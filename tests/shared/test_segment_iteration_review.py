from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agents.hapax_daimonion import daily_segment_prep as prep
from scripts.review_one_segment_iteration import main as review_cli_main
from shared.segment_iteration_review import review_one_segment_iteration
from shared.segment_quality_actionability import (
    LAYOUT_RESPONSIBILITY_VERSION,
    QUALITY_RUBRIC_VERSION,
    validate_layout_responsibility,
    validate_segment_actionability,
)

EXCELLENT_SCRIPT = [
    (
        "Number 1 is the Command-R manifest gate because it turns a prepared segment into "
        "something the host can audit instead of something the model merely asserts. Shoshana "
        "Zuboff argues that measurement systems become social systems when nobody can inspect "
        "their extraction, and that is the exact problem for livestream craft: the audience hears "
        "confidence while the runtime still owes proof. The stakes are practical, not ceremonial. "
        "Place the Command-R manifest gate in S-tier because the manifest, prompt hash, and "
        "source hash have to stay visible enough that the claim can be checked. Remember that "
        "opening rule, because the final nine should inherit this gate rather than trusting a "
        "polished voice."
    ),
    (
        "Now compare that with the layout responsibility gate, because StudioCompositor and "
        "LayoutState are where the spoken claim either becomes visible or remains only speech. "
        "Place rendered LayoutState in S-tier for the canary, while LayoutStore gauge success is "
        "only B-tier evidence, because a stored switch can look successful without changing the "
        "frame assignments that the audience sees. This is the pivot: a default host shot can feel "
        "stable while laundering failure. The consequence is that any chart, comparison, or chat "
        "prompt in the script needs a typed layout need and a pending runtime readback, not a "
        "prepared command pretending to be the broadcast authority."
    ),
    (
        "So the actionability test is simple and uncomfortable: what the script says should have "
        "a visible or doable counterpart, and what cannot be witnessed should be spoken as argument "
        "rather than advertised as a screen event. What do you think? Drop it in chat if the ranking "
        "gate is stricter than the content needs, because that response is itself a supported surface "
        "instead of an imaginary clip. The callback is Zuboff again: systems become trustworthy only "
        "when their operations can be inspected. The next move is not the next nine segments; it is "
        "one canary receipt that proves the script, action intents, and layout posture all agree."
    ),
]


GENERIC_SCRIPT = [
    "This topic is interesting and important. There are many things to consider.",
    "Another point is also important. We should think about it carefully.",
    "In conclusion, this was a good discussion. Thanks for watching.",
]

ONE_ACTION_KIND_SCRIPT = [
    (
        "Compare the canary method with the final-nine method because the stream needs a "
        "visible reason to pause before scaling. Shoshana Zuboff argues that systems earn "
        "trust only when their operations can be inspected, and that gives this bit its "
        "stakes: the host cannot treat a polished segment as production-ready until the "
        "canary receipt is visible. Compare the prepared artifact to the runtime review "
        "again, because the audience should hear why one segment is a gate rather than a "
        "sample. Remember the opening constraint: the method has to show its work before "
        "the next nine inherit it."
    ),
    (
        "Now compare the script prior with the actionability prior, because a good segment "
        "can still fail if every spoken move remains invisible. Zuboff's measurement warning "
        "matters here: confident narration can hide the fact that no surface changed and no "
        "viewer action became possible. Compare the receipt fields one by one and keep the "
        "pressure on the same question: what did the audience actually see or do? The turn is "
        "that comparison alone can be coherent without being rich enough for an ideal bit."
    ),
    (
        "So compare the final decision with the first sentence and make the callback explicit. "
        "If the canary cannot show why it is safer than the final-nine path, the method is not "
        "ready. Zuboff's argument returns as a craft rule: inspectable systems make better "
        "livestream promises. Compare the review receipt with the segment itself, then hold "
        "the next nine until the script, source prior, and visible runtime responsibility agree."
    ),
]

WEAK_SOURCE_SCRIPT = [
    (
        "#1 is this careful method because it gives the show a way to pause before scaling. "
        "the problem is important because a confident segment can sound complete while still "
        "needing proof. the stakes are practical: if the review cannot explain what changed, "
        "then the next batch should wait. remember the opening rule, because the final nine "
        "should inherit a visible gate instead of trusting a polished voice. this is clear, "
        "direct, and paced for the audience, but it deliberately avoids named references or "
        "grounded argument from any cited prior."
    ),
    (
        "now compare this first method with the later method, because the difference has to "
        "be visible in the review. place this canary gate in S-tier for caution, because it "
        "keeps the process from rushing past a weak script. the turn is that a segment can be "
        "orderly and still fail the fidelity bar. it can have shape, stakes, and a surface "
        "action while never showing where the prior came from or why the audience should "
        "trust the argument."
    ),
    (
        "so the closing move is to ask the audience to check the method rather than admire "
        "the confidence. what do you think? drop it in chat if the review should be stricter "
        "before the next nine. the callback is the first rule again: a good canary needs a "
        "visible receipt and a real grounded prior. this version has enough motion to look "
        "like a bit, but it still lacks reference fidelity and should not pass the ideal gate."
    ),
]


def _artifact(script: list[str]) -> dict[str, Any]:
    beats = ["manifest gate", "layout responsibility", "actionability close"]
    prompt_sha256 = prep._sha256_text("prompt")
    seed_sha256 = prep._sha256_text("seed")
    actionability = validate_segment_actionability(script, beats)
    layout = validate_layout_responsibility(actionability["beat_action_intents"])
    source_hashes = prep._source_hashes_from_fields(
        programme_id="prog-canary",
        role="tier_list",
        topic="One segment iteration review",
        segment_beats=beats,
        seed_sha256=seed_sha256,
        prompt_sha256=prompt_sha256,
    )
    payload: dict[str, Any] = {
        "schema_version": prep.PREP_ARTIFACT_SCHEMA_VERSION,
        "authority": prep.PREP_ARTIFACT_AUTHORITY,
        "programme_id": "prog-canary",
        "role": "tier_list",
        "topic": "One segment iteration review",
        "segment_beats": beats,
        "prepared_script": script,
        "segment_quality_rubric_version": QUALITY_RUBRIC_VERSION,
        "actionability_rubric_version": prep.ACTIONABILITY_RUBRIC_VERSION,
        "layout_responsibility_version": LAYOUT_RESPONSIBILITY_VERSION,
        "hosting_context": layout["hosting_context"],
        "segment_quality_report": prep.score_segment_quality(script, beats),
        "beat_action_intents": actionability["beat_action_intents"],
        "actionability_alignment": {
            "ok": actionability["ok"],
            "removed_unsupported_action_lines": actionability["removed_unsupported_action_lines"],
        },
        "beat_layout_intents": layout["beat_layout_intents"],
        "layout_decision_contract": layout["layout_decision_contract"],
        "runtime_layout_validation": layout["runtime_layout_validation"],
        "layout_decision_receipts": layout["layout_decision_receipts"],
        "prepped_at": "2026-05-06T04:00:00+00:00",
        "prep_session_id": "segment-prep-canary-test",
        "model_id": prep.RESIDENT_PREP_MODEL,
        "prompt_sha256": prompt_sha256,
        "seed_sha256": seed_sha256,
        "source_hashes": source_hashes,
        "source_provenance_sha256": prep._sha256_json(source_hashes),
        "llm_calls": [
            {
                "call_index": 1,
                "phase": "compose",
                "programme_id": "prog-canary",
                "model_id": prep.RESIDENT_PREP_MODEL,
                "prompt_sha256": prompt_sha256,
                "prompt_chars": 100,
                "called_at": "2026-05-06T04:00:00+00:00",
            }
        ],
        "beat_count": len(beats),
        "avg_chars_per_beat": round(sum(len(item) for item in script) / len(script)),
        "refinement_applied": True,
    }
    payload["artifact_sha256"] = prep._artifact_hash(payload)
    return payload


def _team_receipts_for(artifact: dict[str, Any]) -> list[dict[str, str]]:
    base = {
        "artifact_sha256": artifact["artifact_sha256"],
        "programme_id": artifact["programme_id"],
        "iteration_id": artifact["prep_session_id"],
    }
    return [
        {
            **base,
            "role": "script_quality",
            "verdict": "approved",
            "reviewer": "cx-gold",
            "checked_at": "2026-05-06T04:00:00Z",
            "receipt_id": "script-quality-pass",
            "notes": "Script clears canary fidelity with concrete stakes and grounded prior.",
        },
        {
            **base,
            "role": "actionability_layout",
            "verdict": "approved",
            "reviewer": "cx-gold",
            "checked_at": "2026-05-06T04:00:00Z",
            "receipt_id": "actionability-layout-pass",
            "notes": "Visible and doable claims align to layout needs and evidence refs.",
        },
        {
            **base,
            "role": "layout_responsibility",
            "verdict": "approved",
            "reviewer": "cx-gold",
            "checked_at": "2026-05-06T04:00:00Z",
            "receipt_id": "layout-responsibility-pass",
            "notes": "Prepared artifact stays proposal-only pending witnessed runtime readback.",
        },
    ]


def _failed_criteria(receipt: dict[str, Any]) -> set[str]:
    return {
        item["name"] for item in receipt["automated_gate"]["criteria"] if item["passed"] is False
    }


def _rehash_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    artifact["artifact_sha256"] = prep._artifact_hash(artifact)
    return artifact


def _write_manifest_artifact(tmp_path: Path, artifact: dict[str, Any]) -> Path:
    today = prep._today_dir(tmp_path)
    path = today / prep._programme_artifact_name(artifact["programme_id"])
    path.write_text(json.dumps(artifact), encoding="utf-8")
    (today / "manifest.json").write_text(
        json.dumps({"programmes": [path.name]}),
        encoding="utf-8",
    )
    return path


def test_one_segment_review_blocks_until_team_critique_receipts_pass() -> None:
    receipt = review_one_segment_iteration([_artifact(EXCELLENT_SCRIPT)])

    assert receipt["automated_gate"]["passed"] is True
    assert receipt["ready_for_next_nine"] is False
    assert receipt["decision"] == "team_critique_required"
    assert receipt["team_critique_loop"]["pending_roles"] == [
        "script_quality",
        "actionability_layout",
        "layout_responsibility",
    ]


def test_one_segment_review_accepts_after_automation_and_team_receipts() -> None:
    artifact = _artifact(EXCELLENT_SCRIPT)
    receipt = review_one_segment_iteration(
        [artifact],
        team_critique_receipts=_team_receipts_for(artifact),
    )

    assert receipt["automated_gate"]["passed"] is True
    assert receipt["team_critique_loop"]["passed"] is True
    assert receipt["ready_for_next_nine"] is True
    assert receipt["decision"] == "ready_for_next_nine"
    assert receipt["next_nine_gate_mode"] == "blocking_review_receipt"
    assert receipt["resident_model_continuity"] == {
        "expected_model": prep.RESIDENT_PREP_MODEL,
        "no_qwen": True,
        "no_unload_or_swap": True,
    }


def test_one_segment_review_accepts_multi_phase_resident_call_provenance() -> None:
    artifact = _artifact(EXCELLENT_SCRIPT)
    artifact["llm_calls"].extend(
        [
            {
                "call_index": 2,
                "phase": "refine",
                "programme_id": artifact["programme_id"],
                "model_id": prep.RESIDENT_PREP_MODEL,
                "prompt_sha256": prep._sha256_text("refine prompt"),
                "prompt_chars": 1220,
                "called_at": "2026-05-06T04:01:00+00:00",
            },
            {
                "call_index": 3,
                "phase": "layout_repair",
                "programme_id": artifact["programme_id"],
                "model_id": prep.RESIDENT_PREP_MODEL,
                "prompt_sha256": prep._sha256_text("layout repair prompt"),
                "prompt_chars": 1330,
                "called_at": "2026-05-06T04:02:00+00:00",
            },
        ]
    )
    _rehash_artifact(artifact)

    receipt = review_one_segment_iteration(
        [artifact],
        team_critique_receipts=_team_receipts_for(artifact),
    )

    assert receipt["ready_for_next_nine"] is True
    assert "artifact.prior_source_binding" not in _failed_criteria(receipt)


def test_one_segment_review_accepts_real_loader_objects_without_enriched_hash_mismatch(
    tmp_path: Path,
) -> None:
    artifact = _artifact(EXCELLENT_SCRIPT)
    path = _write_manifest_artifact(tmp_path, artifact)
    loaded = prep.load_prepped_programmes(tmp_path)

    assert len(loaded) == 1
    assert loaded[0]["acceptance_gate"] == "daily_segment_prep.load_prepped_programmes"
    assert loaded[0]["artifact_path"] == str(path)
    assert loaded[0]["runtime_layout_validation"] != artifact["runtime_layout_validation"]

    receipt = review_one_segment_iteration(
        loaded,
        team_critique_receipts=_team_receipts_for(artifact),
    )

    assert receipt["automated_gate"]["passed"] is True
    assert receipt["ready_for_next_nine"] is True
    assert receipt["artifact_path"] == str(path)
    assert not {
        "artifact.hash_receipt",
        "layout.responsible_proposal_only",
        "layout.intent_receipt_freshness",
    } & _failed_criteria(receipt)
    assert receipt["artifact_extraction"] == {
        "accepted_artifact_count": 1,
        "manifest_gate": True,
        "loader_acceptance_gate": "daily_segment_prep.load_prepped_programmes",
        "raw_loader_separation": True,
    }


def test_review_cli_uses_loader_path_but_reviews_saved_raw_artifact(
    tmp_path: Path,
) -> None:
    artifact = _artifact(EXCELLENT_SCRIPT)
    _write_manifest_artifact(tmp_path, artifact)
    team_path = tmp_path / "team-receipts.json"
    receipt_path = tmp_path / "review-receipt.json"
    team_path.write_text(
        json.dumps({"team_critique_receipts": _team_receipts_for(artifact)}),
        encoding="utf-8",
    )

    assert (
        review_cli_main(
            [
                "--prep-dir",
                str(tmp_path),
                "--team-receipts",
                str(team_path),
                "--receipt-out",
                str(receipt_path),
            ]
        )
        == 0
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert receipt["automated_gate"]["passed"] is True
    assert receipt["ready_for_next_nine"] is True
    assert "artifact.hash_receipt" not in _failed_criteria(receipt)


def test_team_critique_receipts_bind_to_artifact_programme_and_iteration() -> None:
    artifact = _artifact(EXCELLENT_SCRIPT)
    receipts = _team_receipts_for(artifact)
    receipts[0]["artifact_sha256"] = "0" * 64
    receipts[1]["iteration_id"] = "stale-iteration"
    receipts[2]["notes"] = "approved"

    receipt = review_one_segment_iteration(
        [artifact],
        team_critique_receipts=receipts,
    )

    assert receipt["automated_gate"]["passed"] is True
    assert receipt["ready_for_next_nine"] is False
    assert receipt["team_critique_loop"]["passed"] is False
    assert receipt["team_critique_loop"]["pending_roles"] == [
        "script_quality",
        "actionability_layout",
        "layout_responsibility",
    ]
    assert receipt["team_critique_loop"]["malformed_receipts"] == [
        "receipt[0] artifact_sha256 does not match canary artifact",
        "receipt[1] iteration_id does not match canary iteration",
        "receipt[2] notes are not substantive",
    ]


def test_one_segment_review_requires_exactly_one_manifest_accepted_artifact() -> None:
    receipt = review_one_segment_iteration([])
    assert receipt["ready_for_next_nine"] is False
    assert "artifact.exactly_one_manifest_accepted" in _failed_criteria(receipt)

    receipt = review_one_segment_iteration(
        [_artifact(EXCELLENT_SCRIPT), _artifact(EXCELLENT_SCRIPT)]
    )
    assert receipt["ready_for_next_nine"] is False
    assert "artifact.exactly_one_manifest_accepted" in _failed_criteria(receipt)


def test_one_segment_review_rejects_generic_script_even_with_team_receipts() -> None:
    artifact = _artifact(GENERIC_SCRIPT)
    receipt = review_one_segment_iteration(
        [artifact],
        team_critique_receipts=_team_receipts_for(artifact),
    )

    assert receipt["ready_for_next_nine"] is False
    assert "script.quality_floor" in _failed_criteria(receipt)


def test_one_segment_review_rejects_single_action_kind_even_if_script_is_sourceful() -> None:
    artifact = _artifact(ONE_ACTION_KIND_SCRIPT)
    receipt = review_one_segment_iteration(
        [artifact],
        team_critique_receipts=_team_receipts_for(artifact),
    )

    assert receipt["ready_for_next_nine"] is False
    assert "actionability.visible_or_doable_counterpart" in _failed_criteria(receipt)


def test_one_segment_review_rejects_weak_source_fidelity() -> None:
    artifact = _artifact(WEAK_SOURCE_SCRIPT)
    receipt = review_one_segment_iteration(
        [artifact],
        team_critique_receipts=_team_receipts_for(artifact),
    )

    assert receipt["ready_for_next_nine"] is False
    assert "script.source_fidelity" in _failed_criteria(receipt)


def test_one_segment_review_rejects_wrong_model_and_layout_success_laundering() -> None:
    artifact = _artifact(EXCELLENT_SCRIPT)
    artifact["model_id"] = "Qwen3.5-9B-exl3-5.00bpw"
    artifact["runtime_layout_validation"] = {
        **artifact["runtime_layout_validation"],
        "status": "success",
        "layout_success": True,
    }
    _rehash_artifact(artifact)

    receipt = review_one_segment_iteration(
        [artifact],
        team_critique_receipts=_team_receipts_for(artifact),
    )

    assert receipt["ready_for_next_nine"] is False
    assert {
        "artifact.command_r_model",
        "layout.responsible_proposal_only",
    }.issubset(_failed_criteria(receipt))


def test_one_segment_review_rejects_stale_prior_source_binding() -> None:
    artifact = _artifact(EXCELLENT_SCRIPT)
    artifact["source_hashes"] = {
        **artifact["source_hashes"],
        "prompt_sha256": prep._sha256_text("different-prompt"),
    }
    artifact["source_provenance_sha256"] = prep._sha256_json(artifact["source_hashes"])
    _rehash_artifact(artifact)

    receipt = review_one_segment_iteration(
        [artifact],
        team_critique_receipts=_team_receipts_for(artifact),
    )

    assert receipt["ready_for_next_nine"] is False
    assert "artifact.prior_source_binding" in _failed_criteria(receipt)


def test_one_segment_review_rejects_camera_or_spoken_only_layout_laundering() -> None:
    artifact = _artifact(EXCELLENT_SCRIPT)
    artifact["beat_layout_intents"][0]["source_affordances"] = ["camera:overhead"]
    artifact["beat_layout_intents"][1]["needs"] = ["unsupported_layout_need"]
    artifact["beat_layout_intents"][1]["source_affordances"] = ["spoken_argument_only"]
    _rehash_artifact(artifact)

    receipt = review_one_segment_iteration(
        [artifact],
        team_critique_receipts=_team_receipts_for(artifact),
    )

    assert receipt["ready_for_next_nine"] is False
    assert "layout.no_static_camera_spoken_laundering" in _failed_criteria(receipt)


def test_one_segment_review_replays_hard_layout_contract_for_bounded_vocabulary() -> None:
    for forbidden_posture in ("camera_subject", "spoken_only_fallback"):
        artifact = _artifact(EXCELLENT_SCRIPT)
        artifact["layout_decision_contract"] = {
            **artifact["layout_decision_contract"],
            "bounded_vocabulary": ["segment_primary", forbidden_posture],
        }
        _rehash_artifact(artifact)

        receipt = review_one_segment_iteration(
            [artifact],
            team_critique_receipts=_team_receipts_for(artifact),
        )

        assert receipt["ready_for_next_nine"] is False
        assert "layout.hard_contract_replay" in _failed_criteria(receipt)
