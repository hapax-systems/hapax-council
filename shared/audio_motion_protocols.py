"""Audio source-role → motion-protocol proposal layer.

Per cc-task ``audio-reactive-ward-camera-homage-motion-protocols`` (WSJF 8.9,
Phase 0). Builds atop the typed ``shared.audio_source_evidence`` ledger and
turns role-scoped audio activity into typed proposals for camera, ward, and
HOMAGE motion. The proposals are *evidence-bound hypotheses about a programme
moment* — not instructions: the consumer (director / studio_compositor) is
free to refuse them, and they record their own outcome witness.

Phase 0 scope:

- One camera move (``LAYOUT_DRIFT``)
- One ward motion move (``WARD_EMPHASIS``)
- One HOMAGE move (``HOMAGE_PAIR_EMPHASIS``)
- Recency / cooldown / visualizer-governor / public-posture filters
- Visual-outcome witnesses appended to ``MotionWitnessLedger``
- Tests cover music / tts / operator_voice / yt / silence / stale evidence

Out of scope: beat-synced waveform or FFT visuals; expert-system formats;
extended motion vocabularies (transit/orbit/wake/punch-through). The schema
leaves room for those to land as additional kind enums without breaking the
proposal envelope.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.audio_source_evidence import (
    AudioReactiveOutcome,
    AudioSourceEvidence,
    AudioSourceLedger,
    AudioSourceRole,
    FreshnessState,
    PublicPrivatePosture,
)

DEFAULT_COOLDOWN_S: float = 8.0
DEFAULT_LEDGER_TTL_S: float = 6.0


class CameraMoveKind(StrEnum):
    """Camera-layer motion vocabulary. Phase 0 ships only LAYOUT_DRIFT."""

    LAYOUT_DRIFT = "layout_drift"


class WardMoveKind(StrEnum):
    """Ward-layer motion vocabulary. Phase 0 ships only EMPHASIS."""

    EMPHASIS = "emphasis"


class HomageMoveKind(StrEnum):
    """HOMAGE-pair motion vocabulary. Phase 0 ships only PAIR_EMPHASIS."""

    PAIR_EMPHASIS = "pair_emphasis"


MoveLayer = Literal["camera", "ward", "homage"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class MotionProposal(_Frozen):
    """A typed move hypothesis derived from one or more audio source-role rows.

    The proposal carries the source role(s) it derived from, evidence-row IDs
    it consulted, the move kind, parameters, and an outcome — never an
    imperative. ``outcome`` follows ``AudioReactiveOutcome`` semantics:
    ``VERIFIED`` means "ready to execute"; everything else is a refusal with
    a reason populated in ``blocked_reasons``.
    """

    move_layer: MoveLayer
    move_kind: str
    source_roles: tuple[AudioSourceRole, ...] = Field(min_length=1)
    source_evidence_row_ids: tuple[str, ...] = Field(default_factory=tuple)
    parameters: Mapping[str, float | str] = Field(default_factory=dict)
    cooldown_until_epoch: float
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    outcome: AudioReactiveOutcome
    blocked_reasons: tuple[str, ...] = Field(default_factory=tuple)
    proposed_at: str


class MotionWitness(_Frozen):
    """Visual-outcome witness — what the proposal *did* visibly.

    Recorded by the consumer after attempting the move. Even ``NO_OP`` and
    ``BLOCKED`` outcomes get a witness — refusals are evidence too.
    """

    proposal: MotionProposal
    rendered: bool
    rendered_at: str | None = None
    render_evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    notes: str = ""


class MotionWitnessLedger(_Frozen):
    schema_version: Literal[1] = 1
    generated_at: str
    witnesses: tuple[MotionWitness, ...] = Field(default_factory=tuple)


class MotionProtocolRunner:
    """Computes one proposal per layer per tick, gated on freshness, public
    posture, cooldown, and the visualizer-governor.

    State that survives across ticks (per-layer cooldown timers) is held by
    the runner instance; the ledger is read fresh each call.
    """

    # Role → camera kind preference. Music drives DRIFT; TTS and operator
    # voice also drive DRIFT in Phase 0 (less aggressive than full cuts).
    _CAMERA_ROLE_PREFERENCE: tuple[AudioSourceRole, ...] = (
        AudioSourceRole.MUSIC,
        AudioSourceRole.YOUTUBE,
        AudioSourceRole.TTS,
        AudioSourceRole.OPERATOR_VOICE,
    )

    # Role → ward emphasis preference. Operator voice and TTS get ward
    # emphasis (a smaller spatial commitment than camera moves).
    _WARD_ROLE_PREFERENCE: tuple[AudioSourceRole, ...] = (
        AudioSourceRole.OPERATOR_VOICE,
        AudioSourceRole.TTS,
        AudioSourceRole.MUSIC,
        AudioSourceRole.DESK_CONTACT,
    )

    # Role → HOMAGE pair emphasis preference. Music and YT/react drive pair
    # foregrounding (visually rhythmic).
    _HOMAGE_ROLE_PREFERENCE: tuple[AudioSourceRole, ...] = (
        AudioSourceRole.MUSIC,
        AudioSourceRole.YOUTUBE,
    )

    def __init__(
        self,
        *,
        cooldown_window_s: float = DEFAULT_COOLDOWN_S,
        governor_active: bool = True,
        last_move_epochs: Mapping[MoveLayer, float] | None = None,
    ) -> None:
        self._cooldown_s = float(cooldown_window_s)
        self._governor_active = bool(governor_active)
        self._last_move_epochs: dict[MoveLayer, float] = dict(last_move_epochs or {})

    @property
    def last_move_epochs(self) -> dict[MoveLayer, float]:
        return dict(self._last_move_epochs)

    def propose(
        self,
        layer: MoveLayer,
        ledger: AudioSourceLedger,
        *,
        now: float,
    ) -> MotionProposal:
        """Compute the proposal for ``layer`` against ``ledger`` at ``now``."""
        if layer == "camera":
            kind = CameraMoveKind.LAYOUT_DRIFT
            preference = self._CAMERA_ROLE_PREFERENCE
        elif layer == "ward":
            kind = WardMoveKind.EMPHASIS
            preference = self._WARD_ROLE_PREFERENCE
        elif layer == "homage":
            kind = HomageMoveKind.PAIR_EMPHASIS
            preference = self._HOMAGE_ROLE_PREFERENCE
        else:  # pragma: no cover - guarded by Literal
            raise ValueError(f"unknown move layer: {layer!r}")

        proposed_at = _iso_from_epoch(now)
        cooldown_until = self._last_move_epochs.get(layer, 0.0) + self._cooldown_s

        if not self._governor_active:
            return self._refusal(
                layer=layer,
                kind=str(kind),
                reasons=("visualizer_governor_inactive",),
                cooldown_until=cooldown_until,
                proposed_at=proposed_at,
            )

        if now < cooldown_until:
            return self._refusal(
                layer=layer,
                kind=str(kind),
                reasons=("cooldown_active",),
                cooldown_until=cooldown_until,
                proposed_at=proposed_at,
            )

        candidate = self._select_candidate(ledger, preference)
        if candidate is None:
            return MotionProposal(
                move_layer=layer,
                move_kind=str(kind),
                source_roles=(AudioSourceRole.UNKNOWN,),
                cooldown_until_epoch=cooldown_until,
                outcome=AudioReactiveOutcome.NO_OP,
                blocked_reasons=("no_active_source",),
                proposed_at=proposed_at,
            )

        # Refusal: stale.
        if candidate.freshness.state is not FreshnessState.FRESH:
            return self._refusal(
                layer=layer,
                kind=str(kind),
                reasons=("stale_evidence",),
                cooldown_until=cooldown_until,
                proposed_at=proposed_at,
                outcome_override=AudioReactiveOutcome.STALE,
                source_roles=(candidate.role,),
                source_row_ids=(candidate.row_id,),
                evidence_refs=candidate.evidence_envelope_refs,
            )

        # Refusal: public-posture blocked. Camera and HOMAGE are public-facing
        # and require a non-blocked posture; ward emphasis is allowed in
        # private-only mode (no broadcast egress).
        if layer in ("camera", "homage"):
            if candidate.public_private_posture is PublicPrivatePosture.BLOCKED:
                return self._refusal(
                    layer=layer,
                    kind=str(kind),
                    reasons=("public_posture_blocked",),
                    cooldown_until=cooldown_until,
                    proposed_at=proposed_at,
                    source_roles=(candidate.role,),
                    source_row_ids=(candidate.row_id,),
                    evidence_refs=candidate.evidence_envelope_refs,
                )

        # Refusal: missing the relevant downstream permission.
        if layer == "camera" and not candidate.permissions.director_move:
            return self._refusal(
                layer=layer,
                kind=str(kind),
                reasons=("director_move_permission_absent",),
                cooldown_until=cooldown_until,
                proposed_at=proposed_at,
                source_roles=(candidate.role,),
                source_row_ids=(candidate.row_id,),
                evidence_refs=candidate.evidence_envelope_refs,
            )
        if layer in ("ward", "homage") and not candidate.permissions.visual_modulation:
            return self._refusal(
                layer=layer,
                kind=str(kind),
                reasons=("visual_modulation_permission_absent",),
                cooldown_until=cooldown_until,
                proposed_at=proposed_at,
                source_roles=(candidate.role,),
                source_row_ids=(candidate.row_id,),
                evidence_refs=candidate.evidence_envelope_refs,
            )

        # Verified.
        params = self._parameters_for(layer, candidate)
        new_cooldown_until = now + self._cooldown_s
        proposal = MotionProposal(
            move_layer=layer,
            move_kind=str(kind),
            source_roles=(candidate.role,),
            source_evidence_row_ids=(candidate.row_id,),
            parameters=params,
            cooldown_until_epoch=new_cooldown_until,
            evidence_refs=candidate.evidence_envelope_refs,
            outcome=AudioReactiveOutcome.VERIFIED,
            proposed_at=proposed_at,
        )
        self._last_move_epochs[layer] = now
        return proposal

    @staticmethod
    def _select_candidate(
        ledger: AudioSourceLedger,
        preference: tuple[AudioSourceRole, ...],
    ) -> AudioSourceEvidence | None:
        """Pick the highest-preference active row, ties broken by RMS desc."""
        by_role: dict[AudioSourceRole, list[AudioSourceEvidence]] = {}
        for row in ledger.source_rows:
            if row.active:
                by_role.setdefault(row.role, []).append(row)
        for role in preference:
            rows = by_role.get(role, [])
            if rows:
                return max(rows, key=lambda r: r.signal_metrics.rms)
        return None

    @staticmethod
    def _parameters_for(
        layer: MoveLayer,
        candidate: AudioSourceEvidence,
    ) -> dict[str, float | str]:
        """Translate the source signal into move-shape parameters.

        Phase 0 keeps the parameter surface minimal: a single ``intensity``
        scalar (RMS-derived, clamped 0..1) and a textual ``source_role`` for
        downstream debug. Per-layer kinds may add their own keys later.
        """
        intensity = max(0.0, min(1.0, candidate.signal_metrics.rms * 4.0))
        params: dict[str, float | str] = {
            "intensity": round(intensity, 4),
            "source_role": candidate.role.value,
        }
        if layer == "camera":
            params["drift_seconds"] = 4.0
        elif layer == "ward":
            params["emphasis_seconds"] = 2.5
        elif layer == "homage":
            params["pair_seconds"] = 3.0
        return params

    @staticmethod
    def _refusal(
        *,
        layer: MoveLayer,
        kind: str,
        reasons: tuple[str, ...],
        cooldown_until: float,
        proposed_at: str,
        outcome_override: AudioReactiveOutcome | None = None,
        source_roles: tuple[AudioSourceRole, ...] = (AudioSourceRole.UNKNOWN,),
        source_row_ids: tuple[str, ...] = (),
        evidence_refs: tuple[str, ...] = (),
    ) -> MotionProposal:
        return MotionProposal(
            move_layer=layer,
            move_kind=kind,
            source_roles=source_roles,
            source_evidence_row_ids=source_row_ids,
            cooldown_until_epoch=cooldown_until,
            evidence_refs=evidence_refs,
            outcome=outcome_override or AudioReactiveOutcome.BLOCKED,
            blocked_reasons=reasons,
            proposed_at=proposed_at,
        )


def record_witness(
    ledger: MotionWitnessLedger | None,
    proposal: MotionProposal,
    *,
    rendered: bool,
    rendered_at: float | None = None,
    render_evidence_refs: tuple[str, ...] = (),
    notes: str = "",
) -> MotionWitnessLedger:
    """Append a witness for ``proposal`` to (a possibly-empty) ledger."""
    base = ledger or MotionWitnessLedger(generated_at=_iso_from_epoch(0.0))
    witness = MotionWitness(
        proposal=proposal,
        rendered=rendered,
        rendered_at=_iso_from_epoch(rendered_at) if rendered_at is not None else None,
        render_evidence_refs=render_evidence_refs,
        notes=notes,
    )
    return MotionWitnessLedger(
        generated_at=_iso_from_epoch(rendered_at if rendered_at is not None else 0.0),
        witnesses=base.witnesses + (witness,),
    )


def _iso_from_epoch(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat().replace("+00:00", "Z")
