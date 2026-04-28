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
    if name.startswith("hapax-") and "-broadcast-" in name and name.endswith("-playback"):
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
        positions = [str(p) for p in positions_raw]
    elif isinstance(positions_raw, str):
        # pw-dump sometimes returns "[ FL FR ]" as a single string.
        positions = [p for p in positions_raw.strip("[]").split() if p]
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
        schema_version=1,
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
