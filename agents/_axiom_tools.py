# shared/axiom_tools.py
"""Decision-time axiom compliance tools for Pydantic AI agents.

Provides two tools that LLM agents call during reasoning:
  - check_axiom_compliance: Search precedents for similar situations
  - record_axiom_decision: Record a new axiom-application decision

Usage:
    from shared.axiom_tools import get_axiom_tools

    for tool_fn in get_axiom_tools():
        agent.tool(tool_fn)
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from pydantic_ai import RunContext  # noqa: TC002 — needed at runtime for tool registration

from agents._config import AXIOM_AUDIT_DIR

log = logging.getLogger(__name__)

USAGE_LOG = AXIOM_AUDIT_DIR / "tool-usage.jsonl"


def _log_tool_usage(tool_name: str) -> None:
    """Append a usage entry to the axiom tool usage log."""
    try:
        USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with USAGE_LOG.open("a") as f:
            f.write(json.dumps({"ts": time.time(), "tool": tool_name}) + "\n")
    except OSError:
        pass  # Never fail the tool call over logging


async def check_axiom_compliance(
    ctx: RunContext[Any],
    situation: str,
    axiom_id: str = "",
    domain: str = "",
) -> str:
    """Check if a decision complies with system axioms.

    Thin Pydantic AI wrapper over shared.axiom_enforcement.check_full().
    Searches the precedent database for similar prior decisions. Returns
    relevant precedents with reasoning and distinguishing facts. If no
    close precedent exists, returns axiom text and derived implications.

    Args:
        situation: Description of the decision being made.
        axiom_id: Specific axiom to check. If empty, checks all active axioms.
        domain: Include domain axioms for this domain (e.g. "management").
            Constitutional axioms are always included (supremacy clause).
    """
    _log_tool_usage("check_axiom_compliance")
    from shared.axiom_enforcement import check_full

    result = check_full(situation, axiom_id=axiom_id, domain=domain)

    if result.checked_rules == 0 and not result.violations:
        return "No axioms defined in registry."

    if result.compliant:
        return f"Compliant. Checked {result.checked_rules} rules across axioms."

    lines = [f"Non-compliant ({len(result.violations)} violation(s)):"]
    for v in result.violations:
        lines.append(f"  - {v}")
    if result.axiom_ids:
        lines.append(f"Axioms involved: {', '.join(result.axiom_ids)}")
    return "\n".join(lines)


async def record_axiom_decision(
    ctx: RunContext[Any],
    axiom_id: str,
    situation: str,
    decision: str,
    reasoning: str,
    tier: str = "T2",
    distinguishing_facts: str = "[]",
) -> str:
    """Record a decision about axiom compliance as precedent.

    Called after making significant decisions that touch axioms.
    Recorded with authority='agent' — pending operator review.

    Args:
        axiom_id: Which axiom this decision relates to.
        situation: What was being decided.
        decision: 'compliant', 'violation', 'edge_case', 'sufficient', or 'insufficient'.
        reasoning: Why this decision was reached.
        tier: Significance tier — T0, T1, T2, or T3.
        distinguishing_facts: JSON array of decisive facts.
    """
    _log_tool_usage("record_axiom_decision")
    from agents._axiom_precedents import Precedent, PrecedentStore

    try:
        facts = json.loads(distinguishing_facts)
    except (json.JSONDecodeError, TypeError):
        facts = [distinguishing_facts] if distinguishing_facts else []

    precedent = Precedent(
        id="",  # auto-generated
        axiom_id=axiom_id,
        situation=situation,
        decision=decision,
        reasoning=reasoning,
        tier=tier,
        distinguishing_facts=facts,
        authority="agent",
        created="",  # auto-generated
        superseded_by=None,
    )

    try:
        store = PrecedentStore()
        pid = store.record(precedent)
        return f"Recorded precedent {pid} (axiom={axiom_id}, decision={decision}, authority=agent)."
    except Exception as e:
        log.error("Failed to record axiom decision: %s", e)
        return f"Failed to record precedent: {e}"


def get_axiom_tools() -> list:
    """Return axiom tool functions for agent registration."""
    return [check_axiom_compliance, record_axiom_decision]
