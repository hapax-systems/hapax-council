"""Graph-patch recruitment consumer — wires GraphPatch into the chain mutation path.

Architectural fix per researcher audit + memory
``feedback_no_presets_use_parametric_modulation``: the system architecture
mandates *constrained algorithmic parametric modulation + chain composition
(transition primitives + affordance-recruited node add/remove)*. The director
NEVER picks a preset. Chain composition emerges from per-impingement
node add/remove and structural graph operations fired by the affordance pipeline.

The ``GraphPatch`` type at ``agents/effect_graph/types.py:85-89`` carries
``add_nodes / remove_nodes / add_edges / remove_edges`` fields but had zero
callers — the architecturally-correct chain mutation primitive was unwired.
This module is the bridge.

Shape:
1. ``shared/compositional_affordances.py`` registers ``node.add.<type>``,
   ``node.remove.<role>``, and structural ``node.compose`` / ``node.fork`` /
   ``node.merge`` / ``node.route`` capabilities. Each one carries a
   Gibson-verb description (cognitive-function, not implementation-detail).
   The AffordancePipeline's cosine-similarity retrieval surfaces the matching
   capability per impingement narrative.
2. ``agents/studio_compositor/compositional_consumer.dispatch_node_patch``
   writes the recruited capability under the corresponding ``node.*`` family
   in ``recent-recruitment.json``.
3. This consumer reads the recruitment, builds a ``GraphPatch``, applies it
   to the most-recently-known live graph (or the publication-current one),
   and writes the patched graph as a new mutation file at
   ``/dev/shm/hapax-compositor/graph-mutation.json``. The compositor's
   state-reader loop already consumes that path (state.py:344-365) and
   reloads the graph runtime — same egress channel as preset recruitment.

Cooldown + single-flight match the preset_recruitment_consumer shape so
the architecture stays parallel: chain-composition recruitments don't
thrash the chain any more than preset-family recruitments do.

The consumer is intentionally small: it reads recruitments, composes a
patch, and writes the result. It does not author content (descriptions
live in the affordance catalog), it does not pick effects (the pipeline
does), it does not modulate params (the visual chain does). It just
closes the recruitment → mutation loop that was open.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

from agents.effect_graph.types import EdgeDef, EffectGraph, GraphPatch, NodeInstance

log = logging.getLogger(__name__)

RECRUITMENT_FILE = Path("/dev/shm/hapax-compositor/recent-recruitment.json")
MUTATION_FILE = Path("/dev/shm/hapax-compositor/graph-mutation.json")

COOLDOWN_S = 8.0
"""Minimum seconds between consecutive consumer activations.

Mirrors the preset_recruitment_consumer cooldown. Chain mutations that re-
fire within this window represent the same compositional moment. Without
cooldown the chain would visibly thrash to viewers.
"""

PATCH_BIAS_TTL_S = 20.0
"""How fresh a node.* patch recruitment must be to be honoured.

Beyond this window the recruitment is treated as stale and the consumer
declines to apply it. Matches the existing preset.bias TTL so the
director's structural intent on patch capabilities ages out the same way.
"""

# Module-level state — same pattern as preset_recruitment_consumer.
_last_activation_t: float = 0.0
NODE_PATCH_FAMILIES = (
    "node.add",
    "node.remove",
    "node.compose",
    "node.fork",
    "node.merge",
    "node.route",
)
_last_node_family_ts_seen: dict[str, float] = dict.fromkeys(NODE_PATCH_FAMILIES, 0.0)
_last_patched_graph: EffectGraph | None = None

# Single-flight lock so two patches don't race their writes onto MUTATION_FILE.
_patch_lock = threading.Lock()


# Callable that returns the current live EffectGraph, or None if unknown.
# Wired by the compositor at startup via ``set_current_graph_provider``;
# defaults to ``_last_patched_graph`` so tests can drive without a runtime.
_current_graph_provider: Callable[[], EffectGraph | None] | None = None


def set_current_graph_provider(provider: Callable[[], EffectGraph | None] | None) -> None:
    """Register a callable that returns the live ``EffectGraph``.

    Called once at compositor startup with a closure over the
    ``GraphRuntime.current_graph`` accessor. Tests inject a stub.
    """
    global _current_graph_provider
    _current_graph_provider = provider


def _get_current_graph() -> EffectGraph | None:
    """Return the live graph: provider first, then last patched, then None."""
    if _current_graph_provider is not None:
        try:
            g = _current_graph_provider()
            if g is not None:
                return g
        except Exception:
            log.debug("current_graph_provider raised", exc_info=True)
    return _last_patched_graph


def _write_mutation(graph: EffectGraph) -> None:
    """Write a patched graph to the SHM mutation file (state-reader consumes)."""
    MUTATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = graph.model_dump(mode="json")
    MUTATION_FILE.write_text(json.dumps(payload), encoding="utf-8")


def _fresh_items(payload: dict, family: str, now: float) -> tuple[list[dict], float]:
    """Return fresh per-family recruitment items and the newest item timestamp."""
    families = payload.get("families") or {}
    entry = families.get(family) or {}
    if not isinstance(entry, dict):
        return [], 0.0
    raw_items = entry.get("items") or []
    if not isinstance(raw_items, list):
        return [], 0.0
    fresh: list[dict] = []
    newest_ts = 0.0
    for it in raw_items:
        if not isinstance(it, dict):
            continue
        ts = it.get("last_recruited_ts")
        if not isinstance(ts, (int, float)):
            continue
        ts_f = float(ts)
        if now - ts_f > PATCH_BIAS_TTL_S:
            continue
        fresh.append(it)
        newest_ts = max(newest_ts, ts_f)
    return fresh, newest_ts


def _family_timestamps(payload: dict) -> dict[str, float]:
    """Top-level last-recruited timestamp per node-patch family."""
    families = payload.get("families") or {}
    out: dict[str, float] = {}
    for family in NODE_PATCH_FAMILIES:
        entry = families.get(family) or {}
        if not isinstance(entry, dict):
            out[family] = 0.0
            continue
        ts = entry.get("last_recruited_ts")
        out[family] = float(ts) if isinstance(ts, (int, float)) else 0.0
    return out


def _pair_suffix(raw: object) -> tuple[str, str] | None:
    """Parse ``a,b`` or ``{a,b}`` suffixes from node composition names."""
    if not isinstance(raw, str):
        return None
    suffix = raw.strip().strip("{}")
    parts = [p.strip() for p in suffix.split(",", 1)]
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return parts[0], parts[1]


def _safe_node_id_part(value: str) -> str:
    """Normalize a capability suffix into a conservative graph node-id segment."""
    out = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in value)
    out = "_".join(part for part in out.split("_") if part)
    return out or "node"


def _unique_node_id(graph: EffectGraph, prefix: str) -> str:
    if prefix not in graph.nodes:
        return prefix
    i = 2
    while f"{prefix}_{i}" in graph.nodes:
        i += 1
    return f"{prefix}_{i}"


def _endpoint(node_id: str, port: str, *, source: bool) -> str:
    if source and port == "out":
        return node_id
    if not source and port == "in":
        return node_id
    return f"{node_id}:{port}"


def _canonical_edge(edge: list[str]) -> EdgeDef | None:
    try:
        return EdgeDef.from_list(edge)
    except ValueError:
        return None


def _edge_key(edge: list[str]) -> tuple[str, str, str, str] | None:
    parsed = _canonical_edge(edge)
    if parsed is None:
        return None
    return (parsed.source_node, parsed.source_port, parsed.target_node, parsed.target_port)


def _diff_patch(before: EffectGraph, after: EffectGraph) -> GraphPatch:
    """Build the patch that reproduces ``after`` from ``before``."""
    remove_nodes = [node_id for node_id in before.nodes if node_id not in after.nodes]
    add_nodes = {
        node_id: node for node_id, node in after.nodes.items() if before.nodes.get(node_id) != node
    }
    before_edge_keys = {_edge_key(edge) for edge in before.edges}
    after_edge_keys = {_edge_key(edge) for edge in after.edges}
    remove_edges = [
        edge
        for edge in before.edges
        if (key := _edge_key(edge)) is not None and key not in after_edge_keys
    ]
    add_edges = [
        edge
        for edge in after.edges
        if (key := _edge_key(edge)) is not None and key not in before_edge_keys
    ]
    return GraphPatch(
        add_nodes=add_nodes,
        remove_nodes=remove_nodes,
        add_edges=add_edges,
        remove_edges=remove_edges,
    )


def _outgoing_edges(graph: EffectGraph, node_id: str) -> list[tuple[list[str], EdgeDef]]:
    out: list[tuple[list[str], EdgeDef]] = []
    for edge in graph.edges:
        parsed = _canonical_edge(edge)
        if parsed is not None and parsed.source_node == node_id:
            out.append((edge, parsed))
    return out


def _incoming_edges(graph: EffectGraph, node_id: str) -> list[tuple[list[str], EdgeDef]]:
    incoming: list[tuple[list[str], EdgeDef]] = []
    for edge in graph.edges:
        parsed = _canonical_edge(edge)
        if parsed is not None and parsed.target_node == node_id:
            incoming.append((edge, parsed))
    return incoming


def _compose_patch(graph: EffectGraph, first: str, second: str) -> GraphPatch:
    """Compose two existing nodes into a downstream blend meta-node."""
    if first not in graph.nodes or second not in graph.nodes:
        return GraphPatch()
    meta_id = _unique_node_id(
        graph,
        f"meta_{_safe_node_id_part(first)}_{_safe_node_id_part(second)}",
    )
    pair = {first, second}
    downstream = [
        (edge, parsed)
        for edge, parsed in _outgoing_edges(graph, first) + _outgoing_edges(graph, second)
        if parsed.target_node not in pair
    ]
    return GraphPatch(
        add_nodes={meta_id: NodeInstance(type="blend", params={"mode": "screen", "alpha": 0.5})},
        add_edges=[
            [first, f"{meta_id}:a"],
            [second, f"{meta_id}:b"],
            *[
                [meta_id, _endpoint(parsed.target_node, parsed.target_port, source=False)]
                for _, parsed in downstream
            ],
        ],
        remove_edges=[edge for edge, _ in downstream],
    )


def _fork_patch(graph: EffectGraph, node_id: str) -> GraphPatch:
    """Duplicate an existing node onto a parallel branch with matching edges."""
    node = graph.nodes.get(node_id)
    if node is None:
        return GraphPatch()
    fork_id = _unique_node_id(graph, f"fork_{_safe_node_id_part(node_id)}")
    add_edges: list[list[str]] = []
    for _, parsed in _incoming_edges(graph, node_id):
        add_edges.append(
            [
                _endpoint(parsed.source_node, parsed.source_port, source=True),
                _endpoint(fork_id, parsed.target_port, source=False),
            ]
        )
    for _, parsed in _outgoing_edges(graph, node_id):
        add_edges.append(
            [
                _endpoint(fork_id, parsed.source_port, source=True),
                _endpoint(parsed.target_node, parsed.target_port, source=False),
            ]
        )
    return GraphPatch(add_nodes={fork_id: node.model_copy(deep=True)}, add_edges=add_edges)


def _merge_patch(graph: EffectGraph, first: str, second: str) -> GraphPatch:
    """Merge two branch tips into a blend node before their shared downstream."""
    if first not in graph.nodes or second not in graph.nodes:
        return GraphPatch()
    first_out = _outgoing_edges(graph, first)
    second_out = _outgoing_edges(graph, second)
    second_targets = {(e.target_node, e.target_port): (edge, e) for edge, e in second_out}
    shared: list[tuple[list[str], EdgeDef]] = []
    for edge, parsed in first_out:
        candidate = second_targets.get((parsed.target_node, parsed.target_port))
        if candidate is None:
            continue
        shared.append((edge, parsed))
        shared.append(candidate)
        break
    if not shared:
        return GraphPatch()
    downstream = shared[0][1]
    merge_id = _unique_node_id(
        graph,
        f"merge_{_safe_node_id_part(first)}_{_safe_node_id_part(second)}",
    )
    return GraphPatch(
        add_nodes={merge_id: NodeInstance(type="blend", params={"mode": "screen", "alpha": 0.5})},
        add_edges=[
            [first, f"{merge_id}:a"],
            [second, f"{merge_id}:b"],
            [merge_id, _endpoint(downstream.target_node, downstream.target_port, source=False)],
        ],
        remove_edges=[edge for edge, _ in shared],
    )


def _route_patch(graph: EffectGraph, source: str, target: str) -> GraphPatch:
    """Reroute the source node's first outgoing edge to a new existing target."""
    if source not in graph.nodes or target not in graph.nodes:
        return GraphPatch()
    current_out = _outgoing_edges(graph, source)
    remove_edges = [current_out[0][0]] if current_out else []
    return GraphPatch(add_edges=[[source, target]], remove_edges=remove_edges)


def _build_patch_from_recruitment(
    payload: dict,
    graph: EffectGraph | None = None,
) -> tuple[GraphPatch, float]:
    """Parse a recruitment payload, return (patch, newest_ts).

    ``payload`` is the parsed ``recent-recruitment.json`` content. Looks
    for the node-patch family entries. Each carries an ``items`` list of
    ``{capability, suffix, last_recruited_ts}`` so multiple recruitments
    within the cooldown can be coalesced into a single patch.

    Returns an empty ``GraphPatch`` when nothing fresh is found.
    """
    now = time.time()
    add_items, add_newest = _fresh_items(payload, "node.add", now)
    remove_items, remove_newest = _fresh_items(payload, "node.remove", now)
    compose_items, compose_newest = _fresh_items(payload, "node.compose", now)
    fork_items, fork_newest = _fresh_items(payload, "node.fork", now)
    merge_items, merge_newest = _fresh_items(payload, "node.merge", now)
    route_items, route_newest = _fresh_items(payload, "node.route", now)
    newest_ts = max(
        add_newest,
        remove_newest,
        compose_newest,
        fork_newest,
        merge_newest,
        route_newest,
    )

    add_nodes: dict[str, NodeInstance] = {}
    add_edges: list[list[str]] = []
    remove_edges: list[list[str]] = []
    for it in add_items:
        node_type = it.get("suffix") or it.get("node_type")
        if not isinstance(node_type, str) or not node_type:
            continue
        # Synthesize a unique node id with the recruited type as the
        # node-id suffix so the slot pipeline can find it. Using the
        # recruitment ts keeps the id stable across re-applications
        # within the same window without collisions across windows.
        node_id = f"sat_{node_type}"
        add_nodes[node_id] = NodeInstance(type=node_type, params={})
        # No edges asserted by default — modulation/wiring happens
        # downstream of compile via the slot assignment pass. Future
        # patches can attach edges via the affordance metadata; for now
        # the slot pipeline picks them up by node-id presence.

    remove_nodes: list[str] = []
    for it in remove_items:
        target = it.get("suffix") or it.get("node_id") or it.get("role")
        if not isinstance(target, str) or not target:
            continue
        remove_nodes.append(target)

    if graph is not None:
        working = graph.apply_patch(
            GraphPatch(add_nodes=add_nodes, remove_nodes=remove_nodes, add_edges=add_edges)
        )
        for it in compose_items:
            pair = _pair_suffix(it.get("suffix"))
            if pair is None:
                continue
            p = _compose_patch(working, *pair)
            add_nodes.update(p.add_nodes)
            add_edges.extend(p.add_edges)
            remove_edges.extend(p.remove_edges)
            working = working.apply_patch(p)

        for it in fork_items:
            target = it.get("suffix") or it.get("node_id")
            if not isinstance(target, str) or not target:
                continue
            p = _fork_patch(working, target)
            add_nodes.update(p.add_nodes)
            add_edges.extend(p.add_edges)
            remove_edges.extend(p.remove_edges)
            working = working.apply_patch(p)

        for it in merge_items:
            pair = _pair_suffix(it.get("suffix"))
            if pair is None:
                continue
            p = _merge_patch(working, *pair)
            add_nodes.update(p.add_nodes)
            add_edges.extend(p.add_edges)
            remove_edges.extend(p.remove_edges)
            working = working.apply_patch(p)

        for it in route_items:
            pair = _pair_suffix(it.get("suffix"))
            if pair is None:
                continue
            p = _route_patch(working, *pair)
            add_nodes.update(p.add_nodes)
            add_edges.extend(p.add_edges)
            remove_edges.extend(p.remove_edges)
            working = working.apply_patch(p)

        return _diff_patch(graph, working), newest_ts

    return (
        GraphPatch(
            add_nodes=add_nodes,
            remove_nodes=remove_nodes,
            add_edges=add_edges,
            remove_edges=remove_edges,
        ),
        newest_ts,
    )


def _apply_patch_async(graph: EffectGraph, patch: GraphPatch) -> None:
    """Background-thread runner — apply the patch and write the mutation file.

    Single-flight via ``_patch_lock``. A second activation that races
    ahead of an in-flight apply degrades to skipping (logged).
    """

    def _runner() -> None:
        global _last_patched_graph
        if not _patch_lock.acquire(blocking=False):
            log.info("graph-patch consumer: apply skipped (in-flight)")
            return
        try:
            patched = graph.apply_patch(patch)
            _write_mutation(patched)
            _last_patched_graph = patched
            try:
                from shared import director_observability as _do

                emitter = getattr(_do, "emit_graph_patch_applied", None)
                if callable(emitter):
                    emitter(
                        added=list(patch.add_nodes.keys()),
                        removed=list(patch.remove_nodes),
                    )
            except Exception:
                log.debug("emit_graph_patch_applied unavailable", exc_info=True)
        finally:
            _patch_lock.release()

    threading.Thread(target=_runner, name="graph-patch-apply", daemon=True).start()


def process_graph_patch_recruitment() -> bool:
    """Read recent-recruitment.json, dispatch a graph patch on a fresh
    ``node.*`` recruitment.

    Returns True iff a patch was dispatched this tick. Idempotent —
    repeated calls within the cooldown window are no-ops. The actual
    patched graph is written by the background-thread runner.

    Per the architectural directive (memory
    ``feedback_no_presets_use_parametric_modulation``): this is the
    chain-composition primitive. Director never picks a preset; the
    pipeline recruits node patch capabilities and this
    consumer mutates the live graph by surgical patch.
    """
    global _last_activation_t
    if not RECRUITMENT_FILE.exists():
        return False
    try:
        payload = json.loads(RECRUITMENT_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        # Schema drift: a writer producing valid JSON whose root is null,
        # a list, a string, or a number raises AttributeError out of
        # _build_patch_from_recruitment / _family_timestamps. Same shape
        # as the other recent SHM-read fixes (#2638 preset-recruitment).
        return False

    current = _get_current_graph()
    patch, newest_ts = _build_patch_from_recruitment(payload, current)
    if patch.is_empty:
        return False

    # Short-circuit: have we already consumed every entry in this window?
    family_timestamps = _family_timestamps(payload)
    if all(
        family_timestamps[family] <= _last_node_family_ts_seen.get(family, 0.0)
        for family in NODE_PATCH_FAMILIES
    ):
        return False

    # Cooldown gate — chain mutations that arrive faster than the
    # cooldown allows are dropped, same as preset_recruitment_consumer.
    now_mono = time.monotonic()
    if (now_mono - _last_activation_t) < COOLDOWN_S:
        return False

    if current is None:
        log.debug("graph-patch consumer: no current graph, skipping")
        return False

    _apply_patch_async(current, patch)
    _last_activation_t = now_mono
    for family, ts in family_timestamps.items():
        _last_node_family_ts_seen[family] = max(_last_node_family_ts_seen.get(family, 0.0), ts)
    log.info(
        "graph-patch consumer: applied patch (added=%s, removed=%s, newest_ts=%.3f)",
        sorted(patch.add_nodes.keys()),
        sorted(patch.remove_nodes),
        newest_ts,
    )
    return True


def _reset_state_for_tests() -> None:
    """Test helper — clears module-level state between cases."""
    global _last_activation_t, _last_node_family_ts_seen, _last_patched_graph
    global _current_graph_provider
    _last_activation_t = 0.0
    _last_node_family_ts_seen = dict.fromkeys(NODE_PATCH_FAMILIES, 0.0)
    _last_patched_graph = None
    _current_graph_provider = None
    if _patch_lock.locked():
        try:
            _patch_lock.release()
        except RuntimeError:
            pass
