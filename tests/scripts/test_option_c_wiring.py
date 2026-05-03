"""Option C — private-monitor track-fenced via S-4 (Phase 0 wiring).

These tests cover the Phase 0 wiring shipped per the spec amendment at
`docs/superpowers/specs/2026-05-02-hapax-private-monitor-track-fenced-via-s4.md`:

  1. WirePlumber pin retargeting from Yeti to S-4 USB IN Track 1 input.
  2. Leak-guard forbidden-list narrowing (S-4 USB OUT pair forbidden,
     S-4 USB IN sink ALLOWED — the privacy invariant moved to TRACK-OUTPUT
     level per the spec amendment).
  3. Audio-topology descriptor entries for the S-4 private-monitor route.
  4. Runtime-edge classifier addition (`private-track-fenced-via-s4-out-1`)
     so the topology audit doesn't flag the new edge as drift.

Phase 0 explicitly excludes S-4 internal scene programming (operator-side
firmware action) and operator hardware patch validation (operator-confirmed
2026-05-02T~17:00Z).

Reference: cc-task `~/Documents/Personal/20-projects/hapax-cc-tasks/active/private-hapax-s4-track-fenced-implementation.md`.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import types
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

WP_S4_PIN = REPO_ROOT / "config" / "wireplumber" / "56-hapax-private-pin-s4-track-1.conf"
WP_YETI_DISABLED = (
    REPO_ROOT
    / "config"
    / "wireplumber"
    / "56-hapax-private-pin-yeti.conf.disabled-2026-05-02-option-c"
)
LEAK_GUARD_SCRIPT = REPO_ROOT / "scripts" / "hapax-private-broadcast-leak-guard"
TOPOLOGY_AUDIT_SCRIPT = REPO_ROOT / "scripts" / "hapax-audio-topology"
AUDIO_TOPOLOGY_YAML = REPO_ROOT / "config" / "audio-topology.yaml"
OPTION_C_DOC = REPO_ROOT / "docs" / "governance" / "option-c-private-track-fenced-routing.md"

S4_USB_SINK = "alsa_output.usb-Torso_Electronics_S-4_fedcba9876543220-03.multichannel-output"
S4_USB_SOURCE = "alsa_input.usb-Torso_Electronics_S-4_fedcba9876543220-03.multichannel-input"


def _load_module(path: Path, name: str) -> types.ModuleType:
    """Load a script (no `.py` suffix) as an importable module."""
    loader = SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def leak_guard() -> types.ModuleType:
    return _load_module(LEAK_GUARD_SCRIPT, "leak_guard_option_c")


@pytest.fixture(scope="module")
def topology_audit() -> types.ModuleType:
    return _load_module(TOPOLOGY_AUDIT_SCRIPT, "topology_audit_option_c")


@pytest.fixture(scope="module")
def topology_yaml() -> dict[str, object]:
    return yaml.safe_load(AUDIO_TOPOLOGY_YAML.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. WirePlumber pin retargeting
# ---------------------------------------------------------------------------


def test_wp_s4_pin_targets_s4_usb_sink_not_yeti() -> None:
    """The new Layer B conf targets the S-4 USB IN sink, not the Yeti.

    Privacy invariant per Option C: any S-4 track routed to analog OUT 1/2
    is private (the operator's monitor patch). The host writes private TTS
    into the S-4 USB IN slot (host-side multichannel-output sink) which the
    S-4 internal scene routes to Track 1 → analog OUT 1/2.
    """
    body = WP_S4_PIN.read_text(encoding="utf-8")
    assert S4_USB_SINK in body, "S-4 USB IN sink must be the target.object"
    assert "Blue_Microphones_Yeti" not in body, "Yeti must not be the target"
    # Pinned for both assistant and notification private families.
    assert 'node.name = "hapax-private-playback"' in body
    assert 'node.name = "hapax-notification-private-playback"' in body


def test_wp_s4_pin_preserves_fail_closed_props() -> None:
    """`node.dont-fallback = true` must be preserved per the spec.

    If the S-4 is absent (USB-disconnected), the private stream stays
    unrouted (fail-closed) rather than falling back to the L-12 broadcast
    bus. This is the same fail-closed posture as the prior Yeti pin.
    """
    body = WP_S4_PIN.read_text(encoding="utf-8")
    assert "node.dont-fallback = true" in body
    assert "node.dont-reconnect = true" in body
    assert "node.dont-move = true" in body
    assert "node.linger = true" in body
    assert "priority.session = -1" in body


def test_wp_yeti_pin_preserved_disabled_for_revert() -> None:
    """The Yeti pin remains on disk under a `.disabled-*` suffix.

    Per global CLAUDE.md "revert > stall" policy and the cc-task constraint
    "DO NOT remove the Yeti-pin conf in this PR — keep it disabled so
    operator can revert if needed; don't delete".
    """
    assert WP_YETI_DISABLED.exists(), (
        "Yeti pin must be preserved disabled-on-disk for revert capability"
    )
    body = WP_YETI_DISABLED.read_text(encoding="utf-8")
    assert "Blue_Microphones_Yeti_Stereo_Microphone_REV8" in body


# ---------------------------------------------------------------------------
# 2. Leak-guard forbidden-list narrowing
# ---------------------------------------------------------------------------


def test_s4_usb_in_sink_is_not_forbidden_option_c(leak_guard: types.ModuleType) -> None:
    """The S-4 USB IN sink (host-side multichannel-output) is the new
    private route per Option C — must NOT be forbidden.

    Pre-Option C, the leak guard forbade `Torso_Electronics_S-4` as a
    target via a broad pattern that matched both USB IN sink and USB OUT
    source. The Option C narrowing splits these:

      ALLOW:  alsa_output.*Torso_Electronics_S-4*  (host writes here, S-4
              processes via Track 1, output goes to analog OUT 1/2)
      FORBID: alsa_input.*Torso_Electronics_S-4*   (host reads here from
              S-4 USB OUT pair → broadcast loopback)
    """
    text = (
        f"hapax-private-playback:output_FL\n"
        f"  |-> {S4_USB_SINK}:playback_AUX0\n"
        f"hapax-private-playback:output_FR\n"
        f"  |-> {S4_USB_SINK}:playback_AUX1\n"
    )
    edges = leak_guard.parse_pw_link(text)
    leaks = leak_guard.detect_forbidden(edges)
    assert leaks == [], (
        f"S-4 USB IN sink must be ALLOWED for private route under Option C; "
        f"got {[(l.source_port, l.target_port) for l in leaks]}"
    )


def test_s4_usb_out_pair_is_forbidden_option_c(leak_guard: types.ModuleType) -> None:
    """The S-4 USB OUT pair (host-side multichannel-input source) IS
    forbidden — it's the broadcast-bound capture surface.

    `s4-loopback` reads from the host-side `alsa_input.*S-4*` source and
    forwards to `hapax-livestream-tap`. Anything that lands on this source
    is in the broadcast set.
    """
    text = f"hapax-private-playback:output_FL\n  |-> {S4_USB_SOURCE}:capture_AUX0\n"
    edges = leak_guard.parse_pw_link(text)
    leaks = leak_guard.detect_forbidden(edges)
    assert len(leaks) == 1
    assert S4_USB_SOURCE in leaks[0].target_node


def test_s4_loopback_nodes_are_forbidden(leak_guard: types.ModuleType) -> None:
    """`hapax-s4-content` and `hapax-s4-tap` are the S-4 broadcast loopback
    nodes — private must not reach them.

    Per `config/audio-topology.yaml` `s4-loopback`, these nodes target
    `hapax-livestream-tap`. The broad `^hapax-s4-(?:content|tap)` pattern
    in the leak guard matches both.
    """
    text = (
        "hapax-private-playback:output_FL\n"
        "  |-> hapax-s4-content:input_FL\n"
        "hapax-notification-private-playback:output_FL\n"
        "  |-> hapax-s4-tap:input_FL\n"
    )
    edges = leak_guard.parse_pw_link(text)
    leaks = leak_guard.detect_forbidden(edges)
    assert len(leaks) == 2
    targets = {leak.target_node for leak in leaks}
    assert "hapax-s4-content" in targets
    assert "hapax-s4-tap" in targets


# ---------------------------------------------------------------------------
# 3. Audio-topology descriptor
# ---------------------------------------------------------------------------


def test_topology_yaml_s4_output_carries_option_c_annotation(
    topology_yaml: dict[str, object],
) -> None:
    """The S-4 USB IN sink (`s4-output`) carries the Option C annotation.

    Per the spec amendment, the S-4 USB pair is dual-citizen: broadcast
    tracks 2-4 also write to this same sink. The privacy invariant lives
    at TRACK-OUTPUT level (which Track is routed where inside the S-4
    firmware), not device level. The descriptor records this via params
    on the existing `s4-output` node rather than introducing a duplicate
    pipewire_name node.
    """
    nodes = topology_yaml["nodes"]
    assert isinstance(nodes, list)
    by_id = {node["id"]: node for node in nodes if isinstance(node, dict)}
    assert "s4-output" in by_id, "config/audio-topology.yaml must declare s4-output"
    node = by_id["s4-output"]
    assert node["pipewire_name"] == S4_USB_SINK
    params = node.get("params", {})
    assert params.get("private_monitor_endpoint") is True
    assert params.get("private_monitor_track") == 1
    assert params.get("option_c_route") == "private-track-fenced-via-s4-out-1"


def test_topology_yaml_declares_s4_analog_out_endpoint(
    topology_yaml: dict[str, object],
) -> None:
    """Descriptor must include the S-4 analog OUT 1/2 endpoint node.

    This node models the operator's monitor patch destination so the audit
    graph can reason about where the private-monitor track terminates and
    can verify there is no software path back to L-12 USB IN.
    """
    nodes = topology_yaml["nodes"]
    by_id = {node["id"]: node for node in nodes if isinstance(node, dict)}
    assert "s4-analog-out-1-2" in by_id, (
        "config/audio-topology.yaml must declare the S-4 analog OUT 1/2 endpoint"
    )
    params = by_id["s4-analog-out-1-2"].get("params", {})
    assert params.get("private_monitor_endpoint") is True
    assert params.get("forbidden_target_family") == "l12-broadcast"


def test_topology_yaml_canonical_option_c_edges(topology_yaml: dict[str, object]) -> None:
    """Descriptor must include the canonical Option C private-monitor edges."""
    edges = topology_yaml["edges"]
    assert isinstance(edges, list)
    edge_set = {(edge["source"], edge["target"]) for edge in edges if isinstance(edge, dict)}
    assert ("private-monitor-output", "s4-output") in edge_set, (
        "private-monitor-output must edge into s4-output (the S-4 USB IN sink)"
    )
    assert ("notification-private-monitor-output", "s4-output") in edge_set
    assert ("s4-output", "s4-analog-out-1-2") in edge_set


def test_topology_yaml_private_monitor_output_targets_s4(
    topology_yaml: dict[str, object],
) -> None:
    """`private-monitor-output` (and notification sibling) must target the
    S-4 USB IN sink, not the Yeti, per Option C."""
    nodes = topology_yaml["nodes"]
    by_id = {node["id"]: node for node in nodes if isinstance(node, dict)}
    assert by_id["private-monitor-output"]["target_object"] == S4_USB_SINK
    assert by_id["notification-private-monitor-output"]["target_object"] == S4_USB_SINK


# ---------------------------------------------------------------------------
# 4. Runtime-edge classifier
# ---------------------------------------------------------------------------


def test_classifier_recognizes_private_track_fenced_edge(
    topology_audit: types.ModuleType,
) -> None:
    """The runtime-edge classifier must produce the new
    `private-track-fenced-via-s4-out-1` label for the Option C edge.

    Without this, the topology audit (`hapax-audio-topology verify`) would
    flag the new edge as drift — `+ edges only in right` — and refuse to
    pass.
    """
    from shared.audio_topology import ChannelMap, Node, NodeKind

    # The bridge (private-monitor-output) targets the S-4 USB IN sink
    # (s4-output) under Option C. Both sides carry option_c_route =
    # private-track-fenced-via-s4-out-1.
    bridge = Node(
        id="private-monitor-output",
        kind=NodeKind.LOOPBACK,
        pipewire_name="hapax-private-playback",
        description="Option C private-monitor bridge to S-4 USB IN Track 1 input",
        target_object=S4_USB_SINK,
        channels=ChannelMap(count=2, positions=["FL", "FR"]),
        params={
            "private_monitor_bridge": True,
            "option_c_route": "private-track-fenced-via-s4-out-1",
        },
    )
    s4_endpoint = Node(
        id="s4-output",
        kind=NodeKind.ALSA_SINK,
        pipewire_name=S4_USB_SINK,
        description="S-4 USB IN sink (Option C private-monitor endpoint)",
        target_object=None,
        hw="hw:CARD=S4",
        channels=ChannelMap(
            count=10,
            positions=[
                "AUX0",
                "AUX1",
                "AUX2",
                "AUX3",
                "AUX4",
                "AUX5",
                "AUX6",
                "AUX7",
                "AUX8",
                "AUX9",
            ],
        ),
        params={
            "private_monitor_endpoint": True,
            "private_monitor_track": 1,
            "option_c_route": "private-track-fenced-via-s4-out-1",
        },
    )
    declared_by_name = {
        bridge.pipewire_name: bridge,
        s4_endpoint.pipewire_name: s4_endpoint,
    }
    live_by_name = dict(declared_by_name)

    classification = topology_audit._classify_live_extra_edge(
        bridge.pipewire_name,
        s4_endpoint.pipewire_name,
        declared_by_name,
        live_by_name,
    )
    assert classification == "private-track-fenced-via-s4-out-1", (
        f"Option C edge must be classified as 'private-track-fenced-via-s4-out-1'; "
        f"got {classification!r}"
    )


def test_inspector_taxonomy_lists_option_c_classification() -> None:
    """The inspector module exports the classification taxonomy.

    Adding to `ALLOWED_RUNTIME_EDGE_CLASSIFICATIONS` keeps downstream
    tools and tests synced with the classifier in `hapax-audio-topology`.
    """
    from shared.audio_topology_inspector import ALLOWED_RUNTIME_EDGE_CLASSIFICATIONS

    assert "private-track-fenced-via-s4-out-1" in ALLOWED_RUNTIME_EDGE_CLASSIFICATIONS
    # Legacy classification preserved for revert path.
    assert "private-monitor-runtime-output-binding" in ALLOWED_RUNTIME_EDGE_CLASSIFICATIONS


# ---------------------------------------------------------------------------
# 5. Documentation
# ---------------------------------------------------------------------------


def test_option_c_runbook_covers_required_operator_actions() -> None:
    """The Option C operator runbook documents the required post-merge steps."""
    body = OPTION_C_DOC.read_text(encoding="utf-8")
    for marker in [
        "56-hapax-private-pin-s4-track-1.conf",
        "HAPAX-PRIVATE-MONITOR",
        "S-4 analog OUT 1/2",
        "wireplumber.service",
        "hapax-private-broadcast-leak-guard",
        "Forbidden analog patch destinations",
        "2026-05-02-hapax-private-monitor-track-fenced-via-s4.md",
    ]:
        assert marker in body, f"Option C runbook missing: {marker!r}"


def test_inspector_private_monitor_bridge_allows_s4_endpoint() -> None:
    """The inspector's `_PRIVATE_MONITOR_BRIDGES` map allows the S-4
    endpoint (`s4-output`) so `check_l12_forward_invariant` validates the
    new topology correctly. Yeti is preserved as an allowed alternative
    for revert capability per global CLAUDE.md "revert > stall" policy.
    """
    from shared.audio_topology_inspector import _PRIVATE_MONITOR_BRIDGES

    for bridge_id in ("private-monitor-output", "notification-private-monitor-output"):
        _capture_id, _source_id, allowed_endpoints = _PRIVATE_MONITOR_BRIDGES[bridge_id]
        # Allowed endpoints should be a tuple/list including the Option C
        # S-4 target. (Yeti is also allowed for revert capability.)
        assert isinstance(allowed_endpoints, (tuple, list)), (
            f"{bridge_id} allowed endpoints must be a tuple/list under Option C"
        )
        assert "s4-output" in allowed_endpoints, (
            f"{bridge_id} must allow the S-4 USB IN sink (s4-output) per Option C"
        )


def test_leak_guard_forbidden_pattern_is_anchored() -> None:
    """The S-4 narrowing pattern must be anchored so it doesn't accidentally
    match the host-side sink.

    Regression pin: a poorly-anchored pattern like `Torso_Electronics_S-4`
    (no anchor) would re-broaden the forbid to include the USB IN sink and
    break Option C. The Option C pattern uses `^alsa_input\\.usb-Torso_...`
    which is anchored to the source-side device only.
    """
    body = LEAK_GUARD_SCRIPT.read_text(encoding="utf-8")
    # The unanchored old pattern must be GONE.
    assert 're.compile(r"Torso_Electronics_S-4")' not in body, (
        "Unanchored S-4 pattern would re-forbid the new Option C private route"
    )
    # The new anchored input-side pattern must be present.
    assert (
        re.search(
            r're\.compile\(r"\^alsa_input\\\.usb-Torso_Electronics_S-4',
            body,
        )
        is not None
    ), "Option C narrowed pattern must anchor to alsa_input.* (S-4 USB OUT pair)"
