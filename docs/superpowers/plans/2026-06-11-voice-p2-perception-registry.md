# 13-Point Perception Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land `config/perception-registry.yaml` (13 capture points with geometry classes + exposure-domain typing), a shared percept envelope (`shared/percepts.py`), and refactor audio_input/CPAL source selection to subscriptions resolved over the registry.

**Architecture:** The registry is the capture-side dual of the rebuild design's Port abstraction (`shared/audio_graph/model.py`): versioned YAML validated by frozen/extra-forbid Pydantic models in `shared/perception_registry.py`. Roles become subscriptions to points (`stt.ear → respeaker.asr_beam` etc.). `agents/hapax_daimonion/audio_input.py` and `cpal/stt_source_resolver.py` derive their source candidates from the registry, fail-open to today's hardcoded constants when the registry is absent/invalid (existing degraded-posture contract preserved).

**Tech Stack:** Python 3.12, Pydantic v2 (frozen, extra="forbid", mirroring `shared/audio_graph/model.py`), PyYAML, pytest (`uv run --no-sync pytest`).

**Authority:** CASE-VOICE-FOUNDATION-20260610 §5d (operator-ratified). Task: voice-p2-perception-registry-20260610.

---

## Design decisions (locked)

### The 13 points (empirically grounded, 2026-06-11 podium `pw-cli ls Node`)

| # | point id | geometry | exposure | live PipeWire capture |
|---|----------|----------|----------|----------------------|
| 1 | `rode` | person_attached | broadcast | `hapax-mic-rode-capture` (mk5 IN AUX0) |
| 2 | `respeaker` | spatial_array | quarantine | `alsa_input.usb-Seeed_Studio_reSpeaker_XVF3800_4-Mic_Array` |
| 3 | `camera-mic-brio-operator` | av_paired | quarantine | `alsa_input.usb-046d_Logitech_BRIO_5342C819` |
| 4 | `camera-mic-brio-room` | av_paired | quarantine | `alsa_input.usb-046d_Logitech_BRIO_43B0576A` |
| 5 | `camera-mic-brio-synths` | av_paired | quarantine | `alsa_input.usb-046d_Logitech_BRIO_9726C031` |
| 6 | `camera-mic-c920-desk` | av_paired | quarantine | `alsa_input.usb-046d_HD_Pro_Webcam_C920_2657DFCF` |
| 7 | `camera-mic-c920-overhead` | av_paired | quarantine | `alsa_input.usb-046d_HD_Pro_Webcam_C920_7B88C71F` |
| 8 | `camera-mic-c920-room` | av_paired | quarantine | `alsa_input.usb-046d_HD_Pro_Webcam_C920_86B6B75F` |
| 9 | `cortado` | contact | quarantine | `contact_mic` (status: available — node absent since L-12 retirement) |
| 10 | `yeti` | ambient | quarantine | `alsa_input.usb-Blue_Microphones_Yeti` (+ continuous archive, consent-gated) |
| 11 | `m8` | instrument | broadcast | `hapax-m8-instrument-capture` (+ stem archive) |
| 12 | `polyend` | instrument | broadcast | `hapax-polyend-instrument-capture` |
| 13 | `watch-relay` | person_attached | quarantine | none (status: future — §5d "a future point, not a special case") |

Enumeration rationale: §5d hedges "6–7 camera mics"; live enumeration shows exactly 6 (3 BRIO + 3 C920, serial-matched to `config/camera-loopbacks/*.env` roles — that serial pairing IS the AV co-location). Points-not-roles doctrine ("every audio input is a first-class perception sensor") admits the live `polyend` instrument capture the spec's class list exemplified with M8; the watch-relay deferred mic is mandated as a declared future point. 6 single-exemplar classes + 6 cameras + polyend + watch = 13, matching the task title.

Non-points (deliberate): mk5 raw input, S-4 wet return, livestream tap — they sense the *system's own egress*, not the environment; they are already governed by `config/audio-graph.yaml`. The AEC'd virtual source `echo_cancel_capture` is not a point — it is a processed *channel* of the yeti point.

### Exposure typing
Reuses `shared.audio_graph.model.ExposureDomain` verbatim (the "same exposure-domain typing" clause). `broadcast` for points whose capture feeds live broadcast chains today (rode, m8, polyend); `quarantine` (fail-closed) for everything else. Ratified constraint enforced by validator: **av_paired ⇒ quarantine** ("camera-mic points compile to quarantine for broadcast reachability while remaining recruitable percept sources"). `perception_recruitable: true` on all 13.

### Subscriptions (spec-exact + one existing consumer made visible)
```
stt.ear            → respeaker.asr_beam   (fallbacks: rode, yeti.aec, yeti)
barge_in           → respeaker.{vad,doa}
broadcast_voice    → rode
guest.ear          → yeti
duck.sidechain     → rode (tap: pre_wet)
noise.room_reference → camera mic points   (existing consumer: DaimonionConfig.noise_ref_room_patterns)
```

### Runtime resolution contract (behavior-preserving)
Precedence unchanged: `HAPAX_AUDIO_INPUT_TARGET` env > explicit `source_name`/cfg > registry-derived default > legacy hardcoded fallback. `resolve_source()` candidate-walk semantics untouched. Registry absent/invalid ⇒ log warning, fall back to today's constants (fail-open degraded posture, same as empty pw-cli). Intentional default change: registry-derived stt.ear priority puts **respeaker first** (ratified: ReSpeaker = the STT front-end; live truth: it already IS the sole live STT mic via drop-in override), then rode, `echo_cancel_capture`, raw yeti.

### Pre-existing test debt in touched files (baseline 2026-06-11)
`tests/hapax_daimonion/test_echo_cancel_input.py`: 4 red on main — `test_default_priority_lists_aec_first` (contradicts code since the priority gained Rode first) and 3 `TestEchoCancelConf` tests referencing the deleted `config/pipewire/hapax-echo-cancel.conf`. This task replaces the priority test with registry-derived assertions (it tests the exact constant we refactor); the 3 conf-file tests belong to voice-p0-pipewire-conf-dedupe fallout and stay untouched — declared in the PR.

---

### Task 1: Shared percept envelope

**Files:**
- Create: `shared/percepts.py`
- Test: `tests/shared/test_percepts.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Percept envelope — one schema across audio and visual perception."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.percepts import GeometryClass, Percept


def test_percept_is_frozen_and_forbids_extras() -> None:
    cfg = Percept.model_config
    assert cfg.get("frozen") is True
    assert cfg.get("extra") == "forbid"
    with pytest.raises(ValidationError):
        Percept(
            timestamp=1.0,
            source_point="rode",
            geometry_class=GeometryClass.PERSON_ATTACHED,
            confidence=1.0,
            unknown_extra="x",
        )


def test_confidence_bounds_enforced() -> None:
    with pytest.raises(ValidationError):
        Percept(
            timestamp=1.0,
            source_point="rode",
            geometry_class=GeometryClass.PERSON_ATTACHED,
            confidence=1.5,
        )
    with pytest.raises(ValidationError):
        Percept(
            timestamp=1.0,
            source_point="rode",
            geometry_class=GeometryClass.PERSON_ATTACHED,
            confidence=-0.1,
        )


def test_audio_and_visual_percepts_share_envelope() -> None:
    """§5d: one schema so CLAP/Essentia ↔ YOLO correlation composes."""
    doa = Percept(
        timestamp=1749600000.0,
        source_point="respeaker",
        geometry_class=GeometryClass.SPATIAL_ARRAY,
        confidence=0.92,
        payload={"kind": "doa", "bearing_deg": 135.0},
    )
    person = Percept(
        timestamp=1749600000.1,
        source_point="camera-mic-brio-operator",
        geometry_class=GeometryClass.AV_PAIRED,
        confidence=0.81,
        payload={"kind": "person", "bbox": [0.1, 0.2, 0.4, 0.9]},
    )
    assert doa.source_point != person.source_point
    assert abs(person.timestamp - doa.timestamp) < 0.5  # shared time base


def test_roundtrip() -> None:
    p = Percept(
        timestamp=1.5,
        source_point="yeti",
        geometry_class=GeometryClass.AMBIENT,
        confidence=0.5,
        payload={"kind": "vad", "prob": 0.5},
    )
    assert Percept.model_validate(p.model_dump(mode="json")) == p


def test_geometry_classes_complete() -> None:
    assert {g.value for g in GeometryClass} == {
        "person_attached",
        "spatial_array",
        "av_paired",
        "contact",
        "ambient",
        "instrument",
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --no-sync pytest tests/shared/test_percepts.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'shared.percepts'`

- [ ] **Step 3: Write the implementation**

```python
"""Shared percept envelope — one schema across audio and visual perception.

CASE-VOICE-FOUNDATION-20260610 §5d (points-not-roles): every perception
sample, regardless of modality, travels as the same envelope —
``{timestamp, source_point, geometry_class, confidence, payload}`` — on a
shared time base (epoch seconds, ``time.time()``) so CLAP/Essentia ↔ YOLO
multi-point correlation composes. ``source_point`` is a point id from
``config/perception-registry.yaml`` (see :mod:`shared.perception_registry`).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GeometryClass(StrEnum):
    """Capture geometry of a perception point (§5d class vocabulary)."""

    PERSON_ATTACHED = "person_attached"
    SPATIAL_ARRAY = "spatial_array"
    AV_PAIRED = "av_paired"
    CONTACT = "contact"
    AMBIENT = "ambient"
    INSTRUMENT = "instrument"


class Percept(BaseModel):
    """One perception sample from one registry point."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timestamp: float
    """Epoch seconds (``time.time()``) — the shared cross-modal time base."""

    source_point: str
    """Point id from config/perception-registry.yaml."""

    geometry_class: GeometryClass
    confidence: float = Field(ge=0.0, le=1.0)
    payload: dict[str, Any] = Field(default_factory=dict)
    """Modality-specific body; convention: a ``kind`` key names the percept
    type (``vad``, ``doa``, ``asr_partial``, ``person``, ``scene`` …)."""


__all__ = ["GeometryClass", "Percept"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --no-sync pytest tests/shared/test_percepts.py -q`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add shared/percepts.py tests/shared/test_percepts.py
git commit -m "feat(voice): shared percept envelope — one schema across modalities (§5d)"
```

### Task 2: Registry model

**Files:**
- Create: `shared/perception_registry.py`
- Test: `tests/shared/test_perception_registry.py`

- [ ] **Step 1: Write the failing model tests** (file also gains real-YAML pins in Task 3)

```python
"""Perception registry model — frozen/forbid, ref integrity, policy validators."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.audio_graph.model import ExposureDomain
from shared.percepts import GeometryClass
from shared.perception_registry import (
    ArchiveSpec,
    PerceptChannel,
    PerceptionPoint,
    PerceptionRegistry,
    SubscriptionSpec,
)

_MODELS_UNDER_TEST = (
    ArchiveSpec,
    PerceptChannel,
    PerceptionPoint,
    SubscriptionSpec,
    PerceptionRegistry,
)


def _point(**overrides):
    base = dict(
        geometry=GeometryClass.AMBIENT,
        exposure=ExposureDomain.QUARANTINE,
        description="test point",
        pipewire_node="alsa_input.test",
        channels={"raw": PerceptChannel(kind="audio_pcm")},
    )
    base.update(overrides)
    return PerceptionPoint(**base)


def test_every_model_is_frozen_and_forbids_extras() -> None:
    for cls in _MODELS_UNDER_TEST:
        cfg = cls.model_config
        assert cfg.get("frozen") is True, f"{cls.__name__} must declare frozen=True"
        assert cfg.get("extra") == "forbid", f"{cls.__name__} must declare extra='forbid'"


def test_av_paired_must_be_quarantined() -> None:
    """Ratified: camera-mic points compile to quarantine for broadcast."""
    with pytest.raises(ValidationError, match="quarantine"):
        _point(
            geometry=GeometryClass.AV_PAIRED,
            exposure=ExposureDomain.BROADCAST,
            av_pair="brio-operator",
        )


def test_av_paired_requires_av_pair() -> None:
    with pytest.raises(ValidationError, match="av_pair"):
        _point(geometry=GeometryClass.AV_PAIRED)


def test_spatial_array_requires_doa_channel() -> None:
    """'spatial-array ReSpeaker w/ DOA' — the bearings channel is the contract."""
    with pytest.raises(ValidationError, match="doa"):
        _point(geometry=GeometryClass.SPATIAL_ARRAY)


def test_subscription_must_reference_declared_point() -> None:
    with pytest.raises(ValidationError, match="ghost"):
        PerceptionRegistry(
            schema_version=1,
            points={"yeti": _point()},
            subscriptions={"stt.ear": SubscriptionSpec(point="ghost")},
        )


def test_subscription_channel_must_exist_on_point() -> None:
    with pytest.raises(ValidationError, match="asr_beam"):
        PerceptionRegistry(
            schema_version=1,
            points={"yeti": _point()},
            subscriptions={"stt.ear": SubscriptionSpec(point="yeti", channels=["asr_beam"])},
        )


def test_voice_source_tag_collision_rejected() -> None:
    with pytest.raises(ValidationError, match="voice_source_tag"):
        PerceptionRegistry(
            schema_version=1,
            points={
                "a": _point(voice_source_tag="yeti"),
                "b": _point(voice_source_tag="yeti"),
            },
        )


def test_resolve_subscription_targets_walks_channel_then_fallbacks() -> None:
    reg = PerceptionRegistry(
        schema_version=1,
        points={
            "respeaker": _point(
                geometry=GeometryClass.SPATIAL_ARRAY,
                pipewire_node="alsa_input.usb-Seeed",
                channels={
                    "raw": PerceptChannel(kind="audio_pcm"),
                    "asr_beam": PerceptChannel(kind="asr_beam"),
                    "vad": PerceptChannel(kind="vad"),
                    "doa": PerceptChannel(kind="doa"),
                },
            ),
            "yeti": _point(
                channels={
                    "raw": PerceptChannel(kind="audio_pcm"),
                    "aec": PerceptChannel(kind="audio_pcm", pipewire_node="echo_cancel_capture"),
                },
            ),
        },
        subscriptions={
            "stt.ear": SubscriptionSpec(
                point="respeaker",
                channels=["asr_beam"],
                fallbacks=["yeti.aec", "yeti"],
            )
        },
    )
    assert reg.resolve_subscription_targets("stt.ear") == [
        "alsa_input.usb-Seeed",
        "echo_cancel_capture",
        "alsa_input.test",
    ]


def test_resolve_skips_nodeless_points() -> None:
    reg = PerceptionRegistry(
        schema_version=1,
        points={
            "watch-relay": _point(pipewire_node=None, status="future"),
            "yeti": _point(),
        },
        subscriptions={
            "guest.ear": SubscriptionSpec(point="watch-relay", fallbacks=["yeti"])
        },
    )
    assert reg.resolve_subscription_targets("guest.ear") == ["alsa_input.test"]


def test_unknown_subscription_raises_keyerror() -> None:
    reg = PerceptionRegistry(schema_version=1, points={"yeti": _point()})
    with pytest.raises(KeyError):
        reg.resolve_subscription_targets("nope")


def test_yaml_roundtrip() -> None:
    reg = PerceptionRegistry(
        schema_version=1,
        points={"yeti": _point(archive=ArchiveSpec(service="audio-recorder.service", consent_required=True))},
        subscriptions={"guest.ear": SubscriptionSpec(point="yeti")},
    )
    assert PerceptionRegistry.from_yaml(reg.to_yaml()) == reg
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --no-sync pytest tests/shared/test_perception_registry.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'shared.perception_registry'`

- [ ] **Step 3: Write the implementation**

```python
"""13-point perception registry — capture-side dual of the Port abstraction.

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
from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class PerceptionPoint(BaseModel):
    """One capture point — a physical sensor with a geometry class."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    geometry: GeometryClass
    exposure: ExposureDomain
    description: str = ""
    pipewire_node: str | None = None
    """Substring ``pw-cat --record --target`` accepts (None for future points)."""
    av_pair: str | None = None
    """camera-loopback role this mic is lens-co-located with (av_paired only)."""
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
    """Versioned 13-point capture registry."""

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
    "PerceptChannel",
    "PerceptionPoint",
    "PerceptionRegistry",
    "PointStatus",
    "SubscriptionSpec",
    "load_default_registry",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --no-sync pytest tests/shared/test_perception_registry.py -q`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add shared/perception_registry.py tests/shared/test_perception_registry.py
git commit -m "feat(voice): perception registry model — capture-side dual of the Port abstraction"
```

### Task 3: The registry YAML + regression pins

**Files:**
- Create: `config/perception-registry.yaml`
- Modify: `tests/shared/test_perception_registry.py` (append real-file pins)

- [ ] **Step 1: Append the failing regression-pin tests**

```python
# ---------------------------------------------------------------------------
# Real-file regression pins (tests/test_wgsl_node_affordance_coverage.py idiom)
# ---------------------------------------------------------------------------

from shared.perception_registry import DEFAULT_REGISTRY_PATH, load_default_registry


@pytest.fixture(scope="module")
def live_registry() -> PerceptionRegistry:
    return PerceptionRegistry.from_yaml(DEFAULT_REGISTRY_PATH)


def test_registry_file_loads_and_load_default_agrees(live_registry) -> None:
    assert load_default_registry() == live_registry


def test_thirteen_points(live_registry) -> None:
    assert len(live_registry.points) == 13


def test_all_geometry_classes_represented(live_registry) -> None:
    present = {p.geometry for p in live_registry.points.values()}
    assert present == set(GeometryClass)


def test_six_av_paired_camera_mics_all_quarantined(live_registry) -> None:
    cams = {
        pid: p
        for pid, p in live_registry.points.items()
        if p.geometry == GeometryClass.AV_PAIRED
    }
    assert len(cams) == 6
    for pid, cam in cams.items():
        assert cam.exposure == ExposureDomain.QUARANTINE, pid
        assert cam.perception_recruitable, pid
        assert cam.av_pair, pid


def test_respeaker_declares_dsp_percept_channels(live_registry) -> None:
    respeaker = live_registry.points["respeaker"]
    assert respeaker.geometry == GeometryClass.SPATIAL_ARRAY
    assert {"asr_beam", "vad", "doa"} <= set(respeaker.channels)


def test_spec_subscriptions_present_and_resolvable(live_registry) -> None:
    """§5d subscription map, verbatim."""
    subs = live_registry.subscriptions
    assert subs["stt.ear"].point == "respeaker"
    assert subs["stt.ear"].channels == ["asr_beam"]
    assert subs["barge_in"].point == "respeaker"
    assert set(subs["barge_in"].channels) == {"vad", "doa"}
    assert subs["broadcast_voice"].point == "rode"
    assert subs["guest.ear"].point == "yeti"
    assert subs["duck.sidechain"].point == "rode"
    assert subs["duck.sidechain"].tap == "pre_wet"
    for name in subs:
        assert live_registry.resolve_subscription_targets(name), name


def test_stt_ear_priority_is_respeaker_then_fallback_ladder(live_registry) -> None:
    targets = live_registry.resolve_subscription_targets("stt.ear")
    assert targets[0].startswith("alsa_input.usb-Seeed_Studio_reSpeaker_XVF3800")
    assert "echo_cancel_capture" in targets
    assert any("Blue_Microphones_Yeti" in t for t in targets)


def test_yeti_archive_is_consent_gated(live_registry) -> None:
    archive = live_registry.points["yeti"].archive
    assert archive is not None
    assert archive.consent_required is True


def test_watch_relay_is_declared_future_point(live_registry) -> None:
    watch = live_registry.points["watch-relay"]
    assert watch.status == PointStatus.FUTURE
    assert watch.pipewire_node is None


def test_voice_source_tags_match_legacy_resolver_contract(live_registry) -> None:
    """Tag vocabulary kept in sync with rode_wireless_adapter._VALID_TAGS."""
    assert live_registry.voice_source_tag_map() == {
        "rode": "hapax-mic-rode-capture",
        "yeti": "echo_cancel_capture",
        "contact-mic": "contact_mic",
    }
```

(Also add `PointStatus` to the existing import from `shared.perception_registry`.)

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --no-sync pytest tests/shared/test_perception_registry.py -q`
Expected: new pins FAIL with `FileNotFoundError` (config/perception-registry.yaml missing)

- [ ] **Step 3: Write `config/perception-registry.yaml`**

```yaml
# 13-point perception registry — capture-side dual of config/audio-graph.yaml.
# CASE-VOICE-FOUNDATION-20260610 §5d (points-not-roles, operator-directed).
# Validated by shared/perception_registry.py; regression-pinned by
# tests/shared/test_perception_registry.py. Exposure typing mirrors
# shared.audio_graph.model.ExposureDomain — `quarantine` is fail-closed for
# broadcast reachability while the point stays perception-recruitable.
# Node names verified live on hapax-podium 2026-06-11 (`pw-cli ls Node`).
schema_version: 1
description: >-
  Every audio input is a first-class perception sensor with a geometry
  class; roles are subscriptions to points. Non-points by design: mk5 raw
  input, S-4 wet return, livestream tap (they sense the system's own
  egress and are governed by config/audio-graph.yaml). echo_cancel_capture
  is the yeti point's aec channel, not a point.

points:
  rode:
    geometry: person_attached
    exposure: broadcast
    description: Operator Rode Wireless Pro via mk5 IN AUX0 — the broadcast voice mic.
    pipewire_node: hapax-mic-rode-capture
    voice_source_tag: rode
    equipment_ref: config/equipment/rode-wireless-pro-dual-wireless-microphone-system.yaml
    channels:
      raw:
        kind: audio_pcm
      pre_wet:
        kind: audio_pcm
        description: Pre-wet sidechain tap for duck handoff (rebuild design §ducking).
    tags: [operator, dry-safe]

  respeaker:
    geometry: spatial_array
    exposure: quarantine
    description: >-
      Seeed ReSpeaker XVF3800 4-mic array — the STT front-end (its only
      role). asr_beam/vad/doa become live once the three DSP bench acts
      land (Phase 2 run-sheet); until the ch1 mux act, capture resolves to
      the stereo array node.
    pipewire_node: alsa_input.usb-Seeed_Studio_reSpeaker_XVF3800_4-Mic_Array
    channels:
      raw:
        kind: audio_pcm
      asr_beam:
        kind: asr_beam
        description: ASR-processed beam (mux ch1 after DSP act 2).
      vad:
        kind: vad
        description: Hardware VAD percept.
      doa:
        kind: doa
        description: Direction-of-arrival bearings.
    tags: [stt-ear, hardware-aec]

  camera-mic-brio-operator:
    geometry: av_paired
    exposure: quarantine
    description: BRIO 5342C819 mic, lens-co-located with camera-loopback brio-operator.
    pipewire_node: alsa_input.usb-046d_Logitech_BRIO_5342C819
    av_pair: brio-operator
    channels:
      mic: {kind: audio_pcm}
    tags: [noise-ref-room]

  camera-mic-brio-room:
    geometry: av_paired
    exposure: quarantine
    description: BRIO 43B0576A mic, lens-co-located with camera-loopback brio-room.
    pipewire_node: alsa_input.usb-046d_Logitech_BRIO_43B0576A
    av_pair: brio-room
    channels:
      mic: {kind: audio_pcm}
    tags: [noise-ref-room]

  camera-mic-brio-synths:
    geometry: av_paired
    exposure: quarantine
    description: BRIO 9726C031 mic, lens-co-located with camera-loopback brio-synths.
    pipewire_node: alsa_input.usb-046d_Logitech_BRIO_9726C031
    av_pair: brio-synths
    channels:
      mic: {kind: audio_pcm}
    tags: [noise-ref-room]

  camera-mic-c920-desk:
    geometry: av_paired
    exposure: quarantine
    description: C920 2657DFCF mic, lens-co-located with camera-loopback c920-desk.
    pipewire_node: alsa_input.usb-046d_HD_Pro_Webcam_C920_2657DFCF
    av_pair: c920-desk
    channels:
      mic: {kind: audio_pcm}
    tags: [noise-ref-room]

  camera-mic-c920-overhead:
    geometry: av_paired
    exposure: quarantine
    description: C920 7B88C71F mic, lens-co-located with camera-loopback c920-overhead.
    pipewire_node: alsa_input.usb-046d_HD_Pro_Webcam_C920_7B88C71F
    av_pair: c920-overhead
    channels:
      mic: {kind: audio_pcm}
    tags: [noise-ref-room]

  camera-mic-c920-room:
    geometry: av_paired
    exposure: quarantine
    description: C920 86B6B75F mic, lens-co-located with camera-loopback c920-room.
    pipewire_node: alsa_input.usb-046d_HD_Pro_Webcam_C920_86B6B75F
    av_pair: c920-room
    channels:
      mic: {kind: audio_pcm}
    tags: [noise-ref-room]

  cortado:
    geometry: contact
    exposure: quarantine
    description: >-
      Zeppelin Design Labs Cortado MkIII contact mic (desk vibration).
      Former L-12 CH2; no live node since the L-12 retirement — tag kept
      for the voice-source contract.
    pipewire_node: contact_mic
    voice_source_tag: contact-mic
    status: available
    equipment_ref: config/equipment/zeppelin-design-labs-cortado-mkiii-versatile-rugged-steel-co.yaml
    channels:
      raw: {kind: audio_pcm}
    tags: [desk-activity]

  yeti:
    geometry: ambient
    exposure: quarantine
    description: >-
      Blue Yeti — ambient/GUEST ear. Highest-exposure consent surface in
      the registry: the continuous archive persists non-operator audio
      (axiom interpersonal_transparency w88). Egress AND retention are
      consent-gated (voice-p2-guest-channel).
    pipewire_node: alsa_input.usb-Blue_Microphones_Yeti
    voice_source_tag: yeti
    equipment_ref: config/equipment/blue-yeti.yaml
    archive:
      service: audio-recorder.service
      consent_required: true
      description: Continuous ambient archive.
    channels:
      raw:
        kind: audio_pcm
      aec:
        kind: audio_pcm
        pipewire_node: echo_cancel_capture
        description: >-
          Software-AEC'd view (module-echo-cancel; engages only when an
          echo-cancel conf is loaded — HAPAX_AEC_ACTIVE flow).
    tags: [guest-ear, consent-surface]

  m8:
    geometry: instrument
    exposure: broadcast
    description: Dirtywave M8 — instrument capture into chain.m8 loudnorm; stem archive.
    pipewire_node: hapax-m8-instrument-capture
    equipment_ref: config/equipment/m8-tracker-model-02.yaml
    archive:
      service: hapax-m8-stem-archive
      consent_required: false
      description: Operator instrument stems (no third-party exposure).
    channels:
      raw: {kind: audio_pcm}
    tags: [instrument, voice-return-fenced]

  polyend:
    geometry: instrument
    exposure: broadcast
    description: Polyend instrument capture into chain.polyend loudnorm.
    pipewire_node: hapax-polyend-instrument-capture
    channels:
      raw: {kind: audio_pcm}
    tags: [instrument]

  watch-relay:
    geometry: person_attached
    exposure: quarantine
    description: >-
      Watch-relay deferred mic — declared future point (§5d: a future
      point, not a special case); source-arbitration seam comes free.
    status: future
    channels: {}
    tags: [future]

subscriptions:
  stt.ear:
    point: respeaker
    channels: [asr_beam]
    fallbacks: [rode, yeti.aec, yeti]
    description: Streaming STT front-end; fallback ladder preserves the degraded posture.
  barge_in:
    point: respeaker
    channels: [vad, doa]
    description: One barge-in path on the AEC'd beam (voice-p2-barge-in-one-path).
  broadcast_voice:
    point: rode
    description: Operator broadcast voice (never dropped).
  guest.ear:
    point: yeti
    description: GUEST channel; consent gates egress and archive (voice-p2-guest-channel).
  duck.sidechain:
    point: rode
    tap: pre_wet
    description: Pre-wet Rode sidechain for duck handoff (voice-p2-duck-handoff).
  noise.room_reference:
    point: camera-mic-brio-operator
    fallbacks:
      - camera-mic-brio-room
      - camera-mic-brio-synths
      - camera-mic-c920-desk
      - camera-mic-c920-overhead
      - camera-mic-c920-room
    description: >-
      Existing consumer made visible: multi_mic noise reference
      (DaimonionConfig.noise_ref_room_patterns matches these mics today).
```

- [ ] **Step 4: Run to verify everything passes**

Run: `uv run --no-sync pytest tests/shared/test_perception_registry.py -q`
Expected: 22 passed

- [ ] **Step 5: Commit**

```bash
git add config/perception-registry.yaml tests/shared/test_perception_registry.py
git commit -m "feat(voice): 13-point perception-registry.yaml + regression pins"
```

### Task 4: audio_input subscription refactor

**Files:**
- Modify: `agents/hapax_daimonion/audio_input.py` (lines 18-25 region + new function)
- Modify: `agents/hapax_daimonion/config.py:73-76` (default becomes registry-derived)
- Modify: `tests/hapax_daimonion/test_echo_cancel_input.py:79-92` (stale priority test → registry-derived assertions)
- Test: `tests/hapax_daimonion/test_audio_input.py` (append)

- [ ] **Step 1: Write the failing tests** (append to `tests/hapax_daimonion/test_audio_input.py`)

```python
# ── Registry-derived stt.ear priority (voice-p2-perception-registry) ────


class TestSttSourcePriority:
    def test_derived_from_registry_respeaker_first(self) -> None:
        from agents.hapax_daimonion import audio_input as ai_mod

        priority = ai_mod.stt_source_priority()
        assert priority[0].startswith("alsa_input.usb-Seeed_Studio_reSpeaker_XVF3800")
        assert "echo_cancel_capture" in priority
        assert any("Yeti" in s for s in priority)

    def test_falls_back_to_legacy_constants_without_registry(self, monkeypatch) -> None:
        from agents.hapax_daimonion import audio_input as ai_mod

        monkeypatch.setattr(ai_mod, "load_default_registry", lambda: None)
        assert ai_mod.stt_source_priority() == ai_mod._LEGACY_SOURCE_PRIORITY

    def test_falls_back_when_subscription_missing(self, monkeypatch) -> None:
        from agents.hapax_daimonion import audio_input as ai_mod
        from shared.perception_registry import PerceptionRegistry

        empty = PerceptionRegistry(schema_version=1)
        monkeypatch.setattr(ai_mod, "load_default_registry", lambda: empty)
        assert ai_mod.stt_source_priority() == ai_mod._LEGACY_SOURCE_PRIORITY

    def test_module_default_matches_function(self) -> None:
        from agents.hapax_daimonion import audio_input as ai_mod

        assert ai_mod.DEFAULT_SOURCE_PRIORITY == ai_mod.stt_source_priority()


class TestConfigDefaultFromRegistry:
    def test_config_default_is_registry_priority(self) -> None:
        from agents.hapax_daimonion import audio_input as ai_mod
        from agents.hapax_daimonion.config import DaimonionConfig

        assert DaimonionConfig().audio_input_source == ai_mod.stt_source_priority()
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --no-sync pytest tests/hapax_daimonion/test_audio_input.py -q`
Expected: FAIL with `AttributeError: ... has no attribute 'stt_source_priority'`

- [ ] **Step 3: Implement in `audio_input.py`**

Replace lines 18-25 block with:

```python
from shared.perception_registry import load_default_registry

# Preferred source when echo-cancellation is known to be active.
# See docs/runbooks/audio-topology.md and spec 2026-04-18-audio-pathways-audit-design.md.
_AEC_SOURCE_NAME = "echo_cancel_capture"
_RODE_WIRELESS_PATTERN = "alsa_input.usb-R__DE_Wireless_PRO_RX"
_RAW_YETI_PATTERN = "alsa_input.usb-Blue_Microphones_Yeti"

# Degraded-posture constants used only when config/perception-registry.yaml
# is absent or invalid (same fail-open contract as an empty pw-cli answer).
_LEGACY_SOURCE_PRIORITY: list[str] = [_RODE_WIRELESS_PATTERN, _AEC_SOURCE_NAME, _RAW_YETI_PATTERN]

_STT_EAR_SUBSCRIPTION = "stt.ear"


def stt_source_priority() -> list[str]:
    """Capture-target priority for the STT ear, resolved over the
    perception registry (CASE-VOICE-FOUNDATION-20260610 §5d: roles are
    subscriptions to points; stt.ear → point.respeaker.asr_beam with the
    rode/yeti fallback ladder). Falls back to the legacy hardcoded
    priority when the registry or the subscription is unavailable.
    """
    registry = load_default_registry()
    if registry is None:
        return list(_LEGACY_SOURCE_PRIORITY)
    try:
        targets = registry.resolve_subscription_targets(_STT_EAR_SUBSCRIPTION)
    except KeyError:
        log.warning(
            "perception registry lacks %r subscription; using legacy priority",
            _STT_EAR_SUBSCRIPTION,
        )
        return list(_LEGACY_SOURCE_PRIORITY)
    if not targets:
        return list(_LEGACY_SOURCE_PRIORITY)
    return targets


# Resolved once at import; HAPAX_AUDIO_INPUT_TARGET still overrides at
# stream construction and explicit config wins over this default.
DEFAULT_SOURCE_PRIORITY: list[str] = stt_source_priority()
```

In `config.py`, replace the `audio_input_source` literal default (lines 73-76) with:

```python
    # Audio hardware — operator-preferred priority list, resolved over
    # config/perception-registry.yaml (stt.ear subscription; §5d roles-are-
    # subscriptions). Resolver (agents/hapax_daimonion/audio_input.py::
    # resolve_source) walks the list at daimonion start and picks the first
    # source pw-cli reports live. Legacy hardcoded ladder remains the
    # degraded-posture fallback inside stt_source_priority().
    #
    # Backward compat: a single str is auto-wrapped to a 1-element list
    # by the post-init validator below, with a deprecation warning.
    audio_input_source: list[str] = Field(default_factory=stt_source_priority)
```

with `from agents.hapax_daimonion.audio_input import stt_source_priority` added to config.py imports (audio_input imports nothing from config — no cycle) and `Field` added to the pydantic import if absent.

Replace the stale `test_default_priority_lists_aec_first` (test_echo_cancel_input.py:79-81) with:

```python
    def test_default_priority_is_registry_derived(self) -> None:
        assert DEFAULT_SOURCE_PRIORITY[0].startswith(
            "alsa_input.usb-Seeed_Studio_reSpeaker_XVF3800"
        )
        assert _AEC_SOURCE_NAME in DEFAULT_SOURCE_PRIORITY
        assert any("Yeti" in s for s in DEFAULT_SOURCE_PRIORITY)
```

and update `TestDaimonionConfigAudioSource.test_default_is_priority_list` (lines 88-92) to assert the registry-derived shape:

```python
    def test_default_is_priority_list(self) -> None:
        cfg = DaimonionConfig()
        assert isinstance(cfg.audio_input_source, list)
        assert cfg.audio_input_source[0].startswith(
            "alsa_input.usb-Seeed_Studio_reSpeaker_XVF3800"
        )
        assert any("Yeti" in s for s in cfg.audio_input_source)
```

- [ ] **Step 4: Run to verify**

Run: `uv run --no-sync pytest tests/hapax_daimonion/test_audio_input.py tests/hapax_daimonion/test_echo_cancel_input.py tests/hapax_daimonion/test_config_audio.py tests/hapax_daimonion/test_daemon_audio_wiring.py -q`
Expected: only the 3 pre-existing `TestEchoCancelConf` conf-file failures remain (declared baseline); everything else passes.

- [ ] **Step 5: Commit**

```bash
git add agents/hapax_daimonion/audio_input.py agents/hapax_daimonion/config.py tests/hapax_daimonion/test_audio_input.py tests/hapax_daimonion/test_echo_cancel_input.py
git commit -m "feat(voice): audio_input stt.ear priority resolved over the perception registry"
```

### Task 5: stt_source_resolver subscription refactor

**Files:**
- Modify: `agents/hapax_daimonion/cpal/stt_source_resolver.py:36-45`
- Test: Create `tests/hapax_daimonion/test_stt_source_resolver.py`

- [ ] **Step 1: Write the failing tests**

```python
"""stt_source_resolver — registry-backed tag→target map, legacy fallback."""

from __future__ import annotations

from pathlib import Path

from agents.hapax_daimonion.cpal import stt_source_resolver as mod
from agents.hapax_daimonion.cpal.stt_source_resolver import SttSourceResolver


class TestTagMap:
    def test_registry_backed_map_matches_contract(self) -> None:
        assert mod._tag_to_source_map() == {
            "rode": "hapax-mic-rode-capture",
            "yeti": "echo_cancel_capture",
            "contact-mic": "contact_mic",
        }

    def test_falls_back_to_legacy_map_without_registry(self, monkeypatch) -> None:
        monkeypatch.setattr(mod, "load_default_registry", lambda: None)
        assert mod._tag_to_source_map() == mod._LEGACY_TAG_TO_SOURCE


class TestResolver:
    def test_resolves_rode_tag_via_registry(self, tmp_path: Path) -> None:
        tag_file = tmp_path / "voice-source.txt"
        tag_file.write_text("rode")
        r = SttSourceResolver(path=tag_file)
        assert r.resolve() == "hapax-mic-rode-capture"

    def test_missing_tag_file_falls_back_to_yeti(self, tmp_path: Path) -> None:
        r = SttSourceResolver(path=tmp_path / "absent.txt")
        assert r.resolve() == "echo_cancel_capture"

    def test_invalid_tag_falls_back_to_yeti(self, tmp_path: Path) -> None:
        tag_file = tmp_path / "voice-source.txt"
        tag_file.write_text("not-a-tag")
        r = SttSourceResolver(path=tag_file)
        assert r.resolve() == "echo_cancel_capture"

    def test_cache_honors_ttl(self, tmp_path: Path) -> None:
        tag_file = tmp_path / "voice-source.txt"
        tag_file.write_text("rode")
        now = [0.0]
        r = SttSourceResolver(path=tag_file, cache_ttl_s=5.0, clock=lambda: now[0])
        assert r.current_tag() == "rode"
        tag_file.write_text("yeti")
        now[0] = 4.0
        assert r.current_tag() == "rode"  # cached
        now[0] = 6.0
        assert r.current_tag() == "yeti"  # expired
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --no-sync pytest tests/hapax_daimonion/test_stt_source_resolver.py -q`
Expected: FAIL with `AttributeError: ... no attribute '_tag_to_source_map'`

- [ ] **Step 3: Implement**

In `stt_source_resolver.py`, replace the `_TAG_TO_SOURCE` block (lines 36-45) with:

```python
from shared.perception_registry import load_default_registry

# Degraded-posture map used only when config/perception-registry.yaml is
# absent or invalid. The registry's voice_source_tag fields are the live
# SSOT (points rode/yeti/cortado declare the tags this file accepts).
_LEGACY_TAG_TO_SOURCE: dict[str, str] = {
    VOICE_SOURCE_RODE: "alsa_input.usb-RODE_Wireless_Pro",
    VOICE_SOURCE_YETI: "echo_cancel_capture",
    VOICE_SOURCE_CONTACT_MIC: "contact_mic",
}


def _tag_to_source_map() -> dict[str, str]:
    """tag → pw-cat target, resolved over the perception registry.

    Roles are subscriptions to points (§5d); the voice-source tag file is
    the operator-directed point selector, so each tag maps to a registry
    point's capture node. Fail-open to the legacy map.
    """
    registry = load_default_registry()
    if registry is None:
        return dict(_LEGACY_TAG_TO_SOURCE)
    tags = registry.voice_source_tag_map()
    if set(tags) != set(_LEGACY_TAG_TO_SOURCE):
        log.warning(
            "perception registry voice_source_tags %s != expected %s; using legacy map",
            sorted(tags),
            sorted(_LEGACY_TAG_TO_SOURCE),
        )
        return dict(_LEGACY_TAG_TO_SOURCE)
    return tags


_TAG_TO_SOURCE: dict[str, str] = _tag_to_source_map()
_FALLBACK_SOURCE = _TAG_TO_SOURCE[VOICE_SOURCE_YETI]
```

(`_read_tag` and the resolver class keep reading module-level `_TAG_TO_SOURCE`; no other changes.)

- [ ] **Step 4: Run to verify**

Run: `uv run --no-sync pytest tests/hapax_daimonion/test_stt_source_resolver.py -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add agents/hapax_daimonion/cpal/stt_source_resolver.py tests/hapax_daimonion/test_stt_source_resolver.py
git commit -m "feat(voice): stt_source_resolver tag map resolved over the perception registry"
```

### Task 6: Full verification + PR

- [ ] **Step 1: Full daimonion + shared + audio_graph test sweep**

Run: `uv run --no-sync pytest tests/shared/ tests/hapax_daimonion/ tests/audio_graph/ -q`
Expected: no NEW failures vs the declared baseline (3 `TestEchoCancelConf` reds pre-exist).

- [ ] **Step 2: Lint**

Run: `uv run --no-sync ruff check shared/percepts.py shared/perception_registry.py agents/hapax_daimonion/audio_input.py agents/hapax_daimonion/config.py agents/hapax_daimonion/cpal/stt_source_resolver.py tests/shared/test_percepts.py tests/shared/test_perception_registry.py tests/hapax_daimonion/test_stt_source_resolver.py && uv run --no-sync ruff format --check <same files>`
Expected: clean

- [ ] **Step 3: Push + PR**

```bash
git push -u origin epsilon/voice-p2-perception-registry-20260610
gh pr create --title "feat(voice): 13-point perception registry + percept schema + subscription refactor" --body "<scope, decisions, baseline declaration, acceptance mapping>"
```

- [ ] **Step 4: cc-close to pr_open** (frontier_review_required — ends at pr_open awaiting acceptance receipt; never lane-closable)

```bash
uv run --no-sync bash /home/hapax/projects/hapax-council--epsilon/scripts/cc-close voice-p2-perception-registry-20260610 --pr <N>
```

---

## Self-review

- **Spec coverage:** registry YAML w/ geometry classes ✅ (Task 3); one percept schema shared with visual pipeline ✅ (Task 1, cross-modal test); subscriptions over the registry for audio_input/CPAL ✅ (Tasks 4-5); exposure-domain dual + camera quarantine compilation ✅ (Task 2 validator + Task 3 pins); DOA channel ✅; archives + consent surface ✅; watch-relay future point ✅.
- **Type consistency:** `GeometryClass` lives in `shared/percepts.py`, imported by registry; `ExposureDomain` reused from `shared.audio_graph.model`; `stt_source_priority` referenced consistently in Task 4 config.py default_factory.
- **Placeholder scan:** all steps carry full code; no TBDs.
- **Out of scope (later tasks own them):** barge-in rewiring (voice-p2-barge-in-one-path), consent gating enforcement (voice-p2-guest-channel), duck VCA (voice-p2-duck-handoff), ReSpeaker DSP acts (Phase 2 bench), percept *emission* from DSP channels (rides the ReSpeaker acts).
