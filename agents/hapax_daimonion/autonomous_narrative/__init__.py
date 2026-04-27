"""Autonomous narrative director (ytb-SS1).

Composes substantive first-system narration from current state (active
programme + recent chronicle events + stimmung + director activity) and
emits it via the Daimonion impingement → CPAL → TTS path.

Architecture: narration is recruited via the AffordancePipeline
(``narration.autonomous_first_system`` in the affordance registry).
When the pipeline's cosine-similarity + Thompson scoring selects
narration, ``run_loops_aux._dispatch_autonomous_narration()`` calls
``compose.compose_narrative()`` + ``emit.emit_narrative()``.

Cadence emerges from base_level decay + refractory inhibition (120s)
rather than hardcoded gates. The standalone polling loop + 5 hardcoded
gates (loop.py, gates.py) were retired per feedback_no_expert_system_rules.

Default ON per directive feedback_features_on_by_default 2026-04-25T20:55Z;
opt-out via ``HAPAX_AUTONOMOUS_NARRATIVE_ENABLED=0`` (checked in compose.py).

Spec: ``ytb-SS1`` cc-task.
"""

__all__: list[str] = []
