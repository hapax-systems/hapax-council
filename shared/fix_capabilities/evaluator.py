"""LLM evaluator agent for health fix proposals.

Receives a failing health check, probe data, and available actions.
Uses pydantic-ai to select the best action and return a FixProposal.
"""
from __future__ import annotations

import logging
from typing import Optional

from pydantic_ai import Agent

from agents.health_monitor import CheckResult, Status
from shared.config import get_model
from shared.fix_capabilities.base import Action, FixProposal, ProbeResult, Safety

log = logging.getLogger(__name__)

# ── System prompt ────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a health-fix evaluator for a single-operator LLM workstation.

Given a failing health check and available fix actions, you must:

1. Pick exactly ONE action from the available list that best addresses the failure.
2. Fill the action's params using data from the probe results.
3. Set the safety field to match the action's safety classification.
4. If no action fits the problem, set action_name to "no_action".

Return a FixProposal with:
- capability: the probe's capability name
- action_name: the chosen action's name (or "no_action")
- params: a dict of parameters extracted from probe data
- rationale: a brief explanation of why this action was chosen
- safety: "safe" or "destructive" matching the action's classification

Be conservative. Only propose destructive actions when safe alternatives cannot work.
"""

# ── Agent ────────────────────────────────────────────────────────────────────

_evaluator_agent = Agent(
    model=get_model("balanced"),
    output_type=FixProposal,
    system_prompt=_SYSTEM_PROMPT,
)


# ── Prompt builder ───────────────────────────────────────────────────────────

def _build_prompt(
    check: CheckResult,
    probe: ProbeResult,
    actions: list[Action],
) -> str:
    """Assemble the user prompt from check, probe, and available actions."""
    lines = [
        "## Failing Health Check",
        f"- Name: {check.name}",
        f"- Group: {check.group}",
        f"- Status: {check.status.value}",
        f"- Message: {check.message}",
    ]
    if check.detail:
        lines.append(f"- Detail: {check.detail}")
    if check.remediation:
        lines.append(f"- Remediation hint: {check.remediation}")

    lines.append("")
    lines.append("## Probe Data")
    lines.append(probe.summary())

    lines.append("")
    lines.append("## Available Actions")
    for action in actions:
        safety_tag = f"[{action.safety.value}]"
        desc = f" — {action.description}" if action.description else ""
        lines.append(f"- {action.name} {safety_tag}{desc}")

    lines.append("")
    lines.append(f"Capability: {probe.capability}")

    return "\n".join(lines)


# ── Public API ───────────────────────────────────────────────────────────────

async def evaluate_check(
    check: CheckResult,
    probe: ProbeResult,
    actions: list[Action],
) -> Optional[FixProposal]:
    """Evaluate a failing check and return a fix proposal, or None.

    Returns None if:
    - The check is healthy
    - No actions are available
    - The LLM proposes "no_action"
    - Any error occurs during evaluation
    """
    if check.status == Status.HEALTHY:
        return None

    if not actions:
        return None

    try:
        prompt = _build_prompt(check, probe, actions)
        result = await _evaluator_agent.run(prompt)
        proposal = result.output

        if proposal.action_name == "no_action":
            log.info("Evaluator chose no_action for check %s", check.name)
            return None

        return proposal
    except Exception:
        log.warning("Evaluator failed for check %s", check.name, exc_info=True)
        return None
