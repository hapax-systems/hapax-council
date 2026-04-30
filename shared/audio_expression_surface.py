"""Semantic FX expression planning for Hapax voice/programme audio.

The semantic voice router proves where audio may go. This module adds the
expression contract that proves whether public Hapax voice may speak at all:
public voice needs a witnessed wet/FX plan, while dry voice remains private,
diagnostic, emergency, or dry-run only.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from shared.evil_pet_presets import PRESETS, EvilPetPreset
from shared.s4_scenes import SCENES, S4Scene
from shared.voice_output_router import (
    DEFAULT_PRIVATE_MONITOR_STATUS_PATH,
    VoiceOutputDestination,
    VoiceRouteResult,
    resolve_voice_output_route,
    target_for_route,
)

DEFAULT_FX_DEVICE_WITNESS_PATH = Path("/dev/shm/hapax-audio/fx-device-witness.json")


class AudioPublicPosture(StrEnum):
    """Public/private posture for an audio-expression request."""

    PRIVATE = "private"
    DRY_RUN = "dry_run"
    PUBLIC_LIVE = "public_live"
    PUBLIC_ARCHIVE = "public_archive"
    PUBLIC_MONETIZABLE = "public_monetizable"


PUBLIC_POSTURES: frozenset[AudioPublicPosture] = frozenset(
    {
        AudioPublicPosture.PUBLIC_LIVE,
        AudioPublicPosture.PUBLIC_ARCHIVE,
        AudioPublicPosture.PUBLIC_MONETIZABLE,
    }
)


class AudioExpressionRegister(StrEnum):
    """Operator-facing semantic FX registers."""

    CLEAR_WET = "clear_wet"
    MEMORY = "memory"
    TAPE = "tape"
    RADIO = "radio"
    BROKEN_GRAIN = "broken_grain"
    DARK = "dark"
    NERVOUS_DELAY = "nervous_delay"
    CONTROLLED_VIBRATO = "controlled_vibrato"
    OBLITERATED = "obliterated"


class FxSelectedRoute(StrEnum):
    """Expression surface selected for the plan."""

    EVIL_PET = "evil_pet"
    S4 = "s4"
    DUAL_FX = "dual_fx"
    PRIVATE_MONITOR = "private_monitor"
    DRY_RUN_PROBE = "dry_run_probe"
    HELD = "held"


class FxPlanState(StrEnum):
    """Whether a plan can be executed."""

    PLANNED = "planned"
    HELD = "held"
    BLOCKED = "blocked"


class FxFallback(StrEnum):
    """Allowed fallback policy for the plan."""

    NONE = "none"
    HELD = "held"
    PRIVATE_ONLY = "private_only"
    SAFE_WET_BASELINE = "safe_wet_baseline"
    NO_PUBLIC_SPEECH = "no_public_speech"


class FxTimingPolicy(StrEnum):
    """When an FX plan may be applied."""

    UTTERANCE_BOUNDARY = "utterance_boundary"
    PROGRAMME_BOUNDARY = "programme_boundary"
    CROSSFADE = "crossfade"
    EMERGENCY_HOLD = "emergency_hold"


class FxOutcomeState(StrEnum):
    """Witness result for an attempted FX plan."""

    SATISFIED = "satisfied"
    PARTIAL = "partial"
    FAILED = "failed"
    BLOCKED = "blocked"
    STALE = "stale"
    INTERRUPTED = "interrupted"


class FxRiskClamps(BaseModel):
    """Bounded controls that prevent semantic intensity from becoming risk."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    resonance: float = Field(default=0.65, ge=0.0, le=1.0)
    shimmer: float = Field(default=0.0, ge=0.0, le=1.0)
    feedback: float = Field(default=0.2, ge=0.0, le=1.0)
    gain: float = Field(default=0.75, ge=0.0, le=1.0)
    wetness: float = Field(default=0.95, ge=0.0, le=1.0)
    stepped_cc_crossings: int = Field(default=4, ge=0, le=16)
    saturation: float = Field(default=0.45, ge=0.0, le=1.0)
    reverb_tail: float = Field(default=0.55, ge=0.0, le=1.0)
    route_leak_risk: float = Field(default=0.0, ge=0.0, le=1.0)


class AudioExpressionIntent(BaseModel):
    """Semantic request to make voice/programme audio expressive."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    intent_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_impingement_ref: str | None = None
    programme_ref: str | None = None
    director_move_ref: str | None = None
    speech_act_ref: str | None = None
    semantic_basis: tuple[str, ...] = Field(default_factory=tuple)
    expression_register: AudioExpressionRegister = AudioExpressionRegister.CLEAR_WET
    intended_outcome: str
    clarity_budget: float = Field(default=0.85, ge=0.0, le=1.0)
    public_posture: AudioPublicPosture = AudioPublicPosture.PRIVATE
    risk_clamps: FxRiskClamps = Field(default_factory=FxRiskClamps)
    world_surface_refs: tuple[str, ...] = Field(default_factory=tuple)
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)


class FxCcCommand(BaseModel):
    """One bounded MIDI CC command in an Evil Pet overlay."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    device: str
    channel: int = Field(ge=0, le=15)
    cc: int = Field(ge=0, le=127)
    value: int = Field(ge=0, le=127)
    ramp_ms: int = Field(default=120, ge=0, le=5000)
    hold_ms: int = Field(default=0, ge=0, le=60000)
    release_ms: int = Field(default=250, ge=0, le=60000)
    note: str


class FxDeviceWitness(BaseModel):
    """Current evidence for FX hardware and route readiness."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    max_age_s: float = Field(default=300.0, gt=0.0)
    evil_pet_midi: bool = False
    evil_pet_sd_pack: bool = False
    evil_pet_firmware_verified: bool = False
    s4_midi: bool = False
    s4_audio: bool = False
    l12_route: bool = False
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)

    def is_fresh(self, *, now: datetime | None = None) -> bool:
        ts = now if now is not None else datetime.now(UTC)
        observed = self.observed_at
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=UTC)
        return (ts - observed).total_seconds() <= self.max_age_s

    @property
    def evil_pet_ready(self) -> bool:
        return self.evil_pet_midi and self.evil_pet_sd_pack and self.evil_pet_firmware_verified

    @property
    def s4_ready(self) -> bool:
        return self.s4_midi and self.s4_audio and self.l12_route


def load_fx_device_witness(
    path: Path = DEFAULT_FX_DEVICE_WITNESS_PATH,
    *,
    now: datetime | None = None,
) -> FxDeviceWitness:
    """Load FX device evidence; missing or invalid evidence fails closed."""

    ts = now if now is not None else datetime.now(UTC)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("FX device witness must be a JSON object")
        return FxDeviceWitness.model_validate(payload)
    except (OSError, TypeError, ValueError):
        return FxDeviceWitness(
            observed_at=ts,
            max_age_s=300.0,
            evil_pet_midi=False,
            evil_pet_sd_pack=False,
            evil_pet_firmware_verified=False,
            s4_midi=False,
            s4_audio=False,
            l12_route=False,
            evidence_refs=("fx-device-witness:missing-or-invalid",),
        )


class FxPlan(BaseModel):
    """Resolved expression plan; executable only when ``state`` is planned."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    plan_id: str
    intent_id: str
    state: FxPlanState
    selected_route: FxSelectedRoute
    evil_pet_baseline: str | None = None
    evil_pet_baseline_hash: str | None = None
    evil_pet_cc_overlay: tuple[FxCcCommand, ...] = Field(default_factory=tuple)
    s4_scene: str | None = None
    s4_scene_hash: str | None = None
    s4_params: tuple[FxCcCommand, ...] = Field(default_factory=tuple)
    route_plan: VoiceRouteResult
    timing_policy: FxTimingPolicy
    no_dry_invariant: bool
    expected_observables: tuple[str, ...] = Field(default_factory=tuple)
    fallback: FxFallback
    operator_visible_reason: str
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)

    @property
    def playback_target(self) -> str | None:
        if self.state != FxPlanState.PLANNED:
            return None
        return target_for_route(self.route_plan)


class FxOutcomeWitness(BaseModel):
    """Outcome evidence recorded before posterior learning."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    witness_id: str
    plan_id: str
    executed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    device_reachability: FxDeviceWitness
    route_evidence: tuple[str, ...] = Field(default_factory=tuple)
    audio_probe: tuple[str, ...] = Field(default_factory=tuple)
    egress_evidence: tuple[str, ...] = Field(default_factory=tuple)
    observed_register: AudioExpressionRegister | None = None
    outcome_state: FxOutcomeState
    mismatch_reasons: tuple[str, ...] = Field(default_factory=tuple)
    posterior_update_allowed: bool = False

    @classmethod
    def grounded(
        cls,
        *,
        witness_id: str,
        plan: FxPlan,
        device_reachability: FxDeviceWitness,
        route_evidence: tuple[str, ...],
        audio_probe: tuple[str, ...],
        egress_evidence: tuple[str, ...],
        observed_register: AudioExpressionRegister,
    ) -> FxOutcomeWitness:
        """Build a witness that permits learning only after all evidence exists."""

        grounded = bool(route_evidence and audio_probe and egress_evidence)
        state = FxOutcomeState.SATISFIED if grounded else FxOutcomeState.PARTIAL
        return cls(
            witness_id=witness_id,
            plan_id=plan.plan_id,
            device_reachability=device_reachability,
            route_evidence=route_evidence,
            audio_probe=audio_probe,
            egress_evidence=egress_evidence,
            observed_register=observed_register,
            outcome_state=state,
            mismatch_reasons=() if grounded else ("missing_grounded_witness_component",),
            posterior_update_allowed=grounded,
        )


RouteResolver = Callable[[VoiceOutputDestination], VoiceRouteResult]


def resolve_fx_plan(
    intent: AudioExpressionIntent,
    *,
    device_witness: FxDeviceWitness,
    private_monitor_status_path: Path = DEFAULT_PRIVATE_MONITOR_STATUS_PATH,
    route_resolver: RouteResolver | None = None,
    now: datetime | None = None,
) -> FxPlan:
    """Resolve an expression intent into an executable or held FX plan."""

    ts = now if now is not None else datetime.now(UTC)
    resolver = route_resolver or (
        lambda destination: resolve_voice_output_route(
            destination,
            private_monitor_status_path=private_monitor_status_path,
        )
    )

    if intent.public_posture == AudioPublicPosture.DRY_RUN:
        route = resolver(VoiceOutputDestination.DRY_RUN_PROBE)
        return _plan(
            intent,
            state=FxPlanState.PLANNED,
            selected_route=FxSelectedRoute.DRY_RUN_PROBE,
            route=route,
            timing_policy=FxTimingPolicy.EMERGENCY_HOLD,
            no_dry_invariant=False,
            fallback=FxFallback.HELD,
            operator_visible_reason="Dry-run probe records expression intent without playback.",
            evidence_refs=intent.evidence_refs + ("route:dry_run.voice_probe",),
        )

    if intent.public_posture == AudioPublicPosture.PRIVATE:
        route = resolver(VoiceOutputDestination.PRIVATE_ASSISTANT_MONITOR)
        if not route.accepted:
            return _held(
                intent,
                route=route,
                reason_code=route.reason_code,
                operator_visible_reason=route.operator_visible_reason,
                fallback=FxFallback.HELD,
            )
        return _plan(
            intent,
            state=FxPlanState.PLANNED,
            selected_route=FxSelectedRoute.PRIVATE_MONITOR,
            route=route,
            timing_policy=FxTimingPolicy.UTTERANCE_BOUNDARY,
            no_dry_invariant=False,
            fallback=FxFallback.PRIVATE_ONLY,
            operator_visible_reason=(
                "Private diagnostic voice may use the exact private monitor without public FX."
            ),
            expected_observables=("private_monitor_route_bound",),
            evidence_refs=intent.evidence_refs + route.evidence_refs,
        )

    route = resolver(VoiceOutputDestination.PUBLIC_BROADCAST)
    if not route.accepted:
        return _held(
            intent,
            route=route,
            reason_code=route.reason_code,
            operator_visible_reason=route.operator_visible_reason,
        )

    freshness_reason = _device_freshness_reason(device_witness, now=ts)
    if freshness_reason is not None:
        return _held(
            intent,
            route=route,
            reason_code=freshness_reason,
            operator_visible_reason=(
                "Public Hapax voice is held until current FX device witness is available."
            ),
        )

    selected = _select_public_fx_route(device_witness)
    if selected == FxSelectedRoute.HELD:
        return _held(
            intent,
            route=route,
            reason_code="public_fx_witness_missing",
            operator_visible_reason=(
                "Public Hapax voice is held because no witnessed wet FX route is available."
            ),
        )

    preset = _preset_for_register(intent.expression_register)
    scene = (
        _scene_for_register(intent.expression_register)
        if selected != FxSelectedRoute.EVIL_PET
        else None
    )
    return _plan(
        intent,
        state=FxPlanState.PLANNED,
        selected_route=selected,
        evil_pet_baseline=preset.name if selected != FxSelectedRoute.S4 else None,
        evil_pet_baseline_hash=(_hash_preset(preset) if selected != FxSelectedRoute.S4 else None),
        evil_pet_cc_overlay=(
            _cc_overlay_for_register(intent.expression_register, intent.risk_clamps)
            if selected != FxSelectedRoute.S4
            else ()
        ),
        s4_scene=scene.name if scene is not None else None,
        s4_scene_hash=_hash_scene(scene) if scene is not None else None,
        s4_params=_s4_params_for_scene(scene, intent.risk_clamps) if scene is not None else (),
        route=route,
        timing_policy=FxTimingPolicy.UTTERANCE_BOUNDARY,
        no_dry_invariant=True,
        fallback=FxFallback.SAFE_WET_BASELINE,
        operator_visible_reason="Public Hapax voice has a witnessed wet FX expression plan.",
        expected_observables=(
            "public_broadcast_route_bound",
            "wet_fx_route_present",
            "intelligibility_budget_respected",
        ),
        evidence_refs=intent.evidence_refs + route.evidence_refs + device_witness.evidence_refs,
    )


def _plan(
    intent: AudioExpressionIntent,
    *,
    state: FxPlanState,
    selected_route: FxSelectedRoute,
    route: VoiceRouteResult,
    timing_policy: FxTimingPolicy,
    no_dry_invariant: bool,
    fallback: FxFallback,
    operator_visible_reason: str,
    evil_pet_baseline: str | None = None,
    evil_pet_baseline_hash: str | None = None,
    evil_pet_cc_overlay: tuple[FxCcCommand, ...] = (),
    s4_scene: str | None = None,
    s4_scene_hash: str | None = None,
    s4_params: tuple[FxCcCommand, ...] = (),
    expected_observables: tuple[str, ...] = (),
    evidence_refs: tuple[str, ...] = (),
) -> FxPlan:
    return FxPlan(
        plan_id=f"fx-plan:{intent.intent_id}",
        intent_id=intent.intent_id,
        state=state,
        selected_route=selected_route,
        evil_pet_baseline=evil_pet_baseline,
        evil_pet_baseline_hash=evil_pet_baseline_hash,
        evil_pet_cc_overlay=evil_pet_cc_overlay,
        s4_scene=s4_scene,
        s4_scene_hash=s4_scene_hash,
        s4_params=s4_params,
        route_plan=route,
        timing_policy=timing_policy,
        no_dry_invariant=no_dry_invariant,
        expected_observables=expected_observables,
        fallback=fallback,
        operator_visible_reason=operator_visible_reason,
        evidence_refs=evidence_refs,
    )


def _held(
    intent: AudioExpressionIntent,
    *,
    route: VoiceRouteResult,
    reason_code: str,
    operator_visible_reason: str,
    fallback: FxFallback = FxFallback.NO_PUBLIC_SPEECH,
) -> FxPlan:
    return _plan(
        intent,
        state=FxPlanState.HELD,
        selected_route=FxSelectedRoute.HELD,
        route=route,
        timing_policy=FxTimingPolicy.EMERGENCY_HOLD,
        no_dry_invariant=intent.public_posture in PUBLIC_POSTURES,
        fallback=fallback,
        operator_visible_reason=f"{operator_visible_reason} ({reason_code})",
        expected_observables=("no_public_speech",),
        evidence_refs=intent.evidence_refs + route.evidence_refs,
    )


def _device_freshness_reason(
    device_witness: FxDeviceWitness,
    *,
    now: datetime,
) -> str | None:
    if not device_witness.is_fresh(now=now):
        return "fx_device_witness_stale"
    if device_witness.evil_pet_sd_pack is False and device_witness.s4_ready is False:
        return "evil_pet_sd_pack_missing"
    return None


def _select_public_fx_route(device_witness: FxDeviceWitness) -> FxSelectedRoute:
    if device_witness.evil_pet_ready and device_witness.s4_ready:
        return FxSelectedRoute.DUAL_FX
    if device_witness.evil_pet_ready:
        return FxSelectedRoute.EVIL_PET
    if device_witness.s4_ready:
        return FxSelectedRoute.S4
    return FxSelectedRoute.HELD


def _preset_for_register(register: AudioExpressionRegister) -> EvilPetPreset:
    name = {
        AudioExpressionRegister.CLEAR_WET: "hapax-bypass",
        AudioExpressionRegister.MEMORY: "hapax-memory",
        AudioExpressionRegister.TAPE: "hapax-bed-music",
        AudioExpressionRegister.RADIO: "hapax-radio",
        AudioExpressionRegister.BROKEN_GRAIN: "hapax-granular-wash",
        AudioExpressionRegister.DARK: "hapax-underwater",
        AudioExpressionRegister.NERVOUS_DELAY: "hapax-broadcast-ghost",
        AudioExpressionRegister.CONTROLLED_VIBRATO: "hapax-s4-companion",
        AudioExpressionRegister.OBLITERATED: "hapax-obliterated",
    }[register]
    return PRESETS[name]


def _scene_for_register(register: AudioExpressionRegister) -> S4Scene:
    name = {
        AudioExpressionRegister.CLEAR_WET: "VOCAL-COMPANION",
        AudioExpressionRegister.MEMORY: "MEMORY-COMPANION",
        AudioExpressionRegister.TAPE: "MUSIC-BED",
        AudioExpressionRegister.RADIO: "VOCAL-COMPANION",
        AudioExpressionRegister.BROKEN_GRAIN: "VOCAL-MOSAIC",
        AudioExpressionRegister.DARK: "UNDERWATER-COMPANION",
        AudioExpressionRegister.NERVOUS_DELAY: "VOCAL-MOSAIC",
        AudioExpressionRegister.CONTROLLED_VIBRATO: "VOCAL-COMPANION",
        AudioExpressionRegister.OBLITERATED: "SONIC-RITUAL",
    }[register]
    return SCENES[name]


def _cc_overlay_for_register(
    register: AudioExpressionRegister,
    clamps: FxRiskClamps,
) -> tuple[FxCcCommand, ...]:
    preset = _preset_for_register(register)
    wet_value = _clamp_cc(preset.ccs.get(40, 95), clamps.wetness)
    resonance_value = _clamp_cc(preset.ccs.get(71, 25), clamps.resonance)
    shimmer_value = _clamp_cc(preset.ccs.get(94, 0), clamps.shimmer)
    saturation_value = _clamp_cc(preset.ccs.get(39, 38), clamps.saturation)
    return (
        FxCcCommand(
            device="evil_pet",
            channel=0,
            cc=40,
            value=wet_value,
            note="wet/dry mix clamped by expression-surface wetness budget",
        ),
        FxCcCommand(
            device="evil_pet",
            channel=0,
            cc=71,
            value=resonance_value,
            note="filter resonance clamped by expression-surface risk budget",
        ),
        FxCcCommand(
            device="evil_pet",
            channel=0,
            cc=94,
            value=shimmer_value,
            note="shimmer clamped; shimmer cannot imply truth or grounding",
        ),
        FxCcCommand(
            device="evil_pet",
            channel=0,
            cc=39,
            value=saturation_value,
            note="saturation clamped by expression-surface risk budget",
        ),
    )[: max(0, min(4, clamps.stepped_cc_crossings))]


def _s4_params_for_scene(
    scene: S4Scene,
    clamps: FxRiskClamps,
) -> tuple[FxCcCommand, ...]:
    limit = max(0, min(4, clamps.stepped_cc_crossings))
    out: list[FxCcCommand] = []
    for cc, value in tuple(sorted(scene.ccs.items()))[:limit]:
        out.append(
            FxCcCommand(
                device="s4",
                channel=0,
                cc=cc,
                value=_clamp_cc(value, clamps.feedback if cc in {80, 81} else clamps.reverb_tail),
                note=f"S-4 {scene.name} parameter clamped by expression-surface budget",
            )
        )
    return tuple(out)


def _clamp_cc(value: int, clamp: float) -> int:
    return max(0, min(127, min(value, round(127 * clamp))))


def _hash_preset(preset: EvilPetPreset) -> str:
    payload = {"name": preset.name, "description": preset.description, "ccs": preset.ccs}
    return _hash_payload(payload)


def _hash_scene(scene: S4Scene) -> str:
    payload = {
        "name": scene.name,
        "program_number": scene.program_number,
        "material": scene.material,
        "granular": scene.granular,
        "filter": scene.filter,
        "color": scene.color,
        "space": scene.space,
        "ccs": scene.ccs,
    }
    return _hash_payload(payload)


def _hash_payload(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "AudioExpressionIntent",
    "AudioExpressionRegister",
    "AudioPublicPosture",
    "DEFAULT_FX_DEVICE_WITNESS_PATH",
    "FxCcCommand",
    "FxDeviceWitness",
    "FxFallback",
    "FxOutcomeState",
    "FxOutcomeWitness",
    "FxPlan",
    "FxPlanState",
    "FxRiskClamps",
    "FxSelectedRoute",
    "FxTimingPolicy",
    "PUBLIC_POSTURES",
    "load_fx_device_witness",
    "resolve_fx_plan",
]
