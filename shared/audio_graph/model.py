"""Port-level mk5 audio graph model.

This module is the additive Phase 1+2 model for the mk5 compiler. It is
deliberately separate from :mod:`shared.audio_graph.schema`, which still models
the older node-level SSOT work and is used by existing tests/consumers.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

import shared.audio_loudness as loudness


class ExposureDomain(StrEnum):
    """Privacy/routing domain on a single PipeWire port."""

    BROADCAST = "broadcast"
    BROADCAST_PROCESSOR = "broadcast_processor"
    BROADCAST_EGRESS = "broadcast_egress"
    BROADCAST_MONITOR = "broadcast_monitor"
    PRIVATE = "private"
    NOTIFICATION = "notification"
    QUARANTINE = "quarantine"
    UNKNOWN = "unknown"
    DISABLED = "disabled"
    FAILED = "failed"
    HARDWARE_OPAQUE = "hardware_opaque"


class PortDirection(StrEnum):
    """Direction of a PipeWire port in the host graph."""

    INPUT = "input"
    OUTPUT = "output"
    MONITOR = "monitor"
    DUPLEX = "duplex"


class ModulationPath(StrEnum):
    """Exactly one modulation path per authorized source."""

    DRY = "dry"
    SOFTWARE_WET = "software_wet"
    HARDWARE_CHARACTER = "hardware_character"
    QUARANTINE = "quarantine"


class DevicePort(BaseModel):
    """A physical or hardware-facing PipeWire port."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ref: str
    exposure: ExposureDomain
    direction: PortDirection
    description: str = ""
    channel: str | None = None
    target_object_pinned: bool = True
    autoconnect: bool = False
    dont_reconnect: bool = True
    dont_move: bool = True
    state_restore: bool = False
    monitor_port: bool = False
    default_sink_eligible: bool = False
    tags: list[str] = Field(default_factory=list)

    @field_validator("ref")
    @classmethod
    def _ref_is_port_ref(cls, v: str) -> str:
        if ":" not in v:
            raise ValueError(f"port ref {v!r} must be in node:port form")
        return v


class DeviceSpec(BaseModel):
    """Hardware or virtual device identity plus typed ports."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["alsa", "pipewire", "midi", "opaque_hardware"]
    description: str = ""
    match: dict[str, str] = Field(default_factory=dict)
    profile: str | None = None
    api_alsa_use_acp: bool | None = None
    ports: dict[str, DevicePort] = Field(default_factory=dict)
    disabled_by_default: bool = False
    hardware_opaque: bool = False


class GraphPort(BaseModel):
    """Port on a generated logical graph node."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    exposure: ExposureDomain
    direction: PortDirection
    description: str = ""
    target_object_pinned: bool = True
    autoconnect: bool = False
    dont_reconnect: bool = True
    dont_move: bool = True
    state_restore: bool = False
    monitor_port: bool = False
    default_sink_eligible: bool = False
    tags: list[str] = Field(default_factory=list)


class GraphNode(BaseModel):
    """Generated PipeWire/WirePlumber node used by the offline compiler."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal[
        "role",
        "source",
        "wet",
        "dry_safe",
        "normalizer",
        "duck",
        "bus",
        "monitor",
        "processor",
        "egress",
        "hardware_insert",
        "quarantine",
    ]
    description: str = ""
    exposure: ExposureDomain
    ports: dict[str, GraphPort] = Field(default_factory=dict)
    required_effects: list[str] = Field(default_factory=list)
    generated: bool = True


class RoleSpec(BaseModel):
    """Semantic role entry point."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    media_role: str
    default_bus: str
    fallback_target: Literal["none"] = "none"
    broadcast_voice_role: bool = False


class SourceSpec(BaseModel):
    """One producer of audio."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["hardware_capture", "role_loopback", "application_stream", "instrument"]
    exposure: ExposureDomain
    role: str
    source_port: str
    output_bus: str
    modulation: ModulationPath
    broadcast_eligible: bool = False
    authority_case: str | None = None
    rights_required: bool = False
    provenance_refs: list[str] = Field(default_factory=list)
    wet_profile: str | None = None
    hardware_insert: str | None = None
    dry_safe: bool = False
    dry_allowed: bool = False
    never_drop: bool = False
    active: bool = True
    duck_trigger: str | None = None
    ducked_by: list[str] = Field(default_factory=list)
    default_sink_allowed: bool = False

    @model_validator(mode="after")
    def _one_modulation_path(self) -> SourceSpec:
        if self.modulation == ModulationPath.SOFTWARE_WET:
            if not self.wet_profile:
                raise ValueError(
                    f"source {self.source_port!r} uses software_wet without wet_profile"
                )
            if self.hardware_insert:
                raise ValueError("software_wet sources may not also use hardware_insert")
        if self.modulation == ModulationPath.HARDWARE_CHARACTER:
            if not self.hardware_insert:
                raise ValueError(
                    f"source {self.source_port!r} uses hardware_character without hardware_insert"
                )
            if self.wet_profile:
                raise ValueError("hardware_character sources may not also use wet_profile")
        if self.modulation == ModulationPath.DRY and not self.dry_allowed:
            raise ValueError("dry modulation requires dry_allowed=true")
        return self


class WetControl(BaseModel):
    """One plugin/control-port value with an explicit range."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    plugin: str
    control: str
    default: float
    min: float
    max: float
    unit: str = ""
    smooth_ms: int = Field(default=100, ge=0)


class WetProfile(BaseModel):
    """Reusable `hapax-wet` software profile."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    template: Literal["hapax-wet"] = "hapax-wet"
    wet_mix_min: float = Field(..., ge=0.0, le=1.0)
    wet_mix_default: float = Field(..., ge=0.0, le=1.0)
    dry_gain_db_default: float = Field(default=0.0, ge=-90.0, le=12.0)
    controls: list[WetControl] = Field(default_factory=list)


class HardwareInsert(BaseModel):
    """Optional opaque hardware character path."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["opaque_analog_insert", "instrument"]
    send: str | None = None
    return_port: str | None = Field(default=None, alias="return")
    exposure: ExposureDomain
    enabled_by_default: bool = False
    isolation_credit: bool = False
    failure_policy: Literal["bypass", "mute", "quarantine"] = "bypass"
    evidence_required: list[str] = Field(default_factory=list)


class BusSpec(BaseModel):
    """Logical sum, processor, monitor, or egress bus."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    exposure: ExposureDomain
    kind: Literal["source_bus", "sum", "processor", "egress", "monitor", "quarantine"]
    accepts: list[ExposureDomain] = Field(default_factory=list)
    feeds: list[str] = Field(default_factory=list)
    required_effects: list[str] = Field(default_factory=list)


class MonitorSpec(BaseModel):
    """Reserved monitor mapping."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str
    target: str
    exposure: ExposureDomain
    exclusive: bool = True
    post_master: bool = False


class AudioEdge(BaseModel):
    """Exact desired or forbidden port-level link."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str
    target: str
    gain_db: float = 0.0
    reason: str = ""

    @field_validator("source", "target")
    @classmethod
    def _edge_ref_is_port_ref(cls, v: str) -> str:
        if ":" not in v:
            raise ValueError(f"edge endpoint {v!r} must be in node:port form")
        return v

    @property
    def key(self) -> str:
        return f"{self.source}|{self.target}"


class ClockSpec(BaseModel):
    """Graph clock."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rate: Literal[44100] = 44100
    allowed_rates: list[Literal[44100]] = Field(default_factory=lambda: [44100])


class LoudnessConstantRefs(BaseModel):
    """Symbolic references into shared.audio_loudness."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    egress_target_lufs_i: Literal["EGRESS_TARGET_LUFS_I"] = "EGRESS_TARGET_LUFS_I"
    egress_true_peak_dbtp: Literal["EGRESS_TRUE_PEAK_DBTP"] = "EGRESS_TRUE_PEAK_DBTP"
    pre_norm_target_lufs_i: Literal["PRE_NORM_TARGET_LUFS_I"] = "PRE_NORM_TARGET_LUFS_I"
    pre_norm_true_peak_dbtp: Literal["PRE_NORM_TRUE_PEAK_DBTP"] = "PRE_NORM_TRUE_PEAK_DBTP"
    master_input_makeup_db: Literal["MASTER_INPUT_MAKEUP_DB"] = "MASTER_INPUT_MAKEUP_DB"
    duck_depth_operator_voice_db: Literal["DUCK_DEPTH_OPERATOR_VOICE_DB"] = (
        "DUCK_DEPTH_OPERATOR_VOICE_DB"
    )
    duck_depth_tts_db: Literal["DUCK_DEPTH_TTS_DB"] = "DUCK_DEPTH_TTS_DB"

    def resolve(self) -> dict[str, float]:
        """Resolve constants from the live Python SSOT."""
        return {
            name: float(getattr(loudness, ref))
            for name, ref in self.model_dump(mode="python").items()
        }


class ReconcilerSpec(BaseModel):
    """Offline statement of the reconciler contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    desired_link_format: Literal["source_node:source_port|target_node:target_port"] = (
        "source_node:source_port|target_node:target_port"
    )
    forbidden_runs_last: bool = True
    reload_interval_ticks: int = Field(default=60, ge=1)


class FenceSpec(BaseModel):
    """Fail-closed port-domain fence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    default_exposure: ExposureDomain = ExposureDomain.QUARANTINE
    default_sink: Literal["hapax-pc-loudnorm"] = "hapax-pc-loudnorm"
    obs_allowed_sources: list[str] = Field(default_factory=list)
    forbidden_from_domains: list[ExposureDomain] = Field(default_factory=list)
    forbidden_to_domains: list[ExposureDomain] = Field(default_factory=list)
    protected_target_tag: str = "protected_public_target"
    layer_c_forbidden_target_patterns: list[str] = Field(default_factory=list)
    known_blocked_links: list[AudioEdge] = Field(default_factory=list)
    gain_budget_ceiling_db: float = Field(default=24.0, ge=0.0, le=24.0)
    m8_voice_wet_block_required: bool = True


class PortAudioGraph(BaseModel):
    """Phase 1+2 mk5 port-level graph."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    description: str = ""
    clock: ClockSpec
    constants: LoudnessConstantRefs = Field(default_factory=LoudnessConstantRefs)
    reconciler: ReconcilerSpec = Field(default_factory=ReconcilerSpec)
    devices: dict[str, DeviceSpec] = Field(default_factory=dict)
    nodes: dict[str, GraphNode] = Field(default_factory=dict)
    roles: dict[str, RoleSpec] = Field(default_factory=dict)
    sources: dict[str, SourceSpec] = Field(default_factory=dict)
    wet_profiles: dict[str, WetProfile] = Field(default_factory=dict)
    hardware_inserts: dict[str, HardwareInsert] = Field(default_factory=dict)
    buses: dict[str, BusSpec] = Field(default_factory=dict)
    monitors: dict[str, MonitorSpec] = Field(default_factory=dict)
    fence: FenceSpec
    internal_edges: list[AudioEdge] = Field(default_factory=list)
    desired_links: list[AudioEdge] = Field(default_factory=list)
    forbidden_links: list[AudioEdge] = Field(default_factory=list)

    @model_validator(mode="after")
    def _references_are_valid(self) -> PortAudioGraph:
        ports = self.port_refs()
        for edge in [*self.internal_edges, *self.desired_links, *self.forbidden_links]:
            if edge.source not in ports:
                raise ValueError(f"edge source {edge.source!r} is not a declared port")
            if edge.target not in ports:
                raise ValueError(f"edge target {edge.target!r} is not a declared port")
        for edge in self.fence.known_blocked_links:
            if edge.source not in ports:
                raise ValueError(f"known blocked source {edge.source!r} is not a declared port")
            if edge.target not in ports:
                raise ValueError(f"known blocked target {edge.target!r} is not a declared port")
        for source_id, source in self.sources.items():
            if source.role not in self.roles:
                raise ValueError(f"source {source_id!r} references missing role {source.role!r}")
            if source.source_port not in ports:
                raise ValueError(
                    f"source {source_id!r} source_port {source.source_port!r} is not declared"
                )
            if source.output_bus not in self.buses:
                raise ValueError(
                    f"source {source_id!r} output_bus {source.output_bus!r} is not declared"
                )
            if source.wet_profile and source.wet_profile not in self.wet_profiles:
                raise ValueError(
                    f"source {source_id!r} wet_profile {source.wet_profile!r} is not declared"
                )
            if source.hardware_insert and source.hardware_insert not in self.hardware_inserts:
                raise ValueError(
                    f"source {source_id!r} hardware_insert {source.hardware_insert!r} missing"
                )
        return self

    def port_refs(self) -> set[str]:
        """All declared port refs."""
        return set(self.ports_by_ref())

    def ports_by_ref(self) -> dict[str, DevicePort | GraphPort]:
        """Declared device + generated node ports keyed by `node:port`."""
        out: dict[str, DevicePort | GraphPort] = {}
        for device in self.devices.values():
            for port in device.ports.values():
                if port.ref in out:
                    raise ValueError(f"duplicate port ref {port.ref!r}")
                out[port.ref] = port
        for node_id, node in self.nodes.items():
            for port_name, port in node.ports.items():
                ref = f"{node_id}:{port_name}"
                if ref in out:
                    raise ValueError(f"duplicate port ref {ref!r}")
                out[ref] = port
        return out

    def node_for_ref(self, ref: str) -> str:
        return ref.split(":", 1)[0]

    def all_edges(self) -> list[AudioEdge]:
        return [*self.internal_edges, *self.desired_links]

    def resolved_loudness_constants(self) -> dict[str, float]:
        return self.constants.resolve()

    @classmethod
    def from_yaml(cls, source: str | Path) -> PortAudioGraph:
        raw = source.read_text() if isinstance(source, Path) else source
        data = yaml.safe_load(raw)
        if not isinstance(data, dict):
            raise ValueError("PortAudioGraph.from_yaml expects a top-level mapping")
        return cls.model_validate(data)

    def to_yaml(self) -> str:
        return yaml.safe_dump(
            self.model_dump(by_alias=True, mode="json"),
            default_flow_style=False,
            sort_keys=False,
        )


__all__ = [
    "AudioEdge",
    "BusSpec",
    "ClockSpec",
    "DevicePort",
    "DeviceSpec",
    "ExposureDomain",
    "FenceSpec",
    "GraphNode",
    "GraphPort",
    "HardwareInsert",
    "LoudnessConstantRefs",
    "ModulationPath",
    "MonitorSpec",
    "PortAudioGraph",
    "PortDirection",
    "ReconcilerSpec",
    "RoleSpec",
    "SourceSpec",
    "WetControl",
    "WetProfile",
]
