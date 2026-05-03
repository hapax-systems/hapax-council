"""``compile_descriptor()`` is deterministic + integrates invariants."""

from __future__ import annotations

from shared.audio_graph import (
    AudioGraph,
    AudioLink,
    AudioNode,
    ChannelDownmix,
    ChannelMap,
    DownmixRoute,
    DownmixStrategy,
    LoopbackTopology,
    NodeKind,
    compile_descriptor,
)
from shared.audio_graph.invariants import InvariantKind, InvariantSeverity


def _make_clean_graph() -> AudioGraph:
    return AudioGraph(
        nodes=[
            AudioNode(
                id="hapax-livestream-tap",
                kind=NodeKind.TAP,
                pipewire_name="hapax-livestream-tap",
                channels=ChannelMap(count=2, positions=["FL", "FR"]),
            ),
            AudioNode(
                id="broadcast-master",
                kind=NodeKind.LOOPBACK,
                pipewire_name="hapax-broadcast-master",
                channels=ChannelMap(count=2, positions=["FL", "FR"]),
            ),
            AudioNode(
                id="broadcast-normalized",
                kind=NodeKind.FILTER_CHAIN,
                pipewire_name="hapax-broadcast-normalized",
                channels=ChannelMap(count=2, positions=["FL", "FR"]),
            ),
            AudioNode(
                id="obs-broadcast-remap",
                kind=NodeKind.LOOPBACK,
                pipewire_name="hapax-obs-broadcast-remap",
                channels=ChannelMap(count=2, positions=["FL", "FR"]),
            ),
        ],
        links=[
            AudioLink(source="broadcast-master", target="broadcast-normalized"),
            AudioLink(source="broadcast-normalized", target="obs-broadcast-remap"),
        ],
    )


def test_compile_is_deterministic() -> None:
    g = _make_clean_graph()
    a = compile_descriptor(g)
    b = compile_descriptor(g)
    assert a.pipewire_confs == b.pipewire_confs
    assert a.wireplumber_confs == b.wireplumber_confs
    assert a.pactl_loads == b.pactl_loads
    assert [v.kind for v in a.pre_apply_violations] == [v.kind for v in b.pre_apply_violations]
    assert a.post_apply_probes == b.post_apply_probes


def test_compile_emits_pipewire_confs_per_non_alsa_node() -> None:
    g = _make_clean_graph()
    art = compile_descriptor(g)
    # 4 nodes, none of which are ALSA hw → 4 confs.
    assert len(art.pipewire_confs) == 4
    assert "hapax-livestream-tap.conf" in art.pipewire_confs


def test_compile_skips_alsa_endpoints() -> None:
    g = AudioGraph(
        nodes=[
            AudioNode(
                id="alsa-l12",
                kind=NodeKind.ALSA_SOURCE,
                pipewire_name="alsa_input.usb-ZOOM_Corporation_L-12.multichannel-input",
                hw="hw:L12,0",
            ),
            AudioNode(
                id="hapax-livestream-tap",
                kind=NodeKind.TAP,
                pipewire_name="hapax-livestream-tap",
            ),
        ]
    )
    art = compile_descriptor(g)
    # ALSA source omitted; null-tap kept.
    assert "alsa_input.usb-ZOOM_Corporation_L-12.multichannel-input.conf" not in art.pipewire_confs
    assert "hapax-livestream-tap.conf" in art.pipewire_confs


def test_compile_blocks_on_violation() -> None:
    """A graph with a private→broadcast leak must yield empty confs."""
    g = AudioGraph(
        nodes=[
            AudioNode(
                id="hapax-private",
                kind=NodeKind.TAP,
                pipewire_name="hapax-private",
                fail_closed=True,
            ),
            AudioNode(
                id="livestream-tap",
                kind=NodeKind.TAP,
                pipewire_name="livestream-tap",
            ),
        ],
        links=[AudioLink(source="hapax-private", target="livestream-tap")],
    )
    art = compile_descriptor(g)
    blocking = [v for v in art.pre_apply_violations if v.severity == InvariantSeverity.BLOCKING]
    assert len(blocking) >= 1
    assert any(v.kind == InvariantKind.PRIVATE_NEVER_BROADCASTS for v in blocking)
    assert art.pipewire_confs == {}
    assert art.wireplumber_confs == {}


def test_compile_emits_pactl_loads_for_marked_loopbacks() -> None:
    g = AudioGraph(
        nodes=[
            AudioNode(
                id="hapax-livestream-tap",
                kind=NodeKind.TAP,
                pipewire_name="hapax-livestream-tap",
            ),
            AudioNode(
                id="hapax-livestream-tap-dst",
                kind=NodeKind.LOOPBACK,
                pipewire_name="hapax-livestream-tap-dst",
            ),
        ],
        loopbacks=[
            LoopbackTopology(
                node_id="hapax-livestream-tap-dst",
                source="hapax-livestream-tap",
                sink="hapax-livestream",
                apply_via_pactl_load=True,
            )
        ],
    )
    art = compile_descriptor(g)
    assert len(art.pactl_loads) == 1
    pl = art.pactl_loads[0]
    assert pl.source == "hapax-livestream-tap"
    assert pl.sink == "hapax-livestream"


def test_compile_builds_egress_probe_when_obs_remap_present() -> None:
    g = _make_clean_graph()
    art = compile_descriptor(g)
    egress_probes = [p for p in art.post_apply_probes if p.name == "obs-egress-band"]
    assert len(egress_probes) == 1
    assert egress_probes[0].egress_rms_band_dbfs == (-40.0, -10.0)
    assert egress_probes[0].egress_max_crest == 5.0


def test_compile_builds_downmix_probe_per_channel_change() -> None:
    g = AudioGraph(
        nodes=[
            AudioNode(
                id="l12-capture",
                kind=NodeKind.LOOPBACK,
                pipewire_name="l12-capture",
                channels=ChannelMap(count=14, positions=[f"AUX{i}" for i in range(14)]),
            ),
            AudioNode(
                id="l12-evilpet-capture",
                kind=NodeKind.FILTER_CHAIN,
                pipewire_name="hapax-l12-evilpet-capture",
                channels=ChannelMap(count=2, positions=["FL", "FR"]),
            ),
        ],
        channel_downmixes=[
            ChannelDownmix(
                source_node="l12-capture",
                target_node="l12-evilpet-capture",
                strategy=DownmixStrategy.CHANNEL_PICK,
                routes=[DownmixRoute(target_position="FL", source_positions=["AUX1"])],
            )
        ],
    )
    art = compile_descriptor(g)
    downmix_probes = [p for p in art.post_apply_probes if p.name.startswith("downmix-")]
    assert len(downmix_probes) == 1
    assert downmix_probes[0].source_to_capture == "hapax-l12-evilpet-capture.monitor"


def test_compile_builds_private_silence_probes() -> None:
    g = AudioGraph(
        nodes=[
            AudioNode(
                id="hapax-private",
                kind=NodeKind.TAP,
                pipewire_name="hapax-private",
                fail_closed=True,
            ),
        ]
    )
    art = compile_descriptor(g)
    silence = [p for p in art.post_apply_probes if p.expected_outcome == "not_detected"]
    assert len(silence) == 1
    assert silence[0].source_to_capture == "hapax-obs-broadcast-remap.monitor"
