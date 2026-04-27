"""Autonomous narrative director (ytb-SS1).

Composes substantive first-system narration from current state (active
programme + recent chronicle events + stimmung + director activity) and
emits it via the Daimonion impingement → CPAL → TTS path.

Architecture: narration is driven by an *endogenous drive* evaluator
(``narrative_drive.py``) that accumulates internal pressure and emits
drive impingements to the DMN bus when a Bayesian posterior crosses a
stochastic threshold. The AffordancePipeline then recruits
``narration.autonomous_first_system`` from those impingements, and
``run_loops_aux._dispatch_autonomous_narration()`` calls
``compose.compose_narrative()`` + ``emit.emit_narrative()``.

Drive pressure is modulated by: time since last emission (exponential
accumulation), chronicle richness, stimmung trajectory, operator
presence, programme role affinity, and learned Thompson sampling priors.
Cadence emerges from these Bayesian factors + refractory inhibition
(120s), not from hardcoded gates. The standalone polling loop + 5
hardcoded gates (loop.py, gates.py) were retired per
feedback_no_expert_system_rules.

Design: docs/research/2026-04-27-endogenous-drive-role-semantic-surfacing.md

Default ON per directive feedback_features_on_by_default 2026-04-25T20:55Z;
opt-out via ``HAPAX_AUTONOMOUS_NARRATIVE_ENABLED=0`` (checked in compose.py).

Spec: ``ytb-SS1`` cc-task.
"""

__all__: list[str] = []
