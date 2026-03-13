"""Fix pipeline orchestrator.

Processes failing health checks through the probe → evaluate → validate → execute
flow, wiring together capabilities, the LLM evaluator, and notifications.

When LLM evaluation fails (e.g. LiteLLM down), falls back to deterministic
execution of safe remediation commands already embedded in health checks.
"""

from __future__ import annotations

import logging
import re
import shlex

from pydantic import BaseModel, Field

from agents.health_monitor import CheckResult, HealthReport, Status, run_cmd
from shared.fix_capabilities import get_capability_for_group
from shared.fix_capabilities.base import ExecutionResult, FixProposal, Safety
from shared.fix_capabilities.evaluator import evaluate_check
from shared.notify import send_notification

log = logging.getLogger(__name__)

# ── Deterministic fallback ──────────────────────────────────────────────────

# Patterns that are safe to execute without LLM evaluation.
# Each regex is matched against the full remediation command string.
_SAFE_REMEDIATION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^systemctl --user (start|restart|reset-failed) [\w@.\-]+$"),
    re.compile(r"^systemctl --user reset-failed [\w@.\-]+ && systemctl --user start [\w@.\-]+$"),
    re.compile(r"^docker (start|restart) [\w.\-]+$"),
    re.compile(r"^cd [~/\w.\-]+ && docker compose up -d(?: [\w.\-]+)?$"),
    re.compile(r"^cd [~/\w.\-]+ && docker compose --profile \w+ up -d(?: [\w.\-]+)?$"),
    re.compile(r"^cd [~/\w.\-]+ && docker compose restart [\w.\-]+$"),
]


def _is_safe_remediation(cmd: str) -> bool:
    """Check if a remediation command matches a known-safe pattern."""
    return any(p.match(cmd) for p in _SAFE_REMEDIATION_PATTERNS)


async def _run_deterministic_fix(check: CheckResult) -> FixOutcome:
    """Execute a health check's built-in remediation command directly.

    Only called when the LLM evaluator is unavailable and the remediation
    command matches a known-safe pattern.
    """
    cmd = check.remediation
    assert cmd is not None  # caller checks

    proposal = FixProposal(
        capability="deterministic_fallback",
        action_name="remediation_command",
        params={"command": cmd},
        rationale=f"LLM evaluator unavailable; executing safe remediation: {cmd}",
        safety=Safety.SAFE,
    )

    try:
        args = shlex.split(cmd)
    except ValueError as e:
        return FixOutcome(
            check_name=check.name,
            proposal=proposal,
            rejected_reason=f"Could not parse remediation command: {e}",
        )

    # Handle "cd <dir> && <cmd>" patterns
    cwd = None
    if len(args) >= 4 and args[0] == "cd" and args[2] == "&&":
        import os

        cwd = os.path.expanduser(args[1])
        args = args[3:]

    # Handle chained commands: "cmd1 && cmd2"
    # Split into sub-commands and run sequentially
    commands: list[list[str]] = []
    current: list[str] = []
    for arg in args:
        if arg == "&&":
            if current:
                commands.append(current)
            current = []
        else:
            current.append(arg)
    if current:
        commands.append(current)

    last_result = ExecutionResult(success=True, message="no commands")
    for sub_cmd in commands:
        rc, stdout, stderr = await run_cmd(sub_cmd, timeout=30.0, cwd=cwd)
        if rc != 0:
            last_result = ExecutionResult(
                success=False,
                message=f"Command {' '.join(sub_cmd)} failed (rc={rc}): {stderr}",
                output=stderr,
            )
            break
        last_result = ExecutionResult(
            success=True,
            message=f"Executed: {' '.join(sub_cmd)}",
            output=stdout,
        )

    return FixOutcome(
        check_name=check.name,
        proposal=proposal,
        executed=True,
        execution_result=last_result,
    )


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
            # No capability — try deterministic fallback
            if mode == "apply" and check.remediation and _is_safe_remediation(check.remediation):
                log.info(
                    "No capability for %s, falling back to deterministic fix: %s",
                    check.name,
                    check.remediation,
                )
                outcome = await _run_deterministic_fix(check)
                result.total += 1
                result.outcomes.append(outcome)
            continue

        # Gather context (probe)
        try:
            probe = await cap.gather_context(check)
        except Exception:
            log.warning("gather_context failed for check %s", check.name, exc_info=True)
            probe = None

        # Evaluate — ask LLM for a fix proposal
        proposal = None
        if probe is not None:
            proposal = await evaluate_check(check, probe, cap.available_actions())

        if proposal is None:
            # LLM evaluator unavailable or returned no proposal — deterministic fallback
            if mode == "apply" and check.remediation and _is_safe_remediation(check.remediation):
                log.info(
                    "LLM evaluator unavailable for %s, falling back to deterministic fix: %s",
                    check.name,
                    check.remediation,
                )
                outcome = await _run_deterministic_fix(check)
                result.total += 1
                result.outcomes.append(outcome)
            else:
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
