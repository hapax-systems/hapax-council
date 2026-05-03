"""11 invariants — each with at least one + and one - test case.

Per spec §2.4. Tests are organised by invariant kind (1..11).
"""

from __future__ import annotations

from shared.audio_graph.invariants import (
    EgressHealth,
    InvariantKind,
    InvariantSeverity,
    check_all_invariants,
    check_channel_count_topology_wide,
    check_egress_safety_band_crest,
    check_egress_safety_band_rms,
    check_format_compatibility,
    check_gain_budget,
    check_hardware_bleed_guard,
    check_l12_directionality,
    check_master_bus_sole_path,
    check_no_duplicate_pipewire_names,
    check_port_compatibility,
    check_private_never_broadcasts,
)
from shared.audio_graph.schema import (
    AudioGraph,
    AudioLink,
    AudioNode,
    ChannelMap,
    DownmixStrategy,
    GainStage,
    LoopbackTopology,
    NodeKind,
)


def _make_node(
    id_: str,
    *,
    kind: NodeKind = NodeKind.NULL_SINK,
    pipewire_name: str | None = None,
    channels: ChannelMap | None = None,
    params: dict[str, str | int | float | bool] | None = None,
    target_object: str | None = None,
) -> AudioNode:
    return AudioNode(
        id=id_,
        kind=kind,
        pipewire_name=pipewire_name or id_,
        channels=channels or ChannelMap(count=2, positions=("FL", "FR")),
        params=params or {},
        target_object=target_object,
    )


# ---------------------------------------------------------------------------
# 1. PRIVATE_NEVER_BROADCASTS
# ---------------------------------------------------------------------------


class TestPrivateNeverBroadcasts:
    def test_pass_when_private_isolated(self) -> None:
        priv = _make_node("private-sink", params={"private_monitor_endpoint": True})
        broadcast = _make_node("hapax-livestream-tap")
        g = AudioGraph(nodes=(priv, broadcast))
        assert check_private_never_broadcasts(g) == []

    def test_fail_when_private_reaches_broadcast(self) -> None:
        priv = _make_node("private-sink", params={"private_monitor_endpoint": True})
        bcast = _make_node("hapax-livestream-tap")
        link = AudioLink(source="private-sink", target="hapax-livestream-tap")
        g = AudioGraph(nodes=(priv, bcast), links=(link,))
        violations = check_private_never_broadcasts(g)
        assert len(violations) == 1
        assert violations[0].kind == InvariantKind.PRIVATE_NEVER_BROADCASTS
        assert violations[0].severity == InvariantSeverity.BLOCKING

    def test_fail_via_loopback_path(self) -> None:
        # Loopbacks count as edges
        priv = _make_node("role-assistant", params={"private_monitor_endpoint": True})
        bcast = _make_node("hapax-livestream-tap")
        # Note: LoopbackTopology pulls source/sink across as graph edges
        lb = LoopbackTopology(
            node_id="role-assistant", source="role-assistant", sink="hapax-livestream-tap"
        )
        g = AudioGraph(nodes=(priv, bcast), loopbacks=(lb,))
        violations = check_private_never_broadcasts(g)
        assert len(violations) == 1


# ---------------------------------------------------------------------------
# 2. L12_DIRECTIONALITY
# ---------------------------------------------------------------------------


class TestL12Directionality:
    def test_pass_aux_inbound_aux_outbound(self) -> None:
        cap = AudioNode(
            id="l12-capture",
            kind=NodeKind.ALSA_SOURCE,
            pipewire_name="alsa_input.l12",
            hw="hw:CARD=L12",
            channels=ChannelMap(count=14, positions=tuple(f"AUX{i}" for i in range(14))),
        )
        chain = AudioNode(
            id="evilpet-capture",
            kind=NodeKind.FILTER_CHAIN,
            pipewire_name="evilpet-capture",
            channels=ChannelMap(count=14, positions=tuple(f"AUX{i}" for i in range(14))),
        )
        link = AudioLink(
            source="l12-capture",
            source_port="AUX1",
            target="evilpet-capture",
            target_port="AUX1",
        )
        g = AudioGraph(nodes=(cap, chain), links=(link,))
        # We only run l12_directionality
        assert check_l12_directionality(g) == []

    def test_fail_speaker_port_into_aux_only_input(self) -> None:
        cap = AudioNode(
            id="l12-capture",
            kind=NodeKind.ALSA_SOURCE,
            pipewire_name="alsa_input.l12",
            hw="hw:CARD=L12",
            channels=ChannelMap(count=14, positions=tuple(f"AUX{i}" for i in range(14))),
        )
        # An edge from L-12 capture using FL is illegal
        bad = _make_node("downstream")
        link = AudioLink(
            source="l12-capture",
            source_port="FL",
            target="downstream",
        )
        g = AudioGraph(nodes=(cap, bad), links=(link,))
        violations = check_l12_directionality(g)
        assert len(violations) >= 1
        assert violations[0].kind == InvariantKind.L12_DIRECTIONALITY

    def test_fail_aux_port_into_l12_return(self) -> None:
        # L-12 USB return only accepts FL/FR/RL/RR — AUX inbound is illegal
        ret = AudioNode(
            id="l12-usb-return",
            kind=NodeKind.ALSA_SINK,
            pipewire_name="alsa_output.l12",
            hw="surround40:CARD=L12",
            channels=ChannelMap(count=4, positions=("FL", "FR", "RL", "RR")),
        )
        upstream = _make_node("upstream")
        link = AudioLink(
            source="upstream",
            source_port="AUX1",
            target="l12-usb-return",
        )
        g = AudioGraph(nodes=(upstream, ret), links=(link,))
        violations = check_l12_directionality(g)
        assert any(v.kind == InvariantKind.L12_DIRECTIONALITY for v in violations)


# ---------------------------------------------------------------------------
# 3. PORT_COMPATIBILITY
# ---------------------------------------------------------------------------


class TestPortCompatibility:
    def test_pass_speaker_to_speaker(self) -> None:
        a = _make_node("a")
        b = _make_node("b")
        link = AudioLink(source="a", source_port="FL", target="b", target_port="FL")
        g = AudioGraph(nodes=(a, b), links=(link,))
        assert check_port_compatibility(g) == []

    def test_pass_aux_to_aux(self) -> None:
        a = _make_node("a")
        b = _make_node("b")
        link = AudioLink(source="a", source_port="AUX1", target="b", target_port="AUX5")
        g = AudioGraph(nodes=(a, b), links=(link,))
        assert check_port_compatibility(g) == []

    def test_fail_speaker_to_aux(self) -> None:
        a = _make_node("a")
        b = _make_node("b")
        link = AudioLink(source="a", source_port="FL", target="b", target_port="AUX1")
        g = AudioGraph(nodes=(a, b), links=(link,))
        violations = check_port_compatibility(g)
        assert len(violations) == 1
        assert violations[0].kind == InvariantKind.PORT_COMPATIBILITY


# ---------------------------------------------------------------------------
# 4. FORMAT_COMPATIBILITY
# ---------------------------------------------------------------------------


class TestFormatCompatibility:
    def test_pass_when_counts_match(self) -> None:
        a = _make_node("a")
        b = _make_node("b")
        link = AudioLink(source="a", target="b")
        g = AudioGraph(nodes=(a, b), links=(link,))
        assert check_format_compatibility(g) == []

    def test_pass_when_count_change_has_downmix(self) -> None:
        a = _make_node(
            "a", channels=ChannelMap(count=14, positions=tuple(f"AUX{i}" for i in range(14)))
        )
        b = _make_node("b")
        link = AudioLink(source="a", target="b")
        gs = GainStage(
            edge_source="a", edge_target="b", downmix_strategy=DownmixStrategy.CHANNEL_PICK
        )
        g = AudioGraph(nodes=(a, b), links=(link,), gain_stages=(gs,))
        assert check_format_compatibility(g) == []

    def test_fail_count_change_without_downmix(self) -> None:
        a = _make_node(
            "a",
            channels=ChannelMap(count=14, positions=tuple(f"AUX{i}" for i in range(14))),
        )
        b = _make_node("b")
        link = AudioLink(source="a", target="b")
        g = AudioGraph(nodes=(a, b), links=(link,))
        violations = check_format_compatibility(g)
        assert len(violations) == 1
        assert violations[0].kind == InvariantKind.FORMAT_COMPATIBILITY


# ---------------------------------------------------------------------------
# 5. CHANNEL_COUNT_TOPOLOGY_WIDE
# ---------------------------------------------------------------------------


class TestChannelCountTopologyWide:
    def test_pass_when_chain_has_downmix(self) -> None:
        a = _make_node(
            "a",
            channels=ChannelMap(count=14, positions=tuple(f"AUX{i}" for i in range(14))),
        )
        mid = _make_node(
            "mid",
            channels=ChannelMap(count=14, positions=tuple(f"AUX{i}" for i in range(14))),
        )
        terminus = _make_node("terminus")
        l1 = AudioLink(source="a", target="mid")
        l2 = AudioLink(source="mid", target="terminus")
        gs = GainStage(
            edge_source="mid",
            edge_target="terminus",
            downmix_strategy=DownmixStrategy.CHANNEL_PICK,
        )
        g = AudioGraph(nodes=(a, mid, terminus), links=(l1, l2), gain_stages=(gs,))
        assert check_channel_count_topology_wide(g) == []

    def test_fail_multi_hop_count_change_no_downmix(self) -> None:
        a = _make_node(
            "a",
            channels=ChannelMap(count=14, positions=tuple(f"AUX{i}" for i in range(14))),
        )
        mid = _make_node(
            "mid",
            channels=ChannelMap(count=14, positions=tuple(f"AUX{i}" for i in range(14))),
        )
        terminus = _make_node("terminus")
        l1 = AudioLink(source="a", target="mid")
        l2 = AudioLink(source="mid", target="terminus")
        g = AudioGraph(nodes=(a, mid, terminus), links=(l1, l2))
        violations = check_channel_count_topology_wide(g)
        assert any(v.kind == InvariantKind.CHANNEL_COUNT_TOPOLOGY_WIDE for v in violations)


# ---------------------------------------------------------------------------
# 6. GAIN_BUDGET
# ---------------------------------------------------------------------------


class TestGainBudget:
    def test_pass_under_budget(self) -> None:
        a = _make_node("a")
        b = _make_node("b")
        link = AudioLink(source="a", target="b", makeup_gain_db=12.0)
        g = AudioGraph(nodes=(a, b), links=(link,))
        assert check_gain_budget(g) == []

    def test_fail_over_budget(self) -> None:
        a = _make_node("a")
        b = _make_node("b")
        c = _make_node("c")
        l1 = AudioLink(source="a", target="b", makeup_gain_db=15.0)
        l2 = AudioLink(source="b", target="c", makeup_gain_db=15.0)
        g = AudioGraph(nodes=(a, b, c), links=(l1, l2))
        violations = check_gain_budget(g)
        assert any(v.kind == InvariantKind.GAIN_BUDGET for v in violations)

    def test_per_channel_override_pushes_over(self) -> None:
        a = _make_node("a")
        b = _make_node("b")
        link = AudioLink(source="a", target="b", makeup_gain_db=0.0)
        gs = GainStage(
            edge_source="a",
            edge_target="b",
            base_gain_db=20.0,
            per_channel_overrides={"FL": 10.0},
        )
        g = AudioGraph(nodes=(a, b), links=(link,), gain_stages=(gs,))
        violations = check_gain_budget(g)
        assert any(v.kind == InvariantKind.GAIN_BUDGET for v in violations)


# ---------------------------------------------------------------------------
# 7. MASTER_BUS_SOLE_PATH
# ---------------------------------------------------------------------------


class TestMasterBusSolePath:
    def test_pass_when_master_is_only_path(self) -> None:
        master = _make_node("broadcast-master")
        norm = _make_node("broadcast-normalized")
        obs = _make_node("hapax-obs-broadcast-remap")
        l1 = AudioLink(source="broadcast-master", target="broadcast-normalized")
        l2 = AudioLink(source="broadcast-normalized", target="hapax-obs-broadcast-remap")
        g = AudioGraph(nodes=(master, norm, obs), links=(l1, l2))
        assert check_master_bus_sole_path(g) == []

    def test_pass_when_no_master(self) -> None:
        # If there's no master node, the invariant is silent
        a = _make_node("a")
        b = _make_node("b")
        g = AudioGraph(nodes=(a, b))
        assert check_master_bus_sole_path(g) == []

    def test_fail_when_bypass_exists(self) -> None:
        # A node reaches OBS without going through the master
        master = _make_node("broadcast-master")
        bypass = _make_node("rogue-source")
        obs = _make_node("hapax-obs-broadcast-remap")
        # Master -> OBS (normal path)
        l1 = AudioLink(source="broadcast-master", target="hapax-obs-broadcast-remap")
        # Rogue -> OBS (bypass)
        l2 = AudioLink(source="rogue-source", target="hapax-obs-broadcast-remap")
        g = AudioGraph(nodes=(master, bypass, obs), links=(l1, l2))
        violations = check_master_bus_sole_path(g)
        assert any(v.kind == InvariantKind.MASTER_BUS_SOLE_PATH for v in violations)


# ---------------------------------------------------------------------------
# 8. NO_DUPLICATE_PIPEWIRE_NAMES
# ---------------------------------------------------------------------------


class TestNoDuplicatePipewireNames:
    def test_pass_unique(self) -> None:
        a = _make_node("a", pipewire_name="hapax-a")
        b = _make_node("b", pipewire_name="hapax-b")
        g = AudioGraph(nodes=(a, b))
        assert check_no_duplicate_pipewire_names(g) == []

    def test_fail_duplicate(self) -> None:
        a = _make_node("a", pipewire_name="hapax-shared")
        b = _make_node("b", pipewire_name="hapax-shared")
        g = AudioGraph(nodes=(a, b))
        violations = check_no_duplicate_pipewire_names(g)
        assert len(violations) == 1
        assert violations[0].kind == InvariantKind.NO_DUPLICATE_PIPEWIRE_NAMES


# ---------------------------------------------------------------------------
# 9. HARDWARE_BLEED_GUARD
# ---------------------------------------------------------------------------


class TestHardwareBleedGuard:
    def test_pass_no_bleed_declared(self) -> None:
        a = _make_node("a")
        b = _make_node("b")
        gs = GainStage(edge_source="a", edge_target="b", base_gain_db=24.0)
        g = AudioGraph(nodes=(a, b), gain_stages=(gs,))
        assert check_hardware_bleed_guard(g) == []

    def test_pass_when_gain_below_bleed(self) -> None:
        a = _make_node("a")
        b = _make_node("b")
        # base 0, bleed 27 → 0 - 27 = -27 ≤ 0 ✓
        gs = GainStage(edge_source="a", edge_target="b", base_gain_db=0.0, declared_bleed_db=27.0)
        g = AudioGraph(nodes=(a, b), gain_stages=(gs,))
        assert check_hardware_bleed_guard(g) == []

    def test_fail_base_exceeds_bleed(self) -> None:
        a = _make_node("a")
        b = _make_node("b")
        # base 10, bleed 5 → 10 - 5 = 5 > 0 ✗
        gs = GainStage(edge_source="a", edge_target="b", base_gain_db=10.0, declared_bleed_db=5.0)
        g = AudioGraph(nodes=(a, b), gain_stages=(gs,))
        violations = check_hardware_bleed_guard(g)
        assert any(v.kind == InvariantKind.HARDWARE_BLEED_GUARD for v in violations)

    def test_fail_per_channel_override_exceeds_bleed(self) -> None:
        a = _make_node("a")
        b = _make_node("b")
        # base 0, override AUX3=15, bleed 27 → 0 + 15 - 27 = -12 ≤ 0 (pass)
        # base 0, override AUX3=30, bleed 27 → 0 + 30 - 27 = 3 > 0 (fail)
        gs = GainStage(
            edge_source="a",
            edge_target="b",
            base_gain_db=0.0,
            per_channel_overrides={"AUX3": 30.0},
            declared_bleed_db=27.0,
        )
        # base+override outside [-90,30] for AUX3 — limit is 30
        # let's adjust to a value within range that still violates
        gs2 = GainStage(
            edge_source="a",
            edge_target="b",
            base_gain_db=10.0,
            per_channel_overrides={"AUX3": 20.0},
            declared_bleed_db=27.0,
        )
        g = AudioGraph(nodes=(a, b), gain_stages=(gs, gs2))
        violations = check_hardware_bleed_guard(g)
        assert any(v.kind == InvariantKind.HARDWARE_BLEED_GUARD for v in violations)


# ---------------------------------------------------------------------------
# 10. EGRESS_SAFETY_BAND_RMS
# ---------------------------------------------------------------------------


class TestEgressSafetyBandRMS:
    def test_pass_rms_in_band(self) -> None:
        obs = _make_node("hapax-obs-broadcast-remap")
        g = AudioGraph(nodes=(obs,))
        health = EgressHealth(rms_dbfs=-22.0, crest_factor=3.5, zcr=0.05)
        assert check_egress_safety_band_rms(g, health) == []

    def test_pass_when_livestream_inactive(self) -> None:
        obs = _make_node("hapax-obs-broadcast-remap")
        g = AudioGraph(nodes=(obs,))
        # RMS OUTSIDE band, but livestream not active → no violation
        health = EgressHealth(rms_dbfs=-80.0, crest_factor=3.5, zcr=0.05, livestream_active=False)
        assert check_egress_safety_band_rms(g, health) == []

    def test_fail_rms_too_quiet(self) -> None:
        obs = _make_node("hapax-obs-broadcast-remap")
        g = AudioGraph(nodes=(obs,))
        health = EgressHealth(rms_dbfs=-80.0, crest_factor=3.5, zcr=0.05)
        violations = check_egress_safety_band_rms(g, health)
        assert any(v.kind == InvariantKind.EGRESS_SAFETY_BAND_RMS for v in violations)

    def test_fail_rms_too_loud(self) -> None:
        obs = _make_node("hapax-obs-broadcast-remap")
        g = AudioGraph(nodes=(obs,))
        health = EgressHealth(rms_dbfs=-2.0, crest_factor=3.5, zcr=0.05)
        violations = check_egress_safety_band_rms(g, health)
        assert any(v.kind == InvariantKind.EGRESS_SAFETY_BAND_RMS for v in violations)


# ---------------------------------------------------------------------------
# 11. EGRESS_SAFETY_BAND_CREST
# ---------------------------------------------------------------------------


class TestEgressSafetyBandCrest:
    def test_pass_normal_crest(self) -> None:
        obs = _make_node("hapax-obs-broadcast-remap")
        g = AudioGraph(nodes=(obs,))
        health = EgressHealth(rms_dbfs=-20.0, crest_factor=3.5, zcr=0.05)
        assert check_egress_safety_band_crest(g, health) == []

    def test_pass_when_livestream_inactive(self) -> None:
        obs = _make_node("hapax-obs-broadcast-remap")
        g = AudioGraph(nodes=(obs,))
        # Crest above threshold but inactive → no violation
        health = EgressHealth(rms_dbfs=-20.0, crest_factor=8.0, zcr=0.4, livestream_active=False)
        assert check_egress_safety_band_crest(g, health) == []

    def test_pass_when_below_rms_floor(self) -> None:
        # High crest but very quiet — operator wouldn't call it noise
        obs = _make_node("hapax-obs-broadcast-remap")
        g = AudioGraph(nodes=(obs,))
        health = EgressHealth(rms_dbfs=-50.0, crest_factor=8.0, zcr=0.4)
        assert check_egress_safety_band_crest(g, health) == []

    def test_fail_clipping_noise(self) -> None:
        obs = _make_node("hapax-obs-broadcast-remap")
        g = AudioGraph(nodes=(obs,))
        # crest > 5 AND rms > -40 → fail
        health = EgressHealth(rms_dbfs=-15.0, crest_factor=7.0, zcr=0.3)
        violations = check_egress_safety_band_crest(g, health)
        assert any(v.kind == InvariantKind.EGRESS_SAFETY_BAND_CREST for v in violations)


# ---------------------------------------------------------------------------
# Aggregate runner
# ---------------------------------------------------------------------------


class TestCheckAllInvariants:
    def test_clean_graph_passes_all(self) -> None:
        master = _make_node("broadcast-master")
        norm = _make_node("broadcast-normalized")
        obs = _make_node("hapax-obs-broadcast-remap")
        l1 = AudioLink(source="broadcast-master", target="broadcast-normalized")
        l2 = AudioLink(source="broadcast-normalized", target="hapax-obs-broadcast-remap")
        g = AudioGraph(nodes=(master, norm, obs), links=(l1, l2))
        violations = check_all_invariants(g)
        # Check_all may include several invariant kinds — we just want
        # zero blocking violations on a clean graph.
        blocking = [v for v in violations if v.severity == InvariantSeverity.BLOCKING]
        assert blocking == [], f"clean graph produced violations: {blocking}"

    def test_filter_kinds(self) -> None:
        # Build a graph that violates ONLY no_duplicate_pipewire_names
        a = _make_node("a", pipewire_name="dup")
        b = _make_node("b", pipewire_name="dup")
        g = AudioGraph(nodes=(a, b))
        only_dup = check_all_invariants(g, kinds={InvariantKind.NO_DUPLICATE_PIPEWIRE_NAMES})
        assert all(v.kind == InvariantKind.NO_DUPLICATE_PIPEWIRE_NAMES for v in only_dup)

    def test_egress_invariants_run_when_health_provided(self) -> None:
        obs = _make_node("hapax-obs-broadcast-remap")
        g = AudioGraph(nodes=(obs,))
        health = EgressHealth(rms_dbfs=-80.0, crest_factor=3.0, zcr=0.05)
        violations = check_all_invariants(g, egress_health=health)
        assert any(v.kind == InvariantKind.EGRESS_SAFETY_BAND_RMS for v in violations)

    def test_egress_invariants_skipped_without_health(self) -> None:
        obs = _make_node("hapax-obs-broadcast-remap")
        g = AudioGraph(nodes=(obs,))
        violations = check_all_invariants(g)
        # Without health, the egress-band predicates can't fire
        assert not any(
            v.kind
            in (
                InvariantKind.EGRESS_SAFETY_BAND_RMS,
                InvariantKind.EGRESS_SAFETY_BAND_CREST,
            )
            for v in violations
        )
