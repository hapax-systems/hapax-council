"""Invariant tests — every one of 11 invariants has + and - test cases."""

from __future__ import annotations

from shared.audio_graph import (
    AudioGraph,
    AudioLink,
    AudioNode,
    ChannelDownmix,
    ChannelMap,
    DownmixRoute,
    DownmixStrategy,
    FormatSpec,
    GainStage,
    NodeKind,
)
from shared.audio_graph.invariants import (
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


def _make_node(
    node_id: str,
    *,
    kind: NodeKind = NodeKind.FILTER_CHAIN,
    fail_closed: bool = False,
    private_monitor_endpoint: bool = False,
    channels_count: int = 2,
    pipewire_name: str | None = None,
    target_object: str | None = None,
    hw: str | None = None,
) -> AudioNode:
    return AudioNode(
        id=node_id,
        kind=kind,
        pipewire_name=pipewire_name or node_id,
        channels=ChannelMap(
            count=channels_count,
            positions=(
                ["FL", "FR"] if channels_count == 2 else [f"AUX{i}" for i in range(channels_count)]
            ),
        ),
        fail_closed=fail_closed,
        private_monitor_endpoint=private_monitor_endpoint,
        target_object=target_object,
        hw=hw,
    )


# ---------------------------------------------------------------------------
# 1. PRIVATE_NEVER_BROADCASTS
# ---------------------------------------------------------------------------


def test_private_never_broadcasts_clean_passes() -> None:
    g = AudioGraph(
        nodes=[
            _make_node("hapax-private", kind=NodeKind.TAP, fail_closed=True),
            _make_node("hapax-notification-private", kind=NodeKind.TAP, fail_closed=True),
        ]
    )
    assert check_private_never_broadcasts(g) == []


def test_private_never_broadcasts_violation_detected() -> None:
    nodes = [
        _make_node(
            "hapax-private",
            kind=NodeKind.TAP,
            fail_closed=True,
            private_monitor_endpoint=True,
        ),
        _make_node("livestream-tap", kind=NodeKind.TAP),
    ]
    g = AudioGraph(
        nodes=nodes,
        links=[AudioLink(source="hapax-private", target="livestream-tap")],
    )
    violations = check_private_never_broadcasts(g)
    assert any(v.kind == InvariantKind.PRIVATE_NEVER_BROADCASTS for v in violations)
    assert violations[0].severity == InvariantSeverity.BLOCKING


# ---------------------------------------------------------------------------
# 2. L12_DIRECTIONALITY
# ---------------------------------------------------------------------------


def test_l12_directionality_clean_passes() -> None:
    n = AudioNode(
        id="l12-capture",
        kind=NodeKind.LOOPBACK,
        pipewire_name="l12-capture",
        target_object="alsa_input.usb-ZOOM_Corporation_L-12_xxxx.multichannel-input",
        channels=ChannelMap(
            count=14,
            positions=[f"AUX{i}" for i in range(14)],
        ),
    )
    g = AudioGraph(nodes=[n])
    assert check_l12_directionality(g) == []


def test_l12_directionality_wrong_position_detected() -> None:
    n = AudioNode(
        id="l12-capture-bad",
        kind=NodeKind.LOOPBACK,
        pipewire_name="l12-capture-bad",
        target_object="alsa_input.usb-ZOOM_Corporation_L-12_xxxx.multichannel-input",
        channels=ChannelMap(count=2, positions=["RL", "RR"]),  # wrong direction
    )
    g = AudioGraph(nodes=[n])
    violations = check_l12_directionality(g)
    assert any(v.kind == InvariantKind.L12_DIRECTIONALITY for v in violations)


# ---------------------------------------------------------------------------
# 3. PORT_COMPATIBILITY
# ---------------------------------------------------------------------------


def test_port_compatibility_clean_passes() -> None:
    g = AudioGraph(
        nodes=[
            _make_node("a"),
            _make_node("b"),
        ],
        links=[AudioLink(source="a", source_port="FL", target="b", target_port="FL")],
    )
    assert check_port_compatibility(g) == []


def test_port_compatibility_mismatch_detected() -> None:
    g = AudioGraph(
        nodes=[_make_node("a"), _make_node("b")],
        links=[
            AudioLink(source="a", source_port="FL", target="b", target_port="RL"),
        ],
    )
    violations = check_port_compatibility(g)
    assert any(v.kind == InvariantKind.PORT_COMPATIBILITY for v in violations)


def test_port_compatibility_with_downmix_passes() -> None:
    cdm = ChannelDownmix(
        source_node="a",
        target_node="b",
        strategy=DownmixStrategy.CHANNEL_PICK,
        routes=[DownmixRoute(target_position="RL", source_positions=["FL"])],
    )
    g = AudioGraph(
        nodes=[_make_node("a"), _make_node("b")],
        links=[
            AudioLink(source="a", source_port="FL", target="b", target_port="RL"),
        ],
        channel_downmixes=[cdm],
    )
    assert check_port_compatibility(g) == []


# ---------------------------------------------------------------------------
# 4. FORMAT_COMPATIBILITY
# ---------------------------------------------------------------------------


def test_format_compatibility_same_count_passes() -> None:
    g = AudioGraph(
        nodes=[
            _make_node("a", channels_count=2),
            _make_node("b", channels_count=2),
        ],
        links=[AudioLink(source="a", target="b")],
    )
    assert check_format_compatibility(g) == []


def test_format_compatibility_count_change_without_downmix_detected() -> None:
    g = AudioGraph(
        nodes=[
            _make_node("l12-capture", channels_count=14),
            _make_node("l12-evilpet-capture", channels_count=2),
        ],
        links=[AudioLink(source="l12-capture", target="l12-evilpet-capture")],
    )
    violations = check_format_compatibility(g)
    assert any(v.kind == InvariantKind.FORMAT_COMPATIBILITY for v in violations)


def test_format_compatibility_count_change_with_downmix_passes() -> None:
    g = AudioGraph(
        nodes=[
            _make_node("l12-capture", channels_count=14),
            _make_node("l12-evilpet-capture", channels_count=2),
        ],
        links=[AudioLink(source="l12-capture", target="l12-evilpet-capture")],
        channel_downmixes=[
            ChannelDownmix(
                source_node="l12-capture",
                target_node="l12-evilpet-capture",
                strategy=DownmixStrategy.CHANNEL_PICK,
                routes=[DownmixRoute(target_position="FL", source_positions=["AUX1"])],
            )
        ],
    )
    assert check_format_compatibility(g) == []


# ---------------------------------------------------------------------------
# 5. CHANNEL_COUNT_TOPOLOGY_WIDE
# ---------------------------------------------------------------------------


def test_channel_count_topology_wide_with_format_specs_passes() -> None:
    g = AudioGraph(
        nodes=[
            _make_node("a", channels_count=14),
            _make_node("b", channels_count=2),
        ],
        channel_downmixes=[
            ChannelDownmix(
                source_node="a",
                target_node="b",
                strategy=DownmixStrategy.CHANNEL_PICK,
                routes=[DownmixRoute(target_position="FL", source_positions=["AUX1"])],
                source_format=FormatSpec(channels=14),
                target_format=FormatSpec(channels=2),
            )
        ],
    )
    assert check_channel_count_topology_wide(g) == []


def test_channel_count_topology_wide_missing_format_warns() -> None:
    g = AudioGraph(
        nodes=[
            _make_node("a", channels_count=14),
            _make_node("b", channels_count=2),
        ],
        channel_downmixes=[
            ChannelDownmix(
                source_node="a",
                target_node="b",
                strategy=DownmixStrategy.CHANNEL_PICK,
                routes=[DownmixRoute(target_position="FL", source_positions=["AUX1"])],
            )
        ],
    )
    violations = check_channel_count_topology_wide(g)
    assert any(v.kind == InvariantKind.CHANNEL_COUNT_TOPOLOGY_WIDE for v in violations)
    assert violations[0].severity == InvariantSeverity.WARNING


# ---------------------------------------------------------------------------
# 6. GAIN_BUDGET
# ---------------------------------------------------------------------------


def test_gain_budget_clean_passes() -> None:
    g = AudioGraph(
        nodes=[
            _make_node("src", kind=NodeKind.LOOPBACK),
            _make_node("hop"),
            _make_node("livestream-tap", kind=NodeKind.TAP),
        ],
        links=[
            AudioLink(source="src", target="hop", makeup_gain_db=14.0),
            AudioLink(source="hop", target="livestream-tap", makeup_gain_db=-1.0),
        ],
    )
    assert check_gain_budget(g) == []


def test_gain_budget_overage_detected() -> None:
    g = AudioGraph(
        nodes=[
            _make_node("src", kind=NodeKind.LOOPBACK),
            _make_node("hop"),
            _make_node("livestream-tap", kind=NodeKind.TAP),
        ],
        links=[
            AudioLink(source="src", target="hop", makeup_gain_db=20.0),
            AudioLink(source="hop", target="livestream-tap", makeup_gain_db=10.0),
        ],
    )
    violations = check_gain_budget(g)
    assert any(v.kind == InvariantKind.GAIN_BUDGET for v in violations)


# ---------------------------------------------------------------------------
# 7. MASTER_BUS_SOLE_PATH
# ---------------------------------------------------------------------------


def test_master_bus_sole_path_traversed_passes() -> None:
    g = AudioGraph(
        nodes=[
            _make_node("src", kind=NodeKind.LOOPBACK),
            _make_node("broadcast-master"),
            _make_node("broadcast-normalized", kind=NodeKind.TAP),
        ],
        links=[
            AudioLink(source="src", target="broadcast-master"),
            AudioLink(source="broadcast-master", target="broadcast-normalized"),
        ],
    )
    assert check_master_bus_sole_path(g) == []


def test_master_bus_sole_path_bypass_warns() -> None:
    g = AudioGraph(
        nodes=[
            _make_node("src", kind=NodeKind.LOOPBACK),
            _make_node("broadcast-master"),
            _make_node("broadcast-normalized", kind=NodeKind.TAP),
        ],
        links=[
            # bypass: src goes straight to broadcast-normalized
            AudioLink(source="src", target="broadcast-normalized"),
        ],
    )
    violations = check_master_bus_sole_path(g)
    assert any(v.kind == InvariantKind.MASTER_BUS_SOLE_PATH for v in violations)
    assert violations[0].severity == InvariantSeverity.WARNING


# ---------------------------------------------------------------------------
# 8. NO_DUPLICATE_PIPEWIRE_NAMES
# ---------------------------------------------------------------------------


def test_no_duplicate_pipewire_names_clean_passes() -> None:
    g = AudioGraph(
        nodes=[
            _make_node("a", pipewire_name="a"),
            _make_node("b", pipewire_name="b"),
        ]
    )
    assert check_no_duplicate_pipewire_names(g) == []


def test_no_duplicate_pipewire_names_caught_at_validation() -> None:
    """Schema validator catches dupe before checker even runs."""
    import pytest
    from pydantic import ValidationError

    n1 = _make_node("a", pipewire_name="dup")
    n2 = _make_node("b", pipewire_name="dup")
    with pytest.raises(ValidationError):
        AudioGraph(nodes=[n1, n2])


# ---------------------------------------------------------------------------
# 9. HARDWARE_BLEED_GUARD
# ---------------------------------------------------------------------------


def test_hardware_bleed_guard_silent_passes() -> None:
    g = AudioGraph(
        nodes=[_make_node("a")],
        gain_stages=[
            GainStage(
                edge_source="a",
                edge_target="b",
                base_gain_db=-30.0,
                declared_bleed_db=27.0,
            ),
        ],
    )
    assert check_hardware_bleed_guard(g) == []


def test_hardware_bleed_guard_amplification_detected() -> None:
    g = AudioGraph(
        nodes=[_make_node("a")],
        gain_stages=[
            GainStage(
                edge_source="l12-capture",
                edge_target="gain_samp",
                base_gain_db=0.0,
                declared_bleed_db=27.0,  # net = 0 + 0 - 27 = -27 ≤ 0 (passes)
                per_channel_overrides={"AUX3": 30.0},  # net = 0 + 30 - 27 = +3 (FAIL)
            ),
        ],
    )
    violations = check_hardware_bleed_guard(g)
    assert any(v.kind == InvariantKind.HARDWARE_BLEED_GUARD for v in violations)


# ---------------------------------------------------------------------------
# 10. EGRESS_SAFETY_BAND_RMS
# ---------------------------------------------------------------------------


def test_egress_safety_band_rms_egress_present_passes_structurally() -> None:
    g = AudioGraph(
        nodes=[
            _make_node("obs-broadcast-remap"),
        ]
    )
    # Structural check; passes (an egress exists).
    assert check_egress_safety_band_rms(g) == []


def test_egress_safety_band_rms_no_egress_warns() -> None:
    g = AudioGraph(
        nodes=[_make_node("a")],  # no egress node
    )
    violations = check_egress_safety_band_rms(g)
    assert any(v.kind == InvariantKind.EGRESS_SAFETY_BAND_RMS for v in violations)
    assert violations[0].severity == InvariantSeverity.WARNING


# ---------------------------------------------------------------------------
# 11. EGRESS_SAFETY_BAND_CREST
# ---------------------------------------------------------------------------


def test_egress_safety_band_crest_egress_present_passes_structurally() -> None:
    g = AudioGraph(nodes=[_make_node("obs-broadcast-remap")])
    assert check_egress_safety_band_crest(g) == []


def test_egress_safety_band_crest_no_egress_warns() -> None:
    g = AudioGraph(nodes=[_make_node("a")])
    violations = check_egress_safety_band_crest(g)
    assert any(v.kind == InvariantKind.EGRESS_SAFETY_BAND_CREST for v in violations)
    assert violations[0].severity == InvariantSeverity.WARNING


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------


def test_check_all_invariants_runs_each() -> None:
    g = AudioGraph(nodes=[_make_node("a")])
    violations = check_all_invariants(g)
    # Two warnings expected (egress missing + master-bus skipped because
    # no broadcast-master node, but those won't fire either because the
    # graph has no path to a non-existent egress).
    kinds = {v.kind for v in violations}
    assert InvariantKind.EGRESS_SAFETY_BAND_RMS in kinds
    assert InvariantKind.EGRESS_SAFETY_BAND_CREST in kinds
