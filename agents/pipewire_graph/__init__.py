"""Shadow-mode PipeWire graph daemon package.

Phase 2 of the audio graph SSOT plan introduces the
``hapax-pipewire-graph`` daemon in observe-only mode. This package is
deliberately read-only with respect to PipeWire: dry-run reports and
egress health JSONL are written under ``~/hapax-state/pipewire-graph``;
no confs are written, no modules are loaded, and safe-mute is never
engaged in this phase.
"""

from __future__ import annotations

from agents.pipewire_graph.circuit_breaker import (
    EgressCircuitBreaker,
    EgressFailureMode,
    EgressHealth,
    ShadowAlert,
)
from agents.pipewire_graph.metrics import PipewireGraphMetrics
from agents.pipewire_graph.safe_mute import SafeMuteRail, SafeMuteResult

__all__ = [
    "EgressCircuitBreaker",
    "EgressFailureMode",
    "EgressHealth",
    "PipewireGraphMetrics",
    "SafeMuteRail",
    "SafeMuteResult",
    "ShadowAlert",
]
