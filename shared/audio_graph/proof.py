"""Port-level safety proofs for the mk5 audio graph."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from shared.audio_graph.model import (
    AudioEdge,
    ExposureDomain,
    ModulationPath,
    PortAudioGraph,
    PortDirection,
)


class ProofSeverity(StrEnum):
    """Proof result severity."""

    BLOCKING = "blocking"
    WARNING = "warning"


class ProofCode(StrEnum):
    """Phase 1+2 proof obligations."""

    PF1_ALLOWLIST_ROUTE_CLASS = "PF1_ALLOWLIST_ROUTE_CLASS"
    PF2_WIREPLUMBER_DENY_COVERAGE = "PF2_WIREPLUMBER_DENY_COVERAGE"
    PF3_LEAK_GUARD_MK5_PATTERNS = "PF3_LEAK_GUARD_MK5_PATTERNS"
    PF4_RECONCILER_FORBIDDEN_LAST = "PF4_RECONCILER_FORBIDDEN_LAST"
    PF5_NULL_SINK_FAIL_CLOSED = "PF5_NULL_SINK_FAIL_CLOSED"
    PF6_BROADCAST_ROLE_ONLY_TO_VOICE_FX = "PF6_BROADCAST_ROLE_ONLY_TO_VOICE_FX"
    PF7_DEFAULT_SINK_FAIL_CLOSED = "PF7_DEFAULT_SINK_FAIL_CLOSED"
    PF8_CAPTURE_PIN = "PF8_CAPTURE_PIN"
    PF9_MONITOR_PIN = "PF9_MONITOR_PIN"
    PF10_PRIVACY_REACHABILITY = "PF10_PRIVACY_REACHABILITY"
    PF11_GAIN_BUDGET = "PF11_GAIN_BUDGET"
    PF12_KNOWN_LEAK_VECTORS = "PF12_KNOWN_LEAK_VECTORS"
    LIMITER_OBS_PATH = "LIMITER_OBS_PATH"
    NEVER_DROP_SPEECH = "NEVER_DROP_SPEECH"
    NEVER_DRY_NORMAL_STATE = "NEVER_DRY_NORMAL_STATE"
    DESIRED_FORBIDDEN_OVERLAP = "DESIRED_FORBIDDEN_OVERLAP"
    PLUGIN_CONTROL_RANGE = "PLUGIN_CONTROL_RANGE"


class ProofViolation(BaseModel):
    """One proof violation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: ProofCode
    severity: ProofSeverity = ProofSeverity.BLOCKING
    message: str
    source: str | None = None
    target: str | None = None
    path: list[str] = Field(default_factory=list)


class ProofReport(BaseModel):
    """Output of all proof checks."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    violations: list[ProofViolation] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(v.severity == ProofSeverity.BLOCKING for v in self.violations)

    def blocking(self) -> list[ProofViolation]:
        return [v for v in self.violations if v.severity == ProofSeverity.BLOCKING]


@dataclass(frozen=True)
class PortGraph:
    """Compiled port graph used by the proof engine."""

    adjacency: dict[str, list[str]] = field(default_factory=dict)
    edge_gain: dict[tuple[str, str], float] = field(default_factory=dict)


PUBLIC_DOMAINS: frozenset[ExposureDomain] = frozenset(
    {
        ExposureDomain.BROADCAST,
        ExposureDomain.BROADCAST_PROCESSOR,
        ExposureDomain.BROADCAST_EGRESS,
        ExposureDomain.BROADCAST_MONITOR,
    }
)

PRIVATE_ROOT_DOMAINS: frozenset[ExposureDomain] = frozenset(
    {
        ExposureDomain.PRIVATE,
        ExposureDomain.NOTIFICATION,
        ExposureDomain.QUARANTINE,
        ExposureDomain.UNKNOWN,
        ExposureDomain.DISABLED,
        ExposureDomain.FAILED,
        ExposureDomain.HARDWARE_OPAQUE,
    }
)


def build_port_graph(graph: PortAudioGraph) -> PortGraph:
    """Build adjacency from internal + desired edges."""
    ports = graph.port_refs()
    adjacency: dict[str, list[str]] = {ref: [] for ref in ports}
    edge_gain: dict[tuple[str, str], float] = {}
    for edge in graph.all_edges():
        adjacency.setdefault(edge.source, []).append(edge.target)
        edge_gain[(edge.source, edge.target)] = edge.gain_db
    return PortGraph(adjacency=adjacency, edge_gain=edge_gain)


def _shortest_path(port_graph: PortGraph, start: str, targets: set[str]) -> list[str] | None:
    queue: deque[tuple[str, list[str]]] = deque([(start, [start])])
    seen: set[str] = set()
    while queue:
        node, path = queue.popleft()
        if node in seen:
            continue
        seen.add(node)
        if node in targets:
            return path
        for next_node in port_graph.adjacency.get(node, []):
            if next_node not in seen:
                queue.append((next_node, [*path, next_node]))
    return None


def _simple_paths_to_targets(
    port_graph: PortGraph,
    start: str,
    targets: set[str],
) -> list[list[str]]:
    max_depth = len(port_graph.adjacency) + 1
    queue: deque[tuple[str, list[str]]] = deque([(start, [start])])
    paths: list[list[str]] = []
    while queue:
        node, path = queue.popleft()
        if node in targets:
            paths.append(path)
            continue
        if len(path) >= max_depth:
            continue
        for next_node in sorted(port_graph.adjacency.get(node, [])):
            if next_node not in path:
                queue.append((next_node, [*path, next_node]))
    return paths


def _path_gain_db(port_graph: PortGraph, path: list[str]) -> float:
    total = 0.0
    for src, dst in zip(path, path[1:], strict=False):
        total += port_graph.edge_gain.get((src, dst), 0.0)
    return total


def _ports_with_domains(
    graph: PortAudioGraph, domains: frozenset[ExposureDomain] | set[ExposureDomain]
) -> set[str]:
    ports = graph.ports_by_ref()
    return {ref for ref, port in ports.items() if port.exposure in domains}


def _links_by_key(edges: list[AudioEdge]) -> dict[str, AudioEdge]:
    return {edge.key: edge for edge in edges}


def protected_public_targets(graph: PortAudioGraph) -> set[str]:
    """Ports covered by generated pre-link deny policy."""
    return {
        ref
        for ref, port in graph.ports_by_ref().items()
        if graph.fence.protected_target_tag in port.tags
    }


def guarded_source_ports(graph: PortAudioGraph) -> set[str]:
    """Ports that fail closed away from protected public targets."""
    return {
        ref
        for ref, port in graph.ports_by_ref().items()
        if port.exposure in set(graph.fence.forbidden_from_domains)
        and port.direction in {PortDirection.OUTPUT, PortDirection.MONITOR, PortDirection.DUPLEX}
    }


def generated_forbidden_edges(graph: PortAudioGraph) -> list[AudioEdge]:
    """Generate domain-matrix forbidden links for the reconciler/WP deny plane."""
    return [
        AudioEdge(source=src, target=dst, reason="generated-domain-fence")
        for src in sorted(guarded_source_ports(graph))
        for dst in sorted(protected_public_targets(graph))
        if src != dst
    ]


def check_desired_forbidden_overlap(graph: PortAudioGraph) -> list[ProofViolation]:
    desired = set(_links_by_key(graph.desired_links))
    forbidden = set(_links_by_key([*graph.forbidden_links, *generated_forbidden_edges(graph)])) | {
        edge.key for edge in graph.fence.known_blocked_links
    }
    overlap = sorted(desired & forbidden)
    return (
        [
            ProofViolation(
                code=ProofCode.DESIRED_FORBIDDEN_OVERLAP,
                message=f"desired links overlap forbidden links: {overlap}",
            )
        ]
        if overlap
        else []
    )


def check_allowlist_route_class(graph: PortAudioGraph) -> list[ProofViolation]:
    ports = graph.ports_by_ref()
    violations: list[ProofViolation] = []
    for edge in graph.desired_links:
        src = ports[edge.source]
        dst = ports[edge.target]
        if dst.exposure in PUBLIC_DOMAINS and src.exposure not in PUBLIC_DOMAINS:
            violations.append(
                ProofViolation(
                    code=ProofCode.PF1_ALLOWLIST_ROUTE_CLASS,
                    message=(
                        f"{edge.source} ({src.exposure}) may not feed "
                        f"{edge.target} ({dst.exposure})"
                    ),
                    source=edge.source,
                    target=edge.target,
                )
            )
    for source_id, source in graph.sources.items():
        if source.exposure == ExposureDomain.BROADCAST and not source.broadcast_eligible:
            violations.append(
                ProofViolation(
                    code=ProofCode.PF1_ALLOWLIST_ROUTE_CLASS,
                    message=f"broadcast source {source_id!r} is not broadcast_eligible",
                    source=source.source_port,
                )
            )
        if source.exposure == ExposureDomain.BROADCAST and not source.authority_case:
            violations.append(
                ProofViolation(
                    code=ProofCode.PF1_ALLOWLIST_ROUTE_CLASS,
                    message=f"broadcast source {source_id!r} is missing authority_case",
                    source=source.source_port,
                )
            )
        if source.rights_required and not source.provenance_refs:
            violations.append(
                ProofViolation(
                    code=ProofCode.PF1_ALLOWLIST_ROUTE_CLASS,
                    message=f"rights-required source {source_id!r} lacks provenance_refs",
                    source=source.source_port,
                )
            )
    return violations


def check_privacy_reachability(
    graph: PortAudioGraph, port_graph: PortGraph
) -> list[ProofViolation]:
    private_roots = _ports_with_domains(graph, PRIVATE_ROOT_DOMAINS)
    forbidden_targets = _ports_with_domains(
        graph, set(graph.fence.forbidden_to_domains) | PUBLIC_DOMAINS
    )
    violations: list[ProofViolation] = []
    for root in sorted(private_roots):
        path = _shortest_path(port_graph, root, forbidden_targets)
        if path:
            violations.append(
                ProofViolation(
                    code=ProofCode.PF10_PRIVACY_REACHABILITY,
                    message=f"non-public root {root} reaches public target {path[-1]}",
                    source=root,
                    target=path[-1],
                    path=path,
                )
            )
    return violations


def check_wireplumber_deny_coverage(graph: PortAudioGraph) -> list[ProofViolation]:
    protected_targets = protected_public_targets(graph)
    if not protected_targets:
        return [
            ProofViolation(
                code=ProofCode.PF2_WIREPLUMBER_DENY_COVERAGE,
                message="no protected public targets declared for WirePlumber deny generation",
            )
        ]
    guarded_sources = guarded_source_ports(graph)
    forbidden = set(_links_by_key([*graph.forbidden_links, *generated_forbidden_edges(graph)])) | {
        edge.key for edge in graph.fence.known_blocked_links
    }
    missing: list[str] = []
    for src in sorted(guarded_sources):
        for dst in sorted(protected_targets):
            if f"{src}|{dst}" not in forbidden:
                missing.append(f"{src}|{dst}")
    if missing:
        shown = missing[:8]
        suffix = "" if len(missing) <= 8 else f" (+{len(missing) - 8} more)"
        return [
            ProofViolation(
                code=ProofCode.PF2_WIREPLUMBER_DENY_COVERAGE,
                message=f"missing generated forbidden coverage: {shown}{suffix}",
            )
        ]
    return []


def check_layer_c_patterns(graph: PortAudioGraph) -> list[ProofViolation]:
    required = ("playback_AUX2", "playback_AUX3", "hapax-voice-wet")
    missing = [
        token
        for token in required
        if not any(token in pattern for pattern in graph.fence.layer_c_forbidden_target_patterns)
    ]
    return (
        [
            ProofViolation(
                code=ProofCode.PF3_LEAK_GUARD_MK5_PATTERNS,
                message=f"layer-C leak guard patterns missing mk5 tokens: {missing}",
            )
        ]
        if missing
        else []
    )


def check_reconciler_contract(graph: PortAudioGraph) -> list[ProofViolation]:
    if graph.reconciler.forbidden_runs_last:
        return []
    return [
        ProofViolation(
            code=ProofCode.PF4_RECONCILER_FORBIDDEN_LAST,
            message="reconciler must enforce forbidden links after desired links",
        )
    ]


def check_private_fail_closed(graph: PortAudioGraph) -> list[ProofViolation]:
    violations: list[ProofViolation] = []
    for source_id, source in graph.sources.items():
        if source.exposure in {ExposureDomain.PRIVATE, ExposureDomain.NOTIFICATION}:
            if source.default_sink_allowed:
                violations.append(
                    ProofViolation(
                        code=ProofCode.PF5_NULL_SINK_FAIL_CLOSED,
                        message=f"private source {source_id!r} allows default sink fallback",
                        source=source.source_port,
                    )
                )
            bus = graph.buses[source.output_bus]
            if bus.exposure not in {ExposureDomain.PRIVATE, ExposureDomain.NOTIFICATION}:
                violations.append(
                    ProofViolation(
                        code=ProofCode.PF5_NULL_SINK_FAIL_CLOSED,
                        message=f"private source {source_id!r} outputs to {bus.exposure}",
                        source=source.source_port,
                    )
                )
    return violations


def check_broadcast_role_only_to_voice_fx(graph: PortAudioGraph) -> list[ProofViolation]:
    violations: list[ProofViolation] = []
    for edge in graph.desired_links:
        if "hapax-voice-fx-capture" not in edge.target:
            continue
        source_ids = [
            source_id
            for source_id, source in graph.sources.items()
            if source.source_port == edge.source
        ]
        if source_ids and all(
            graph.sources[source_id].role != "broadcast_voice" for source_id in source_ids
        ):
            violations.append(
                ProofViolation(
                    code=ProofCode.PF6_BROADCAST_ROLE_ONLY_TO_VOICE_FX,
                    message=f"non-broadcast voice source feeds voice-fx: {edge.key}",
                    source=edge.source,
                    target=edge.target,
                )
            )
    return violations


def check_default_sink_fail_closed(graph: PortAudioGraph) -> list[ProofViolation]:
    violations: list[ProofViolation] = []
    if graph.fence.default_sink != "hapax-pc-loudnorm-playback":
        violations.append(
            ProofViolation(
                code=ProofCode.PF7_DEFAULT_SINK_FAIL_CLOSED,
                message=(
                    "default sink must be hapax-pc-loudnorm-playback, "
                    f"got {graph.fence.default_sink}"
                ),
            )
        )
    for ref, port in graph.ports_by_ref().items():
        if port.default_sink_eligible and graph.fence.default_sink not in ref:
            violations.append(
                ProofViolation(
                    code=ProofCode.PF7_DEFAULT_SINK_FAIL_CLOSED,
                    message=f"physical/non-quarantine port is default-sink eligible: {ref}",
                    source=ref,
                )
            )
    return violations


def check_capture_pin(graph: PortAudioGraph) -> list[ProofViolation]:
    violations: list[ProofViolation] = []
    for ref, port in graph.ports_by_ref().items():
        if port.direction != PortDirection.INPUT or "capture_pin_required" not in port.tags:
            continue
        if port.autoconnect or not port.target_object_pinned or not port.dont_reconnect:
            violations.append(
                ProofViolation(
                    code=ProofCode.PF8_CAPTURE_PIN,
                    message=f"capture/input port is not pinned fail-closed: {ref}",
                    source=ref,
                )
            )
    return violations


def check_monitor_pin(graph: PortAudioGraph) -> list[ProofViolation]:
    violations: list[ProofViolation] = []
    for ref, port in graph.ports_by_ref().items():
        if not port.monitor_port:
            continue
        if port.autoconnect or not port.dont_reconnect or not port.dont_move:
            violations.append(
                ProofViolation(
                    code=ProofCode.PF9_MONITOR_PIN,
                    message=f"monitor port is not pinned: {ref}",
                    source=ref,
                )
            )
    return violations


def check_gain_budget(graph: PortAudioGraph, port_graph: PortGraph) -> list[ProofViolation]:
    public_targets = _ports_with_domains(
        graph, {ExposureDomain.BROADCAST_EGRESS, ExposureDomain.BROADCAST_MONITOR}
    )
    violations: list[ProofViolation] = []
    for root in sorted(graph.port_refs()):
        for path in _simple_paths_to_targets(port_graph, root, public_targets):
            gain = _path_gain_db(port_graph, path)
            if gain > graph.fence.gain_budget_ceiling_db:
                violations.append(
                    ProofViolation(
                        code=ProofCode.PF11_GAIN_BUDGET,
                        message=(
                            f"path {' -> '.join(path)} accumulates {gain:+.1f} dB "
                            f"(>{graph.fence.gain_budget_ceiling_db:+.1f} dB)"
                        ),
                        source=root,
                        target=path[-1],
                        path=path,
                    )
                )
    return violations


def check_known_leak_vectors(graph: PortAudioGraph) -> list[ProofViolation]:
    desired = set(_links_by_key(graph.desired_links))
    forbidden = set(_links_by_key([*graph.forbidden_links, *generated_forbidden_edges(graph)])) | {
        edge.key for edge in graph.fence.known_blocked_links
    }
    violations: list[ProofViolation] = []
    for edge in graph.fence.known_blocked_links:
        if edge.key in desired:
            violations.append(
                ProofViolation(
                    code=ProofCode.PF12_KNOWN_LEAK_VECTORS,
                    message=f"known leak vector is desired: {edge.key}",
                    source=edge.source,
                    target=edge.target,
                )
            )
        if edge.key not in forbidden:
            violations.append(
                ProofViolation(
                    code=ProofCode.PF12_KNOWN_LEAK_VECTORS,
                    message=f"known leak vector lacks forbidden coverage: {edge.key}",
                    source=edge.source,
                    target=edge.target,
                )
            )
    if graph.fence.m8_voice_wet_block_required:
        has_m8_block = any(
            "m8" in edge.source and "hapax-voice-wet" in edge.target
            for edge in graph.fence.known_blocked_links
        )
        if not has_m8_block:
            violations.append(
                ProofViolation(
                    code=ProofCode.PF12_KNOWN_LEAK_VECTORS,
                    message="M8 -> hapax-voice-wet known blocked link is not declared",
                )
            )
    return violations


def check_limiter_obs_path(graph: PortAudioGraph, port_graph: PortGraph) -> list[ProofViolation]:
    ports = graph.port_refs()
    normalized_node = graph.nodes.get("hapax-broadcast-normalized")
    if (
        normalized_node is None
        or "fast_lookahead_limiter_1913" not in normalized_node.required_effects
    ):
        return [
            ProofViolation(
                code=ProofCode.LIMITER_OBS_PATH,
                message="hapax-broadcast-normalized must declare fast_lookahead_limiter_1913",
            )
        ]
    allowed_obs_sources = set(graph.fence.obs_allowed_sources)
    if "hapax-obs-broadcast-remap:capture_FL" not in ports:
        return [
            ProofViolation(
                code=ProofCode.LIMITER_OBS_PATH,
                message="stable OBS remap capture port is missing",
            )
        ]
    if "hapax-obs-broadcast-remap" not in allowed_obs_sources:
        return [
            ProofViolation(
                code=ProofCode.LIMITER_OBS_PATH,
                message="OBS allowed sources must include hapax-obs-broadcast-remap",
            )
        ]

    starts = {
        "hapax-livestream-tap:monitor_FL",
        "hapax-livestream-tap:monitor_FR",
    } & ports
    targets = {
        "hapax-obs-broadcast-remap:capture_FL",
        "hapax-obs-broadcast-remap:capture_FR",
    } & ports
    normalized_ports = {ref for ref in ports if ref.startswith("hapax-broadcast-normalized:")}
    violations: list[ProofViolation] = []
    for start in starts:
        paths = _simple_paths_to_targets(port_graph, start, targets)
        if not paths:
            violations.append(
                ProofViolation(
                    code=ProofCode.LIMITER_OBS_PATH,
                    message=f"{start} does not reach OBS remap",
                    source=start,
                )
            )
            continue
        for path in paths:
            if any(port in normalized_ports for port in path):
                continue
            violations.append(
                ProofViolation(
                    code=ProofCode.LIMITER_OBS_PATH,
                    message=f"OBS path bypasses hapax-broadcast-normalized: {path}",
                    source=start,
                    target=path[-1],
                    path=path,
                )
            )
            break
    return violations


def check_never_drop_speech(graph: PortAudioGraph, port_graph: PortGraph) -> list[ProofViolation]:
    public_targets = _ports_with_domains(graph, {ExposureDomain.BROADCAST_EGRESS})
    violations: list[ProofViolation] = []
    for source_id, source in graph.sources.items():
        if not source.never_drop:
            continue
        if not source.dry_safe:
            violations.append(
                ProofViolation(
                    code=ProofCode.NEVER_DROP_SPEECH,
                    message=f"never-drop source {source_id!r} lacks dry_safe rail",
                    source=source.source_port,
                )
            )
        path = _shortest_path(port_graph, source.source_port, public_targets)
        if not path:
            violations.append(
                ProofViolation(
                    code=ProofCode.NEVER_DROP_SPEECH,
                    message=f"never-drop source {source_id!r} does not reach broadcast egress",
                    source=source.source_port,
                )
            )
    return violations


def check_never_dry(graph: PortAudioGraph) -> list[ProofViolation]:
    violations: list[ProofViolation] = []
    for source_id, source in graph.sources.items():
        if not source.active or source.exposure in {
            ExposureDomain.QUARANTINE,
            ExposureDomain.DISABLED,
            ExposureDomain.HARDWARE_OPAQUE,
        }:
            continue
        if source.modulation == ModulationPath.DRY:
            if source.dry_allowed and source.never_drop:
                continue
            violations.append(
                ProofViolation(
                    code=ProofCode.NEVER_DRY_NORMAL_STATE,
                    message=f"source {source_id!r} is raw dry without operator dry exemption",
                    source=source.source_port,
                )
            )
        if source.modulation == ModulationPath.SOFTWARE_WET:
            profile = graph.wet_profiles[source.wet_profile or ""]
            if profile.wet_mix_min <= 0.0 or profile.wet_mix_default <= 0.0:
                violations.append(
                    ProofViolation(
                        code=ProofCode.NEVER_DRY_NORMAL_STATE,
                        message=f"source {source_id!r} wet profile can be fully dry",
                        source=source.source_port,
                    )
                )
        if source.modulation == ModulationPath.HARDWARE_CHARACTER:
            insert = graph.hardware_inserts[source.hardware_insert or ""]
            if not insert.enabled_by_default and source.active:
                violations.append(
                    ProofViolation(
                        code=ProofCode.NEVER_DRY_NORMAL_STATE,
                        message=f"active hardware source {source_id!r} uses disabled insert",
                        source=source.source_port,
                    )
                )
    return violations


def check_plugin_control_ranges(graph: PortAudioGraph) -> list[ProofViolation]:
    violations: list[ProofViolation] = []
    for profile_id, profile in graph.wet_profiles.items():
        for control in profile.controls:
            if control.default < control.min or control.default > control.max:
                violations.append(
                    ProofViolation(
                        code=ProofCode.PLUGIN_CONTROL_RANGE,
                        message=(
                            f"{profile_id}.{control.plugin}:{control.control} default "
                            f"{control.default} outside [{control.min}, {control.max}]"
                        ),
                    )
                )
    return violations


def run_all_proofs(graph: PortAudioGraph) -> ProofReport:
    """Run all Phase 1+2 proof obligations."""
    port_graph = build_port_graph(graph)
    violations: list[ProofViolation] = []
    violations.extend(check_desired_forbidden_overlap(graph))
    violations.extend(check_allowlist_route_class(graph))
    violations.extend(check_wireplumber_deny_coverage(graph))
    violations.extend(check_layer_c_patterns(graph))
    violations.extend(check_reconciler_contract(graph))
    violations.extend(check_private_fail_closed(graph))
    violations.extend(check_broadcast_role_only_to_voice_fx(graph))
    violations.extend(check_default_sink_fail_closed(graph))
    violations.extend(check_capture_pin(graph))
    violations.extend(check_monitor_pin(graph))
    violations.extend(check_privacy_reachability(graph, port_graph))
    violations.extend(check_gain_budget(graph, port_graph))
    violations.extend(check_known_leak_vectors(graph))
    violations.extend(check_limiter_obs_path(graph, port_graph))
    violations.extend(check_never_drop_speech(graph, port_graph))
    violations.extend(check_never_dry(graph))
    violations.extend(check_plugin_control_ranges(graph))
    return ProofReport(violations=violations)


__all__ = [
    "PortGraph",
    "ProofCode",
    "ProofReport",
    "ProofSeverity",
    "ProofViolation",
    "build_port_graph",
    "generated_forbidden_edges",
    "guarded_source_ports",
    "protected_public_targets",
    "run_all_proofs",
]
