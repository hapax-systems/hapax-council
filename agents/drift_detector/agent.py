"""drift_detector agent — LLM-powered drift detection comparing docs vs reality."""

from __future__ import annotations

import logging

from opentelemetry import trace
from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits

from .config import get_model
from .context_tools import get_context_tools
from .docs import load_docs
from .introspect import generate_manifest
from .models import DriftReport, InfrastructureManifest
from .scanners import (
    check_doc_freshness,
    check_project_memory,
    check_screen_context_drift,
    scan_axiom_violations,
    scan_sufficiency_gaps,
)
from .system_prompt import get_system_prompt_fragment

log = logging.getLogger("drift_detector")
try:
    from agents import _langfuse_config  # noqa: F401
except ImportError:
    pass
_tracer = trace.get_tracer(__name__)

SYSTEM_PROMPT = """\
You are an infrastructure drift detector. You compare live system state against
documentation and identify discrepancies.

You will receive:
1. A JSON infrastructure manifest (the ground truth)
2. Documentation files (what the docs claim)

Your job: find every place where documentation is wrong, outdated, or incomplete
relative to what's actually running. Also find undocumented components.

GUIDELINES:
- Be precise. "LibreChat" in docs but "Open WebUI" running is a real drift.
- Ignore trivial differences (exact version strings change often).
- Focus on: services referenced that don't exist, services running that aren't
  documented, wrong ports, missing agents/tools, stale architecture descriptions.
- "planned" or "in development" is NOT drift for missing items.
- Wildcard LiteLLM routes expand to many models; don't flag each as undocumented.
- Model aliases mapping to specific model IDs is expected, not drift.
- Check goals: active goal with no service/agent = "goal-gap" category.
- Check axioms: T0 violation = severity high, T1 = medium.
- Sufficiency mode: check infrastructure ACTIVELY SUPPORTS the requirement.
  Category: "axiom-sufficiency-gap". T0=high, T1=medium, T2=low.
- System-level implications: examine emergent properties across services.

Call lookup_constraints() for additional operator constraints.
"""

drift_agent = Agent(
    get_model("fast"),
    system_prompt=get_system_prompt_fragment("drift-detector") + "\n\n" + SYSTEM_PROMPT,
    output_type=DriftReport,
)

for _tool_fn in get_context_tools():
    drift_agent.tool(_tool_fn)

from .axiom_tools import get_axiom_tools

for _tool_fn in get_axiom_tools():
    drift_agent.tool(_tool_fn)


async def detect_drift(manifest: InfrastructureManifest | None = None) -> DriftReport:
    """Run drift detection: collect manifest, load docs, ask LLM to compare."""
    with _tracer.start_as_current_span("drift.detect"):
        if manifest is None:
            manifest = await generate_manifest()

        # Run deterministic scans
        axiom_violations = scan_axiom_violations()
        sufficiency_gaps = scan_sufficiency_gaps()
        stale_docs = check_doc_freshness()
        screen_drift = check_screen_context_drift()
        memory_drift = check_project_memory()
        from .registry_checks import check_document_registry

        registry_drift = check_document_registry()

        docs = load_docs()
        if not docs:
            return DriftReport(
                drift_items=[], docs_analyzed=[], summary="No documentation files found."
            )

        # Build prompt
        from .prompt_builder import build_axiom_section, build_goals_section

        doc_sections = []
        for path, content in docs.items():
            if len(content) > 8000:
                content = content[:8000] + "\n\n[... truncated ...]"
            doc_sections.append(f"### {path}\n```\n{content}\n```")

        prompt = f"""## Live Infrastructure Manifest (ground truth)
```json
{manifest.model_dump_json(indent=2)}
```

## Documentation Files
{chr(10).join(doc_sections)}
{build_goals_section()}
{build_axiom_section()}

Analyze these documents against the live manifest. Find every discrepancy where
documentation doesn't match reality. Be thorough but ignore trivial version
string differences and wildcard model expansions."""

        deterministic = (
            axiom_violations
            + sufficiency_gaps
            + stale_docs
            + screen_drift
            + memory_drift
            + registry_drift
        )

        try:
            result = await drift_agent.run(prompt, usage_limits=UsageLimits(request_limit=200))
        except Exception as exc:
            log.error("LLM drift analysis failed: %s", exc)
            return DriftReport(
                drift_items=deterministic,
                docs_analyzed=list(docs.keys()),
                summary=f"Drift analysis failed: {exc}"
                + (f" ({len(deterministic)} deterministic finding(s))" if deterministic else ""),
            )

        report = result.output
        report.docs_analyzed = list(docs.keys())

        if deterministic:
            report.drift_items = deterministic + report.drift_items
            parts = []
            if axiom_violations:
                parts.append(f"{len(axiom_violations)} axiom violation(s)")
            if sufficiency_gaps:
                parts.append(f"{len(sufficiency_gaps)} sufficiency gap(s)")
            if stale_docs:
                parts.append(f"{len(stale_docs)} stale doc(s)")
            if screen_drift:
                parts.append(f"{len(screen_drift)} screen context drift(s)")
            if memory_drift:
                parts.append(f"{len(memory_drift)} missing project memory section(s)")
            if registry_drift:
                parts.append(f"{len(registry_drift)} registry enforcement finding(s)")
            report.summary = f"{', '.join(parts)} found in codebase. " + report.summary

        return report


# ── Formatters ───────────────────────────────────────────────────────────────

_SEVERITY_ICON = {"high": "[!!]", "medium": "[! ]", "low": "[ .]"}


def format_human(report: DriftReport) -> str:
    lines = []
    if not report.drift_items:
        lines.append("No drift detected. Documentation matches live infrastructure.")
    else:
        high = sum(1 for d in report.drift_items if d.severity == "high")
        med = sum(1 for d in report.drift_items if d.severity == "medium")
        low = sum(1 for d in report.drift_items if d.severity == "low")
        lines.append(
            f"Drift Report: {len(report.drift_items)} items ({high} high, {med} medium, {low} low)"
        )
        lines.append("")
        for item in sorted(
            report.drift_items,
            key=lambda d: {"high": 0, "medium": 1, "low": 2}.get(d.severity, 3),
        ):
            icon = _SEVERITY_ICON.get(item.severity, "[??]")
            lines.append(f"{icon} [{item.category}] {item.doc_file}")
            lines.append(f"     Doc says:  {item.doc_claim}")
            lines.append(f"     Reality:   {item.reality}")
            lines.append(f"     Fix:       {item.suggestion}")
            lines.append("")
    lines.append("")
    lines.append(f"Summary: {report.summary}")
    lines.append(f"Docs analyzed: {', '.join(report.docs_analyzed)}")
    return "\n".join(lines)
