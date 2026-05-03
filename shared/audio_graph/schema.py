"""Audio Graph SSOT — Pydantic models.

Per spec §2 of
``docs/superpowers/specs/2026-05-03-audio-graph-ssot-and-router-daemon-design.md``.

The models in this module are the **single source of truth** for the
workstation's PipeWire audio graph. Every artefact downstream
(``.conf`` files, ``pactl load-module`` invocations, WirePlumber rules,
post-apply probes, rollback plans) is derived from an ``AudioGraph``
instance. The compiler in ``compiler.py`` is the only authorised producer
of those derived artefacts; the validator in ``validator.py`` round-trips
existing confs back into the schema to surface gaps where the spec
doesn't yet fit reality.

Design contract:

* All models are ``frozen=True`` and ``extra="forbid"``. The compiler's
  apply path requires immutability for transactional safety (spec §4.4
  — "atomic apply with snapshot+rollback" demands that the input
  descriptor cannot mutate while the apply is in flight). ``extra="forbid"``
  makes spec drift surface as a parse error rather than as silently
  accepted unknown fields.
* All numeric ranges are validated at construction time. Out-of-range
  gains, negative channel counts, etc. raise ``pydantic.ValidationError``.
* IDs follow kebab-case convention — they're descriptor-local stable
  identifiers used as edge keys and in error messages.
"""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class NodeKind(StrEnum):
    """The audio-graph node kinds modelled in P1.

    Kinds map to PipeWire primitives:

    * ``alsa_source`` / ``alsa_sink`` — hardware endpoints (an ALSA PCM
      device wrapped by PipeWire). E.g. the L-12 multichannel USB capture,
      Yeti analog-stereo headphone.
    * ``filter_chain`` — a ``libpipewire-module-filter-chain`` instance.
      Covers loudnorm chains, duckers, the L-12 multitrack capture
      filter, voice-fx chains.
    * ``loopback`` — a ``libpipewire-module-loopback`` bridging two
      endpoints. Distinct from ``LoopbackTopology`` which models the
      loopback's typed properties; a ``loopback`` node is the placeholder
      in the graph wiring.
    * ``null_sink`` — a ``support.null-audio-sink`` adapter (e.g.
      ``hapax-livestream-tap``, ``hapax-private``). Fan-out points and
      fail-closed sinks land here.
    * ``tap`` — a model-only descriptor for hardware patch points that
      are not PipeWire-visible (e.g. the S-4 analog OUT 1/2 monitor
      patch). Lets the audit graph reason about the destination of
      private-monitor tracks.
    """

    ALSA_SOURCE = "alsa_source"
    ALSA_SINK = "alsa_sink"
    FILTER_CHAIN = "filter_chain"
    LOOPBACK = "loopback"
    NULL_SINK = "null_sink"
    TAP = "tap"


class DownmixStrategy(StrEnum):
    """Channel-count-change strategies.

    When ``source.channels.count != target.channels.count``, the
    ``format_compatibility`` invariant requires an explicit
    ``GainStage`` (or partner downmix descriptor on the link) declaring
    how channels combine.

    * ``channel_pick`` — pick a subset of source positions; map them
      onto target positions. The 14ch L-12 capture → 2ch livestream-tap
      uses this strategy with ``map={"FL": "AUX1+AUX3", "FR": "AUX4+AUX5"}``.
    * ``mixdown`` — sum all source channels into target channels.
    * ``broadcast_fan_out`` — duplicate one source channel onto multiple
      target positions (mono → stereo).
    """

    CHANNEL_PICK = "channel_pick"
    MIXDOWN = "mixdown"
    BROADCAST_FAN_OUT = "broadcast_fan_out"


class ChannelMap(BaseModel):
    """Canonical channel layout for a node's audio.

    Tracks both the count and the explicit position list. The position
    list is the load-bearing field: PipeWire's ``audio.position`` directive
    determines port-name compatibility, and the ``port_compatibility``
    invariant relies on positions matching across edges.

    Position tokens follow PipeWire convention:

    * ``FL``, ``FR``, ``RL``, ``RR``, ``MONO`` — speaker positions
    * ``AUX0`` .. ``AUX63`` — multi-channel multitrack positions
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    count: int = Field(..., ge=1, le=64)
    positions: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _positions_match_count(self) -> ChannelMap:
        if self.positions and len(self.positions) != self.count:
            raise ValueError(
                f"ChannelMap.positions length ({len(self.positions)}) "
                f"must equal count ({self.count}) when positions are set"
            )
        return self


class FormatSpec(BaseModel):
    """Sample format for a node or stream.

    Captures the PipeWire ``audio.rate`` / ``audio.format`` / ``audio.channels``
    triple. P1 carries this as data — the compiler propagates it into
    emitted confs; the format-compatibility invariant uses it to detect
    mismatches across edges (today's failure #5: ``audio.channels=2``
    declared on a chain whose capture is 14ch).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    rate_hz: int = Field(..., ge=8000, le=192000)
    format: Literal["s16", "s24", "s24_32", "s32", "f32", "f64"] = "s32"
    channels: int = Field(..., ge=1, le=64)


class GainStage(BaseModel):
    """Per-edge gain stage with bleed-aware constraints.

    Spec §2 — lifts PipeWire ``builtin mixer`` gain into a typed model
    so the ``hardware_bleed_guard`` invariant can reason about it. Today
    the operator hand-tunes ``gain_samp = 1.0`` in conf text and the
    hardware bleed (-27 dB on AUX2/AUX3) is recorded only as a comment.
    This model surfaces the bleed declaration as data so apply-time
    checks can refuse a configuration where ``base_gain_db +
    per_channel_overrides[ch] - declared_bleed_db > 0``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    edge_source: str
    edge_target: str
    edge_source_port: str | None = None
    base_gain_db: float = Field(default=0.0, ge=-90.0, le=30.0)
    per_channel_overrides: dict[str, float] = Field(default_factory=dict)
    declared_bleed_db: float | None = None
    downmix_strategy: DownmixStrategy | None = None
    downmix_map: dict[str, str] = Field(default_factory=dict)

    @field_validator("base_gain_db")
    @classmethod
    def _gain_is_finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError(
                f"GainStage.base_gain_db={v!r} — must be finite "
                "(values like inf/nan are pathological)"
            )
        return v

    @field_validator("per_channel_overrides")
    @classmethod
    def _overrides_in_range(cls, v: dict[str, float]) -> dict[str, float]:
        for ch, gain_db in v.items():
            if not math.isfinite(gain_db) or gain_db < -90.0 or gain_db > 30.0:
                raise ValueError(
                    f"GainStage.per_channel_overrides[{ch!r}]={gain_db!r} — "
                    "must be finite and in [-90, +30] dB"
                )
        return v


class AudioNode(BaseModel):
    """One node in the audio graph.

    Fields:

    * ``id`` — descriptor-internal stable identifier. Kebab-case by
      convention. Used as the source/target key in ``AudioLink``.
    * ``kind`` — see ``NodeKind``.
    * ``pipewire_name`` — the ``node.name`` string the live PipeWire
      graph uses. Must be unique across all nodes (per the
      ``no_duplicate_pipewire_names`` invariant).
    * ``description`` — operator-readable label surfaced in tooling.
    * ``target_object`` — for ``loopback``, ``filter_chain``, ``alsa_*``
      nodes, the upstream ``target.object`` (sink or source) the node
      binds to.
    * ``hw`` — for ALSA endpoints, the symbolic ALSA card identifier
      (e.g. ``hw:CARD=L12``).
    * ``channels`` — channel map for the node's primary stream.
    * ``format`` — optional sample format.
    * ``params`` — opaque pass-through for kind-specific PipeWire fields
      (filter graph internals, ``audit_role``, ``private_monitor_endpoint``,
      ``fail_closed``, ``stream.dont-remix``, etc.). The compiler emits
      these verbatim in confs; invariants read specific keys
      (``private_monitor_endpoint``, ``forbidden_target_family``,
      ``fail_closed``).
    * ``filter_graph`` — opaque blob for filter-chain internals
      (``filter.graph.nodes``, ``filter.graph.links``, ``inputs``,
      ``outputs``). P1 does NOT regenerate filter-graph internals
      byte-identically from descriptor; the validator reads them as
      JSON-friendly bag and the compiler echoes them. P4 may model
      individual stages as first-class.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    kind: NodeKind
    pipewire_name: str
    description: str = ""
    target_object: str | None = None
    hw: str | None = None
    channels: ChannelMap = Field(
        default_factory=lambda: ChannelMap(count=2, positions=("FL", "FR"))
    )
    format: FormatSpec | None = None
    params: dict[str, str | int | float | bool] = Field(default_factory=dict)
    filter_graph: dict[str, Any] | None = None

    @field_validator("id")
    @classmethod
    def _id_is_kebab(cls, v: str) -> str:
        if not v or any(c.isspace() for c in v) or v != v.lower():
            raise ValueError(
                f"AudioNode.id={v!r} — must be lowercase, no whitespace (kebab-case convention)"
            )
        return v

    @model_validator(mode="after")
    def _hardware_nodes_have_hw(self) -> AudioNode:
        if self.kind in (NodeKind.ALSA_SOURCE, NodeKind.ALSA_SINK) and not self.hw:
            raise ValueError(
                f"AudioNode {self.id!r}: kind={self.kind.value} requires hw "
                "(api.alsa.path) to be set"
            )
        return self


class AudioLink(BaseModel):
    """A directed edge between two nodes.

    Fields:

    * ``source`` / ``target`` — ``AudioNode.id`` references.
    * ``source_port`` / ``target_port`` — optional port specifiers
      (``FL``, ``AUX10``, etc.). When omitted, the whole node's primary
      output links to the target's primary input — PipeWire's default
      auto-link behaviour.
    * ``makeup_gain_db`` — gain applied at the edge. Range ``[-60, +30]``.
      Cumulative gain along any path is bounded by the ``gain_budget``
      invariant (spec §2.4 — ≤ +24 dB).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str
    source_port: str | None = None
    target: str
    target_port: str | None = None
    makeup_gain_db: float = 0.0

    @field_validator("makeup_gain_db")
    @classmethod
    def _gain_in_range(cls, v: float) -> float:
        if not math.isfinite(v) or v < -60.0 or v > 30.0:
            raise ValueError(
                f"AudioLink.makeup_gain_db={v!r} — must be in [-60, +30] dB "
                "(values outside this range are pathological)"
            )
        return v


class LoopbackTopology(BaseModel):
    """Explicit model of a ``module-loopback`` instance.

    Today loopbacks live as ``LOOPBACK``-kind nodes with free-form
    ``params``. This model lifts the loopback's required fields into typed
    properties so the apply path can reason about them (today's failure
    #8: BT hijack happened because no model declared ``source_dont_move``
    on the OBS-monitor loopback).

    The ``apply_via_pactl_load`` flag captures the empirical finding from
    ``~/.local/bin/hapax-obs-monitor-load``: "the conf-file approach via
    ``pipewire.conf.d/`` was demonstrably broken: pipewire would link the
    capture and playback ports correctly but no signal flowed." When
    True, the compiler emits a ``PactlLoad`` artefact instead of a conf
    fragment.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str
    source: str
    sink: str
    source_dont_move: bool = True
    sink_dont_move: bool = True
    fail_closed_on_target_absent: bool = True
    latency_msec: int = Field(default=20, ge=1, le=1000)
    apply_via_pactl_load: bool = False
    expected_source_port_pattern: str | None = None
    expected_sink_port_pattern: str | None = None


class BroadcastInvariant(BaseModel):
    """One invariant the topology must satisfy.

    Per spec §2, the applier checks every ``BroadcastInvariant`` before
    writing any artefact and (for continuous invariants) after applying.
    Violations of severity ``BLOCKING`` refuse the apply atomically;
    violations of ``WARNING`` proceed with operator notification;
    ``INFORMATIONAL`` is logged only.

    The ``check_fn_name`` is the registry key into ``INVARIANT_REGISTRY``
    in ``invariants.py`` — the actual checker is a pure function that
    takes the descriptor and returns a list of violations.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str
    severity: Literal["blocking", "warning", "informational"] = "blocking"
    description: str
    check_fn_name: str
    continuous: bool = False


class AudioGraph(BaseModel):
    """Complete declarative description of the workstation's audio graph.

    Top-level model — every artefact (PipeWire conf, pactl invocation,
    post-apply probe) derives from one ``AudioGraph`` instance. The
    compiler in ``compiler.py`` is the only authorised producer of derived
    artefacts.

    Validation at parse time catches:

    * Dangling links (``source``/``target`` references a non-existent node)
    * Duplicate node IDs
    * Inverted channel maps
    * Out-of-range gains

    The 11 broadcast invariants in ``invariants.py`` are NOT checked at
    parse time — they're checked by the compiler in ``compile_descriptor``
    (the ``preflight_checks`` field of ``CompiledArtefacts``). This split
    keeps the schema parse fast (parse time stays O(nodes+links)) and
    keeps the invariant predicate set hot-swappable as the spec evolves.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    description: str = ""
    nodes: tuple[AudioNode, ...] = Field(default_factory=tuple)
    links: tuple[AudioLink, ...] = Field(default_factory=tuple)
    gain_stages: tuple[GainStage, ...] = Field(default_factory=tuple)
    loopbacks: tuple[LoopbackTopology, ...] = Field(default_factory=tuple)
    invariants: tuple[BroadcastInvariant, ...] = Field(default_factory=tuple)

    @field_validator("nodes")
    @classmethod
    def _node_ids_unique(cls, v: tuple[AudioNode, ...]) -> tuple[AudioNode, ...]:
        seen: set[str] = set()
        for node in v:
            if node.id in seen:
                raise ValueError(f"Duplicate node id: {node.id!r}")
            seen.add(node.id)
        return v

    @model_validator(mode="after")
    def _links_reference_valid_nodes(self) -> AudioGraph:
        node_ids = {n.id for n in self.nodes}
        for link in self.links:
            if link.source not in node_ids:
                raise ValueError(
                    f"AudioLink {link.source!r} → {link.target!r}: source not in graph nodes"
                )
            if link.target not in node_ids:
                raise ValueError(
                    f"AudioLink {link.source!r} → {link.target!r}: target not in graph nodes"
                )
        return self

    @model_validator(mode="after")
    def _gain_stages_reference_valid_nodes(self) -> AudioGraph:
        node_ids = {n.id for n in self.nodes}
        for gs in self.gain_stages:
            if gs.edge_source not in node_ids:
                raise ValueError(
                    f"GainStage {gs.edge_source!r} → {gs.edge_target!r}: "
                    "edge_source not in graph nodes"
                )
            if gs.edge_target not in node_ids:
                raise ValueError(
                    f"GainStage {gs.edge_source!r} → {gs.edge_target!r}: "
                    "edge_target not in graph nodes"
                )
        return self

    @model_validator(mode="after")
    def _loopbacks_reference_valid_nodes(self) -> AudioGraph:
        node_ids = {n.id for n in self.nodes}
        for lb in self.loopbacks:
            if lb.node_id not in node_ids:
                raise ValueError(f"LoopbackTopology {lb.node_id!r}: not in graph nodes")
        return self

    def node_by_id(self, node_id: str) -> AudioNode:
        """Return the node with the given id; KeyError if absent."""
        for n in self.nodes:
            if n.id == node_id:
                return n
        raise KeyError(f"No node with id {node_id!r} in graph")

    def links_from(self, node_id: str) -> tuple[AudioLink, ...]:
        """Return all links sourced at ``node_id``."""
        return tuple(link for link in self.links if link.source == node_id)

    def links_to(self, node_id: str) -> tuple[AudioLink, ...]:
        """Return all links targeting ``node_id``."""
        return tuple(link for link in self.links if link.target == node_id)
