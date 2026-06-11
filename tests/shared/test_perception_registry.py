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
        subscriptions={"guest.ear": SubscriptionSpec(point="watch-relay", fallbacks=["yeti"])},
    )
    assert reg.resolve_subscription_targets("guest.ear") == ["alsa_input.test"]


def test_unknown_subscription_raises_keyerror() -> None:
    reg = PerceptionRegistry(schema_version=1, points={"yeti": _point()})
    with pytest.raises(KeyError):
        reg.resolve_subscription_targets("nope")


def test_yaml_roundtrip() -> None:
    reg = PerceptionRegistry(
        schema_version=1,
        points={
            "yeti": _point(
                archive=ArchiveSpec(service="audio-recorder.service", consent_required=True)
            )
        },
        subscriptions={"guest.ear": SubscriptionSpec(point="yeti")},
    )
    assert PerceptionRegistry.from_yaml(reg.to_yaml()) == reg
