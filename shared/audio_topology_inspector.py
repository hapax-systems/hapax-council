"""pw-dump → TopologyDescriptor inspector (CLI Phase 4).

Parses PipeWire's ``pw-dump`` JSON output into a ``TopologyDescriptor``
instance so the Phase 3 CLI's ``verify`` / ``switch`` / ``audit`` /
``watchdog`` subcommands have a live-graph view.

pw-dump shape (abridged):

    [
      {"id": N, "type": "PipeWire:Interface:Node", "info": {
          "props": {
              "node.name": "alsa_input.usb-...",
              "media.class": "Audio/Source",
              "factory.name": "api.alsa.pcm.source",
              "api.alsa.path": "hw:L6,0",
              "audio.channels": 12,
              ...
          }
      }},
      {"id": N, "type": "PipeWire:Interface:Link", "info": {
          "output-node-id": ..., "output-port-id": ...,
          "input-node-id": ...,  "input-port-id": ...
      }},
      {"id": N, "type": "PipeWire:Interface:Port", ...}
    ]

Mapping to our descriptor:

- ``media.class="Audio/Source"`` + ``factory.name="api.alsa.pcm.source"``
  → ``NodeKind.ALSA_SOURCE``
- ``media.class="Audio/Sink"`` + ``factory.name="api.alsa.pcm.sink"``
  → ``NodeKind.ALSA_SINK``
- ``media.class="Audio/Sink"`` + ``factory.name="support.null-audio-sink"``
  → ``NodeKind.TAP``
- ``factory.name=="filter-chain"`` or ``node.name`` starts with
  ``hapax-``-prefixed filter-chain → ``NodeKind.FILTER_CHAIN``
- ``factory.name=="loopback"`` → ``NodeKind.LOOPBACK``

Edges built from Link objects only — pw-dump's ``output-node-id`` /
``input-node-id`` integer refs. We resolve those back to descriptor
``id`` strings by node-id lookup.

Scope (Phase 4):

- Live graph → descriptor round-trip so ``verify`` can diff against
  the canonical ``config/audio-topology.yaml``.
- NOT writing changes back to PipeWire — that's Phase 5 (watchdog
  + switch).
- NOT edge ports. pw-dump's port discovery requires a second pass
  over Port objects + mapping back to node+channel-position, which
  adds surface without immediate livestream-readiness value. Phase
  4 edges carry source/target node ids only; port info is Phase 5+.

References:
    - docs/superpowers/plans/2026-04-20-unified-audio-architecture-plan.md §4
    - man 1 pw-dump
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shared.audio_topology import (
    ChannelMap,
    Edge,
    Node,
    NodeKind,
    TopologyDescriptor,
)

_PIPEWIRE_NODE = "PipeWire:Interface:Node"
_PIPEWIRE_LINK = "PipeWire:Interface:Link"


# Runtime-edge classification taxonomy.
#
# When the live PipeWire graph contains edges that are not present in the
# declared `config/audio-topology.yaml`, the audit (`hapax-audio-topology
# verify`) classifies each extra edge against this taxonomy. Anything
# unclassified surfaces as drift (`+ edges only in right`) and fails the
# audit. The actual classifier function lives in
# `scripts/hapax-audio-topology._classify_live_extra_edge`; this constant
# is the public-facing list so downstream tools (and tests) can reason
# about the allowed set.
#
# Adding a new classification here is necessary but not sufficient — the
# classifier function in the script must also produce the new label.
ALLOWED_RUNTIME_EDGE_CLASSIFICATIONS: tuple[str, ...] = (
    # Pre-Option C: legacy Yeti pin private-monitor binding.
    "private-monitor-runtime-output-binding",
    # Option C (2026-05-02 spec amendment): track-fenced private monitor
    # via S-4. Architectural compliance edge for the Option C resolution
    # of the NO-DRY-HAPAX vs PRIVATE-NEVER-BROADCASTS contradiction.
    # See `docs/superpowers/specs/2026-05-02-hapax-private-monitor-track-fenced-via-s4.md`.
    "private-track-fenced-via-s4-out-1",
    # Runtime fallback when the M8 hardware source is absent.
    "runtime-fallback-m8-source-absent",
)


@dataclass(frozen=True)
class TtsBroadcastPathCheck:
    """Result of the TTS-to-livestream forward-path health check."""

    ok: bool
    missing_nodes: tuple[str, ...]
    missing_edges: tuple[str, ...]

    def format(self) -> str:
        """Operator-readable single report block."""
        lines = ["TTS broadcast path: " + ("OK" if self.ok else "FAIL")]
        for node in self.missing_nodes:
            lines.append(f"missing node: {node}")
        for edge in self.missing_edges:
            lines.append(f"missing edge: {edge}")
        return "\n".join(lines)


@dataclass(frozen=True)
class L12ForwardInvariantViolation:
    """One static L-12 directionality violation in a topology descriptor."""

    code: str
    message: str


@dataclass(frozen=True)
class L12ForwardInvariantCheck:
    """Result of the static L-12 forward/private directionality check."""

    ok: bool
    violations: tuple[L12ForwardInvariantViolation, ...]

    def format(self) -> str:
        """Operator-readable single report block."""
        lines = ["L-12 forward invariant: " + ("OK" if self.ok else "FAIL")]
        for violation in self.violations:
            lines.append(f"{violation.code}: {violation.message}")
        return "\n".join(lines)


_REQUIRED_L12_DIRECTIONALITY_NODES = {
    "l12-capture",
    "l12-usb-return",
    "livestream-tap",
    "l12-evilpet-capture",
    "private-sink",
    "private-monitor-capture",
    "private-monitor-output",
    "notification-private-sink",
    "notification-private-monitor-capture",
    "notification-private-monitor-output",
    "yeti-headphone-output",
    "role-multimedia",
    "role-notification",
    "role-assistant",
    "role-broadcast",
    "pc-loudnorm",
    "voice-fx",
    "tts-loudnorm",
    "tts-duck",
    "tts-broadcast-capture",
    "tts-broadcast-playback",
}
_ALLOWED_L12_RETURN_PRODUCERS = {"tts-duck", "pc-loudnorm", "music-duck"}
_ALLOWED_L12_RETURN_DIRECTIONS = {"broadcast"}
_PRIVATE_ONLY_ROOTS = {
    "role-assistant",
    "role-notification",
    "private-sink",
    "private-monitor-capture",
    "private-monitor-output",
    "notification-private-sink",
    "notification-private-monitor-capture",
    "notification-private-monitor-output",
}
_PRIVATE_FORBIDDEN_REACHABILITY = {
    "l12-capture",
    "l12-usb-return",
    "l12-evilpet-capture",
    "livestream-tap",
    "livestream-legacy",
    "broadcast-master-capture",
    "broadcast-normalized-capture",
    "obs-broadcast-remap-capture",
    "role-multimedia",
    "pc-loudnorm",
    "voice-fx",
    "tts-loudnorm",
    "tts-duck",
    "tts-broadcast-capture",
    "tts-broadcast-playback",
}
_PRIVATE_MONITOR_BRIDGES = {
    # Option C (2026-05-02 spec amendment): private-monitor bridges target
    # the S-4 USB IN sink (`s4-output` carries the `option_c_route =
    # private-track-fenced-via-s4-out-1` annotation). The Yeti endpoint is
    # preserved as a valid alternative target for backward compatibility
    # (operator can revert via the disabled
    # `56-hapax-private-pin-yeti.conf.disabled-*` WirePlumber conf). See
    # `docs/superpowers/specs/2026-05-02-hapax-private-monitor-track-fenced-via-s4.md`.
    #
    # The third element of each tuple is the SET of allowed endpoint IDs.
    # `check_l12_forward_invariant` accepts any one of them; the WirePlumber
    # pin determines which is live.
    "private-monitor-output": (
        "private-monitor-capture",
        "private-sink",
        ("s4-output", "yeti-headphone-output"),
    ),
    "notification-private-monitor-output": (
        "notification-private-monitor-capture",
        "notification-private-sink",
        ("s4-output", "yeti-headphone-output"),
    ),
}
_PRIVATE_MONITOR_CAPTURE_NODES = {
    "private-monitor-capture": "private-sink",
    "notification-private-monitor-capture": "notification-private-sink",
}
_PRIVATE_MONITOR_FAIL_CLOSED_PARAMS = {
    "node.dont-fallback": True,
    "node.dont-reconnect": True,
    "node.dont-move": True,
    "node.linger": True,
    "state.restore": False,
    "fail_closed_on_target_absent": True,
}


def run_pw_dump() -> str:
    """Invoke ``pw-dump`` and return the JSON text.

    Isolated so tests can monkey-patch without a live PipeWire instance.
    Propagates CalledProcessError on non-zero exit — callers should
    tolerate or surface the failure; pw-dump failing usually means
    PipeWire isn't running, not a bug in this module.
    """
    result = subprocess.run(
        ["pw-dump"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _classify_node_kind(props: dict[str, Any]) -> NodeKind | None:
    """Infer ``NodeKind`` from a PipeWire node's props dict.

    Returns ``None`` for nodes this inspector doesn't model — e.g.
    ``media.class="Stream/*"`` application streams, client nodes.

    Heuristic notes (#216 inspector classification patch):

    PipeWire rarely sets ``factory.name`` on nodes spawned by module
    loaders (``filter-chain``, ``loopback``); the factory lives on the
    module record, not the exposed node. So we fall back to name-
    pattern matching for the hapax-* family of virtual nodes:

    - A hapax-* node whose media.class is Audio/Sink AND whose name
      does NOT end in ``-capture`` or ``-playback`` is treated as a
      LOOPBACK (client-facing sink side of a loopback module).
    - A hapax-* node whose name ends in ``-capture`` and whose media.
      class is Audio/Sink is treated as a FILTER_CHAIN (client-facing
      sink side of a filter-chain that processes captured audio).
    - Stream/* media.class nodes are always skipped — they're the
      internal pair of a filter-chain or loopback, not the primary
      node the descriptor declares.

    This yields correct classification for every ``hapax-*`` node we
    ship plus the ``support.null-audio-sink`` / loopback / ALSA
    primitives. Future module types (e.g. ``stream-split``) that
    don't fit this taxonomy would need new heuristics.
    """
    media_class = props.get("media.class", "")
    factory = props.get("factory.name", "")
    name = props.get("node.name", "")
    # Null-sink tap.
    if factory == "support.null-audio-sink":
        return NodeKind.TAP
    # Explicit loopback / filter-chain factories (when PipeWire sets
    # them — rare but honoured).
    if factory == "filter-chain":
        return NodeKind.FILTER_CHAIN
    if factory == "loopback" or "loopback" in name:
        if media_class == "Audio/Sink":
            return NodeKind.LOOPBACK
        return None
    # ALSA endpoints.
    if factory == "api.alsa.pcm.source" or media_class == "Audio/Source":
        if props.get("api.alsa.path"):
            return NodeKind.ALSA_SOURCE
    if factory == "api.alsa.pcm.sink" or media_class == "Audio/Sink":
        if props.get("api.alsa.path"):
            return NodeKind.ALSA_SINK
    # Factory-less hapax-* virtual nodes — name-pattern heuristic.
    # Most -playback suffix nodes are the internal pair of a filter-chain
    # or loopback, so the descriptor declares the -capture side or bare sink
    # as primary. Broadcast bridges are an exception: the playback side is
    # the only modeled endpoint that proves the bridge reaches the target
    # livestream tap.
    if (
        name.startswith("hapax-")
        and (
            "-broadcast-" in name
            or name
            in {
                "hapax-private-playback",
                "hapax-notification-private-playback",
            }
        )
        and name.endswith("-playback")
    ):
        return NodeKind.LOOPBACK
    if name.endswith("-playback"):
        return None
    # Skip Stream/Output (playback stream) but NOT Stream/Input —
    # some filter-chain / loopback capture sides expose as Stream/
    # Input/Audio rather than Audio/Sink.
    if media_class == "Stream/Output/Audio":
        return None
    if name.startswith("hapax-") and name.endswith("-capture"):
        # Capture side of a filter-chain (or occasionally a loopback).
        # The diff's kind-mismatch report surfaces disagreement with
        # the descriptor; the audit call sees them paired by
        # pipewire_name regardless.
        return NodeKind.FILTER_CHAIN
    if name.startswith("hapax-") and media_class == "Audio/Sink":
        # Bare hapax-<name> sink: canonical loopback pattern.
        return NodeKind.LOOPBACK
    return None


def _id_from_name(pipewire_name: str) -> str:
    """Derive a descriptor ``Node.id`` from the pipewire_name.

    Uses the pipewire node.name verbatim where it's already kebab-
    case (typical for our hapax-* naming), else transforms underscores
    to dashes and lowercases. Length cap keeps the id readable even
    for very long ALSA names.
    """
    base = pipewire_name.lower().replace("_", "-")
    # Trim ALSA's long factory-suffix so the id is tractable. E.g.
    # "alsa-input.usb-zoom-corporation-l6-00.multitrack" → last two
    # segments: "l6-00-multitrack".
    if base.startswith("alsa-input.") or base.startswith("alsa-output."):
        tail = base.split(".", 1)[1]
        # Keep the last two dash-separated segments.
        parts = tail.split("-")
        if len(parts) > 2:
            base = "-".join(parts[-2:])
        else:
            base = tail
    return base


def _build_node(pw_node: dict[str, Any]) -> Node | None:
    props = pw_node.get("info", {}).get("props", {})
    kind = _classify_node_kind(props)
    if kind is None:
        return None
    pipewire_name = props.get("node.name")
    if not pipewire_name:
        return None
    node_id = _id_from_name(pipewire_name)
    hw = props.get("api.alsa.path") if kind in (NodeKind.ALSA_SOURCE, NodeKind.ALSA_SINK) else None
    target_object = props.get("target.object")
    description = props.get("node.description", "")
    count = int(props.get("audio.channels") or 2)
    positions_raw = props.get("audio.position")
    positions: list[str] = []
    if isinstance(positions_raw, list):
        positions = [str(p).rstrip(",") for p in positions_raw]
    elif isinstance(positions_raw, str):
        # pw-dump sometimes returns "[ FL FR ]" as a single string.
        positions = [p.rstrip(",") for p in positions_raw.strip("[]").split() if p]
    if positions and len(positions) != count:
        # Keep the count authoritative; drop the mismatched positions.
        positions = []
    channels = ChannelMap(count=count, positions=positions)
    return Node(
        id=node_id,
        kind=kind,
        pipewire_name=pipewire_name,
        description=description,
        target_object=target_object,
        hw=hw,
        channels=channels,
    )


def _build_edges(pw_objects: list[dict[str, Any]], node_by_pwid: dict[int, Node]) -> list[Edge]:
    edges: list[Edge] = []
    for obj in pw_objects:
        if obj.get("type") != _PIPEWIRE_LINK:
            continue
        info = obj.get("info", {})
        src_pwid = info.get("output-node-id")
        tgt_pwid = info.get("input-node-id")
        if src_pwid is None or tgt_pwid is None:
            continue
        src_node = node_by_pwid.get(src_pwid)
        tgt_node = node_by_pwid.get(tgt_pwid)
        if src_node is None or tgt_node is None:
            # Link touches a node kind we don't model (application
            # stream, client). Skip — verify only cares about edges
            # between descriptor-known nodes.
            continue
        # Dedup: at most one edge per (source, target) pair at this
        # phase. Port-level edges are Phase 5+.
        if any(e.source == src_node.id and e.target == tgt_node.id for e in edges):
            continue
        edges.append(Edge(source=src_node.id, target=tgt_node.id))
    return edges


def pw_dump_to_descriptor(pw_dump_json: str | list[dict[str, Any]]) -> TopologyDescriptor:
    """Parse pw-dump output into a ``TopologyDescriptor``.

    Accepts either a JSON string (``run_pw_dump()`` output) or an
    already-parsed list of pw-dump objects (useful for tests).
    """
    if isinstance(pw_dump_json, str):
        pw_objects = json.loads(pw_dump_json)
    else:
        pw_objects = pw_dump_json

    nodes: list[Node] = []
    node_by_pwid: dict[int, Node] = {}
    seen_ids: set[str] = set()
    for obj in pw_objects:
        if obj.get("type") != _PIPEWIRE_NODE:
            continue
        node = _build_node(obj)
        if node is None:
            continue
        # Dedup on descriptor id — pw-dump sometimes exposes multiple
        # PW-level nodes for one logical graph node (capture+playback
        # sides of a loopback, for example). First-wins.
        if node.id in seen_ids:
            continue
        pw_id = obj.get("id")
        if pw_id is None:
            continue
        nodes.append(node)
        node_by_pwid[pw_id] = node
        seen_ids.add(node.id)

    edges = _build_edges(pw_objects, node_by_pwid)
    return TopologyDescriptor(
        schema_version=2,
        description="extracted from live pw-dump",
        nodes=nodes,
        edges=edges,
    )


def descriptor_from_live() -> TopologyDescriptor:
    """Shortcut: run pw-dump and parse its output."""
    return pw_dump_to_descriptor(run_pw_dump())


def descriptor_from_dump_file(path: str | Path) -> TopologyDescriptor:
    """Shortcut: load a captured pw-dump JSON file and parse."""
    return pw_dump_to_descriptor(Path(path).read_text())


def check_tts_broadcast_path(
    descriptor: TopologyDescriptor,
    *,
    source_name: str = "hapax-tts-duck",
    bridge_prefix: str = "hapax-tts-broadcast-",
    target_name: str = "hapax-livestream-tap",
) -> TtsBroadcastPathCheck:
    """Verify TTS reaches the livestream tap in a parsed PipeWire graph.

    The static config can declare the loopback while the live graph is still
    missing one side after deployment/restart. This checks the live shape:
    ``hapax-tts-duck -> hapax-tts-broadcast-* -> hapax-livestream-tap``.
    """
    by_name = {node.pipewire_name: node for node in descriptor.nodes}
    bridge_nodes = [
        node for node in descriptor.nodes if node.pipewire_name.startswith(bridge_prefix)
    ]

    missing_nodes: list[str] = []
    source = by_name.get(source_name)
    if source is None:
        missing_nodes.append(source_name)
    target = by_name.get(target_name)
    if target is None:
        missing_nodes.append(target_name)
    if not bridge_nodes:
        missing_nodes.append(f"{bridge_prefix}*")

    edge_pairs = {(edge.source, edge.target) for edge in descriptor.edges}
    missing_edges: list[str] = []
    if source is not None and bridge_nodes:
        if not any((source.id, bridge.id) in edge_pairs for bridge in bridge_nodes):
            missing_edges.append(f"{source_name} -> {bridge_prefix}*")
    if target is not None and bridge_nodes:
        if not any((bridge.id, target.id) in edge_pairs for bridge in bridge_nodes):
            missing_edges.append(f"{bridge_prefix}* -> {target_name}")

    return TtsBroadcastPathCheck(
        ok=not missing_nodes and not missing_edges,
        missing_nodes=tuple(missing_nodes),
        missing_edges=tuple(missing_edges),
    )


def check_l12_forward_invariant(descriptor: TopologyDescriptor) -> L12ForwardInvariantCheck:
    """Validate the current static L-12 directionality contract.

    This is the CI/static complement to ``scripts/audio-leak-guard.sh``.
    It consumes the canonical ``TopologyDescriptor`` instead of parsing
    conf text directly, so topology drift and the guard stay on the same
    source of truth.
    """
    violations: list[L12ForwardInvariantViolation] = []
    by_id = {node.id: node for node in descriptor.nodes}
    graph = _static_directionality_graph(descriptor)
    ref_to_id = _reference_to_node_id(descriptor)
    edge_pairs = {(edge.source, edge.target) for edge in descriptor.edges}

    for node_id in sorted(_REQUIRED_L12_DIRECTIONALITY_NODES - by_id.keys()):
        violations.append(
            L12ForwardInvariantViolation(
                code="missing_required_node",
                message=f"{node_id} is required by the L-12 directionality contract",
            )
        )

    def node(node_id: str) -> Node | None:
        return by_id.get(node_id)

    def expect_target(node_id: str, expected: str, code: str) -> None:
        n = node(node_id)
        if n is None:
            return
        if n.target_object != expected:
            violations.append(
                L12ForwardInvariantViolation(
                    code=code,
                    message=(f"{node_id} targets {n.target_object!r}; expected {expected!r}"),
                )
            )

    expect_target("role-assistant", "hapax-private", "assistant_target_not_private")
    expect_target(
        "role-notification",
        "hapax-notification-private",
        "notification_target_not_private",
    )
    expect_target("role-multimedia", "hapax-pc-loudnorm", "multimedia_target_not_pc")
    expect_target("role-broadcast", "hapax-voice-fx-capture", "broadcast_target_not_voice_fx")

    for node_id in ("private-sink", "notification-private-sink"):
        private = node(node_id)
        if private is None:
            continue
        if private.target_object is not None or private.params.get("fail_closed") is not True:
            violations.append(
                L12ForwardInvariantViolation(
                    code="private_sink_not_fail_closed",
                    message=(f"{node_id} must be a fail-closed sink with no downstream target"),
                )
            )

    for capture_id, source_id in _PRIVATE_MONITOR_CAPTURE_NODES.items():
        capture = node(capture_id)
        source = node(source_id)
        if capture is None or source is None:
            continue
        if ref_to_id.get(capture.target_object or "") != source_id:
            violations.append(
                L12ForwardInvariantViolation(
                    code="private_monitor_capture_target_not_private_sink",
                    message=(
                        f"{capture_id} targets {capture.target_object!r}; "
                        f"expected {source.pipewire_name!r}"
                    ),
                )
            )
        if capture.params.get("stream.capture.sink") is not True:
            violations.append(
                L12ForwardInvariantViolation(
                    code="private_monitor_capture_not_sink_monitor",
                    message=f"{capture_id} must set stream.capture.sink=true",
                )
            )
        if (source_id, capture_id) not in edge_pairs:
            violations.append(
                L12ForwardInvariantViolation(
                    code="private_monitor_capture_edge_missing",
                    message=f"{source_id} must feed {capture_id}",
                )
            )

    for bridge_id, (capture_id, source_id, endpoint_ids) in _PRIVATE_MONITOR_BRIDGES.items():
        bridge = node(bridge_id)
        # Resolve allowed endpoints. Each entry can be either a single id
        # (legacy schema) or a tuple of allowed alternatives (Option C).
        if isinstance(endpoint_ids, str):
            allowed_endpoint_ids = (endpoint_ids,)
        else:
            allowed_endpoint_ids = endpoint_ids
        endpoints = [n for n in (node(eid) for eid in allowed_endpoint_ids) if n is not None]
        if bridge is None or not endpoints:
            continue
        resolved_target_id = ref_to_id.get(bridge.target_object or "")
        if resolved_target_id not in allowed_endpoint_ids:
            allowed_names = " or ".join(repr(e.pipewire_name) for e in endpoints)
            violations.append(
                L12ForwardInvariantViolation(
                    code="private_monitor_bridge_target_not_allowed_endpoint",
                    message=(
                        f"{bridge_id} targets {bridge.target_object!r}; expected {allowed_names}"
                    ),
                )
            )
        for key, expected in _PRIVATE_MONITOR_FAIL_CLOSED_PARAMS.items():
            if bridge.params.get(key) != expected:
                violations.append(
                    L12ForwardInvariantViolation(
                        code="private_monitor_bridge_not_fail_closed",
                        message=f"{bridge_id} must set {key}={expected!r}",
                    )
                )
        if bridge.params.get("private_monitor_bridge") is not True:
            violations.append(
                L12ForwardInvariantViolation(
                    code="private_monitor_bridge_not_declared",
                    message=f"{bridge_id} must declare private_monitor_bridge=true",
                )
            )
        if (capture_id, bridge_id) not in edge_pairs:
            violations.append(
                L12ForwardInvariantViolation(
                    code="private_monitor_bridge_edge_missing",
                    message=f"{source_id} monitor bridge must connect {capture_id} to {bridge_id}",
                )
            )

    pc_loudnorm = node("pc-loudnorm")
    if pc_loudnorm is not None and pc_loudnorm.params.get("notification_excluded") is not True:
        violations.append(
            L12ForwardInvariantViolation(
                code="pc_loudnorm_allows_notifications",
                message="pc-loudnorm must keep notification_excluded=true",
            )
        )

    l12_return = node("l12-usb-return")
    if l12_return is not None:
        l12_return_refs = {l12_return.id, l12_return.pipewire_name}
        for candidate in descriptor.nodes:
            if _node_targets_any(candidate, l12_return_refs):
                allowed_direction = candidate.params.get("allowed_l12_return_direction")
                if (
                    candidate.id not in _ALLOWED_L12_RETURN_PRODUCERS
                    and allowed_direction not in _ALLOWED_L12_RETURN_DIRECTIONS
                ):
                    violations.append(
                        L12ForwardInvariantViolation(
                            code="unexpected_l12_return_producer",
                            message=(
                                f"{candidate.id} targets L-12 return without an explicit "
                                "allowed-direction contract"
                            ),
                        )
                    )

    capture = node("l12-evilpet-capture")
    if capture is not None:
        capture_positions = str(capture.params.get("capture_positions", ""))
        forbidden_positions = str(capture.params.get("forbidden_capture_positions", ""))
        if capture_positions != "AUX1 AUX3 AUX4 AUX5":
            violations.append(
                L12ForwardInvariantViolation(
                    code="l12_capture_positions_not_narrowed",
                    message="l12-evilpet-capture must bind only AUX1 AUX3 AUX4 AUX5",
                )
            )
        for pos in ("AUX8", "AUX9", "AUX10", "AUX11", "AUX12", "AUX13"):
            if pos not in forbidden_positions.split():
                violations.append(
                    L12ForwardInvariantViolation(
                        code="l12_forbidden_capture_position_missing",
                        message=f"l12-evilpet-capture must forbid {pos}",
                    )
                )

    if not _can_reach(graph, "l12-capture", "livestream-tap"):
        violations.append(
            L12ForwardInvariantViolation(
                code="l12_capture_missing_livestream_forward_path",
                message="L-12 capture must forward through l12-evilpet-capture to livestream-tap",
            )
        )

    if not _can_reach(graph, "role-broadcast", "livestream-tap"):
        violations.append(
            L12ForwardInvariantViolation(
                code="broadcast_role_missing_livestream_forward_path",
                message="role-broadcast must reach voice-fx, TTS loudnorm/duck, and livestream-tap",
            )
        )

    tts_duck = node("tts-duck")
    if tts_duck is not None:
        forward_path = _param_words(tts_duck.params.get("broadcast_forward_path"))
        expected_forward_path = [
            "hapax-tts-broadcast-capture",
            "hapax-tts-broadcast-playback",
            "hapax-livestream-tap",
        ]
        if forward_path != expected_forward_path:
            violations.append(
                L12ForwardInvariantViolation(
                    code="tts_broadcast_forward_path_not_declared",
                    message=(
                        "tts-duck must declare broadcast_forward_path="
                        + " ".join(expected_forward_path)
                    ),
                )
            )
        if not _can_reach(graph, "tts-duck", "livestream-tap"):
            violations.append(
                L12ForwardInvariantViolation(
                    code="tts_l12_missing_livestream_forward_path",
                    message=("tts-duck targets L-12 return but does not also reach livestream-tap"),
                )
            )

    for root in sorted(_PRIVATE_ONLY_ROOTS & by_id.keys()):
        reachable_forbidden = sorted(_reachable_from(graph, root) & _PRIVATE_FORBIDDEN_REACHABILITY)
        if reachable_forbidden:
            violations.append(
                L12ForwardInvariantViolation(
                    code="private_route_reaches_broadcast_path",
                    message=f"{root} can reach forbidden node(s): {', '.join(reachable_forbidden)}",
                )
            )

    return L12ForwardInvariantCheck(
        ok=not violations,
        violations=tuple(violations),
    )


def _node_targets_any(node: Node, refs: set[str]) -> bool:
    if node.target_object in refs:
        return True
    playback_target = node.params.get("playback_target")
    return isinstance(playback_target, str) and playback_target in refs


def _param_words(value: str | int | float | bool | None) -> list[str]:
    if not isinstance(value, str):
        return []
    return [word for word in value.split() if word]


def _static_directionality_graph(descriptor: TopologyDescriptor) -> dict[str, set[str]]:
    """Build a conservative directed graph from descriptor edges and params."""
    by_id = {node.id: node for node in descriptor.nodes}
    ref_to_id = _reference_to_node_id(descriptor)
    graph: dict[str, set[str]] = {node.id: set() for node in descriptor.nodes}

    def add(source: str | None, target: str | None) -> None:
        if source is None or target is None:
            return
        if source not in by_id or target not in by_id:
            return
        graph.setdefault(source, set()).add(target)

    for edge in descriptor.edges:
        add(edge.source, edge.target)

    for node in descriptor.nodes:
        target_id = ref_to_id.get(node.target_object or "")
        if target_id is not None:
            if node.kind == NodeKind.FILTER_CHAIN and node.id.endswith("-capture"):
                add(target_id, node.id)
            else:
                add(node.id, target_id)

        playback_target = node.params.get("playback_target")
        if isinstance(playback_target, str):
            add(node.id, ref_to_id.get(playback_target))

        forward_path = [
            ref_to_id[token]
            for token in _param_words(node.params.get("broadcast_forward_path"))
            if token in ref_to_id
        ]
        if forward_path:
            add(node.id, forward_path[0])
            for source, target in zip(forward_path, forward_path[1:], strict=False):
                add(source, target)

    return graph


def _reference_to_node_id(descriptor: TopologyDescriptor) -> dict[str, str]:
    """Map stable descriptor IDs and PipeWire node names to descriptor IDs."""
    refs: dict[str, str] = {}
    for node in descriptor.nodes:
        refs[node.id] = node.id
        refs[node.pipewire_name] = node.id
        playback_source = node.params.get("playback_source")
        if isinstance(playback_source, str) and playback_source:
            refs[playback_source] = node.id
    return refs


def _reachable_from(graph: dict[str, set[str]], start: str) -> set[str]:
    seen: set[str] = set()
    frontier = list(graph.get(start, ()))
    while frontier:
        current = frontier.pop()
        if current in seen:
            continue
        seen.add(current)
        next_nodes = graph.get(current)
        if next_nodes:
            frontier.extend(next_nodes - seen)
    return seen


def _can_reach(graph: dict[str, set[str]], source: str, target: str) -> bool:
    return target in _reachable_from(graph, source)
