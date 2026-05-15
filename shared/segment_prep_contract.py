"""Explicit source/action contract for prepared livestream segments.

The prep contract is the artifact-level counterpart to the spoken script. It
records what the segment is trying to prove, which sources alter the claims,
what should become visible/doable, and what runtime must read back later.
Deterministic script/layout detectors may replay this contract, but they do not
replace it.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from shared.loop_card import LoopAdmissibility, validate_loop_cards

SEGMENT_PREP_CONTRACT_VERSION = 1
SEGMENT_PREP_OUTCOME_VERSION = 1
SEGMENT_PREP_DIAGNOSTIC_AUTHORITY = "diagnostic_only"
SELECTED_RELEASE_MANIFEST = "selected-release-manifest.json"
CANDIDATE_LEDGER = "candidate-ledger.jsonl"

SEGMENT_PREP_OUTCOME_TYPES = frozenset(
    {"no_candidate", "no_release", "refusal", "refusal_brief_candidate"}
)
SEGMENT_PREP_OUTCOME_FORBIDDEN_FIELDS = frozenset(
    {
        "artifact_sha256",
        "prepared_script",
        "prepared_script_candidate",
        "programmes",
        "qdrant_upserted",
        "rag_digest_path",
        "selected_artifacts",
        "selected_release_manifest",
        "selected_release_manifest_sha256",
        "selected_release_publication",
    }
)
PREPARED_SCRIPT_BINDING_VERSION = 1
PREPARED_SCRIPT_BINDING_SCOPE = "post_refinement_final_prepared_script"

_INTERNAL_EVIDENCE_REF_RE = re.compile(r"^beat_action_intents\[\d+\]\.intents\[\d+\]$")
_GENERIC_SOURCE_RE = re.compile(
    r"\b(?:source|evidence|receipt|packet|proof|reference|citation)\b", re.IGNORECASE
)
_FRAMEWORK_LEAK_RE = re.compile(
    r"\b(?:"
    r"non[- ]human personage contract|runtime readback doctrine|"
    r"quality[- ]budget principle|source consequence contract|"
    r"layout responsibility doctrine|proposal[- ]only layout|"
    r"segment prep framework|loadability gate|pool release|"
    r"quarantine gate|validator compliance"
    r")\b",
    re.IGNORECASE,
)
_SCRIPTLIKE_BEAT_RE = re.compile(
    r"\b(?:"
    r"welcome(?: to)?|we(?:'ll|'d| will| would| are| have| ranked)|let'?s|let us|"
    r"next up|moving on|there you have it|feel free|share your thoughts|"
    r"we(?:'d| would) love|our (?:first|next|journey|viewers|audience|topic|ranking)|"
    r"thanks for|thank you for"
    r")\b",
    re.IGNORECASE,
)
_GENERIC_STAGE_BEAT_RE = re.compile(
    r"^\s*(?:hook|opening|intro|motivat(?:e|ion)|fram(?:e|ing)|"
    r"main(?:[_ -]?points?|[_ -]?point(?:[_ -]*\d*)?)|body|synthesi[sz]e?|"
    r"questions?|recap|closing|close)\s*:",
    re.IGNORECASE,
)
_TEMPLATE_LEAK_RE = re.compile(
    r"(?:"
    r"\b(?:source candidates from vault \+ rag|source from vault \+ rag|"
    r"rank against operator positions|narrate placements|narrate the climb|"
    r"ground in operator positions from profile-facts|resolve via content-resolver|"
    r"surface from rag|descend through vault notes|outline from operator vault notes|"
    r"warm-then-deep question arc)\b"
    r"|"
    r"\bitem_\d+:"
    r"|"
    r"\{(?:topic|item|hook|close|body|subject|source|beat|segment|title|name|"
    r"item_\d+|beat_\d+|criteria|ranking|tier|description|argument|claim)\}"
    r")",
    re.IGNORECASE,
)
_CURRENT_RANKING_RE = re.compile(
    r"\b(?:best|top|latest|current|recent|leading|ranking|ranked|tier[- ]list)\b",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"\b(20\d{2})\b")


def is_internal_evidence_ref(value: Any) -> bool:
    return isinstance(value, str) and bool(_INTERNAL_EVIDENCE_REF_RE.fullmatch(value.strip()))


def validate_segment_prep_outcome(payload: Mapping[str, Any]) -> list[str]:
    """Validate a diagnostic-only prep outcome dossier.

    Outcome dossiers explain why a prep pass produced no loadable candidate.
    They are explicitly not artifacts and must not be manifest- or runtime-load
    eligible.
    """
    failures: list[str] = []
    if payload.get("segment_prep_outcome_version") != SEGMENT_PREP_OUTCOME_VERSION:
        failures.append("unsupported_outcome_version")
    if payload.get("outcome_type") not in SEGMENT_PREP_OUTCOME_TYPES:
        failures.append("unsupported_outcome_type")
    if payload.get("authority") != SEGMENT_PREP_DIAGNOSTIC_AUTHORITY:
        failures.append("outcome_not_diagnostic_only")
    for field in sorted(SEGMENT_PREP_OUTCOME_FORBIDDEN_FIELDS):
        if field in payload:
            failures.append(f"forbidden_outcome_field:{field}")
    boundary = payload.get("release_boundary")
    if not isinstance(boundary, Mapping):
        failures.append("missing_release_boundary")
    else:
        for field in ("listed_in_manifest", "selected_release_eligible", "runtime_pool_eligible"):
            if boundary.get(field) is not False:
                failures.append(f"release_boundary_not_closed:{field}")
    if not payload.get("prep_session_id"):
        failures.append("missing_prep_session_id")
    if not payload.get("reason_code"):
        failures.append("missing_reason_code")
    return failures


# ---------------------------------------------------------------------------
# Enriched outcome dossier fields
# ---------------------------------------------------------------------------

_ENRICHED_COMMON_FIELDS = (
    "investigated_leads",
    "source_gaps",
    "confidence_per_gap",
    "budget_spent",
    "budget_remaining",
    "authority_ceiling_reached",
    "falsification_criterion",
)

_ENRICHED_NO_RELEASE_FIELDS = (
    "review_gap_details",
    "script_contract_state",
    "return_to_prep_eligible",
    "return_to_prep_bounded_action",
)

_ENRICHED_REFUSAL_FIELDS = (
    "refusal_source_gaps",
    "operator_re_aim_affordance",
)

_OUTCOME_ENRICHMENT_MAP: dict[str, tuple[tuple[str, ...], ...]] = {
    "no_candidate": (_ENRICHED_COMMON_FIELDS,),
    "no_release": (_ENRICHED_COMMON_FIELDS, _ENRICHED_NO_RELEASE_FIELDS),
    "refusal": (_ENRICHED_REFUSAL_FIELDS,),
    "refusal_brief_candidate": (_ENRICHED_REFUSAL_FIELDS,),
}


def _is_nonempty_list(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) > 0


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float)


def _source_gap_valid(gap: Any) -> bool:
    if not isinstance(gap, Mapping):
        return False
    return all(_is_nonempty_string(gap.get(field)) for field in ("gap_id", "description"))


def _review_gap_detail_valid(detail: Any) -> bool:
    if not isinstance(detail, Mapping):
        return False
    return all(
        _is_nonempty_string(detail.get(field))
        for field in ("gap_id", "reviewer", "notes", "severity")
    )


def _refusal_source_gap_valid(gap: Any) -> bool:
    if not isinstance(gap, Mapping):
        return False
    return all(_is_nonempty_string(gap.get(field)) for field in ("gap_id", "why_refusal_warranted"))


def validate_enriched_outcome(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Check enriched dossier fields on an outcome payload.

    Returns ``{"ok": bool, "thin_fields": [...]}`` where *thin_fields* lists
    enrichment fields that are missing or structurally inadequate for the
    given ``outcome_type``.
    """
    outcome_type = str(payload.get("outcome_type") or "")
    field_groups = _OUTCOME_ENRICHMENT_MAP.get(outcome_type)
    if field_groups is None:
        return {"ok": False, "thin_fields": ["outcome_type"]}

    thin: list[str] = []

    for group in field_groups:
        for field in group:
            value = payload.get(field)

            # --- common fields ---
            if field == "investigated_leads":
                if not _is_nonempty_list(value):
                    thin.append(field)
            elif field == "source_gaps":
                if not _is_nonempty_list(value) or not all(_source_gap_valid(gap) for gap in value):
                    thin.append(field)
            elif field == "confidence_per_gap":
                if (
                    not isinstance(value, Mapping)
                    or not value
                    or not all(isinstance(v, int | float) for v in value.values())
                ):
                    thin.append(field)
            elif field in ("budget_spent", "budget_remaining"):
                if not _is_number(value):
                    thin.append(field)
            elif field in ("authority_ceiling_reached", "falsification_criterion"):
                if not _is_nonempty_string(value):
                    thin.append(field)

            # --- no_release extras ---
            elif field == "review_gap_details":
                if not _is_nonempty_list(value) or not all(
                    _review_gap_detail_valid(d) for d in value
                ):
                    thin.append(field)
            elif field == "script_contract_state":
                if not _is_nonempty_string(value):
                    thin.append(field)
            elif field == "return_to_prep_eligible":
                if not isinstance(value, bool):
                    thin.append(field)
            elif field == "return_to_prep_bounded_action":
                # None is acceptable when return_to_prep_eligible is False
                if payload.get("return_to_prep_eligible") is True and not _is_nonempty_string(
                    value
                ):
                    thin.append(field)

            # --- refusal extras ---
            elif field == "refusal_source_gaps":
                if not _is_nonempty_list(value) or not all(
                    _refusal_source_gap_valid(gap) for gap in value
                ):
                    thin.append(field)
            elif field == "operator_re_aim_affordance":
                if not _is_nonempty_string(value):
                    thin.append(field)

    return {"ok": not thin, "thin_fields": thin}


_RETURN_TO_PREP_REQUIRED_FIELDS = (
    "identified_gap",
    "bounded_work_item",
    "budget_authority",
    "expected_observable",
    "falsification_criterion",
)


def validate_return_to_prep(dossier: Mapping[str, Any]) -> dict[str, Any]:
    """Validate that a return-to-prep request has a bounded dossier.

    Failed review, no_release, runtime fallback, or readback mismatch
    may return to prep ONLY when the dossier identifies:
    1. Exact source/script/contract/review/personage/runtime-readback gap
    2. Bounded work item closing it
    3. Budget and egress authority for work
    4. Expected observable change
    5. Falsification criterion

    Without these, the correct result is terminal diagnostic outcome.
    """
    missing: list[str] = []
    for field in _RETURN_TO_PREP_REQUIRED_FIELDS:
        if not _is_nonempty_string(dossier.get(field)):
            missing.append(field)
    return {
        "ok": not missing,
        "missing_fields": missing,
        "terminal_recommended": len(missing) > 0,
    }


def is_content_evidence_ref(value: Any) -> bool:
    """Return whether a ref looks like content/source evidence, not parser provenance."""
    if not isinstance(value, str):
        return False
    ref = value.strip()
    if not ref or is_internal_evidence_ref(ref):
        return False
    lowered = ref.lower()
    if lowered in {"source", "evidence", "receipt", "proof", "packet"}:
        return False
    if lowered.startswith(
        (
            "vault:",
            "rag:",
            "source:",
            "packet:",
            "claim:",
            "object:",
            "action:",
            "receipt:",
            "profile:",
            "resolver:",
            "media:",
            "prepared_artifact:",
            "content:",
            "standard:",
        )
    ):
        return True
    return ":" in ref and len(ref) >= 8 and not _GENERIC_SOURCE_RE.fullmatch(ref)


def is_source_evidence_ref(value: Any) -> bool:
    """Return whether a ref names an external/source packet, not derived prep state."""
    if not is_content_evidence_ref(value):
        return False
    ref = str(value).strip().lower()
    if ref.startswith(("action:", "object:", "claim:", "prepared_artifact:", "standard:")):
        return False
    return ref.startswith(
        (
            "vault:",
            "rag:",
            "source:",
            "packet:",
            "receipt:",
            "profile:",
            "resolver:",
            "media:",
            "content:",
        )
    )


def framework_vocabulary_leaks(texts: Sequence[str]) -> list[dict[str, Any]]:
    leaks: list[dict[str, Any]] = []
    for beat_index, text in enumerate(texts):
        for match in _FRAMEWORK_LEAK_RE.finditer(text):
            leaks.append({"beat_index": beat_index, "matched_text": match.group(0)})
    return leaks


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, Sequence):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out


def _mapping_list(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _mapping_text(value: Mapping[str, Any] | None) -> str:
    if not isinstance(value, Mapping):
        return ""
    chunks: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, str):
            chunks.append(item)
        elif isinstance(item, Mapping):
            for nested in item.values():
                visit(nested)
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
            for nested in item:
                visit(nested)

    visit(value)
    return " ".join(chunks)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_json(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return _sha256_text(text)


def _is_sha256_hex(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(ch in "0123456789abcdef" for ch in value.lower())
    )


def prepared_script_sha256(script: Sequence[str]) -> str:
    """Hash the exact final prepared_script sequence used by the artifact."""

    return _sha256_json([str(item) for item in script])


def _prepared_script_binding(
    *,
    script: Sequence[str],
    segment_beats: Sequence[str],
) -> dict[str, Any]:
    return {
        "binding_version": PREPARED_SCRIPT_BINDING_VERSION,
        "binding_scope": PREPARED_SCRIPT_BINDING_SCOPE,
        "hash_method": "sha256_json_utf8",
        "prepared_script_sha256": prepared_script_sha256(script),
        "script_beat_count": len(script),
        "segment_beats_sha256": _sha256_json([str(item) for item in segment_beats]),
        "segment_beat_count": len(segment_beats),
    }


def _content_refs_from_mapping(value: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(value, Mapping):
        return []
    refs: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            for key, nested in item.items():
                key_token = str(key)
                if key_token in {
                    "evidence_ref",
                    "evidence_refs",
                    "source_ref",
                    "source_refs",
                    "source_packet_refs",
                    "source_packet_ref",
                    "prepared_artifact_ref",
                }:
                    refs.extend(_string_list(nested))
                visit(nested)
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
            for nested in item:
                visit(nested)

    visit(value)
    return _dedupe([ref for ref in refs if is_content_evidence_ref(ref)])


def _dedupe(values: Sequence[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            out.append(value)
            seen.add(value)
    return out


def _slug(value: str) -> str:
    token = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if token:
        return token[:80]
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _entry_beat_index(entry: Mapping[str, Any], fallback_index: int, beat_count: int) -> int:
    """Resolve model-emitted beat indexes, accepting either 0- or 1-based values."""

    raw = entry.get("beat_index")
    if raw is None:
        raw = entry.get("beat_number")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = fallback_index
    if beat_count <= 0:
        return max(value, 0)
    if 0 <= value < beat_count:
        return value
    if 1 <= value <= beat_count:
        return value - 1
    return max(0, min(fallback_index, beat_count - 1))


def _beat_id_for_entry(
    entry: Mapping[str, Any],
    fallback_index: int,
    beat_ids: Sequence[str],
) -> str:
    beat_id = str(entry.get("beat_id") or "").strip()
    if beat_id:
        return beat_id
    beat_index = _entry_beat_index(entry, fallback_index, len(beat_ids))
    if 0 <= beat_index < len(beat_ids):
        return beat_ids[beat_index]
    return f"beat-{beat_index + 1}"


def _entry_refs(entry: Mapping[str, Any], *fields: str) -> list[str]:
    refs: list[str] = []
    for field in fields:
        refs.extend(_string_list(entry.get(field)))
    return _dedupe([ref for ref in refs if is_content_evidence_ref(ref)])


def _first_non_empty_text(entry: Mapping[str, Any], *fields: str) -> str:
    for field in fields:
        value = entry.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            joined = "; ".join(str(item).strip() for item in value if str(item).strip())
            if joined:
                return joined
    return ""


def _content_refs_from_programme(programme: Any) -> list[str]:
    content = getattr(programme, "content", None)
    if content is None:
        return []
    refs: list[str] = []
    for field in ("beat_layout_intents", "beat_action_intents", "beat_cards", "live_priors"):
        for entry in _mapping_list(getattr(content, field, None)):
            refs.extend(_string_list(entry.get("evidence_refs") or entry.get("evidence_ref")))
            if field in {"beat_cards", "live_priors"}:
                refs.extend(_string_list(entry.get("prepared_artifact_ref")))
    refs.extend(_content_refs_from_mapping(getattr(content, "role_contract", None)))
    prepared_ref = getattr(content, "prepared_artifact_ref", None)
    if isinstance(prepared_ref, str):
        refs.append(prepared_ref)
    elif isinstance(prepared_ref, Mapping):
        refs.extend(_string_list(prepared_ref.get("ref") or prepared_ref.get("artifact_ref")))
    return _dedupe([ref for ref in refs if is_content_evidence_ref(ref)])


def _role_contract_from_programme(programme: Any) -> Mapping[str, Any]:
    content = getattr(programme, "content", None)
    contract = getattr(content, "role_contract", {}) if content else {}
    return contract if isinstance(contract, Mapping) else {}


def _role_contract_source_refs(role_contract: Mapping[str, Any]) -> list[str]:
    refs = _string_list(role_contract.get("source_packet_refs"))
    refs.extend(_string_list(role_contract.get("source_refs")))
    refs.extend(_content_refs_from_mapping(role_contract))
    return _dedupe([ref for ref in refs if is_source_evidence_ref(ref)])


def _missing_role_contract_fields(role: str, role_contract: Mapping[str, Any]) -> list[str]:
    required = [
        "source_packet_refs",
        "role_live_bit_mechanic",
        "event_object",
        "audience_job",
        "payoff",
        "temporality_band",
    ]
    if role in {"tier_list", "top_10"}:
        required.append("tier_criteria" if role == "tier_list" else "ordering_criterion")
    elif role == "lecture":
        required.extend(["teaching_objective", "demonstration_object", "worked_example"])
    elif role == "interview":
        required.extend(["subject_context", "question_ladder", "answer_source_policy"])
    elif role == "react":
        required.extend(["media_ref", "timestamp_or_locator", "claim_under_reaction"])
    elif role == "iceberg":
        required.extend(["layer_refs", "bottom_payoff"])
    elif role == "rant":
        required.extend(["bounded_claim", "receipt_flip"])
    missing: list[str] = []
    for field in required:
        if not _contract_field_has_value(role_contract, field):
            missing.append(field)
    if not _role_contract_source_refs(role_contract):
        missing.append("source_packet_refs:source_evidence_ref")
    return missing


def _contract_field_has_value(role_contract: Mapping[str, Any], field: str) -> bool:
    value = role_contract.get(field)
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return any(str(item).strip() for item in value if item is not None)
    return bool(value)


def _operator_interview(role_contract: Mapping[str, Any]) -> bool:
    subject_ref = str(role_contract.get("subject_ref") or "").strip().lower()
    subject_context = str(role_contract.get("subject_context") or "").strip().lower()
    return subject_ref in {"operator", "hapax-operator", "ryan"} or bool(
        re.search(r"\b(?:the )?operator\b", subject_context)
    )


def _interview_contract_violations(role_contract: Mapping[str, Any]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []

    question_ladder = role_contract.get("question_ladder")
    if isinstance(question_ladder, str):
        violations.append({"reason": "interview_question_ladder_must_be_structured"})
        questions: list[Mapping[str, Any]] = []
    elif isinstance(question_ladder, Sequence) and not isinstance(question_ladder, (str, bytes)):
        questions = [item for item in question_ladder if isinstance(item, Mapping)]
        if len(questions) != len(question_ladder):
            violations.append({"reason": "interview_question_ladder_contains_unstructured_items"})
    else:
        questions = []

    if not questions:
        violations.append({"reason": "interview_question_ladder_missing_questions"})
    for index, question in enumerate(questions):
        for field in (
            "question_id",
            "question_text",
            "answer_kind",
            "followup_policy",
            "what_answer_changes",
        ):
            if not str(question.get(field) or "").strip():
                violations.append({"reason": f"interview_question_missing_{field}", "index": index})
        refs = _string_list(
            question.get("source_refs")
            or question.get("source_packet_refs")
            or question.get("evidence_refs")
        )
        if not any(is_source_evidence_ref(ref) for ref in refs):
            violations.append({"reason": "interview_question_missing_source_refs", "index": index})

    answer_policy = role_contract.get("answer_source_policy")
    if not isinstance(answer_policy, Mapping):
        violations.append({"reason": "interview_answer_source_policy_must_be_structured"})
    else:
        for field in (
            "operator_answer_authority",
            "transcript_ref_kind",
            "no_answer_flag",
            "refusal_policy",
            "public_private_boundary",
        ):
            if not str(answer_policy.get(field) or "").strip():
                violations.append({"reason": f"interview_answer_policy_missing_{field}"})

    topic_selection = role_contract.get("topic_selection")
    if _operator_interview(role_contract):
        if not isinstance(topic_selection, Mapping):
            violations.append({"reason": "operator_interview_missing_topic_selection"})
        else:
            topic_refs = _string_list(
                topic_selection.get("topic_source_refs")
                or topic_selection.get("source_refs")
                or topic_selection.get("source_packet_refs")
            )
            if not any(is_source_evidence_ref(ref) for ref in topic_refs):
                violations.append({"reason": "operator_interview_topic_missing_source_refs"})
            for field in (
                "why_this_topic_now",
                "premise_under_test",
                "operator_topic_consent_required",
                "allowed_runtime_responses",
            ):
                value = topic_selection.get(field)
                if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                    empty = not any(str(item).strip() for item in value if item is not None)
                else:
                    empty = not str(value or "").strip()
                if empty:
                    violations.append({"reason": f"operator_interview_topic_missing_{field}"})

        agency = role_contract.get("operator_agency_policy")
        if not isinstance(agency, Mapping):
            violations.append({"reason": "operator_interview_missing_agency_policy"})
        else:
            for field in ("stop_policy", "skip_policy", "private_policy", "off_record_policy"):
                if not str(agency.get(field) or "").strip():
                    violations.append({"reason": f"operator_interview_agency_missing_{field}"})

    return violations


def programme_source_readiness(programme: Any) -> dict[str, Any]:
    """Validate that a planned programme has source material before compose."""
    content = getattr(programme, "content", None)
    role = getattr(getattr(programme, "role", None), "value", str(getattr(programme, "role", "")))
    narrative = str(getattr(content, "narrative_beat", "") or "") if content else ""
    beats = _string_list(getattr(content, "segment_beats", []) if content else [])
    beat_layout_intents = _mapping_list(
        getattr(content, "beat_layout_intents", []) if content else []
    )
    role_contract = _role_contract_from_programme(programme)
    role_contract_text = _mapping_text(role_contract)
    evidence_refs = _content_refs_from_programme(programme)
    source_refs = _role_contract_source_refs(role_contract)
    violations: list[dict[str, Any]] = []

    if not source_refs:
        violations.append({"reason": "source_recruitment_required"})
    missing_role_contract = _missing_role_contract_fields(role, role_contract)
    if missing_role_contract:
        violations.append(
            {"reason": "missing_role_contract_fields", "fields": missing_role_contract}
        )
    if not beats:
        violations.append({"reason": "missing_segment_beats"})
    if not beat_layout_intents:
        violations.append({"reason": "missing_programme_layout_intents"})
    else:
        for index, intent in enumerate(beat_layout_intents):
            refs = _string_list(intent.get("evidence_refs") or intent.get("evidence_ref"))
            if not any(is_content_evidence_ref(ref) for ref in refs):
                violations.append(
                    {"reason": "programme_layout_intent_missing_content_evidence", "index": index}
                )
            if intent.get("default_static_success_allowed") is True:
                violations.append(
                    {"reason": "programme_layout_intent_allows_static_default", "index": index}
                )

    combined_raw = " ".join([narrative, *beats, role_contract_text])
    combined = combined_raw.lower()
    scriptlike_indices = [
        index for index, beat in enumerate(beats) if _SCRIPTLIKE_BEAT_RE.search(beat)
    ]
    if scriptlike_indices:
        violations.append(
            {"reason": "segment_beats_are_scripted_or_human_hostish", "indices": scriptlike_indices}
        )
    generic_stage_indices = [
        index for index, beat in enumerate(beats) if _GENERIC_STAGE_BEAT_RE.search(beat)
    ]
    if generic_stage_indices:
        violations.append(
            {
                "reason": "segment_beats_are_generic_stage_directions",
                "indices": generic_stage_indices,
            }
        )
    if _TEMPLATE_LEAK_RE.search(combined_raw):
        violations.append({"reason": "programme_narrative_beat_template_leak"})
    stale_years = [
        int(match.group(1))
        for match in _YEAR_RE.finditer(combined_raw)
        if int(match.group(1)) <= datetime.now(tz=UTC).year - 2
    ]
    if (
        stale_years
        and _CURRENT_RANKING_RE.search(combined_raw)
        and not re.search(
            r"\b(?:historical|retrospective|archival|snapshot|as of|period piece)\b",
            combined,
        )
    ):
        violations.append(
            {
                "reason": "stale_current_ranking_requires_retrospective_or_freshness_context",
                "years": _dedupe([str(year) for year in stale_years]),
            }
        )
    has_lecture_contract = all(
        _contract_field_has_value(role_contract, field)
        for field in ("teaching_objective", "demonstration_object", "worked_example")
    )
    if (
        role == "lecture"
        and not has_lecture_contract
        and not re.search(
            r"\b(?:demonstration|worked example|example object|teaching object|case object|"
            r"definition card|source object|proof object)\b",
            combined,
        )
    ):
        violations.append({"reason": "lecture_requires_demonstration_object"})
    has_interview_contract = all(
        _contract_field_has_value(role_contract, field)
        for field in ("subject_context", "question_ladder", "answer_source_policy")
    )
    if (
        role == "interview"
        and not has_interview_contract
        and not re.search(
            r"\b(?:transcript|recorded source|answer source|question ladder|source answer|"
            r"no-answer flag)\b",
            combined,
        )
    ):
        violations.append({"reason": "interview_requires_answer_source_policy"})
    if role == "interview":
        violations.extend(_interview_contract_violations(role_contract))
    has_react_contract = all(
        _contract_field_has_value(role_contract, field)
        for field in ("media_ref", "timestamp_or_locator", "claim_under_reaction")
    )
    if (
        role == "react"
        and not has_react_contract
        and not re.search(
            r"\b(?:media ref|resolver|timestamp|time-stamped|source media|claim under reaction)\b",
            combined,
        )
    ):
        violations.append({"reason": "react_requires_media_locator"})
    ordering_field = {"tier_list": "tier_criteria", "top_10": "ordering_criterion"}.get(role)
    if (
        ordering_field
        and not _contract_field_has_value(role_contract, ordering_field)
        and not re.search(
            r"\b(?:criterion|criteria|ordering rule|ranking rule|tier criteria)\b",
            combined,
        )
    ):
        violations.append({"reason": f"{role}_requires_ordering_criteria"})

    return {
        "ok": not violations,
        "role": role,
        "evidence_refs": source_refs,
        "content_evidence_refs": evidence_refs,
        "violations": violations,
    }


def _beat_ids(beats: Sequence[str]) -> list[str]:
    out: list[str] = []
    for index, beat in enumerate(beats):
        prefix = str(beat).split(":", 1)[0].strip()
        out.append(prefix if prefix and len(prefix) <= 40 else f"beat-{index + 1}")
    return out


def _action_kind_for_intent(intent: Mapping[str, Any]) -> str:
    kind = str(intent.get("kind") or "")
    if kind == "tier_chart":
        return "rank"
    if kind == "countdown":
        return "reveal_rank"
    if kind == "chat_poll":
        return "public_decision"
    if kind == "source_citation":
        return "cite_source"
    if kind == "comparison":
        return "compare"
    if kind == "iceberg_depth":
        return "reveal_depth"
    if kind == "argument_posture_shift":
        return "qualify_argument"
    return kind or "narrate"


def _ttl_to_seconds(value: Any) -> float | None:
    if isinstance(value, int | float) and value > 0:
        return float(value)
    if not isinstance(value, str):
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*(ms|s|sec|secs|second|seconds)?", value.lower())
    if not match:
        return None
    amount = float(match.group(1))
    if amount <= 0:
        return None
    unit = match.group(2) or "s"
    if unit == "ms":
        return amount / 1000.0
    return amount


def _loop_cards_from_contract_parts(
    *,
    programme_id: str,
    role: str,
    layout_need_map: Sequence[Mapping[str, Any]],
    readback_obligations: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Build feedforward loop cards from prep layout/readback obligations.

    These cards do not claim runtime control. They declare the reference and
    sensor/readback surface that the later runtime loop must close.
    """

    readbacks_by_need = {
        str(readback.get("layout_need_id") or ""): readback
        for readback in readback_obligations
        if isinstance(readback, Mapping)
    }
    cards: list[dict[str, Any]] = []
    for index, need in enumerate(layout_need_map):
        need_id = str(need.get("layout_need_id") or f"need:{programme_id}:{index}")
        readback = readbacks_by_need.get(need_id, {})
        readback_id = str(readback.get("readback_id") or f"readback:{_slug(need_id)}")
        evidence_refs = _string_list(
            need.get("source_packet_refs")
            or need.get("evidence_refs")
            or readback.get("evidence_refs")
        )
        cards.append(
            {
                "loop_card_version": 1,
                "loop_id": f"loop:{programme_id}:{_slug(need_id)}",
                "admissibility": LoopAdmissibility.FEEDFORWARD_PLAN.value,
                "plant_boundary": (
                    f"future runtime delivery for {programme_id} role={role} need={need_id}"
                ),
                "controlled_variable": str(need.get("need_kind") or "layout_need"),
                "reference_signal": str(
                    readback.get("must_show")
                    or need.get("why_visible")
                    or need.get("minimum_runtime_affordance")
                    or "declared visible effect"
                ),
                "sensor_ref": readback_id,
                "actuator_ref": "runtime_layout_controller",
                "sample_period_s": 1.0,
                "latency_budget_s": _ttl_to_seconds(readback.get("timeout_or_ttl")) or 30.0,
                "readback_ref": readback_id,
                "fallback_mode": str(
                    need.get("fallback_if_unavailable")
                    or readback.get("failure_signal")
                    or "narrow to spoken argument if runtime readback fails"
                ),
                "authority_boundary": "prep_prior_only_runtime_must_close_readback",
                "privacy_ceiling": "public_archive_candidate",
                "evidence_refs": evidence_refs,
                "disturbance_refs": ("stale_readback", "missing_layout_surface"),
                "failure_mode": str(
                    readback.get("failure_signal")
                    or "runtime readback missing, stale, mismatched, or fallback-only"
                ),
                "limits": (
                    "prepared artifact declares the reference but cannot command layout",
                    "selected release still requires review receipts",
                ),
            }
        )
    return cards


def _normalize_claim_map(
    raw_claims: Sequence[Mapping[str, Any]],
    *,
    programme_id: str,
    beat_ids: Sequence[str],
    refs: Sequence[str],
    raw_source_consequences: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_claims):
        beat_id = _beat_id_for_entry(raw, index, beat_ids)
        fallback_ref = refs[min(index, len(refs) - 1)] if refs else ""
        grounds = _entry_refs(
            raw,
            "grounds",
            "evidence_refs",
            "evidence_ref",
            "source_refs",
            "source_ref",
            "source_packet_refs",
            "source_packet_ref",
        )
        if not grounds and fallback_ref:
            grounds = [fallback_ref]
        consequence = _first_non_empty_text(
            raw,
            "source_consequence",
            "consequence",
            "what_source_changes",
            "why_it_matters",
        )
        if not consequence and index < len(raw_source_consequences):
            consequence = _first_non_empty_text(
                raw_source_consequences[index],
                "source_consequence",
                "consequence",
                "changed_field",
                "what_source_changes",
            )
        claim_id = str(raw.get("claim_id") or "").strip()
        if not claim_id:
            claim_id = f"claim:{programme_id}:{_slug(beat_id)}:{index + 1}"
        claims.append(
            {
                **dict(raw),
                "claim_id": claim_id,
                "beat_id": beat_id,
                "claim_text": _first_non_empty_text(
                    raw,
                    "claim_text",
                    "claim",
                    "text",
                    "assertion",
                ),
                "claim_kind": str(raw.get("claim_kind") or "livestream_segment_claim"),
                "grounds": grounds,
                "warrant": str(
                    raw.get("warrant") or "source packet and beat plan must change the public claim"
                ),
                "qualifier_or_limit": str(
                    raw.get("qualifier_or_limit") or "prep prior only pending runtime readback"
                ),
                "source_consequence": consequence,
                "visible_object_ids": _string_list(raw.get("visible_object_ids"))
                or [f"object:{programme_id}:{_slug(beat_id)}"],
            }
        )
    return claims


def _claim_ids_by_beat(claim_map: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    by_beat: dict[str, list[str]] = {}
    for claim in claim_map:
        claim_id = str(claim.get("claim_id") or "").strip()
        beat_id = str(claim.get("beat_id") or "").strip()
        if claim_id and beat_id:
            by_beat.setdefault(beat_id, []).append(claim_id)
    return by_beat


def _normalize_source_consequence_map(
    raw_consequences: Sequence[Mapping[str, Any]],
    *,
    refs: Sequence[str],
    claim_map: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    claim_ids = [str(claim.get("claim_id") or "") for claim in claim_map]
    consequences: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_consequences):
        fallback_ref = refs[min(index, len(refs) - 1)] if refs else ""
        source_refs = _entry_refs(
            raw,
            "source_ref",
            "evidence_ref",
            "evidence_refs",
            "source_refs",
            "source_packet_refs",
        )
        source_ref = str(raw.get("source_ref") or (source_refs[0] if source_refs else fallback_ref))
        linked_claim_ids = _string_list(raw.get("claim_ids") or raw.get("claim_id"))
        if not linked_claim_ids and index < len(claim_ids) and claim_ids[index]:
            linked_claim_ids = [claim_ids[index]]
        changed_field = _first_non_empty_text(
            raw,
            "changed_field",
            "consequence",
            "source_consequence",
            "what_source_changes",
        )
        consequences.append(
            {
                **dict(raw),
                "source_ref": source_ref,
                "claim_ids": linked_claim_ids,
                "consequence_kind": str(
                    raw.get("consequence_kind") or "scope_confidence_or_action_delta"
                ),
                "changed_field": changed_field,
                "failure_if_missing": str(
                    raw.get("failure_if_missing")
                    or "quarantine or recruit stronger source before prep"
                ),
            }
        )
    return consequences


def _normalize_actionability_map(
    raw_actions: Sequence[Mapping[str, Any]],
    *,
    programme_id: str,
    beat_ids: Sequence[str],
    claims_by_beat: Mapping[str, Sequence[str]],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    all_claim_ids = [
        claim_id
        for claim_ids in claims_by_beat.values()
        for claim_id in claim_ids
        if str(claim_id).strip()
    ]
    for index, raw in enumerate(raw_actions):
        beat_id = _beat_id_for_entry(raw, index, beat_ids)
        kind = _first_non_empty_text(raw, "kind", "action", "action_kind")
        target = _first_non_empty_text(raw, "object", "target", "event_object")
        action_id = str(raw.get("action_id") or "").strip()
        if not action_id:
            action_id = f"action:{programme_id}:{_slug(beat_id)}:{index + 1}"
        linked_claim_ids = _string_list(raw.get("claim_ids") or raw.get("claim_id")) or list(
            claims_by_beat.get(beat_id, ())
        )
        if not linked_claim_ids and all_claim_ids:
            linked_claim_ids = [all_claim_ids[min(index, len(all_claim_ids) - 1)]]
        actions.append(
            {
                **dict(raw),
                "action_id": action_id,
                "beat_id": beat_id,
                "claim_ids": linked_claim_ids,
                "kind": kind,
                "object": target,
                "operation": _first_non_empty_text(raw, "operation", "do", "visible_action")
                or (f"make {target} inspectable" if target else ""),
                "feedback": _first_non_empty_text(
                    raw,
                    "feedback",
                    "expected_effect",
                    "effect",
                    "what_changes",
                )
                or "source changes the visible public object",
                "fallback": _first_non_empty_text(raw, "fallback", "failure_mode")
                or "narrow to spoken argument and say runtime readback is unavailable",
            }
        )
    return actions


def _normalize_layout_need_map(
    raw_needs: Sequence[Mapping[str, Any]],
    *,
    programme_id: str,
    beat_ids: Sequence[str],
    refs: Sequence[str],
    claims_by_beat: Mapping[str, Sequence[str]],
    actions: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    action_ids_by_beat: dict[str, list[str]] = {}
    for action in actions:
        beat_id = str(action.get("beat_id") or "").strip()
        action_id = str(action.get("action_id") or "").strip()
        if beat_id and action_id:
            action_ids_by_beat.setdefault(beat_id, []).append(action_id)
    all_claim_ids = [
        claim_id
        for claim_ids in claims_by_beat.values()
        for claim_id in claim_ids
        if str(claim_id).strip()
    ]
    layout_needs: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_needs):
        beat_id = _beat_id_for_entry(raw, index, beat_ids)
        fallback_ref = refs[min(index, len(refs) - 1)] if refs else ""
        source_packet_refs = _entry_refs(
            raw,
            "source_packet_refs",
            "source_packet_ref",
            "evidence_refs",
            "evidence_ref",
            "source_refs",
            "source_ref",
        )
        if not source_packet_refs and fallback_ref:
            source_packet_refs = [fallback_ref]
        need_kind = _first_non_empty_text(raw, "need_kind", "need", "layout_need")
        layout_need_id = str(raw.get("layout_need_id") or "").strip()
        if not layout_need_id:
            layout_need_id = f"need:{programme_id}:{_slug(beat_id)}:{index + 1}"
        linked_claim_ids = _string_list(raw.get("claim_ids") or raw.get("claim_id")) or list(
            claims_by_beat.get(beat_id, ())
        )
        if not linked_claim_ids and all_claim_ids:
            linked_claim_ids = [all_claim_ids[min(index, len(all_claim_ids) - 1)]]
        layout_needs.append(
            {
                **dict(raw),
                "layout_need_id": layout_need_id,
                "beat_id": beat_id,
                "claim_ids": linked_claim_ids,
                "action_ids": _string_list(raw.get("action_ids") or raw.get("action_id"))
                or action_ids_by_beat.get(beat_id, []),
                "source_packet_refs": source_packet_refs,
                "need_kind": need_kind,
                "why_visible": _first_non_empty_text(raw, "why_visible", "why", "reason")
                or "viewer must inspect the object or consequence named by the claim",
                "minimum_runtime_affordance": _first_non_empty_text(
                    raw,
                    "minimum_runtime_affordance",
                    "affordance",
                    "surface",
                ),
                "fallback_if_unavailable": _first_non_empty_text(
                    raw,
                    "fallback_if_unavailable",
                    "fallback",
                )
                or "say the readback failed and narrow the claim",
            }
        )
    return layout_needs


def _normalize_readback_obligations(
    raw_readbacks: Sequence[Mapping[str, Any]],
    *,
    layout_need_map: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    layout_need_ids = [str(need.get("layout_need_id") or "") for need in layout_need_map]
    readbacks: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_readbacks):
        need_id = str(raw.get("layout_need_id") or "").strip()
        if not need_id and index < len(layout_need_ids):
            need_id = layout_need_ids[index]
        readbacks.append(
            {
                **dict(raw),
                "readback_id": str(raw.get("readback_id") or f"readback:{_slug(need_id)}"),
                "layout_need_id": need_id,
                "must_show": _first_non_empty_text(raw, "must_show", "must_render")
                or "declared layout need",
                "must_not_claim": _first_non_empty_text(raw, "must_not_claim")
                or "runtime layout success before rendered readback",
                "success_signal": _first_non_empty_text(raw, "success_signal")
                or "rendered compositor readback names the same source/action object",
                "failure_signal": _first_non_empty_text(raw, "failure_signal")
                or "missing, stale, mismatched, or fallback-only readback",
                "timeout_or_ttl": str(raw.get("timeout_or_ttl") or raw.get("ttl_s") or "30s"),
                "evidence_refs": _entry_refs(raw, "evidence_refs", "evidence_ref"),
            }
        )
    return readbacks


def _valid_or_derived_loop_cards(
    raw_cards: Sequence[Mapping[str, Any]],
    *,
    programme_id: str,
    role: str,
    layout_need_map: Sequence[Mapping[str, Any]],
    readback_obligations: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    if raw_cards:
        normalized: list[dict[str, Any]] = []
        for index, raw in enumerate(raw_cards):
            card = dict(raw)
            if not _string_list(card.get("evidence_refs")) and index < len(layout_need_map):
                need = layout_need_map[index]
                card["evidence_refs"] = _string_list(
                    need.get("source_packet_refs") or need.get("evidence_refs")
                )
            normalized.append(card)
        if validate_loop_cards(normalized).get("ok") is True:
            return normalized, False
    if layout_need_map and readback_obligations:
        return (
            _loop_cards_from_contract_parts(
                programme_id=programme_id,
                role=role,
                layout_need_map=layout_need_map,
                readback_obligations=readback_obligations,
            ),
            True,
        )
    return [], False


def build_segment_prep_contract(
    *,
    programme_id: str,
    role: str,
    topic: str,
    segment_beats: Sequence[str],
    script: Sequence[str],
    actionability: Mapping[str, Any],
    layout_responsibility: Mapping[str, Any],
    source_refs: Sequence[str],
    model_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize a model-emitted contract and fill deterministic ids."""
    beat_ids = _beat_ids(segment_beats)
    refs = _dedupe([ref for ref in source_refs if is_content_evidence_ref(ref)])
    if not refs:
        refs = _dedupe(
            [
                ref
                for beat in actionability.get("beat_action_intents", []) or []
                if isinstance(beat, Mapping)
                for intent in beat.get("intents", []) or []
                if isinstance(intent, Mapping)
                for ref in _string_list(intent.get("evidence_refs"))
                if is_content_evidence_ref(ref)
            ]
        )

    model_contract_provided = isinstance(model_contract, Mapping) and bool(model_contract)
    if model_contract_provided:
        generation = model_contract.get("contract_generation")
        if isinstance(generation, Mapping) and (
            generation.get("model_emitted") is False
            or _string_list(generation.get("deterministic_backfilled_fields"))
        ):
            model_contract_provided = False
    model_contract = model_contract or {}
    deterministic_backfilled_fields: list[str] = []
    canonicalized_fields: list[str] = []
    derived_fields: list[str] = []
    source_packets = list(_mapping_list(model_contract.get("source_packet_refs")))
    if not source_packets:
        deterministic_backfilled_fields.append("source_packet_refs")
    existing_source_refs = {
        str(packet.get("source_ref") or packet.get("id") or "")
        for packet in source_packets
        if isinstance(packet, Mapping)
    }
    for ref in refs:
        if ref not in existing_source_refs:
            source_packets.append(
                {
                    "id": f"packet:{_slug(ref)}",
                    "source_ref": ref,
                    "evidence_refs": [ref],
                    "freshness_band": "not_applicable_or_unverified",
                }
            )

    raw_claim_map = list(_mapping_list(model_contract.get("claim_map")))
    raw_source_consequence_map = list(_mapping_list(model_contract.get("source_consequence_map")))
    claim_map = _normalize_claim_map(
        raw_claim_map,
        programme_id=programme_id,
        beat_ids=beat_ids,
        refs=refs,
        raw_source_consequences=raw_source_consequence_map,
    )
    if raw_claim_map:
        canonicalized_fields.append("claim_map")
    if not claim_map:
        deterministic_backfilled_fields.append("claim_map")
        for index, text in enumerate(script):
            beat_id = beat_ids[index] if index < len(beat_ids) else f"beat-{index + 1}"
            ref = refs[min(index, len(refs) - 1)] if refs else ""
            claim_map.append(
                {
                    "claim_id": f"claim:{programme_id}:{beat_id}",
                    "beat_id": beat_id,
                    "claim_text": text[:360],
                    "claim_kind": "livestream_segment_claim",
                    "grounds": [ref] if ref else [],
                    "warrant": "source packet and beat plan must change the public claim",
                    "qualifier_or_limit": "prep prior only pending runtime readback",
                    "source_consequence": (
                        "source must alter scope, rank, confidence, contrast, or visible action"
                    ),
                    "visible_object_ids": [f"object:{programme_id}:{beat_id}"],
                }
            )

    claims_by_beat = _claim_ids_by_beat(claim_map)

    actionability_map = _normalize_actionability_map(
        list(_mapping_list(model_contract.get("actionability_map"))),
        programme_id=programme_id,
        beat_ids=beat_ids,
        claims_by_beat=claims_by_beat,
    )
    if _mapping_list(model_contract.get("actionability_map")):
        canonicalized_fields.append("actionability_map")
    if not actionability_map:
        deterministic_backfilled_fields.append("actionability_map")
        for beat in actionability.get("beat_action_intents", []) or []:
            if not isinstance(beat, Mapping):
                continue
            beat_index = int(beat.get("beat_index", 0))
            beat_id = (
                beat_ids[beat_index] if beat_index < len(beat_ids) else f"beat-{beat_index + 1}"
            )
            for intent_index, intent in enumerate(beat.get("intents", []) or []):
                if not isinstance(intent, Mapping) or intent.get("kind") == "spoken_argument":
                    continue
                action_id = f"action:{programme_id}:{beat_id}:{intent_index}"
                target = str(intent.get("target") or intent.get("kind") or "segment-object")
                actionability_map.append(
                    {
                        "action_id": action_id,
                        "beat_id": beat_id,
                        "claim_ids": [f"claim:{programme_id}:{beat_id}"],
                        "kind": _action_kind_for_intent(intent),
                        "object": target,
                        "operation": (intent.get("actionability_map") or {}).get("operation")
                        or f"make {target} inspectable",
                        "feedback": (intent.get("actionability_map") or {}).get("feedback")
                        or str(intent.get("expected_effect") or ""),
                        "fallback": (intent.get("actionability_map") or {}).get("fallback")
                        or "narrow to spoken argument and say runtime readback is unavailable",
                    }
                )

    claims_by_beat = _claim_ids_by_beat(claim_map)

    source_consequence_map = _normalize_source_consequence_map(
        raw_source_consequence_map,
        refs=refs,
        claim_map=claim_map,
    )
    if raw_source_consequence_map:
        canonicalized_fields.append("source_consequence_map")
    if not source_consequence_map:
        deterministic_backfilled_fields.append("source_consequence_map")
        for claim in claim_map:
            claim_id = str(claim.get("claim_id") or "")
            grounds = _string_list(claim.get("grounds"))
            ref = grounds[0] if grounds else (refs[0] if refs else "")
            source_consequence_map.append(
                {
                    "source_ref": ref,
                    "claim_ids": [claim_id] if claim_id else [],
                    "consequence_kind": "scope_confidence_or_action_delta",
                    "changed_field": "claim_scope_or_visible_action",
                    "failure_if_missing": "quarantine or recruit stronger source before prep",
                }
            )

    layout_need_map = _normalize_layout_need_map(
        list(_mapping_list(model_contract.get("layout_need_map"))),
        programme_id=programme_id,
        beat_ids=beat_ids,
        refs=refs,
        claims_by_beat=claims_by_beat,
        actions=actionability_map,
    )
    if _mapping_list(model_contract.get("layout_need_map")):
        canonicalized_fields.append("layout_need_map")
    if not layout_need_map:
        deterministic_backfilled_fields.append("layout_need_map")
        for beat in layout_responsibility.get("beat_layout_intents", []) or []:
            if not isinstance(beat, Mapping):
                continue
            beat_index = int(beat.get("beat_index", 0))
            beat_id = (
                beat_ids[beat_index] if beat_index < len(beat_ids) else f"beat-{beat_index + 1}"
            )
            for need_index, need in enumerate(_string_list(beat.get("needs"))):
                layout_need_map.append(
                    {
                        "layout_need_id": f"need:{programme_id}:{beat_id}:{need_index}",
                        "beat_id": beat_id,
                        "claim_ids": [f"claim:{programme_id}:{beat_id}"],
                        "action_ids": [
                            str(action.get("action_id"))
                            for action in actionability_map
                            if action.get("beat_id") == beat_id and action.get("action_id")
                        ],
                        "source_packet_refs": _string_list(beat.get("evidence_refs")),
                        "need_kind": need,
                        "why_visible": "viewer must inspect the object or consequence named by the claim",
                        "minimum_runtime_affordance": ",".join(
                            _string_list(beat.get("source_affordances"))
                        ),
                        "fallback_if_unavailable": "say the readback failed and narrow the claim",
                    }
                )

    raw_readback_obligations = list(_mapping_list(model_contract.get("readback_obligations")))
    readback_obligations = _normalize_readback_obligations(
        raw_readback_obligations,
        layout_need_map=layout_need_map,
    )
    if raw_readback_obligations:
        canonicalized_fields.append("readback_obligations")
    if not readback_obligations:
        if model_contract_provided and layout_need_map:
            derived_fields.append("readback_obligations")
        else:
            deterministic_backfilled_fields.append("readback_obligations")
        for need in layout_need_map:
            need_id = str(need.get("layout_need_id") or "")
            readback_obligations.append(
                {
                    "readback_id": f"readback:{_slug(need_id)}",
                    "layout_need_id": need_id,
                    "must_show": str(need.get("need_kind") or "declared layout need"),
                    "must_not_claim": "runtime layout success before rendered readback",
                    "success_signal": "rendered compositor readback names the same source/action object",
                    "failure_signal": "missing, stale, mismatched, or fallback-only readback",
                    "timeout_or_ttl": "30s",
                }
            )

    role_excellence_plan = dict(model_contract.get("role_excellence_plan") or {})
    if "role_excellence_plan" not in model_contract:
        deterministic_backfilled_fields.append("role_excellence_plan")
    role_excellence_plan.setdefault(
        "live_event_plan",
        {
            "bit_engine": "source-bound object changes public status",
            "audience_job": "inspect, vote, challenge, or compare a bounded object",
            "payoff": "closing beat resolves or reframes the opening pressure",
        },
    )
    raw_loop_cards = list(_mapping_list(model_contract.get("loop_cards")))
    loop_cards, loop_cards_derived = _valid_or_derived_loop_cards(
        raw_loop_cards,
        programme_id=programme_id,
        role=role,
        layout_need_map=layout_need_map,
        readback_obligations=readback_obligations,
    )
    if raw_loop_cards:
        canonicalized_fields.append("loop_cards")
    if loop_cards_derived and model_contract_provided:
        derived_fields.append("loop_cards")
    if not loop_cards:
        deterministic_backfilled_fields.append("loop_cards")
        loop_cards = _loop_cards_from_contract_parts(
            programme_id=programme_id,
            role=role,
            layout_need_map=layout_need_map,
            readback_obligations=readback_obligations,
        )

    return {
        "prep_contract_version": SEGMENT_PREP_CONTRACT_VERSION,
        "rundown_card": {
            "programme_id": programme_id,
            "role": role,
            "topic": topic,
            "premise": str(claim_map[0].get("claim_text") or topic)[:500] if claim_map else topic,
            "beat_ids": beat_ids,
            "fallback_posture": "explicit_fallback_spoken_focus",
        },
        "role_contract_ref": f"standard:segment-role:{role}",
        "prepared_script_binding": _prepared_script_binding(
            script=script,
            segment_beats=segment_beats,
        ),
        "source_packet_refs": source_packets,
        "claim_map": claim_map,
        "source_consequence_map": source_consequence_map,
        "actionability_map": actionability_map,
        "layout_need_map": layout_need_map,
        "readback_obligations": readback_obligations,
        "loop_cards": loop_cards,
        "chaos_controls": {
            "bounded_vocabulary": ["source_visible", "comparison", "tier_visual", "chat_prompt"],
            "ttl_required": True,
            "hysteresis_required": True,
            "conflict_arbitration": "runtime_priority_then_freshness_then_fallback",
            "fallback_policy": "fallback preserves stream safety but is not responsible success",
        },
        "repair_decision": "rewrite_recruit_source_or_quarantine",
        "segment_loadability_report": {"explicit_contract_present": True},
        "role_excellence_plan": role_excellence_plan,
        "contract_generation": {
            "model_emitted": model_contract_provided,
            "deterministic_backfilled_fields": deterministic_backfilled_fields,
            "canonicalized_fields": sorted(set(canonicalized_fields)),
            "derived_fields": sorted(set(derived_fields)),
        },
    }


def validate_segment_prep_contract(
    contract: Mapping[str, Any] | None,
    *,
    prepared_script: Sequence[str] | None = None,
    segment_beats: Sequence[str] | None = None,
) -> dict[str, Any]:
    violations: list[dict[str, Any]] = []
    if not isinstance(contract, Mapping):
        return {"ok": False, "violations": [{"reason": "missing_segment_prep_contract"}]}
    if contract.get("prep_contract_version") != SEGMENT_PREP_CONTRACT_VERSION:
        violations.append({"reason": "unsupported_prep_contract_version"})
    generation = contract.get("contract_generation")
    if not isinstance(generation, Mapping) or generation.get("model_emitted") is not True:
        violations.append({"reason": "model_emitted_segment_prep_contract_required"})
    backfilled = _string_list(
        generation.get("deterministic_backfilled_fields") if isinstance(generation, Mapping) else []
    )
    critical_backfill = sorted(
        set(backfilled)
        & {
            "source_packet_refs",
            "claim_map",
            "source_consequence_map",
            "actionability_map",
            "layout_need_map",
            "readback_obligations",
            "role_excellence_plan",
            "loop_cards",
        }
    )
    if critical_backfill:
        violations.append(
            {
                "reason": "segment_prep_contract_has_deterministic_backfill",
                "fields": critical_backfill,
            }
        )

    script_binding = contract.get("prepared_script_binding")
    if not isinstance(script_binding, Mapping):
        violations.append({"reason": "missing_prepared_script_binding"})
    else:
        if script_binding.get("binding_version") != PREPARED_SCRIPT_BINDING_VERSION:
            violations.append({"reason": "unsupported_prepared_script_binding_version"})
        if script_binding.get("binding_scope") != PREPARED_SCRIPT_BINDING_SCOPE:
            violations.append({"reason": "invalid_prepared_script_binding_scope"})
        if script_binding.get("hash_method") != "sha256_json_utf8":
            violations.append({"reason": "invalid_prepared_script_binding_hash_method"})
        bound_script_sha256 = script_binding.get("prepared_script_sha256")
        if not _is_sha256_hex(bound_script_sha256):
            violations.append({"reason": "missing_prepared_script_sha256"})
        if (
            not isinstance(script_binding.get("script_beat_count"), int)
            or int(script_binding.get("script_beat_count") or 0) <= 0
        ):
            violations.append({"reason": "invalid_prepared_script_beat_count"})
        if prepared_script is not None:
            script_list = [str(item) for item in prepared_script]
            if bound_script_sha256 != prepared_script_sha256(script_list):
                violations.append({"reason": "prepared_script_binding_hash_mismatch"})
            if script_binding.get("script_beat_count") != len(script_list):
                violations.append({"reason": "prepared_script_binding_count_mismatch"})
        if not _is_sha256_hex(script_binding.get("segment_beats_sha256")):
            violations.append({"reason": "missing_bound_segment_beats_sha256"})
        if (
            not isinstance(script_binding.get("segment_beat_count"), int)
            or int(script_binding.get("segment_beat_count") or 0) <= 0
        ):
            violations.append({"reason": "invalid_bound_segment_beat_count"})
        if segment_beats is not None:
            beat_list = [str(item) for item in segment_beats]
            if script_binding.get("segment_beats_sha256") != _sha256_json(beat_list):
                violations.append({"reason": "prepared_script_binding_segment_beats_mismatch"})
            if script_binding.get("segment_beat_count") != len(beat_list):
                violations.append({"reason": "prepared_script_binding_segment_beat_count_mismatch"})

    source_packets = _mapping_list(contract.get("source_packet_refs"))
    source_refs = _dedupe(
        [
            ref
            for packet in source_packets
            for ref in _string_list(packet.get("evidence_refs") or packet.get("source_ref"))
        ]
    )
    if not source_packets or not any(is_content_evidence_ref(ref) for ref in source_refs):
        violations.append({"reason": "missing_source_packet_refs"})
    source_ref_set = set(source_refs)
    for index, packet in enumerate(source_packets):
        packet_refs = _string_list(packet.get("evidence_refs") or packet.get("source_ref"))
        if not any(is_source_evidence_ref(ref) for ref in packet_refs):
            violations.append(
                {"reason": "source_packet_missing_source_evidence_ref", "index": index}
            )

    claim_map = _mapping_list(contract.get("claim_map"))
    if not claim_map:
        violations.append({"reason": "missing_claim_map"})
    claim_ids: set[str] = set()
    for index, claim in enumerate(claim_map):
        claim_id = str(claim.get("claim_id") or "").strip()
        if not claim_id:
            violations.append({"reason": "claim_missing_id", "index": index})
        else:
            claim_ids.add(claim_id)
        if not str(claim.get("claim_text") or "").strip():
            violations.append({"reason": "claim_missing_text", "index": index})
        grounds = _string_list(claim.get("grounds"))
        if not grounds:
            violations.append({"reason": "claim_missing_grounds", "index": index})
        elif not all(is_source_evidence_ref(ref) for ref in grounds):
            violations.append({"reason": "claim_ground_not_source_evidence_ref", "index": index})
        elif not any(ref in source_ref_set for ref in grounds):
            violations.append({"reason": "claim_ground_not_in_source_packets", "index": index})
        if not str(claim.get("source_consequence") or "").strip():
            violations.append({"reason": "claim_missing_source_consequence", "index": index})

    source_consequences = _mapping_list(contract.get("source_consequence_map"))
    if not source_consequences:
        violations.append({"reason": "missing_source_consequence_map"})
    for index, consequence in enumerate(source_consequences):
        consequence_claim_ids = _string_list(consequence.get("claim_ids"))
        if not consequence_claim_ids:
            violations.append({"reason": "source_consequence_missing_claim_ids", "index": index})
        elif not set(consequence_claim_ids).issubset(claim_ids):
            violations.append({"reason": "source_consequence_unknown_claim_id", "index": index})
        consequence_ref = str(consequence.get("source_ref") or "").strip()
        if not consequence_ref or not is_source_evidence_ref(consequence_ref):
            violations.append({"reason": "source_consequence_missing_source_ref", "index": index})
        elif source_ref_set and consequence_ref not in source_ref_set:
            violations.append(
                {"reason": "source_consequence_source_ref_not_in_packets", "index": index}
            )
        if not str(consequence.get("changed_field") or "").strip():
            violations.append(
                {"reason": "source_consequence_missing_changed_field", "index": index}
            )
        if not str(consequence.get("failure_if_missing") or "").strip():
            violations.append({"reason": "source_consequence_missing_failure", "index": index})

    actions = _mapping_list(contract.get("actionability_map"))
    if not actions:
        violations.append({"reason": "missing_actionability_map"})
    action_ids: set[str] = set()
    for index, action in enumerate(actions):
        for field in (
            "action_id",
            "beat_id",
            "kind",
            "object",
            "operation",
            "feedback",
            "fallback",
        ):
            if not str(action.get(field) or "").strip():
                violations.append({"reason": f"action_missing_{field}", "index": index})
        action_id = str(action.get("action_id") or "").strip()
        if action_id:
            action_ids.add(action_id)
        action_claim_ids = _string_list(action.get("claim_ids"))
        if not action_claim_ids:
            violations.append({"reason": "action_missing_claim_ids", "index": index})
        elif not set(action_claim_ids).issubset(claim_ids):
            violations.append({"reason": "action_unknown_claim_id", "index": index})

    layout_needs = _mapping_list(contract.get("layout_need_map"))
    if not layout_needs:
        violations.append({"reason": "missing_layout_need_map"})
    layout_need_ids: set[str] = set()
    for index, need in enumerate(layout_needs):
        refs = _string_list(need.get("source_packet_refs") or need.get("evidence_refs"))
        if not any(is_content_evidence_ref(ref) for ref in refs):
            violations.append({"reason": "layout_need_missing_content_evidence", "index": index})
        elif not any(is_source_evidence_ref(ref) for ref in refs):
            violations.append({"reason": "layout_need_missing_source_evidence", "index": index})
        for field in ("layout_need_id", "beat_id", "need_kind", "why_visible"):
            if not str(need.get(field) or "").strip():
                violations.append({"reason": f"layout_need_missing_{field}", "index": index})
        layout_need_id = str(need.get("layout_need_id") or "").strip()
        if layout_need_id:
            layout_need_ids.add(layout_need_id)
        need_claim_ids = _string_list(need.get("claim_ids"))
        if need_claim_ids and not set(need_claim_ids).issubset(claim_ids):
            violations.append({"reason": "layout_need_unknown_claim_id", "index": index})
        need_action_ids = _string_list(need.get("action_ids"))
        if need_action_ids and not set(need_action_ids).issubset(action_ids):
            violations.append({"reason": "layout_need_unknown_action_id", "index": index})

    readbacks = _mapping_list(contract.get("readback_obligations"))
    if not readbacks:
        violations.append({"reason": "missing_readback_obligations"})
    for index, readback in enumerate(readbacks):
        for field in (
            "readback_id",
            "layout_need_id",
            "must_show",
            "must_not_claim",
            "success_signal",
            "failure_signal",
        ):
            if not str(readback.get(field) or "").strip():
                violations.append({"reason": f"readback_missing_{field}", "index": index})
        layout_need_id = str(readback.get("layout_need_id") or "").strip()
        if layout_need_id and layout_need_id not in layout_need_ids:
            violations.append({"reason": "readback_unknown_layout_need_id", "index": index})
        ttl = _ttl_to_seconds(readback.get("timeout_or_ttl") or readback.get("ttl_s"))
        if ttl is None or ttl <= 0:
            violations.append({"reason": "readback_missing_positive_ttl", "index": index})

    loop_report = validate_loop_cards(contract.get("loop_cards"))
    if loop_report["ok"] is not True:
        violations.append(
            {
                "reason": "invalid_or_missing_loop_cards",
                "violations": loop_report["violations"],
            }
        )

    role_plan = contract.get("role_excellence_plan")
    if not isinstance(role_plan, Mapping) or not role_plan.get("live_event_plan"):
        violations.append({"reason": "missing_role_excellence_live_event_plan"})

    return {"ok": not violations, "violations": violations}
