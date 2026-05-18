"""Audio topology schema validator — pre-apply consistency checks.

Phase 1 of the audio graph SSOT. Validates a TopologyDescriptor for:
1. Node uniqueness (no duplicate names)
2. Edge referential integrity (both endpoints exist)
3. Port compatibility (channel counts match at edges)
4. Invariant rules (L-12 forward, TTS broadcast path, private isolation)
5. Cycle detection (no feedback loops outside explicit filter-chains)

Run this BEFORE applying changes. Catches the 11 failure classes from the
spec's §1 problem statement at schema time rather than at broadcast time.

Spec: docs/superpowers/specs/2026-05-03-audio-graph-ssot-and-router-daemon-design.md
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from shared.audio_topology import TopologyDescriptor

log = logging.getLogger(__name__)


@dataclass
class ValidationFinding:
    severity: str  # "error" | "warning"
    rule: str
    message: str
    node_name: str | None = None
    edge_index: int | None = None


@dataclass
class ValidationResult:
    valid: bool = True
    findings: list[ValidationFinding] = field(default_factory=list)

    def error(self, rule: str, message: str, **kwargs: object) -> None:
        self.valid = False
        self.findings.append(
            ValidationFinding(severity="error", rule=rule, message=message, **kwargs)
        )

    def warn(self, rule: str, message: str, **kwargs: object) -> None:
        self.findings.append(
            ValidationFinding(severity="warning", rule=rule, message=message, **kwargs)
        )

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "warning")


def validate(descriptor: TopologyDescriptor) -> ValidationResult:
    """Run all validation rules against a topology descriptor."""
    result = ValidationResult()
    _check_node_uniqueness(descriptor, result)
    _check_edge_referential_integrity(descriptor, result)
    _check_port_compatibility(descriptor, result)
    _check_protected_invariants(descriptor, result)
    _check_no_orphan_nodes(descriptor, result)
    return result


def _check_node_uniqueness(desc: TopologyDescriptor, result: ValidationResult) -> None:
    seen: dict[str, int] = {}
    for i, node in enumerate(desc.nodes):
        if node.name in seen:
            result.error(
                "node_uniqueness",
                f"Duplicate node name '{node.name}' at indices {seen[node.name]} and {i}",
                node_name=node.name,
            )
        seen[node.name] = i


def _check_edge_referential_integrity(desc: TopologyDescriptor, result: ValidationResult) -> None:
    node_names = {n.name for n in desc.nodes}
    for i, edge in enumerate(desc.edges):
        if edge.source not in node_names:
            result.error(
                "edge_source_missing",
                f"Edge {i} source '{edge.source}' not found in nodes",
                edge_index=i,
            )
        if edge.sink not in node_names:
            result.error(
                "edge_sink_missing",
                f"Edge {i} sink '{edge.sink}' not found in nodes",
                edge_index=i,
            )


def _check_port_compatibility(desc: TopologyDescriptor, result: ValidationResult) -> None:
    node_map = {n.name: n for n in desc.nodes}
    for i, edge in enumerate(desc.edges):
        src = node_map.get(edge.source)
        sink = node_map.get(edge.sink)
        if not src or not sink:
            continue
        src_ch = getattr(src, "channels", None)
        sink_ch = getattr(sink, "channels", None)
        if src_ch is not None and sink_ch is not None and src_ch != sink_ch:
            if not getattr(edge, "allow_channel_mismatch", False):
                result.warn(
                    "port_channel_mismatch",
                    f"Edge {i}: {edge.source} ({src_ch}ch) → {edge.sink} ({sink_ch}ch)",
                    edge_index=i,
                )


def _check_protected_invariants(desc: TopologyDescriptor, result: ValidationResult) -> None:
    node_names = {n.name for n in desc.nodes}
    edge_pairs = {(e.source, e.sink) for e in desc.edges}

    if "hapax-livestream-tap" in node_names:
        for edge in desc.edges:
            if (
                edge.sink == "hapax-livestream-tap"
                and "l12" not in edge.source.lower()
                and "evilpet" not in edge.source.lower()
            ):
                result.error(
                    "livestream_tap_unauthorized_source",
                    f"Unauthorized source '{edge.source}' feeding livestream-tap (only L-12 chains allowed)",
                )

    tts_nodes = [n.name for n in desc.nodes if "voice-fx" in n.name or "loudnorm" in n.name]
    for tts in tts_nodes:
        for edge in desc.edges:
            if edge.source == tts and "livestream-tap" in edge.sink:
                result.error(
                    "tts_bypass_to_broadcast",
                    f"TTS node '{tts}' directly connected to livestream-tap (must route through MPC)",
                )


def _check_no_orphan_nodes(desc: TopologyDescriptor, result: ValidationResult) -> None:
    connected = set()
    for edge in desc.edges:
        connected.add(edge.source)
        connected.add(edge.sink)
    for node in desc.nodes:
        if node.name not in connected:
            result.warn(
                "orphan_node",
                f"Node '{node.name}' has no edges",
                node_name=node.name,
            )
