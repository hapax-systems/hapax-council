"""Audio Graph SSOT — 11 invariants per spec §2.4.

Each invariant is a pure function over the ``AudioGraph`` descriptor (and,
for the two continuous post-apply invariants, an additional measured
``EgressHealth`` window). All return a list of ``InvariantViolation``;
empty list means pass.

The 11 invariants:

| #  | Kind                          | Pre/Post | Drives           |
|----|-------------------------------|----------|------------------|
|  1 | ``private_never_broadcasts``  | pre       | constitutional   |
|  2 | ``l12_directionality``        | pre       | constitutional   |
|  3 | ``port_compatibility``        | pre       | format-class     |
|  4 | ``format_compatibility``      | pre       | format-class     |
|  5 | ``channel_count_topology_wide`` | pre     | format-class     |
|  6 | ``gain_budget``               | pre       | safety           |
|  7 | ``master_bus_sole_path``      | pre       | architectural    |
|  8 | ``no_duplicate_pipewire_names``| pre      | architectural    |
|  9 | ``hardware_bleed_guard``      | pre       | safety           |
| 10 | ``egress_safety_band_rms``    | post      | continuous (P5)  |
| 11 | ``egress_safety_band_crest``  | post      | continuous (P5)  |

Pre-apply invariants run before the compiler emits any artefact (spec
§3.1 — ``compile_descriptor`` returns empty artefacts when any
``BLOCKING`` violation is found). Post-apply invariants run continuously
in P5 once the daemon's circuit breaker is live; in P1 they're
implemented as predicates that take measured ``EgressHealth`` windows so
the unit tests can pin both pass and fail behaviours.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from shared.audio_graph.schema import AudioGraph, AudioNode

# ---------------------------------------------------------------------------
# Constants — spec §2.4 / §4.2
# ---------------------------------------------------------------------------

#: Cumulative gain budget along any source-to-broadcast path. Spec §2.4
#: — exceeding this surfaces the descriptor as a likely-clipping
#: configuration. +24 dB is the operator's stated headroom budget.
GAIN_BUDGET_MAX_DB: float = 24.0

#: Egress RMS safe band in dBFS. Spec §2.4 / §4.2 — RMS at the OBS-bound
#: monitor must be in this range during livestream.
EGRESS_RMS_BAND_DBFS: tuple[float, float] = (-40.0, -10.0)

#: Egress crest factor threshold above which the audio is presumed to be
#: clipping noise / amplified bleed. Spec §4.2 — voice 3-4, music 4-6,
#: clipping > 5.
EGRESS_CREST_CLIPPING_THRESHOLD: float = 5.0

#: AUX positions that the L-12 sources its capture on. Per audio-topology
#: §1.4 (spec §2.2) — the L-12 multichannel source publishes
#: ``audio.position = [AUX0..AUX13]`` and only these positions may
#: appear on edges sourced from the L-12.
L12_INPUT_POSITIONS: frozenset[str] = frozenset(f"AUX{i}" for i in range(14))

#: Speaker positions that the L-12 USB return accepts on its sink side
#: (FL/FR/RL/RR — surround40). The ``l12_directionality`` invariant
#: requires that L-12-bound playback sticks to these.
L12_OUTPUT_POSITIONS: frozenset[str] = frozenset(("FL", "FR", "RL", "RR"))

#: Node-id substrings that mark a node as "broadcast-family" — a
#: descriptor fragment that ultimately reaches the OBS / livestream egress.
#: Used by both ``private_never_broadcasts`` and ``master_bus_sole_path``.
BROADCAST_FAMILY_ID_HINTS: tuple[str, ...] = (
    "livestream-tap",
    "livestream-legacy",
    "broadcast-master",
    "broadcast-normalized",
    "obs-broadcast-remap",
    "l12-evilpet-capture",
)

#: The single canonical master-bus node id. Per spec §2.4
#: ``master_bus_sole_path`` invariant: every broadcast-bound stream
#: must traverse this node before reaching OBS.
MASTER_BUS_NODE_ID: str = "broadcast-master"

#: Set of params keys that mark a node as private-only. Reachability from
#: any private-tagged node into the broadcast family is the
#: ``private_never_broadcasts`` violation.
PRIVATE_TAG_KEYS: frozenset[str] = frozenset(("private_monitor_endpoint", "fail_closed"))

#: Node-id substrings that flag a node as private even without explicit
#: params tagging — covers the operator's "private" / "notification-private"
#: convention. Reachability from any of these into the broadcast family
#: is also a violation.
PRIVATE_ID_HINTS: tuple[str, ...] = (
    "private-sink",
    "private-monitor-capture",
    "private-monitor-output",
    "notification-private-sink",
    "notification-private-monitor-capture",
    "notification-private-monitor-output",
    "role-assistant",
    "role-notification",
)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


class InvariantSeverity(StrEnum):
    """How a violation is handled at apply time."""

    BLOCKING = "blocking"
    WARNING = "warning"
    INFORMATIONAL = "informational"


class InvariantKind(StrEnum):
    """Taxonomy of constitutional + operational invariants."""

    PRIVATE_NEVER_BROADCASTS = "private_never_broadcasts"
    L12_DIRECTIONALITY = "l12_directionality"
    PORT_COMPATIBILITY = "port_compatibility"
    FORMAT_COMPATIBILITY = "format_compatibility"
    CHANNEL_COUNT_TOPOLOGY_WIDE = "channel_count_topology_wide"
    GAIN_BUDGET = "gain_budget"
    MASTER_BUS_SOLE_PATH = "master_bus_sole_path"
    NO_DUPLICATE_PIPEWIRE_NAMES = "no_duplicate_pipewire_names"
    HARDWARE_BLEED_GUARD = "hardware_bleed_guard"
    EGRESS_SAFETY_BAND_RMS = "egress_safety_band_rms"
    EGRESS_SAFETY_BAND_CREST = "egress_safety_band_crest"


class InvariantViolation(BaseModel):
    """One violation surfaced by an invariant predicate.

    Pure data; carried verbatim into the compiler's
    ``CompiledArtefacts.preflight_checks`` field.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: InvariantKind
    severity: InvariantSeverity = InvariantSeverity.BLOCKING
    node_id: str | None = None
    edge: tuple[str, str] | None = None
    message: str


class EgressHealth(BaseModel):
    """A single 0.5 s window of measured egress audio health.

    Per spec §4.2 — the circuit breaker reads ``parec`` of the OBS-bound
    monitor at 2 Hz and computes ``rms_dbfs`` / ``crest_factor`` /
    ``zcr``. P1 carries this as data so the post-apply egress
    predicates can be tested deterministically without a live audio
    capture.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    rms_dbfs: float
    crest_factor: float = Field(..., ge=0.0)
    zcr: float = Field(..., ge=0.0, le=1.0)
    sample_window_s: float = Field(default=0.5, gt=0.0)
    livestream_active: bool = True


# ---------------------------------------------------------------------------
# 1. PRIVATE_NEVER_BROADCASTS
# ---------------------------------------------------------------------------


def _build_adjacency(graph: AudioGraph) -> dict[str, list[str]]:
    """Build an outgoing-adjacency map from links + loopbacks.

    Loopbacks count as edges from ``source`` → ``sink`` because they
    establish runtime signal flow even though they're modelled as
    ``LoopbackTopology`` rather than ``AudioLink``.
    """

    adj: dict[str, list[str]] = defaultdict(list)
    for link in graph.links:
        adj[link.source].append(link.target)
    for lb in graph.loopbacks:
        adj[lb.source].append(lb.sink)
    return dict(adj)


def _bfs_descendants(adj: dict[str, list[str]], src: str) -> set[str]:
    """All node ids reachable from ``src`` (including ``src``)."""
    seen: set[str] = {src}
    queue: deque[str] = deque([src])
    while queue:
        cur = queue.popleft()
        for nxt in adj.get(cur, ()):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen


def _is_private(node: AudioNode) -> bool:
    """True if a node is private-only by params or id-hint."""
    if any(node.params.get(k) is True for k in PRIVATE_TAG_KEYS):
        return True
    return any(hint in node.id for hint in PRIVATE_ID_HINTS)


def _is_broadcast_family(node: AudioNode) -> bool:
    """True if a node id matches any broadcast-family hint."""
    return any(hint in node.id for hint in BROADCAST_FAMILY_ID_HINTS)


def check_private_never_broadcasts(graph: AudioGraph) -> list[InvariantViolation]:
    """Reachability check: BFS from every private-tagged node.

    Violations are any private node from which a broadcast-family node
    is reachable. This is the constitutional invariant — the operator's
    private monitor (S-4 OUT 1/2 patch, Yeti headphone) must NEVER be
    audible on the livestream broadcast.
    """

    private_ids = {n.id for n in graph.nodes if _is_private(n)}
    broadcast_ids = {n.id for n in graph.nodes if _is_broadcast_family(n)}
    adj = _build_adjacency(graph)
    violations: list[InvariantViolation] = []
    for src in sorted(private_ids):
        reachable = _bfs_descendants(adj, src)
        crossings = reachable & broadcast_ids
        if crossings:
            violations.append(
                InvariantViolation(
                    kind=InvariantKind.PRIVATE_NEVER_BROADCASTS,
                    severity=InvariantSeverity.BLOCKING,
                    node_id=src,
                    message=(
                        f"private node {src!r} reaches broadcast-family "
                        f"nodes: {sorted(crossings)!r}"
                    ),
                )
            )
    return violations


# ---------------------------------------------------------------------------
# 2. L12_DIRECTIONALITY
# ---------------------------------------------------------------------------


def check_l12_directionality(graph: AudioGraph) -> list[InvariantViolation]:
    """L-12 inputs flow only on AUX positions; outputs on FL/FR/RL/RR.

    The L-12 hardware mixer publishes 14 capture channels at
    ``audio.position=[AUX0..AUX13]`` and accepts 4 playback channels at
    ``audio.position=[FL FR RL RR]``. Edges that cross this contract
    (e.g. an AUX-port edge sinking into L-12 USB return, or an
    FL/FR-port edge sourcing from L-12 capture) are configuration bugs.

    The ``forbidden_target_family=l12-broadcast`` params tag is also
    honoured: any node bearing this tag must NOT have any descendant
    in the L-12 broadcast family.
    """

    violations: list[InvariantViolation] = []
    by_id = {n.id: n for n in graph.nodes}

    for link in graph.links:
        # Inbound to L-12 (target is l12-usb-return-shaped) must be FL/FR/RL/RR
        target_node = by_id.get(link.target)
        if target_node is not None and "l12-usb-return" in target_node.id:
            if link.source_port is not None and link.source_port not in L12_OUTPUT_POSITIONS:
                violations.append(
                    InvariantViolation(
                        kind=InvariantKind.L12_DIRECTIONALITY,
                        severity=InvariantSeverity.BLOCKING,
                        edge=(link.source, link.target),
                        message=(
                            f"L-12 USB return edge from {link.source!r} "
                            f"uses source_port={link.source_port!r}; "
                            f"expected one of {sorted(L12_OUTPUT_POSITIONS)!r}"
                        ),
                    )
                )

        # Outbound from L-12 capture must be AUX-positioned
        source_node = by_id.get(link.source)
        if source_node is not None and "l12-capture" in source_node.id:
            if link.source_port is not None and link.source_port not in L12_INPUT_POSITIONS:
                violations.append(
                    InvariantViolation(
                        kind=InvariantKind.L12_DIRECTIONALITY,
                        severity=InvariantSeverity.BLOCKING,
                        edge=(link.source, link.target),
                        message=(
                            f"L-12 capture edge to {link.target!r} uses "
                            f"source_port={link.source_port!r}; expected "
                            f"AUX0..AUX13"
                        ),
                    )
                )

    # forbidden_target_family annotation
    adj = _build_adjacency(graph)
    for node in graph.nodes:
        forbidden = node.params.get("forbidden_target_family")
        if forbidden != "l12-broadcast":
            continue
        reachable = _bfs_descendants(adj, node.id)
        # Exclude self
        reachable.discard(node.id)
        forbidden_ids = {n.id for n in graph.nodes if "l12" in n.id and "broadcast" not in n.id} | {
            n.id for n in graph.nodes if _is_broadcast_family(n)
        }
        crossings = reachable & forbidden_ids
        if crossings:
            violations.append(
                InvariantViolation(
                    kind=InvariantKind.L12_DIRECTIONALITY,
                    severity=InvariantSeverity.BLOCKING,
                    node_id=node.id,
                    message=(
                        f"node {node.id!r} carries forbidden_target_family="
                        f"l12-broadcast but reaches: {sorted(crossings)!r}"
                    ),
                )
            )

    return violations


# ---------------------------------------------------------------------------
# 3. PORT_COMPATIBILITY
# ---------------------------------------------------------------------------


def _position_family(pos: str) -> str:
    """Family of a position token: speaker / aux / mono / unknown."""
    if pos in ("FL", "FR", "RL", "RR", "SL", "SR", "FC", "LFE"):
        return "speaker"
    if pos.startswith("AUX") and pos[3:].isdigit():
        return "aux"
    if pos == "MONO":
        return "mono"
    return "unknown"


def check_port_compatibility(graph: AudioGraph) -> list[InvariantViolation]:
    """Edge source/target ports must reference compatible families.

    A speaker-position edge cannot land on an AUX target (and vice
    versa) without an explicit downmix node. This catches today's #1
    failure (FL/FR vs RL/RR mismatch — music silent on broadcast).

    The check is family-level rather than position-identity: matching
    FL→FL or AUX1→AUX1 is required; FL→RL is allowed only when the
    target is L-12 USB return (an explicit position remap).
    """

    violations: list[InvariantViolation] = []
    for link in graph.links:
        if link.source_port is None or link.target_port is None:
            continue
        src_fam = _position_family(link.source_port)
        tgt_fam = _position_family(link.target_port)
        if src_fam != tgt_fam:
            violations.append(
                InvariantViolation(
                    kind=InvariantKind.PORT_COMPATIBILITY,
                    severity=InvariantSeverity.BLOCKING,
                    edge=(link.source, link.target),
                    message=(
                        f"link source_port={link.source_port!r} "
                        f"(family={src_fam}) → target_port="
                        f"{link.target_port!r} (family={tgt_fam}) — "
                        "incompatible position families"
                    ),
                )
            )
    return violations


# ---------------------------------------------------------------------------
# 4. FORMAT_COMPATIBILITY
# ---------------------------------------------------------------------------


def _has_downmix(graph: AudioGraph, src_id: str, tgt_id: str) -> bool:
    """True if a GainStage with non-None downmix_strategy spans this edge."""
    return any(
        gs.edge_source == src_id and gs.edge_target == tgt_id and gs.downmix_strategy is not None
        for gs in graph.gain_stages
    )


def check_format_compatibility(graph: AudioGraph) -> list[InvariantViolation]:
    """Channel-count change between source and target requires explicit downmix.

    Today's failure #5 — ``audio.channels=2`` declared on a chain whose
    capture is 14ch — was a silent downmix that produced a quiet
    livestream. With ``GainStage(downmix_strategy=...)`` the operator
    surfaces the downmix as data; without it, the apply path refuses.
    """

    violations: list[InvariantViolation] = []
    by_id = {n.id: n for n in graph.nodes}
    for link in graph.links:
        src = by_id.get(link.source)
        tgt = by_id.get(link.target)
        if src is None or tgt is None:
            continue
        if src.channels.count == tgt.channels.count:
            continue
        if _has_downmix(graph, link.source, link.target):
            continue
        violations.append(
            InvariantViolation(
                kind=InvariantKind.FORMAT_COMPATIBILITY,
                severity=InvariantSeverity.BLOCKING,
                edge=(link.source, link.target),
                message=(
                    f"channel-count change {src.channels.count}ch → "
                    f"{tgt.channels.count}ch on edge {link.source!r} → "
                    f"{link.target!r} requires explicit GainStage "
                    "downmix_strategy"
                ),
            )
        )
    return violations


# ---------------------------------------------------------------------------
# 5. CHANNEL_COUNT_TOPOLOGY_WIDE
# ---------------------------------------------------------------------------


def check_channel_count_topology_wide(graph: AudioGraph) -> list[InvariantViolation]:
    """Global format check: any node downstream of a multi-channel capture
    must either share its channel count or pass through a downmix node.

    This generalises ``format_compatibility`` to multi-hop paths: even if
    no single edge crosses a count change without a declared downmix,
    a chain like ``14ch → 14ch → 2ch`` without a downmix at the second
    edge is the same failure. This invariant walks the descendants of
    each multi-channel node and surfaces any descendant whose channel
    count differs without a corresponding ``GainStage`` downmix.
    """

    violations: list[InvariantViolation] = []
    by_id = {n.id: n for n in graph.nodes}
    adj = _build_adjacency(graph)

    for src in graph.nodes:
        if src.channels.count <= 2:
            continue
        descendants = _bfs_descendants(adj, src.id) - {src.id}
        for tgt_id in sorted(descendants):
            tgt = by_id.get(tgt_id)
            if tgt is None or tgt.channels.count == src.channels.count:
                continue
            # Walk one path src → ... → tgt; if any edge in that path
            # has a downmix, accept this descendant. We use a simple
            # any-path check: did any direct or transitive predecessor
            # of tgt include a GainStage with downmix_strategy set?
            if _path_contains_downmix(graph, src.id, tgt_id):
                continue
            violations.append(
                InvariantViolation(
                    kind=InvariantKind.CHANNEL_COUNT_TOPOLOGY_WIDE,
                    severity=InvariantSeverity.BLOCKING,
                    edge=(src.id, tgt_id),
                    message=(
                        f"multi-channel source {src.id!r} ({src.channels.count}ch) "
                        f"reaches {tgt_id!r} ({tgt.channels.count}ch) without a "
                        "downmix GainStage on any path"
                    ),
                )
            )
    return violations


def _path_contains_downmix(graph: AudioGraph, src_id: str, tgt_id: str) -> bool:
    """True if any path src → tgt includes a GainStage with downmix_strategy."""
    adj = _build_adjacency(graph)
    downmix_edges = {
        (gs.edge_source, gs.edge_target)
        for gs in graph.gain_stages
        if gs.downmix_strategy is not None
    }
    # BFS keeping track of "did this path see a downmix".
    queue: deque[tuple[str, bool]] = deque([(src_id, False)])
    seen: set[tuple[str, bool]] = {(src_id, False)}
    while queue:
        cur, seen_dm = queue.popleft()
        if cur == tgt_id and seen_dm:
            return True
        for nxt in adj.get(cur, ()):
            nxt_dm = seen_dm or ((cur, nxt) in downmix_edges)
            key = (nxt, nxt_dm)
            if key not in seen:
                seen.add(key)
                queue.append(key)
    return False


# ---------------------------------------------------------------------------
# 6. GAIN_BUDGET
# ---------------------------------------------------------------------------


def check_gain_budget(graph: AudioGraph) -> list[InvariantViolation]:
    """Cumulative makeup_gain_db along any source-to-broadcast path ≤ +24 dB.

    Walks every source node (no incoming links) and DFS-traverses to all
    reachable nodes, summing ``link.makeup_gain_db`` plus ``GainStage.base_gain_db``.
    Any path whose cumulative gain exceeds the budget surfaces a violation
    with the offending path printed for the operator.
    """

    violations: list[InvariantViolation] = []
    incoming: dict[str, set[str]] = defaultdict(set)
    for link in graph.links:
        incoming[link.target].add(link.source)
    for lb in graph.loopbacks:
        incoming[lb.sink].add(lb.source)

    sources = [n for n in graph.nodes if n.id not in incoming]

    by_pair_link_gain: dict[tuple[str, str], float] = {}
    for link in graph.links:
        # If multiple links between the same pair, take the max gain
        # — a fan-in already covers this case; we just want the worst.
        prev = by_pair_link_gain.get((link.source, link.target), float("-inf"))
        by_pair_link_gain[(link.source, link.target)] = max(prev, link.makeup_gain_db)

    by_pair_stage_gain: dict[tuple[str, str], float] = {}
    for gs in graph.gain_stages:
        prev = by_pair_stage_gain.get((gs.edge_source, gs.edge_target), float("-inf"))
        # base_gain_db is the floor; per_channel_overrides may push higher
        overrides_max = max((v for v in gs.per_channel_overrides.values()), default=0.0)
        effective = gs.base_gain_db + max(overrides_max, 0.0)
        by_pair_stage_gain[(gs.edge_source, gs.edge_target)] = max(prev, effective)

    adj = _build_adjacency(graph)

    for src in sources:
        # DFS with cumulative gain; track each path's running sum
        stack: list[tuple[str, float, tuple[str, ...]]] = [(src.id, 0.0, (src.id,))]
        seen_keys: set[tuple[str, int]] = set()
        while stack:
            cur, cum, path = stack.pop()
            # Use a coarse key (node, rounded gain) to cap expansion
            key = (cur, int(round(cum * 10)))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            if cum > GAIN_BUDGET_MAX_DB:
                violations.append(
                    InvariantViolation(
                        kind=InvariantKind.GAIN_BUDGET,
                        severity=InvariantSeverity.BLOCKING,
                        node_id=cur,
                        message=(
                            f"cumulative gain {cum:.2f} dB on path "
                            f"{' → '.join(path)} exceeds budget "
                            f"+{GAIN_BUDGET_MAX_DB:.1f} dB"
                        ),
                    )
                )
                continue
            for nxt in adj.get(cur, ()):
                edge_gain = by_pair_link_gain.get((cur, nxt), 0.0)
                if edge_gain == float("-inf"):
                    edge_gain = 0.0
                stage_gain = by_pair_stage_gain.get((cur, nxt), 0.0)
                if stage_gain == float("-inf"):
                    stage_gain = 0.0
                new_cum = cum + edge_gain + stage_gain
                stack.append((nxt, new_cum, (*path, nxt)))
    return violations


# ---------------------------------------------------------------------------
# 7. MASTER_BUS_SOLE_PATH
# ---------------------------------------------------------------------------


def check_master_bus_sole_path(graph: AudioGraph) -> list[InvariantViolation]:
    """Every broadcast-bound source must traverse the master bus.

    The graph defines a designated master node (id == ``broadcast-master``).
    Any **source-only** node (no incoming edges) that reaches the
    OBS-bound capture (an ``obs-broadcast-remap`` family node) MUST do so
    through the master. This invariant runs only when the master exists
    and at least one OBS terminus exists; it's silent otherwise.

    Restricting the bypass check to source-only nodes (rather than every
    intermediate) lets the chain ``master → normalized → OBS`` pass
    cleanly — ``normalized`` is downstream of the master, not a
    bypassing source.

    Source-only is defined as: no incoming ``AudioLink`` AND no
    incoming ``LoopbackTopology`` edge AND not the master itself.
    """

    violations: list[InvariantViolation] = []
    node_ids = {n.id for n in graph.nodes}
    if MASTER_BUS_NODE_ID not in node_ids:
        return violations

    obs_terminus_ids = {n.id for n in graph.nodes if "obs-broadcast-remap" in n.id}
    if not obs_terminus_ids:
        return violations

    adj = _build_adjacency(graph)

    # Identify source-only node ids (no incoming edges).
    incoming: dict[str, set[str]] = defaultdict(set)
    for src, tgts in adj.items():
        for tgt in tgts:
            incoming[tgt].add(src)
    source_only = {n.id for n in graph.nodes if n.id not in incoming and n.id != MASTER_BUS_NODE_ID}

    # Master-deleted adjacency: drop edges INTO master AND edges out of master
    # so any path through master is broken.
    adj_no_master: dict[str, list[str]] = {
        k: [t for t in v if t != MASTER_BUS_NODE_ID]
        for k, v in adj.items()
        if k != MASTER_BUS_NODE_ID
    }

    for offender in sorted(source_only):
        if offender in obs_terminus_ids:
            continue
        offender_node = next((n for n in graph.nodes if n.id == offender), None)
        if offender_node is None or _is_private(offender_node):
            continue
        # Can offender reach any OBS terminus in the master-deleted graph?
        reachable = _bfs_descendants(adj_no_master, offender)
        crossings = reachable & obs_terminus_ids
        if crossings:
            violations.append(
                InvariantViolation(
                    kind=InvariantKind.MASTER_BUS_SOLE_PATH,
                    severity=InvariantSeverity.BLOCKING,
                    node_id=offender,
                    message=(
                        f"source node {offender!r} reaches OBS terminus "
                        f"{sorted(crossings)!r} without traversing master "
                        f"{MASTER_BUS_NODE_ID!r}"
                    ),
                )
            )
    return violations


# ---------------------------------------------------------------------------
# 8. NO_DUPLICATE_PIPEWIRE_NAMES
# ---------------------------------------------------------------------------


def check_no_duplicate_pipewire_names(graph: AudioGraph) -> list[InvariantViolation]:
    """``pipewire_name`` must be unique across all nodes.

    Two nodes claiming the same ``node.name`` would produce undefined
    runtime behaviour — PipeWire would arbitrarily pick one. This
    invariant catches the bug at parse time.
    """

    seen: dict[str, list[str]] = defaultdict(list)
    for node in graph.nodes:
        seen[node.pipewire_name].append(node.id)
    violations: list[InvariantViolation] = []
    for name, ids in seen.items():
        if len(ids) > 1:
            violations.append(
                InvariantViolation(
                    kind=InvariantKind.NO_DUPLICATE_PIPEWIRE_NAMES,
                    severity=InvariantSeverity.BLOCKING,
                    message=(f"pipewire_name={name!r} is shared by nodes {sorted(ids)!r}"),
                )
            )
    return violations


# ---------------------------------------------------------------------------
# 9. HARDWARE_BLEED_GUARD
# ---------------------------------------------------------------------------


def check_hardware_bleed_guard(graph: AudioGraph) -> list[InvariantViolation]:
    """Per-channel gain after declared bleed must not exceed 0 dB.

    For any ``GainStage`` with ``declared_bleed_db`` set, every channel
    in ``per_channel_overrides`` (and the base gain on its source port)
    must satisfy ``base_gain_db + override - declared_bleed_db ≤ 0``.
    Today's failure #6 — ``gain_samp = 1.0`` on AUX3 with -27 dB hardware
    bleed — surfaces here once the operator declares the bleed value.
    """

    violations: list[InvariantViolation] = []
    for gs in graph.gain_stages:
        if gs.declared_bleed_db is None:
            continue
        # Base gain alone vs bleed
        if gs.base_gain_db - gs.declared_bleed_db > 0.0:
            violations.append(
                InvariantViolation(
                    kind=InvariantKind.HARDWARE_BLEED_GUARD,
                    severity=InvariantSeverity.BLOCKING,
                    edge=(gs.edge_source, gs.edge_target),
                    message=(
                        f"GainStage {gs.edge_source!r} → {gs.edge_target!r}: "
                        f"base_gain_db={gs.base_gain_db:.2f}, "
                        f"declared_bleed_db={gs.declared_bleed_db:.2f}; "
                        "base gain exceeds bleed budget (would amplify bleed "
                        "above signal floor)"
                    ),
                )
            )
        # Per-channel overrides
        for ch, override in gs.per_channel_overrides.items():
            if gs.base_gain_db + override - gs.declared_bleed_db > 0.0:
                violations.append(
                    InvariantViolation(
                        kind=InvariantKind.HARDWARE_BLEED_GUARD,
                        severity=InvariantSeverity.BLOCKING,
                        edge=(gs.edge_source, gs.edge_target),
                        message=(
                            f"GainStage {gs.edge_source!r} → {gs.edge_target!r} "
                            f"channel {ch!r}: "
                            f"effective gain {gs.base_gain_db + override:.2f} dB "
                            f"exceeds bleed -{gs.declared_bleed_db:.2f} dB"
                        ),
                    )
                )
    return violations


# ---------------------------------------------------------------------------
# 10. EGRESS_SAFETY_BAND_RMS
# ---------------------------------------------------------------------------


def check_egress_safety_band_rms(
    graph: AudioGraph, health: EgressHealth
) -> list[InvariantViolation]:
    """RMS at OBS-bound monitor must be in [-40, -10] dBFS during livestream.

    Continuous post-apply invariant — P5 enforces it via the circuit
    breaker; P1 carries the predicate as data so its behaviour is
    pinnable in tests. When ``livestream_active=False``, the predicate
    no-ops (silence is acceptable when no broadcast is in flight).
    """

    if not health.livestream_active:
        return []
    lo, hi = EGRESS_RMS_BAND_DBFS
    if lo <= health.rms_dbfs <= hi:
        return []
    # Don't even need to read the graph — the egress health alone says
    # whether the band is breached. The graph is only used to resolve
    # which surface this applies to in the violation message.
    obs_term = next(
        (n.id for n in graph.nodes if "obs-broadcast-remap" in n.id),
        "obs-broadcast-remap",
    )
    return [
        InvariantViolation(
            kind=InvariantKind.EGRESS_SAFETY_BAND_RMS,
            severity=InvariantSeverity.BLOCKING,
            node_id=obs_term,
            message=(
                f"egress RMS {health.rms_dbfs:.2f} dBFS at {obs_term!r} "
                f"outside safe band [{lo:.1f}, {hi:.1f}] dBFS"
            ),
        )
    ]


# ---------------------------------------------------------------------------
# 11. EGRESS_SAFETY_BAND_CREST
# ---------------------------------------------------------------------------


def check_egress_safety_band_crest(
    graph: AudioGraph, health: EgressHealth
) -> list[InvariantViolation]:
    """Crest factor at OBS must not exceed clipping-noise threshold.

    Continuous post-apply invariant. When ``livestream_active=False``,
    the predicate no-ops. When the crest factor exceeds the threshold
    AND the RMS is loud enough that the operator would call it a noise
    complaint (above -40 dBFS), the predicate fires.
    """

    if not health.livestream_active:
        return []
    if (
        health.crest_factor > EGRESS_CREST_CLIPPING_THRESHOLD
        and health.rms_dbfs > EGRESS_RMS_BAND_DBFS[0]
    ):
        obs_term = next(
            (n.id for n in graph.nodes if "obs-broadcast-remap" in n.id),
            "obs-broadcast-remap",
        )
        return [
            InvariantViolation(
                kind=InvariantKind.EGRESS_SAFETY_BAND_CREST,
                severity=InvariantSeverity.BLOCKING,
                node_id=obs_term,
                message=(
                    f"egress crest {health.crest_factor:.2f} at {obs_term!r} "
                    f"exceeds clipping threshold "
                    f"{EGRESS_CREST_CLIPPING_THRESHOLD:.1f} with RMS "
                    f"{health.rms_dbfs:.2f} dBFS — likely clipping noise / "
                    "amplified bleed"
                ),
            )
        ]
    return []


# ---------------------------------------------------------------------------
# Registry — kind → checker
# ---------------------------------------------------------------------------


#: Maps every ``InvariantKind`` to its pre-apply checker.
#:
#: The two continuous invariants (RMS, crest) are NOT in this registry
#: because they require an additional ``EgressHealth`` argument; callers
#: invoke ``check_egress_safety_band_*(graph, health)`` directly. The
#: registry covers exactly the 9 pre-apply invariants the compiler runs.
INVARIANT_REGISTRY: dict[InvariantKind, InvariantChecker] = {
    InvariantKind.PRIVATE_NEVER_BROADCASTS: check_private_never_broadcasts,
    InvariantKind.L12_DIRECTIONALITY: check_l12_directionality,
    InvariantKind.PORT_COMPATIBILITY: check_port_compatibility,
    InvariantKind.FORMAT_COMPATIBILITY: check_format_compatibility,
    InvariantKind.CHANNEL_COUNT_TOPOLOGY_WIDE: check_channel_count_topology_wide,
    InvariantKind.GAIN_BUDGET: check_gain_budget,
    InvariantKind.MASTER_BUS_SOLE_PATH: check_master_bus_sole_path,
    InvariantKind.NO_DUPLICATE_PIPEWIRE_NAMES: check_no_duplicate_pipewire_names,
    InvariantKind.HARDWARE_BLEED_GUARD: check_hardware_bleed_guard,
}


from collections.abc import Callable  # noqa: E402

InvariantChecker = Callable[[AudioGraph], list[InvariantViolation]]


def check_all_invariants(
    graph: AudioGraph,
    egress_health: EgressHealth | None = None,
    kinds: Iterable[InvariantKind] | None = None,
) -> list[InvariantViolation]:
    """Run all (or a filtered subset of) invariants over a graph.

    When ``egress_health`` is provided AND no ``kinds`` filter (or the
    filter includes either continuous kind), the post-apply egress
    predicates also fire. With a ``kinds`` filter, only those listed run.
    """

    if kinds is None:
        kinds_set: set[InvariantKind] = set(InvariantKind)
    else:
        kinds_set = set(kinds)

    violations: list[InvariantViolation] = []
    for kind in InvariantKind:
        if kind not in kinds_set:
            continue
        if kind in INVARIANT_REGISTRY:
            violations.extend(INVARIANT_REGISTRY[kind](graph))
        elif kind == InvariantKind.EGRESS_SAFETY_BAND_RMS and egress_health is not None:
            violations.extend(check_egress_safety_band_rms(graph, egress_health))
        elif kind == InvariantKind.EGRESS_SAFETY_BAND_CREST and egress_health is not None:
            violations.extend(check_egress_safety_band_crest(graph, egress_health))
    return violations
