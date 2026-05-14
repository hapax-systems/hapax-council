"""Continuous preset-space drift engine with smooth transitions.

Traverses the full EffectGraph space — mutating which shader nodes
are active, how they're composed, and what parameters they use.
Uses seeded RNG for reproducible trajectories.

Transitions use a 3-phase approach:
  1. FADE_OUT: interpolate current effect toward passthrough over ~1s
  2. SWAP: replace the shader fragment (invisible at passthrough)
  3. FADE_IN: interpolate new effect from passthrough to target over ~1s
"""

from __future__ import annotations

import copy
import logging
import random
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agents.effect_graph.registry import ShaderRegistry
    from agents.effect_graph.runtime import GraphRuntime

from agents.effect_graph.types import (
    EffectGraph,
    GraphPatch,
    NodeInstance,
)

log = logging.getLogger(__name__)

PROTECTED_NODES = frozenset({"out", "output"})
STRUCTURAL_TYPES = frozenset({"output", "content_layer"})
HEAVY_NODES = frozenset({
    "fluid_sim", "reaction_diffusion", "particle_system",
    "droste", "slitscan", "tunnel", "rutt_etra",
    "displacement_map", "warp",
})
MIN_CHAIN_LEN = 3
MAX_CHAIN_LEN = 5

# For each shader type, define which param(s) control "intensity"
# and what value makes the shader act as passthrough.
# Format: {param: passthrough_value}
PASSTHROUGH_PARAMS: dict[str, dict[str, float]] = {
    "edge_detect":          {"threshold": 1.0},
    "bloom":                {"alpha": 0.0},
    "emboss":               {"strength": 0.0},
    "sharpen":              {"amount": 0.0},
    "colorgrade":           {"saturation": 1.0, "brightness": 1.0, "contrast": 1.0, "sepia": 0.0, "hue_rotate": 0.0},
    "invert":               {"strength": 0.0},
    "vignette":             {"strength": 0.0},
    "noise_overlay":        {"intensity": 0.0},
    "scanlines":            {"opacity": 0.0},
    "chromatic_aberration":  {"intensity": 0.0},
    "posterize":            {"levels": 256.0},
    "glitch_block":         {"intensity": 0.0},
    "thermal":              {"intensity": 0.0},
    "halftone":             {"dot_size": 1.0},
    "kaleidoscope":         {"segments": 1.0},
    "dither":               {"color_levels": 256.0},
    "feedback":             {"decay": 0.0},
    "vhs":                  {"chroma_shift": 0.0},
    "fisheye":              {"strength": 0.0},
    "mirror":               {"position": 0.5},
    "ascii":                {"cell_size": 1.0},
    "pixsort":              {"sort_length": 0.0},
    "nightvision_tint":     {"green_intensity": 0.0, "brightness": 1.0, "contrast": 1.0},
    "threshold":            {"level": 0.0},
    "tile":                 {"count_x": 1.0, "count_y": 1.0},
    "sierpinski_lines":     {"opacity": 0.0},
    "breathing":            {"amplitude": 0.0},
    "echo":                 {"frame_count": 1.0},
    "stutter":              {"freeze_chance": 0.0},
    "voronoi_overlay":      {"edge_width": 0.0},
    "palette":              {"saturation": 1.0, "brightness": 1.0, "contrast": 1.0},
    "postprocess":          {"master_opacity": 0.0},
    "kuwahara":             {"radius": 0.0},
    "diff":                 {"threshold": 1.0},
    "luma_key":             {"threshold": 0.0},
    "color_map":            {"blend": 0.0},
    "drift":                {"amplitude": 0.0},
}

TRANSITION_FRAMES = 30  # ~1s at 30fps per phase


class TransitionPhase(Enum):
    IDLE = auto()
    FADE_OUT = auto()
    FADE_IN = auto()


@dataclass
class PendingTransition:
    """State for an in-progress smooth transition."""
    phase: TransitionPhase = TransitionPhase.IDLE
    target_graph: EffectGraph | None = None
    # Params to interpolate FROM (current values at transition start)
    fade_out_start: dict[int, dict[str, float]] = field(default_factory=dict)
    # Params to interpolate TO during fade-out (passthrough)
    fade_out_end: dict[int, dict[str, float]] = field(default_factory=dict)
    # Params to interpolate FROM after swap (passthrough)
    fade_in_start: dict[int, dict[str, float]] = field(default_factory=dict)
    # Params to interpolate TO during fade-in (target effect values)
    fade_in_end: dict[int, dict[str, float]] = field(default_factory=dict)
    frame: int = 0
    total_frames: int = TRANSITION_FRAMES


@dataclass
class GraphDriftEngine:
    """Walks through preset-graph space via stochastic mutations."""

    registry: ShaderRegistry
    runtime: GraphRuntime
    seed: int = 42
    mutation_interval_s: float = 30.0

    _rng: random.Random = field(init=False)
    _current_graph: EffectGraph | None = field(default=None, init=False)
    _last_mutation_t: float = field(default=0.0, init=False)
    _tick_count: int = field(default=0, init=False)
    _available_types: list[str] = field(default_factory=list, init=False)
    _booted: bool = field(default=False, init=False)
    _transition: PendingTransition = field(default_factory=PendingTransition, init=False)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)
        self._available_types = [
            nt for nt in self.registry.node_types
            if nt not in STRUCTURAL_TYPES
            and nt not in HEAVY_NODES
            and self.registry.get(nt) is not None
            and self.registry.get(nt).glsl_source is not None
        ]
        log.info(
            "GraphDrift: %d swappable node types, interval=%.0fs, seed=%d",
            len(self._available_types), self.mutation_interval_s, self.seed
        )

    def boot(self, initial_graph: EffectGraph) -> None:
        self._current_graph = copy.deepcopy(initial_graph)
        self._last_mutation_t = time.monotonic()
        self._booted = True
        log.info("GraphDrift booted from '%s' (%d nodes)",
                 initial_graph.name, len(initial_graph.nodes))

    def tick(self, slot_pipeline: Any = None) -> bool:
        """Called every frame. Returns True if visual state changed."""
        if not self._booted or self._current_graph is None:
            return False

        self._tick_count += 1

        # Handle in-progress transition
        if self._transition.phase != TransitionPhase.IDLE:
            return self._advance_transition(slot_pipeline)

        # Check if it's time for a new mutation
        now = time.monotonic()
        elapsed = now - self._last_mutation_t
        if elapsed < self.mutation_interval_s:
            return False

        # Start a new mutation transition
        try:
            mutated = self._mutate_graph()
            if mutated is None:
                self._last_mutation_t = now
                return False

            # Validate by attempting compilation
            self.runtime._compiler.compile(mutated)

            # Start smooth transition
            self._begin_transition(mutated, slot_pipeline)
            return True
        except Exception:
            log.warning("GraphDrift mutation failed, skipping", exc_info=True)
            self._last_mutation_t = now
            return False

    def _begin_transition(self, target_graph: EffectGraph, sp: Any) -> None:
        """Start a smooth fade-out → swap → fade-in transition."""
        self._transition = PendingTransition(
            phase=TransitionPhase.FADE_OUT,
            target_graph=target_graph,
            frame=0,
            total_frames=TRANSITION_FRAMES,
        )

        if sp is None:
            # No slot pipeline — do hard swap
            self._complete_swap()
            return

        # Capture current param values for interpolation targets
        current_graph = self._current_graph
        if current_graph is None:
            self._complete_swap()
            return

        # For fade-out: interpolate current node params toward passthrough
        for i, node_type in enumerate(sp._slot_assignments):
            if node_type is None or node_type in STRUCTURAL_TYPES:
                continue
            current_params = dict(sp._slot_base_params[i])
            passthrough = PASSTHROUGH_PARAMS.get(node_type, {})
            if passthrough:
                # Only interpolate params that have passthrough definitions
                start = {k: current_params.get(k, v) for k, v in passthrough.items()}
                self._transition.fade_out_start[i] = start
                self._transition.fade_out_end[i] = dict(passthrough)

        # Pre-compute fade-in targets from the new graph's node params
        chain = self._get_chain_node_ids(target_graph)
        for idx, node_id in enumerate(chain):
            if node_id not in target_graph.nodes:
                continue
            node = target_graph.nodes[node_id]
            if node.type in STRUCTURAL_TYPES:
                continue
            defn = self.registry.get(node.type)
            if defn is None:
                continue
            # Target = node params (overrides) merged with registry defaults
            target_params = {}
            for k, p in defn.params.items():
                if p.default is not None:
                    target_params[k] = float(p.default) if isinstance(p.default, (int, float)) else p.default
            target_params.update({k: v for k, v in node.params.items()
                                  if isinstance(v, (int, float))})

            passthrough = PASSTHROUGH_PARAMS.get(node.type, {})
            if passthrough:
                self._transition.fade_in_start[idx] = dict(passthrough)
                fade_end = {k: target_params.get(k, v) for k, v in passthrough.items()}
                self._transition.fade_in_end[idx] = fade_end

        chain_types = self._get_chain_types(target_graph)
        log.info("GraphDrift: fade-out started → target chain: %s",
                 " → ".join(chain_types))

    def _advance_transition(self, sp: Any) -> bool:
        """Advance one frame of the transition animation."""
        t = self._transition
        t.frame += 1
        progress = min(1.0, t.frame / max(1, t.total_frames))

        if t.phase == TransitionPhase.FADE_OUT:
            # Interpolate toward passthrough and flush to GPU
            if sp is not None:
                for slot_idx, start in t.fade_out_start.items():
                    end = t.fade_out_end.get(slot_idx, {})
                    for key in start:
                        if key in end:
                            v = start[key] + (end[key] - start[key]) * progress
                            sp._slot_base_params[slot_idx][key] = v
                            if hasattr(sp, "_slot_preset_params"):
                                sp._slot_preset_params[slot_idx][key] = v
                    # Flush this slot's uniforms to GPU immediately
                    if slot_idx < sp.num_slots and sp._slot_assignments[slot_idx] is not None:
                        sp._apply_glfeedback_uniforms(slot_idx)

            if t.frame >= t.total_frames:
                # Fade-out complete — do the shader swap
                self._complete_swap()
                # Start fade-in
                t.phase = TransitionPhase.FADE_IN
                t.frame = 0

                # Apply passthrough params to new slots
                if sp is not None:
                    for slot_idx, params in t.fade_in_start.items():
                        if slot_idx < sp.num_slots and sp._slot_assignments[slot_idx] is not None:
                            for key, val in params.items():
                                sp._slot_base_params[slot_idx][key] = val
                                if hasattr(sp, "_slot_preset_params"):
                                    sp._slot_preset_params[slot_idx][key] = val
            return True

        elif t.phase == TransitionPhase.FADE_IN:
            # Interpolate from passthrough toward target and flush to GPU
            if sp is not None:
                for slot_idx, start in t.fade_in_start.items():
                    end = t.fade_in_end.get(slot_idx, {})
                    if slot_idx >= sp.num_slots or sp._slot_assignments[slot_idx] is None:
                        continue
                    for key in start:
                        if key in end:
                            v = start[key] + (end[key] - start[key]) * progress
                            sp._slot_base_params[slot_idx][key] = v
                            if hasattr(sp, "_slot_preset_params"):
                                sp._slot_preset_params[slot_idx][key] = v
                    # Flush this slot's uniforms to GPU immediately
                    if slot_idx < sp.num_slots and sp._slot_assignments[slot_idx] is not None:
                        sp._apply_glfeedback_uniforms(slot_idx)

            if t.frame >= t.total_frames:
                # Transition complete
                t.phase = TransitionPhase.IDLE
                self._last_mutation_t = time.monotonic()
                chain_types = self._get_chain_types(self._current_graph) if self._current_graph else []
                log.warning("GRAPH_DRIFT transition complete: chain: %s",
                            " → ".join(chain_types))
            return True

        return False

    def _complete_swap(self) -> None:
        """Execute the shader swap (load new graph via runtime)."""
        t = self._transition
        if t.target_graph is None:
            return
        try:
            self.runtime.load_graph(t.target_graph)
            self._current_graph = copy.deepcopy(t.target_graph)
            chain = self._get_chain_types(t.target_graph)
            log.info("GraphDrift: shader swap executed → %s", " → ".join(chain))
        except Exception:
            log.warning("GraphDrift: swap failed", exc_info=True)
            t.phase = TransitionPhase.IDLE
            self._last_mutation_t = time.monotonic()

    # ── Mutation operations (unchanged) ─────────────────────────

    def _mutate_graph(self) -> EffectGraph | None:
        g = self._current_graph
        if g is None:
            return None

        chain = self._get_chain_node_ids(g)
        chain_types = [g.nodes[nid].type for nid in chain if nid in g.nodes]

        mutations = ["swap"]
        if len(chain) < MAX_CHAIN_LEN:
            mutations.append("add")
        if len(chain) > MIN_CHAIN_LEN:
            mutations.append("remove")

        op = self._rng.choice(mutations)

        if op == "swap":
            return self._op_swap_node(g, chain, chain_types)
        elif op == "add":
            return self._op_add_node(g, chain)
        elif op == "remove":
            return self._op_remove_node(g, chain, chain_types)
        return None

    def _op_swap_node(self, g, chain, chain_types):
        swappable = [
            (i, nid) for i, nid in enumerate(chain)
            if nid in g.nodes and g.nodes[nid].type not in STRUCTURAL_TYPES
        ]
        if not swappable:
            return None
        idx, node_id = self._rng.choice(swappable)
        old_type = g.nodes[node_id].type
        candidates = [t for t in self._available_types
                      if t != old_type and t not in chain_types]
        if not candidates:
            return None
        new_type = self._rng.choice(candidates)
        defn = self.registry.get(new_type)
        default_params = {}
        if defn:
            default_params = {
                k: p.default for k, p in defn.params.items()
                if p.default is not None
            }
        new_node = NodeInstance(type=new_type, params=default_params)
        patch = GraphPatch(add_nodes={node_id: new_node})
        mutated = g.apply_patch(patch)
        mutated = mutated.model_copy(update={"name": f"drift_{int(time.time())}"})
        log.info("GraphDrift swap: %s %s → %s", node_id, old_type, new_type)
        return mutated

    def _op_add_node(self, g, chain):
        chain_types = [g.nodes[nid].type for nid in chain if nid in g.nodes]
        candidates = [t for t in self._available_types if t not in chain_types]
        if not candidates:
            return None
        new_type = self._rng.choice(candidates)
        defn = self.registry.get(new_type)
        default_params = {}
        if defn:
            default_params = {k: p.default for k, p in defn.params.items()
                              if p.default is not None}
        new_id = f"drift_{new_type}_{int(time.time()) % 10000}"
        if len(chain) < 2:
            return None
        insert_idx = self._rng.randint(1, len(chain) - 1)
        before_id = chain[insert_idx - 1]
        after_id = chain[insert_idx]
        new_node = NodeInstance(type=new_type, params=default_params)
        patch = GraphPatch(
            add_nodes={new_id: new_node},
            remove_edges=[[before_id, after_id]],
            add_edges=[[before_id, new_id], [new_id, after_id]],
        )
        mutated = g.apply_patch(patch)
        mutated = mutated.model_copy(update={"name": f"drift_{int(time.time())}"})
        log.info("GraphDrift add: %s (%s) between %s and %s",
                 new_id, new_type, before_id, after_id)
        return mutated

    def _op_remove_node(self, g, chain, chain_types):
        removable = [
            (i, nid) for i, nid in enumerate(chain)
            if nid in g.nodes and g.nodes[nid].type not in STRUCTURAL_TYPES
            and nid not in PROTECTED_NODES
        ]
        if not removable:
            return None
        idx, node_id = self._rng.choice(removable)
        edges = g.parsed_edges
        predecessors = [e.source_node for e in edges if e.target_node == node_id]
        successors = [e.target_node for e in edges if e.source_node == node_id]
        if not predecessors or not successors:
            return None
        pred, succ = predecessors[0], successors[0]
        patch = GraphPatch(remove_nodes=[node_id], add_edges=[[pred, succ]])
        mutated = g.apply_patch(patch)
        mutated = mutated.model_copy(update={"name": f"drift_{int(time.time())}"})
        log.info("GraphDrift remove: %s (%s), reconnect %s → %s",
                 node_id, g.nodes[node_id].type, pred, succ)
        return mutated

    def _get_chain_node_ids(self, g):
        edges = g.parsed_edges
        children: dict[str, list[str]] = {}
        for e in edges:
            children.setdefault(e.source_node, []).append(e.target_node)
        chain = []
        current = "@live"
        visited = set()
        while current in children and current not in visited:
            visited.add(current)
            nexts = children[current]
            if not nexts:
                break
            nxt = nexts[0]
            if nxt in g.nodes and g.nodes[nxt].type != "output":
                chain.append(nxt)
            current = nxt
        return chain

    def _get_chain_types(self, g):
        ids = self._get_chain_node_ids(g)
        return [g.nodes[nid].type for nid in ids if nid in g.nodes]
