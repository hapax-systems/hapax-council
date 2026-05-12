from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agents.hapax_daimonion import daily_segment_prep as prep

SOURCE_REF = "vault:test-segment-source"


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = json.dumps(payload).encode()

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def _ready_content(
    *,
    narrative_beat: str,
    segment_beats: list[str],
    role: str = "rant",
) -> SimpleNamespace:
    role_contract: dict[str, Any] = {
        "source_packet_refs": [SOURCE_REF],
        "role_live_bit_mechanic": "source evidence changes a visible segment object",
        "event_object": "source-backed public comparison object",
        "audience_job": "inspect the source-backed consequence",
        "payoff": "the final beat resolves the source consequence",
        "temporality_band": "evergreen",
    }
    if role in {"tier_list", "top_10"}:
        role_contract["tier_criteria"] = "source-backed criterion for each placement"
    if role == "rant":
        role_contract["bounded_claim"] = "source evidence constrains the claim"
        role_contract["receipt_flip"] = "receipt changes confidence or scope"
    return SimpleNamespace(
        narrative_beat=narrative_beat,
        segment_beats=segment_beats,
        role_contract=role_contract,
        beat_layout_intents=[
            {
                "beat_id": f"beat-{index + 1}",
                "evidence_refs": [SOURCE_REF],
                "needs": ["source_visible"],
                "default_static_success_allowed": False,
            }
            for index, _beat in enumerate(segment_beats)
        ],
    )


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


def test_parse_segment_generation_extracts_embedded_json_object() -> None:
    raw = "Here is the segment JSON:\n" + json.dumps(
        {
            "prepared_script": ["First spoken beat.", "Second spoken beat."],
            "segment_prep_contract": {
                "claim_map": [{"claim_id": "claim:first", "claim_text": "First"}]
            },
        }
    )

    script, contract = prep._parse_segment_generation(raw)

    assert script == ["First spoken beat.", "Second spoken beat."]
    assert contract == {"claim_map": [{"claim_id": "claim:first", "claim_text": "First"}]}


def test_tier_list_placement_repair_names_quoted_target() -> None:
    repaired = prep._repair_tier_list_placement_phrases(
        [
            "The 'Rollback Failure' case lacks a recovery path. "
            "This failure is placed in S-tier by the audit criteria.",
            "The 'Consensus Gap' packet has fragmented evidence. "
            "We place this failure in B-tier after the provenance check.",
        ]
    )

    assert repaired[0].endswith(
        "Place Rollback Failure in S-tier under the stated source criteria."
    )
    assert repaired[1].endswith("Place Consensus Gap in B-tier under the stated source criteria.")


def test_tier_list_placement_repair_reuses_prior_named_placements() -> None:
    repaired = prep._repair_tier_list_placement_phrases(
        [
            "Waterfall is rigid under the source criteria. Place Waterfall in C-tier.",
            "Agile adapts better under the source criteria. Place Agile in S-tier.",
            "The comparison between Agile and Waterfall is the point of the segment.",
        ]
    )

    assert "Place Waterfall in C-tier under the stated source criteria." in repaired[2]
    assert "Place Agile in S-tier under the stated source criteria." in repaired[2]


def test_source_visible_repair_uses_beat_evidence_ref_for_spoken_only_beat() -> None:
    repaired = prep._repair_source_visible_beats(
        ["The launch decision needs a mechanical receipt before the public claim."],
        ["explain the launch gate using vault:hn-readiness-tree.md"],
    )

    assert repaired == [
        "The launch decision needs a mechanical receipt before the public claim. "
        "According to HN Readiness Tree, this source changes the visible obligation."
    ]
    actionability = prep.validate_segment_actionability(repaired, ["repair"])
    layout = prep.validate_layout_responsibility(actionability["beat_action_intents"])
    assert layout["ok"] is True


def test_source_visible_repair_does_not_duplicate_existing_trigger() -> None:
    script = ["According to the HN readiness tree, the receipt blocks launch."]

    assert (
        prep._repair_source_visible_beats(
            script,
            ["explain the launch gate using vault:hn-readiness-tree.md"],
        )
        == script
    )


def test_live_event_payoff_repair_makes_final_resolution_explicit() -> None:
    repaired = prep._repair_live_event_payoff(
        ["The source comparison changes the public claim but stops without a payoff."]
    )

    assert "Therefore the final decision" in repaired[0]


def test_comparison_repair_uses_source_planned_comparison_direction() -> None:
    repaired = prep._repair_comparison_beats(
        ["The source changes the lecture object."],
        [
            "work through agent_governance_model_application from "
            "vault:agent-governance-principles.md and compare it against "
            "agent_governance_model_example"
        ],
    )

    assert "Compare it against agent_governance_model_example" in repaired[0]
    actionability = prep.validate_segment_actionability(repaired, ["repair"])
    assert {
        intent["kind"]
        for declaration in actionability["beat_action_intents"]
        for intent in declaration["intents"]
    } >= {"comparison"}


def test_segment_prep_contract_canonicalizes_model_alias_fields() -> None:
    beats = [
        "open the proof using vault:test-segment-source",
        "compare the claim against vault:test-segment-source",
    ]
    script = [
        "According to the test source, now compare the launch claim against the visible "
        "receipt because the source changes confidence.",
        "Then compare the narrowed claim with the original claim, according to the test "
        "source. Therefore the final decision returns to the opening receipt.",
    ]
    actionability = prep.validate_segment_actionability(script, beats)
    layout = prep.validate_layout_responsibility(actionability["beat_action_intents"])
    model_contract = {
        "source_packet_refs": [
            {
                "id": "packet:test-source",
                "source_ref": SOURCE_REF,
                "evidence_refs": [SOURCE_REF],
            }
        ],
        "claim_map": [
            {"claim": "the receipt changes launch confidence", "evidence_ref": SOURCE_REF},
            {
                "claim": "the narrowed claim must resolve the opening receipt",
                "evidence_ref": SOURCE_REF,
            },
        ],
        "source_consequence_map": [
            {"source_ref": SOURCE_REF, "consequence": "launch confidence changes"},
            {"source_ref": SOURCE_REF, "consequence": "the final scope narrows"},
        ],
        "actionability_map": [
            {"beat_index": 0, "action": "comparison", "target": "launch receipt"},
            {"beat_index": 1, "action": "comparison", "target": "narrowed claim"},
        ],
        "layout_need_map": [
            {"beat_index": 0, "need": "source_visible", "evidence_ref": SOURCE_REF},
            {"beat_index": 1, "need": "source_visible", "evidence_ref": SOURCE_REF},
        ],
        "readback_obligations": [],
        "loop_cards": [],
        "role_excellence_plan": {
            "live_event_plan": {
                "bit_engine": "source-backed comparison",
                "audience_job": "inspect the receipt",
                "payoff": "resolve whether the receipt supports launch",
            }
        },
    }

    contract = prep.build_segment_prep_contract(
        programme_id="prog-contract-alias",
        role="lecture",
        topic="Contract aliases",
        segment_beats=beats,
        script=script,
        actionability=actionability,
        layout_responsibility=layout,
        source_refs=[SOURCE_REF],
        model_contract=model_contract,
    )
    report = prep.validate_segment_prep_contract(
        contract,
        prepared_script=script,
        segment_beats=beats,
    )

    assert report == {"ok": True, "violations": []}
    assert contract["contract_generation"]["model_emitted"] is True
    assert contract["contract_generation"]["deterministic_backfilled_fields"] == []
    assert "claim_map" in contract["contract_generation"]["canonicalized_fields"]
    assert "readback_obligations" in contract["contract_generation"]["derived_fields"]
    assert "loop_cards" in contract["contract_generation"]["derived_fields"]
    assert contract["claim_map"][0]["claim_id"].startswith("claim:prog-contract-alias:")
    assert contract["claim_map"][0]["grounds"] == [SOURCE_REF]
    assert contract["layout_need_map"][0]["source_packet_refs"] == [SOURCE_REF]
    assert contract["loop_cards"][0]["evidence_refs"] == [SOURCE_REF]


def test_hermeneutic_deltas_are_json_mode_before_artifact_hashing() -> None:
    from datetime import UTC, datetime

    from shared.hermeneutic_spiral import HermeneuticDelta

    delta = HermeneuticDelta(
        delta_id="delta:test",
        programme_id="prog-json",
        role="lecture",
        topic="JSON mode",
        cycle_timestamp=datetime.now(tz=UTC),
        delta_kind="new_consequence",
        source_ref=SOURCE_REF,
        consequence_kind="claim_shape_changed",
        summary="source changes the claim shape",
    )

    payload = {"hermeneutic_deltas": [delta.model_dump(mode="json")]}

    assert prep._artifact_hash(payload)


def test_refine_script_returns_final_model_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    refined = ["Place the final claim in A-tier because the cited source changes the consequence."]
    contract = {"claim_map": [{"claim_id": "claim:final", "claim_text": refined[0]}]}
    monkeypatch.setattr(
        prep,
        "_call_llm",
        lambda *_args, **_kwargs: json.dumps(
            {"prepared_script": refined, "segment_prep_contract": contract}
        ),
    )

    script, model_contract, changed = prep._refine_script(
        ["Draft claim."],
        SimpleNamespace(
            role=SimpleNamespace(value="tier_list"),
            content=SimpleNamespace(
                narrative_beat="Contract refresh",
                segment_beats=["rank final claim"],
            ),
        ),
    )

    assert script == refined
    assert model_contract == contract
    assert changed is True


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


def test_call_llm_refuses_wrong_resident_model(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(req: Any, timeout: float) -> _FakeResponse:  # noqa: ARG001
        url = getattr(req, "full_url", str(req))
        if url.endswith("/v1/model"):
            return _FakeResponse({"id": "wrong-model"})
        raise AssertionError("chat endpoint should not be called on residency mismatch")

    monkeypatch.delenv("HAPAX_SEGMENT_PREP_MODEL", raising=False)
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(
        prep,
        "assert_segment_prep_allowed",
        lambda _activity: SimpleNamespace(mode="open", reason="test", source="test"),
    )

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
    monkeypatch.setattr(
        prep,
        "assert_segment_prep_allowed",
        lambda _activity: SimpleNamespace(mode="open", reason="test", source="test"),
    )

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


def test_call_llm_checks_live_authority_on_every_call(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(req: Any, timeout: float) -> _FakeResponse:  # noqa: ARG001
        url = getattr(req, "full_url", str(req))
        if url.endswith("/v1/model"):
            return _FakeResponse({"id": prep.RESIDENT_PREP_MODEL})
        return _FakeResponse({"choices": [{"message": {"content": "ok"}}]})

    checked: list[str] = []

    def fake_authority(activity: str) -> SimpleNamespace:
        checked.append(activity)
        return SimpleNamespace(mode="open", reason="test", source="test")

    monkeypatch.delenv("HAPAX_SEGMENT_PREP_MODEL", raising=False)
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(prep, "assert_segment_prep_allowed", fake_authority)

    session = prep._new_prep_session()
    session["authority_gate_passed"] = True

    assert prep._call_llm("one", prep_session=session) == "ok"
    assert prep._call_llm("two", prep_session=session) == "ok"
    assert checked == ["pool_generation", "pool_generation"]


def _valid_artifact(**overrides: Any) -> dict[str, Any]:
    prompt_sha256 = prep._sha256_text("prompt")
    seed_sha256 = prep._sha256_text("seed")
    segment_beats = ["Beat one"]
    prepared_script = [
        "Place Test item in S-tier because Zuboff argues measurement needs visible proof, "
        "which means the ranking makes the claim visible."
    ]
    actionability = prep.validate_segment_actionability(prepared_script, segment_beats)
    layout = prep.validate_layout_responsibility(actionability["beat_action_intents"])
    source_consequence_map = prep.build_source_consequence_map(
        prepared_script,
        actionability["beat_action_intents"],
    )
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
        "hosting_context": layout["hosting_context"],
        "segment_quality_report": prep.score_segment_quality(prepared_script, segment_beats),
        "consultation_manifest": prep.build_consultation_manifest("rant"),
        "source_consequence_map": source_consequence_map,
        "live_event_viability": prep.build_live_event_viability(
            prepared_script,
            actionability=actionability,
            layout=layout,
            role="rant",
        ),
        "readback_obligations": prep.build_readback_obligations(layout["beat_layout_intents"]),
        "beat_action_intents": actionability["beat_action_intents"],
        "actionability_alignment": {
            "ok": actionability["ok"],
            "removed_unsupported_action_lines": actionability["removed_unsupported_action_lines"],
            "personage_violations": actionability["personage_violations"],
            "detector_theater_lines": actionability["detector_theater_lines"],
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
    segment_beats = segment_beats or ["Beat one"]
    prepared_script = prepared_script or [
        f"Place {programme_id} in S-tier because Zuboff argues measurement needs visible proof, "
        "which means the ranking makes the claim visible."
    ]
    payload = _valid_artifact(
        programme_id=programme_id,
        topic=topic,
        segment_beats=segment_beats,
        prepared_script=prepared_script,
    )
    actionability = prep.validate_segment_actionability(prepared_script, segment_beats)
    layout = prep.validate_layout_responsibility(actionability["beat_action_intents"])
    source_consequence_map = prep.build_source_consequence_map(
        prepared_script,
        actionability["beat_action_intents"],
    )
    source_hashes = prep._source_hashes_from_fields(
        programme_id=programme_id,
        role=str(payload["role"]),
        topic=topic,
        segment_beats=segment_beats,
        seed_sha256=str(payload["seed_sha256"]),
        prompt_sha256=str(payload["prompt_sha256"]),
    )
    payload["beat_action_intents"] = actionability["beat_action_intents"]
    payload["actionability_alignment"] = {
        "ok": actionability["ok"],
        "removed_unsupported_action_lines": actionability["removed_unsupported_action_lines"],
        "personage_violations": actionability["personage_violations"],
        "detector_theater_lines": actionability["detector_theater_lines"],
    }
    payload["consultation_manifest"] = prep.build_consultation_manifest(str(payload["role"]))
    payload["source_consequence_map"] = source_consequence_map
    payload["live_event_viability"] = prep.build_live_event_viability(
        prepared_script,
        actionability=actionability,
        layout=layout,
        role=str(payload["role"]),
    )
    payload["readback_obligations"] = prep.build_readback_obligations(layout["beat_layout_intents"])
    payload["beat_layout_intents"] = layout["beat_layout_intents"]
    payload["layout_decision_contract"] = layout["layout_decision_contract"]
    payload["runtime_layout_validation"] = layout["runtime_layout_validation"]
    payload["layout_decision_receipts"] = layout["layout_decision_receipts"]
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

    loaded = prep.load_prepped_programmes(tmp_path, require_selected=False)

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

    assert prep.load_prepped_programmes(tmp_path, require_selected=False) == []


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

    assert prep.load_prepped_programmes(tmp_path, require_selected=False) == []


def test_load_prepped_programmes_rejects_hash_mismatch(tmp_path: Path) -> None:
    payload = _valid_artifact()
    payload["prepared_script"] = ["Tampered."]
    _write_artifact(tmp_path, payload)

    assert prep.load_prepped_programmes(tmp_path, require_selected=False) == []


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

    assert prep.load_prepped_programmes(tmp_path, require_selected=False) == []


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
            target_programmes: int | None = None,  # noqa: ARG002
            **_kw: Any,
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
    monkeypatch.setattr(
        prep,
        "assert_segment_prep_allowed",
        lambda _activity: SimpleNamespace(mode="open", reason="test", source="test"),
    )
    monkeypatch.setattr(
        prep,
        "assert_next_nine_canary_ready",
        lambda: {
            "ok": True,
            "path": str(tmp_path / "canary-review.json"),
            "receipt": {
                "programme_id": "prog-canary",
                "artifact_sha256": "a" * 64,
                "iteration_id": "segment-prep-canary-test",
            },
        },
    )
    monkeypatch.setattr(planner_module, "ProgrammePlanner", FakePlanner)
    monkeypatch.setattr(prep, "prep_segment", fake_prep_segment)
    saved = prep.run_prep(tmp_path)

    assert [path.name for path in saved] == ["prog-2.json", "prog-3.json"]
    manifest = json.loads((today / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["programmes"] == ["prog-1.json", "prog-2.json", "prog-3.json"]
    assert manifest["run_saved_programmes"] == ["prog-2.json", "prog-3.json"]
    assert [
        item["programme_id"]
        for item in prep.load_prepped_programmes(tmp_path, require_selected=False)
    ] == [
        "prog-1",
        "prog-2",
        "prog-3",
    ]


def test_run_prep_pool_generation_requires_passing_canary_before_model_check(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(prep, "MAX_SEGMENTS", 2)
    monkeypatch.setattr(
        prep,
        "_new_prep_session",
        lambda: {
            "prep_session_id": "segment-prep-needs-canary",
            "model_id": prep.RESIDENT_PREP_MODEL,
            "llm_calls": [],
        },
    )
    monkeypatch.setattr(
        prep,
        "assert_segment_prep_allowed",
        lambda _activity: SimpleNamespace(mode="pool_generation_allowed", reason="test"),
    )

    def missing_canary() -> None:
        raise prep.SegmentCanaryGateError("missing canary review receipt")

    monkeypatch.setattr(prep, "assert_next_nine_canary_ready", missing_canary)
    monkeypatch.setattr(
        prep,
        "_assert_resident_prep_model",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("model must not be probed before canary gate")
        ),
    )

    saved = prep.run_prep(tmp_path)

    status = json.loads(
        (prep._today_dir(tmp_path) / prep.PREP_STATUS_FILENAME).read_text(encoding="utf-8")
    )
    assert saved == []
    assert status["status"] == "blocked"
    assert status["phase"] == "next_nine_canary_gate_blocked"
    assert "missing canary review receipt" in status["last_error"]


def test_run_prep_one_segment_writes_status_and_exact_planner_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import agents.programme_manager.planner as planner_module

    captured_targets: list[int | None] = []

    class FakePlanner:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def plan(
            self,
            *,
            show_id: str,  # noqa: ARG002
            target_programmes: int | None = None,
            **_kw: Any,
        ) -> None:
            captured_targets.append(target_programmes)
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
    monkeypatch.setattr(
        prep,
        "assert_segment_prep_allowed",
        lambda _activity: SimpleNamespace(mode="open", reason="test", source="test"),
    )
    monkeypatch.setattr(planner_module, "ProgrammePlanner", FakePlanner)
    saved = prep.run_prep(tmp_path)

    today = prep._today_dir(tmp_path)
    status = json.loads((today / prep.PREP_STATUS_FILENAME).read_text(encoding="utf-8"))
    manifest = json.loads((today / "manifest.json").read_text(encoding="utf-8"))
    assert saved == []
    assert captured_targets == [1]
    assert status["status"] == "completed_no_programmes"
    assert status["target_segments"] == 1
    assert status["max_rounds"] == 1
    assert status["planner_target_programmes"] == 1
    assert status["phase"] == "completed_no_programmes"
    assert status["manifest_path"].endswith("manifest.json")
    assert manifest["programmes"] == []
    assert manifest["run_saved_programmes"] == []
    ledger_path = today / prep.PREP_DIAGNOSTIC_LEDGER_FILENAME
    ledger_row = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert ledger_row["terminal_status"] == "no_candidate"
    assert ledger_row["terminal_reason"] == "planner_no_segmented_programmes"
    assert ledger_row["diagnostic_only"] is True
    assert ledger_row["release_boundary"] == "closed"
    assert ledger_row["runtime_boundary"] == "closed"
    assert ledger_row["loadable"] is False
    dossier = json.loads(Path(ledger_row["dossier_ref"]).read_text(encoding="utf-8"))
    assert dossier["no_candidate_metadata"]["target_segments"] == 1
    assert dossier["manifest_eligible"] is False
    assert dossier["qdrant_eligible"] is False


def test_prep_segment_no_beats_writes_non_loadable_diagnostic_dossier(
    tmp_path: Path,
) -> None:
    programme = SimpleNamespace(
        programme_id="prog-no-beats",
        role=SimpleNamespace(value="rant"),
        content=SimpleNamespace(
            narrative_beat="No beat candidate",
            segment_beats=[],
        ),
    )
    session = {
        "prep_session_id": "segment-prep-test",
        "model_id": prep.RESIDENT_PREP_MODEL,
        "llm_calls": [],
    }

    saved = prep.prep_segment(programme, tmp_path, prep_session=session)

    assert saved is None
    assert not (tmp_path / "prog-no-beats.json").exists()
    assert not (tmp_path / "manifest.json").exists()
    ledger_row = json.loads(
        (tmp_path / prep.PREP_DIAGNOSTIC_LEDGER_FILENAME).read_text(encoding="utf-8")
    )
    assert ledger_row["terminal_status"] == "no_candidate"
    assert ledger_row["terminal_reason"] == "no_segment_beats"
    assert ledger_row["diagnostic_only"] is True
    assert ledger_row["release_boundary"] == "closed"
    assert ledger_row["runtime_boundary"] == "closed"
    assert ledger_row["loadable"] is False
    dossier = json.loads(Path(ledger_row["dossier_ref"]).read_text(encoding="utf-8"))
    assert dossier["record_type"] == "prep_terminal_dossier"
    assert dossier["no_candidate_metadata"]["candidate_count"] == 0
    assert dossier["manifest_eligible"] is False
    assert dossier["qdrant_eligible"] is False


def test_prep_segment_quarantines_actionability_invalid_script(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    programme = SimpleNamespace(
        programme_id="prog-invalid-action",
        role=SimpleNamespace(value="tier_list"),
        content=_ready_content(
            narrative_beat="Unsupported clip claim",
            segment_beats=["Make the claim without unsupported visuals"],
            role="tier_list",
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
    assert diagnostic["authority"] == prep.PREP_DIAGNOSTIC_AUTHORITY
    assert diagnostic["diagnostic_only"] is True
    assert diagnostic["release_boundary"] == "closed"
    assert diagnostic["runtime_boundary"] == "closed"
    assert diagnostic["loadable"] is False
    assert diagnostic["actionability_alignment"]["ok"] is False
    assert diagnostic["actionability_alignment"]["removed_unsupported_action_lines"]
    ledger_row = json.loads(
        (tmp_path / prep.PREP_DIAGNOSTIC_LEDGER_FILENAME).read_text(encoding="utf-8")
    )
    assert ledger_row["terminal_status"] == "refused_no_release"
    assert ledger_row["terminal_reason"] == "actionability_alignment_failed"
    assert ledger_row["manifest_eligible"] is False
    dossier = json.loads(Path(ledger_row["dossier_ref"]).read_text(encoding="utf-8"))
    assert dossier["diagnostic_refs"] == [str(diagnostic_path)]
    assert dossier["refusal_metadata"]["removed_unsupported_action_line_count"] == 1


def test_prep_segment_quarantines_responsible_spoken_only_script(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    programme = SimpleNamespace(
        programme_id="prog-spoken-only",
        role=SimpleNamespace(value="rant"),
        content=_ready_content(
            narrative_beat="Spoken only argument",
            segment_beats=["argue the point without visible evidence"],
            role="rant",
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
    diagnostic_path = tmp_path / "prog-spoken-only.layout-invalid.json"
    assert diagnostic_path.exists()
    diagnostic = json.loads(diagnostic_path.read_text(encoding="utf-8"))
    assert diagnostic["not_loadable_reason"] == "layout responsibility failed"
    assert diagnostic["authority"] == prep.PREP_DIAGNOSTIC_AUTHORITY
    assert diagnostic["diagnostic_only"] is True
    assert diagnostic["release_boundary"] == "closed"
    assert diagnostic["runtime_boundary"] == "closed"
    assert diagnostic["loadable"] is False
    assert diagnostic["layout_responsibility"]["ok"] is False
    assert "unsupported_layout_need" in {
        item["reason"] for item in diagnostic["layout_responsibility"]["violations"]
    }
    ledger_row = json.loads(
        (tmp_path / prep.PREP_DIAGNOSTIC_LEDGER_FILENAME).read_text(encoding="utf-8")
    )
    assert ledger_row["terminal_status"] == "refused_no_release"
    assert ledger_row["terminal_reason"] == "layout_responsibility_failed"
    assert ledger_row["qdrant_eligible"] is False
    dossier = json.loads(Path(ledger_row["dossier_ref"]).read_text(encoding="utf-8"))
    assert dossier["diagnostic_refs"] == [str(diagnostic_path)]
    assert dossier["refusal_metadata"]["violation_count"] >= 1


def test_prep_segment_quarantines_spoken_only_tier_list_without_validator_repair(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    programme = SimpleNamespace(
        programme_id="prog-tier-repair",
        role=SimpleNamespace(value="tier_list"),
        content=_ready_content(
            narrative_beat="Tier list on programming languages",
            segment_beats=[
                "hook with a tier rubric",
                "rank the early language",
                "rank the modern language",
            ],
            role="tier_list",
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
        raise AssertionError(f"unexpected phase {phase!r}")

    monkeypatch.setattr(prep, "_call_llm", fake_call)
    monkeypatch.setattr(prep, "_refine_script", lambda script, _programme, **_kwargs: script)
    monkeypatch.setattr(prep, "_emit_self_evaluation", lambda *_args, **_kwargs: None)

    saved = prep.prep_segment(programme, tmp_path, prep_session=session)

    assert saved is None
    assert not (tmp_path / "prog-tier-repair.json").exists()
    diagnostic_path = tmp_path / "prog-tier-repair.layout-invalid.json"
    diagnostic = json.loads(diagnostic_path.read_text(encoding="utf-8"))
    assert diagnostic["not_loadable_reason"] == "layout responsibility failed"
    assert "missing_tier_placement_phrase" in {
        item["reason"] for item in diagnostic["layout_responsibility"]["violations"]
    }
    assert prompts == ["prompt"]
    assert phases == ["compose"]
    assert session["llm_calls"][0]["phase"] == "compose"


def test_prep_segment_rejects_tier_list_without_exact_placements(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    programme = SimpleNamespace(
        programme_id="prog-tier-generic-repair",
        role=SimpleNamespace(value="tier_list"),
        content=_ready_content(
            narrative_beat="Tier list on programming languages",
            segment_beats=[
                "hook with a tier rubric",
                "rank FORTRAN as the early language",
                "rank Java as the modern language",
            ],
            role="tier_list",
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
        raise AssertionError(f"unexpected phase {phase!r}")

    monkeypatch.setattr(prep, "_call_llm", fake_call)
    monkeypatch.setattr(prep, "_refine_script", lambda script, _programme, **_kwargs: script)
    monkeypatch.setattr(prep, "_emit_self_evaluation", lambda *_args, **_kwargs: None)

    saved = prep.prep_segment(programme, tmp_path, prep_session=session)

    assert saved is None
    diagnostic_path = tmp_path / "prog-tier-generic-repair.layout-invalid.json"
    diagnostic = json.loads(diagnostic_path.read_text(encoding="utf-8"))
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
    payload["source_provenance_sha256"] = prep._sha256_json(payload["source_hashes"])
    payload["artifact_sha256"] = prep._artifact_hash(payload)
    _write_artifact(tmp_path, payload)

    assert prep.load_prepped_programmes(tmp_path, require_selected=False) == []


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
    payload["source_provenance_sha256"] = prep._sha256_json(payload["source_hashes"])
    payload["artifact_sha256"] = prep._artifact_hash(payload)
    today = prep._today_dir(tmp_path)
    path = today / "prog-tier-final-candidate.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    (today / "manifest.json").write_text(
        json.dumps({"programmes": [path.name]}),
        encoding="utf-8",
    )

    assert prep.load_prepped_programmes(tmp_path, require_selected=False) == []


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

    assert prep.load_prepped_programmes(tmp_path, require_selected=False) == []


def test_raw_manifest_candidates_are_not_published_to_qdrant() -> None:
    assert not hasattr(prep, "_upsert_programmes_to_qdrant")
