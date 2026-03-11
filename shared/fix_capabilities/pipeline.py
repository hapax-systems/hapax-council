"""Fix pipeline orchestrator.

Processes failing health checks through the probe → evaluate → validate → execute
flow, wiring together capabilities, the LLM evaluator, and notifications.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from agents.health_monitor import CheckResult, HealthReport, Status
from shared.fix_capabilities import get_capability_for_group
from shared.fix_capabilities.base import ExecutionResult, FixProposal
from shared.fix_capabilities.evaluator import evaluate_check
from shared.notify import send_notification

log = logging.getLogger(__name__)


# ── Models ───────────────────────────────────────────────────────────────────


class FixOutcome(BaseModel):
    """Outcome of processing a single failing check through the pipeline."""

    check_name: str
    proposal: FixProposal | None = None
    executed: bool = False
    notified: bool = False
    execution_result: ExecutionResult | None = None
    rejected_reason: str | None = None


class PipelineResult(BaseModel):
    """Aggregate result of running the fix pipeline over a health report."""

    total: int = 0
    outcomes: list[FixOutcome] = Field(default_factory=list)

    @property
    def executed_count(self) -> int:
        """Number of outcomes that were executed."""
        return sum(1 for o in self.outcomes if o.executed)

    @property
    def notified_count(self) -> int:
        """Number of outcomes where notifications were sent."""
        return sum(1 for o in self.outcomes if o.notified)


# ── Pipeline ─────────────────────────────────────────────────────────────────


async def run_fix_pipeline(
    report: HealthReport,
    *,
    mode: str = "apply",
) -> PipelineResult:
    """Run the fix pipeline over all failing checks in a health report.

    Args:
        report: The health report to process.
        mode: "apply" to execute safe fixes, "dry_run" to skip execution.

    Returns:
        PipelineResult with outcomes for each processed check.
    """
    result = PipelineResult()

    # Collect all failing checks across groups
    failing: list[CheckResult] = []
    for group in report.groups:
        for check in group.checks:
            if check.status != Status.HEALTHY:
                failing.append(check)

    for check in failing:
        # Look up capability
        cap = get_capability_for_group(check.group)
        if cap is None:
            log.debug("No capability for group %s, skipping %s", check.group, check.name)
            continue

        # Gather context (probe)
        try:
            probe = await cap.gather_context(check)
        except Exception:
            log.warning("gather_context failed for check %s", check.name, exc_info=True)
            continue

        # Evaluate — ask LLM for a fix proposal
        proposal = await evaluate_check(check, probe, cap.available_actions())
        if proposal is None:
            log.debug("No proposal for check %s, skipping", check.name)
            continue

        # From here we have a proposal, so increment total
        result.total += 1

        # Validate
        if not cap.validate(proposal):
            result.outcomes.append(
                FixOutcome(
                    check_name=check.name,
                    proposal=proposal,
                    rejected_reason=f"Validation failed for {proposal.action_name}",
                )
            )
            continue

        # Dry-run: record but don't execute
        if mode == "dry_run":
            result.outcomes.append(FixOutcome(check_name=check.name, proposal=proposal))
            continue

        # Execute or notify based on safety
        if proposal.is_safe():
            exec_result = await cap.execute(proposal)
            result.outcomes.append(
                FixOutcome(
                    check_name=check.name,
                    proposal=proposal,
                    executed=True,
                    execution_result=exec_result,
                )
            )
        else:
            # Destructive — notify operator instead of executing
            send_notification(
                title=f"Fix requires approval: {check.name}",
                message=f"{proposal.rationale} (action: {proposal.action_name})",
                priority="high",
                tags=["fix-pipeline", "destructive"],
            )
            result.outcomes.append(
                FixOutcome(
                    check_name=check.name,
                    proposal=proposal,
                    notified=True,
                )
            )

    return result
