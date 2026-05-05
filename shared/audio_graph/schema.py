"""Pydantic models for the audio graph SSOT.

Implements the spec's 7 base models PLUS 12 schema-additive gap-folds
from the alignment audit. See module docstring of
:mod:`shared.audio_graph` for the gap mapping.

Design notes
------------

Every model carries
``model_config = ConfigDict(extra="forbid", frozen=True)`` so the
schema is **transactional**: any unknown key in input data fails
validation rather than being silently ignored, and every instance is
hashable / immutable so the daemon's apply lock can pass references
across threads without defensive copies.

The :class:`AudioGraph` root is a strict superset of
:class:`shared.audio_topology.TopologyDescriptor`. We do not subclass
the existing descriptor because we want forbid-extra and frozen=True
without breaking the older descriptor's downstream consumers
(generator, inspector, switcher), which still write into the v3
descriptor's ``params`` dict at parse-time.

Channel positions
-----------------

PipeWire's canonical positions (``shared.audio_topology.ChannelMap``)
remain the source of vocabulary; the spec does not enumerate them.
For port-compatibility checks, we treat positions as opaque strings
matched case-insensitively (``aux1`` ≡ ``AUX1``), which matches
PipeWire's handling.

Gap mapping (audit §7)
----------------------

- G-1 (global tunables) → :class:`GlobalTunables` + ``AudioGraph.tunables``.
- G-2 (ALSA card profile pin) → :class:`AlsaProfilePin` +
  :class:`AlsaCardRule` + ``AudioGraph.alsa_rules``.
- G-3 (channel-pick too narrow) → :class:`MixdownGraph` +
  :class:`MixerRoute` + ``DownmixStrategy.LADSPA_MIXDOWN``.
- G-4 (chain_kind="loudnorm-wet") → :class:`FilterChainTemplate`
  discriminated union (taxonomy includes ``loudnorm-with-comp-and-reverb``).
- G-5 (typed fail_closed) → ``AudioNode.fail_closed``.
- G-6 (remap-source loopback) → :class:`RemapSource` +
  ``LoopbackTopology.virtual_source_metadata``.
- G-7 (chain_kind too coarse) → richer :class:`FilterChainTemplate`
  (``loudnorm-simple``, ``loudnorm-with-comp``,
  ``loudnorm-with-comp-and-reverb``, ``voice-fx-biquad``,
  ``ducker-sidechain``, ``builtin-mixer-duck``).
- G-8 (loopback flags) → :class:`LoopbackTopology` extends with
  ``dont_reconnect``, ``dont_move``, ``linger``, ``state_restore``.
- G-9 (FormatSpec missing) → :class:`FormatSpec` typed model.
- G-10 (fan-out) → :class:`Fanout` model.
- G-11 (config/pipewire drift) → ``AudioGraph.deployed_root_path`` +
  ``config_root_path`` typed paths.
- G-12 (WirePlumber non-loopback rules) → :class:`WireplumberRule`
  parent + concrete subclasses.
- G-13 (role-based loopback infrastructure) →
  :class:`RoleLoopback` + :class:`MediaRoleSink` + :class:`DuckPolicy`
  + :class:`PreferredTargetPin`.
- G-14 (bluez) → :class:`BluezRule`.
- G-15 (restore-stream rules) → :class:`StreamRestoreRule`.
- G-16 (stream pin rules) → :class:`StreamPin`.
- G-17 (acknowledged punt) → documented in spec §8 only; no schema
  field at this phase.
"""

from __future__ import annotations

import math
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Vocabulary enums
# ---------------------------------------------------------------------------


class NodeKind(StrEnum):
    """Types of nodes in a PipeWire audio graph.

    Same vocabulary as ``shared.audio_topology.NodeKind`` so the
    inspector / generator can use either model with the same kind
    string.
    """

    ALSA_SOURCE = "alsa_source"
    ALSA_SINK = "alsa_sink"
    FILTER_CHAIN = "filter_chain"
    LOOPBACK = "loopback"
    TAP = "tap"


class FilterChainTemplate(StrEnum):
    """Discriminated union of filter-chain shapes (gap G-4 + G-7).

    The spec's original ``chain_kind = ["loudnorm", "duck", "usb-bias"]``
    cannot express:

    - M8 chain (``sc4m + plate + fast_lookahead_limiter``)  → ``loudnorm-with-comp-and-reverb``
    - PC/YT chain (``sc4m + sc4m + fast_lookahead_limiter``) → ``loudnorm-with-comp``
    - Music chain (``fast_lookahead_limiter`` alone)         → ``loudnorm-simple``
    - Voice-fx (``biquad`` per channel)                       → ``voice-fx-biquad``
    - YouTube ducker (``sc4m`` as sidechain)                  → ``ducker-sidechain``
    - Music duck (``builtin mixer`` controlled via pw-cli)    → ``builtin-mixer-duck``

    ``custom`` is the explicit escape hatch — when set, the
    :attr:`AudioNode.filter_graph_stages` field carries the
    full per-stage description.
    """

    LOUDNORM_SIMPLE = "loudnorm-simple"
    LOUDNORM_WITH_COMP = "loudnorm-with-comp"
    LOUDNORM_WITH_COMP_AND_REVERB = "loudnorm-with-comp-and-reverb"
    VOICE_FX_BIQUAD = "voice-fx-biquad"
    DUCKER_SIDECHAIN = "ducker-sidechain"
    BUILTIN_MIXER_DUCK = "builtin-mixer-duck"
    USB_BIAS = "usb-bias"
    CUSTOM = "custom"


class DownmixStrategy(StrEnum):
    """How a channel-count change at a node boundary is realised.

    Gap G-3: spec's flat ``map: dict[str, str]`` cannot express the
    L-12 14→2 software mixdown (the very failure that motivated the
    spec). ``LADSPA_MIXDOWN`` adds the structured shape.
    """

    CHANNEL_PICK = "channel-pick"
    MIXDOWN_EQUAL = "mixdown-equal"
    LADSPA_MIXDOWN = "ladspa-mixdown"
    BROADCAST_FAN_OUT = "broadcast-fan-out"


# ---------------------------------------------------------------------------
# Format spec (gap G-9)
# ---------------------------------------------------------------------------


class FormatSpec(BaseModel):
    """Audio sample format declared at a node / link boundary.

    Spec promised this model but did not define it; PipeWire's
    ``audio.format``, ``audio.rate``, ``audio.channels`` triple needs
    a typed shape to drive ``FORMAT_COMPATIBILITY`` invariant checks.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    rate_hz: Literal[16000, 44100, 48000] = 48000
    format: Literal["S16LE", "S24LE", "S32LE", "F32LE"] = "S32LE"
    channels: int = Field(..., ge=1, le=64)


# ---------------------------------------------------------------------------
# Channel map (re-export shape; matches existing audio_topology.ChannelMap)
# ---------------------------------------------------------------------------


class ChannelMap(BaseModel):
    """Canonical channel layout; positions track PipeWire vocabulary.

    Re-uses the shape of :class:`shared.audio_topology.ChannelMap`
    but enforces ``frozen=True`` and ``extra="forbid"``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    count: int = Field(..., ge=1, le=64)
    positions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _positions_match_count(self) -> ChannelMap:
        if self.positions and len(self.positions) != self.count:
            raise ValueError(
                f"ChannelMap.positions length ({len(self.positions)}) "
                f"must equal count ({self.count}) when positions are set"
            )
        return self


# ---------------------------------------------------------------------------
# Filter-chain stage (gap G-7)
# ---------------------------------------------------------------------------


class FilterStage(BaseModel):
    """One LADSPA / builtin filter-chain stage in a multi-stage chain.

    Replaces the current implicit-from-``chain_kind`` modelling with an
    explicit per-stage description, so chains like
    ``sc4m + sc4m + fast_lookahead_limiter`` (PC loudnorm) and
    ``sc4m + plate + fast_lookahead_limiter`` (M8) can be expressed
    as data, not as a hand-edited conf.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["builtin", "ladspa"]
    plugin: str | None = None  # required when type=ladspa
    label: str
    name: str
    control: dict[str, float | str | int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _ladspa_requires_plugin(self) -> FilterStage:
        if self.type == "ladspa" and not self.plugin:
            raise ValueError(
                f"FilterStage(name={self.name!r}, type=ladspa) requires plugin to be set"
            )
        return self


# ---------------------------------------------------------------------------
# Gain stage (spec §2.1, gap G-8 hardware bleed surfacing)
# ---------------------------------------------------------------------------


class GainStage(BaseModel):
    """Declarative gain stage attached to an edge / mixdown.

    Adds per-channel and bleed-aware variants on top of the existing
    ``Edge.makeup_gain_db``. Today's failure #6 (``gain_samp=1.0`` on
    AUX3 with -27 dB hardware bleed signature) is the motivating case
    — this model lets the operator surface the bleed measurement
    explicitly and the ``HARDWARE_BLEED_GUARD`` invariant prevents an
    accidental amplification of the bleed source.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    edge_source: str
    edge_target: str
    edge_source_port: str | None = None
    base_gain_db: float = Field(default=0.0, ge=-90.0, le=30.0)
    per_channel_overrides: dict[str, float] = Field(default_factory=dict)
    declared_bleed_db: float | None = None

    @field_validator("base_gain_db")
    @classmethod
    def _gain_finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError(f"GainStage.base_gain_db must be finite (got {v!r})")
        return v


# ---------------------------------------------------------------------------
# Mixdown graph (gap G-3 — L-12 14→2 expressibility)
# ---------------------------------------------------------------------------


class MixerRoute(BaseModel):
    """One source-to-sum input wiring within a mixdown graph.

    Models the L-12 ``links`` block: ``gain_evilpet:Out → sum_l:In 1``
    plus the gain assignment on each sum input position.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_stage: str  # e.g. "gain_evilpet"
    source_port: str = "Out"
    sink_stage: str  # e.g. "sum_l"
    sink_port: str  # e.g. "In 1"
    gain: float = 1.0


class MixdownGraph(BaseModel):
    """Structured ``ladspa-mixdown`` graph (gap G-3).

    L-12 capture is 14 ch → 2 ch via 4 per-channel mixer gains
    summing into 2 mixer busses. Spec's ``map: dict[str, str]``
    cannot model this without losing the gain scalars.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    stages: list[GainStage] = Field(default_factory=list)
    routes: list[MixerRoute] = Field(default_factory=list)
    output_stages: list[str] = Field(default_factory=list)


class DownmixRoute(BaseModel):
    """One position-to-position route inside a CHANNEL_PICK downmix."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target_position: str  # e.g. "FL"
    source_positions: list[str] = Field(default_factory=list)  # e.g. ["AUX1"]


class ChannelDownmix(BaseModel):
    """Explicit declaration of a channel-count change at a node boundary.

    If absent and the descriptor introduces a count change between
    ``source.channels.count != target.channels.count``, the
    ``FORMAT_COMPATIBILITY`` invariant fails (today's #5 silent-downmix bug).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_node: str
    target_node: str
    strategy: DownmixStrategy
    routes: list[DownmixRoute] = Field(default_factory=list)
    mixdown: MixdownGraph | None = None
    source_format: FormatSpec | None = None
    target_format: FormatSpec | None = None

    @model_validator(mode="after")
    def _strategy_requires_correct_payload(self) -> ChannelDownmix:
        if self.strategy == DownmixStrategy.LADSPA_MIXDOWN and self.mixdown is None:
            raise ValueError(
                f"ChannelDownmix({self.source_node}→{self.target_node}) with strategy="
                f"ladspa-mixdown requires mixdown:MixdownGraph to be set"
            )
        if self.strategy == DownmixStrategy.CHANNEL_PICK and not self.routes:
            raise ValueError(
                f"ChannelDownmix({self.source_node}→{self.target_node}) with strategy="
                f"channel-pick requires routes:list[DownmixRoute] to be non-empty"
            )
        return self


# ---------------------------------------------------------------------------
# Loopback topology (spec §2.1 + gap G-8 + gap G-6)
# ---------------------------------------------------------------------------


class RemapSource(BaseModel):
    """Loopback whose playback side advertises ``Audio/Source`` (gap G-6).

    ``hapax-obs-broadcast-remap.conf`` is functionally a remap-source
    for OBS persistence, declaring ``device.class=filter`` and
    ``node.virtual=true`` on the playback side. Carry the metadata
    explicitly so the validator sees this node as a stable target
    rather than as a regular loopback.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    media_class: Literal["Audio/Source"] = "Audio/Source"
    device_class: Literal["filter"] = "filter"
    node_virtual: bool = True


class LoopbackTopology(BaseModel):
    """Explicit model of a ``module-loopback`` instance.

    Extends the spec's base shape with the four flags surfaced in
    audit gap G-8 (``dont_reconnect``, ``dont_move``, ``linger``,
    ``state_restore``) and the optional :class:`RemapSource` overlay
    from gap G-6.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str
    source: str
    sink: str
    source_dont_move: bool = True
    sink_dont_move: bool = True
    fail_closed_on_target_absent: bool = True
    apply_via_pactl_load: bool = False
    # Gap G-8 — hapax-private-monitor-bridge.conf flags.
    dont_reconnect: bool = False
    dont_move: bool = False
    linger: bool = False
    state_restore: bool = True
    # Gap G-6 — remap-source overlay (optional; presence means "this
    # loopback playback advertises Audio/Source").
    remap_source: RemapSource | None = None
    # Gap G-9 — sample format on the loopback boundary.
    format: FormatSpec | None = None
    latency_msec: int | None = None
    passive_capture: bool = False
    passive_playback: bool = True
    stream_dont_remix: bool = False
    stream_capture_sink: bool = False


# ---------------------------------------------------------------------------
# Fan-out (gap G-10 — TTS-broadcast splits one filter into two destinations)
# ---------------------------------------------------------------------------


class Fanout(BaseModel):
    """Explicit fan-out from one node to N destinations (gap G-10).

    ``hapax-tts-duck.conf`` produces a filter-chain whose output goes
    to BOTH the L-12 USB return AND the livestream tap (via separate
    parallel ``module-loopback``). Two separate edges represent this
    today; this model surfaces it as a typed concept the breaker can
    reason about (one fan-out, two probe boundaries, gain conserved).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_node: str
    targets: list[str] = Field(..., min_length=2)
    description: str = ""


# ---------------------------------------------------------------------------
# Audio node (extends shared.audio_topology.Node with gap-fields)
# ---------------------------------------------------------------------------


class AudioNode(BaseModel):
    """One node in the audio graph.

    Mirrors :class:`shared.audio_topology.Node` for migration parity,
    plus:

    - :attr:`fail_closed` (gap G-5) — typed boolean for endpoint
      ``fail_closed=true`` declarations.
    - :attr:`format` (gap G-9) — typed format spec.
    - :attr:`filter_chain_template` (gap G-4 + G-7) — typed enum.
    - :attr:`filter_graph_stages` — used when
      ``filter_chain_template=CUSTOM``.
    - :attr:`mixdown` — optional :class:`MixdownGraph` for filter-chain
      nodes that perform a channel-count change.
    - :attr:`private_monitor_endpoint` — typed boolean for the spec's
      ``params.private_monitor_endpoint`` flag.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    kind: NodeKind
    pipewire_name: str
    description: str = ""
    target_object: str | None = None
    hw: str | None = None
    channels: ChannelMap = Field(
        default_factory=lambda: ChannelMap(count=2, positions=["FL", "FR"])
    )
    format: FormatSpec | None = None
    # Gap G-5 — typed fail-closed for null-sink TAPs.
    fail_closed: bool = False
    private_monitor_endpoint: bool = False
    # Spec §2.1 + gap G-7 — typed filter-chain shape.
    filter_chain_template: FilterChainTemplate | None = None
    filter_graph_stages: list[FilterStage] = Field(default_factory=list)
    # Loudnorm / usb-bias parametric knobs (parity with audio_topology v3).
    limit_db: float | None = None
    bias_db: float | None = None
    release_s: float | None = None
    remap_to_rear: bool | None = None
    # Gap G-3 — embedded mixdown for filter-chain nodes that downmix.
    mixdown: MixdownGraph | None = None
    # Free-form extras for back-compat. Kept narrow: int / float / bool /
    # str. Anything richer than that should be promoted to a typed field.
    params: dict[str, str | int | float | bool] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _id_is_kebab(cls, v: str) -> str:
        if not v or any(c.isspace() for c in v) or v != v.lower():
            raise ValueError(f"AudioNode.id={v!r} — must be lowercase, no whitespace (kebab-case)")
        return v

    @model_validator(mode="after")
    def _hardware_nodes_have_hw(self) -> AudioNode:
        if self.kind in (NodeKind.ALSA_SOURCE, NodeKind.ALSA_SINK) and not self.hw:
            raise ValueError(f"AudioNode {self.id!r}: kind={self.kind.value} requires hw to be set")
        return self

    @model_validator(mode="after")
    def _custom_template_requires_stages(self) -> AudioNode:
        if (
            self.filter_chain_template == FilterChainTemplate.CUSTOM
            and not self.filter_graph_stages
        ):
            raise ValueError(
                f"AudioNode {self.id!r}: filter_chain_template=custom requires "
                "filter_graph_stages to be non-empty"
            )
        return self


# ---------------------------------------------------------------------------
# Audio link (extends Edge with port-pair typing for PORT_COMPATIBILITY)
# ---------------------------------------------------------------------------


class AudioLink(BaseModel):
    """A directed link between two nodes in the graph.

    Same shape as :class:`shared.audio_topology.Edge` but with
    explicit port-vocabulary types so the ``PORT_COMPATIBILITY``
    invariant can compare positions.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str
    source_port: str | None = None
    target: str
    target_port: str | None = None
    makeup_gain_db: float = 0.0
    gain_stage: GainStage | None = None  # optional richer gain description

    @field_validator("makeup_gain_db")
    @classmethod
    def _gain_in_range(cls, v: float) -> float:
        if not math.isfinite(v) or v < -60.0 or v > 30.0:
            raise ValueError(f"AudioLink.makeup_gain_db={v!r} — must be in [-60, +30] dB")
        return v


# ---------------------------------------------------------------------------
# Global tunables (gap G-1)
# ---------------------------------------------------------------------------


class GlobalTunables(BaseModel):
    """PipeWire ``context.properties`` tunables (gap G-1).

    Models ``10-voice-quantum.conf`` / ``hapax-quantum.conf``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    default_clock_quantum: int | None = None
    min_quantum: int | None = None
    max_quantum: int | None = None
    allowed_rates: list[int] = Field(default_factory=list)
    extra_properties: dict[str, str | int | float | bool] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# WirePlumber rules (gap G-2 + G-12 + G-14 + G-15 + G-16 + G-17)
# ---------------------------------------------------------------------------


class AlsaProfilePin(BaseModel):
    """Profile-pinning rule on an ALSA card (gaps G-2 + G-17 partial).

    ``hapax-s4-usb-sink.conf`` pins the S-4 to its ``pro-audio`` profile so
    all 10 channels enumerate. ``60-ryzen-analog-always.conf`` pins
    the Ryzen HDA to ``analog-stereo``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    card_match: str
    profile: str | None = None
    api_alsa_use_acp: bool | None = None
    priority_session: int | None = None
    priority_driver: int | None = None


class AlsaCardRule(BaseModel):
    """Generic ``monitor.alsa.rules`` block (gap G-12).

    Covers suspend timeouts, sample-rate pins, volume defaults, and
    ``intended-roles`` directives.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    description: str = ""
    matches: list[dict[str, str]] = Field(default_factory=list)
    update_props: dict[str, str | int | float | bool | list[int] | list[str]] = Field(
        default_factory=dict
    )


class BluezRule(BaseModel):
    """Bluez monitor rule (gap G-14).

    Covers ``52-iloud-no-suspend.conf``, ``56-bluez-codec-priority.conf``,
    ``70-iloud-never-default.conf``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    description: str = ""
    matches: list[dict[str, str]] = Field(default_factory=list)
    update_props: dict[str, str | int | float | bool | list[int] | list[str]] = Field(
        default_factory=dict
    )
    properties: dict[str, str | int | float | bool] = Field(default_factory=dict)


class StreamRestoreRule(BaseModel):
    """Stream-restore rule (gap G-15).

    Models ``55-hapax-private-no-restore.conf``: marks streams whose
    runtime-state should not persist across restarts.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    matches: list[dict[str, str]] = Field(default_factory=list)
    state_restore_target: bool = False
    state_restore_props: bool = False


class StreamPin(BaseModel):
    """Stream-target pinning rule (gap G-16).

    Models ``56-hapax-private-pin-s4-track-1.conf``: pins specific
    streams to a target node and prevents WirePlumber from re-routing.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    matches: list[dict[str, str]] = Field(default_factory=list)
    target_object: str
    dont_fallback: bool = True
    dont_reconnect: bool = True
    dont_move: bool = True
    linger: bool = True
    priority_session: int | None = None


# ---------------------------------------------------------------------------
# Role-based loopback infrastructure (gap G-13 — the load-bearing one)
# ---------------------------------------------------------------------------


class PreferredTargetPin(BaseModel):
    """Per-role preferred-target sink pin (gap G-13).

    ``50-hapax-voice-duck.conf`` pins each role's loopback to a
    specific sink (``hapax-private``, ``hapax-pc-loudnorm``,
    ``hapax-voice-fx-capture``, ``hapax-notification-private``).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: str  # e.g. "Multimedia", "Notification", "Assistant", "Broadcast"
    preferred_target: str
    same_priority_action: Literal["mix", "duck", "cork"] = "mix"
    lower_priority_action: Literal["mix", "duck", "cork"] = "mix"


class DuckPolicy(BaseModel):
    """Role-based ducking policy (gap G-13).

    Captures ``linking.role-based.duck-level`` and the per-role
    priority/action map.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    duck_level: float = Field(default=0.3, ge=0.0, le=1.0)
    default_media_role: str = "Multimedia"
    role_priorities: dict[str, int] = Field(default_factory=dict)


class RoleLoopback(BaseModel):
    """One entry in the role-loopback infrastructure (gap G-13).

    Each role (Multimedia, Notification, Assistant, Broadcast) is
    backed by a ``module-loopback`` declared as a
    ``wireplumber.components`` entry. This model surfaces:

    - ``role`` — declared media role string.
    - ``loopback_node_name`` — e.g. ``loopback.sink.role.assistant``.
    - ``priority`` — integer ordering (10 = lowest, 40 = highest).
    - ``intended_roles`` — what role tags this loopback claims.
    - ``preferred_target`` — sink to which the role pins by default.
    - ``node_volume`` — initial volume on the loopback capture side.
    - ``state_restore`` — whether the loopback's stream-state may persist.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: str
    loopback_node_name: str
    description: str = ""
    priority: int = Field(..., ge=0)
    intended_roles: list[str] = Field(default_factory=list)
    preferred_target: str | None = None
    node_volume: float = Field(default=1.0, ge=0.0, le=4.0)
    same_priority_action: Literal["mix", "duck", "cork"] = "mix"
    lower_priority_action: Literal["mix", "duck", "cork"] = "mix"
    state_restore: bool = False


class MediaRoleSink(BaseModel):
    """Bundle of role-loopback infrastructure typed as a single unit (gap G-13).

    ``50-hapax-voice-duck.conf`` declares the whole role-based ducking
    surface in one conf. We keep them grouped so the validator can
    diff a single conf against a single model instance.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    duck_policy: DuckPolicy
    loopbacks: list[RoleLoopback] = Field(default_factory=list)
    preferred_target_pins: list[PreferredTargetPin] = Field(default_factory=list)


class WireplumberRule(BaseModel):
    """Catch-all parent for non-typed wireplumber rules (gap G-12).

    For rules whose typed shape isn't yet modelled, we keep the
    string content in ``raw_content`` and surface them as
    "untyped wireplumber rules" in :class:`AudioGraphValidator`
    output. This keeps the validator forward-compatible without
    silently dropping operator-meaningful state.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str  # filename, e.g. "55-hapax-private-no-restore.conf"
    description: str = ""
    raw_content: str = ""


# ---------------------------------------------------------------------------
# Broadcast invariant (spec §2.1)
# ---------------------------------------------------------------------------


# Note: invariant kinds + severity + violation live in
# :mod:`shared.audio_graph.invariants`. We re-import them at runtime
# below so the schema model can typecheck without a forward declaration.


class BroadcastInvariant(BaseModel):
    """One invariant the topology must satisfy.

    The applier checks every BroadcastInvariant before writing any
    artefact and after applying. Violations of severity=BLOCKING
    refuse the apply atomically. Violations of severity=WARNING land
    in the daemon's audit log and trigger an ntfy.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str  # InvariantKind value
    severity: str = "blocking"  # InvariantSeverity value
    description: str
    check_fn_name: str


# ---------------------------------------------------------------------------
# Root model
# ---------------------------------------------------------------------------


class AudioGraph(BaseModel):
    """Single-source-of-truth audio graph descriptor.

    The root model that drives the SSOT compiler + validator. Schema
    version 4 (extends :class:`shared.audio_topology.TopologyDescriptor`'s
    schema 3 with the gap-folds).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[4] = 4
    description: str = ""
    # Path config (gap G-11).
    deployed_root_path: Path = Path("~/.config/pipewire/pipewire.conf.d")
    deployed_wireplumber_root_path: Path = Path("~/.config/wireplumber/wireplumber.conf.d")
    config_root_path: Path | None = None  # Set when source-of-truth lives in repo.

    # Core graph (spec §2.1).
    nodes: list[AudioNode]
    links: list[AudioLink] = Field(default_factory=list)
    loopbacks: list[LoopbackTopology] = Field(default_factory=list)
    channel_downmixes: list[ChannelDownmix] = Field(default_factory=list)
    fanouts: list[Fanout] = Field(default_factory=list)
    gain_stages: list[GainStage] = Field(default_factory=list)
    invariants: list[BroadcastInvariant] = Field(default_factory=list)

    # Gap G-1 — global tunables.
    tunables: list[GlobalTunables] = Field(default_factory=list)

    # Gap G-2 — ALSA card profile pinning.
    alsa_profile_pins: list[AlsaProfilePin] = Field(default_factory=list)

    # Gap G-12 — typed ALSA card rules (suspend timeouts, etc.)
    alsa_rules: list[AlsaCardRule] = Field(default_factory=list)

    # Gap G-13 — role-based loopback infrastructure.
    media_role_sinks: list[MediaRoleSink] = Field(default_factory=list)

    # Gap G-14 — bluez rules.
    bluez_rules: list[BluezRule] = Field(default_factory=list)

    # Gap G-15 — stream-restore rules.
    stream_restore_rules: list[StreamRestoreRule] = Field(default_factory=list)

    # Gap G-16 — stream-pin rules.
    stream_pins: list[StreamPin] = Field(default_factory=list)

    # Gap G-12 catch-all — un-typed wireplumber rules retained as text.
    untyped_wireplumber_rules: list[WireplumberRule] = Field(default_factory=list)

    @field_validator("nodes")
    @classmethod
    def _node_ids_unique(cls, v: list[AudioNode]) -> list[AudioNode]:
        seen: set[str] = set()
        for node in v:
            if node.id in seen:
                raise ValueError(f"Duplicate node id: {node.id!r}")
            seen.add(node.id)
        return v

    @field_validator("nodes")
    @classmethod
    def _pipewire_names_unique(cls, v: list[AudioNode]) -> list[AudioNode]:
        """NO_DUPLICATE_PIPEWIRE_NAMES — also a runtime invariant."""
        seen: set[str] = set()
        for node in v:
            if node.pipewire_name in seen:
                raise ValueError(
                    f"Duplicate pipewire_name: {node.pipewire_name!r} on node {node.id!r}"
                )
            seen.add(node.pipewire_name)
        return v

    @model_validator(mode="after")
    def _links_reference_valid_nodes(self) -> AudioGraph:
        node_ids = {n.id for n in self.nodes}
        for link in self.links:
            if link.source not in node_ids:
                raise ValueError(f"AudioLink {link.source!r}→{link.target!r}: source not in nodes")
            if link.target not in node_ids:
                raise ValueError(f"AudioLink {link.source!r}→{link.target!r}: target not in nodes")
        return self

    @model_validator(mode="after")
    def _loopbacks_reference_valid_nodes(self) -> AudioGraph:
        node_ids = {n.id for n in self.nodes}
        # Loopbacks may reference external pipewire node names (target.object
        # can be an alsa_output or another loopback's pipewire_name) so we
        # validate node_id only.
        for lb in self.loopbacks:
            if lb.node_id not in node_ids:
                raise ValueError(f"LoopbackTopology(node_id={lb.node_id!r}): node not in nodes")
        return self

    @model_validator(mode="after")
    def _downmixes_reference_valid_nodes(self) -> AudioGraph:
        node_ids = {n.id for n in self.nodes}
        for cdm in self.channel_downmixes:
            if cdm.source_node not in node_ids:
                raise ValueError(
                    f"ChannelDownmix({cdm.source_node}→{cdm.target_node}): source_node not in nodes"
                )
            if cdm.target_node not in node_ids:
                raise ValueError(
                    f"ChannelDownmix({cdm.source_node}→{cdm.target_node}): target_node not in nodes"
                )
        return self

    # ------------------------------------------------------------------
    # Convenience accessors used by validator + invariants.
    # ------------------------------------------------------------------

    def node_by_id(self, node_id: str) -> AudioNode:
        for n in self.nodes:
            if n.id == node_id:
                return n
        raise KeyError(f"No node with id {node_id!r} in AudioGraph")

    def node_by_pipewire_name(self, pw_name: str) -> AudioNode | None:
        for n in self.nodes:
            if n.pipewire_name == pw_name:
                return n
        return None

    def links_from(self, node_id: str) -> list[AudioLink]:
        return [link for link in self.links if link.source == node_id]

    def links_to(self, node_id: str) -> list[AudioLink]:
        return [link for link in self.links if link.target == node_id]

    def adjacency(self) -> dict[str, list[str]]:
        """node_id → list of node_ids reachable in one hop (link, fanout, downmix)."""
        adj: dict[str, list[str]] = {n.id: [] for n in self.nodes}
        for link in self.links:
            adj[link.source].append(link.target)
        for fan in self.fanouts:
            adj[fan.source_node].extend(fan.targets)
        for cdm in self.channel_downmixes:
            adj[cdm.source_node].append(cdm.target_node)
        return adj

    # ------------------------------------------------------------------
    # Serialisation.
    # ------------------------------------------------------------------

    def to_yaml(self) -> str:
        return yaml.safe_dump(
            self.model_dump(mode="json"), default_flow_style=False, sort_keys=False
        )

    @classmethod
    def from_yaml(cls, source: str | Path) -> AudioGraph:
        if isinstance(source, Path):
            raw = source.read_text()
        else:
            raw = source
        data = yaml.safe_load(raw)
        if not isinstance(data, dict):
            raise ValueError("AudioGraph.from_yaml expects a top-level mapping")
        if data.get("schema_version") != 4:
            raise ValueError(f"unknown schema_version: {data.get('schema_version')!r} (expected 4)")
        return cls.model_validate(data)


# Re-export of frequently-used aliases.
__all__: list[Any] = [
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
]
