"""Declarative audio topology descriptor — single source of truth for the PipeWire graph.

Phase 1 of ``docs/superpowers/plans/2026-04-20-unified-audio-architecture-
plan.md``. The workstation's audio graph today is a bag of `.conf` files
under ``config/pipewire/`` plus a few WirePlumber policy drops; drift is
silent (you only notice when the livestream goes dead or OBS clips)
and there is no way to answer "what is the current graph?" without
reading `pw-dump` JSON by hand. This module defines the descriptor that
future phases (§2 generator, §3 CLI, §4 inspector, §5 watchdog,
§6 migration) will build on.

A ``TopologyDescriptor`` is a Pydantic document describing nodes
(ALSA sources/sinks, PipeWire filter-chain modules, loopbacks, taps)
and directed edges (links between node ports, optionally with makeup
gain). The descriptor is self-contained — it captures everything a
generator needs to emit the conf files and everything a verifier needs
to assert live-graph parity.

Scope boundaries:

- No MIDI. Voice/MIDI routing lives in ``shared/evil_pet_state.py``
  (mutex) and the vocal/vinyl chains (CC emission).
- No cross-device graphs. Wear OS → phone → council ingest paths are
  HTTP-mediated and don't belong here. ``TopologyDescriptor`` models
  the workstation's local PipeWire + ALSA graph only.
- No runtime. This module is pure data; Phase 2 ships the generator
  and Phase 3 ships the CLI.

References:
    - docs/research/2026-04-20-unified-audio-architecture-design.md
    - docs/superpowers/plans/2026-04-20-unified-audio-architecture-plan.md
"""

from __future__ import annotations

import math
from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


class NodeKind(StrEnum):
    """Types of nodes in a PipeWire audio graph.

    Each kind maps to a specific PipeWire primitive:

    - ``alsa_source`` / ``alsa_sink``: hardware endpoints (an ALSA PCM
      device wrapped by PipeWire). E.g. L6 USB capture, Ryzen HD Audio
      line-out.
    - ``filter_chain``: a ``libpipewire-module-filter-chain`` instance.
      Covers the voice-fx biquad chain, the L6 Main Mix makeup-gain
      node, any future LADSPA stack.
    - ``loopback``: a ``libpipewire-module-loopback`` bridging two
      endpoints (e.g. hapax-livestream virtual sink → Ryzen analog).
    - ``tap``: a null-sink or virtual sink consumed by OBS/the
      compositor — a fan-out point.
    """

    ALSA_SOURCE = "alsa_source"
    ALSA_SINK = "alsa_sink"
    FILTER_CHAIN = "filter_chain"
    LOOPBACK = "loopback"
    TAP = "tap"


class ChannelMap(BaseModel, frozen=True):
    """Canonical channel layout for a node's audio.

    PipeWire accepts either a channel count (1/2/mono/stereo) or an
    explicit position list like ``[FL, FR]`` or
    ``[AUX0 ... AUX11]`` for multi-channel multitrack capture. The
    descriptor stores the explicit list so the generator can emit
    the exact ``audio.position`` the live graph uses.
    """

    count: int = Field(..., ge=1, le=64)
    # Position tokens follow PipeWire's convention (FL, FR, SL, SR,
    # AUX0..AUX63, MONO). Kept as strings so new PW versions adding
    # positions don't require a code change.
    positions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _positions_match_count(self) -> ChannelMap:
        if self.positions and len(self.positions) != self.count:
            raise ValueError(
                f"ChannelMap.positions length ({len(self.positions)}) "
                f"must equal count ({self.count}) when positions are set"
            )
        return self


class Node(BaseModel, frozen=True):
    """One node in the audio graph.

    Fields:
        id: Descriptor-internal stable identifier. Kebab-case by
            convention. Used as the source/target key in ``Edge``.
        kind: See ``NodeKind``.
        pipewire_name: The ``node.name`` string the live graph uses.
            Must match exactly for ``verify`` to recognise the live
            node as this descriptor node.
        description: Operator-readable label surfaced in tooling (the
            CLI's ``describe`` subcommand, Grafana labels).
        target_object: For ``loopback`` and ``filter_chain`` nodes,
            the upstream ``target.object`` (sink or source) the node
            binds to. ``None`` for hardware endpoints.
        hw: For ``alsa_source``/``alsa_sink``, the ``api.alsa.path``
            like ``hw:L6,0``. Phase 4 inspector reads this from
            ``pw-dump`` to pair live nodes with descriptor nodes.
        channels: Channel map for the node's primary stream.
        params: Arbitrary key/value bag for node-kind-specific
            parameters (``api.alsa.use-acp``, filter-chain graph
            description, loopback passthrough flag, etc.). Treated
            as an opaque pass-through by the generator — each kind's
            template writes the keys it understands and ignores the
            rest.

    Filter-chain template params (schema v3, audit F#8):
        chain_kind: Selects a LADSPA / builtin filter-chain template
            for ``filter_chain`` nodes. ``"loudnorm"`` emits a
            single ``fast_lookahead_limiter_1913`` LADSPA stage.
            ``"duck"`` emits a paired-mono ``builtin mixer`` ducker
            (``duck_l`` / ``duck_r``) with default ``Gain 1 = 1.0``;
            the daemon writes runtime gain via ``pw-cli``.
            ``"usb-bias"`` emits a ``fast_lookahead_limiter_1913``
            with non-zero ``Input gain`` (LADSPA-clamped to
            ``[-20, +20]``) plus optional FL/FR → RL/RR remap.
            ``None`` (the default) preserves the legacy generic
            filter-chain behaviour.
        limit_db: Output ceiling in dBFS for ``loudnorm`` /
            ``usb-bias`` chains. Maps to LADSPA ``Limit (dB)``.
        bias_db: USB-IN line-driver gain in dB for ``usb-bias``
            chains. Maps to LADSPA ``Input gain (dB)``. Clamped to
            ``[-20, +20]``; the generator raises ``ConfigError`` on
            overshoot rather than silently truncating.
        release_s: LADSPA ``Release time (s)`` for ``loudnorm`` /
            ``usb-bias`` chains. Defaults to ``0.20`` for
            ``loudnorm`` when omitted.
        remap_to_rear: When ``True`` on a ``usb-bias`` chain, the
            playback side advertises ``audio.position = [ RL RR ]``
            so the L-12 surround40 sink picks up the bias-driven
            stream on the rear pair (the L-12 USB return convention).
    """

    id: str
    kind: NodeKind
    pipewire_name: str
    description: str = ""
    target_object: str | None = None
    hw: str | None = None
    channels: ChannelMap = Field(
        default_factory=lambda: ChannelMap(count=2, positions=["FL", "FR"])
    )
    params: dict[str, str | int | float | bool] = Field(default_factory=dict)
    chain_kind: Literal["loudnorm", "duck", "usb-bias"] | None = None
    limit_db: float | None = None
    bias_db: float | None = None
    release_s: float | None = None
    remap_to_rear: bool | None = None

    @field_validator("id")
    @classmethod
    def _id_is_kebab(cls, v: str) -> str:
        if not v or any(c.isspace() for c in v) or v != v.lower():
            raise ValueError(
                f"Node.id={v!r} — must be lowercase, no whitespace (kebab-case convention)"
            )
        return v

    @model_validator(mode="after")
    def _hardware_nodes_have_hw(self) -> Node:
        if self.kind in (NodeKind.ALSA_SOURCE, NodeKind.ALSA_SINK) and not self.hw:
            raise ValueError(
                f"Node {self.id!r}: kind={self.kind.value} requires hw (api.alsa.path) to be set"
            )
        return self


class Edge(BaseModel, frozen=True):
    """A directed link between two nodes in the graph.

    Fields:
        source: ``Node.id`` of the upstream node.
        source_port: Optional port specifier (e.g. ``FL``, ``AUX10``).
            When omitted, the whole node's primary output links to the
            target's primary input — PipeWire's default auto-link
            behaviour.
        target: ``Node.id`` of the downstream node.
        target_port: Optional downstream port. See ``source_port``.
        makeup_gain_db: Gain applied at the edge. Phase 2 generator
            translates this to a ``builtin mixer`` filter-chain node
            with ``Gain 1`` set to the linear equivalent. Zero dB
            means pass-through; ≠ 0 inserts a gain stage. Range
            ``[-60, +30]`` — beyond that is pathological and almost
            certainly a bug in the descriptor.
    """

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
                f"Edge.makeup_gain_db={v!r} — must be in [-60, +30] dB "
                "(values outside this range are pathological)"
            )
        return v


class TopologyDescriptor(BaseModel, frozen=True):
    """Complete declarative description of the workstation's audio graph.

    Serialises round-trip to YAML via ``to_yaml()``/``from_yaml()``.
    Validation at parse time catches: dangling edges (source/target
    references a non-existent node), duplicate node IDs, inverted
    channel maps, out-of-range gains.

    Versioning: ``schema_version`` increments on breaking schema
    changes so older descriptors can be migrated explicitly. Current
    = 3 (2026-05-02 — Node typed filter-chain template params
    ``chain_kind`` / ``limit_db`` / ``bias_db`` / ``release_s`` /
    ``remap_to_rear`` for the LADSPA loudnorm / duck / usb-bias
    generator templates, audit F#8). Schema 2 still parses for
    backward compatibility (typed chain params remain ``None`` on
    nodes that omit them); new descriptors write 3. Schema 1 is
    no longer accepted — the v1 → v2 symbolic ALSA card-id
    migration must complete before parsing succeeds.
    """

    schema_version: Literal[2, 3] = 3
    description: str = ""
    nodes: list[Node]
    edges: list[Edge] = Field(default_factory=list)

    @field_validator("nodes")
    @classmethod
    def _node_ids_unique(cls, v: list[Node]) -> list[Node]:
        seen: set[str] = set()
        for node in v:
            if node.id in seen:
                raise ValueError(f"Duplicate node id: {node.id!r}")
            seen.add(node.id)
        return v

    @model_validator(mode="after")
    def _edges_reference_valid_nodes(self) -> TopologyDescriptor:
        node_ids = {n.id for n in self.nodes}
        for edge in self.edges:
            if edge.source not in node_ids:
                raise ValueError(
                    f"Edge {edge.source!r} → {edge.target!r}: source not in descriptor nodes"
                )
            if edge.target not in node_ids:
                raise ValueError(
                    f"Edge {edge.source!r} → {edge.target!r}: target not in descriptor nodes"
                )
        return self

    def node_by_id(self, node_id: str) -> Node:
        for n in self.nodes:
            if n.id == node_id:
                return n
        raise KeyError(f"No node with id {node_id!r} in descriptor")

    def edges_from(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.source == node_id]

    def edges_to(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.target == node_id]

    def to_yaml(self) -> str:
        # Pydantic's model_dump preserves field order; yaml dumps with
        # default_flow_style=False so the output reads top-down.
        return yaml.safe_dump(
            self.model_dump(mode="json"), default_flow_style=False, sort_keys=False
        )

    @classmethod
    def from_yaml(cls, source: str | Path) -> TopologyDescriptor:
        if isinstance(source, Path):
            raw = source.read_text()
        else:
            raw = source
        data = yaml.safe_load(raw)
        # Parser-front guard: validate schema_version explicitly so older v1
        # descriptors (or anything outside the supported window) fail with a
        # message that mentions the version, not a deeply-nested pydantic
        # Literal-mismatch error.
        if isinstance(data, dict) and data.get("schema_version") not in (2, 3):
            raise ValueError(
                f"unknown schema_version: {data.get('schema_version')!r} (supported: 2, 3)"
            )
        return cls.model_validate(data)
