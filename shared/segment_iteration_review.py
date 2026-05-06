"""Deterministic gate for the one-segment iteration protocol.

The review layer consumes manifest-accepted prepared artifacts and emits a
receipt for the canary segment. It does not call models, generate content, or
grant prepared artifacts any runtime layout authority.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from shared.resident_command_r import RESIDENT_COMMAND_R_MODEL
from shared.segment_prep_consultation import (
    framework_vocabulary_hits,
    nonsterile_force_ok,
    validate_consultation_manifest,
    validate_live_event_viability,
    validate_readback_obligations,
    validate_source_consequence_map,
)
from shared.segment_quality_actionability import (
    RESPONSIBLE_HOSTING_CONTEXT,
    forbidden_layout_authority_fields,
    score_segment_quality,
    validate_layout_responsibility,
    validate_segment_actionability,
)

SEGMENT_ITERATION_REVIEW_VERSION = 1
MIN_AUTOMATED_SCRIPT_SCORE = 3.5
IDEAL_SCRIPT_SCORE_FLOORS = {
    "premise": 4,
    "tension": 4,
    "arc": 3,
    "specificity": 5,
    "pacing": 3,
    "stakes": 3,
    "callbacks": 3,
    "audience_address": 3,
    "source_fidelity": 3,
    "ending": 3,
    "actionability": 4,
    "layout_responsibility": 4,
}
REQUIRED_SOURCE_HASH_KEYS = frozenset(
    {
        "programme_sha256",
        "topic_sha256",
        "segment_beats_sha256",
        "seed_sha256",
        "prompt_sha256",
    }
)
REQUIRED_TEAM_CRITIQUE_ROLES = (
    "script_quality",
    "actionability_layout",
    "layout_responsibility",
)
REQUIRED_POSITIVE_EXCELLENCE_EVIDENCE = (
    "live_bit_viability",
    "source_consequence",
    "role_standard_fit",
    "non_anthropomorphic_force",
    "no_detector_trigger_theater",
    "framework_vocabulary_leakage",
)
PASSING_TEAM_VERDICTS = frozenset({"approved", "pass", "passed"})
MIN_CONCRETE_ACTION_KINDS = 2
ACTIONABILITY_DIVERSITY_EXCLUDED_KINDS = frozenset({"source_citation", "spoken_argument"})
MIN_TEAM_CRITIQUE_NOTE_WORDS = 6
MIN_EXCELLENCE_EVIDENCE_NOTE_WORDS = 5
FORBIDDEN_LAYOUT_LAUNDERING_TERMS = frozenset(
    {
        "camera",
        "camera_subject",
        "host_camera_or_voice_presence",
        "non_responsible_static",
        "spoken_argument_only",
        "spoken_only_fallback",
        "static",
        "default",
        "garage-door",
        "garage_door",
    }
)
EXCELLENCE_CRITERION_NAMES = frozenset(
    {
        "script.quality_floor",
        "script.ideal_livestream_bit",
        "script.source_fidelity",
        "consultation.role_standards_exemplars_counterexamples",
        "consultation.source_consequence_map",
        "consultation.live_event_viability",
        "consultation.readback_obligations",
        "script.non_anthropomorphic_force",
        "script.framework_vocabulary_not_prompt_facing",
        "actionability.visible_or_doable_counterpart",
        "actionability.claim_layout_binding",
    }
)
LOADER_ACCEPTANCE_GATE = "daily_segment_prep.load_prepped_programmes"
_LOADER_METADATA_KEYS = frozenset(
    {
        "accepted",
        "acceptance_gate",
        "artifact_path",
        "artifact_path_diagnostic",
        "prepared_artifact_ref",
        "projected_layout_contract",
        "runtime_actionability_validation",
    }
)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_json(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return _sha256_text(text)


def _artifact_hash(payload: Mapping[str, Any]) -> str:
    return _sha256_json({k: v for k, v in payload.items() if k != "artifact_sha256"})


def _criterion(
    name: str,
    passed: bool,
    detail: str,
    *,
    observed: Any | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {"name": name, "passed": bool(passed), "detail": detail}
    if observed is not None:
        out["observed"] = observed
    return out


def _is_sha256_hex(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(ch in "0123456789abcdef" for ch in value.lower())
    )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _artifact_iteration_id(artifact: Mapping[str, Any]) -> str:
    for key in ("segment_iteration_id", "iteration_id", "prep_session_id"):
        value = artifact.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _loader_metadata(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {key: candidate[key] for key in _LOADER_METADATA_KEYS if key in candidate}


def _read_raw_artifact(path_value: Any) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(path_value, str) or not path_value.strip():
        return None, "loader-accepted artifact did not expose artifact_path"
    path = Path(path_value)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, f"could not read raw artifact at {path}: {exc}"
    if not isinstance(data, dict):
        return None, f"raw artifact at {path} is not a JSON object"
    return data, None


def _separate_review_artifact(
    candidate: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], str | None]:
    """Return saved raw artifact bytes separate from loader acceptance metadata."""

    raw_artifact = candidate.get("raw_artifact")
    if isinstance(raw_artifact, Mapping):
        metadata = _loader_metadata(_mapping(candidate.get("loader_metadata")))
        metadata.update(_loader_metadata(candidate))
        return dict(raw_artifact), metadata, None

    metadata = _loader_metadata(candidate)
    if candidate.get("acceptance_gate") == LOADER_ACCEPTANCE_GATE:
        path = candidate.get("artifact_path") or candidate.get("artifact_path_diagnostic")
        raw, error = _read_raw_artifact(path)
        if raw is not None:
            return raw, metadata, None
        return dict(candidate), metadata, error

    return dict(candidate), metadata, None


def _score_floor_failures(scores: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    failures: dict[str, dict[str, Any]] = {}
    for name, floor in IDEAL_SCRIPT_SCORE_FLOORS.items():
        observed = scores.get(name)
        if not isinstance(observed, int | float) or observed < floor:
            failures[name] = {"observed": observed, "minimum": floor}
    return failures


def _source_binding_ok(
    artifact: Mapping[str, Any],
    source_hashes: Mapping[str, Any],
    llm_calls: Sequence[Any],
) -> bool:
    if set(source_hashes) != REQUIRED_SOURCE_HASH_KEYS:
        return False
    if source_hashes.get("prompt_sha256") != artifact.get("prompt_sha256"):
        return False
    if source_hashes.get("seed_sha256") != artifact.get("seed_sha256"):
        return False
    if not llm_calls:
        return False

    programme_id = artifact.get("programme_id")
    compose_prompt_seen = False
    last_call_index = 0
    for call in llm_calls:
        if not isinstance(call, Mapping):
            return False
        call_index = call.get("call_index")
        if not isinstance(call_index, int) or call_index <= last_call_index:
            return False
        last_call_index = call_index
        if call.get("programme_id") != programme_id:
            return False
        if call.get("model_id") != RESIDENT_COMMAND_R_MODEL:
            return False
        if not isinstance(call.get("phase"), str) or not call.get("phase"):
            return False
        prompt_sha256 = call.get("prompt_sha256")
        if not _is_sha256_hex(prompt_sha256):
            return False
        if call.get("phase") == "compose" and prompt_sha256 == artifact.get("prompt_sha256"):
            compose_prompt_seen = True
    return compose_prompt_seen


def _concrete_action_bindings(
    beat_action_intents: Any,
    beat_layout_intents: Any,
) -> list[dict[str, Any]]:
    if not isinstance(beat_action_intents, list) or not isinstance(beat_layout_intents, list):
        return []
    layout_by_index = {
        beat.get("beat_index"): beat
        for beat in beat_layout_intents
        if isinstance(beat, Mapping) and isinstance(beat.get("beat_index"), int)
    }
    bindings: list[dict[str, Any]] = []
    for beat in beat_action_intents:
        if not isinstance(beat, Mapping) or not isinstance(beat.get("beat_index"), int):
            continue
        beat_index = beat["beat_index"]
        layout_beat = layout_by_index.get(beat_index)
        concrete_intents = [
            intent
            for intent in beat.get("intents") or []
            if isinstance(intent, Mapping) and intent.get("kind") != "spoken_argument"
        ]
        if not concrete_intents:
            continue
        needs = layout_beat.get("needs") if isinstance(layout_beat, Mapping) else None
        evidence_refs = (
            layout_beat.get("evidence_refs") if isinstance(layout_beat, Mapping) else None
        )
        source_affordances = (
            layout_beat.get("source_affordances") if isinstance(layout_beat, Mapping) else None
        )
        bindings.append(
            {
                "beat_index": beat_index,
                "action_kinds": sorted({str(intent.get("kind")) for intent in concrete_intents}),
                "has_layout_need": isinstance(needs, list)
                and any(
                    isinstance(need, str)
                    and need not in {"unsupported_layout_need", "host_presence"}
                    for need in needs
                ),
                "has_evidence_ref": isinstance(evidence_refs, list) and bool(evidence_refs),
                "has_source_affordance": isinstance(source_affordances, list)
                and bool(source_affordances),
                "default_static_success_allowed": bool(
                    layout_beat.get("default_static_success_allowed")
                    if isinstance(layout_beat, Mapping)
                    else False
                ),
            }
        )
    return bindings


def _layout_laundering_terms(value: Any, *, path: str = "$") -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            found.extend(_layout_laundering_terms(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_layout_laundering_terms(child, path=f"{path}[{index}]"))
    elif isinstance(value, str):
        lowered = value.lower()
        for term in FORBIDDEN_LAYOUT_LAUNDERING_TERMS:
            if term in lowered:
                found.append({"path": path, "value": value, "term": term})
                break
    return found


def _positive_excellence_evidence_errors(receipt: Mapping[str, Any], index: int) -> list[str]:
    evidence = receipt.get("positive_excellence_evidence") or receipt.get("review_evidence")
    if not isinstance(evidence, Mapping):
        return [f"receipt[{index}] missing positive_excellence_evidence"]
    errors: list[str] = []
    for key in REQUIRED_POSITIVE_EXCELLENCE_EVIDENCE:
        item = evidence.get(key)
        if not isinstance(item, Mapping):
            errors.append(f"receipt[{index}] evidence {key} missing")
            continue
        if item.get("passed") is not True:
            errors.append(f"receipt[{index}] evidence {key} did not pass")
        notes = str(item.get("notes") or "").strip()
        if len(notes.split()) < MIN_EXCELLENCE_EVIDENCE_NOTE_WORDS:
            errors.append(f"receipt[{index}] evidence {key} notes are not substantive")
        refs = item.get("evidence_refs")
        if not isinstance(refs, list) or not any(isinstance(ref, str) and ref for ref in refs):
            errors.append(f"receipt[{index}] evidence {key} missing evidence_refs")
    return errors


def _detector_theater_ok(actionability: Mapping[str, Any]) -> bool:
    return actionability.get("detector_theater_lines") == []


def _forbidden_bounded_vocabulary_terms(
    artifact: Mapping[str, Any],
) -> list[dict[str, str]]:
    contract = _mapping(artifact.get("layout_decision_contract"))
    vocabulary = contract.get("bounded_vocabulary")
    if not isinstance(vocabulary, list):
        return []
    forbidden = {"camera_subject", "spoken_only_fallback"}
    return [
        {
            "path": f"$.layout_decision_contract.bounded_vocabulary[{index}]",
            "value": item,
        }
        for index, item in enumerate(vocabulary)
        if isinstance(item, str) and item in forbidden
    ]


def _prepared_layout_contract_replay(
    artifact: Mapping[str, Any],
    loader_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    forbidden_bounded_vocabulary = _forbidden_bounded_vocabulary_terms(artifact)
    if forbidden_bounded_vocabulary:
        return {
            "ok": False,
            "error": "responsible layout_decision_contract advertises forbidden bounded_vocabulary",
            "forbidden_bounded_vocabulary": forbidden_bounded_vocabulary,
        }
    try:
        from agents.hapax_daimonion.segment_layout_contract import (
            validate_prepared_segment_artifact,
        )

        contract = validate_prepared_segment_artifact(
            artifact,
            artifact_path=str(
                loader_metadata.get("artifact_path")
                or loader_metadata.get("artifact_path_diagnostic")
                or ""
            )
            or None,
            artifact_sha256=str(artifact.get("artifact_sha256") or "") or None,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    return {
        "ok": True,
        "contract": contract.model_dump(mode="json", by_alias=True),
    }


def _team_critique_loop(
    receipts: Sequence[Mapping[str, Any]] | None,
    *,
    artifact_sha256: str,
    programme_id: str,
    iteration_id: str,
) -> dict[str, Any]:
    normalized: list[dict[str, Any]] = []
    approved_roles: set[str] = set()
    malformed: list[str] = []
    blocking: list[str] = []

    for index, receipt in enumerate(receipts or ()):
        role = str(receipt.get("role") or receipt.get("gate") or "").strip()
        verdict = str(receipt.get("verdict") or receipt.get("status") or "").strip().lower()
        reviewer = str(receipt.get("reviewer") or "").strip()
        checked_at = str(receipt.get("checked_at") or "").strip()
        receipt_id = str(receipt.get("receipt_id") or receipt.get("id") or "").strip()
        notes = str(receipt.get("notes") or "").strip()
        receipt_artifact_sha256 = str(receipt.get("artifact_sha256") or "").strip()
        receipt_programme_id = str(receipt.get("programme_id") or "").strip()
        receipt_iteration_id = str(receipt.get("iteration_id") or "").strip()
        positive_excellence_evidence = receipt.get("positive_excellence_evidence") or receipt.get(
            "review_evidence"
        )
        entry = {
            "role": role,
            "verdict": verdict,
            "reviewer": reviewer,
            "checked_at": checked_at,
            "receipt_id": receipt_id,
            "artifact_sha256": receipt_artifact_sha256,
            "programme_id": receipt_programme_id,
            "iteration_id": receipt_iteration_id,
            "notes": notes,
            "positive_excellence_evidence": positive_excellence_evidence
            if isinstance(positive_excellence_evidence, Mapping)
            else {},
        }
        normalized.append(entry)

        missing = [
            key
            for key, value in {
                "role": role,
                "verdict": verdict,
                "reviewer": reviewer,
                "checked_at": checked_at,
                "receipt_id": receipt_id,
                "artifact_sha256": receipt_artifact_sha256,
                "programme_id": receipt_programme_id,
                "iteration_id": receipt_iteration_id,
                "notes": notes,
            }.items()
            if not value
        ]
        if missing:
            malformed.append(f"receipt[{index}] missing {','.join(missing)}")
            continue
        if receipt_artifact_sha256 != artifact_sha256:
            malformed.append(f"receipt[{index}] artifact_sha256 does not match canary artifact")
            continue
        if receipt_programme_id != programme_id:
            malformed.append(f"receipt[{index}] programme_id does not match canary artifact")
            continue
        if receipt_iteration_id != iteration_id:
            malformed.append(f"receipt[{index}] iteration_id does not match canary iteration")
            continue
        if len(notes.split()) < MIN_TEAM_CRITIQUE_NOTE_WORDS:
            malformed.append(f"receipt[{index}] notes are not substantive")
            continue
        evidence_errors = _positive_excellence_evidence_errors(receipt, index)
        if evidence_errors:
            malformed.extend(evidence_errors)
            continue
        if role not in REQUIRED_TEAM_CRITIQUE_ROLES:
            malformed.append(f"receipt[{index}] has unsupported role {role!r}")
            continue
        if verdict in PASSING_TEAM_VERDICTS:
            approved_roles.add(role)
        else:
            blocking.append(role)

    pending_roles = [role for role in REQUIRED_TEAM_CRITIQUE_ROLES if role not in approved_roles]
    return {
        "required_roles": list(REQUIRED_TEAM_CRITIQUE_ROLES),
        "receipts": normalized,
        "pending_roles": pending_roles,
        "malformed_receipts": malformed,
        "blocking_roles": sorted(set(blocking)),
        "passed": not pending_roles and not malformed and not blocking,
        "instructions": [
            "Review the single canary artifact before any next-nine generation.",
            "Each reviewer records a receipt with role, verdict, reviewer, checked_at, receipt_id, artifact_sha256, programme_id, iteration_id, and substantive notes.",
            "Approvals must cover script quality, actionability/layout fit, and layout-responsibility doctrine.",
            "Approvals must include bound positive-excellence evidence for live bit viability, source consequence, role-standard fit, personage honesty, detector-theater absence, and framework-vocabulary leakage.",
            "Any revise/block verdict sends the method back to one-segment iteration.",
        ],
    }


def review_one_segment_iteration(
    accepted_artifacts: Sequence[Mapping[str, Any]],
    *,
    team_critique_receipts: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Review the canary set and return a receipt for the next-nine gate."""

    criteria = [
        _criterion(
            "artifact.exactly_one_manifest_accepted",
            len(accepted_artifacts) == 1,
            "one-segment canary must expose exactly one manifest-accepted artifact",
            observed={"accepted_artifact_count": len(accepted_artifacts)},
        )
    ]
    if len(accepted_artifacts) != 1:
        team = _team_critique_loop(
            team_critique_receipts,
            artifact_sha256="",
            programme_id="",
            iteration_id="",
        )
        return _receipt(
            artifact={},
            loader_metadata={},
            accepted_artifact_count=len(accepted_artifacts),
            criteria=criteria,
            quality_report={},
            actionability_report={},
            layout_report={},
            team_critique_loop=team,
        )

    artifact, loader_metadata, separation_error = _separate_review_artifact(accepted_artifacts[0])
    criteria.append(
        _criterion(
            "artifact.raw_loader_separation",
            separation_error is None,
            "review must hash/check the saved raw artifact separately from loader enrichment",
            observed={
                "loader_acceptance_gate": loader_metadata.get("acceptance_gate"),
                "artifact_path": loader_metadata.get("artifact_path")
                or loader_metadata.get("artifact_path_diagnostic"),
                "error": separation_error,
            },
        )
    )
    artifact_criteria, quality, actionability, layout = _review_artifact(
        artifact,
        loader_metadata=loader_metadata,
    )
    criteria.extend(artifact_criteria)
    team = _team_critique_loop(
        team_critique_receipts,
        artifact_sha256=str(artifact.get("artifact_sha256") or ""),
        programme_id=str(artifact.get("programme_id") or ""),
        iteration_id=_artifact_iteration_id(artifact),
    )
    return _receipt(
        artifact=artifact,
        loader_metadata=loader_metadata,
        accepted_artifact_count=1,
        criteria=criteria,
        quality_report=quality,
        actionability_report=actionability,
        layout_report=layout,
        team_critique_loop=team,
    )


def _review_artifact(
    artifact: Mapping[str, Any],
    *,
    loader_metadata: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any]]:
    script = _string_list(artifact.get("prepared_script"))
    beats = _string_list(artifact.get("segment_beats"))
    quality = score_segment_quality(script, beats) if script else {}
    actionability = validate_segment_actionability(script, beats) if script else {}
    beat_action_intents = actionability.get("beat_action_intents") if actionability else []
    layout = (
        validate_layout_responsibility(beat_action_intents)
        if isinstance(beat_action_intents, list)
        else {}
    )
    runtime_layout_validation = _mapping(artifact.get("runtime_layout_validation"))
    layout_contract = _mapping(artifact.get("layout_decision_contract"))
    actionability_alignment = _mapping(artifact.get("actionability_alignment"))
    source_hashes = _mapping(artifact.get("source_hashes"))
    hard_contract_replay = _prepared_layout_contract_replay(artifact, loader_metadata)
    raw_llm_calls = artifact.get("llm_calls")
    llm_calls: list[Any] = raw_llm_calls if isinstance(raw_llm_calls, list) else []
    forbidden_layout_fields = forbidden_layout_authority_fields(dict(artifact))
    layout_laundering_terms = _layout_laundering_terms(
        {
            "beat_layout_intents": artifact.get("beat_layout_intents"),
            "layout_decision_contract": artifact.get("layout_decision_contract"),
            "runtime_layout_validation": artifact.get("runtime_layout_validation"),
            "layout_decision_receipts": artifact.get("layout_decision_receipts"),
        }
    )
    concrete_action_kinds = sorted(
        {
            str(intent.get("kind"))
            for beat in beat_action_intents or []
            for intent in (beat.get("intents") or [])
            if isinstance(intent, Mapping)
            and str(intent.get("kind")) not in ACTIONABILITY_DIVERSITY_EXCLUDED_KINDS
        }
    )
    expected_artifact_hash = artifact.get("artifact_sha256")
    expected_source_hash = artifact.get("source_provenance_sha256")
    recomputed_action_intents = actionability.get("beat_action_intents") if actionability else None
    recomputed_layout_intents = layout.get("beat_layout_intents") if layout else None
    concrete_action_bindings = _concrete_action_bindings(
        recomputed_action_intents,
        recomputed_layout_intents,
    )
    score_failures = _score_floor_failures(_mapping(quality.get("scores")) if quality else {})
    consultation_manifest = validate_consultation_manifest(
        artifact.get("consultation_manifest"),
        role=str(artifact.get("role") or ""),
    )
    source_consequence = validate_source_consequence_map(artifact.get("source_consequence_map"))
    live_event_viability = validate_live_event_viability(artifact.get("live_event_viability"))
    readback_obligations = validate_readback_obligations(artifact.get("readback_obligations"))
    framework_hits = framework_vocabulary_hits(" ".join(script))
    nonsterile_force = nonsterile_force_ok(
        script,
        personage_violations=actionability.get("personage_violations") or [],
    )

    criteria = [
        _criterion(
            "artifact.command_r_model",
            artifact.get("model_id") == RESIDENT_COMMAND_R_MODEL
            and all(
                isinstance(call, Mapping) and call.get("model_id") == RESIDENT_COMMAND_R_MODEL
                for call in llm_calls
            ),
            "prepared artifact and all LLM call receipts must use resident Command-R",
            observed={
                "model_id": artifact.get("model_id"),
                "llm_call_count": len(llm_calls),
            },
        ),
        _criterion(
            "artifact.prior_only_authority",
            artifact.get("authority") == "prior_only",
            "prepared artifact must remain prior-only content",
            observed=artifact.get("authority"),
        ),
        _criterion(
            "artifact.hash_receipt",
            _is_sha256_hex(expected_artifact_hash)
            and expected_artifact_hash == _artifact_hash(artifact),
            "artifact_sha256 must match the artifact bytes excluding artifact_sha256",
            observed=expected_artifact_hash,
        ),
        _criterion(
            "artifact.source_provenance_receipt",
            _is_sha256_hex(expected_source_hash)
            and bool(source_hashes)
            and expected_source_hash == _sha256_json(source_hashes),
            "source_provenance_sha256 must match source_hashes",
            observed=expected_source_hash,
        ),
        _criterion(
            "artifact.prior_source_binding",
            _source_binding_ok(artifact, source_hashes, llm_calls),
            "source hashes, prompt hash, seed hash, and LLM call receipts must bind to the same prior",
            observed={
                "source_hash_keys": sorted(source_hashes),
                "prompt_sha256": artifact.get("prompt_sha256"),
                "seed_sha256": artifact.get("seed_sha256"),
                "llm_call_count": len(llm_calls),
            },
        ),
        _criterion(
            "layout.hard_contract_replay",
            hard_contract_replay.get("ok") is True,
            "review must replay the prepared segment layout contract gates before next-nine release",
            observed={
                "error": hard_contract_replay.get("error"),
                "forbidden_bounded_vocabulary": hard_contract_replay.get(
                    "forbidden_bounded_vocabulary"
                ),
                "bounded_vocabulary": _mapping(
                    _mapping(hard_contract_replay.get("contract")).get("layout_decision_contract")
                ).get("bounded_vocabulary"),
            },
        ),
        _criterion(
            "script.shape",
            bool(script) and bool(beats) and len(script) == len(beats),
            "prepared_script must be present and align one-to-one with segment_beats",
            observed={"script_beats": len(script), "segment_beats": len(beats)},
        ),
        _criterion(
            "script.quality_floor",
            bool(quality)
            and float(quality.get("overall") or 0) >= MIN_AUTOMATED_SCRIPT_SCORE
            and quality.get("label") != "generic"
            and _mapping(quality.get("diagnostics")).get("thin_beats") == 0,
            "script must clear the automated quality floor; team critique decides excellence",
            observed={
                "overall": quality.get("overall"),
                "label": quality.get("label"),
                "thin_beats": _mapping(quality.get("diagnostics")).get("thin_beats"),
            },
        ),
        _criterion(
            "script.ideal_livestream_bit",
            bool(quality) and not score_failures,
            "canary script must clear per-dimension floors for a compelling livestream bit",
            observed={
                "score_failures": score_failures,
                "scores": quality.get("scores"),
            },
        ),
        _criterion(
            "script.source_fidelity",
            bool(quality)
            and _mapping(quality.get("scores")).get("source_fidelity", 0)
            >= IDEAL_SCRIPT_SCORE_FLOORS["source_fidelity"],
            "sources must appear as grounded arguments, not decorative name drops",
            observed={
                "source_fidelity": _mapping(quality.get("scores")).get("source_fidelity")
                if quality
                else None,
                "proper_noun_count": _mapping(quality.get("diagnostics")).get("proper_noun_count")
                if quality
                else None,
            },
        ),
        _criterion(
            "consultation.role_standards_exemplars_counterexamples",
            consultation_manifest.get("ok") is True,
            "artifact must bind advisory role standards, exemplars, counterexamples, and quality ranges without granting authority",
            observed=consultation_manifest,
        ),
        _criterion(
            "consultation.source_consequence_map",
            source_consequence.get("ok") is True,
            "sources must change claim, ranking, scope, action, or visible/doable obligation rather than decorate prose",
            observed=source_consequence,
        ),
        _criterion(
            "consultation.live_event_viability",
            live_event_viability.get("ok") is True,
            "canary must carry a reviewable live-event viability plan, not only a loadable script",
            observed=live_event_viability,
        ),
        _criterion(
            "consultation.readback_obligations",
            readback_obligations.get("ok") is True,
            "prepared action/layout claims must specify runtime readback obligations without claiming success",
            observed=readback_obligations,
        ),
        _criterion(
            "script.non_anthropomorphic_force",
            nonsterile_force.get("ok") is True,
            "script must be forceful and source-bound without fake human feeling, taste, memory, empathy, or inner life",
            observed=nonsterile_force,
        ),
        _criterion(
            "script.framework_vocabulary_not_prompt_facing",
            not framework_hits,
            "review framework vocabulary must not leak into prepared spoken prose",
            observed={"hits": framework_hits},
        ),
        _criterion(
            "actionability.supported",
            actionability.get("ok") is True
            and actionability_alignment.get("ok") is True
            and actionability.get("removed_unsupported_action_lines") == [],
            "script must not contain unsupported action claims",
            observed={
                "removed": actionability.get("removed_unsupported_action_lines"),
                "artifact_alignment": actionability_alignment,
            },
        ),
        _criterion(
            "actionability.personage_honesty",
            actionability.get("personage_violations") == [],
            "prepared script must not claim human feeling, empathy, taste, intuition, memory, concern, or Hapax inner life",
            observed=actionability.get("personage_violations"),
        ),
        _criterion(
            "actionability.no_detector_trigger_theater",
            _detector_theater_ok(actionability),
            "detector/readback language must not become dramatic proof or runtime authority without payload-bound receipts",
            observed=actionability.get("detector_theater_lines"),
        ),
        _criterion(
            "actionability.visible_or_doable_counterpart",
            len(concrete_action_kinds) >= MIN_CONCRETE_ACTION_KINDS,
            "the canary must contain multiple visible or doable supported action intents",
            observed={"concrete_action_kinds": concrete_action_kinds},
        ),
        _criterion(
            "actionability.claim_layout_binding",
            bool(concrete_action_bindings)
            and all(
                binding["has_layout_need"]
                and binding["has_evidence_ref"]
                and binding["has_source_affordance"]
                and not binding["default_static_success_allowed"]
                for binding in concrete_action_bindings
            ),
            "every concrete spoken claim must bind to a layout need, source affordance, and evidence ref",
            observed={"bindings": concrete_action_bindings},
        ),
        _criterion(
            "actionability.receipt_freshness",
            artifact.get("beat_action_intents") == recomputed_action_intents,
            "stored beat_action_intents must match deterministic recomputation",
        ),
        _criterion(
            "layout.responsible_proposal_only",
            layout.get("ok") is True
            and artifact.get("hosting_context") == RESPONSIBLE_HOSTING_CONTEXT
            and layout_contract.get("may_command_layout") is False
            and layout_contract.get("default_static_success_allowed") is False
            and runtime_layout_validation.get("status") == "pending_runtime_readback"
            and runtime_layout_validation.get("layout_success") is False
            and artifact.get("layout_decision_receipts") == [],
            "prepared layout metadata must stay responsible, proposal-only, and pending readback",
            observed={
                "hosting_context": artifact.get("hosting_context"),
                "layout_success": runtime_layout_validation.get("layout_success"),
                "receipt_count": len(artifact.get("layout_decision_receipts") or []),
            },
        ),
        _criterion(
            "layout.intent_receipt_freshness",
            artifact.get("beat_layout_intents") == recomputed_layout_intents,
            "stored beat_layout_intents must match deterministic recomputation",
        ),
        _criterion(
            "layout.no_prepared_authority",
            not forbidden_layout_fields,
            "prepared artifact must not carry concrete layout authority, static-default success, or cues",
            observed=forbidden_layout_fields,
        ),
        _criterion(
            "layout.no_static_camera_spoken_laundering",
            not layout_laundering_terms,
            "prepared layout metadata must not launder static default, camera, or spoken-only fallback as responsible success",
            observed=layout_laundering_terms,
        ),
    ]
    return criteria, quality, actionability, layout


def _receipt(
    *,
    artifact: Mapping[str, Any],
    loader_metadata: Mapping[str, Any],
    accepted_artifact_count: int,
    criteria: list[dict[str, Any]],
    quality_report: dict[str, Any],
    actionability_report: dict[str, Any],
    layout_report: dict[str, Any],
    team_critique_loop: dict[str, Any],
) -> dict[str, Any]:
    eligibility_criteria = [
        item for item in criteria if item.get("name") not in EXCELLENCE_CRITERION_NAMES
    ]
    excellence_criteria = [
        item for item in criteria if item.get("name") in EXCELLENCE_CRITERION_NAMES
    ]
    eligibility_passed = all(item["passed"] for item in eligibility_criteria)
    excellence_automation_passed = all(item["passed"] for item in excellence_criteria)
    automation_passed = eligibility_passed and excellence_automation_passed
    team_passed = bool(team_critique_loop.get("passed"))
    ready_for_next_nine = eligibility_passed and excellence_automation_passed and team_passed
    decision = (
        "ready_for_next_nine"
        if ready_for_next_nine
        else "team_critique_required"
        if automation_passed
        else "revise_canary_artifact"
    )
    body = {
        "segment_iteration_review_version": SEGMENT_ITERATION_REVIEW_VERSION,
        "programme_id": artifact.get("programme_id"),
        "artifact_sha256": artifact.get("artifact_sha256"),
        "iteration_id": _artifact_iteration_id(artifact),
        "artifact_path": loader_metadata.get("artifact_path")
        or loader_metadata.get("artifact_path_diagnostic")
        or artifact.get("artifact_path")
        or artifact.get("artifact_path_diagnostic"),
        "artifact_extraction": {
            "accepted_artifact_count": accepted_artifact_count,
            "manifest_gate": accepted_artifact_count == 1,
            "loader_acceptance_gate": loader_metadata.get("acceptance_gate"),
            "raw_loader_separation": any(
                item["name"] == "artifact.raw_loader_separation" and item["passed"]
                for item in criteria
            )
            or not loader_metadata,
        },
        "automated_gate": {
            "passed": automation_passed,
            "minimum_script_score": MIN_AUTOMATED_SCRIPT_SCORE,
            "criteria": criteria,
        },
        "eligibility_gate": {
            "passed": eligibility_passed,
            "criteria": eligibility_criteria,
            "meaning": (
                "safety, model, provenance, source-binding, layout-authority, and "
                "personage hard gates passed; this is not excellence approval"
            ),
        },
        "excellence_selection": {
            "passed": excellence_automation_passed and team_passed,
            "automation_passed": excellence_automation_passed,
            "team_passed": team_passed,
            "criteria": excellence_criteria,
            "required_positive_excellence_evidence": list(REQUIRED_POSITIVE_EXCELLENCE_EVIDENCE),
            "meaning": (
                "canary release requires live-bit viability, source consequence, "
                "role-standard calibration, non-anthropomorphic force, detector-theater "
                "rejection, framework-vocabulary hygiene, and bound team evidence"
            ),
        },
        "script_quality": quality_report,
        "actionability": {
            "ok": actionability_report.get("ok"),
            "beat_action_intents": actionability_report.get("beat_action_intents"),
            "removed_unsupported_action_lines": actionability_report.get(
                "removed_unsupported_action_lines"
            ),
        },
        "layout_responsibility": {
            "ok": layout_report.get("ok"),
            "hosting_context": layout_report.get("hosting_context"),
            "beat_layout_intents": layout_report.get("beat_layout_intents"),
            "runtime_layout_validation": layout_report.get("runtime_layout_validation"),
            "layout_decision_contract": layout_report.get("layout_decision_contract"),
        },
        "team_critique_loop": team_critique_loop,
        "ready_for_next_nine": ready_for_next_nine,
        "next_nine_gate_mode": "blocking_review_receipt",
        "decision": decision,
        "resident_model_continuity": {
            "expected_model": RESIDENT_COMMAND_R_MODEL,
            "no_qwen": True,
            "no_unload_or_swap": True,
        },
    }
    body["review_receipt_sha256"] = _sha256_json(body)
    return body
