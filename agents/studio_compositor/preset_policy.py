"""Central policy gate for compositor FX preset activation."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

_TRUTHY = frozenset({"1", "true", "yes", "on", "enabled", "active"})
_IMPLICIT_CAMERA_LEGIBLE_PRESETS = frozenset({"clean"})
_FULL_FRAME_NOISE_NODE_TYPES = frozenset({"noise_gen", "noise_overlay"})
_MAX_CAMERA_LEGIBLE_ANONYMIZE = 0.5
_MIN_CAMERA_LEGIBLE_POSTERIZE_LEVELS = 8.0


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
    if any(name in _IMPLICIT_CAMERA_LEGIBLE_PRESETS for name in candidates):
        return True
    return _truthy(effective_env.get("HAPAX_CAMERA_LEGIBLE_FX_ONLY"))


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
        if node_type in _FULL_FRAME_NOISE_NODE_TYPES:
            return PresetPolicyDecision(
                allowed=False,
                reason="camera_legible_full_frame_noise",
                preset=primary,
                matched=(node_id, node_type),
            )

        node_def = registry.get(node_type) if registry is not None else None
        if getattr(node_def, "requires_content_slots", False):
            return PresetPolicyDecision(
                allowed=False,
                reason="camera_legible_unbound_content_slots",
                preset=primary,
                matched=(node_id, node_type),
            )

        if node_type == "postprocess":
            anonymize = _param_float(
                node,
                "anonymize",
                registry=registry,
                default=0.0,
            )
            if anonymize > _MAX_CAMERA_LEGIBLE_ANONYMIZE:
                return PresetPolicyDecision(
                    allowed=False,
                    reason="camera_legible_anonymize",
                    preset=primary,
                    matched=(node_id, f"anonymize={anonymize:g}"),
                )

        if node_type == "posterize":
            levels = _param_float(
                node,
                "levels",
                registry=registry,
                default=_MIN_CAMERA_LEGIBLE_POSTERIZE_LEVELS,
            )
            if levels < _MIN_CAMERA_LEGIBLE_POSTERIZE_LEVELS:
                return PresetPolicyDecision(
                    allowed=False,
                    reason="camera_legible_posterize_levels",
                    preset=primary,
                    matched=(node_id, f"levels={levels:g}"),
                )

    return PresetPolicyDecision(allowed=True, reason="allowed", preset=primary)


__all__ = [
    "PresetPolicyDecision",
    "PresetPolicyError",
    "autonomous_fx_mutations_enabled",
    "evaluate_preset_graph_policy",
    "evaluate_preset_policy",
]
