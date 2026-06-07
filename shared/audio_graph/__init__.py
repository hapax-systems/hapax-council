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
    CandidateBundle,
    CompiledArtefacts,
    PactlLoad,
    PostApplyProbe,
    compile_descriptor,
    compile_port_audio_graph,
)
from shared.audio_graph.invariants import (
    INVARIANT_CHECKERS,
    InvariantKind,
    InvariantSeverity,
    InvariantViolation,
    check_all_invariants,
)
from shared.audio_graph.model import (
    AudioEdge,
    BusSpec,
    ClockSpec,
    DevicePort,
    DeviceSpec,
    ExposureDomain,
    FenceSpec,
    GraphNode,
    GraphPort,
    HardwareInsert,
    LoudnessConstantRefs,
    ModulationPath,
    MonitorSpec,
    PortAudioGraph,
    PortDirection,
    ReconcilerSpec,
    RoleSpec,
    SourceSpec,
    WetControl,
    WetProfile,
)
from shared.audio_graph.proof import (
    PortGraph,
    ProofCode,
    ProofReport,
    ProofSeverity,
    ProofViolation,
    build_port_graph,
    run_all_proofs,
)
from shared.audio_graph.render_pipewire import (
    render_forbidden_link_map,
    render_link_map,
    render_pipewire_candidates,
)
from shared.audio_graph.render_wireplumber import (
    render_link_deny_lua,
    render_wireplumber_candidates,
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
    "AudioEdge",
    "AlsaCardRule",
    "AlsaProfilePin",
    "AudioGraph",
    "AudioLink",
    "AudioNode",
    "BluezRule",
    "BroadcastInvariant",
    "BusSpec",
    "ChannelDownmix",
    "ChannelMap",
    "ClockSpec",
    "DevicePort",
    "DeviceSpec",
    "DownmixRoute",
    "DownmixStrategy",
    "DuckPolicy",
    "ExposureDomain",
    "Fanout",
    "FenceSpec",
    "FilterChainTemplate",
    "FilterStage",
    "FormatSpec",
    "GainStage",
    "GlobalTunables",
    "GraphNode",
    "GraphPort",
    "HardwareInsert",
    "LoopbackTopology",
    "LoudnessConstantRefs",
    "MediaRoleSink",
    "MixdownGraph",
    "MixerRoute",
    "ModulationPath",
    "MonitorSpec",
    "NodeKind",
    "PortAudioGraph",
    "PortDirection",
    "PreferredTargetPin",
    "ReconcilerSpec",
    "RemapSource",
    "RoleLoopback",
    "RoleSpec",
    "SourceSpec",
    "StreamPin",
    "StreamRestoreRule",
    "WetControl",
    "WetProfile",
    "WireplumberRule",
    # invariants
    "InvariantKind",
    "InvariantSeverity",
    "InvariantViolation",
    "check_all_invariants",
    "INVARIANT_CHECKERS",
    # port-level proof
    "PortGraph",
    "ProofCode",
    "ProofReport",
    "ProofSeverity",
    "ProofViolation",
    "build_port_graph",
    "run_all_proofs",
    # compiler
    "CandidateBundle",
    "CompiledArtefacts",
    "PactlLoad",
    "PostApplyProbe",
    "compile_descriptor",
    "compile_port_audio_graph",
    # candidate renderers
    "render_forbidden_link_map",
    "render_link_deny_lua",
    "render_link_map",
    "render_pipewire_candidates",
    "render_wireplumber_candidates",
    # validator
    "AudioGraphValidator",
    "DecomposeResult",
    "GapReport",
]
