"""Schema tests — every model class roundtrips, frozen + extra-forbid enforced."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.audio_graph import (
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

# ---------------------------------------------------------------------------
# Per-model frozen / extra-forbid
# ---------------------------------------------------------------------------


_MODELS_UNDER_TEST = (
    FormatSpec,
    ChannelMap,
    FilterStage,
    GainStage,
    MixerRoute,
    MixdownGraph,
    DownmixRoute,
    ChannelDownmix,
    RemapSource,
    LoopbackTopology,
    Fanout,
    AudioNode,
    AudioLink,
    GlobalTunables,
    AlsaProfilePin,
    AlsaCardRule,
    BluezRule,
    StreamRestoreRule,
    StreamPin,
    PreferredTargetPin,
    DuckPolicy,
    RoleLoopback,
    MediaRoleSink,
    WireplumberRule,
    BroadcastInvariant,
    AudioGraph,
)


def test_every_model_is_frozen_and_forbids_extras() -> None:
    for cls in _MODELS_UNDER_TEST:
        cfg = cls.model_config
        assert cfg.get("frozen") is True, f"{cls.__name__} must declare frozen=True"
        assert cfg.get("extra") == "forbid", f"{cls.__name__} must declare extra='forbid'"


def test_extra_field_rejected() -> None:
    with pytest.raises(ValidationError):
        FormatSpec(rate_hz=48000, channels=2, format="S32LE", unknown_extra="x")


# ---------------------------------------------------------------------------
# Per-model roundtrip (model_dump → model_validate is identity)
# ---------------------------------------------------------------------------


def _roundtrip(instance):
    cls = type(instance)
    return cls.model_validate(instance.model_dump(mode="json"))


def test_format_spec_roundtrip() -> None:
    f = FormatSpec(rate_hz=48000, channels=14, format="S32LE")
    assert _roundtrip(f) == f


def test_channel_map_position_count_mismatch_rejected() -> None:
    with pytest.raises(ValidationError):
        ChannelMap(count=2, positions=["FL"])


def test_filter_stage_ladspa_requires_plugin() -> None:
    with pytest.raises(ValidationError):
        FilterStage(type="ladspa", label="x", name="y")
    s = FilterStage(type="ladspa", plugin="sc4m_1916", label="sc4m", name="m8_comp_l")
    assert _roundtrip(s) == s


def test_gain_stage_with_bleed() -> None:
    gs = GainStage(
        edge_source="l12-capture",
        edge_target="l12-evilpet-capture",
        edge_source_port="AUX3",
        base_gain_db=0.0,
        per_channel_overrides={"AUX3": 0.0},
        declared_bleed_db=27.0,
    )
    assert _roundtrip(gs) == gs


def test_mixdown_graph_with_ladspa_strategy() -> None:
    mg = MixdownGraph(
        stages=[
            GainStage(
                edge_source="l12-capture",
                edge_target="gain_evilpet",
                base_gain_db=0.0,
            ),
        ],
        routes=[
            MixerRoute(
                source_stage="gain_evilpet",
                source_port="Out",
                sink_stage="sum_l",
                sink_port="In 1",
                gain=1.0,
            ),
        ],
        output_stages=["sum_l", "sum_r"],
    )
    assert _roundtrip(mg) == mg


def test_channel_downmix_ladspa_requires_mixdown() -> None:
    with pytest.raises(ValidationError):
        ChannelDownmix(
            source_node="l12-capture",
            target_node="l12-evilpet-capture",
            strategy=DownmixStrategy.LADSPA_MIXDOWN,
        )


def test_channel_downmix_channel_pick_requires_routes() -> None:
    with pytest.raises(ValidationError):
        ChannelDownmix(
            source_node="src",
            target_node="dst",
            strategy=DownmixStrategy.CHANNEL_PICK,
        )


def test_loopback_topology_with_g8_flags() -> None:
    lb = LoopbackTopology(
        node_id="hapax-private-playback",
        source="hapax-private",
        sink="alsa_output.usb-Torso_Electronics_S-4-...multichannel-output",
        source_dont_move=True,
        sink_dont_move=True,
        dont_reconnect=True,
        dont_move=True,
        linger=True,
        state_restore=False,
    )
    assert _roundtrip(lb) == lb
    assert lb.dont_reconnect is True
    assert lb.linger is True
    assert lb.state_restore is False


def test_remap_source_overlay() -> None:
    rs = RemapSource()
    lb = LoopbackTopology(
        node_id="hapax-obs-broadcast-remap",
        source="hapax-obs-broadcast-remap-capture",
        sink="hapax-broadcast-normalized",
        remap_source=rs,
    )
    assert lb.remap_source == rs
    assert _roundtrip(lb).remap_source == rs


def test_audio_node_kebab_id_required() -> None:
    with pytest.raises(ValidationError):
        AudioNode(id="UpperCase", kind=NodeKind.TAP, pipewire_name="x")


def test_audio_node_alsa_requires_hw() -> None:
    with pytest.raises(ValidationError):
        AudioNode(id="alsa-source", kind=NodeKind.ALSA_SOURCE, pipewire_name="x")


def test_audio_node_custom_template_requires_stages() -> None:
    with pytest.raises(ValidationError):
        AudioNode(
            id="bad-fc",
            kind=NodeKind.FILTER_CHAIN,
            pipewire_name="x",
            filter_chain_template=FilterChainTemplate.CUSTOM,
        )


def test_audio_node_fail_closed_typed() -> None:
    n = AudioNode(
        id="hapax-private",
        kind=NodeKind.TAP,
        pipewire_name="hapax-private",
        fail_closed=True,
        private_monitor_endpoint=True,
    )
    assert n.fail_closed is True
    assert n.private_monitor_endpoint is True


def test_audio_node_industrial_name_validates() -> None:
    n = AudioNode(
        id="music-duck",
        kind=NodeKind.FILTER_CHAIN,
        pipewire_name="hapax-music-duck",
        industrial_name="chain.music.ducker",
    )
    assert n.industrial_name == "chain.music.ducker"

    with pytest.raises(ValidationError):
        AudioNode(
            id="bad-industrial",
            kind=NodeKind.TAP,
            pipewire_name="hapax-bad-industrial",
            industrial_name="hapax-music-duck",
        )

    with pytest.raises(ValidationError):
        AudioNode(
            id="not-hierarchical",
            kind=NodeKind.TAP,
            pipewire_name="hapax-not-hierarchical",
            industrial_name="music-duck",
        )


def test_audio_link_gain_range_enforced() -> None:
    with pytest.raises(ValidationError):
        AudioLink(source="a", target="b", makeup_gain_db=999.0)


def test_audio_graph_node_id_unique() -> None:
    n1 = AudioNode(id="x", kind=NodeKind.TAP, pipewire_name="pw1")
    n2 = AudioNode(id="x", kind=NodeKind.TAP, pipewire_name="pw2")
    with pytest.raises(ValidationError):
        AudioGraph(nodes=[n1, n2])


def test_audio_graph_pipewire_name_unique() -> None:
    n1 = AudioNode(id="a", kind=NodeKind.TAP, pipewire_name="dup")
    n2 = AudioNode(id="b", kind=NodeKind.TAP, pipewire_name="dup")
    with pytest.raises(ValidationError):
        AudioGraph(nodes=[n1, n2])


def test_audio_graph_industrial_name_unique() -> None:
    n1 = AudioNode(
        id="a",
        kind=NodeKind.TAP,
        pipewire_name="pw1",
        industrial_name="chain.valid.duplicate",
    )
    n2 = AudioNode(
        id="b",
        kind=NodeKind.TAP,
        pipewire_name="pw2",
        industrial_name="chain.valid.duplicate",
    )
    with pytest.raises(ValidationError):
        AudioGraph(nodes=[n1, n2])


def test_audio_graph_link_source_must_exist() -> None:
    n = AudioNode(id="a", kind=NodeKind.TAP, pipewire_name="a")
    with pytest.raises(ValidationError):
        AudioGraph(nodes=[n], links=[AudioLink(source="ghost", target="a")])


def test_audio_graph_loopback_node_must_exist() -> None:
    n = AudioNode(id="a", kind=NodeKind.TAP, pipewire_name="a")
    lb = LoopbackTopology(node_id="ghost", source="x", sink="y")
    with pytest.raises(ValidationError):
        AudioGraph(nodes=[n], loopbacks=[lb])


def test_audio_graph_yaml_roundtrip() -> None:
    n = AudioNode(
        id="hapax-livestream-tap",
        kind=NodeKind.TAP,
        pipewire_name="hapax-livestream-tap",
        channels=ChannelMap(count=2, positions=["FL", "FR"]),
    )
    g = AudioGraph(nodes=[n])
    yaml_text = g.to_yaml()
    g2 = AudioGraph.from_yaml(yaml_text)
    assert g2 == g


def test_audio_graph_unknown_schema_version_rejected() -> None:
    with pytest.raises(ValueError, match="schema_version"):
        AudioGraph.from_yaml("schema_version: 99\nnodes: []\n")


def test_role_loopback_models_voice_duck_conf() -> None:
    """50-hapax-voice-duck.conf decomposition shape (gap G-13)."""
    duck = DuckPolicy(duck_level=0.3, default_media_role="Multimedia")
    roles = [
        RoleLoopback(
            role="Multimedia",
            loopback_node_name="loopback.sink.role.multimedia",
            description="Multimedia",
            priority=10,
            intended_roles=["Music", "Movie", "Game", "Multimedia"],
            preferred_target="hapax-pc-loudnorm",
            node_volume=0.5,
        ),
        RoleLoopback(
            role="Notification",
            loopback_node_name="loopback.sink.role.notification",
            description="System Notifications",
            priority=20,
            intended_roles=["Notification"],
            preferred_target="hapax-notification-private",
        ),
        RoleLoopback(
            role="Assistant",
            loopback_node_name="loopback.sink.role.assistant",
            description="Hapax Daimonion Assistant",
            priority=40,
            intended_roles=["Assistant"],
            preferred_target="hapax-private",
            node_volume=0.25,
        ),
        RoleLoopback(
            role="Broadcast",
            loopback_node_name="loopback.sink.role.broadcast",
            description="Hapax Daimonion Broadcast",
            priority=40,
            intended_roles=["Broadcast"],
            preferred_target="hapax-voice-fx-capture",
            node_volume=0.25,
            lower_priority_action="duck",
        ),
    ]
    pins = [
        PreferredTargetPin(role=lb.role, preferred_target=lb.preferred_target or "") for lb in roles
    ]
    sink = MediaRoleSink(duck_policy=duck, loopbacks=roles, preferred_target_pins=pins)
    assert _roundtrip(sink) == sink
    assert sink.duck_policy.duck_level == 0.3


def test_global_tunables_models_quantum_conf() -> None:
    """10-voice-quantum.conf decomposition (gap G-1)."""
    g = GlobalTunables(
        default_clock_quantum=128,
        min_quantum=64,
        max_quantum=1024,
        allowed_rates=[16000, 44100, 48000],
    )
    assert _roundtrip(g) == g


def test_alsa_profile_pin_models_s4_usb_sink_conf() -> None:
    """hapax-s4-usb-sink.conf decomposition (gap G-2)."""
    pin = AlsaProfilePin(
        card_match="~alsa_card.usb-Torso_Electronics_S-4*",
        profile="pro-audio",
        api_alsa_use_acp=False,
        priority_session=1500,
        priority_driver=1500,
    )
    assert _roundtrip(pin) == pin


def test_l12_mixdown_expressed_via_ladspa_strategy() -> None:
    """Gap G-3 acceptance: L-12 14→2 software mixdown is expressible.

    The actual L-12 conf has 4 mono input gain stages summing into 2
    stereo busses. Channel-pick can't express this; ladspa-mixdown can.
    """
    mg = MixdownGraph(
        stages=[
            GainStage(edge_source="l12-capture", edge_target="gain_evilpet", base_gain_db=0.0),
            GainStage(edge_source="l12-capture", edge_target="gain_contact", base_gain_db=0.0),
            GainStage(edge_source="l12-capture", edge_target="gain_rode", base_gain_db=0.0),
            GainStage(
                edge_source="l12-capture",
                edge_target="gain_samp",
                base_gain_db=-90.0,
                declared_bleed_db=27.0,
            ),
        ],
        routes=[
            MixerRoute(
                source_stage=src,
                source_port="Out",
                sink_stage="sum_l",
                sink_port=f"In {i}",
                gain=1.0,
            )
            for i, src in enumerate(
                ["gain_evilpet", "gain_contact", "gain_rode", "gain_samp"], start=1
            )
        ]
        + [
            MixerRoute(
                source_stage=src,
                source_port="Out",
                sink_stage="sum_r",
                sink_port=f"In {i}",
                gain=1.0,
            )
            for i, src in enumerate(
                ["gain_evilpet", "gain_contact", "gain_rode", "gain_samp"], start=1
            )
        ],
        output_stages=["sum_l", "sum_r"],
    )
    cdm = ChannelDownmix(
        source_node="l12-capture",
        target_node="l12-evilpet-capture",
        strategy=DownmixStrategy.LADSPA_MIXDOWN,
        mixdown=mg,
        source_format=FormatSpec(rate_hz=48000, channels=14, format="S32LE"),
        target_format=FormatSpec(rate_hz=48000, channels=2, format="S32LE"),
    )
    assert _roundtrip(cdm) == cdm
    assert cdm.mixdown is not None
    assert len(cdm.mixdown.stages) == 4
