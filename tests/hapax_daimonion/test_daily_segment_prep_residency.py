from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agents.hapax_daimonion import daily_segment_prep as prep
from agents.hapax_daimonion import programme_loop
from shared.programme_store import ProgrammePlanStore
from shared.segment_candidate_selection import SEGMENT_CANDIDATE_SELECTION_VERSION
from shared.source_packet import (
    ResolvedSourceSet,
    SourcePacket,
    build_resolved_source_set,
    validate_cited_handles,
)

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


@pytest.fixture(autouse=True)
def _healthy_council_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default the deliberative council to a HEALTHY verdict for prep tests.

    prep_segment is now fail-LOUD: a degraded / unavailable council (no LiteLLM
    in the test env) is a TERMINAL no-release. These tests exercise the
    DETERMINISTIC gauntlet (actionability / layout / tier-list / manifest), not
    the council, so a healthy default lets them reach their actual concern. The
    council fail-loud behavior has dedicated pins (test_council_coherence_check_*
    here, and tests/deliberative_council/test_council_fail_loud.py). Tests that
    patch ``deliberate`` themselves override this (later monkeypatch wins).
    cc-task cctv-council-perfect-health-faillloud-convergence.
    """
    from agents.deliberative_council import engine as council_engine
    from agents.deliberative_council.models import ConvergenceStatus, CouncilVerdict

    async def _healthy(council_input: Any, mode: Any, rubric: Any, config: Any = None) -> Any:
        return CouncilVerdict(
            scores={"coherence": 4},
            confidence_bands={},
            convergence_status=ConvergenceStatus.CONVERGED,
            disagreement_log=[],
            research_findings=[],
            evidence_matrix=None,
            receipt={"council_health": {"members_valid": 6, "families_valid": 5}},
        )

    monkeypatch.setattr(council_engine, "deliberate", _healthy)


@pytest.fixture(autouse=True)
def _recruited_sources_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default source recruitment to a HEALTHY non-empty ResolvedSourceSet.

    prep_segment now RECRUITS a content-hash-bound source set before composition
    and REFUSES (no-candidate) when nothing resolves. Most tests exercise the
    compose/gate gauntlet, not recruitment, so a healthy default set (containing
    the canonical test SOURCE_REF) lets them proceed. The refuse-on-empty
    behavior has a dedicated pin (test_prep_segment_refuses_when_no_sources_resolve).
    Tests that set recruit_source_set themselves override this (later wins).
    """
    import agents.hapax_daimonion.angle_resolver as angle_resolver
    from shared.source_packet import SourcePacket, build_resolved_source_set

    def _recruit(topic: str, **_kwargs: Any) -> Any:
        return build_resolved_source_set(
            topic or "topic",
            (
                SourcePacket(
                    source_ref=SOURCE_REF,
                    content_hash="testrecruithash0",
                    snippet="recruited test source snippet",
                    freshness="fresh",
                    source_consequence="the cited source changes the claim",
                ),
            ),
        )

    monkeypatch.setattr(angle_resolver, "recruit_source_set", _recruit)


@pytest.fixture(autouse=True)
def _composability_gate_accepts_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default the S2 topic+type composability gate to ACCEPT for prep tests.

    prep_segment now runs a pre-compose STRUCTURAL composability gate (a capable-
    model gateway call) before the expensive compose. These tests exercise the
    downstream deterministic / coherence gauntlet, not the gate, so an ACCEPT
    default lets them reach their actual concern (and keeps them hermetic — no
    live gateway call). The gate's own behavior is pinned in
    test_segment_composability_gate.py. Tests that patch assess_composability
    themselves override this (later monkeypatch wins).
    """
    import agents.hapax_daimonion.segment_composability_gate as gate

    monkeypatch.setattr(
        gate,
        "assess_composability",
        lambda *_a, **_k: gate.CompositionGateResult(True, "test-default-accept"),
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
        deadline_monotonic: float | None = None,  # noqa: ARG001 — accept run_prep's AC-3a deadline
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


def test_substance_feedback_persist_round_trip(tmp_path: Path) -> None:
    """A3: downstream substance rationale persists per-day so the NEXT batch
    invocation's planner can re-author informed by it. Overwrite semantics — an
    empty list clears the file so stale rationale never haunts later runs."""
    today = prep._today_dir(tmp_path)

    assert prep._read_prior_substance_feedback(today) is None

    prep._write_substance_feedback(today, ["[a] claims thin", "[b] unsupported topic"])
    out = prep._read_prior_substance_feedback(today)
    assert out is not None
    assert "claims thin" in out
    assert "unsupported topic" in out

    prep._write_substance_feedback(today, [])
    assert prep._read_prior_substance_feedback(today) is None


def test_run_prep_threads_prior_substance_feedback_into_planner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A3: run_prep seeds the planner with the prior batch invocation's persisted
    downstream substance rationale, so the planner re-authors informed by why the
    last run's segments were found thin (segment prep runs in repeated batches —
    'the next round' is the next invocation)."""
    import agents.programme_manager.planner as planner_module

    today = prep._today_dir(tmp_path)
    rationale = "[prog-x] council refuted 3/4 claims as unsupported by any source"
    (today / prep.PLANNER_SUBSTANCE_FEEDBACK_FILENAME).write_text(rationale, encoding="utf-8")

    captured: list[str | None] = []

    class FakePlanner:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def plan(
            self,
            *,
            show_id: str,  # noqa: ARG002
            prior_substance_feedback: str | None = None,
            **_kw: Any,
        ) -> None:
            captured.append(prior_substance_feedback)
            return None

    monkeypatch.setattr(prep, "MAX_SEGMENTS", 1)
    monkeypatch.setattr(
        prep,
        "_new_prep_session",
        lambda: {
            "prep_session_id": "segment-prep-substance",
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

    prep.run_prep(tmp_path)

    assert captured, "planner was never called"
    assert captured[0] == rationale


def test_record_substance_feedback_accumulates_and_skips_blank() -> None:
    """A3 helper: rationale text is accumulated per-programme on the session;
    blank rationale is ignored (no empty feedback fed to the planner)."""
    session: dict[str, Any] = {}
    prep._record_substance_feedback(session, "prog-1", "claims unsupported by sources")
    prep._record_substance_feedback(session, "prog-2", "   ")
    prep._record_substance_feedback(session, "prog-3", "topic too abstract for evidence")

    assert session["planner_substance_feedback"] == [
        "[prog-1] claims unsupported by sources",
        "[prog-3] topic too abstract for evidence",
    ]


def test_prep_segment_records_substance_feedback_on_no_candidate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A3: when disconfirmation refutes a structural claim (no-candidate), the
    gap rationale is recorded on the session so the NEXT batch invocation's
    planner re-authors instead of re-proposing the same thin topic. The segment
    is still honestly refused (returns None)."""
    import shared.segment_disconfirmation as disc

    programme = SimpleNamespace(
        programme_id="prog-nc",
        role=SimpleNamespace(value="rant"),
        content=_ready_content(
            narrative_beat="A thin claim",
            segment_beats=["argue the point with a source receipt"],
            role="rant",
        ),
    )
    session = {
        "prep_session_id": "segment-prep-test",
        "model_id": prep.RESIDENT_PREP_MODEL,
        "llm_calls": [],
    }

    monkeypatch.setattr(prep, "_build_seed", lambda _programme: "seed")
    monkeypatch.setattr(prep, "_build_full_segment_prompt", lambda _programme, _seed: "prompt")
    monkeypatch.setattr(
        prep,
        "_call_llm",
        lambda _prompt, **_kwargs: json.dumps(
            ["According to the receipt, the launch claim changes once the source is visible."]
        ),
    )
    monkeypatch.setattr(prep, "_refine_script", lambda script, _programme, **_kwargs: script)
    monkeypatch.setattr(prep, "_emit_self_evaluation", lambda *_args, **_kwargs: None)

    # Force the disconfirmation no-candidate verdict deterministically.
    monkeypatch.setattr(disc, "extract_claims", lambda **_kwargs: ["claim:1"])
    monkeypatch.setattr(disc, "run_council_disconfirmation", lambda _claims: ["verdict"])
    monkeypatch.setattr(
        disc, "apply_council_verdicts", lambda *_a, **_kw: {"no_candidate_triggered": True}
    )
    monkeypatch.setattr(
        disc,
        "build_substance_gap_report",
        lambda *_a, **_kw: "GAP: claims unsupported by any cited source",
    )

    saved = prep.prep_segment(programme, tmp_path, prep_session=session)

    assert saved is None
    assert session["planner_substance_feedback"] == [
        "[prog-nc] GAP: claims unsupported by any cited source"
    ]


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


# ─────────────────────────────────────────────────────────────────────────────
# Phase A — generation integrity (R-A1..R-A3)
# cc-task: segment-prep-phase-a-generation-integrity-20260607
# ─────────────────────────────────────────────────────────────────────────────


def _council_verdict(scores: dict[str, int | None]) -> Any:
    from agents.deliberative_council.models import ConvergenceStatus, CouncilVerdict

    return CouncilVerdict(
        scores=scores,
        confidence_bands={},
        convergence_status=ConvergenceStatus.CONVERGED,
        disagreement_log=[],
        research_findings=[],
        evidence_matrix=None,
        receipt={"input_hash": "test"},
    )


def test_select_angle_routes_through_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    """A1.1: angle selection must resolve a provider via explicit gateway routing
    (provider prefix + api_base) instead of raising ``LLM Provider NOT provided``
    on a bare ``local-fast`` model. The bare call crashed every angle resolution
    into the degenerate ``except`` fallback (topic-as-thesis, no challenge)."""
    import litellm

    from agents.hapax_daimonion import angle_resolver
    from shared.source_packet import SourcePacket

    captured: dict[str, Any] = {}

    def fake_completion(**kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        content = (
            "THESIS: a contested thesis\n"
            "CHALLENGE: a real tension\n"
            "OPENING_PRESSURE: why does it matter?\n"
            "SUPPORTING_SOURCES: 1\n"
            "CHALLENGING_SOURCES: 2"
        )
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    monkeypatch.setattr(litellm, "completion", fake_completion)

    packets = [
        SourcePacket(
            source_ref="vault:a", content_hash="h1", snippet="position one", freshness="fresh"
        ),
        SourcePacket(
            source_ref="vault:b", content_hash="h2", snippet="position two", freshness="fresh"
        ),
    ]
    angle = angle_resolver._select_angle("a topic", packets)

    assert captured, "litellm.completion was never called"
    model = captured["model"]
    # An explicit provider prefix + api_base is what lets litellm resolve a
    # provider; without either the call raises 'LLM Provider NOT provided'.
    assert "/" in model, f"model {model!r} has no explicit provider prefix"
    assert captured.get("api_base"), "no api_base passed; provider cannot resolve"
    litellm.get_llm_provider(model)  # resolved model string must not raise
    # The angle came from the parsed LLM response, not the crash fallback.
    assert angle.thesis_position == "a contested thesis"


def test_web_supplement_is_excised_loud_noop(caplog: pytest.LogCaptureFixture) -> None:
    """A1.3: the sparse-source web supplement is EXCISED to a loud no-op. The
    prior code called the async ``web_verify`` WITHOUT ``await`` — a coroutine is
    never a ``str``, so it silently did nothing. The fix does NOT add ``await``
    (that routes to the ``web-research`` alias the research found mis-routes to a
    non-grounded model, laundering ungrounded output as 'verification'). The
    supplement stays disabled with a loud ledger entry until a real grounded web
    provider exists; sparse local sources stay sparse and a no-candidate is the
    honest outcome."""
    import logging

    from agents.hapax_daimonion import angle_resolver
    from shared.source_packet import SourcePacket

    existing = [
        SourcePacket(
            source_ref="vault:a", content_hash="h1", snippet="only local", freshness="fresh"
        )
    ]

    with caplog.at_level(logging.WARNING, logger="agents.hapax_daimonion.angle_resolver"):
        out = angle_resolver._web_supplement("a topic", existing)

    # Disabled: nothing appended, the original list is returned unchanged.
    assert out == existing
    assert len(out) == 1
    # Loud ledger entry — not a silent no-op.
    assert any("web supplement" in record.message.lower() for record in caplog.records)
    # Negative-existence: the broken async web_verify route is gone from the module.
    source = Path(angle_resolver.__file__).read_text(encoding="utf-8")
    assert "web_verify" not in source


def test_anterior_topic_substance_gate_is_removed() -> None:
    """A2: the mis-staged anterior topic-substance gate is REMOVED. It ran the
    adversarial ``DisconfirmationRubric`` (which needs attached evidence) on a
    BARE pre-source topic STRING, structurally flooring ~2.0 for any abstract
    topic. Disconfirmation keeps its correct home DOWNSTREAM — on extracted
    claims (``segment_disconfirmation``) and the composed script
    (``_council_coherence_check``). No replacement anterior phrase/length/keyword
    gate may be reintroduced (that is the forbidden expert-rule)."""
    assert not hasattr(prep, "_council_topic_substance_gate")
    source = Path(prep.__file__).read_text(encoding="utf-8")
    assert "_council_topic_substance_gate" not in source


def test_compose_refusal_reason_allows_viable_segment() -> None:
    """R-A1 pass path: a segment whose contract, live-event report, and
    live-event viability all pass is NOT refused at compose time."""
    ok = {"ok": True}
    assert (
        prep._compose_refusal_reason(
            segment_prep_contract_report=ok,
            segment_live_event_report=ok,
            live_event_viability_report=ok,
        )
        is None
    )


def test_compose_refusal_reason_refuses_non_viable_segment() -> None:
    """R-A1 refusal path: live-event viability is enforced at WRITE time, so a
    non-viable segment is refused at compose (recorded as a refusal dossier)
    rather than saved as a dead candidate dropped at the manifest boundary."""
    ok = {"ok": True}
    assert (
        prep._compose_refusal_reason(
            segment_prep_contract_report=ok,
            segment_live_event_report=ok,
            live_event_viability_report={"ok": False},
        )
        == "live_event_viability_not_demonstrated"
    )
    assert (
        prep._compose_refusal_reason(
            segment_prep_contract_report={"ok": False},
            segment_live_event_report=ok,
            live_event_viability_report=ok,
        )
        == "segment_prep_contract_failed"
    )
    assert (
        prep._compose_refusal_reason(
            segment_prep_contract_report=ok,
            segment_live_event_report={"ok": False},
            live_event_viability_report=ok,
        )
        == "segment_live_event_report_failed"
    )


def test_council_coherence_check_constructs_valid_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R-A3: the coherence-check council config must be constructible."""
    from agents.deliberative_council import engine as council_engine
    from agents.deliberative_council.models import CouncilConfig

    captured: dict[str, Any] = {}

    async def fake_deliberate(
        council_input: Any, mode: Any, rubric: Any, config: Any = None
    ) -> Any:
        captured["config"] = config
        return _council_verdict({"coherence": 4})

    monkeypatch.setattr(council_engine, "deliberate", fake_deliberate)

    outcome = prep._council_coherence_check("a coherent composed script", "prog-1")

    assert "config" in captured, "deliberate never reached — CouncilConfig construction raised"
    assert isinstance(captured["config"], CouncilConfig)
    assert outcome.passed is True
    assert outcome.refused is False


def test_run_narrative_critique_constructs_valid_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R-A3: the narrative-critique default council config must be constructible
    (no ``max_models``/``phase3_rounds`` extra_forbidden)."""
    from agents.deliberative_council import engine as council_engine
    from agents.deliberative_council.models import CouncilConfig
    from shared.segment_narrative_critique import run_narrative_critique

    captured: dict[str, Any] = {}

    async def fake_deliberate(
        council_input: Any, mode: Any, rubric: Any, config: Any = None
    ) -> Any:
        captured["config"] = config
        return _council_verdict({"focalization_integrity": 4, "escalation_architecture": 4})

    monkeypatch.setattr(council_engine, "deliberate", fake_deliberate)

    run_narrative_critique("a composed narrative script " + "x" * 200, "prog-1")

    assert "config" in captured, "deliberate never reached — CouncilConfig construction raised"
    assert isinstance(captured["config"], CouncilConfig)


def test_council_coherence_check_refuses_when_degraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail-LOUD (cc-task cctv-council-perfect-health-faillloud-convergence):
    a degraded coherence council (no trustworthy scores) REFUSES — it must NOT
    wave the segment through. Replaces the prior fail-open behavior."""
    from agents.deliberative_council import engine as council_engine

    async def fake_deliberate(
        council_input: Any, mode: Any, rubric: Any, config: Any = None
    ) -> Any:
        return _council_verdict({})

    monkeypatch.setattr(council_engine, "deliberate", fake_deliberate)

    outcome = prep._council_coherence_check("a script", "prog-1")
    assert outcome.refused is True
    assert outcome.passed is False


def test_council_coherence_check_refuses_when_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """council-unavailable (deliberate raises) → the consumer REFUSES the
    segment, never returns a silent pass."""
    from agents.deliberative_council import engine as council_engine

    async def boom(council_input: Any, mode: Any, rubric: Any, config: Any = None) -> Any:
        raise RuntimeError("litellm down")

    monkeypatch.setattr(council_engine, "deliberate", boom)

    outcome = prep._council_coherence_check("a script", "prog-1")
    assert outcome.refused is True
    assert outcome.passed is False


def test_council_coherence_check_refuses_on_refused_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A REFUSED panel verdict (below quorum / family floor) → coherence refuses
    and records the council decision for the manifest receipt."""
    from agents.deliberative_council import engine as council_engine
    from agents.deliberative_council.models import ConvergenceStatus, CouncilVerdict

    async def fake_deliberate(
        council_input: Any, mode: Any, rubric: Any, config: Any = None
    ) -> Any:
        return CouncilVerdict(
            scores={},
            confidence_bands={},
            convergence_status=ConvergenceStatus.REFUSED,
            disagreement_log=[],
            research_findings=[],
            evidence_matrix=None,
            receipt={"council_health": {"members_valid": 1, "families_valid": 1}},
        )

    monkeypatch.setattr(council_engine, "deliberate", fake_deliberate)

    outcome = prep._council_coherence_check("a script", "prog-1")
    assert outcome.refused is True
    assert outcome.council_decisions["convergence_status"] == "refused"
    assert outcome.council_decisions["members_valid"] == 1


def test_council_coherence_check_records_health_when_healthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A healthy, good-quality panel passes AND records members_valid/
    families_valid into the council_decisions receipt for the manifest."""
    from agents.deliberative_council import engine as council_engine
    from agents.deliberative_council.models import ConvergenceStatus, CouncilVerdict

    async def fake_deliberate(
        council_input: Any, mode: Any, rubric: Any, config: Any = None
    ) -> Any:
        return CouncilVerdict(
            scores={"a": 4, "b": 4},
            confidence_bands={},
            convergence_status=ConvergenceStatus.CONVERGED,
            disagreement_log=[],
            research_findings=[],
            evidence_matrix=None,
            receipt={"council_health": {"members_valid": 5, "families_valid": 5}},
        )

    monkeypatch.setattr(council_engine, "deliberate", fake_deliberate)

    outcome = prep._council_coherence_check("a script", "prog-1")
    assert outcome.passed is True
    assert outcome.refused is False
    assert outcome.council_decisions["members_valid"] == 5
    assert outcome.council_decisions["families_valid"] == 5
    # Per-axis scores are recorded so the generative trace stance fields are
    # populated, not silently unassessed (codex-1, PR #4133).
    assert outcome.council_decisions["scores"] == {"a": 4, "b": 4}


def test_council_coherence_check_critical_axis_floor_blocks_mean_masking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A structurally strong segment whose ending fizzles (payoff=1) scores a
    mean of 3.75 — which clears the mean>=3 gate — but must NOT release: a total
    failure on any one coherence axis is unreleasable. The mean masks it; the
    critical-axis floor catches it. Evidenced by scripts/calibrate-eval.py
    (fixture mixed-strong-but-no-payoff). It refines (passed=False), not
    refuses (refused=False), and records the offending axis in the receipt."""
    from agents.deliberative_council import engine as council_engine
    from agents.deliberative_council.models import ConvergenceStatus, CouncilVerdict

    async def fake_deliberate(
        council_input: Any, mode: Any, rubric: Any, config: Any = None
    ) -> Any:
        return CouncilVerdict(
            scores={
                "opening_pressure": 5,
                "argumentative_specificity": 5,
                "thematic_progression": 4,
                "payoff_resolution": 1,
            },
            confidence_bands={},
            convergence_status=ConvergenceStatus.CONVERGED,
            disagreement_log=[],
            research_findings=[],
            evidence_matrix=None,
            receipt={"council_health": {"members_valid": 6, "families_valid": 5}},
        )

    monkeypatch.setattr(council_engine, "deliberate", fake_deliberate)

    outcome = prep._council_coherence_check("a strong script that fizzles", "prog-1")
    assert outcome.council_decisions["mean_score"] == 3.75  # would pass a mean-only gate
    assert outcome.passed is False  # but the critical-axis floor blocks release
    assert outcome.refused is False  # it refines, it does not refuse
    assert outcome.council_decisions["axis_min"] == 1
    assert outcome.council_decisions["axis_min_name"] == "payoff_resolution"
    assert "payoff_resolution" in outcome.feedback


def test_council_coherence_check_passes_when_all_axes_clear_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The floor must not over-reject: a uniformly-adequate panel (no axis at the
    rock-bottom) with mean>=3 still passes."""
    from agents.deliberative_council import engine as council_engine
    from agents.deliberative_council.models import ConvergenceStatus, CouncilVerdict

    async def fake_deliberate(
        council_input: Any, mode: Any, rubric: Any, config: Any = None
    ) -> Any:
        return CouncilVerdict(
            scores={"opening_pressure": 3, "payoff_resolution": 2, "thematic_progression": 4},
            confidence_bands={},
            convergence_status=ConvergenceStatus.CONVERGED,
            disagreement_log=[],
            research_findings=[],
            evidence_matrix=None,
            receipt={"council_health": {"members_valid": 6, "families_valid": 5}},
        )

    monkeypatch.setattr(council_engine, "deliberate", fake_deliberate)

    outcome = prep._council_coherence_check("an adequate script", "prog-1")
    assert outcome.passed is True
    assert outcome.refused is False
    assert outcome.council_decisions["axis_min"] == 2  # mediocre, but not catastrophic


def test_prep_segment_blocks_release_when_coherence_fails_after_noop_refine(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Coherence (incl. the critical-axis floor) is a RELEASE gate, not just a
    refinement trigger. When the first check fails and refinement is a no-op, the
    post-refine re-check must BLOCK release (return None) — not let a
    sub-threshold / critical-axis-failed draft proceed to later gates and be
    saved. Verifies the fix for codex-1's "floor blocks release is not
    implemented" (PR #4133); the assertion that BOTH checks ran guards against a
    false pass from an earlier gate."""
    programme = SimpleNamespace(
        programme_id="prog-coh",
        role=SimpleNamespace(value="rant"),
        content=_ready_content(
            narrative_beat="A thin claim",
            segment_beats=["argue the point with a source receipt"],
            role="rant",
        ),
    )
    session = {
        "prep_session_id": "segment-prep-test",
        "model_id": prep.RESIDENT_PREP_MODEL,
        "llm_calls": [],
    }

    monkeypatch.setattr(prep, "_build_seed", lambda _programme: "seed")
    monkeypatch.setattr(prep, "_build_full_segment_prompt", lambda _programme, _seed: "prompt")
    monkeypatch.setattr(
        prep,
        "_call_llm",
        lambda _prompt, **_kwargs: json.dumps(
            ["According to the receipt, the launch claim changes once the source is visible."]
        ),
    )
    monkeypatch.setattr(prep, "_refine_script", lambda script, _programme, **_kwargs: script)
    monkeypatch.setattr(prep, "_emit_self_evaluation", lambda *_args, **_kwargs: None)

    coh_calls = {"n": 0}

    def _low(_script: str, _pid: str) -> Any:
        coh_calls["n"] += 1
        return prep._CoherenceOutcome(
            passed=False,
            refused=False,
            feedback="Council coherence scores (mean=1.5, min=1):",
            council_decisions={"check": "coherence", "mean_score": 1.5, "axis_min": 1},
        )

    monkeypatch.setattr(prep, "_council_coherence_check", _low)

    saved = prep.prep_segment(programme, tmp_path, prep_session=session)

    assert saved is None  # release blocked
    assert coh_calls["n"] == 2  # initial check + post-refine re-check both ran


def test_prep_segment_blocks_release_when_final_coherence_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The FINAL coherence gate validates the artifact that actually SHIPS. A draft
    that PASSED the early check can still be regenerated by the recomposition
    passes (disconfirmation/narrative/actionability); the final gate re-validates
    that post-recompose script and blocks release if it fails. Gating only the
    early/refined draft let a recompose-degraded final script ship un-validated
    (codex-1, PR #4133). Asserting both coherence calls ran (early pass + final
    fail, mid re-check skipped) proves the final gate — not an earlier gate — is
    what blocked."""
    import shared.segment_disconfirmation as disc
    import shared.segment_narrative_critique as narr
    from agents.deliberative_council.models import (
        ConvergenceStatus,
        NarrativeVerdict,
        NarrativeVerdictStatus,
    )

    programme = SimpleNamespace(
        programme_id="prog-final",
        role=SimpleNamespace(value="rant"),
        content=_ready_content(
            narrative_beat="A claim",
            segment_beats=["argue the point with a source receipt"],
            role="rant",
        ),
    )
    session = {
        "prep_session_id": "segment-prep-test",
        "model_id": prep.RESIDENT_PREP_MODEL,
        "llm_calls": [],
    }

    monkeypatch.setattr(prep, "_build_seed", lambda _programme: "seed")
    monkeypatch.setattr(prep, "_build_full_segment_prompt", lambda _programme, _seed: "prompt")
    monkeypatch.setattr(
        prep,
        "_call_llm",
        lambda _prompt, **_kwargs: json.dumps(
            ["According to the receipt, the launch claim changes once the source is visible."]
        ),
    )
    monkeypatch.setattr(prep, "_refine_script", lambda script, _programme, **_kwargs: script)
    monkeypatch.setattr(prep, "_emit_self_evaluation", lambda *_args, **_kwargs: None)
    # No claims -> disconfirmation skipped; benign narrative verdict -> no recompose.
    monkeypatch.setattr(disc, "extract_claims", lambda **_kwargs: [])
    monkeypatch.setattr(
        narr,
        "run_narrative_critique",
        lambda _text, _pid: NarrativeVerdict(
            scores={},
            confidence_bands={},
            convergence_status=ConvergenceStatus.CONVERGED,
            verdict_status=NarrativeVerdictStatus.BROADCAST_READY,
            receipt={"mean_score": 4.0},
        ),
    )
    monkeypatch.setattr(
        prep,
        "validate_segment_actionability",
        lambda script, _beats: {
            "ok": True,
            "prepared_script": list(script),
            "beat_action_intents": [],
            "diagnostic_sanitized_script": list(script),
            "removed_unsupported_action_lines": [],
        },
    )

    coh_calls = {"n": 0}

    def _coh(_script: str, _pid: str) -> Any:
        coh_calls["n"] += 1
        passed = coh_calls["n"] == 1  # early PASSES, final FAILS
        return prep._CoherenceOutcome(
            passed=passed,
            refused=False,
            feedback="" if passed else "Council coherence scores (mean=1.5, min=1):",
            council_decisions={
                "check": "coherence",
                "mean_score": 4.0 if passed else 1.5,
                "axis_min": 4 if passed else 1,
                "scores": {},
            },
        )

    monkeypatch.setattr(prep, "_council_coherence_check", _coh)

    saved = prep.prep_segment(programme, tmp_path, prep_session=session)

    assert saved is None  # final gate blocked release
    assert coh_calls["n"] == 2  # early (passed) + final (failed); mid re-check skipped


def test_salient_impingement_block_tolerates_malformed_strength() -> None:
    """A live /dev/shm impingement record may carry a null or string strength. The
    renderer formats strength with {:.2f}, which raises on a non-numeric value
    OUTSIDE the read guard — turning an observability input into a failed segment.
    The renderer must coerce defensively (codex-1, PR #4133)."""
    records = [
        {"source": "a", "strength": None, "content": {"narrative": "null strength"}},
        {"source": "b", "strength": "high", "type": "spike"},
        {"source": "c", "strength": 0.8, "content": {"narrative": "real strength"}},
    ]
    block, ranked = prep._salient_impingement_block(records)
    assert "SALIENT FIELD" in block
    assert "0.80" in block  # the numeric record renders
    assert "0.00" in block  # the malformed ones coerce to 0.0 instead of raising
    assert len(ranked) == 3


# --- Phase C: selection + manifest automation and prep->active-Programme bridge ----


def _phase_c_live_report(score: int, *, role: str = "rant") -> dict[str, Any]:
    return {
        "live_event_rubric_version": 1,
        "score": score,
        "band": "good" if score >= 82 else "thin",
        "ok": score >= 82,
        "dimensions": [
            {"name": "live_event_object", "passed": True, "points": 12, "observed": {}},
            {
                "name": "role_standard_fit",
                "passed": True,
                "points": 10,
                "observed": {"role": role, "required_action_kinds": []},
            },
        ],
    }


def _phase_c_hex_sha(pid: str) -> str:
    return hashlib.sha256(pid.encode("utf-8")).hexdigest()


def _phase_c_eligible_artifact(pid: str, *, score: int) -> dict[str, Any]:
    return {
        "programme_id": pid,
        "role": "rant",
        "artifact_path": f"/tmp/{pid}.json",
        "artifact_sha256": _phase_c_hex_sha(pid),
        "segment_quality_report": {"overall": 4.2},
        "segment_live_event_report": _phase_c_live_report(score),
    }


def _phase_c_ledger_row(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_ledger_version": SEGMENT_CANDIDATE_SELECTION_VERSION,
        "programme_id": artifact["programme_id"],
        "artifact_name": Path(artifact["artifact_path"]).name,
        "artifact_path": artifact["artifact_path"],
        "artifact_sha256": artifact["artifact_sha256"],
        "segment_quality_overall": artifact["segment_quality_report"]["overall"],
        "segment_live_event_score": artifact["segment_live_event_report"]["score"],
        "manifest_eligible": True,
        "prep_contract_ok": True,
        "runtime_pool_eligible": False,
        "selected_release_required": True,
    }


def _patch_selection(monkeypatch: pytest.MonkeyPatch, artifacts: list[dict[str, Any]]) -> None:
    monkeypatch.setattr(prep, "load_prepped_programmes", lambda *a, **k: list(artifacts))
    monkeypatch.setattr(
        prep, "read_candidate_ledger", lambda *a, **k: [_phase_c_ledger_row(x) for x in artifacts]
    )
    monkeypatch.setattr(
        prep,
        "assert_segment_prep_allowed",
        lambda *a, **k: SimpleNamespace(
            mode="runtime_pool_load_allowed", reason="test", source="test"
        ),
    )
    monkeypatch.setattr(
        prep,
        "publish_selected_release_feedback",
        lambda **k: {"ok": True, "publication_ok": True},
    )


def test_select_release_pool_writes_manifest_with_auto_excellence_receipts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    artifacts = [
        _phase_c_eligible_artifact("prog-a", score=96),
        _phase_c_eligible_artifact("prog-b", score=88),
    ]
    _patch_selection(monkeypatch, artifacts)

    result = prep.select_release_pool(tmp_path, selected_count=10)

    assert result["ok"] is True
    assert result["manifest_written"] is True
    today = prep._today_path(tmp_path)
    manifest_path = today / "selected-release-manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["ok"] is True
    assert manifest["selected_count"] == 2
    # Each chosen candidate records an auditable, re-checkable excellence receipt.
    receipt = manifest["selected_artifacts"][0]["excellence_receipt"]
    assert receipt["auto_derived"] is True
    assert receipt["verdict"] == "approved"
    assert receipt["criterion_vector"]["role_standard_fit"]["points"] == 10
    assert receipt["scores"]["live_event_floor"] == 82
    # require_selected=True would filter the runtime pool to exactly these hashes.
    selected_hashes = set(prep._selected_release_artifact_hashes(today).values())
    assert selected_hashes == {a["artifact_sha256"] for a in artifacts}


def test_select_release_pool_enforces_selected_count_bound(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    artifacts = [
        _phase_c_eligible_artifact("prog-a", score=96),
        _phase_c_eligible_artifact("prog-b", score=90),
        _phase_c_eligible_artifact("prog-c", score=84),
    ]
    _patch_selection(monkeypatch, artifacts)

    result = prep.select_release_pool(tmp_path, selected_count=1)

    assert result["ok"] is True
    assert result["selected_count"] == 1
    manifest = json.loads(
        (prep._today_path(tmp_path) / "selected-release-manifest.json").read_text(encoding="utf-8")
    )
    # Ranking is respected: the single slot goes to the top-scoring candidate.
    assert manifest["programmes"] == ["prog-a.json"]


def test_select_release_pool_no_eligible_pool_writes_no_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(prep, "load_prepped_programmes", lambda *a, **k: [])

    result = prep.select_release_pool(tmp_path, selected_count=10)

    # A no-candidate outcome is a successful no-release, not an error.
    assert result["ok"] is False
    assert result["reason"] == "no_eligible_pool"
    assert not (prep._today_path(tmp_path) / "selected-release-manifest.json").exists()


def _phase_c_prepped_payload(pid: str, *, authority: str = "prior_only") -> dict[str, Any]:
    sha = _phase_c_hex_sha(pid)
    return {
        "programme_id": pid,
        "role": "rant",
        "topic": "the source-backed segment topic",
        "declared_topic": "the source-backed segment topic",
        "prepared_script": ["First spoken beat grounded in the source-backed claim."],
        "segment_beats": ["beat one direction"],
        "beat_action_intents": [{"beat_index": 0, "intents": [{"kind": "source_citation"}]}],
        "beat_layout_intents": [
            {"beat_id": "beat-1", "needs": ["source_visible"], "evidence_refs": [SOURCE_REF]}
        ],
        "prepared_artifact_ref": {
            "ref": f"prepared_artifact:{sha}",
            "artifact_sha256": sha,
            "authority": authority,
            "projected_authority": authority,
        },
        "authority": authority,
        "hosting_context": "responsible_live_hosting",
        "source_refs": [SOURCE_REF],
        "evidence_refs": [SOURCE_REF],
    }


def test_bridge_activates_prior_only_and_refuses_non_prior_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    prior = _phase_c_prepped_payload("prog-prior")
    launder = _phase_c_prepped_payload("prog-launder", authority="diagnostic_only")
    monkeypatch.setattr(prep, "load_prepped_programmes", lambda *a, **k: [prior, launder])
    store = ProgrammePlanStore(path=tmp_path / "programmes.jsonl")

    result = prep.activate_selected_prepped_segment(store, prep_dir=tmp_path)

    # The bridge refuses non-prior-only content (no laundering into runtime).
    assert result["added"] == ["prog-prior"]
    assert result["activated"] == "prog-prior"
    assert result["prior_only_ok"] is False
    assert result["refused_non_prior_only"][0]["programme_id"] == "prog-launder"
    active = store.active_programme()
    assert active is not None
    assert active.programme_id == "prog-prior"
    assert active.content.authority == "prior_only"


def test_bridge_active_segment_payload_reflects_prepped_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    prior = _phase_c_prepped_payload("prog-prior")
    monkeypatch.setattr(prep, "load_prepped_programmes", lambda *a, **k: [prior])
    store = ProgrammePlanStore(path=tmp_path / "programmes.jsonl")

    prep.activate_selected_prepped_segment(store, prep_dir=tmp_path)
    active = store.active_programme()
    payload = programme_loop._active_segment_payload(active, active.role.value, 0)

    # active-segment.json reflects a prepped artifact carrying prior_only + layout needs.
    assert payload["prepared_artifact_ref"] is not None
    assert payload["authority"] == "prior_only"
    assert payload["current_beat_layout_intents"]


def test_prep_segment_refuses_when_no_sources_resolve(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Refuse-on-empty: no recruited source → a first-class no-candidate terminal,
    composition is never reached, and nothing is fabricated to fill. Open-world /
    current-event topics with no wired recruiter resolve nothing and land here too.
    """
    import agents.hapax_daimonion.angle_resolver as angle_resolver

    programme = SimpleNamespace(
        programme_id="prog-norsrc",
        role=SimpleNamespace(value="rant"),
        content=_ready_content(
            narrative_beat="An open-world claim with no recruited source",
            segment_beats=["argue the point with a source receipt"],
            role="rant",
        ),
    )
    session = {
        "prep_session_id": "segment-prep-test",
        "model_id": prep.RESIDENT_PREP_MODEL,
        "llm_calls": [],
    }
    # Nothing resolves (open-world topic / no wired recruiter).
    monkeypatch.setattr(angle_resolver, "recruit_source_set", lambda *_a, **_k: None)

    def _no_compose(*_a: Any, **_k: Any) -> str:
        raise AssertionError("composition must not run when no source resolves")

    monkeypatch.setattr(prep, "_call_llm", _no_compose)

    saved = prep.prep_segment(programme, tmp_path, prep_session=session)

    assert saved is None
    assert not (tmp_path / "prog-norsrc.json").exists()
    ledger_row = json.loads(
        (tmp_path / prep.PREP_DIAGNOSTIC_LEDGER_FILENAME).read_text(encoding="utf-8")
    )
    assert ledger_row["terminal_status"] == "no_candidate"
    assert ledger_row["terminal_reason"] == "no_resolved_sources"
    assert ledger_row["loadable"] is False


# ── recruit-before-plan + thesis-object: dominant 04:00 path ─────────────────
# segment-recruit-before-plan-thesis-20260607 — inform authorship from RESOLVED
# sources, built on main's src:N handle primitives.


def _prep_clock(*values: float):
    seq = iter(values)
    last = [0.0]

    def _now() -> float:
        try:
            last[0] = next(seq)
        except StopIteration:
            pass
        return last[0]

    return _now


def _mk_source_set(topic: str, n: int) -> ResolvedSourceSet:
    packets = tuple(
        SourcePacket(
            source_ref=f"vault:{topic}-{i}.md",
            content_hash=f"hash-{topic}-{i}",
            snippet=f"{topic} :: src {i}",
            freshness="fresh",
            source_consequence=f"without {topic}-{i}, this perspective is absent",
        )
        for i in range(n)
    )
    source_set = build_resolved_source_set(topic, packets)
    assert source_set is not None
    return source_set


def _inert_channels() -> dict[str, Any]:
    return {
        "perception": None,
        "vault_state": None,
        "profile": None,
        "density_field": None,
        "stream_biography": None,
    }


def _inert_plan_time_context(*_args: Any, **_kwargs: Any) -> tuple[dict[str, Any], list[Any]]:
    return ({"resolved_sources": [], **_inert_channels()}, [])


@pytest.fixture
def real_plan_time_context() -> bool:
    """Opt out of the hermetic patch to exercise the real plan-time executor."""
    return True


@pytest.fixture(autouse=True)
def _hermetic_plan_time_context(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep run_prep tests off the network. Plan-time recruitment hits Qdrant,
    the vault, /dev/shm, and the resident LLM; tests that target plan-time
    context request ``real_plan_time_context`` to opt out of this patch."""
    if "real_plan_time_context" in request.fixturenames:
        return
    monkeypatch.setattr(prep, "_plan_time_context", _inert_plan_time_context, raising=False)


class TestSeedTopics:
    def test_prefers_fore_understanding_then_supplements_from_vault(
        self, real_plan_time_context: bool, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(prep, "_recent_vault_topics", lambda *_a, **_k: ["live vault topic"])
        seeds = prep._candidate_seed_topics([{"topic": "evidence discipline"}], limit=5)
        assert seeds[0] == "evidence discipline"
        assert "live vault topic" in seeds

    def test_routes_around_dead_fore_understanding_via_live_vault(
        self, real_plan_time_context: bool, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(prep, "_recent_vault_topics", lambda *_a, **_k: ["live vault topic"])
        seeds = prep._candidate_seed_topics([], limit=5)
        assert seeds == ["live vault topic"]

    def test_dedupes_and_caps_the_slate(
        self, real_plan_time_context: bool, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(prep, "_recent_vault_topics", lambda *_a, **_k: [])
        fore = [{"topic": "a"}, {"topic": "a"}, {"topic": "b"}, {"topic": "c"}]
        assert prep._candidate_seed_topics(fore, limit=2) == ["a", "b"]


class TestPlanTimeContext:
    def _patch_recruit(
        self, monkeypatch: pytest.MonkeyPatch, sets: list[ResolvedSourceSet]
    ) -> None:
        monkeypatch.setattr(
            prep, "_candidate_seed_topics", lambda *_a, **_k: [s.topic for s in sets]
        )
        monkeypatch.setattr(
            "agents.hapax_daimonion.angle_resolver.recruit_source_sets",
            lambda *_a, **_k: list(sets),
        )
        monkeypatch.setattr(prep, "_gather_planner_channels", _inert_channels)

    def test_recruits_resolved_sources_for_the_planner(
        self, real_plan_time_context: bool, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sets = [_mk_source_set("dense topic", 2)]
        self._patch_recruit(monkeypatch, sets)
        kwargs, _theses = prep._plan_time_context(
            [{"topic": "x"}], llm_fn=lambda _p: "", recruit_budget_s=100.0, thesis_budget_s=100.0
        )
        assert kwargs["resolved_sources"] == sets

    def test_authors_theses_bound_to_resolved_handles(
        self, real_plan_time_context: bool, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sets = [_mk_source_set("dense topic", 2)]
        self._patch_recruit(monkeypatch, sets)
        thesis_json = (
            '{"claim":"evidence beats vibes","grounds":["src:0"],'
            '"warrant":"w","falsifier":"f","source_consequence":"s"}'
        )
        _kwargs, theses = prep._plan_time_context(
            [], llm_fn=lambda _p: thesis_json, recruit_budget_s=100.0, thesis_budget_s=100.0
        )
        assert len(theses) == 1
        assert validate_cited_handles(sets[0], theses[0].grounds)["ok"] is True

    def test_threads_live_context_channels(
        self, real_plan_time_context: bool, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_recruit(monkeypatch, [])
        monkeypatch.setattr(
            prep,
            "_gather_planner_channels",
            lambda: {**_inert_channels(), "perception": {"zone": "voice"}},
        )
        kwargs, theses = prep._plan_time_context(
            [], llm_fn=lambda _p: "", recruit_budget_s=10.0, thesis_budget_s=10.0
        )
        assert kwargs["perception"] == {"zone": "voice"}
        assert theses == []

    def test_thesis_authoring_halts_on_budget(
        self, real_plan_time_context: bool, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sets = [_mk_source_set(f"topic-{i}", 1) for i in range(3)]
        self._patch_recruit(monkeypatch, sets)
        calls: list[int] = []

        def _llm(_p: str) -> str:
            calls.append(1)
            return ""

        _kwargs, theses = prep._plan_time_context(
            [],
            llm_fn=_llm,
            recruit_budget_s=100.0,
            thesis_budget_s=50.0,
            now=_prep_clock(0.0, 0.0, 999.0),
        )
        assert len(theses) == 1
        assert len(calls) == 1


def test_run_prep_informs_planner_with_resolved_sources(
    real_plan_time_context: bool, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The dominant 04:00 path hands the planner recruited resolved sources +
    live context channels — it does not author blind on fore_understanding."""
    import agents.programme_manager.planner as planner_module

    captured: dict[str, Any] = {}
    sentinel_sets = [_mk_source_set("dense topic", 1)]

    class CapturingPlanner:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def plan(
            self, *, show_id: str, target_programmes: int | None = None, **kw: Any
        ) -> SimpleNamespace:  # noqa: ARG002
            captured.update(kw)
            return SimpleNamespace(programmes=[])

    monkeypatch.setattr(
        prep,
        "_plan_time_context",
        lambda *_a, **_k: (
            {
                "resolved_sources": sentinel_sets,
                **_inert_channels(),
                "perception": {"zone": "voice"},
            },
            [],
        ),
    )
    monkeypatch.setattr(planner_module, "ProgrammePlanner", CapturingPlanner)
    monkeypatch.setattr(prep, "MAX_SEGMENTS", 1)
    monkeypatch.setattr(
        prep,
        "_new_prep_session",
        lambda: {
            "prep_session_id": "segment-prep-wiring",
            "model_id": prep.RESIDENT_PREP_MODEL,
            "llm_calls": [],
        },
    )
    monkeypatch.setattr(prep, "_assert_resident_prep_model", lambda *_a, **_k: None)
    monkeypatch.setattr(
        prep,
        "assert_segment_prep_allowed",
        lambda _activity: SimpleNamespace(mode="open", reason="test", source="test"),
    )
    prep.run_prep(tmp_path)

    assert captured.get("resolved_sources") == sentinel_sets
    assert captured.get("perception") == {"zone": "voice"}
    assert "fore_understanding" in captured
