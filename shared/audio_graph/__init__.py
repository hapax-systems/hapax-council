"""Audio Graph SSOT — Pydantic schema, compiler, validator, invariants.

Phase P1 of the audio-graph SSOT spec
(``docs/superpowers/specs/2026-05-03-audio-graph-ssot-and-router-daemon-design.md``).

This package introduces the typed source-of-truth for the workstation's
PipeWire audio graph. P1 ships:

- ``schema``: ``AudioGraph`` + child models (frozen, ``extra="forbid"``).
- ``compiler``: ``compile_descriptor(graph) -> CompiledArtefacts``
  (pure function, byte-deterministic, emits 5-tuple of artefacts).
- ``invariants``: 11 pure-function predicates (9 pre-apply + 2 continuous
  egress), each returning a list of ``InvariantViolation``.
- ``validator``: ``AudioGraphValidator`` decomposes existing PipeWire
  conf files into ``AudioGraph`` instances and surfaces gaps for follow-up
  schema iteration.

P1 contains NO runtime side-effects: no PipeWire mutation, no service
restarts, no live audio probes. The validator is read-only against
operator configuration. The CI gate (``audio-graph-validate``) runs the
validator against a fixture snapshot of the operator's confs and fails
when any conf does not decompose cleanly.

Subsequent phases (P2–P5) add the ``hapax-pipewire-graph`` daemon, the
applier lock, atomic apply with snapshot+rollback, and the continuous
egress circuit breaker. Those are out of scope here.
"""

from __future__ import annotations

from shared.audio_graph.compiler import (
    CompiledArtefacts,
    PactlLoad,
    PostApplyProbe,
    RollbackPlan,
    compile_descriptor,
)
from shared.audio_graph.invariants import (
    INVARIANT_REGISTRY,
    EgressHealth,
    InvariantKind,
    InvariantSeverity,
    InvariantViolation,
    check_all_invariants,
    check_channel_count_topology_wide,
    check_egress_safety_band_crest,
    check_egress_safety_band_rms,
    check_format_compatibility,
    check_gain_budget,
    check_hardware_bleed_guard,
    check_l12_directionality,
    check_master_bus_sole_path,
    check_no_duplicate_pipewire_names,
    check_port_compatibility,
    check_private_never_broadcasts,
)
from shared.audio_graph.schema import (
    AudioGraph,
    AudioLink,
    AudioNode,
    BroadcastInvariant,
    ChannelMap,
    DownmixStrategy,
    FormatSpec,
    GainStage,
    LoopbackTopology,
    NodeKind,
)
from shared.audio_graph.validator import (
    AudioGraphValidator,
    ConfParseError,
    ValidationGap,
    ValidationReport,
)

__all__ = [
    "INVARIANT_REGISTRY",
    "AudioGraph",
    "AudioGraphValidator",
    "AudioLink",
    "AudioNode",
    "BroadcastInvariant",
    "ChannelMap",
    "CompiledArtefacts",
    "ConfParseError",
    "DownmixStrategy",
    "EgressHealth",
    "FormatSpec",
    "GainStage",
    "InvariantKind",
    "InvariantSeverity",
    "InvariantViolation",
    "LoopbackTopology",
    "NodeKind",
    "PactlLoad",
    "PostApplyProbe",
    "RollbackPlan",
    "ValidationGap",
    "ValidationReport",
    "check_all_invariants",
    "check_channel_count_topology_wide",
    "check_egress_safety_band_crest",
    "check_egress_safety_band_rms",
    "check_format_compatibility",
    "check_gain_budget",
    "check_hardware_bleed_guard",
    "check_l12_directionality",
    "check_master_bus_sole_path",
    "check_no_duplicate_pipewire_names",
    "check_port_compatibility",
    "check_private_never_broadcasts",
    "compile_descriptor",
]
