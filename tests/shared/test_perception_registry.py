"""Perception registry model — frozen/forbid, ref integrity, policy validators."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.audio_graph.model import ExposureDomain
from shared.percepts import GeometryClass
from shared.perception_registry import (
    DEFAULT_REGISTRY_PATH,
    ArchiveSpec,
    PerceptChannel,
    PerceptionPoint,
    PerceptionRegistry,
    PointStatus,
    SubscriptionSpec,
    load_default_registry,
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


# ---------------------------------------------------------------------------
# Real-file regression pins (tests/test_wgsl_node_affordance_coverage.py idiom)
# ---------------------------------------------------------------------------


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
