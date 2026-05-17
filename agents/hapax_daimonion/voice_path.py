"""Voice-path router — tier → audio-path selection (dual-FX Phase 3).

Phase 3 of docs/superpowers/plans/2026-04-20-dual-fx-routing-plan.md.
Maps a ``VoiceTier`` to one of four addressable paths:

- ``dry``: diagnostic/private/emergency only, no public expression default.
- ``radio``: S-4 USB-direct pitched/reverb without granular.
- ``evil_pet``: Ryzen → L6 ch 5 → AUX 1 → Evil Pet → return.
- ``both``: parallel — S-4 direct alongside Evil Pet for wide stereo.

The path decision is SOFT — the router returns a suggested path given
current tier + caller context, never enforces it. Downstream wiring
(``VocalChainCapability``, ``engine_gate.apply_tier_gated``) reads the
choice and switches the PipeWire route. Operator override via the
``hapax-voice-tier`` CLI writes a SHM flag this router checks first.

Data source: ``config/voice-paths.yaml``. Keeps the mapping as
data rather than code so the operator can hand-tune tier→path biases
without a rebuild.

Reference:
    - docs/research/2026-04-20-dual-fx-routing-design.md
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

import yaml

from shared.voice_tier import TIER_NAMES, VoiceTier

_DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config" / "voice-paths.yaml"


class VoicePath(StrEnum):
    """Addressable voice routing paths.

    String values match the YAML keys in ``config/voice-paths.yaml``
    so config edits round-trip through the enum parser without a
    separate mapping layer.
    """

    DRY = "dry"
    RADIO = "radio"
    EVIL_PET = "evil_pet"
    BOTH = "both"
    HELD = "held"


@dataclass(frozen=True)
class PathConfig:
    """Single-path config from voice-paths.yaml."""

    path: VoicePath
    description: str
    sink: str
    via_evil_pet: bool
    via_s4: bool
    public_expression_allowed: bool
    default_for_tiers: frozenset[str]
    dry_bypass_sink: str | None = None


@dataclass(frozen=True)
class VoicePathDecision:
    """Production voice-path decision after expression-surface witness gating."""

    path: VoicePath
    accepted: bool
    reason_code: str
    operator_visible_reason: str


def load_paths(path: Path | None = None) -> dict[VoicePath, PathConfig]:
    """Parse ``config/voice-paths.yaml`` into a ``{VoicePath: PathConfig}`` map."""
    source = path if path is not None else _DEFAULT_CONFIG
    data = yaml.safe_load(source.read_text())
    out: dict[VoicePath, PathConfig] = {}
    for key, raw in data.get("paths", {}).items():
        vp = VoicePath(key)
        out[vp] = PathConfig(
            path=vp,
            description=raw.get("description", ""),
            sink=raw["sink"],
            via_evil_pet=bool(raw.get("via_evil_pet", False)),
            via_s4=bool(raw.get("via_s4", False)),
            public_expression_allowed=bool(raw.get("public_expression_allowed", True)),
            default_for_tiers=frozenset(raw.get("default_for_tiers", [])),
            dry_bypass_sink=raw.get("dry_bypass_sink"),
        )
    return out


def _tier_canonical(tier: VoiceTier) -> str:
    """Return the ``TIER_NAMES`` canonical name with dashes→underscores.

    YAML uses ``broadcast_ghost``/``granular_wash``; ``TIER_NAMES``
    stores the dash form. Normalise so the comparison is consistent.
    """
    return TIER_NAMES[tier].replace("-", "_")


def select_voice_path(
    tier: VoiceTier,
    paths: dict[VoicePath, PathConfig] | None = None,
) -> VoicePath:
    """Pick the default voice path for a tier.

    First path whose ``default_for_tiers`` contains the canonical tier
    name wins. If no path claims the tier, fall back to ``EVIL_PET``
    when available so an expressive route does not silently become dry.
    ``DRY`` remains addressable for private/diagnostic/emergency callers
    but is not a public/persona default.
    """
    data = paths if paths is not None else load_paths()
    canonical = _tier_canonical(tier)
    for path_cfg in data.values():
        if canonical in path_cfg.default_for_tiers:
            return path_cfg.path
    return VoicePath.HELD


def resolve_public_voice_path(
    tier: VoiceTier | int,
    *,
    device_witness_provider: Callable[[], object] | None = None,
    now: datetime | None = None,
) -> VoicePathDecision:
    """Resolve a public/default voice path through the FX expression gate.

    ``select_voice_path`` is the data-level tier mapping. This production
    decision is stricter: no wet route is returned unless
    ``shared.audio_expression_surface.resolve_fx_plan`` accepts current FX
    device evidence. Missing/stale evidence therefore resolves to ``HELD``.
    """

    from shared.audio_expression_surface import (
        AudioExpressionIntent,
        AudioPublicPosture,
        FxDeviceWitness,
        FxPlanState,
        FxSelectedRoute,
        load_fx_device_witness,
        resolve_fx_plan,
    )

    ts = now if now is not None else datetime.now(UTC)
    tier_enum = tier if isinstance(tier, VoiceTier) else VoiceTier(int(tier))
    raw_witness = (
        device_witness_provider()
        if device_witness_provider is not None
        else load_fx_device_witness(now=ts)
    )
    witness = (
        raw_witness
        if isinstance(raw_witness, FxDeviceWitness)
        else FxDeviceWitness.model_validate(raw_witness)
    )
    intent = AudioExpressionIntent(
        intent_id=f"voice-tier:{_tier_canonical(tier_enum)}",
        created_at=ts,
        source_impingement_ref="vocal_chain:voice-tier",
        speech_act_ref="voice-tier:default-public",
        semantic_basis=("voice-tier", _tier_canonical(tier_enum)),
        expression_register=_register_for_tier(tier_enum),
        intended_outcome="Public Hapax voice remains marked by witnessed wet FX.",
        clarity_budget=0.85,
        public_posture=AudioPublicPosture.PUBLIC_LIVE,
        evidence_refs=("voice-path:public-default",),
    )
    plan = resolve_fx_plan(intent, device_witness=witness, now=ts)
    if plan.state != FxPlanState.PLANNED:
        return VoicePathDecision(
            path=VoicePath.HELD,
            accepted=False,
            reason_code=plan.operator_visible_reason,
            operator_visible_reason=(
                "Public/default voice path held because FX expression evidence did not pass."
            ),
        )

    path = {
        FxSelectedRoute.EVIL_PET: VoicePath.EVIL_PET,
        FxSelectedRoute.S4: VoicePath.RADIO,
        FxSelectedRoute.DUAL_FX: VoicePath.BOTH,
    }.get(plan.selected_route, VoicePath.HELD)
    return VoicePathDecision(
        path=path,
        accepted=path is not VoicePath.HELD,
        reason_code=plan.route_plan.reason_code,
        operator_visible_reason=plan.operator_visible_reason,
    )


def _register_for_tier(tier: VoiceTier):
    from shared.audio_expression_surface import AudioExpressionRegister

    return {
        VoiceTier.UNADORNED: AudioExpressionRegister.CLEAR_WET,
        VoiceTier.RADIO: AudioExpressionRegister.RADIO,
        VoiceTier.BROADCAST_GHOST: AudioExpressionRegister.CLEAR_WET,
        VoiceTier.MEMORY: AudioExpressionRegister.MEMORY,
        VoiceTier.UNDERWATER: AudioExpressionRegister.DARK,
        VoiceTier.GRANULAR_WASH: AudioExpressionRegister.BROKEN_GRAIN,
        VoiceTier.OBLITERATED: AudioExpressionRegister.OBLITERATED,
    }[tier]


def requires_granular_engine(path: VoicePath) -> bool:
    """True when the path routes audio through the Evil Pet granular engine.

    Callers use this to decide whether they need to acquire the
    ``evil_pet_granular_engine`` mutex before emitting CCs —
    ``EVIL_PET`` and ``BOTH`` both drive the engine, ``DRY`` and
    ``RADIO`` leave it untouched.
    """
    if path is VoicePath.HELD:
        return False
    data = load_paths()
    return data[path].via_evil_pet


def describe_path(path: VoicePath) -> str:
    """Operator-readable description from the config — used in CLI output."""
    if path is VoicePath.HELD:
        return "Held: no public/default voice route until FX expression witness passes."
    return load_paths()[path].description


def all_paths() -> list[VoicePath]:
    """All addressable paths, ordered by YAML key."""
    return list(load_paths().keys())
