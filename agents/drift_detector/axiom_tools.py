"""Vendored from shared/axiom_tools.py — decision-time axiom compliance tools."""

from __future__ import annotations

import json
import logging
import time

from pydantic_ai import RunContext  # noqa: TC002

from .config import AXIOM_AUDIT_DIR

log = logging.getLogger(__name__)

USAGE_LOG = AXIOM_AUDIT_DIR / "tool-usage.jsonl"


def _log_tool_usage(tool_name: str) -> None:
    """Append a usage entry to the axiom tool usage log."""
    try:
        USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with USAGE_LOG.open("a") as f:
            f.write(json.dumps({"ts": time.time(), "tool": tool_name}) + "\n")
    except OSError:
        pass


async def check_axiom_compliance(
    ctx: RunContext[None],
    situation: str,
    axiom_id: str = "",
    domain: str = "",
) -> str:
    """Check if a decision complies with system axioms.

    Searches the precedent database for similar prior decisions. Returns
    relevant precedents with reasoning and distinguishing facts.

    Args:
        situation: Description of the decision being made.
        axiom_id: Specific axiom to check. If empty, checks all active axioms.
        domain: Include domain axioms for this domain (e.g. "management").
    """
    _log_tool_usage("check_axiom_compliance")
    try:
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
    except ImportError:
        return "Axiom enforcement module not available."
    except Exception as e:
        return f"Error checking axiom compliance: {e}"


async def record_axiom_decision(
    ctx: RunContext[None],
    axiom_id: str,
    situation: str,
    decision: str,
    reasoning: str,
    tier: str = "T2",
    distinguishing_facts: str = "[]",
) -> str:
    """Record a decision about axiom compliance as precedent.

    Called after making significant decisions that touch axioms.

    Args:
        axiom_id: Which axiom this decision relates to.
        situation: What was being decided.
        decision: 'compliant', 'violation', 'edge_case', 'sufficient', or 'insufficient'.
        reasoning: Why this decision was reached.
        tier: Significance tier.
        distinguishing_facts: JSON array of decisive facts.
    """
    _log_tool_usage("record_axiom_decision")
    try:
        from agents._axiom_precedents import Precedent, PrecedentStore

        try:
            facts = json.loads(distinguishing_facts)
        except (json.JSONDecodeError, TypeError):
            facts = [distinguishing_facts] if distinguishing_facts else []

        precedent = Precedent(
            id="",
            axiom_id=axiom_id,
            situation=situation,
            decision=decision,
            reasoning=reasoning,
            tier=tier,
            distinguishing_facts=facts,
            authority="agent",
            created="",
            superseded_by=None,
        )

        store = PrecedentStore()
        pid = store.record(precedent)
        return f"Recorded precedent {pid} (axiom={axiom_id}, decision={decision}, authority=agent)."
    except ImportError:
        return "Axiom precedent store not available."
    except Exception as e:
        log.error("Failed to record axiom decision: %s", e)
        return f"Failed to record precedent: {e}"


def get_axiom_tools() -> list:
    """Return axiom tool functions for agent registration."""
    return [check_axiom_compliance, record_axiom_decision]
