"""Reverie affordance registration — shader nodes, content types, legacy capabilities.

The system discovers which visual effects are relevant to each impingement
via cosine similarity in Qdrant, not prescribed semantic mappings.
"""

from __future__ import annotations

import logging

from agents._affordance import CapabilityRecord, OperationalProperties

log = logging.getLogger("reverie.affordances")

# 12 shader node affordances — expressive descriptions for embedding
SHADER_NODE_AFFORDANCES = [
    ("node.noise_gen", "procedural texture, substrate, continuous field"),
    ("node.reaction_diffusion", "self-organizing emergent spatial patterns, regime-sensitive"),
    ("node.colorgrade", "palette regime, color world shift, atmospheric tone"),
    ("node.drift", "spatial displacement, coherence modulation, gentle warping"),
    ("node.breathing", "rhythmic pulse, expansion and contraction, life cadence"),
    ("node.feedback", "temporal persistence, afterimage, dwelling trace"),
    ("node.content_layer", "content materialization, imagination surface, phenomenology"),
    ("node.postprocess", "final composition, enclosure, vignette, sediment"),
    ("node.fluid_sim", "directional flow with inertia, vorticity, viscous movement"),
    ("node.trail", "motion history, velocity as visual thickness, temporal accumulation"),
    ("node.voronoi_overlay", "spatial partitioning, organic boundaries, cellular territory"),
    ("node.echo", "discrete temporal copies, ghosting, fading repetition"),
]

# Perception content — observe/sense the environment (FAST tier)
PERCEPTION_AFFORDANCES: list[tuple[str, str, OperationalProperties]] = [
    (
        "content.overhead_perspective",
        "Observe workspace from above, providing spatial context for physical activity and object arrangement",
        OperationalProperties(latency_class="fast", medium="visual"),
    ),
    (
        "content.desk_perspective",
        "Observe the operator's face, hands, and immediate work surface at close range",
        OperationalProperties(latency_class="fast", medium="visual"),
    ),
    (
        "content.operator_perspective",
        "Observe the operator directly, capturing presence and expression",
        OperationalProperties(latency_class="fast", medium="visual"),
    ),
]

# Expression content — materialize imagination as visual (SLOW tier)
CONTENT_AFFORDANCES: list[tuple[str, str, OperationalProperties]] = [
    (
        "content.narrative_text",
        "Render imagination narrative as visible text, making thought legible in the visual field",
        OperationalProperties(latency_class="slow", medium="visual"),
    ),
    (
        "content.episodic_recall",
        "Recall and visualize past experiences similar to the current moment from episodic memory",
        OperationalProperties(latency_class="slow", medium="visual"),
    ),
    (
        "content.knowledge_recall",
        "Search and visualize relevant knowledge from ingested documents and notes",
        OperationalProperties(latency_class="slow", medium="visual"),
    ),
    (
        "content.profile_recall",
        "Recall and visualize known facts about the operator's preferences and patterns",
        OperationalProperties(latency_class="slow", medium="visual"),
    ),
    (
        "content.waveform_viz",
        "Sense acoustic energy and render sound as visible waveform shape",
        OperationalProperties(latency_class="fast", medium="visual"),
    ),
]

ALL_CONTENT_AFFORDANCES = PERCEPTION_AFFORDANCES + CONTENT_AFFORDANCES

# Legacy capabilities for backward compat with DMN dispatch
LEGACY_AFFORDANCES = [
    ("shader_graph", "Activate shader graph effects from imagination"),
    ("visual_chain", "Modulate visual chain from stimmung/evaluative"),
    ("fortress_visual_response", "Visual pipeline for fortress crises"),
]


def build_reverie_pipeline_affordances() -> list[CapabilityRecord]:
    """Build all CapabilityRecord objects for Reverie affordances."""
    records: list[CapabilityRecord] = []
    for name, desc in SHADER_NODE_AFFORDANCES:
        records.append(
            CapabilityRecord(
                name=name,
                description=desc,
                daemon="reverie",
                operational=OperationalProperties(latency_class="realtime", medium="visual"),
            )
        )
    for name, desc, ops in ALL_CONTENT_AFFORDANCES:
        records.append(
            CapabilityRecord(
                name=name,
                description=desc,
                daemon="reverie",
                operational=ops,
            )
        )
    for name, desc in LEGACY_AFFORDANCES:
        records.append(
            CapabilityRecord(
                name=name,
                description=desc,
                daemon="reverie",
                operational=OperationalProperties(latency_class="realtime", medium="visual"),
            )
        )
    return records


def build_reverie_pipeline():
    """Build the affordance pipeline with all Reverie affordances registered in Qdrant."""
    from agents._affordance_pipeline import AffordancePipeline

    p = AffordancePipeline()
    records = build_reverie_pipeline_affordances()
    registered = 0
    for rec in records:
        if p.index_capability(rec):
            registered += 1
    log.info("Registered %d/%d Reverie affordances in Qdrant", registered, len(records))
    return p
