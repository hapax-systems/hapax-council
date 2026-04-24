"""Autonomous narrative director (ytb-SS1 Phase 1).

During operator-absent stretches, this background task composes
substantive narrative every 2-3 min from current state (active
programme + recent chronicle events + stimmung + director activity)
and emits it via the existing Daimonion impingement → CPAL →
``ConversationPipeline.generate_spontaneous_speech()`` → TTS path.

Architecture A from the design draft
(``~/.cache/hapax/relay/context/2026-04-24-alpha-ytb-ss1-design-draft.md``):
no new tier, no new intent_family, no new TTS plumbing — just emit an
``Impingement`` with ``source="autonomous_narrative"`` and let the
existing pipeline carry it through. Audio architecture (PRs #1269
master limiter, #1273 sidechain ducking) applies automatically.

Default OFF behind ``HAPAX_AUTONOMOUS_NARRATIVE_ENABLED=0``. The
operator opts in when ready.

Spec: ``ytb-SS1`` cc-task; design draft cited above.
"""

from agents.hapax_daimonion.autonomous_narrative.loop import autonomous_narrative_loop

__all__ = ["autonomous_narrative_loop"]
