"""LLM-powered health analysis — root cause analysis and remediation planning.

Separate from health_monitor.py to keep the monitor zero-LLM.
Uses the 'fast' model for quick analysis.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from shared.config import get_model

# ── Root Cause Analysis ─────────────────────────────────────────────────────


class RootCauseAnalysis(BaseModel):
    """Structured root cause analysis for health failures."""

    summary: str = Field(description="One-sentence summary of the likely root cause")
    probable_cause: str = Field(description="Detailed explanation of the most likely cause")
    related_failures: list[str] = Field(
        default_factory=list,
        description="Other checks likely affected by the same root cause",
    )
    suggested_actions: list[str] = Field(
        default_factory=list,
        description="Ordered list of remediation steps",
    )
    confidence: str = Field(
        default="medium",
        description="Confidence level: low, medium, high",
    )


_rca_agent = Agent(
    get_model("fast"),
    output_type=RootCauseAnalysis,
    system_prompt="""\
You are a systems engineer analyzing health check failures for a Docker-based
LLM infrastructure stack (LiteLLM, Qdrant, Ollama, PostgreSQL, Langfuse).
Analyze the failing checks, recent history patterns, and container logs to
determine the most likely root cause. Be specific and actionable.
""",
)


async def analyze_failures(
    failed_checks: list[dict],
    recent_history: list[dict] | None = None,
    docker_logs: dict[str, str] | None = None,
) -> RootCauseAnalysis:
    """Run LLM root cause analysis on health check failures.

    Args:
        failed_checks: List of failed CheckResult dicts (name, status, message, detail).
        recent_history: Last N health history entries for pattern context.
        docker_logs: Container name → recent log output for relevant containers.
    """
    prompt_parts = ["## Failed Checks\n"]
    for c in failed_checks:
        prompt_parts.append(
            f"- **{c.get('name', '?')}**: {c.get('message', '')} "
            f"(detail: {c.get('detail', 'none')})"
        )

    if recent_history:
        prompt_parts.append("\n## Recent Health History (last 5 runs)\n")
        for h in recent_history[-5:]:
            prompt_parts.append(
                f"- {h.get('timestamp', '?')}: {h.get('status', '?')} "
                f"(failed: {h.get('failed_checks', [])})"
            )

    if docker_logs:
        prompt_parts.append("\n## Container Logs (last 20 lines each)\n")
        for container, logs in docker_logs.items():
            truncated = "\n".join(logs.splitlines()[-20:])
            prompt_parts.append(f"### {container}\n```\n{truncated}\n```\n")

    prompt = "\n".join(prompt_parts)
    result = await _rca_agent.run(prompt)
    return result.output


# ── Remediation Plan (Batch 6 extension point) ─────────────────────────────


class RemediationStep(BaseModel):
    """A single step in a remediation plan."""

    order: int
    description: str
    command: str = ""  # shell command if applicable
    pre_check: str = ""  # command to verify precondition
    rollback: str = ""  # command to undo this step
    risk: str = "low"  # low, medium, high


class RemediationPlan(BaseModel):
    """Multi-step remediation plan with rollback."""

    summary: str
    steps: list[RemediationStep] = Field(default_factory=list)
    estimated_duration: str = ""  # e.g. "2-5 minutes"
    requires_confirmation: bool = True


_remediation_agent = Agent(
    get_model("fast"),
    output_type=RemediationPlan,
    system_prompt="""\
You are a systems engineer creating a safe remediation plan for infrastructure
failures. Each step should have a pre-check and rollback command where applicable.
Be conservative — prefer restarts over destructive actions. Order steps by
dependency (fix upstream services first).
""",
)


async def generate_remediation_plan(
    analysis: RootCauseAnalysis,
    failed_checks: list[dict],
) -> RemediationPlan:
    """Generate a multi-step remediation plan from root cause analysis."""
    prompt = (
        f"## Root Cause\n{analysis.probable_cause}\n\n"
        f"## Failed Checks\n"
        + "\n".join(f"- {c.get('name', '?')}: {c.get('message', '')}" for c in failed_checks)
        + "\n\n## Suggested Actions\n"
        + "\n".join(f"- {a}" for a in analysis.suggested_actions)
    )
    result = await _remediation_agent.run(prompt)
    return result.output
