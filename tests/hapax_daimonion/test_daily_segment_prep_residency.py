from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agents.hapax_daimonion import daily_segment_prep as prep


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = json.dumps(payload).encode()

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def test_prep_model_is_command_r_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HAPAX_SEGMENT_PREP_MODEL", raising=False)
    assert prep._prep_model() == prep.RESIDENT_PREP_MODEL

    monkeypatch.setenv("HAPAX_SEGMENT_PREP_MODEL", "not-command-r")
    with pytest.raises(RuntimeError, match="resident Command-R"):
        prep._prep_model()


def test_prep_llm_timeout_preserves_long_resident_generation() -> None:
    assert prep._PREP_LLM_TIMEOUT_S >= 900


def test_parse_script_extracts_spoken_text_from_object_array() -> None:
    raw = json.dumps(
        [
            {"beat_number": 1, "direction": "hook", "draft": "First spoken beat."},
            {"beat_number": 2, "spoken_text": "Second spoken beat."},
            "Third spoken beat.",
        ]
    )

    assert prep._parse_script(raw) == [
        "First spoken beat.",
        "Second spoken beat.",
        "Third spoken beat.",
    ]


def test_parse_script_rejects_stringified_beat_metadata() -> None:
    raw = json.dumps(
        [
            "{'beat': 1, 'direction': 'hook', 'draft': 'We pivot into the source.'}",
            "Actual spoken beat.",
            '{"beat_number": 2, "spoken_text": "More metadata, not speech."}',
        ]
    )

    assert prep._parse_script(raw) == ["Actual spoken beat."]


def test_parse_script_extracts_json_array_from_preamble() -> None:
    raw = 'Here is the rewrite:\n["First repaired beat.", "Second repaired beat."]\nDone.'

    assert prep._parse_script(raw) == ["First repaired beat.", "Second repaired beat."]


def test_parse_script_extracts_array_from_wrapped_object() -> None:
    raw = json.dumps({"prepared_script": ["First repaired beat.", "Second repaired beat."]})

    assert prep._parse_script(raw) == ["First repaired beat.", "Second repaired beat."]


def test_parse_script_extracts_markdown_numbered_blocks() -> None:
    raw = "\n".join(
        [
            "1. First repaired beat has enough words to count as spoken text.",
            "It continues on the next line.",
            "2. Second repaired beat also has enough words to count as speech.",
        ]
    )

    assert prep._parse_script(raw) == [
        "First repaired beat has enough words to count as spoken text. "
        "It continues on the next line.",
        "Second repaired beat also has enough words to count as speech.",
    ]


def test_daily_prep_source_has_no_model_swap_or_fallback_paths() -> None:
    source = Path(prep.__file__).read_text(encoding="utf-8")
    forbidden = [
        "/v1/model/load",
        "/v1/model/unload",
        "_swap_tabby_model",
        "qwen",
        "HAPAX_LITELLM_URL",
        "chat_template_kwargs",
        "enable_thinking",
    ]
    source_lower = source.lower()
    for item in forbidden:
        assert item.lower() not in source_lower


def test_planner_content_state_reads_grounding_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAPAX_SEGMENT_PREP_FOCUS", "Segment quality protocol")
    monkeypatch.setenv(
        "HAPAX_SEGMENT_PREP_TOPIC_CANDIDATES",
        "non-human livestream personage|visible actionability receipts",
    )
    monkeypatch.setenv(
        "HAPAX_SEGMENT_PREP_SOURCE_REFS",
        "axioms/persona/hapax-description-of-being.md|shared/segment_quality_actionability.py",
    )

    state = prep._planner_content_state_from_env()

    assert state is not None
    assert state["focus"] == "Segment quality protocol"
    assert state["topic_candidates"] == [
        "non-human livestream personage",
        "visible actionability receipts",
    ]
    assert "shared/segment_quality_actionability.py" in state["source_refs"]


def test_composition_prompts_render_required_content_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "HAPAX_SEGMENT_PREP_CONTENT_STATE_JSON",
        json.dumps(
            {
                "required_role": "tier_list",
                "source_packets": [
                    {
                        "id": "packet:test-targets",
                        "topic": "Rank prep failure modes",
                        "items": [
                            {
                                "name": "human-host cosplay opener",
                                "target_tier": "S-tier",
                                "why": "it violates the non-human personage contract",
                            }
                        ],
                        "evidence_refs": ["shared/segment_quality_actionability.py"],
                    }
                ],
            }
        ),
    )
    programme = SimpleNamespace(
        programme_id="prog-content-state",
        role=SimpleNamespace(value="tier_list"),
        content=SimpleNamespace(
            narrative_beat="Rank prep failure modes",
            segment_beats=["hook", "item_1: rank human-host cosplay opener"],
            beat_layout_intents=[],
        ),
    )

    full_prompt = prep._build_full_segment_prompt(programme, "seed")
    beat_prompt = prep._build_sequential_beat_prompt(
        programme=programme,
        seed="seed",
        beat_index=1,
        beat_direction="item_1: rank human-host cosplay opener",
        previous_beats=[],
    )

    assert "REQUIRED PREP CONTENT STATE" in full_prompt
    assert "human-host cosplay opener -> S-tier" in full_prompt
    assert "REQUIRED ITEM FOR THIS BEAT" in beat_prompt
    assert "Place human-host cosplay opener in S-tier" in beat_prompt


def test_dehost_personage_script_removes_plural_host_register() -> None:
    cleaned = prep._dehost_personage_script(
        [
            "We must protect our livestream because our audience needs credibility. "
            "Let's discuss the chart with us.",
        ]
    )

    validation = prep.validate_nonhuman_personage(cleaned)

    assert validation["ok"] is True
    assert "We must" not in cleaned[0]
    assert "our livestream" not in cleaned[0]
    assert "credibility" not in cleaned[0]


def test_dehost_personage_script_translates_generic_engagement_language() -> None:
    cleaned = prep._dehost_personage_script(
        [
            "The method'll assign this to A-tier because it can actively involve "
            "viewers. Welcome back. Your input is invaluable in shaping future "
            "segments. The segment should foster a genuine connection and resonate "
            "with the public. This is a meaningful and immersive experience where "
            "the audience actively engage and contribute to a shared experience. "
            "Transparency and honesty make the result grounded and authentic. "
            "The next-nine gate should stay closed. Hapax aims to enhance clarity. "
            "Hapax's segments should strive for visibility. This connects genuinely "
            "with the audience and fosters trust.",
        ]
    )

    text = cleaned[0]
    validation = prep.validate_nonhuman_personage(cleaned)

    assert validation["ok"] is True
    assert "method'll" not in text
    assert "actively involve viewers" not in text
    assert "Your input is invaluable" not in text
    assert "Welcome back" not in text
    assert "foster a genuine connection" not in text
    assert "resonate with the public" not in text
    assert "immersive experience" not in text
    assert "actively engage and contribute" not in text
    assert "shared experience" not in text
    assert "Transparency and honesty" not in text
    assert "authentic" not in text
    assert "next-nine" not in text
    assert "Hapax aims" not in text
    assert "should strive" not in text
    assert "connects genuinely" not in text
    assert "fosters trust" not in text
    assert "pool release" in text


def test_enforce_declared_target_phrases_removes_plural_duplicate_only() -> None:
    state = {
        "source_packets": [
            {
                "id": "packet:targets",
                "items": [{"name": "human-host cosplay opener", "target_tier": "S-tier"}],
            }
        ]
    }
    script = [
        "Place human-host cosplay openers in S-tier. Place unrelated invention in A-tier.",
        "The item beat must hold the exact phrase.",
    ]

    cleaned = prep._enforce_declared_target_phrases(
        script,
        state,
        ["hook: introduce", "item_1: rank human-host cosplay opener"],
    )

    assert "Place human-host cosplay openers in S-tier" not in " ".join(cleaned)
    assert "Place unrelated invention in A-tier" in cleaned[0]
    assert "Place human-host cosplay opener in S-tier" in cleaned[1]


def test_quality_floor_rejects_solid_but_nonideal_scores() -> None:
    report = {
        "rubric_version": prep.QUALITY_RUBRIC_VERSION,
        "label": "solid",
        "overall": 3.58,
        "diagnostics": {"thin_beats": 0},
        "scores": {
            "premise": 3,
            "tension": 4,
            "arc": 3,
            "specificity": 4,
            "pacing": 4,
            "stakes": 3,
            "callbacks": 3,
            "public_pressure": 3,
            "source_fidelity": 3,
            "ending": 3,
            "actionability": 5,
            "layout_responsibility": 5,
        },
    }

    assert prep._quality_floor_rejection_reason(report) == "segment premise below floor"


def test_sequential_opening_prompt_requires_source_bound_premise() -> None:
    programme = SimpleNamespace(
        programme_id="prog-premise",
        role=SimpleNamespace(value="tier_list"),
        content=SimpleNamespace(
            narrative_beat="Rank prep quality failures",
            segment_beats=["hook: open on loadable does not mean fit"],
        ),
    )

    prompt = prep._build_sequential_beat_prompt(
        programme=programme,
        seed="packet:premise-test",
        beat_index=0,
        beat_direction="hook: open on loadable does not mean fit",
        previous_beats=[],
    )

    assert "OPENING PREMISE CONTRACT" in prompt
    assert "first sentence must state the exact claim under pressure" in prompt
    assert "exact packet id, code path, validator, or receipt" in prompt


def test_single_beat_repair_reasons_couple_premise_and_specificity() -> None:
    programme = SimpleNamespace(
        role=SimpleNamespace(value="tier_list"),
        content=SimpleNamespace(segment_beats=["hook: open on a concrete failure"]),
    )

    reasons = prep._single_beat_repair_reasons(
        beat="The segment discusses the method in broad terms. Source check: the source shows the thing.",
        beat_index=0,
        beat_direction="hook: open on a concrete failure",
        programme=programme,
        personage={"ok": True, "violations": []},
    )

    assert any("opening premise is soft" in reason for reason in reasons)
    assert any("specificity is too low" in reason for reason in reasons)


def test_role_visual_hooks_cover_all_segmented_roles() -> None:
    assert set(prep._ROLE_VISUAL_HOOKS) == set(prep._SEGMENTED_CONTENT_ROLES)
    assert "Source check:" in prep._ROLE_VISUAL_HOOKS["lecture"]
    assert "Source check:" in prep._ROLE_VISUAL_HOOKS["interview"]


def test_segment_prep_prompts_do_not_leak_prompt_anchor_topics() -> None:
    programme = SimpleNamespace(
        programme_id="prog-fortran",
        role=SimpleNamespace(value="tier_list"),
        content=SimpleNamespace(
            narrative_beat="Tier list on FORTRAN compiler ergonomics",
            segment_beats=["hook", "item_1: rank compiler diagnostics"],
            beat_layout_intents=[],
        ),
    )
    layout_responsibility = {
        "violations": [{"reason": "missing_tier_placement_phrase", "beat_index": 1}]
    }

    full_prompt = prep._build_full_segment_prompt(programme, "seed")
    repair_prompt = prep._build_layout_repair_prompt(
        ["Opening argument.", "Compiler diagnostics belong in the ranking."],
        programme,
        layout_responsibility,
    )
    planner_prompt = (
        Path(__file__).resolve().parents[2] / "agents/programme_manager/prompts/programme_plan.md"
    ).read_text(encoding="utf-8")

    combined = "\n".join([full_prompt, repair_prompt, planner_prompt]).lower()
    for term in ("popcorn", "sutton", "appalachian", "moonshine"):
        assert term not in combined


def test_segment_prep_prompts_use_nonhuman_personage_protocol() -> None:
    programme = SimpleNamespace(
        programme_id="prog-protocol",
        role=SimpleNamespace(value="lecture"),
        content=SimpleNamespace(
            narrative_beat="Lecture on source-grounded layout responsibility",
            segment_beats=["hook", "evidence"],
            beat_layout_intents=[],
        ),
    )
    layout_responsibility = {"violations": [{"reason": "unsupported_layout_need", "beat_index": 1}]}

    full_prompt = prep._build_full_segment_prompt(programme, "seed")
    repair_prompt = prep._build_layout_repair_prompt(
        ["Source check: the resolved note argues that receipts matter.", "Spoken-only beat."],
        programme,
        layout_responsibility,
    )
    refinement_prompt = prep._build_refinement_prompt(["Spoken beat."], programme)
    planner_prompt = (
        Path(__file__).resolve().parents[2] / "agents/programme_manager/prompts/programme_plan.md"
    ).read_text(encoding="utf-8")

    combined = "\n".join([full_prompt, repair_prompt, refinement_prompt, planner_prompt])
    lower = combined.lower()
    assert "non-human personage contract" in lower
    assert "chat pressure:" in lower
    assert "voice aperture" in lower
    assert "forbidden human-host register" in lower
    assert "required_role" in combined
    assert "by analogy" in lower
    assert "interspecies-style communication" in lower
    for phrase in (
        "for your research livestream",
        "what do you think",
        "late-night monologue",
        "broadcast editor",
        "host would say",
        "you are the showrunner",
        "hapax has positions",
        "thinkers it trusts",
        "finds hollow",
        "no topic hapax cannot ground",
        "why we're ranking",
        "what criteria we're using",
        "hapax's voice aperture",
        "let the audience absorb",
        "operator/audience input",
        "invites chat reactions",
        "invite chat reactions",
        "invite chat dissent",
        "warm-then-deep",
        "found interesting",
    ):
        assert phrase not in lower


def test_full_segment_prompt_renders_planner_layout_obligations() -> None:
    programme = SimpleNamespace(
        programme_id="prog-lecture-layout",
        role=SimpleNamespace(value="lecture"),
        content=SimpleNamespace(
            narrative_beat="Lecture on resident model continuity",
            segment_beats=["hook: explain why residency matters"],
            beat_layout_intents=[
                {
                    "beat_id": "hook",
                    "needs": ["source_visible", "readability_held"],
                    "expected_effects": ["source_context_legible", "detail_readable"],
                    "evidence_refs": ["vault:resident-model-note"],
                    "source_affordances": ["asset:source-card"],
                }
            ],
        ),
    )

    prompt = prep._build_full_segment_prompt(programme, "seed")

    assert "PLANNER LAYOUT OBLIGATIONS" in prompt
    assert "source_visible" in prompt
    assert "readability_held" in prompt
    assert "may not command a layout" in prompt


def test_content_programming_sources_share_resident_command_r_route() -> None:
    checked_paths = [
        Path("agents/programme_manager/planner.py"),
        Path("agents/hapax_daimonion/autonomous_narrative/compose.py"),
        Path("agents/metadata_composer/composer.py"),
    ]
    forbidden_active_paths = [
        "import litellm",
        "litellm.completion",
        "HAPAX_LITELLM",
        "MODELS['local-fast']",
        'MODELS["local-fast"]',
        "MODELS['balanced']",
        'MODELS["balanced"]',
        "openai/{MODELS",
        "chat_template_kwargs",
        "enable_thinking",
        "/v1/model/load",
        "/v1/model/unload",
        "Qwen3.",
    ]

    for path in checked_paths:
        source = path.read_text(encoding="utf-8")
        assert "call_resident_command_r" in source
        for item in forbidden_active_paths:
            assert item not in source

    metadata_source = Path("agents/metadata_composer/composer.py").read_text(encoding="utf-8")
    assert "_call_llm_balanced" not in metadata_source


def test_batch_prep_script_has_no_model_or_service_swap_paths() -> None:
    source = Path("scripts/batch_prep_segments.sh").read_text(encoding="utf-8")
    forbidden = [
        "/v1/model/load",
        "/v1/model/unload",
        "restart_tabby",
        "pkill",
        "fuser",
        "docker pause",
        "systemctl --user stop",
        "qwen",
    ]
    source_lower = source.lower()
    for item in forbidden:
        assert item.lower() not in source_lower
    assert f'RESIDENT_PREP_MODEL="{prep.RESIDENT_PREP_MODEL}"' in source
    assert 'ACCEPTED_LIMIT="${1:-0}"' in source
    assert 'PREP_BUDGET_S="${HAPAX_SEGMENT_PREP_BUDGET_S:-3600}"' in source
    assert "REQUIRE_TARGET" not in source
    assert "=== FAILED:" not in source
    assert "No accepted segments; continuing until budget expires" in source


def test_call_llm_refuses_wrong_resident_model(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(req: Any, timeout: float) -> _FakeResponse:  # noqa: ARG001
        url = getattr(req, "full_url", str(req))
        if url.endswith("/v1/model"):
            return _FakeResponse({"id": "wrong-model"})
        raise AssertionError("chat endpoint should not be called on residency mismatch")

    monkeypatch.delenv("HAPAX_SEGMENT_PREP_MODEL", raising=False)
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match="resident Command-R required"):
        prep._call_llm("hello")


def test_call_llm_uses_resident_command_r_body_and_records_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bodies: list[dict[str, Any]] = []
    chat_timeouts: list[float] = []

    def fake_urlopen(req: Any, timeout: float) -> _FakeResponse:
        url = getattr(req, "full_url", str(req))
        if url.endswith("/v1/model"):
            return _FakeResponse({"id": prep.RESIDENT_PREP_MODEL})
        chat_timeouts.append(timeout)
        bodies.append(json.loads(req.data.decode()))
        return _FakeResponse({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.delenv("HAPAX_SEGMENT_PREP_MODEL", raising=False)
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    status_path = tmp_path / "prep-status.json"
    session = prep._new_prep_session()
    session["prep_status_path"] = str(status_path)
    session["prep_status"] = {"status": "in_progress", "phase": "test"}
    assert (
        prep._call_llm(
            "hello",
            prep_session=session,
            phase="compose",
            programme_id="prog-1",
            max_tokens=77,
        )
        == "ok"
    )

    assert bodies == [
        {
            "model": prep.RESIDENT_PREP_MODEL,
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 77,
            "temperature": 0.7,
        }
    ]
    assert chat_timeouts == [prep._PREP_LLM_TIMEOUT_S]
    assert session["llm_calls"] == [
        {
            "call_index": 1,
            "phase": "compose",
            "programme_id": "prog-1",
            "model_id": prep.RESIDENT_PREP_MODEL,
            "prompt_sha256": prep._sha256_text("hello"),
            "prompt_chars": 5,
            "called_at": session["llm_calls"][0]["called_at"],
        }
    ]
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["current_llm_call"]["status"] == "returned"
    assert status["current_llm_call"]["max_tokens"] == 77
    assert status["current_llm_call"]["timeout_s"] == prep._PREP_LLM_TIMEOUT_S


def _valid_artifact(**overrides: Any) -> dict[str, Any]:
    prompt_sha256 = prep._sha256_text("prompt")
    seed_sha256 = prep._sha256_text("seed")
    segment_beats = ["rank Test item with source, visible test, and public pressure"]
    prepared_script = [
        "Source check: shared.segment_quality_actionability argues that prepared "
        "segments need source fidelity because a polished voice can hide a weak "
        "prior. Place Test item in S-tier because the ranking makes the claim "
        "visible while keeping the runtime readback pending. Visible test: the "
        "tier chart must expose the item, the tier, and the source hash before "
        "the placement counts as more than speech. But the problem is not only "
        "visibility; the stakes are whether Command-R, DailySegmentPrep, and "
        "LayoutState preserve one auditable chain. Remember the opening rule: a "
        "loadable artifact is still suspect until the receipt, source, and "
        "spoken action agree. Chat pressure: should this artifact stay in S-tier "
        "if any receipt disappears? So the beat closes on the same constraint: "
        "the chart can be trusted only while the evidence remains inspectable."
    ]
    actionability = prep.validate_segment_actionability(prepared_script, segment_beats)
    layout = prep.validate_layout_responsibility(actionability["beat_action_intents"])
    personage = prep.validate_nonhuman_personage(prepared_script)
    source_hashes = prep._source_hashes_from_fields(
        programme_id="prog-1",
        role="rant",
        topic="Test topic",
        segment_beats=segment_beats,
        seed_sha256=seed_sha256,
        prompt_sha256=prompt_sha256,
    )
    payload: dict[str, Any] = {
        "schema_version": prep.PREP_ARTIFACT_SCHEMA_VERSION,
        "authority": prep.PREP_ARTIFACT_AUTHORITY,
        "programme_id": "prog-1",
        "role": "rant",
        "topic": "Test topic",
        "segment_beats": segment_beats,
        "prepared_script": prepared_script,
        "segment_quality_rubric_version": prep.QUALITY_RUBRIC_VERSION,
        "actionability_rubric_version": prep.ACTIONABILITY_RUBRIC_VERSION,
        "layout_responsibility_version": prep.LAYOUT_RESPONSIBILITY_VERSION,
        "personage_rubric_version": prep.PERSONAGE_RUBRIC_VERSION,
        "hosting_context": layout["hosting_context"],
        "segment_quality_report": prep.score_segment_quality(prepared_script, segment_beats),
        "personage_alignment": personage,
        "beat_action_intents": actionability["beat_action_intents"],
        "actionability_alignment": {
            "ok": actionability["ok"],
            "removed_unsupported_action_lines": actionability["removed_unsupported_action_lines"],
        },
        "beat_layout_intents": layout["beat_layout_intents"],
        "layout_decision_contract": layout["layout_decision_contract"],
        "runtime_layout_validation": layout["runtime_layout_validation"],
        "layout_decision_receipts": layout["layout_decision_receipts"],
        "prepped_at": "2026-05-05T00:00:00+00:00",
        "prep_session_id": "segment-prep-test",
        "model_id": prep.RESIDENT_PREP_MODEL,
        "prompt_sha256": prompt_sha256,
        "seed_sha256": seed_sha256,
        "prep_content_state_sha256": prep._content_state_sha256(None),
        "prep_content_state": None,
        "source_hashes": source_hashes,
        "source_provenance_sha256": prep._sha256_json(source_hashes),
        "llm_calls": [
            {
                "call_index": 1,
                "phase": "compose",
                "programme_id": "prog-1",
                "model_id": prep.RESIDENT_PREP_MODEL,
                "prompt_sha256": prompt_sha256,
                "prompt_chars": 123,
                "called_at": "2026-05-05T00:00:00+00:00",
            }
        ],
        "beat_count": 1,
        "avg_chars_per_beat": len(prepared_script[0]),
        "refinement_applied": True,
    }
    payload.update(overrides)
    if "prepared_script" in overrides or "segment_beats" in overrides:
        segment_beats = payload["segment_beats"]
        prepared_script = payload["prepared_script"]
        actionability = prep.validate_segment_actionability(prepared_script, segment_beats)
        layout = prep.validate_layout_responsibility(actionability["beat_action_intents"])
        personage = prep.validate_nonhuman_personage(prepared_script)
        source_hashes = prep._source_hashes_from_fields(
            programme_id=str(payload["programme_id"]),
            role=str(payload["role"]),
            topic=str(payload["topic"]),
            segment_beats=segment_beats,
            seed_sha256=str(payload["seed_sha256"]),
            prompt_sha256=str(payload["prompt_sha256"]),
            content_state_sha256=str(payload["prep_content_state_sha256"]),
        )
        payload["segment_quality_report"] = prep.score_segment_quality(
            prepared_script,
            segment_beats,
        )
        payload["personage_alignment"] = personage
        payload["beat_action_intents"] = actionability["beat_action_intents"]
        payload["actionability_alignment"] = {
            "ok": actionability["ok"],
            "removed_unsupported_action_lines": actionability["removed_unsupported_action_lines"],
        }
        payload["beat_layout_intents"] = layout["beat_layout_intents"]
        payload["layout_decision_contract"] = layout["layout_decision_contract"]
        payload["runtime_layout_validation"] = layout["runtime_layout_validation"]
        payload["layout_decision_receipts"] = layout["layout_decision_receipts"]
        payload["source_hashes"] = source_hashes
        payload["source_provenance_sha256"] = prep._sha256_json(source_hashes)
    payload["artifact_sha256"] = prep._artifact_hash(payload)
    return payload


def _valid_artifact_for(
    programme_id: str,
    *,
    topic: str | None = None,
    segment_beats: list[str] | None = None,
    prepared_script: list[str] | None = None,
) -> dict[str, Any]:
    topic = topic or f"Topic for {programme_id}"
    segment_beats = segment_beats or [f"rank {programme_id} with visible source pressure"]
    prepared_script = prepared_script or [
        f"Source check: DailySegmentPrep records that {programme_id} stays loadable "
        "only when the source hash, prompt hash, and runtime layout contract agree. "
        f"Place {programme_id} in S-tier because the ranking makes the claim visible "
        "without claiming layout success before the readback. Visible test: the tier "
        "chart must show the artifact, the S-tier placement, and the pending runtime "
        "status before the segment can be treated as more than speech. But the risk "
        "is that a clean manifest can hide a weak bit, so the stakes stay practical: "
        "Command-R continuity, source fidelity, and LayoutState must remain bound. "
        "Remember the opening receipt because it returns at the close. Chat pressure: "
        "should this artifact drop a tier if any receipt cannot be inspected? So the "
        "final sentence keeps the same rule active: no receipt, no promotion."
    ]
    payload = _valid_artifact(
        programme_id=programme_id,
        topic=topic,
        segment_beats=segment_beats,
        prepared_script=prepared_script,
    )
    actionability = prep.validate_segment_actionability(prepared_script, segment_beats)
    layout = prep.validate_layout_responsibility(actionability["beat_action_intents"])
    personage = prep.validate_nonhuman_personage(prepared_script)
    source_hashes = prep._source_hashes_from_fields(
        programme_id=programme_id,
        role=str(payload["role"]),
        topic=topic,
        segment_beats=segment_beats,
        seed_sha256=str(payload["seed_sha256"]),
        prompt_sha256=str(payload["prompt_sha256"]),
        content_state_sha256=str(payload["prep_content_state_sha256"]),
    )
    payload["beat_action_intents"] = actionability["beat_action_intents"]
    payload["personage_alignment"] = personage
    payload["actionability_alignment"] = {
        "ok": actionability["ok"],
        "removed_unsupported_action_lines": actionability["removed_unsupported_action_lines"],
    }
    payload["beat_layout_intents"] = layout["beat_layout_intents"]
    payload["layout_decision_contract"] = layout["layout_decision_contract"]
    payload["runtime_layout_validation"] = layout["runtime_layout_validation"]
    payload["layout_decision_receipts"] = layout["layout_decision_receipts"]
    payload["prep_content_state_sha256"] = prep._content_state_sha256(None)
    payload["prep_content_state"] = None
    payload["source_hashes"] = source_hashes
    payload["source_provenance_sha256"] = prep._sha256_json(source_hashes)
    payload["llm_calls"][0]["programme_id"] = programme_id
    payload["beat_count"] = len(segment_beats)
    payload["avg_chars_per_beat"] = round(
        sum(len(item) for item in prepared_script) / max(len(prepared_script), 1)
    )
    payload["artifact_sha256"] = prep._artifact_hash(payload)
    return payload


def _write_artifact(base: Path, payload: dict[str, Any], *, manifest: bool = True) -> Path:
    today = prep._today_dir(base)
    path = today / "prog-1.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    if manifest:
        (today / "manifest.json").write_text(
            json.dumps({"programmes": [path.name]}),
            encoding="utf-8",
        )
    return path


def test_load_prepped_programmes_accepts_valid_provenance(tmp_path: Path) -> None:
    _write_artifact(tmp_path, _valid_artifact())

    loaded = prep.load_prepped_programmes(tmp_path)

    assert len(loaded) == 1
    assert loaded[0]["programme_id"] == "prog-1"
    assert loaded[0]["accepted"] is True
    assert loaded[0]["acceptance_gate"] == "daily_segment_prep.load_prepped_programmes"


def test_load_prepped_programmes_rejects_old_actionability_semantics(tmp_path: Path) -> None:
    payload = _valid_artifact()
    payload["actionability_rubric_version"] = prep.ACTIONABILITY_RUBRIC_VERSION - 1
    path = tmp_path / "prog-1.json"

    assert (
        prep._artifact_rejection_reason(
            payload,
            path=path,
            manifest_programmes={path.name},
        )
        == "unsupported actionability rubric"
    )


def test_load_prepped_programmes_rejects_human_host_personage(tmp_path: Path) -> None:
    payload = _valid_artifact_for(
        "prog-human-host",
        prepared_script=[
            "Welcome, everyone. I feel excited to embark on our journey. "
            "Source check: the resolved note argues that receipts matter."
        ],
    )
    _write_artifact(tmp_path, payload)

    assert prep.load_prepped_programmes(tmp_path) == []


def test_load_prepped_programmes_rejects_content_state_target_wrong_beat(
    tmp_path: Path,
) -> None:
    content_state = {
        "source_packets": [
            {
                "id": "packet:wrong-beat",
                "items": [
                    {"name": "Alpha gate", "target_tier": "S-tier"},
                    {"name": "Beta gate", "target_tier": "A-tier"},
                ],
            }
        ]
    }
    payload = _valid_artifact_for(
        "prog-wrong-beat",
        topic="Tier list target fidelity",
        segment_beats=["hook", "item_1: rank Alpha gate", "item_2: rank Beta gate"],
        prepared_script=[
            (
                "Source check: packet:wrong-beat argues that target placement must stay "
                "attached to its declared beat because global presence can hide drift. "
                "Public readback: the receipt must show beat-level placement before "
                "the target counts. But the risk is exact: a later beat can smuggle "
                "the right phrase into the wrong slot."
            ),
            (
                "Source check: packet:wrong-beat shows that Alpha gate is under review, "
                "but this beat withholds the placement phrase. Visible test: the chart "
                "must expose whether item one received its declared slot. Remember the "
                "opening warning because beat-level drift is the defect under test."
            ),
            (
                "Place Alpha gate in S-tier because this phrase appears on the wrong "
                "beat. Place Beta gate in A-tier because the second item remains "
                "visible. Source check: packet:wrong-beat argues that global target "
                "presence is not sufficient. Chat pressure: should the artifact load "
                "when the exact phrase exists only outside the declared beat?"
            ),
        ],
    )
    content_state_sha256 = prep._content_state_sha256(content_state)
    payload["prep_content_state"] = content_state
    payload["prep_content_state_sha256"] = content_state_sha256
    payload["source_hashes"] = prep._source_hashes_from_fields(
        programme_id=str(payload["programme_id"]),
        role=str(payload["role"]),
        topic=str(payload["topic"]),
        segment_beats=list(payload["segment_beats"]),
        seed_sha256=str(payload["seed_sha256"]),
        prompt_sha256=str(payload["prompt_sha256"]),
        content_state_sha256=content_state_sha256,
    )
    payload["source_provenance_sha256"] = prep._sha256_json(payload["source_hashes"])
    payload["artifact_sha256"] = prep._artifact_hash(payload)
    _write_artifact(tmp_path, payload)

    assert prep.load_prepped_programmes(tmp_path) == []


@pytest.mark.parametrize(
    ("payload", "manifest"),
    [
        (_valid_artifact(model_id="wrong-model"), True),
        (_valid_artifact(prep_session_id=""), True),
        (_valid_artifact(llm_calls=[]), True),
        (
            _valid_artifact(
                llm_calls=[
                    {
                        "call_index": 2,
                        "phase": "compose",
                        "programme_id": "prog-1",
                        "model_id": prep.RESIDENT_PREP_MODEL,
                        "prompt_sha256": prep._sha256_text("prompt"),
                        "called_at": "2026-05-05T00:00:00+00:00",
                    },
                    {
                        "call_index": 1,
                        "phase": "refine",
                        "programme_id": "prog-1",
                        "model_id": prep.RESIDENT_PREP_MODEL,
                        "prompt_sha256": prep._sha256_text("refine prompt"),
                        "called_at": "2026-05-05T00:01:00+00:00",
                    },
                ]
            ),
            True,
        ),
        (_valid_artifact(source_hashes={}), True),
        (_valid_artifact(topic="Tampered topic"), True),
        (_valid_artifact(prepared_script=[]), True),
        (_valid_artifact(beat_layout_intents=[]), True),
        (_valid_artifact(layout_name="default"), True),
        (
            _valid_artifact(
                runtime_layout_validation={
                    "status": "complete",
                    "layout_success": True,
                }
            ),
            True,
        ),
        (_valid_artifact(), False),
    ],
)
def test_load_prepped_programmes_rejects_invalid_provenance(
    tmp_path: Path,
    payload: dict[str, Any],
    manifest: bool,
) -> None:
    _write_artifact(tmp_path, payload, manifest=manifest)

    assert prep.load_prepped_programmes(tmp_path) == []


def test_load_prepped_programmes_rejects_layout_responsibility_failure(
    tmp_path: Path,
) -> None:
    payload = _valid_artifact()
    payload["runtime_layout_validation"]["ok"] = False
    payload["runtime_layout_validation"]["violations"] = [
        {"reason": "unsupported_layout_need", "beat_index": 0}
    ]
    payload["artifact_sha256"] = prep._artifact_hash(payload)
    _write_artifact(tmp_path, payload)

    assert prep.load_prepped_programmes(tmp_path) == []


def test_load_prepped_programmes_rejects_hash_mismatch(tmp_path: Path) -> None:
    payload = _valid_artifact()
    payload["prepared_script"] = ["Tampered."]
    _write_artifact(tmp_path, payload)

    assert prep.load_prepped_programmes(tmp_path) == []


def test_load_prepped_programmes_rejects_stale_declared_action_intents(
    tmp_path: Path,
) -> None:
    payload = _valid_artifact()
    payload["beat_action_intents"][0]["intents"].append(
        {
            "kind": "chat_poll",
            "expected_effect": "chat.poll.requested",
            "target": "chat",
            "evidence_ref": "beat:0:intent:chat_poll",
        }
    )
    payload["artifact_sha256"] = prep._artifact_hash(payload)
    _write_artifact(tmp_path, payload)

    assert prep.load_prepped_programmes(tmp_path) == []


def test_run_prep_appends_manifest_without_readmitting_invalid_or_unlisted_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import agents.programme_manager.planner as planner_module

    today = prep._today_dir(tmp_path)
    existing_path = today / "prog-1.json"
    invalid_path = today / "prog-invalid.json"
    unlisted_path = today / "prog-unlisted.json"
    quarantine_path = today / "prog-quarantine.actionability-invalid.json"
    existing_path.write_text(json.dumps(_valid_artifact_for("prog-1")), encoding="utf-8")
    invalid_payload = _valid_artifact_for("prog-invalid")
    invalid_payload["model_id"] = "wrong-model"
    invalid_payload["artifact_sha256"] = prep._artifact_hash(invalid_payload)
    invalid_path.write_text(json.dumps(invalid_payload), encoding="utf-8")
    unlisted_path.write_text(json.dumps(_valid_artifact_for("prog-unlisted")), encoding="utf-8")
    quarantine_path.write_text(
        json.dumps({"not_loadable_reason": "actionability alignment failed"}),
        encoding="utf-8",
    )
    (today / "manifest.json").write_text(
        json.dumps(
            {
                "programmes": [
                    existing_path.name,
                    invalid_path.name,
                    quarantine_path.name,
                ]
            }
        ),
        encoding="utf-8",
    )

    planned_programmes = [
        SimpleNamespace(
            programme_id="prog-2",
            role=SimpleNamespace(value="rant"),
            content=SimpleNamespace(
                narrative_beat="Second accepted topic",
                segment_beats=["Second beat"],
            ),
        ),
        SimpleNamespace(
            programme_id="prog-3",
            role=SimpleNamespace(value="rant"),
            content=SimpleNamespace(
                narrative_beat="Third accepted topic",
                segment_beats=["Third beat"],
            ),
        ),
    ]

    class FakePlanner:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def plan(
            self,
            *,
            show_id: str,  # noqa: ARG002
            candidate_cap: int | None = None,  # noqa: ARG002
            **_kwargs: Any,
        ) -> SimpleNamespace:
            return SimpleNamespace(programmes=planned_programmes)

    def fake_prep_segment(
        programme: SimpleNamespace,
        prep_dir: Path,
        *,
        prep_session: dict[str, Any],
    ) -> Path:
        path = prep_dir / f"{programme.programme_id}.json"
        payload = _valid_artifact_for(
            programme.programme_id,
            topic=programme.content.narrative_beat,
            segment_beats=list(programme.content.segment_beats),
        )
        payload["prep_session_id"] = prep_session["prep_session_id"]
        payload["model_id"] = prep_session["model_id"]
        payload["llm_calls"][0]["model_id"] = prep_session["model_id"]
        payload["artifact_sha256"] = prep._artifact_hash(payload)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    monkeypatch.setattr(prep, "MAX_SEGMENTS", 2)
    monkeypatch.setattr(
        prep,
        "_new_prep_session",
        lambda: {
            "prep_session_id": "segment-prep-new",
            "model_id": prep.RESIDENT_PREP_MODEL,
            "llm_calls": [],
        },
    )
    monkeypatch.setattr(prep, "_assert_resident_prep_model", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(planner_module, "ProgrammePlanner", FakePlanner)
    monkeypatch.setattr(prep, "prep_segment", fake_prep_segment)
    monkeypatch.setattr(prep, "_upsert_programmes_to_qdrant", lambda *_args, **_kwargs: None)

    saved = prep.run_prep(tmp_path)

    assert [path.name for path in saved] == ["prog-2.json", "prog-3.json"]
    manifest = json.loads((today / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["programmes"] == ["prog-1.json", "prog-2.json", "prog-3.json"]
    assert manifest["run_saved_programmes"] == ["prog-2.json", "prog-3.json"]
    assert [item["programme_id"] for item in prep.load_prepped_programmes(tmp_path)] == [
        "prog-1",
        "prog-2",
        "prog-3",
    ]


def test_run_prep_one_segment_writes_status_and_exact_planner_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import agents.programme_manager.planner as planner_module

    captured_candidate_caps: list[int | None] = []

    class FakePlanner:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def plan(
            self,
            *,
            show_id: str,  # noqa: ARG002
            candidate_cap: int | None = None,
            **_kwargs: Any,
        ) -> None:
            captured_candidate_caps.append(candidate_cap)
            return None

    monkeypatch.setattr(prep, "MAX_SEGMENTS", 1)
    monkeypatch.setattr(
        prep,
        "_new_prep_session",
        lambda: {
            "prep_session_id": "segment-prep-canary-status",
            "model_id": prep.RESIDENT_PREP_MODEL,
            "llm_calls": [],
        },
    )
    monkeypatch.setattr(prep, "_assert_resident_prep_model", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(planner_module, "ProgrammePlanner", FakePlanner)
    monkeypatch.setattr(prep, "_upsert_programmes_to_qdrant", lambda *_args, **_kwargs: None)

    saved = prep.run_prep(tmp_path)

    today = prep._today_dir(tmp_path)
    status = json.loads((today / prep.PREP_STATUS_FILENAME).read_text(encoding="utf-8"))
    manifest = json.loads((today / "manifest.json").read_text(encoding="utf-8"))
    assert saved == []
    assert captured_candidate_caps == [1]
    assert status["status"] == "completed_no_programmes"
    assert status["candidate_cap"] == 1
    assert status["accepted_count_is_outcome"] is True
    assert status["quality_budget_s"] == prep.PREP_BUDGET_S
    assert status["max_rounds"] == 1
    assert status["planner_candidate_cap"] == 1
    assert status["phase"] == "completed_no_programmes"
    assert status["manifest_path"].endswith("manifest.json")
    assert manifest["programmes"] == []
    assert manifest["run_saved_programmes"] == []


def test_prep_segment_quarantines_actionability_invalid_script(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    programme = SimpleNamespace(
        programme_id="prog-invalid-action",
        role=SimpleNamespace(value="tier_list"),
        content=SimpleNamespace(
            narrative_beat="Unsupported clip claim",
            segment_beats=["Make the claim without unsupported visuals"],
        ),
    )
    session = {
        "prep_session_id": "segment-prep-test",
        "model_id": prep.RESIDENT_PREP_MODEL,
        "llm_calls": [],
    }

    monkeypatch.setattr(prep, "_build_seed", lambda _programme: "seed")
    monkeypatch.setattr(
        prep,
        "_build_full_segment_prompt",
        lambda _programme, _seed: "prompt",
    )
    monkeypatch.setattr(
        prep,
        "_call_llm",
        lambda _prompt, **_kwargs: json.dumps(
            [
                "Show the clip on screen before ranking the evidence. "
                "The source only supports the narrow provenance claim."
            ]
        ),
    )
    monkeypatch.setattr(prep, "_refine_script", lambda script, _programme, **_kwargs: script)
    monkeypatch.setattr(prep, "_emit_self_evaluation", lambda *_args, **_kwargs: None)

    saved = prep.prep_segment(programme, tmp_path, prep_session=session)

    assert saved is None
    assert not (tmp_path / "prog-invalid-action.json").exists()
    diagnostic_path = tmp_path / "prog-invalid-action.actionability-invalid.json"
    assert diagnostic_path.exists()
    diagnostic = json.loads(diagnostic_path.read_text(encoding="utf-8"))
    assert diagnostic["not_loadable_reason"] == "actionability alignment failed"
    assert diagnostic["actionability_alignment"]["ok"] is False
    assert diagnostic["actionability_alignment"]["removed_unsupported_action_lines"]


def test_prep_segment_quarantines_responsible_spoken_only_script(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    programme = SimpleNamespace(
        programme_id="prog-spoken-only",
        role=SimpleNamespace(value="rant"),
        content=SimpleNamespace(
            narrative_beat="Spoken only argument",
            segment_beats=["argue the point without visible evidence"],
        ),
    )
    session = {
        "prep_session_id": "segment-prep-test",
        "model_id": prep.RESIDENT_PREP_MODEL,
        "llm_calls": [],
    }

    monkeypatch.setattr(prep, "_build_seed", lambda _programme: "seed")
    monkeypatch.setattr(
        prep,
        "_build_full_segment_prompt",
        lambda _programme, _seed: "prompt",
    )
    monkeypatch.setattr(
        prep,
        "_call_llm",
        lambda _prompt, **_kwargs: json.dumps(
            [
                "This beat makes a spoken argument about stream quality. "
                "It states a consequence, names a problem, and stays entirely in narration."
            ]
        ),
    )
    monkeypatch.setattr(prep, "_refine_script", lambda script, _programme, **_kwargs: script)
    monkeypatch.setattr(prep, "_emit_self_evaluation", lambda *_args, **_kwargs: None)

    saved = prep.prep_segment(programme, tmp_path, prep_session=session)

    assert saved is None
    assert not (tmp_path / "prog-spoken-only.json").exists()
    diagnostic_path = tmp_path / "prog-spoken-only.quality-invalid.json"
    assert diagnostic_path.exists()
    diagnostic = json.loads(diagnostic_path.read_text(encoding="utf-8"))
    assert diagnostic["not_loadable_reason"] == "segment quality is generic"
    assert diagnostic["segment_quality_report"]["label"] == "generic"


def test_prep_segment_repairs_spoken_only_tier_list_into_visible_placements(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    programme = SimpleNamespace(
        programme_id="prog-tier-repair",
        role=SimpleNamespace(value="tier_list"),
        content=SimpleNamespace(
            narrative_beat="Tier list on programming languages",
            segment_beats=[
                "hook with a tier rubric",
                "rank the early language",
                "rank the modern language",
            ],
        ),
    )
    session = {
        "prep_session_id": "segment-prep-test",
        "model_id": prep.RESIDENT_PREP_MODEL,
        "llm_calls": [],
    }
    draft = [
        "This beat compares language eras and explains the stakes of abstraction.",
        "FORTRAN and COBOL matter because they changed business computing.",
        "Java matters because object-oriented design reshaped enterprise software.",
    ]
    repaired = [
        "Source check: the programme packet argues that language-era leverage matters "
        "because abstraction changes who can inspect the work. Place the abstraction "
        "rubric in S-tier because the ranking sorts language eras by leverage, not "
        "nostalgia. Visible test: the tier chart must expose the rubric before any "
        "candidate placement can count. But the problem is that a nostalgic ranking "
        "can sound plausible while hiding the operational criterion. Remember this "
        "opening constraint because the later FORTRAN and Java placements depend on "
        "it. Chat pressure: should the rubric fall if it cannot explain both legacy "
        "and visible method? So the first beat closes with a receipt-shaped premise.",
        "Evidence check: the FORTRAN record shows scientific-computing leverage "
        "because high-level notation made machine work legible to research teams. "
        "Place FORTRAN in A-tier because its scientific-computing legacy made high "
        "level programming visible as a practical working method. Visible test: the "
        "chart must compare FORTRAN against the S-tier rubric rather than treat age "
        "as proof. But the pivot is that legacy alone is not enough; the placement "
        "depends on inspectable method. Remember the rubric from the opening beat. "
        "Chat pressure: should FORTRAN climb if source access beats modern ergonomics? "
        "So this placement stays strong without becoming nostalgia.",
        "Source check: the Java enterprise record matters because platform reach "
        "changed deployment practice, but the object model also added weight. Place "
        "Java in B-tier because its enterprise reach is enormous, but the tradeoff is "
        "a heavier object model that chat can dispute. Visible test: the tier chart "
        "must show Java below FORTRAN on leverage while leaving the dispute visible. "
        "Remember the abstraction rubric and the FORTRAN comparison because both "
        "control this closing placement. Chat pressure: should reach outrank method "
        "clarity? So the final beat turns the list into a public comparison rather "
        "than a generic programming-language recap.",
    ]
    prompts: list[str] = []
    phases: list[str] = []

    monkeypatch.setattr(prep, "_build_seed", lambda _programme: "seed")
    monkeypatch.setattr(
        prep,
        "_build_full_segment_prompt",
        lambda _programme, _seed: "prompt",
    )

    def fake_call(prompt: str, **kwargs: Any) -> str:
        prompts.append(prompt)
        phase = kwargs.get("phase")
        phases.append(str(phase))
        call_session = kwargs.get("prep_session")
        if isinstance(call_session, dict):
            call_session["llm_calls"].append(
                {
                    "call_index": len(call_session["llm_calls"]) + 1,
                    "phase": str(phase),
                    "programme_id": str(kwargs.get("programme_id") or "prog-tier-repair"),
                    "model_id": prep.RESIDENT_PREP_MODEL,
                    "prompt_sha256": prep._sha256_text(prompt),
                    "prompt_chars": len(prompt),
                    "called_at": "2026-05-05T00:00:00+00:00",
                }
            )
        if phase == "compose":
            return json.dumps(draft)
        if phase == "layout_repair":
            return json.dumps(repaired)
        if phase == "quality_personage_repair":
            return json.dumps(repaired)
        raise AssertionError(f"unexpected phase {phase!r}")

    monkeypatch.setattr(prep, "_call_llm", fake_call)
    monkeypatch.setattr(prep, "_refine_script", lambda script, _programme, **_kwargs: script)
    monkeypatch.setattr(prep, "_emit_self_evaluation", lambda *_args, **_kwargs: None)

    saved = prep.prep_segment(programme, tmp_path, prep_session=session)

    assert saved == tmp_path / "prog-tier-repair.json"
    payload = json.loads(saved.read_text(encoding="utf-8"))
    assert payload["prepared_script"][0].startswith(repaired[0])
    assert payload["prepared_script"][1:] == repaired[1:]
    assert payload["runtime_layout_validation"]["status"] == "pending_runtime_readback"
    assert payload["runtime_layout_validation"]["layout_success"] is False
    assert payload["beat_layout_intents"]
    assert not payload["layout_decision_receipts"]
    action_kinds = {
        intent["kind"] for beat in payload["beat_action_intents"] for intent in beat["intents"]
    }
    layout_needs = {need for beat in payload["beat_layout_intents"] for need in beat["needs"]}
    assert "tier_chart" in action_kinds
    assert "spoken_argument" not in action_kinds
    assert "tier_visual" in layout_needs
    assert "unsupported_layout_need" not in layout_needs
    assert any("spoken-only beats do not satisfy" in prompt for prompt in prompts)
    assert any("INVALID: 'Let's kick things off by placing" in prompt for prompt in prompts)
    assert any("MANDATORY FAILED-BEAT REPAIRS" in prompt for prompt in prompts)
    assert phases == ["compose", "layout_repair"]
    assert [call["phase"] for call in payload["llm_calls"]] == [
        "compose",
        "layout_repair",
    ]
    load_root = tmp_path / "load"
    today = prep._today_dir(load_root)
    load_path = today / "prog-tier-repair.json"
    load_path.write_text(json.dumps(payload), encoding="utf-8")
    (today / "manifest.json").write_text(
        json.dumps({"programmes": [load_path.name]}),
        encoding="utf-8",
    )
    assert [item["programme_id"] for item in prep.load_prepped_programmes(load_root)] == [
        "prog-tier-repair"
    ]


def test_prep_segment_repairs_spoken_only_lecture_into_source_checks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    programme = SimpleNamespace(
        programme_id="prog-lecture-repair",
        role=SimpleNamespace(value="lecture"),
        content=SimpleNamespace(
            narrative_beat="Lecture on resident model continuity",
            segment_beats=[
                "hook: explain the continuity problem",
                "evidence: cite the prep contract",
                "definition: define residency",
            ],
            beat_layout_intents=[
                {
                    "beat_id": "hook",
                    "needs": ["source_visible"],
                    "expected_effects": ["source_context_legible"],
                    "evidence_refs": ["vault:resident-model-note"],
                    "source_affordances": ["asset:source-card"],
                }
            ],
        ),
    )
    session = {
        "prep_session_id": "segment-prep-test",
        "model_id": prep.RESIDENT_PREP_MODEL,
        "llm_calls": [],
    }
    draft = [
        "This beat explains why continuity matters for the method.",
        "The prep contract matters because it keeps the generator coherent.",
        "Residency means keeping the same model active for the work.",
    ]
    repaired = [
        "Source check: the resident model note argues that continuity matters because "
        "sequential calls accumulate a stable local context. This opening frames the "
        "lecture around a concrete operational constraint rather than a generic claim. "
        "Visible test: the source card must hold the residency note while the spoken "
        "claim names Command-R, DailySegmentPrep, and the prep contract. But the "
        "problem is not model branding; the stakes are whether one generator carries "
        "the same source pressure from plan to repair. Remember this continuity rule "
        "because the next beats test it against the contract and the definition. Chat "
        "pressure: should a prepared artifact lose trust if the resident model changes "
        "mid-chain? So the first beat leaves a checkable premise on screen.",
        "Evidence check: the prep contract shows that plan, compose, refine, and repair "
        "all use resident Command-R before any artifact can load. That evidence matters "
        "because the public should see the method as a chain, not a slogan. Visible "
        "test: the contract receipt must show the phase list and the model id before "
        "the segment claims continuity. But the pivot is stricter than a normal source "
        "citation: a single missing phase breaks the proof. Remember the opening rule "
        "about local context, because this beat turns it into a manifest obligation. "
        "Chat pressure: should refinement count if the compose receipt is absent? So "
        "the contract becomes a visible gate instead of a decorative citation.",
        "Definition check: residency means the same local grounded generator remains "
        "served across the prep sequence. The definition matters because unloading the "
        "model breaks the continuity this lecture is testing. Worked example: plan, "
        "compose, refine, repair, and load form one chain only if Command-R stays "
        "resident and the prompt hashes remain inspectable. But the closing consequence "
        "is practical: a loadable artifact can still fail if the source chain cannot "
        "be replayed. Remember the first source card and the contract receipt together. "
        "Chat pressure: should the load gate reject any segment without this chain? So "
        "the lecture lands on an operational definition, not a motivational slogan.",
    ]
    prompts: list[str] = []
    phases: list[str] = []

    monkeypatch.setattr(prep, "_build_seed", lambda _programme: "seed")
    monkeypatch.setattr(
        prep,
        "_build_full_segment_prompt",
        lambda _programme, _seed: "prompt",
    )

    def fake_call(prompt: str, **kwargs: Any) -> str:
        prompts.append(prompt)
        phase = kwargs.get("phase")
        phases.append(str(phase))
        call_session = kwargs.get("prep_session")
        if isinstance(call_session, dict):
            call_session["llm_calls"].append(
                {
                    "call_index": len(call_session["llm_calls"]) + 1,
                    "phase": str(phase),
                    "programme_id": "prog-lecture-repair",
                    "model_id": prep.RESIDENT_PREP_MODEL,
                    "prompt_sha256": prep._sha256_text(prompt),
                    "prompt_chars": len(prompt),
                    "called_at": "2026-05-05T00:00:00+00:00",
                }
            )
        if phase == "compose":
            return json.dumps(draft)
        if phase == "layout_repair":
            return json.dumps(repaired)
        if phase == "quality_personage_repair":
            return json.dumps(repaired)
        raise AssertionError(f"unexpected phase {phase!r}")

    monkeypatch.setattr(prep, "_call_llm", fake_call)
    monkeypatch.setattr(prep, "_refine_script", lambda script, _programme, **_kwargs: script)
    monkeypatch.setattr(prep, "_emit_self_evaluation", lambda *_args, **_kwargs: None)

    saved = prep.prep_segment(programme, tmp_path, prep_session=session)

    assert saved == tmp_path / "prog-lecture-repair.json"
    payload = json.loads(saved.read_text(encoding="utf-8"))
    action_kinds = {
        intent["kind"] for beat in payload["beat_action_intents"] for intent in beat["intents"]
    }
    layout_needs = {need for beat in payload["beat_layout_intents"] for need in beat["needs"]}
    assert {"source_check", "evidence_check", "definition_check"}.issubset(action_kinds)
    assert {"source_visible", "evidence_visible", "readability_held"}.issubset(layout_needs)
    assert "unsupported_layout_need" not in layout_needs
    assert all(call["model_id"] == prep.RESIDENT_PREP_MODEL for call in payload["llm_calls"])
    assert any("Source check:" in prompt for prompt in prompts)
    assert phases == ["compose", "layout_repair"]


def test_prep_segment_rejects_tier_list_repair_without_exact_placements(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    programme = SimpleNamespace(
        programme_id="prog-tier-generic-repair",
        role=SimpleNamespace(value="tier_list"),
        content=SimpleNamespace(
            narrative_beat="Tier list on programming languages",
            segment_beats=[
                "hook with a tier rubric",
                "item_1: rank the early language",
                "item_2: rank the modern language",
            ],
        ),
    )
    session = {
        "prep_session_id": "segment-prep-test",
        "model_id": prep.RESIDENT_PREP_MODEL,
        "llm_calls": [],
    }
    draft = [
        "This beat compares language eras and explains the stakes of abstraction.",
        "FORTRAN and COBOL matter because they changed business computing.",
        "Java matters because object-oriented design reshaped enterprise software.",
    ]
    repaired = [
        "This tier list ranks language eras by leverage, not nostalgia.",
        "FORTRAN belongs in A-tier because its scientific-computing legacy made "
        "high level programming visible as a practical working method.",
        "Java belongs in B-tier because its enterprise reach is enormous, but the "
        "tradeoff is a heavier object model that chat can dispute.",
    ]

    monkeypatch.setattr(prep, "_build_seed", lambda _programme: "seed")
    monkeypatch.setattr(
        prep,
        "_build_full_segment_prompt",
        lambda _programme, _seed: "prompt",
    )

    def fake_call(_prompt: str, **kwargs: Any) -> str:
        phase = kwargs.get("phase")
        if phase == "compose":
            return json.dumps(draft)
        if phase == "layout_repair":
            return json.dumps(repaired)
        raise AssertionError(f"unexpected phase {phase!r}")

    monkeypatch.setattr(prep, "_call_llm", fake_call)
    monkeypatch.setattr(prep, "_refine_script", lambda script, _programme, **_kwargs: script)
    monkeypatch.setattr(prep, "_emit_self_evaluation", lambda *_args, **_kwargs: None)

    saved = prep.prep_segment(programme, tmp_path, prep_session=session)

    assert saved is None
    diagnostic_path = tmp_path / "prog-tier-generic-repair.quality-invalid.json"
    diagnostic = json.loads(diagnostic_path.read_text(encoding="utf-8"))
    assert diagnostic["not_loadable_reason"] == "segment quality overall below floor"
    assert "missing_tier_placement_phrase" in {
        item["reason"] for item in diagnostic["layout_responsibility"]["violations"]
    }


def test_load_prepped_programmes_rejects_tier_list_without_exact_placements(
    tmp_path: Path,
) -> None:
    payload = _valid_artifact_for(
        "prog-tier-generic",
        topic="Tier list with generic ranking language",
        segment_beats=[
            "hook with a tier rubric",
            "item_1: rank the early language against the rubric",
            "item_2: rank the modern language",
        ],
        prepared_script=[
            "This tier list ranks language eras by leverage, not nostalgia.",
            "FORTRAN belongs in A-tier because its scientific-computing legacy matters.",
            "Java belongs in B-tier because its enterprise reach is enormous.",
        ],
    )
    payload["role"] = "tier_list"
    payload["source_hashes"] = prep._source_hashes_from_fields(
        programme_id="prog-tier-generic",
        role="tier_list",
        topic=str(payload["topic"]),
        segment_beats=list(payload["segment_beats"]),
        seed_sha256=str(payload["seed_sha256"]),
        prompt_sha256=str(payload["prompt_sha256"]),
    )
    payload["prep_content_state_sha256"] = prep._content_state_sha256(None)
    payload["prep_content_state"] = None
    payload["source_provenance_sha256"] = prep._sha256_json(payload["source_hashes"])
    payload["artifact_sha256"] = prep._artifact_hash(payload)
    _write_artifact(tmp_path, payload)

    assert prep.load_prepped_programmes(tmp_path) == []


def test_load_prepped_programmes_rejects_final_candidate_without_exact_placement(
    tmp_path: Path,
) -> None:
    payload = _valid_artifact_for(
        "prog-tier-final-candidate",
        topic="Tier list with a final candidate beat",
        segment_beats=[
            "criteria intro",
            "second candidate: FORTRAN",
            "third candidate: Java",
        ],
        prepared_script=[
            "This opening names the rubric and the stakes for the tier list.",
            "Place FORTRAN in A-tier because the legacy is visible in the ranking.",
            "Java belongs in B-tier because the enterprise tradeoff is real.",
        ],
    )
    payload["role"] = "tier_list"
    payload["source_hashes"] = prep._source_hashes_from_fields(
        programme_id="prog-tier-final-candidate",
        role="tier_list",
        topic=str(payload["topic"]),
        segment_beats=list(payload["segment_beats"]),
        seed_sha256=str(payload["seed_sha256"]),
        prompt_sha256=str(payload["prompt_sha256"]),
    )
    payload["prep_content_state_sha256"] = prep._content_state_sha256(None)
    payload["prep_content_state"] = None
    payload["source_provenance_sha256"] = prep._sha256_json(payload["source_hashes"])
    payload["artifact_sha256"] = prep._artifact_hash(payload)
    today = prep._today_dir(tmp_path)
    path = today / "prog-tier-final-candidate.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    (today / "manifest.json").write_text(
        json.dumps({"programmes": [path.name]}),
        encoding="utf-8",
    )

    assert prep.load_prepped_programmes(tmp_path) == []


def test_prep_segment_rejects_unsafe_programme_id_before_writing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    programme = SimpleNamespace(
        programme_id="../escape",
        role=SimpleNamespace(value="tier_list"),
        content=SimpleNamespace(
            narrative_beat="Unsafe path",
            segment_beats=["This should not be composed"],
        ),
    )
    called = False

    def fail_if_called(*_args: Any, **_kwargs: Any) -> str:
        nonlocal called
        called = True
        return "[]"

    monkeypatch.setattr(prep, "_call_llm", fail_if_called)

    saved = prep.prep_segment(
        programme,
        tmp_path,
        prep_session={
            "prep_session_id": "segment-prep-test",
            "model_id": prep.RESIDENT_PREP_MODEL,
            "llm_calls": [],
        },
    )

    assert saved is None
    assert called is False
    assert not (tmp_path.parent / "escape.json").exists()


def test_load_prepped_programmes_rejects_programme_id_filename_mismatch(
    tmp_path: Path,
) -> None:
    payload = _valid_artifact_for("prog-safe")
    path = _write_artifact(tmp_path, payload)
    mismatch_path = path.with_name("prog-other.json")
    path.rename(mismatch_path)
    (path.parent / "manifest.json").write_text(
        json.dumps({"programmes": [mismatch_path.name]}),
        encoding="utf-8",
    )

    assert prep.load_prepped_programmes(tmp_path) == []


def test_qdrant_upsert_indexes_only_valid_saved_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import shared.affordance_pipeline as affordance_pipeline
    import shared.config as shared_config

    today = prep._today_dir(tmp_path)
    valid_path = today / "prog-1.json"
    invalid_path = today / "prog-2.json"
    valid_path.write_text(json.dumps(_valid_artifact(programme_id="prog-1")), encoding="utf-8")
    invalid_path.write_text(
        json.dumps(_valid_artifact(programme_id="prog-2", model_id="wrong-model")),
        encoding="utf-8",
    )
    (today / "manifest.json").write_text(
        json.dumps({"programmes": [valid_path.name, invalid_path.name]}),
        encoding="utf-8",
    )

    captured: dict[str, Any] = {}

    def fake_embed_batch(texts: list[str], *, prefix: str) -> list[list[float]]:
        captured["texts"] = texts
        captured["prefix"] = prefix
        return [[0.1, 0.2] for _ in texts]

    class FakeQdrant:
        def upsert(self, *, collection_name: str, points: list[Any]) -> None:
            captured["collection_name"] = collection_name
            captured["points"] = points

    monkeypatch.setattr(affordance_pipeline, "embed_batch_safe", fake_embed_batch)
    monkeypatch.setattr(shared_config, "get_qdrant", lambda: FakeQdrant())

    programmes = [
        SimpleNamespace(
            programme_id="prog-1",
            role=SimpleNamespace(value="rant"),
            content=SimpleNamespace(narrative_beat="Test topic", segment_beats=["Beat one"]),
        ),
        SimpleNamespace(
            programme_id="prog-2",
            role=SimpleNamespace(value="rant"),
            content=SimpleNamespace(narrative_beat="Bad topic", segment_beats=["Beat two"]),
        ),
    ]

    prep._upsert_programmes_to_qdrant(programmes, [valid_path, invalid_path])

    points = captured["points"]
    assert len(points) == 1
    payload = points[0].payload
    assert payload["programme_id"] == "prog-1"
    assert payload["accepted"] is True
    assert payload["authority"] == prep.PREP_ARTIFACT_AUTHORITY
    assert payload["artifact_path"] == str(valid_path)
    assert payload["source_provenance_sha256"]
    assert payload["hosting_context"] == prep.RESPONSIBLE_HOSTING_CONTEXT
    assert payload["beat_layout_intents"]
