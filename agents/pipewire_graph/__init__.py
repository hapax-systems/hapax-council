"""Shadow-mode PipeWire graph daemon package.

Phase 2 of the audio graph SSOT plan introduces the
``hapax-pipewire-graph`` daemon in observe-only mode. This package is
deliberately read-only with respect to PipeWire: dry-run reports and
egress health JSONL are written under ``~/hapax-state/pipewire-graph``;
no confs are written, no modules are loaded, and safe-mute is never
engaged in this phase.

Phase 3 adds only the coordination lock used by edit gates and the
``hapax-pipewire-graph`` CLI. Active apply remains deferred.
"""

from __future__ import annotations

from agents.pipewire_graph.circuit_breaker import (
    EgressCircuitBreaker,
    EgressFailureMode,
    EgressHealth,
    ShadowAlert,
)
from agents.pipewire_graph.lock import (
    ApplierLockStatus,
    acquire_session_lock,
    lock_allows_owner,
    read_lock_status,
    release_session_lock,
)
from agents.pipewire_graph.metrics import PipewireGraphMetrics
from agents.pipewire_graph.safe_mute import SafeMuteRail, SafeMuteResult

__all__ = [
    "ApplierLockStatus",
    "EgressCircuitBreaker",
    "EgressFailureMode",
    "EgressHealth",
    "PipewireGraphMetrics",
    "SafeMuteRail",
    "SafeMuteResult",
    "ShadowAlert",
    "acquire_session_lock",
    "lock_allows_owner",
    "read_lock_status",
    "release_session_lock",
]
