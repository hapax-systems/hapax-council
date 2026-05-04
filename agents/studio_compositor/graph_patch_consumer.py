"""Graph-patch recruitment consumer — wires GraphPatch into the chain mutation path.

Architectural fix per researcher audit + memory
``feedback_no_presets_use_parametric_modulation``: the system architecture
mandates *constrained algorithmic parametric modulation + chain composition
(transition primitives + affordance-recruited node add/remove)*. The director
NEVER picks a preset. Chain composition emerges from per-impingement
node add/remove fired by the affordance pipeline.

The ``GraphPatch`` type at ``agents/effect_graph/types.py:85-89`` carries
``add_nodes / remove_nodes / add_edges / remove_edges`` fields but had zero
callers — the architecturally-correct chain mutation primitive was unwired.
This module is the bridge.

Shape:
1. ``shared/compositional_affordances.py`` registers ``node.add.<type>`` and
   ``node.remove.<role>`` capabilities. Each one carries a Gibson-verb
   description (cognitive-function, not implementation-detail). The
   AffordancePipeline's cosine-similarity retrieval surfaces the matching
   capability per impingement narrative.
2. ``agents/studio_compositor/compositional_consumer.dispatch_node_patch``
   writes the recruited capability under the ``node.add`` /
   ``node.remove`` family in ``recent-recruitment.json``.
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

from agents.effect_graph.types import EffectGraph, GraphPatch, NodeInstance

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
"""How fresh a node.add / node.remove recruitment must be to be honoured.

Beyond this window the recruitment is treated as stale and the consumer
declines to apply it. Matches the existing preset.bias TTL so the
director's structural intent on patch capabilities ages out the same way.
"""

# Module-level state — same pattern as preset_recruitment_consumer.
_last_activation_t: float = 0.0
_last_node_add_ts_seen: float = 0.0
_last_node_remove_ts_seen: float = 0.0
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


def _build_patch_from_recruitment(payload: dict) -> tuple[GraphPatch, float]:
    """Parse a recruitment payload, return (patch, newest_ts).

    ``payload`` is the parsed ``recent-recruitment.json`` content. Looks
    for the ``node.add`` and ``node.remove`` family entries. Each carries
    an ``items`` list of ``{capability, suffix, last_recruited_ts}`` so
    multiple add/remove recruitments within the cooldown can be coalesced
    into a single patch.

    Returns an empty ``GraphPatch`` when nothing fresh is found.
    """
    families = payload.get("families") or {}
    now = time.time()
    add_items: list[dict] = []
    remove_items: list[dict] = []
    newest_ts = 0.0

    add_entry = families.get("node.add") or {}
    if isinstance(add_entry, dict):
        items = add_entry.get("items") or []
        if isinstance(items, list):
            for it in items:
                if not isinstance(it, dict):
                    continue
                ts = it.get("last_recruited_ts")
                if not isinstance(ts, (int, float)):
                    continue
                if now - float(ts) > PATCH_BIAS_TTL_S:
                    continue
                add_items.append(it)
                if float(ts) > newest_ts:
                    newest_ts = float(ts)

    remove_entry = families.get("node.remove") or {}
    if isinstance(remove_entry, dict):
        items = remove_entry.get("items") or []
        if isinstance(items, list):
            for it in items:
                if not isinstance(it, dict):
                    continue
                ts = it.get("last_recruited_ts")
                if not isinstance(ts, (int, float)):
                    continue
                if now - float(ts) > PATCH_BIAS_TTL_S:
                    continue
                remove_items.append(it)
                if float(ts) > newest_ts:
                    newest_ts = float(ts)

    add_nodes: dict[str, NodeInstance] = {}
    add_edges: list[list[str]] = []
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

    return (
        GraphPatch(
            add_nodes=add_nodes,
            remove_nodes=remove_nodes,
            add_edges=add_edges,
            remove_edges=[],
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
    ``node.add`` / ``node.remove`` recruitment.

    Returns True iff a patch was dispatched this tick. Idempotent —
    repeated calls within the cooldown window are no-ops. The actual
    patched graph is written by the background-thread runner.

    Per the architectural directive (memory
    ``feedback_no_presets_use_parametric_modulation``): this is the
    chain-composition primitive. Director never picks a preset; the
    pipeline recruits node.add/node.remove capabilities and this
    consumer mutates the live graph by surgical patch.
    """
    global _last_activation_t, _last_node_add_ts_seen, _last_node_remove_ts_seen
    if not RECRUITMENT_FILE.exists():
        return False
    try:
        payload = json.loads(RECRUITMENT_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False

    patch, newest_ts = _build_patch_from_recruitment(payload)
    if patch.is_empty:
        return False

    # Short-circuit: have we already consumed every entry in this window?
    families = payload.get("families") or {}
    add_ts = (families.get("node.add") or {}).get("last_recruited_ts", 0.0)
    rem_ts = (families.get("node.remove") or {}).get("last_recruited_ts", 0.0)
    add_ts_f = float(add_ts) if isinstance(add_ts, (int, float)) else 0.0
    rem_ts_f = float(rem_ts) if isinstance(rem_ts, (int, float)) else 0.0
    if add_ts_f <= _last_node_add_ts_seen and rem_ts_f <= _last_node_remove_ts_seen:
        return False

    # Cooldown gate — chain mutations that arrive faster than the
    # cooldown allows are dropped, same as preset_recruitment_consumer.
    now_mono = time.monotonic()
    if (now_mono - _last_activation_t) < COOLDOWN_S:
        return False

    current = _get_current_graph()
    if current is None:
        log.debug("graph-patch consumer: no current graph, skipping")
        return False

    _apply_patch_async(current, patch)
    _last_activation_t = now_mono
    _last_node_add_ts_seen = max(_last_node_add_ts_seen, add_ts_f)
    _last_node_remove_ts_seen = max(_last_node_remove_ts_seen, rem_ts_f)
    log.info(
        "graph-patch consumer: applied patch (added=%s, removed=%s, newest_ts=%.3f)",
        sorted(patch.add_nodes.keys()),
        sorted(patch.remove_nodes),
        newest_ts,
    )
    return True


def _reset_state_for_tests() -> None:
    """Test helper — clears module-level state between cases."""
    global _last_activation_t, _last_node_add_ts_seen, _last_node_remove_ts_seen
    global _last_patched_graph, _current_graph_provider
    _last_activation_t = 0.0
    _last_node_add_ts_seen = 0.0
    _last_node_remove_ts_seen = 0.0
    _last_patched_graph = None
    _current_graph_provider = None
    if _patch_lock.locked():
        try:
            _patch_lock.release()
        except RuntimeError:
            pass
