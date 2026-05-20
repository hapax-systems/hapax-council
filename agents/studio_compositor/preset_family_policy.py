"""Family-level live-surface policy inventory for compositor presets."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from agents.effect_graph.registry import ShaderRegistry
from agents.effect_graph.types import EffectGraph

from .preset_family_selector import PRESET_DIR, presets_for_family
from .preset_policy import evaluate_preset_graph_policy, evaluate_preset_policy

NODES_DIR = Path(__file__).parent.parent / "shaders" / "nodes"


@dataclass(frozen=True)
class FamilyPresetPolicyRow:
    """One preset's family-policy verdict."""

    family: str
    preset: str
    allowed: bool
    reason: str
    matched: tuple[str, ...] = ()
    node_types: tuple[str, ...] = ()


@lru_cache(maxsize=1)
def _default_registry() -> ShaderRegistry:
    return ShaderRegistry(NODES_DIR)


def inspect_family_policy(
    family: str,
    *,
    registry: ShaderRegistry | None = None,
    preset_dir: Path = PRESET_DIR,
    env: Mapping[str, str] | None = None,
) -> tuple[FamilyPresetPolicyRow, ...]:
    """Return exact live-surface policy verdicts for every preset in a family."""

    effective_registry = registry if registry is not None else _default_registry()
    rows: list[FamilyPresetPolicyRow] = []
    for preset in presets_for_family(family):
        path = preset_dir / f"{preset}.json"
        if not path.exists():
            rows.append(
                FamilyPresetPolicyRow(
                    family=family,
                    preset=preset,
                    allowed=False,
                    reason="preset_missing",
                )
            )
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            rows.append(
                FamilyPresetPolicyRow(
                    family=family,
                    preset=preset,
                    allowed=False,
                    reason="preset_invalid_json",
                )
            )
            continue
        try:
            graph = EffectGraph(**raw)
        except Exception:
            rows.append(
                FamilyPresetPolicyRow(
                    family=family,
                    preset=preset,
                    allowed=False,
                    reason="preset_invalid_graph",
                )
            )
            continue

        node_types = tuple(node.type for node in graph.nodes.values())
        name_policy = evaluate_preset_policy(
            preset,
            aliases=(graph.name,),
            env=env,
        )
        if not name_policy.allowed:
            rows.append(
                FamilyPresetPolicyRow(
                    family=family,
                    preset=preset,
                    allowed=False,
                    reason=name_policy.reason,
                    matched=name_policy.matched,
                    node_types=node_types,
                )
            )
            continue

        graph_policy = evaluate_preset_graph_policy(
            graph,
            preset_name=preset,
            aliases=(graph.name,),
            registry=effective_registry,
            env=env,
        )
        rows.append(
            FamilyPresetPolicyRow(
                family=family,
                preset=preset,
                allowed=graph_policy.allowed,
                reason=graph_policy.reason,
                matched=graph_policy.matched,
                node_types=node_types,
            )
        )
    return tuple(rows)


def policy_eligible_presets_for_family(
    family: str,
    *,
    registry: ShaderRegistry | None = None,
    preset_dir: Path = PRESET_DIR,
    env: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Return family presets that can pass current live-surface policy."""

    return tuple(
        row.preset
        for row in inspect_family_policy(
            family,
            registry=registry,
            preset_dir=preset_dir,
            env=env,
        )
        if row.allowed
    )


def family_policy_reason_counts(
    family: str,
    *,
    registry: ShaderRegistry | None = None,
    preset_dir: Path = PRESET_DIR,
    env: Mapping[str, str] | None = None,
) -> dict[str, int]:
    """Return blocked verdict counts for compact runtime receipts."""

    counts = Counter(
        row.reason
        for row in inspect_family_policy(
            family,
            registry=registry,
            preset_dir=preset_dir,
            env=env,
        )
        if not row.allowed
    )
    return dict(sorted(counts.items()))


__all__ = [
    "FamilyPresetPolicyRow",
    "family_policy_reason_counts",
    "inspect_family_policy",
    "policy_eligible_presets_for_family",
]
