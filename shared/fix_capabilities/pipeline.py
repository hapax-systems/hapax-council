"""Fix pipeline orchestrator.

Processes failing health checks through the probe → evaluate → validate → execute
flow, wiring together capabilities, the LLM evaluator, and notifications.

When LLM evaluation fails (e.g. LiteLLM down), falls back to deterministic
execution of safe remediation commands already embedded in health checks.
"""

from __future__ import annotations

import logging
import os
import re
import shlex

from pydantic import BaseModel, Field

from agents.health_monitor import CheckResult, HealthReport, Status, run_cmd
from shared.fix_capabilities import get_capability_for_group
from shared.fix_capabilities.background_admission import (
    BackgroundCapabilityAdmission,
    admit_background_capability,
)
from shared.fix_capabilities.base import ExecutionResult, FixProposal, Safety
from shared.fix_capabilities.evaluator import admit_fix_evaluator, evaluate_check
from shared.maintenance_lock import (
    first_docker_maintenance_lock,
    maintenance_lock_for_target,
    maintenance_lock_message,
)
from shared.notify import send_notification

log = logging.getLogger(__name__)

FIX_PIPELINE_ROUTE_ID_ENV = "HAPAX_FIX_PIPELINE_ROUTE_ID"
FIX_PIPELINE_ROUTE_ID = "local_tool.local.worker"

# ── Deterministic fallback ──────────────────────────────────────────────────

# Patterns that are safe to execute without LLM evaluation.
# Each regex is matched against the full remediation command string.
_SAFE_REMEDIATION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^systemctl --user (start|restart|reset-failed|enable --now) [\w@.\-]+$"),
    re.compile(r"^systemctl --user reset-failed [\w@.\-]+ && systemctl --user start [\w@.\-]+$"),
    re.compile(r"^docker (start|restart) [\w.\-]+$"),
    re.compile(r"^cd [~/\w.\-]+ && docker compose up -d(?: [\w.\-]+)*$"),
    re.compile(r"^cd [~/\w.\-]+ && docker compose --profile \w+ up -d(?: [\w.\-]+)*$"),
    re.compile(r"^cd [~/\w.\-]+ && docker compose restart [\w.\-]+$"),
    re.compile(r"^bash [~/\w.\-]+\.sh$"),
    # Qdrant collection creation
    re.compile(r"^curl -X PUT http://localhost:6333/collections/[\w\-]+ "),
    # Ollama model pull
    re.compile(r"^docker exec ollama ollama pull [\w.\-:]+$"),
]

_SAFE_PATH_RE = re.compile(r"^[~/\w.\-]+$")
_SAFE_MODULE_RE = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$")
_SAFE_FLAG_RE = re.compile(r"^--[\w\-]+$")
_SAFE_FLAG_VALUE_RE = re.compile(r"^[\w.\-]+$")


def _normalize_remediation(cmd: str) -> str:
    """Strip human-instruction prefixes from remediation commands."""
    # Remove "Run: ", "Check: ", "Enable timers: " etc.
    m = re.match(r"^(?:Run|Check|Enable timers|Verify):\s*", cmd)
    if m:
        return cmd[m.end() :]
    return cmd


def _is_safe_uv_module_invocation(cmd: str) -> bool:
    """Parse the allowed ``cd <dir> && uv run python -m ...`` command form."""
    try:
        args = shlex.split(cmd)
    except ValueError:
        return False

    if len(args) < 8:
        return False
    if args[0] != "cd" or not _SAFE_PATH_RE.fullmatch(args[1]) or args[2] != "&&":
        return False
    if args[3:7] != ["uv", "run", "python", "-m"]:
        return False
    if not _SAFE_MODULE_RE.fullmatch(args[7]):
        return False

    index = 8
    while index < len(args):
        if not _SAFE_FLAG_RE.fullmatch(args[index]):
            return False
        index += 1
        if index < len(args) and not args[index].startswith("--"):
            if not _SAFE_FLAG_VALUE_RE.fullmatch(args[index]):
                return False
            index += 1

    return True


def _is_safe_remediation(cmd: str) -> bool:
    """Check if a remediation command matches a known-safe pattern."""
    cmd = _normalize_remediation(cmd)
    return any(p.match(cmd) for p in _SAFE_REMEDIATION_PATTERNS) or _is_safe_uv_module_invocation(
        cmd
    )


def _docker_maintenance_lock_reason(sub_cmd: list[str]) -> str | None:
    """Return a maintenance-lock suppression reason for Docker commands."""
    if len(sub_cmd) >= 3 and sub_cmd[0] == "docker" and sub_cmd[1] in {"start", "restart"}:
        action = f"docker {sub_cmd[1]}"
        target = sub_cmd[2]
        lock = maintenance_lock_for_target(target, target_type="container")
        if lock is not None:
            return maintenance_lock_message(action, target, lock)
        return None

    if len(sub_cmd) < 3 or sub_cmd[:2] != ["docker", "compose"]:
        return None

    index = 2
    while index < len(sub_cmd) and sub_cmd[index].startswith("-"):
        flag = sub_cmd[index]
        index += 1
        if flag in {"--profile", "-p", "--project-name", "-f", "--file"} and index < len(sub_cmd):
            index += 1
    if index >= len(sub_cmd):
        return None

    compose_action = sub_cmd[index]
    index += 1
    if compose_action == "up":
        detached = index < len(sub_cmd) and sub_cmd[index] == "-d"
        if not detached:
            return None
        targets = sub_cmd[index + 1 :]
        action = "docker compose up"
    elif compose_action == "restart":
        targets = sub_cmd[index:]
        action = "docker compose restart"
    else:
        return None

    if not targets:
        lock = first_docker_maintenance_lock()
        if lock is not None:
            return maintenance_lock_message(action, "<all compose services>", lock)
        return None

    for target in targets:
        lock = maintenance_lock_for_target(target, target_type="service")
        if lock is not None:
            return maintenance_lock_message(action, target, lock)
    return None


async def _run_deterministic_fix(check: CheckResult) -> FixOutcome:
    """Execute a health check's built-in remediation command directly.

    Only called when the LLM evaluator is unavailable and the remediation
    command matches a known-safe pattern.
    """
    cmd = check.remediation
    assert cmd is not None  # caller checks
    cmd = _normalize_remediation(cmd)

    proposal = FixProposal(
        capability="deterministic_fallback",
        action_name="remediation_command",
        params={"command": cmd},
        rationale=f"LLM evaluator unavailable; executing safe remediation: {cmd}",
        safety=Safety.SAFE,
    )
    admission = _admit_runtime_fix_execution(proposal.capability, proposal.action_name)
    if not admission.admitted:
        return _admission_denied_outcome(check.name, proposal, admission)

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
        lock_reason = _docker_maintenance_lock_reason(sub_cmd)
        if lock_reason is not None:
            return FixOutcome(
                check_name=check.name,
                proposal=proposal,
                rejected_reason=lock_reason,
            )
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
    admission: dict[str, object] | None = None


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


def _admit_runtime_fix_execution(
    capability_name: str,
    action_name: str,
) -> BackgroundCapabilityAdmission:
    return admit_background_capability(
        capability_name=f"health_monitor.fix.{capability_name}.{action_name}",
        route_id=os.environ.get(FIX_PIPELINE_ROUTE_ID_ENV, FIX_PIPELINE_ROUTE_ID),
        mutation_surface="runtime",
        quality_floor="deterministic_ok",
    )


def _admission_denied_outcome(
    check_name: str,
    proposal: FixProposal,
    admission: BackgroundCapabilityAdmission,
) -> FixOutcome:
    return FixOutcome(
        check_name=check_name,
        proposal=proposal,
        rejected_reason=(
            f"Capability admission denied for route {admission.route_id}: "
            f"{admission.denial_summary()}. Next action: set "
            "HAPAX_BACKGROUND_CAPABILITY_TASK_NOTE for this service and refresh "
            "route/resource/quota/runtime-actuation receipts."
        ),
        admission=admission.metadata(),
    )


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
            proposal = await evaluate_check(
                check,
                probe,
                cap.available_actions(),
                admission_gate=admit_fix_evaluator,
            )

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
            admission = _admit_runtime_fix_execution(proposal.capability, proposal.action_name)
            if not admission.admitted:
                result.outcomes.append(_admission_denied_outcome(check.name, proposal, admission))
                continue
            exec_result = await cap.execute(proposal)
            result.outcomes.append(
                FixOutcome(
                    check_name=check.name,
                    proposal=proposal,
                    executed=True,
                    execution_result=exec_result,
                    admission=admission.metadata(),
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
