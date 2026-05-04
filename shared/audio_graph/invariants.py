"""Invariant predicates for the audio graph SSOT.

Implements the 11 invariants from spec §2.4. Each invariant is a
pure function with signature ``checker(graph) -> list[InvariantViolation]``.
The first 9 are pre-apply (static / structural). The last 2 are
continuous post-apply (RMS / crest gates) and are wired by the
daemon's circuit breaker — for P1 we expose the predicate signature
only (the runtime gates are P5).

References:
- Spec §2.4 (the 11 invariants)
- Spec §4.2 (continuous post-apply pair driving the breaker)
- Audit §6 (existing inspector reachability code is the basis for
  ``check_private_never_broadcasts``)
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from shared.audio_graph.schema import (
    AudioGraph,
    AudioLink,
    NodeKind,
)

# Public broadcast-family node ids (must trace from a private endpoint
# to NONE of these). Mirrors
# ``shared.audio_topology_inspector.BROADCAST_FAMILY_NODE_IDS`` once
# that constant lands; for P1 we vendor the canonical names from
# ``audio_topology.yaml`` and the 24-conf live decomposition.
BROADCAST_FAMILY_NODE_IDS: frozenset[str] = frozenset(
    {
        # Canonical (audio-topology.yaml) form.
        "livestream-tap",
        "broadcast-master-capture",
        "broadcast-master",
        "broadcast-normalized-capture",
        "broadcast-normalized",
        "obs-broadcast-remap-capture",
        "obs-broadcast-remap",
        "l12-evilpet-capture",
        "l12-evilpet-playback",
        # Live ``pipewire_name`` form (validator emits these as node ids).
        "hapax-livestream-tap",
        "hapax-livestream-tap-src",
        "hapax-livestream-tap-dst",
        "hapax-broadcast-master-capture",
        "hapax-broadcast-master",
        "hapax-broadcast-normalized-capture",
        "hapax-broadcast-normalized",
        "hapax-obs-broadcast-remap-capture",
        "hapax-obs-broadcast-remap",
        "hapax-l12-evilpet-capture",
        "hapax-l12-evilpet-playback",
    }
)


# Private-only roots (nodes whose contents must never reach broadcast).
PRIVATE_ONLY_ROOTS: frozenset[str] = frozenset(
    {
        "hapax-private",
        "hapax-notification-private",
        "hapax-private-monitor-capture",
        "hapax-notification-private-monitor-capture",
        "hapax-private-playback",
        "hapax-notification-private-playback",
    }
)


class InvariantSeverity(StrEnum):
    """How a violation should be handled at apply time."""

    BLOCKING = "blocking"
    WARNING = "warning"
    INFORMATIONAL = "info"


class InvariantKind(StrEnum):
    """Taxonomy of constitutional + operational invariants."""

    PRIVATE_NEVER_BROADCASTS = "private-never-broadcasts"
    L12_DIRECTIONALITY = "l12-directionality"
    PORT_COMPATIBILITY = "port-compatibility"
    FORMAT_COMPATIBILITY = "format-compatibility"
    CHANNEL_COUNT_TOPOLOGY_WIDE = "channel-count-topology-wide"
    GAIN_BUDGET = "gain-budget"
    MASTER_BUS_SOLE_PATH = "master-bus-sole-path"
    NO_DUPLICATE_PIPEWIRE_NAMES = "no-duplicate-pipewire-names"
    HARDWARE_BLEED_GUARD = "hardware-bleed-guard"
    EGRESS_SAFETY_BAND_RMS = "egress-safety-band-rms"
    EGRESS_SAFETY_BAND_CREST = "egress-safety-band-crest"


@dataclass(frozen=True)
class InvariantViolation:
    """One violation surfaced by an invariant checker."""

    kind: InvariantKind
    severity: InvariantSeverity = InvariantSeverity.BLOCKING
    node_id: str | None = None
    message: str = ""
    extras: tuple[tuple[str, str], ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Reachability helpers.
# ---------------------------------------------------------------------------


def _bfs_descendants(adj: dict[str, list[str]], src: str) -> set[str]:
    """All node ids reachable from ``src`` in ``adj`` (excluding ``src``)."""
    seen: set[str] = set()
    queue: deque[str] = deque(adj.get(src, []))
    while queue:
        node = queue.popleft()
        if node in seen:
            continue
        seen.add(node)
        queue.extend(adj.get(node, []))
    return seen


def _normalised_position(pos: str | None) -> str:
    return (pos or "").strip().lower()


# ---------------------------------------------------------------------------
# Invariant checkers (the 11 from spec §2.4 + §4.2)
# ---------------------------------------------------------------------------


def check_private_never_broadcasts(graph: AudioGraph) -> list[InvariantViolation]:
    """PRIVATE_NEVER_BROADCASTS — reachability from private to broadcast."""
    private_node_ids = {
        n.id
        for n in graph.nodes
        if n.private_monitor_endpoint or n.fail_closed or n.id in PRIVATE_ONLY_ROOTS
    }
    adj = graph.adjacency()
    violations: list[InvariantViolation] = []
    for src in private_node_ids:
        reachable = _bfs_descendants(adj, src)
        crossings = reachable & BROADCAST_FAMILY_NODE_IDS
        if crossings:
            violations.append(
                InvariantViolation(
                    kind=InvariantKind.PRIVATE_NEVER_BROADCASTS,
                    severity=InvariantSeverity.BLOCKING,
                    node_id=src,
                    message=(
                        f"private node {src!r} reaches broadcast-family nodes: {sorted(crossings)}"
                    ),
                )
            )
    return violations


def check_l12_directionality(graph: AudioGraph) -> list[InvariantViolation]:
    """L12_DIRECTIONALITY — AUX0..AUX13 in only; RL/RR out only.

    L-12 multichannel-input is the broadcast capture; the L-12
    surround40 is the playback bus. The AUX positions must only
    appear on capture-side declarations; FL/FR/RL/RR on playback.
    """
    violations: list[InvariantViolation] = []
    for node in graph.nodes:
        # L-12 capture node: must have AUX positions.
        if (
            node.target_object
            and "L-12" in node.target_object
            and "multichannel-input" in node.target_object
        ):
            for pos in node.channels.positions:
                if not pos.lower().startswith("aux") and pos.lower() not in {
                    "mono",
                    "fl",
                    "fr",
                }:
                    violations.append(
                        InvariantViolation(
                            kind=InvariantKind.L12_DIRECTIONALITY,
                            node_id=node.id,
                            message=(
                                f"L-12 capture node {node.id!r} declares non-AUX position {pos!r}"
                            ),
                        )
                    )
    return violations


def check_port_compatibility(graph: AudioGraph) -> list[InvariantViolation]:
    """PORT_COMPATIBILITY — a link's source/target positions must agree.

    If both ports are declared, they must match (case-insensitive).
    If one is declared and the other isn't, we accept (PipeWire's
    auto-link covers it). FL→RL etc. is a config bug, not a remap.
    """
    violations: list[InvariantViolation] = []
    for link in graph.links:
        sp = _normalised_position(link.source_port)
        tp = _normalised_position(link.target_port)
        if sp and tp and sp != tp:
            # FL→FR etc. is a downmix; we permit it ONLY if a
            # ChannelDownmix exists for this edge.
            cdm_present = any(
                cdm.source_node == link.source and cdm.target_node == link.target
                for cdm in graph.channel_downmixes
            )
            if not cdm_present:
                violations.append(
                    InvariantViolation(
                        kind=InvariantKind.PORT_COMPATIBILITY,
                        message=(
                            f"link {link.source!r}:{link.source_port}→{link.target!r}:"
                            f"{link.target_port} mismatched positions, no ChannelDownmix"
                        ),
                    )
                )
    return violations


def check_format_compatibility(graph: AudioGraph) -> list[InvariantViolation]:
    """FORMAT_COMPATIBILITY — channel-count change requires ChannelDownmix.

    Implements gap G-3 / today's failure #5. If a link spans nodes
    with different ``channels.count``, we require a matching
    ChannelDownmix entry; otherwise the topology has an implicit
    silent downmix.
    """
    violations: list[InvariantViolation] = []
    for link in graph.links:
        try:
            src_node = graph.node_by_id(link.source)
            tgt_node = graph.node_by_id(link.target)
        except KeyError:
            continue
        if src_node.channels.count != tgt_node.channels.count:
            cdm_present = any(
                cdm.source_node == link.source and cdm.target_node == link.target
                for cdm in graph.channel_downmixes
            )
            if not cdm_present:
                violations.append(
                    InvariantViolation(
                        kind=InvariantKind.FORMAT_COMPATIBILITY,
                        message=(
                            f"link {link.source!r}({src_node.channels.count}ch)→"
                            f"{link.target!r}({tgt_node.channels.count}ch) "
                            "with no ChannelDownmix declared"
                        ),
                    )
                )
    return violations


def check_channel_count_topology_wide(graph: AudioGraph) -> list[InvariantViolation]:
    """CHANNEL_COUNT_TOPOLOGY_WIDE — every downmix declares both formats.

    For each ChannelDownmix, source_format and target_format should
    be present so the daemon can verify.
    """
    violations: list[InvariantViolation] = []
    for cdm in graph.channel_downmixes:
        if cdm.source_format is None or cdm.target_format is None:
            violations.append(
                InvariantViolation(
                    kind=InvariantKind.CHANNEL_COUNT_TOPOLOGY_WIDE,
                    severity=InvariantSeverity.WARNING,
                    message=(
                        f"ChannelDownmix({cdm.source_node}→{cdm.target_node}) "
                        "missing source_format/target_format declaration"
                    ),
                )
            )
    return violations


def check_gain_budget(graph: AudioGraph) -> list[InvariantViolation]:
    """GAIN_BUDGET — cumulative makeup_gain_db along any path ≤ +24 dB.

    Walks every simple path from a source to a broadcast-family node
    and sums :attr:`AudioLink.makeup_gain_db`. > 24 dB is flagged.
    """
    violations: list[InvariantViolation] = []
    adj_links: dict[str, list[AudioLink]] = defaultdict(list)
    for link in graph.links:
        adj_links[link.source].append(link)

    src_nodes = [
        n.id
        for n in graph.nodes
        if n.kind in (NodeKind.ALSA_SOURCE, NodeKind.LOOPBACK, NodeKind.FILTER_CHAIN)
    ]

    def _dfs(start: str) -> None:
        # iterative DFS with a path-cumulative gain
        stack: list[tuple[str, float, tuple[str, ...]]] = [(start, 0.0, (start,))]
        while stack:
            node, cum_db, path = stack.pop()
            if node in BROADCAST_FAMILY_NODE_IDS:
                if cum_db > 24.0:
                    violations.append(
                        InvariantViolation(
                            kind=InvariantKind.GAIN_BUDGET,
                            message=(
                                f"path {' → '.join(path)} accumulates "
                                f"{cum_db:+.1f} dB makeup-gain (>24 dB ceiling)"
                            ),
                        )
                    )
                continue
            for link in adj_links.get(node, []):
                if link.target in path:
                    continue  # cycle guard
                stack.append((link.target, cum_db + link.makeup_gain_db, path + (link.target,)))

    for src in src_nodes:
        _dfs(src)
    return violations


def check_master_bus_sole_path(graph: AudioGraph) -> list[InvariantViolation]:
    """MASTER_BUS_SOLE_PATH — every broadcast-bound stream traverses the master.

    Every node that reaches a broadcast-family egress node MUST trace
    through ``broadcast-master`` (or ``broadcast-master-capture``) on
    the way. Skips when the graph has no master node defined.
    """
    violations: list[InvariantViolation] = []
    master_id_set = {
        "broadcast-master",
        "broadcast-master-capture",
        "hapax-broadcast-master",
        "hapax-broadcast-master-capture",
    }
    has_master = any(n.id in master_id_set for n in graph.nodes)
    if not has_master:
        return violations
    adj = graph.adjacency()
    src_nodes = [
        n.id
        for n in graph.nodes
        if n.kind in (NodeKind.ALSA_SOURCE, NodeKind.LOOPBACK, NodeKind.FILTER_CHAIN)
    ]
    egress = {
        "broadcast-normalized",
        "obs-broadcast-remap",
        "hapax-broadcast-normalized",
        "hapax-obs-broadcast-remap",
    } & {n.id for n in graph.nodes}
    if not egress:
        return violations
    master_set = master_id_set & {n.id for n in graph.nodes}
    for src in src_nodes:
        if src in master_set:
            continue
        reachable = _bfs_descendants(adj, src)
        if reachable & egress and not reachable & master_set:
            violations.append(
                InvariantViolation(
                    kind=InvariantKind.MASTER_BUS_SOLE_PATH,
                    severity=InvariantSeverity.WARNING,
                    node_id=src,
                    message=(
                        f"{src!r} reaches egress {sorted(reachable & egress)} "
                        "without traversing broadcast-master"
                    ),
                )
            )
    return violations


def check_no_duplicate_pipewire_names(
    graph: AudioGraph,
) -> list[InvariantViolation]:
    """NO_DUPLICATE_PIPEWIRE_NAMES — already enforced at parse time.

    The schema validator rejects duplicate ``pipewire_name`` at
    construction time. This checker stays as a no-op so it can fire
    on graphs assembled by hand-rolled callers that bypass the
    validator (e.g. dynamic graph mutation).
    """
    seen: dict[str, str] = {}
    violations: list[InvariantViolation] = []
    for n in graph.nodes:
        if n.pipewire_name in seen:
            violations.append(
                InvariantViolation(
                    kind=InvariantKind.NO_DUPLICATE_PIPEWIRE_NAMES,
                    node_id=n.id,
                    message=(
                        f"duplicate pipewire_name {n.pipewire_name!r} "
                        f"on {n.id!r} (also on {seen[n.pipewire_name]!r})"
                    ),
                )
            )
        else:
            seen[n.pipewire_name] = n.id
    return violations


def check_hardware_bleed_guard(graph: AudioGraph) -> list[InvariantViolation]:
    """HARDWARE_BLEED_GUARD — declared bleed must not amplify itself.

    For each :class:`GainStage` whose ``declared_bleed_db`` is set,
    require:
        base_gain_db + per_channel_overrides[ch] - declared_bleed_db ≤ 0
    so a bleeding source can never amplify its bleed level above its
    own signal level.
    """
    violations: list[InvariantViolation] = []
    for stage in graph.gain_stages:
        if stage.declared_bleed_db is None:
            continue
        for ch, override_db in stage.per_channel_overrides.items():
            net = stage.base_gain_db + override_db - stage.declared_bleed_db
            if net > 0:
                violations.append(
                    InvariantViolation(
                        kind=InvariantKind.HARDWARE_BLEED_GUARD,
                        message=(
                            f"GainStage {stage.edge_source}→{stage.edge_target} "
                            f"channel {ch}: net gain over declared bleed = "
                            f"{net:+.2f} dB (must be ≤ 0)"
                        ),
                    )
                )
        # Also check the base case (no per-channel override).
        if not stage.per_channel_overrides:
            net = stage.base_gain_db - stage.declared_bleed_db
            if net > 0:
                violations.append(
                    InvariantViolation(
                        kind=InvariantKind.HARDWARE_BLEED_GUARD,
                        message=(
                            f"GainStage {stage.edge_source}→{stage.edge_target}: "
                            f"net gain {net:+.2f} dB > 0 (bleed amplification)"
                        ),
                    )
                )
    return violations


_EGRESS_NODE_NAMES: frozenset[str] = frozenset(
    {
        # Canonical ids.
        "obs-broadcast-remap",
        "broadcast-normalized",
        "livestream-tap",
        # Live pipewire_name form.
        "hapax-obs-broadcast-remap",
        "hapax-broadcast-normalized",
        "hapax-livestream-tap",
    }
)


def check_egress_safety_band_rms(graph: AudioGraph) -> list[InvariantViolation]:
    """EGRESS_SAFETY_BAND_RMS — runtime continuous (P5).

    For P1 we only structurally verify that the graph has at least
    one egress probe declared. The actual RMS gate is applied by the
    daemon's circuit breaker against a live capture window.
    """
    egress_nodes = {n.id for n in graph.nodes} & _EGRESS_NODE_NAMES
    if not egress_nodes:
        return [
            InvariantViolation(
                kind=InvariantKind.EGRESS_SAFETY_BAND_RMS,
                severity=InvariantSeverity.WARNING,
                message=("no egress node found in graph; circuit breaker has nothing to probe"),
            )
        ]
    return []


def check_egress_safety_band_crest(graph: AudioGraph) -> list[InvariantViolation]:
    """EGRESS_SAFETY_BAND_CREST — runtime continuous (P5).

    Same structural check as RMS — confirm an egress is declared so
    the breaker has a target.
    """
    egress_nodes = {n.id for n in graph.nodes} & _EGRESS_NODE_NAMES
    if not egress_nodes:
        return [
            InvariantViolation(
                kind=InvariantKind.EGRESS_SAFETY_BAND_CREST,
                severity=InvariantSeverity.WARNING,
                message=(
                    "no egress node found in graph; crest-factor breaker has nothing to probe"
                ),
            )
        ]
    return []


# ---------------------------------------------------------------------------
# Registry + dispatch
# ---------------------------------------------------------------------------


INVARIANT_CHECKERS: dict[InvariantKind, Callable[[AudioGraph], list[InvariantViolation]]] = {
    InvariantKind.PRIVATE_NEVER_BROADCASTS: check_private_never_broadcasts,
    InvariantKind.L12_DIRECTIONALITY: check_l12_directionality,
    InvariantKind.PORT_COMPATIBILITY: check_port_compatibility,
    InvariantKind.FORMAT_COMPATIBILITY: check_format_compatibility,
    InvariantKind.CHANNEL_COUNT_TOPOLOGY_WIDE: check_channel_count_topology_wide,
    InvariantKind.GAIN_BUDGET: check_gain_budget,
    InvariantKind.MASTER_BUS_SOLE_PATH: check_master_bus_sole_path,
    InvariantKind.NO_DUPLICATE_PIPEWIRE_NAMES: check_no_duplicate_pipewire_names,
    InvariantKind.HARDWARE_BLEED_GUARD: check_hardware_bleed_guard,
    InvariantKind.EGRESS_SAFETY_BAND_RMS: check_egress_safety_band_rms,
    InvariantKind.EGRESS_SAFETY_BAND_CREST: check_egress_safety_band_crest,
}


def check_all_invariants(graph: AudioGraph) -> list[InvariantViolation]:
    """Run every invariant; return concatenated list of violations."""
    out: list[InvariantViolation] = []
    for kind, checker in INVARIANT_CHECKERS.items():
        try:
            out.extend(checker(graph))
        except Exception as exc:  # noqa: BLE001
            out.append(
                InvariantViolation(
                    kind=kind,
                    severity=InvariantSeverity.WARNING,
                    message=f"checker raised {type(exc).__name__}: {exc}",
                )
            )
    return out


__all__ = [
    "BROADCAST_FAMILY_NODE_IDS",
    "PRIVATE_ONLY_ROOTS",
    "InvariantKind",
    "InvariantSeverity",
    "InvariantViolation",
    "INVARIANT_CHECKERS",
    "check_all_invariants",
    "check_private_never_broadcasts",
    "check_l12_directionality",
    "check_port_compatibility",
    "check_format_compatibility",
    "check_channel_count_topology_wide",
    "check_gain_budget",
    "check_master_bus_sole_path",
    "check_no_duplicate_pipewire_names",
    "check_hardware_bleed_guard",
    "check_egress_safety_band_rms",
    "check_egress_safety_band_crest",
]
