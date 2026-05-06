"""Autonomous narration triad continuity envelopes and ledger.

The triad ledger carries state opened by autonomous or director speech:
observations, assessments, and intended outcomes. It is deliberately not
a truth engine. Phrase extraction can identify action debt, but closure
requires explicit witness/capability/director evidence.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from shared.chronicle import ChronicleEvent, current_otel_ids
from shared.chronicle import record as chronicle_record

SCHEMA_VERSION = "2026-04-29.narration-triad.v1"
TRIAD_LEDGER_PATH = Path.home() / "hapax-state" / "outcomes" / "narration-triads.jsonl"
TRIAD_STATE_PATH = Path("/dev/shm/hapax-daimonion/narration-triad-state.json")
DEFAULT_TTL_S = 600.0

TriadStatus = Literal[
    "open",
    "satisfied",
    "partially_satisfied",
    "blocked",
    "inhibited",
    "corrected",
    "stale",
    "superseded",
    "failed",
    "no_learning",
]

ObservationFreshness = Literal["fresh", "recent", "stale", "unknown"]
ClaimMode = Literal["not_claim_bearing", "private_draft", "public_claim", "operator_visible"]
AuthorityCeiling = Literal["self_report", "wcs_witness", "operator_visible", "public_claim"]
AssessmentKind = Literal[
    "unexpected_shift",
    "curiosity",
    "degraded",
    "stable_but_watch",
    "coherence_risk",
    "programme_transition",
    "public_claim_risk",
    "unknown",
]
OutcomeKind = Literal[
    "monitor",
    "re_evaluate",
    "probe",
    "correct",
    "refuse",
    "route_attention",
    "alter_director_move",
    "update_programme",
    "update_posterior",
    "archive_marker",
    "hold_open",
]

_CLOSED_STATUSES: frozenset[str] = frozenset(
    {
        "satisfied",
        "partially_satisfied",
        "blocked",
        "inhibited",
        "corrected",
        "stale",
        "superseded",
        "failed",
        "no_learning",
    }
)
_PLAYBACK_ONLY_REFS: frozenset[str] = frozenset(
    {
        "wcs:audio.broadcast_voice:voice-output-witness",
        "voice-output-witness:playback_completed",
        "playback:completed",
    }
)
_SEMANTIC_CLOSURE_PREFIXES: tuple[str, ...] = (
    "capability_outcome:",
    "director_move:",
    "public_event:",
    "posterior_update:",
    "correction:",
    "wcs:semantic.",
)
_REF_SUFFIXES: tuple[str, ...] = ("_ref", "_refs")


class ObservationItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    observation_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    source: str = Field(min_length=1)
    substrate_ref: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list, min_length=1)
    freshness: ObservationFreshness = "unknown"
    claim_mode: ClaimMode = "not_claim_bearing"
    authority_ceiling: AuthorityCeiling = "self_report"
    confidence: float = Field(ge=0.0, le=1.0)


class AssessmentItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    assessment_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    assessment_kind: AssessmentKind = "unknown"
    basis_refs: list[str] = Field(default_factory=list, min_length=1)
    uncertainty: float = Field(ge=0.0, le=1.0)
    authority_ceiling: AuthorityCeiling = "self_report"
    risk_flags: list[str] = Field(default_factory=list)


class IntendedOutcomeItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    outcome_kind: OutcomeKind = "hold_open"
    expected_effect: str = Field(min_length=1)
    required_witness_refs: list[str] = Field(default_factory=list)
    candidate_recruitment_targets: list[str] = Field(default_factory=list)
    deadline_at: str
    status: TriadStatus = "open"
    blocked_reasons: list[str] = Field(default_factory=list)
    closure_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _open_or_closed_has_policy(self) -> Self:
        if self.status == "open" and not self.deadline_at:
            raise ValueError("open intended outcomes require deadline_at")
        if self.status in {"blocked", "inhibited", "failed", "no_learning"}:
            if not self.blocked_reasons and not self.closure_refs:
                raise ValueError(f"{self.status} outcomes require blocked_reasons or closure_refs")
        return self


class NarrationTriadEnvelope(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: str = SCHEMA_VERSION
    triad_id: str = Field(min_length=1)
    created_at: str
    updated_at: str
    source_path: str = Field(min_length=1)
    impulse_id: str | None = None
    speech_event_id: str = Field(min_length=1)
    speech_act_type: str = Field(min_length=1)
    programme_id: str | None = None
    programme_role: str = "none"
    programme_run_ref: str | None = None
    role_state_ref: str | None = None
    wcs_snapshot_ref: str = Field(min_length=1)
    utterance_text_ref: str = Field(min_length=1)
    utterance_text_hash: str = Field(min_length=64, max_length=64)
    observation_items: list[ObservationItem] = Field(default_factory=list)
    assessment_items: list[AssessmentItem] = Field(default_factory=list)
    intended_outcome_items: list[IntendedOutcomeItem] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list, min_length=1)
    claim_envelope_refs: list[str] = Field(default_factory=list)
    capability_outcome_refs: list[str] = Field(default_factory=list)
    director_move_refs: list[str] = Field(default_factory=list)
    public_event_refs: list[str] = Field(default_factory=list)
    satisfaction_policy: str = "witness_required_no_keyword_truth"
    ttl_s: float = Field(gt=0.0)
    status: TriadStatus = "open"
    posterior_update_refs: list[str] = Field(default_factory=list)
    correction_refs: list[str] = Field(default_factory=list)
    learning_update_allowed: bool = False

    @model_validator(mode="after")
    def _validate_grounding_policy(self) -> Self:
        role = (self.programme_role or "").strip().lower()
        if role not in {"", "none", "unknown"} and not self.programme_id:
            raise ValueError("active programme role requires programme_id")
        if self.status == "open":
            if not self.intended_outcome_items:
                raise ValueError("open triads require intended_outcome_items")
            if self.learning_update_allowed:
                raise ValueError("open triads cannot allow learning updates")
        if self.status in {"satisfied", "partially_satisfied"}:
            closure_refs = set(self.semantic_closure_refs())
            if not closure_refs:
                raise ValueError("semantic satisfaction requires non-playback closure refs")
            if closure_refs.issubset(_PLAYBACK_ONLY_REFS):
                raise ValueError("playback-only refs cannot satisfy semantic outcomes")
        if self.learning_update_allowed and self.status not in {"satisfied", "partially_satisfied"}:
            raise ValueError("learning updates require satisfied or partially_satisfied triads")
        return self

    def semantic_closure_refs(self) -> list[str]:
        refs: list[str] = []
        refs.extend(self.capability_outcome_refs)
        refs.extend(self.director_move_refs)
        refs.extend(self.public_event_refs)
        refs.extend(self.posterior_update_refs)
        refs.extend(self.correction_refs)
        for item in self.intended_outcome_items:
            refs.extend(
                ref
                for ref in item.closure_refs
                if ref not in _PLAYBACK_ONLY_REFS
                and (ref.startswith(_SEMANTIC_CLOSURE_PREFIXES) or ref.startswith("wcs:semantic."))
            )
        return refs


class NarrationTriadState(BaseModel):
    model_config = ConfigDict(frozen=True)

    updated_at: str
    open_triads: list[dict[str, Any]] = Field(default_factory=list)
    recently_resolved_triads: list[dict[str, Any]] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


def utterance_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def speech_event_id_for_utterance(*, impulse_id: str | None, text: str, now: float) -> str:
    base = f"{impulse_id or 'no-impulse'}:{now:.6f}:{utterance_hash(text)}"
    return "speech-" + hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]


def obligation_outcome_kinds(text: str) -> tuple[OutcomeKind, ...]:
    """Identify action-debt language without deciding truth or satisfaction."""
    lowered = text.lower()
    kinds: list[OutcomeKind] = []
    if "monitor" in lowered:
        kinds.append("monitor")
    if "re-evaluate" in lowered or "reevaluate" in lowered or "re evaluate" in lowered:
        kinds.append("re_evaluate")
    if "curious" in lowered or "curiosity" in lowered:
        kinds.append("probe")
    if "warrants closer attention" in lowered or "warrant closer attention" in lowered:
        kinds.append("route_attention")
    return tuple(dict.fromkeys(kinds))


def build_autonomous_narration_triad(
    *,
    text: str,
    context: Any,
    impulse_id: str | None,
    speech_event_id: str | None = None,
    candidate_name: str = "narration.autonomous_first_system",
    now: float | None = None,
) -> NarrationTriadEnvelope:
    ts = _now(now)
    speech_id = speech_event_id or speech_event_id_for_utterance(
        impulse_id=impulse_id, text=text, now=ts
    )
    return _build_speech_triad(
        text=text,
        context=context,
        impulse_id=impulse_id,
        speech_event_id=speech_id,
        speech_act_type="autonomous_narrative",
        source_path="daimonion.autonomous_narrative",
        candidate_name=candidate_name,
        now=ts,
    )


def build_director_speech_triad(
    *,
    text: str,
    programme_id: str | None,
    programme_role: str | None,
    director_move_ref: str,
    speech_event_id: str,
    now: float | None = None,
) -> NarrationTriadEnvelope:
    ts = _now(now)
    context = _ContextProxy(
        programme_id=programme_id,
        programme_role=programme_role or "none",
        stimmung_tone="unknown",
        director_activity=director_move_ref,
        chronicle_events=(),
        triad_continuity={},
    )
    envelope = _build_speech_triad(
        text=text,
        context=context,
        impulse_id=None,
        speech_event_id=speech_event_id,
        speech_act_type="director_narrative",
        source_path="director.speech",
        candidate_name="director.speech",
        now=ts,
        director_move_refs=[director_move_ref],
    )
    return envelope.model_copy(update={"director_move_refs": [director_move_ref]})


class NarrationTriadLedger:
    """Append-only triad ledger plus current summary cache."""

    def __init__(
        self,
        *,
        ledger_path: Path | None = None,
        state_path: Path | None = None,
    ) -> None:
        self.ledger_path = ledger_path or TRIAD_LEDGER_PATH
        self.state_path = state_path or TRIAD_STATE_PATH

    def append(self, envelope: NarrationTriadEnvelope) -> NarrationTriadEnvelope:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger_path.open("a", encoding="utf-8") as fh:
            fh.write(envelope.model_dump_json() + "\n")
        self._write_summary()
        _record_triad_chronicle_event(envelope)
        _record_triad_metric(envelope)
        return envelope

    def append_status_update(
        self,
        envelope: NarrationTriadEnvelope,
        *,
        status: TriadStatus,
        closure_refs: list[str] | None = None,
        blocked_reasons: list[str] | None = None,
        now: float | None = None,
    ) -> NarrationTriadEnvelope:
        ts = _now(now)
        updates = []
        for item in envelope.intended_outcome_items:
            if item.status != "open":
                updates.append(item)
                continue
            refs = list(item.closure_refs)
            refs.extend(closure_refs or [])
            reasons = list(item.blocked_reasons)
            reasons.extend(blocked_reasons or [])
            updates.append(
                item.model_copy(
                    update={
                        "status": status,
                        "closure_refs": _dedupe(refs),
                        "blocked_reasons": _dedupe(reasons),
                    }
                )
            )
        capability_refs = list(envelope.capability_outcome_refs)
        director_refs = list(envelope.director_move_refs)
        public_refs = list(envelope.public_event_refs)
        posterior_refs = list(envelope.posterior_update_refs)
        correction_refs = list(envelope.correction_refs)
        for ref in closure_refs or []:
            if ref.startswith("capability_outcome:"):
                capability_refs.append(ref)
            elif ref.startswith("director_move:"):
                director_refs.append(ref)
            elif ref.startswith("public_event:"):
                public_refs.append(ref)
            elif ref.startswith("posterior_update:"):
                posterior_refs.append(ref)
            elif ref.startswith("correction:"):
                correction_refs.append(ref)
        updated = envelope.model_copy(
            update={
                "updated_at": _iso(ts),
                "status": status,
                "intended_outcome_items": updates,
                "capability_outcome_refs": _dedupe(capability_refs),
                "director_move_refs": _dedupe(director_refs),
                "public_event_refs": _dedupe(public_refs),
                "posterior_update_refs": _dedupe(posterior_refs),
                "correction_refs": _dedupe(correction_refs),
                "learning_update_allowed": status in {"satisfied", "partially_satisfied"},
            }
        )
        updated = NarrationTriadEnvelope.model_validate(updated.model_dump())
        return self.append(updated)

    def latest_by_triad_id(self) -> dict[str, NarrationTriadEnvelope]:
        latest: dict[str, NarrationTriadEnvelope] = {}
        if not self.ledger_path.exists():
            return latest
        for line in self.ledger_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                envelope = NarrationTriadEnvelope.model_validate_json(line)
            except ValidationError:
                continue
            latest[envelope.triad_id] = envelope
        return latest

    def open_triads(self) -> list[NarrationTriadEnvelope]:
        return [e for e in self.latest_by_triad_id().values() if e.status == "open"]

    def resolve_open_triads(
        self,
        *,
        now: float | None = None,
        observed_witness_refs: set[str] | None = None,
        semantic_closure_refs: set[str] | None = None,
    ) -> list[NarrationTriadEnvelope]:
        """Resolve open triads from explicit evidence only.

        Playback or voice-output refs alone are not semantic closure refs.
        """
        ts = _now(now)
        observed = observed_witness_refs or set()
        semantic_refs = {
            ref
            for ref in (semantic_closure_refs or set())
            if ref not in _PLAYBACK_ONLY_REFS and ref.startswith(_SEMANTIC_CLOSURE_PREFIXES)
        }
        updates: list[NarrationTriadEnvelope] = []
        for envelope in self.open_triads():
            deadline = max(
                (_parse_ts(item.deadline_at) for item in envelope.intended_outcome_items),
                default=None,
            )
            if deadline is not None and ts > deadline:
                updates.append(
                    self.append_status_update(
                        envelope,
                        status="stale",
                        closure_refs=[f"triad_ttl_elapsed:{envelope.triad_id}"],
                        now=ts,
                    )
                )
                continue
            required = {
                ref
                for item in envelope.intended_outcome_items
                for ref in item.required_witness_refs
                if ref not in _PLAYBACK_ONLY_REFS
            }
            if semantic_refs and (not required or required.issubset(observed | semantic_refs)):
                updates.append(
                    self.append_status_update(
                        envelope,
                        status="satisfied",
                        closure_refs=sorted(semantic_refs),
                        now=ts,
                    )
                )
        return updates

    def _write_summary(self) -> None:
        latest = list(self.latest_by_triad_id().values())
        latest.sort(key=lambda item: item.updated_at, reverse=True)
        open_triads = [self._summary_item(item) for item in latest if item.status == "open"][:8]
        resolved = [self._summary_item(item) for item in latest if item.status in _CLOSED_STATUSES][
            :8
        ]
        metrics = _summary_metrics(latest)
        state = NarrationTriadState(
            updated_at=_iso(time.time()),
            open_triads=open_triads,
            recently_resolved_triads=resolved,
            metrics=metrics,
        )
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_name(f"{self.state_path.name}.tmp")
        tmp.write_text(state.model_dump_json() + "\n", encoding="utf-8")
        tmp.replace(self.state_path)

    @staticmethod
    def _summary_item(envelope: NarrationTriadEnvelope) -> dict[str, Any]:
        return {
            "triad_id": envelope.triad_id,
            "status": envelope.status,
            "speech_event_id": envelope.speech_event_id,
            "programme_id": envelope.programme_id,
            "programme_role": envelope.programme_role,
            "source_path": envelope.source_path,
            "obligations": [
                {
                    "outcome_id": item.outcome_id,
                    "kind": item.outcome_kind,
                    "status": item.status,
                    "deadline_at": item.deadline_at,
                    "text": item.text,
                }
                for item in envelope.intended_outcome_items
            ],
            "evidence_refs": envelope.evidence_refs[:8],
            "learning_update_allowed": envelope.learning_update_allowed,
        }


def read_triad_state(path: Path | None = None) -> NarrationTriadState:
    state_path = path or TRIAD_STATE_PATH
    try:
        return NarrationTriadState.model_validate_json(state_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValidationError, ValueError):
        return NarrationTriadState(updated_at=_iso(time.time()))


def triad_resolution_refs_from_events(
    events: Iterable[dict[str, Any]],
) -> tuple[set[str], set[str]]:
    """Extract observed and semantic refs from witness-like events.

    This only gathers explicit refs already present in event payloads. It does
    not infer truth from event names or prose, and playback refs remain
    non-semantic.
    """
    observed: set[str] = set()
    semantic: set[str] = set()
    for event in events:
        for ref in _iter_event_refs(event):
            observed.add(ref)
            if ref not in _PLAYBACK_ONLY_REFS and ref.startswith(_SEMANTIC_CLOSURE_PREFIXES):
                semantic.add(ref)
    return observed, semantic


def render_triad_prompt_context(state: NarrationTriadState | dict[str, Any] | None) -> str:
    if state is None:
        return ""
    if isinstance(state, dict):
        open_triads = state.get("open_triads") or []
        resolved_triads = state.get("recently_resolved_triads") or []
    else:
        open_triads = state.open_triads
        resolved_triads = state.recently_resolved_triads
    lines: list[str] = []
    if open_triads:
        lines.append("Open narration continuity:")
        for triad in open_triads[:5]:
            obligations = triad.get("obligations") or []
            label = obligations[0].get("kind") if obligations else "hold_open"
            text = obligations[0].get("text") if obligations else triad.get("triad_id")
            lines.append(f"  - {label}: {text} ({triad.get('status', 'open')})")
    if resolved_triads:
        lines.append("Recently resolved narration continuity:")
        for triad in resolved_triads[:3]:
            lines.append(
                f"  - {triad.get('triad_id')}: {triad.get('status')} "
                f"programme={triad.get('programme_id') or 'none'}"
            )
    return "\n".join(lines)


def _build_speech_triad(
    *,
    text: str,
    context: Any,
    impulse_id: str | None,
    speech_event_id: str,
    speech_act_type: str,
    source_path: str,
    candidate_name: str,
    now: float,
    director_move_refs: list[str] | None = None,
) -> NarrationTriadEnvelope:
    text_hash = utterance_hash(text)
    programme_id, programme_role = _programme_identity(context)
    triad_id = _triad_id(
        source_path=source_path,
        impulse_id=impulse_id,
        speech_event_id=speech_event_id,
        text_hash=text_hash,
    )
    evidence_refs = _evidence_refs(context, impulse_id=impulse_id, candidate_name=candidate_name)
    observations = _observation_items(context, evidence_refs=evidence_refs, now=now)
    assessments = _assessment_items(context, evidence_refs=evidence_refs)
    outcomes = _intended_outcomes(
        text, evidence_refs=evidence_refs, now=now, candidate_name=candidate_name
    )
    return NarrationTriadEnvelope(
        triad_id=triad_id,
        created_at=_iso(now),
        updated_at=_iso(now),
        source_path=source_path,
        impulse_id=impulse_id,
        speech_event_id=speech_event_id,
        speech_act_type=speech_act_type,
        programme_id=programme_id,
        programme_role=programme_role,
        programme_run_ref=f"programme:{programme_id}" if programme_id else None,
        role_state_ref=f"programme_role:{programme_role}" if programme_role else None,
        wcs_snapshot_ref="wcs:audio.broadcast_voice:voice-output-witness",
        utterance_text_ref=f"utterance:{text_hash[:16]}",
        utterance_text_hash=text_hash,
        observation_items=observations,
        assessment_items=assessments,
        intended_outcome_items=outcomes,
        evidence_refs=evidence_refs,
        claim_envelope_refs=["claim_posture:bounded_nonassertive_narration"],
        director_move_refs=director_move_refs or [],
        satisfaction_policy="semantic_witness_required_no_keyword_truth",
        ttl_s=DEFAULT_TTL_S,
        status="open",
        learning_update_allowed=False,
    )


def _intended_outcomes(
    text: str,
    *,
    evidence_refs: list[str],
    now: float,
    candidate_name: str,
) -> list[IntendedOutcomeItem]:
    kinds = obligation_outcome_kinds(text) or ("hold_open",)
    deadline = _iso(now + DEFAULT_TTL_S)
    outcomes: list[IntendedOutcomeItem] = []
    for kind in kinds:
        outcome_id = "outcome-" + hashlib.sha256(f"{kind}:{text}:{now}".encode()).hexdigest()[:12]
        expected = {
            "monitor": "future WCS or capability evidence must update this monitoring claim",
            "re_evaluate": "future posterior or correction evidence must update this re-evaluation",
            "probe": "future evidence must satisfy, block, or no-learn this curiosity",
            "route_attention": "future director/capability evidence must handle this attention debt",
            "hold_open": "future narration must carry this state forward or explicitly resolve it",
        }.get(kind, "future evidence must resolve this intended outcome")
        outcomes.append(
            IntendedOutcomeItem(
                outcome_id=outcome_id,
                text=_outcome_text(kind, text),
                outcome_kind=kind,
                expected_effect=expected,
                required_witness_refs=[
                    "capability_outcome:narration.autonomous_first_system",
                    "wcs:audio.broadcast_voice:voice-output-witness",
                ],
                candidate_recruitment_targets=[candidate_name],
                deadline_at=deadline,
                status="open",
                blocked_reasons=[],
                closure_refs=list(evidence_refs[:4]),
            )
        )
    return outcomes


def _outcome_text(kind: str, text: str) -> str:
    preview = text.strip().replace("\n", " ")[:160]
    if kind == "hold_open":
        return f"Carry forward semantic continuity for narration: {preview}"
    return f"Resolve {kind} obligation opened by narration: {preview}"


def _observation_items(
    context: Any, *, evidence_refs: list[str], now: float
) -> list[ObservationItem]:
    observations: list[ObservationItem] = []
    events = tuple(getattr(context, "chronicle_events", ()) or ())[:3]
    for idx, event in enumerate(events, start=1):
        source = str(event.get("source") or "chronicle")
        payload = event.get("content") or event.get("payload") or {}
        narrative = ""
        if isinstance(payload, dict):
            narrative = str(payload.get("narrative") or payload.get("metric") or "")[:220]
        if not narrative:
            narrative = f"Chronicle event from {source}"
        observations.append(
            ObservationItem(
                observation_id=f"obs-{idx}",
                text=narrative,
                source=source,
                substrate_ref=f"chronicle:{source}",
                evidence_refs=[f"chronicle:{source}", *evidence_refs[:2]],
                freshness="recent",
                claim_mode="operator_visible",
                authority_ceiling="wcs_witness",
                confidence=0.6,
            )
        )
    if not observations:
        observations.append(
            ObservationItem(
                observation_id="obs-context",
                text="No eligible chronicle event was available; narration is bound to current programme, stimmung, and director context.",
                source="autonomous_narrative.context",
                substrate_ref="context:programme-stimmung-director",
                evidence_refs=evidence_refs[:3] or ["context:autonomous_narrative"],
                freshness="unknown",
                claim_mode="not_claim_bearing",
                authority_ceiling="self_report",
                confidence=0.3,
            )
        )
    return observations


def _assessment_items(context: Any, *, evidence_refs: list[str]) -> list[AssessmentItem]:
    stimmung = str(getattr(context, "stimmung_tone", "") or "unknown")
    director = str(getattr(context, "director_activity", "") or "unknown")
    return [
        AssessmentItem(
            assessment_id="assess-context",
            text=f"Narration is carrying current stimmung={stimmung} and director_activity={director}; semantic closure remains witness-required.",
            assessment_kind="stable_but_watch",
            basis_refs=evidence_refs[:4] or ["context:autonomous_narrative"],
            uncertainty=0.5,
            authority_ceiling="self_report",
            risk_flags=[],
        )
    ]


def _programme_identity(context: Any) -> tuple[str | None, str]:
    programme = getattr(context, "programme", None)
    programme_id = getattr(context, "programme_id", None)
    programme_role = getattr(context, "programme_role", None)
    if programme is not None:
        programme_id = getattr(programme, "programme_id", programme_id)
        role = getattr(programme, "role", programme_role)
        programme_role = getattr(role, "value", role)
    return (str(programme_id) if programme_id else None, str(programme_role or "none"))


def _evidence_refs(context: Any, *, impulse_id: str | None, candidate_name: str) -> list[str]:
    programme_id, programme_role = _programme_identity(context)
    refs = [
        "source:autonomous_narrative",
        f"capability:{candidate_name}",
        "wcs:audio.broadcast_voice:voice-output-witness",
        f"programme_role:{programme_role}",
    ]
    if impulse_id:
        refs.append(f"impulse:{impulse_id}")
    if programme_id:
        refs.append(f"programme:{programme_id}")
    events = tuple(getattr(context, "chronicle_events", ()) or ())[:3]
    for event in events:
        source = str(event.get("source") or "chronicle")
        refs.append(f"chronicle:{source}")
    return _dedupe(refs)


def _summary_metrics(envelopes: list[NarrationTriadEnvelope]) -> dict[str, Any]:
    total = len(envelopes)
    open_count = sum(1 for item in envelopes if item.status == "open")
    satisfied = sum(1 for item in envelopes if item.status in {"satisfied", "partially_satisfied"})
    stale = sum(1 for item in envelopes if item.status == "stale")
    blocked = sum(1 for item in envelopes if item.status in {"blocked", "inhibited", "no_learning"})
    return {
        "total": total,
        "open": open_count,
        "satisfied": satisfied,
        "blocked": blocked,
        "stale": stale,
        "orphan_rate": round(open_count / total, 3) if total else 0.0,
        "satisfaction_rate": round(satisfied / total, 3) if total else 0.0,
        "stale_rate": round(stale / total, 3) if total else 0.0,
        "mean_time_to_resolution_s": None,
    }


_TRIAD_EVENT_SALIENCE: dict[str, float] = {
    # All values >= 0.7 (the chronicle-ticker ward's _SALIENCE_THRESHOLD).
    # ``closed`` ranks highest — the moment a triad resolves into
    # satisfied / partially_satisfied lore. ``opened`` and ``updated``
    # are still surface-worthy but rank lower.
    "narration.triad.closed": 0.85,
    "narration.triad.opened": 0.8,
    "narration.triad.updated": 0.75,
}


def _record_triad_chronicle_event(envelope: NarrationTriadEnvelope) -> None:
    event_type = "narration.triad.opened"
    if envelope.status in _CLOSED_STATUSES:
        event_type = "narration.triad.closed"
    elif envelope.status != "open":
        event_type = "narration.triad.updated"
    try:
        trace_id, span_id = current_otel_ids()
        chronicle_record(
            ChronicleEvent(
                ts=_parse_ts(envelope.updated_at) or time.time(),
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=None,
                source="narration_triad",
                event_type=event_type,
                payload={
                    "triad_id": envelope.triad_id,
                    "status": envelope.status,
                    "speech_event_id": envelope.speech_event_id,
                    "programme_id": envelope.programme_id,
                    "source_path": envelope.source_path,
                    "salience": _TRIAD_EVENT_SALIENCE.get(event_type, 0.75),
                },
            )
        )
    except Exception:
        return


try:
    from prometheus_client import Counter

    _TRIAD_STATUS_TOTAL = Counter(
        "narration_triad_status_total",
        "Narration triad ledger appends by status.",
        ("status",),
    )
    _TRIAD_OPEN_TOTAL = Counter("narration_triad_open_total", "Narration triads opened.")
    _TRIAD_SATISFIED_TOTAL = Counter(
        "narration_triad_satisfied_total", "Narration triads semantically satisfied."
    )
    _TRIAD_BLOCKED_TOTAL = Counter(
        "narration_triad_blocked_total", "Narration triads blocked or no-learning."
    )
    _TRIAD_STALE_TOTAL = Counter("narration_triad_stale_total", "Narration triads stale.")
    _TRIAD_CORRECTION_TOTAL = Counter(
        "narration_triad_correction_total", "Narration triads corrected."
    )
    _TRIAD_ORPHAN_TOTAL = Counter(
        "narration_triad_orphan_total", "Narration triads still open at summary time."
    )

except Exception:  # pragma: no cover - prometheus_client optional
    _TRIAD_STATUS_TOTAL = None
    _TRIAD_OPEN_TOTAL = None
    _TRIAD_SATISFIED_TOTAL = None
    _TRIAD_BLOCKED_TOTAL = None
    _TRIAD_STALE_TOTAL = None
    _TRIAD_CORRECTION_TOTAL = None
    _TRIAD_ORPHAN_TOTAL = None


def _record_triad_metric(envelope: NarrationTriadEnvelope) -> None:
    if _TRIAD_STATUS_TOTAL is None:
        return
    _TRIAD_STATUS_TOTAL.labels(status=envelope.status).inc()
    if envelope.status == "open":
        _TRIAD_OPEN_TOTAL.inc()
        _TRIAD_ORPHAN_TOTAL.inc()
    elif envelope.status in {"satisfied", "partially_satisfied"}:
        _TRIAD_SATISFIED_TOTAL.inc()
    elif envelope.status in {"blocked", "inhibited", "no_learning"}:
        _TRIAD_BLOCKED_TOTAL.inc()
    elif envelope.status == "stale":
        _TRIAD_STALE_TOTAL.inc()
    elif envelope.status == "corrected":
        _TRIAD_CORRECTION_TOTAL.inc()


class _ContextProxy:
    def __init__(
        self,
        *,
        programme_id: str | None,
        programme_role: str,
        stimmung_tone: str,
        director_activity: str,
        chronicle_events: tuple[dict[str, Any], ...],
        triad_continuity: dict[str, Any],
    ) -> None:
        self.programme_id = programme_id
        self.programme_role = programme_role
        self.stimmung_tone = stimmung_tone
        self.director_activity = director_activity
        self.chronicle_events = chronicle_events
        self.triad_continuity = triad_continuity
        self.programme = None


def _triad_id(
    *,
    source_path: str,
    impulse_id: str | None,
    speech_event_id: str,
    text_hash: str,
) -> str:
    base = f"{source_path}:{impulse_id or ''}:{speech_event_id}:{text_hash}"
    return "triad-" + hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]


def _dedupe(refs: list[str]) -> list[str]:
    return list(dict.fromkeys(ref for ref in refs if ref))


def _iter_event_refs(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            if key_text.endswith(_REF_SUFFIXES):
                yield from _string_refs(item)
            elif isinstance(item, (dict, list, tuple)):
                yield from _iter_event_refs(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_event_refs(item)


def _string_refs(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, (list, tuple)):
        for item in value:
            if isinstance(item, str):
                yield item
            elif isinstance(item, (dict, list, tuple)):
                yield from _iter_event_refs(item)
    elif isinstance(value, dict):
        yield from _iter_event_refs(value)


def _now(now: float | None) -> float:
    return now if now is not None else time.time()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).isoformat().replace("+00:00", "Z")


def _parse_ts(raw: str) -> float | None:
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


__all__ = [
    "DEFAULT_TTL_S",
    "NarrationTriadEnvelope",
    "NarrationTriadLedger",
    "NarrationTriadState",
    "ObservationItem",
    "AssessmentItem",
    "IntendedOutcomeItem",
    "TRIAD_LEDGER_PATH",
    "TRIAD_STATE_PATH",
    "build_autonomous_narration_triad",
    "build_director_speech_triad",
    "obligation_outcome_kinds",
    "read_triad_state",
    "render_triad_prompt_context",
    "speech_event_id_for_utterance",
    "triad_resolution_refs_from_events",
    "utterance_hash",
]
