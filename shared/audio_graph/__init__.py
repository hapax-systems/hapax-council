"""Audio Graph SSOT — Pydantic schema, compiler, validator, and invariants.

Single source of truth for the PipeWire/WirePlumber audio graph that
drives the livestream broadcast. Implements Phase 1 of the audio graph
SSOT design (`docs/superpowers/specs/2026-05-03-audio-graph-ssot-and-router-daemon-design.md`)
with all 17 alignment-audit gap-folds applied
(`docs/research/2026-05-03-audio-graph-ssot-alignment-audit.md`).

Public API:

- :class:`AudioGraph` — the typed root model (alias for compatibility
  with the existing :class:`shared.audio_topology.TopologyDescriptor`,
  with extension fields for the 12 schema-additive gaps).
- :func:`compile_descriptor` — pure compiler from descriptor to
  artefacts (PipeWire confs, WirePlumber confs, pactl loads,
  pre-apply violation list, post-apply probes).
- :class:`AudioGraphValidator` — read-only decomposer that turns
  live ``~/.config/pipewire/pipewire.conf.d/*.conf`` files into an
  AudioGraph instance and reports any structural gaps.
- 11 invariant predicates (in :mod:`shared.audio_graph.invariants`).

Phase 1 ships **schema + compiler + validator + invariants** only.
No daemon, no apply path, no runtime mutation. The validator is
read-only against ``~/.config/pipewire/`` (file reads only, no
``pw-dump`` / ``pactl`` / ``pw-link`` invocations).

References:
- Spec: docs/superpowers/specs/2026-05-03-audio-graph-ssot-and-router-daemon-design.md
- Audit: docs/research/2026-05-03-audio-graph-ssot-alignment-audit.md
- Existing schema: shared/audio_topology.py (schema_version=3, reused)
- Existing compiler primitive: shared/audio_topology_generator.py
- Existing live-graph reader: shared/audio_topology_inspector.py
"""

from __future__ import annotations

from shared.audio_graph.compiler import (
    CompiledArtefacts,
    PactlLoad,
    PostApplyProbe,
    compile_descriptor,
)
from shared.audio_graph.invariants import (
    INVARIANT_CHECKERS,
    InvariantKind,
    InvariantSeverity,
    InvariantViolation,
    check_all_invariants,
)
from shared.audio_graph.schema import (
    AlsaCardRule,
    AlsaProfilePin,
    AudioGraph,
    AudioLink,
    AudioNode,
    BluezRule,
    BroadcastInvariant,
    ChannelDownmix,
    ChannelMap,
    DownmixRoute,
    DownmixStrategy,
    DuckPolicy,
    Fanout,
    FilterChainTemplate,
    FilterStage,
    FormatSpec,
    GainStage,
    GlobalTunables,
    LoopbackTopology,
    MediaRoleSink,
    MixdownGraph,
    MixerRoute,
    NodeKind,
    PreferredTargetPin,
    RemapSource,
    RoleLoopback,
    StreamPin,
    StreamRestoreRule,
    WireplumberRule,
)
from shared.audio_graph.validator import (
    AudioGraphValidator,
    DecomposeResult,
    GapReport,
)

__all__ = [
    # schema
    "AlsaCardRule",
    "AlsaProfilePin",
    "AudioGraph",
    "AudioLink",
    "AudioNode",
    "BluezRule",
    "BroadcastInvariant",
    "ChannelDownmix",
    "ChannelMap",
    "DownmixRoute",
    "DownmixStrategy",
    "DuckPolicy",
    "Fanout",
    "FilterChainTemplate",
    "FilterStage",
    "FormatSpec",
    "GainStage",
    "GlobalTunables",
    "LoopbackTopology",
    "MediaRoleSink",
    "MixdownGraph",
    "MixerRoute",
    "NodeKind",
    "PreferredTargetPin",
    "RemapSource",
    "RoleLoopback",
    "StreamPin",
    "StreamRestoreRule",
    "WireplumberRule",
    # invariants
    "InvariantKind",
    "InvariantSeverity",
    "InvariantViolation",
    "check_all_invariants",
    "INVARIANT_CHECKERS",
    # compiler
    "CompiledArtefacts",
    "PactlLoad",
    "PostApplyProbe",
    "compile_descriptor",
    # validator
    "AudioGraphValidator",
    "DecomposeResult",
    "GapReport",
]
