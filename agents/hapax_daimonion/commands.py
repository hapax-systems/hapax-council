"""Directive primitives: Command and Schedule.

Phase 3 of the perception type system. Directives prescribe action — they are
inert data objects carrying full provenance of the perception and governance
decisions that produced them. A Directive does nothing until an interpreter
executes it. This gap between description and execution is where governance lives.

Consent threading (DD-22 L4-L6): Labels propagate unchanged. Command carries
an optional consent_label from its originating FusedContext. Schedule inherits
via its Command. No label transformation occurs at this layer.
"""

from __future__ import annotations

import types
from dataclasses import dataclass, field
from typing import Any

from agents.hapax_daimonion.governance import VetoResult
from shared.governance.consent_label import ConsentLabel


@dataclass(frozen=True)
class Command:
    """An inspectable, governable action description.

    Every field is readable data. Governance can inspect action, params,
    min_watermark, trigger_source before deciding whether to allow execution.
    Immutable — prevents TOCTOU bugs between governance check and execution.

    Optional consent_label (DD-22): propagated from FusedContext, unchanged.
    """

    action: str
    params: dict[str, Any] = field(default_factory=dict)
    trigger_time: float = 0.0
    trigger_source: str = ""
    min_watermark: float = 0.0
    governance_result: VetoResult = field(default_factory=lambda: VetoResult(allowed=True))
    selected_by: str = "default"
    consent_label: ConsentLabel | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", types.MappingProxyType(self.params))


@dataclass(frozen=True)
class Schedule:
    """A command bound to a specific time in a specific domain.

    Bridges the gap between "decide what to do" (Detective output) and
    "do it at the right moment" (actuator input). The wall_time field is
    the resolved wall-clock time (from TimelineMapping when available).
    """

    command: Command
    domain: str = "wall"
    target_time: float = 0.0
    wall_time: float = 0.0
    tolerance_ms: float = 50.0
