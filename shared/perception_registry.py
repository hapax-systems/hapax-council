"""16-point perception registry (13 audio/av + 3 Pi-fleet IR edge cams) — capture-side dual of the Port abstraction.

CASE-VOICE-FOUNDATION-20260610 §5d (points-not-roles, operator-directed):
every audio input is a first-class perception sensor with a geometry class;
roles are *subscriptions* to points. This module validates
``config/perception-registry.yaml`` with the same exposure-domain typing as
the mk5 port-level graph (:mod:`shared.audio_graph.model`) — camera-mic
points compile to ``quarantine`` for broadcast reachability while remaining
recruitable percept sources.

Consumers resolve pw-cat capture targets through
:meth:`PerceptionRegistry.resolve_subscription_targets`; loading is
fail-open (callers fall back to their legacy constants when the registry is
absent or invalid — same degraded posture as an empty ``pw-cli`` answer).
"""

from __future__ import annotations

import logging
from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from shared.audio_graph.model import ExposureDomain
from shared.percepts import GeometryClass

log = logging.getLogger(__name__)

DEFAULT_REGISTRY_PATH: Path = (
    Path(__file__).resolve().parent.parent / "config" / "perception-registry.yaml"
)


class PointStatus(StrEnum):
    """Lifecycle of a perception point."""

    ACTIVE = "active"
    AVAILABLE = "available"
    FUTURE = "future"
    RETIRED = "retired"


class PerceptChannel(BaseModel):
    """One percept stream a point can emit (asr_beam, vad, doa, mic …)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str
    description: str = ""
    pipewire_node: str | None = None
    """Override capture node for this channel (e.g. yeti.aec →
    ``echo_cancel_capture``). Falls back to the point's node when unset."""


class ArchiveSpec(BaseModel):
    """Persistent capture attached to a point (consent surface, axiom w88)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    service: str
    consent_required: bool = True
    description: str = ""


class HwSource(BaseModel):
    """The point's hardware capture binding — the SINGLE typed source for the
    generated pipewire loopback conf's ``node.target`` + ``audio.position``.

    Exists to eliminate the hand-typed channel that drifted: cortado's conf
    targeted the retired Zoom L-12 so ``contact_mic`` fell through to mk5
    capture_AUX0 (the Rode) = an eavesdrop class. With this typed, the
    generator emits the conf from here and there is nothing left to hand-type
    (REQ-20260616-perception-audio-ssot-program, Phase 1)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_target: str
    """ALSA capture device the loopback binds to (e.g. the mk5 pro-input)."""
    position: str
    """``audio.position`` channel on that device (e.g. ``AUX1`` = mk5 line-in 2).
    AUX positions are normalized to UPPERCASE (see the validator)."""

    @field_validator("position")
    @classmethod
    def _normalize_aux_position(cls, v: str) -> str:
        """Force AUX channel positions UPPERCASE so the lowercase-aux eavesdrop is
        impossible to express. pipewire matches ``audio.position`` against the
        device's channel position ("AUX1"); lowercase "aux1" does NOT match and
        silently falls back to the first port (capture_AUX0 = the Rode). Making
        this impossible-by-construction is the formal closure (REQ-20260616)."""
        if v.lower().startswith("aux") and v[3:].isdigit():
            return "AUX" + v[3:]
        return v


class EdgeSource(BaseModel):
    """A network edge sensor's capture binding — for points that run inference
    on-device and POST percepts to the council rather than streaming audio
    locally (the Pi-fleet IR cams: YOLOv8n ONNX on-device, results POSTed to
    ``/api/pi/{role}/ir`` and mirrored to ``~/hapax-state/pi-noir/{role}.json``).

    Unlike ``hw_source``/``pipewire_node`` there is NO local audio capture, so
    ``ir_edge`` points bind here and set ``pipewire_node=None``
    (REQ-20260616-perception-audio-ssot-program)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: str
    """Pi role/zone the edge cam serves (e.g. ``desk``, ``room``, ``overhead``)."""
    http_endpoint: str
    """Council ingest endpoint the Pi POSTs its percepts to (e.g. ``/api/pi/desk/ir``)."""
    state_path: str
    """Mirrored percept-JSON path the council reads (e.g. ``~/hapax-state/pi-noir/desk.json``)."""


class PerceptionPoint(BaseModel):
    """One capture point — a physical sensor with a geometry class."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    geometry: GeometryClass
    exposure: ExposureDomain
    description: str = ""
    pipewire_node: str | None = None
    """Substring ``pw-cat --record --target`` accepts (None for future points)."""
    hw_source: HwSource | None = None
    """Typed hardware capture binding the generator emits the loopback conf
    from (device + audio.position). When set, the conf is generated, not
    hand-typed — drift-impossible-by-construction."""
    av_pair: str | None = None
    """camera-loopback role this mic is lens-co-located with (av_paired only)."""
    edge_source: EdgeSource | None = None
    """Network edge-capture binding (``ir_edge`` points only; mutually exclusive
    with pipewire_node/hw_source — the sensor POSTs percepts, no local audio)."""
    channels: dict[str, PerceptChannel] = Field(default_factory=dict)
    perception_recruitable: bool = True
    voice_source_tag: str | None = None
    """Tag accepted in /dev/shm/hapax-compositor/voice-source.txt (see
    cpal/stt_source_resolver.py and rode_wireless_adapter)."""
    archive: ArchiveSpec | None = None
    status: PointStatus = PointStatus.ACTIVE
    equipment_ref: str | None = None
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _geometry_policy(self) -> PerceptionPoint:
        if self.geometry == GeometryClass.AV_PAIRED:
            if self.exposure != ExposureDomain.QUARANTINE:
                raise ValueError(
                    "av_paired points compile to exposure=quarantine "
                    f"(ratified §5d); got {self.exposure!r}"
                )
            if not self.av_pair:
                raise ValueError("av_paired points must declare av_pair")
        if self.geometry == GeometryClass.SPATIAL_ARRAY and "doa" not in self.channels:
            raise ValueError("spatial_array points must declare a 'doa' channel")
        if self.geometry == GeometryClass.IR_EDGE:
            if self.exposure != ExposureDomain.QUARANTINE:
                raise ValueError(
                    "ir_edge points compile to exposure=quarantine "
                    f"(face-landmark + rPPG biometrics, never broadcast); got {self.exposure!r}"
                )
            if self.edge_source is None:
                raise ValueError("ir_edge points must declare edge_source")
            if self.pipewire_node is not None or self.hw_source is not None:
                raise ValueError(
                    "ir_edge points have no local audio capture; "
                    "bind edge_source, not pipewire_node/hw_source"
                )
        return self


class SubscriptionSpec(BaseModel):
    """A role's subscription to a point (roles-are-subscriptions, §5d)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    point: str
    channels: list[str] = Field(default_factory=list)
    tap: str | None = None
    """Signal tap qualifier (e.g. ``pre_wet`` for the duck sidechain)."""
    fallbacks: list[str] = Field(default_factory=list)
    """Ordered degraded-posture refs: ``point`` or ``point.channel``."""
    description: str = ""


class PerceptionRegistry(BaseModel):
    """Versioned 16-point capture registry (13 audio/av + 3 IR edge)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    description: str = ""
    points: dict[str, PerceptionPoint] = Field(default_factory=dict)
    subscriptions: dict[str, SubscriptionSpec] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _references_are_valid(self) -> PerceptionRegistry:
        tags: dict[str, str] = {}
        for point_id, point in self.points.items():
            if point.voice_source_tag is not None:
                if point.voice_source_tag in tags:
                    raise ValueError(
                        f"voice_source_tag {point.voice_source_tag!r} declared by both "
                        f"{tags[point.voice_source_tag]!r} and {point_id!r}"
                    )
                tags[point.voice_source_tag] = point_id
        for sub_id, sub in self.subscriptions.items():
            self._check_ref(sub_id, sub.point, sub.channels)
            for ref in sub.fallbacks:
                point_ref, _, channel_ref = ref.partition(".")
                self._check_ref(sub_id, point_ref, [channel_ref] if channel_ref else [])
        return self

    def _check_ref(self, sub_id: str, point_id: str, channels: list[str]) -> None:
        if point_id not in self.points:
            raise ValueError(f"subscription {sub_id!r} references missing point {point_id!r}")
        declared = self.points[point_id].channels
        for channel in channels:
            if channel not in declared:
                raise ValueError(
                    f"subscription {sub_id!r} references channel {channel!r} "
                    f"not declared on point {point_id!r}"
                )

    # -- resolution ---------------------------------------------------------

    def resolve_subscription_targets(self, name: str) -> list[str]:
        """Prioritized pw-cat capture targets for a subscription.

        Walks the subscribed point/channel then each fallback ref, emitting
        each resolvable node once. Points without a node (future points)
        are skipped — degraded posture is the *caller's* fallback constants.
        """
        sub = self.subscriptions[name]
        refs: list[tuple[str, str | None]] = [
            (sub.point, sub.channels[0] if sub.channels else None)
        ]
        for ref in sub.fallbacks:
            point_ref, _, channel_ref = ref.partition(".")
            refs.append((point_ref, channel_ref or None))
        targets: list[str] = []
        for point_id, channel_id in refs:
            point = self.points[point_id]
            node = point.pipewire_node
            if channel_id is not None:
                channel = point.channels[channel_id]
                node = channel.pipewire_node or node
            if node and node not in targets:
                targets.append(node)
        return targets

    def voice_source_tag_map(self) -> dict[str, str]:
        """tag → pw-cat target for every point declaring a voice_source_tag.

        A point whose ``aec`` channel declares its own node resolves to that
        node (yeti → echo_cancel_capture parity with the legacy resolver map).
        """
        out: dict[str, str] = {}
        for point in self.points.values():
            if point.voice_source_tag is None:
                continue
            node = point.pipewire_node
            aec = point.channels.get("aec")
            if aec is not None and aec.pipewire_node:
                node = aec.pipewire_node
            if node:
                out[point.voice_source_tag] = node
        return out

    # -- serialization ------------------------------------------------------

    @classmethod
    def from_yaml(cls, source: str | Path) -> PerceptionRegistry:
        raw = source.read_text() if isinstance(source, Path) else source
        data = yaml.safe_load(raw)
        if not isinstance(data, dict):
            raise ValueError("PerceptionRegistry.from_yaml expects a top-level mapping")
        return cls.model_validate(data)

    def to_yaml(self) -> str:
        return yaml.safe_dump(
            self.model_dump(by_alias=True, mode="json", exclude_defaults=True),
            default_flow_style=False,
            sort_keys=False,
        )


def load_default_registry(path: Path = DEFAULT_REGISTRY_PATH) -> PerceptionRegistry | None:
    """Load the repo registry; None (with a warning) on absence/invalidity.

    Fail-open by design: capture-side selection degrades to the caller's
    legacy constants, mirroring resolve_source()'s empty-pw-cli posture.
    Never raises.
    """
    try:
        return PerceptionRegistry.from_yaml(path)
    except FileNotFoundError:
        log.warning("perception registry missing at %s; using legacy constants", path)
        return None
    except Exception:
        log.warning(
            "perception registry at %s failed validation; using legacy constants",
            path,
            exc_info=True,
        )
        return None


__all__ = [
    "ArchiveSpec",
    "DEFAULT_REGISTRY_PATH",
    "EdgeSource",
    "PerceptChannel",
    "PerceptionPoint",
    "PerceptionRegistry",
    "PointStatus",
    "SubscriptionSpec",
    "load_default_registry",
]
