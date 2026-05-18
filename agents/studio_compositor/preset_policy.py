"""Central policy gate for compositor FX preset activation."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from shared.live_surface_effect_policy import (
    LIVE_SURFACE_BLOCKED_NODE_TYPES,
    live_surface_glsl_requires_source_bound_repair,
)
from shared.live_surface_effect_policy import (
    apply_live_surface_param_bounds as _apply_live_surface_param_bounds,
)

_TRUTHY = frozenset({"1", "true", "yes", "on", "enabled", "active"})
_FALSY = frozenset({"0", "false", "no", "off", "disabled", "inactive"})
_IMPLICIT_CAMERA_LEGIBLE_PRESETS = frozenset({"clean"})
_MAX_NEUTRAL_CONTENT_SLOT_PARAM = 0.01
_MAX_CAMERA_LEGIBLE_CONTENT_OPACITY = 0.35


@dataclass(frozen=True)
class PresetPolicyDecision:
    allowed: bool
    reason: str
    preset: str
    matched: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class PresetPolicyError(RuntimeError):
    """Raised when a graph activation violates compositor preset policy."""

    def __init__(self, decision: PresetPolicyDecision) -> None:
        self.decision = decision
        super().__init__(f"preset policy blocked {decision.preset}: {decision.reason}")


def _normalize_preset_name(name: str) -> str:
    normalized = name.strip()
    if normalized.endswith(".json"):
        normalized = normalized[:-5]
    return re.sub(r"[^a-z0-9]+", "_", normalized.lower()).strip("_")


def _csv_names(raw: str | None) -> frozenset[str]:
    if not raw:
        return frozenset()
    return frozenset(
        _normalize_preset_name(item) for item in raw.replace("\n", ",").split(",") if item.strip()
    )


def _truthy(raw: str | None) -> bool:
    return (raw or "").strip().lower() in _TRUTHY


def _falsy(raw: str | None) -> bool:
    return (raw or "").strip().lower() in _FALSY


def autonomous_fx_mutations_enabled(env: Mapping[str, str] | None = None) -> bool:
    effective_env = os.environ if env is None else env
    raw = effective_env.get("HAPAX_FX_AUTONOMOUS_MUTATIONS", "1").strip().lower()
    return raw not in {"0", "false", "no", "off", "disabled"}


def evaluate_preset_policy(
    preset_name: str,
    *,
    aliases: Sequence[str] = (),
    env: Mapping[str, str] | None = None,
) -> PresetPolicyDecision:
    """Return whether a preset may be activated under current incident policy.

    The compositor has several preset-selection entry points: startup, API/file
    requests, atmospheric governance, chat/recruitment graph mutations, and
    tests. Runtime incident drop-ins are only meaningful if every path consults
    the same policy. Names are normalized with optional aliases so legacy names
    such as ``halftone`` and canonical files such as ``halftone_preset.json``
    can be governed by one declaration.
    """

    effective_env = os.environ if env is None else env
    candidates = tuple(
        dict.fromkeys(
            name
            for name in (
                _normalize_preset_name(preset_name),
                *(_normalize_preset_name(alias) for alias in aliases),
            )
            if name
        )
    )
    primary = candidates[0] if candidates else _normalize_preset_name(preset_name)

    denylist = _csv_names(effective_env.get("HAPAX_COMPOSITOR_PRESET_DENYLIST"))
    denied = tuple(name for name in candidates if name in denylist)
    if denied:
        return PresetPolicyDecision(
            allowed=False,
            reason="preset_denylisted",
            preset=primary,
            matched=denied,
        )

    if _truthy(effective_env.get("HAPAX_CAMERA_LEGIBLE_FX_ONLY")):
        allowlist = _csv_names(effective_env.get("HAPAX_CAMERA_LEGIBLE_PRESET_ALLOWLIST"))
        if allowlist:
            allowed = tuple(name for name in candidates if name in allowlist)
            if not allowed:
                return PresetPolicyDecision(
                    allowed=False,
                    reason="camera_legible_allowlist",
                    preset=primary,
                    matched=tuple(sorted(allowlist)),
                )

    return PresetPolicyDecision(allowed=True, reason="allowed", preset=primary)


def _candidate_names(
    preset_name: str,
    aliases: Sequence[str] = (),
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            name
            for name in (
                _normalize_preset_name(preset_name),
                *(_normalize_preset_name(alias) for alias in aliases),
            )
            if name
        )
    )


def _camera_legible_contract_enabled(
    candidates: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
) -> bool:
    effective_env = os.environ if env is None else env
    if not _falsy(effective_env.get("HAPAX_LIVE_SURFACE_EFFECT_POLICY")):
        return True
    if any(name in _IMPLICIT_CAMERA_LEGIBLE_PRESETS for name in candidates):
        return True
    return _truthy(effective_env.get("HAPAX_CAMERA_LEGIBLE_FX_ONLY"))


def live_surface_effect_policy_enabled(
    preset_name: str = "",
    *,
    aliases: Sequence[str] = (),
    env: Mapping[str, str] | None = None,
) -> bool:
    """Return whether live-surface effect safety is active for this context."""
    candidates = _candidate_names(preset_name, aliases)
    if not candidates and preset_name:
        candidates = (_normalize_preset_name(preset_name),)
    return _camera_legible_contract_enabled(candidates, env=env)


def apply_live_surface_param_bounds(
    node_type: str,
    params: Mapping[str, Any],
    *,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Clamp runtime params that can otherwise defeat graph-level safety.

    Graph body policy blocks known destructive presets at load time. Runtime
    modulation is a separate path: audio-reactive deltas are applied after the
    preset has been accepted. These clamps keep live output inside the same
    camera-legible contract after every modulation tick.
    """

    out = dict(params)
    if not live_surface_effect_policy_enabled(env=env):
        return out

    return _apply_live_surface_param_bounds(node_type, out)


def _param_default(registry: Any, node_type: str, param_name: str) -> object | None:
    if registry is None:
        return None
    node_def = registry.get(node_type)
    if node_def is None:
        return None
    param_def = node_def.params.get(param_name)
    if param_def is None:
        return None
    return param_def.default


def _param_float(
    node: Any,
    param_name: str,
    *,
    registry: Any = None,
    default: float = 0.0,
) -> float:
    raw = node.params.get(param_name, _param_default(registry, node.type, param_name))
    if raw is None:
        raw = default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _content_slot_use_is_neutral(node: Any, *, registry: Any = None) -> bool:
    """Return whether a content-slot node is declared but inert.

    Most historical presets include ``content_layer`` as a latent recruitment
    point. In the GL compositor path that layer is only camera-safe while it
    remains a pass-through; nonzero content salience/intensity needs runtime
    slot-binding and opacity proof before it can be considered camera-legible.
    """

    salience = _param_float(
        node,
        "salience",
        registry=registry,
        default=0.0,
    )
    intensity = _param_float(
        node,
        "intensity",
        registry=registry,
        default=0.0,
    )
    return (
        salience <= _MAX_NEUTRAL_CONTENT_SLOT_PARAM and intensity <= _MAX_NEUTRAL_CONTENT_SLOT_PARAM
    )


def _content_slot_policy_is_camera_legible(node_def: Any) -> bool:
    policy = getattr(node_def, "content_slot_policy", None)
    if not isinstance(policy, Mapping):
        return False
    geometry = policy.get("camera_geometry_policy")
    if not isinstance(geometry, Mapping):
        return False
    try:
        max_opacity = float(policy.get("camera_legible_max_opacity", 1.0))
    except (TypeError, ValueError):
        return False
    return (
        policy.get("provider") == "content_source_manager"
        and policy.get("missing") == "transparent_noop"
        and policy.get("manager_required") is True
        and policy.get("opacity_source") == "family_filtered"
        and max_opacity <= _MAX_CAMERA_LEGIBLE_CONTENT_OPACITY
        and geometry.get("overlay_only") is True
        and geometry.get("destructive") is False
    )


def evaluate_preset_graph_policy(
    graph: Any,
    *,
    preset_name: str | None = None,
    aliases: Sequence[str] = (),
    registry: Any = None,
    env: Mapping[str, str] | None = None,
) -> PresetPolicyDecision:
    """Return whether a preset graph body is camera-legible under policy.

    Name-level allowlists are insufficient: registry defaults can turn an
    apparently harmless preset into full-frame anonymization/noise after
    compilation. This body-level contract protects the camera-legible surface
    from graph contents that destroy geometry even when the preset name is
    allowed.
    """

    graph_name = preset_name or getattr(graph, "name", "")
    candidates = _candidate_names(graph_name, aliases)
    primary = candidates[0] if candidates else _normalize_preset_name(graph_name)
    if not _camera_legible_contract_enabled(candidates, env=env):
        return PresetPolicyDecision(allowed=True, reason="allowed", preset=primary)

    for node_id, node in graph.nodes.items():
        node_type = node.type
        if node_type in LIVE_SURFACE_BLOCKED_NODE_TYPES:
            return PresetPolicyDecision(
                allowed=False,
                reason="camera_legible_blocked_node",
                preset=primary,
                matched=(node_id, node_type),
            )

        node_def = registry.get(node_type) if registry is not None else None
        if getattr(node_def, "requires_content_slots", False):
            if not _content_slot_policy_is_camera_legible(node_def):
                return PresetPolicyDecision(
                    allowed=False,
                    reason="camera_legible_content_slot_contract",
                    preset=primary,
                    matched=(node_id, node_type),
                )
            if not _content_slot_use_is_neutral(node, registry=registry):
                return PresetPolicyDecision(
                    allowed=False,
                    reason="camera_legible_unbound_content_slots",
                    preset=primary,
                    matched=(node_id, node_type),
                )

        if live_surface_glsl_requires_source_bound_repair(
            node_type,
            has_glsl_source=bool(getattr(node_def, "glsl_source", None)),
        ):
            return PresetPolicyDecision(
                allowed=False,
                reason="camera_legible_glsl_pending_source_bound_repair",
                preset=primary,
                matched=(node_id, node_type),
            )

    return PresetPolicyDecision(allowed=True, reason="allowed", preset=primary)


__all__ = [
    "PresetPolicyDecision",
    "PresetPolicyError",
    "apply_live_surface_param_bounds",
    "autonomous_fx_mutations_enabled",
    "evaluate_preset_graph_policy",
    "evaluate_preset_policy",
    "live_surface_effect_policy_enabled",
]
