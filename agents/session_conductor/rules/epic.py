"""Epic pipeline rule — detects and drives the multi-phase epic workflow."""

from __future__ import annotations

import logging
import re

from agents.session_conductor.rules import HookEvent, HookResponse, RuleBase
from agents.session_conductor.state import (
    EPIC_PHASE_ORDER,
    MAX_GAP_ROUNDS,
    EpicPhase,
    SessionState,
)
from agents.session_conductor.topology import TopologyConfig

log = logging.getLogger(__name__)

_EPIC_PATTERNS = [
    re.compile(r"\bresearch\s+(any|all)\s+loose\s+ends\b", re.IGNORECASE),
    re.compile(r"\bformal\s+design\s+doc\b", re.IGNORECASE),
    re.compile(r"\bbatched\s+planning\b", re.IGNORECASE),
]

# Filenames that indicate a design doc write
_DESIGN_DOC_RE = re.compile(r"(DESIGN|design[_-]doc|design\.md)", re.IGNORECASE)
# Filenames that indicate a plan doc write
_PLAN_DOC_RE = re.compile(r"(PLAN|plan[_-]doc|plan\.md|implementation[_-]plan)", re.IGNORECASE)


def is_epic_trigger(text: str) -> bool:
    """Return True if the text matches any epic entry pattern."""
    return any(p.search(text) for p in _EPIC_PATTERNS)


def _format_topic_summary(state: SessionState) -> str:
    """Format active topics into a summary for directive messages."""
    if not state.active_topics:
        return "  (no topics tracked)"
    lines = []
    for slug, topic in state.active_topics.items():
        status = (
            "converged" if topic.is_converging() else ("capped" if topic.is_capped() else "active")
        )
        findings = "→".join(str(f) for f in topic.findings_per_round)
        lines.append(f"  • {slug}: {topic.rounds} rounds, {status} ({findings} findings)")
    return "\n".join(lines)


def _format_artifacts(state: SessionState) -> str:
    """List accumulated artifact paths."""
    lines = []
    for topic in state.active_topics.values():
        if topic.prior_file.exists():
            lines.append(f"  • {topic.prior_file}")
    if state.design_doc_path:
        lines.append(f"  • {state.design_doc_path}")
    if state.plan_doc_path:
        lines.append(f"  • {state.plan_doc_path}")
    return "\n".join(lines) if lines else "  (none)"


class EpicRule(RuleBase):
    """Detect epic entry and drive phase transitions through the pipeline."""

    def __init__(self, topology: TopologyConfig, state: SessionState) -> None:
        super().__init__(topology)
        self._state = state

    def on_pre_tool_use(self, event: HookEvent) -> HookResponse | None:
        return None

    def on_post_tool_use(self, event: HookEvent) -> HookResponse | None:
        state = self._state

        # Detect epic entry via Agent tool prompts
        if event.tool_name == "Agent":
            prompt = event.tool_input.get("prompt", "")
            if state.epic_phase is None and is_epic_trigger(prompt):
                log.info("EpicRule: epic entry detected — entering RESEARCH phase")
                state.epic_phase = EpicPhase.RESEARCH
                return HookResponse(
                    action="allow",
                    message=(
                        "=== EPIC PIPELINE ACTIVATED ===\n"
                        "Phase: RESEARCH\n"
                        "Research topics until convergence or 5-round cap, "
                        "then write a design doc to advance."
                    ),
                )

        # Detect design/plan doc writes — capture paths and transition
        if event.tool_name in ("Write", "Edit"):
            file_path: str = event.tool_input.get("file_path", "")
            if state.epic_phase == EpicPhase.DESIGN and _DESIGN_DOC_RE.search(file_path):
                state.design_doc_path = file_path
                state.epic_phase = EpicPhase.DESIGN_GAPS
                state.gap_rounds = 0
                log.info("EpicRule: design doc written — transitioning to DESIGN_GAPS")
                return HookResponse(
                    action="allow",
                    message=(
                        f"=== EPIC: DESIGN → DESIGN_GAPS ===\n"
                        f"Design doc: {file_path}\n"
                        f"Review for gaps (max {MAX_GAP_ROUNDS} rounds), "
                        f"then write an implementation plan."
                    ),
                )
            if state.epic_phase == EpicPhase.PLANNING and _PLAN_DOC_RE.search(file_path):
                state.plan_doc_path = file_path
                state.epic_phase = EpicPhase.PLANNING_GAPS
                state.gap_rounds = 0
                log.info("EpicRule: plan doc written — transitioning to PLANNING_GAPS")
                return HookResponse(
                    action="allow",
                    message=(
                        f"=== EPIC: PLANNING → PLANNING_GAPS ===\n"
                        f"Plan doc: {file_path}\n"
                        f"Review for gaps (max {MAX_GAP_ROUNDS} rounds), "
                        f"then begin implementation."
                    ),
                )

        # Check if a convergence/cap-driven phase transition is needed
        return self._check_phase_transition(state)

    def _check_phase_transition(self, state: SessionState) -> HookResponse | None:
        """Advance phase when research converges, or gap rounds are capped."""
        if state.epic_phase is None:
            return None

        current_idx = EPIC_PHASE_ORDER.index(state.epic_phase)

        # Research phase: advance to DESIGN when all active topics converge or cap
        if state.epic_phase == EpicPhase.RESEARCH:
            if state.active_topics and all(
                t.is_converging() or t.is_capped() for t in state.active_topics.values()
            ):
                log.info("EpicRule: all topics converged — transitioning to DESIGN")
                state.epic_phase = EpicPhase.DESIGN
                topics = _format_topic_summary(state)
                artifacts = _format_artifacts(state)
                return HookResponse(
                    action="allow",
                    message=(
                        f"=== EPIC: RESEARCH → DESIGN ===\n"
                        f"All topics converged:\n{topics}\n\n"
                        f"Artifacts:\n{artifacts}\n\n"
                        f"Next: write a formal design doc (matching *design*.md pattern)."
                    ),
                )

        # Gap phases: advance when gap rounds hit cap
        elif state.epic_phase in (EpicPhase.DESIGN_GAPS, EpicPhase.PLANNING_GAPS):
            if state.gap_rounds >= MAX_GAP_ROUNDS:
                next_phase = EPIC_PHASE_ORDER[current_idx + 1]
                old_phase = state.epic_phase
                state.epic_phase = next_phase
                state.gap_rounds = 0
                log.info(
                    "EpicRule: gap rounds capped — transitioning from %s to %s",
                    old_phase.value,
                    next_phase.value,
                )
                artifacts = _format_artifacts(state)
                if next_phase == EpicPhase.PLANNING:
                    action = "Write an implementation plan (matching *plan*.md pattern)."
                elif next_phase == EpicPhase.IMPLEMENTATION:
                    action = "Begin implementation."
                else:
                    action = f"Proceed with {next_phase.value} phase."
                return HookResponse(
                    action="allow",
                    message=(
                        f"=== EPIC: {old_phase.value.upper()} → {next_phase.value.upper()} ===\n"
                        f"Gap review complete ({MAX_GAP_ROUNDS} rounds).\n\n"
                        f"Artifacts:\n{artifacts}\n\n"
                        f"Next: {action}"
                    ),
                )

        return None
