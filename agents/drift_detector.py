"""drift_detector.py — Documentation drift detection agent.

Compares live infrastructure (from introspect.py manifest) against documentation
files and identifies discrepancies. Uses an LLM to understand semantic equivalences
(e.g., "LiteLLM at :4000" in docs ≈ "litellm container on port 4000" in manifest)
and detect genuine drift (e.g., docs reference LibreChat but it was replaced by
Open WebUI).

Usage:
    uv run python -m agents.drift_detector              # Run drift analysis
    uv run python -m agents.drift_detector --fix        # Generate corrected doc fragments
    uv run python -m agents.drift_detector --json       # Machine-readable output
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

log = logging.getLogger("drift_detector")

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits

from shared.config import (
    get_model, CLAUDE_CONFIG_DIR, HAPAXROMANA_DIR, HAPAX_PROJECTS_DIR,
    HAPAX_HOME, AI_AGENTS_DIR, HAPAX_SYSTEM_DIR,
    OBSIDIAN_HAPAX_DIR, COCKPIT_WEB_DIR,
    HAPAX_VSCODE_DIR,
)
from shared.operator import get_system_prompt_fragment

# Import Langfuse OTel config (side-effect: configures exporter)
try:
    from shared import langfuse_config  # noqa: F401
except ImportError:
    pass

from agents.introspect import generate_manifest, InfrastructureManifest


# ── Schemas ──────────────────────────────────────────────────────────────────

class DriftItem(BaseModel):
    """A single discrepancy between documentation and reality."""
    severity: str = Field(description="high, medium, or low")
    category: str = Field(description="Category: missing_service, extra_service, wrong_port, wrong_version, stale_reference, missing_doc, config_mismatch, goal-gap, axiom-violation, axiom-sufficiency-gap, stale_doc")
    doc_file: str = Field(description="Which documentation file contains the drift")
    doc_claim: str = Field(description="What the documentation says")
    reality: str = Field(description="What the actual system state is")
    suggestion: str = Field(description="Suggested fix — either a doc edit or a system change")


class DriftReport(BaseModel):
    """Complete drift analysis."""
    drift_items: list[DriftItem] = Field(default_factory=list)
    docs_analyzed: list[str] = Field(default_factory=list)
    summary: str = Field(description="One-paragraph summary of overall drift state")


# ── Documentation sources ────────────────────────────────────────────────────

DOC_FILES = [
    CLAUDE_CONFIG_DIR / "CLAUDE.md",
    HAPAXROMANA_DIR / "CLAUDE.md",
    HAPAXROMANA_DIR / "agent-architecture.md",
    HAPAXROMANA_DIR / "operations-manual.md",
    HAPAXROMANA_DIR / "README.md",
    # Rules files with factual infrastructure claims
    HAPAX_SYSTEM_DIR / "rules" / "axioms.md",
    HAPAX_SYSTEM_DIR / "rules" / "system-context.md",
    CLAUDE_CONFIG_DIR / "rules" / "environment.md",
    CLAUDE_CONFIG_DIR / "rules" / "models.md",
    CLAUDE_CONFIG_DIR / "rules" / "toolchain.md",
]

# Expected hardware devices — edit here when hardware changes
EXPECTED_DEVICES: dict[str, str] = {
    "Logitech BRIO": "/dev/v4l/by-id/usb-046d_Logitech_BRIO_5342C819-video-index0",
    "Logitech C920": "/dev/v4l/by-id/usb-046d_HD_Pro_Webcam_C920_2657DFCF-video-index0",
}

HAPAX_REPO_DIRS = [
    AI_AGENTS_DIR,
    HAPAXROMANA_DIR,
    HAPAX_SYSTEM_DIR,
    COCKPIT_WEB_DIR,
    OBSIDIAN_HAPAX_DIR,
    HAPAX_VSCODE_DIR,
]

# Also check CLAUDE.md in canonical repos (scoped to HAPAX_REPO_DIRS only)
for p in HAPAX_REPO_DIRS:
    candidate = p / "CLAUDE.md"
    if candidate.is_file() and candidate not in DOC_FILES:
        DOC_FILES.append(candidate)


def load_docs() -> dict[str, str]:
    """Load all documentation files as {short_path: content}."""
    docs = {}
    home = str(HAPAX_HOME)
    for path in DOC_FILES:
        if path.is_file():
            try:
                text = path.read_text(errors="replace")
                short = str(path).replace(home, "~")
                docs[short] = text
            except OSError:
                continue
    return docs


# ── Agent ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are an infrastructure drift detector. You compare live system state against
documentation and identify discrepancies.

You will receive:
1. A JSON infrastructure manifest (the ground truth — what's actually running)
2. Documentation files (what the docs claim about the system)

Your job is to find every place where the documentation is wrong, outdated, or
incomplete relative to what's actually running. Also find places where the system
has components not documented.

IMPORTANT GUIDELINES:
- Be precise. "LibreChat" in docs but "Open WebUI" running is a real drift.
- Ignore trivial differences (exact version strings change often).
- Focus on: services referenced that don't exist, services running that aren't
  documented, wrong ports, missing agents/tools, stale architecture descriptions.
- A document saying "planned" or "in development" is NOT drift for missing items.
- Wildcard LiteLLM routes (anthropic/*, gemini/*, ollama/*) expand to many models;
  don't flag each expanded model as undocumented.
- Model aliases (claude-opus, claude-sonnet) mapping to specific model IDs is
  expected behavior, not drift.
- If operator goals are provided, check whether the infrastructure supports each goal.
  A goal with status "active" but no corresponding service/agent is a goal-capability gap.
  Flag these as drift items with category "goal-gap".
- If a goal has infrastructure support but shows "STALLED" or "DORMANT" in its momentum data,
  note this as an observation — the capability exists but isn't being exercised. This is a system
  design signal (friction too high, entry point unclear), not an operator failing. Category: "goal-gap".
- If axioms are provided, check whether the current infrastructure complies with each axiom
  and its key implications. Flag violations as drift items with category "axiom-violation".
  T0 implications that appear violated: severity=high. T1 implications: severity=medium.
- Implications have `mode` ("compatibility" or "sufficiency") and `level` ("component", "subsystem", "system").
  For sufficiency implications, check whether the infrastructure ACTIVELY SUPPORTS the requirement.
  A sufficiency gap means the system doesn't violate the axiom but also doesn't provide the required capability.
  Category: "axiom-sufficiency-gap". Severity: T0=high, T1=medium, T2=low.
- System-level implications require examining emergent properties across services, not just individual components.

Call lookup_constraints() for additional operator constraints.
"""

drift_agent = Agent(
    get_model("fast"),
    system_prompt=get_system_prompt_fragment("drift-detector") + "\n\n" + SYSTEM_PROMPT,
    output_type=DriftReport,
)

# Register on-demand operator context tools
from shared.context_tools import get_context_tools
for _tool_fn in get_context_tools():
    drift_agent.tool(_tool_fn)

from shared.axiom_tools import get_axiom_tools
for _tool_fn in get_axiom_tools():
    drift_agent.tool(_tool_fn)


def scan_axiom_violations() -> list[DriftItem]:
    """Deterministic pre-LLM scan: run T0 patterns against code repos.

    Returns DriftItems for any structural violations found. This provides
    retroactive axiom enforcement as part of the weekly drift check.
    Patterns loaded from shared/axiom_patterns.txt (not inline).
    """
    from shared.axiom_patterns import load_t0_patterns, scan_directory

    patterns = load_t0_patterns()
    if not patterns:
        return []

    home = str(HAPAX_HOME)
    violations: list[DriftItem] = []

    for repo in HAPAX_REPO_DIRS:
        if not repo.exists():
            continue
        for match in scan_directory(repo, patterns):
            rel_path = match.file.replace(home, "~")
            violations.append(DriftItem(
                severity="high",
                category="axiom-violation",
                doc_file=rel_path,
                doc_claim=f"T0 pattern match at line {match.line}",
                reality=f"Code contains: {match.content}",
                suggestion=f"Remove or refactor: {rel_path}:{match.line}",
            ))

    return violations


def scan_sufficiency_gaps() -> list[DriftItem]:
    """Run sufficiency probes and convert failures to DriftItems."""
    try:
        from shared.sufficiency_probes import run_probes
    except ImportError:
        return []

    results = run_probes()
    items: list[DriftItem] = []

    for r in results:
        if r.met:
            continue

        # Map probe to severity based on implication tier
        probe = next((p for p in __import__("shared.sufficiency_probes", fromlist=["PROBES"]).PROBES if p.id == r.probe_id), None)
        if probe:
            severity = {"T0": "high", "T1": "medium", "T2": "low"}.get(
                _get_implication_tier(probe.implication_id), "low"
            )
        else:
            severity = "low"

        items.append(DriftItem(
            severity=severity,
            category="axiom-sufficiency-gap",
            doc_file=f"probe:{r.probe_id}",
            doc_claim=probe.question if probe else r.probe_id,
            reality=r.evidence,
            suggestion=f"Address sufficiency gap: {r.evidence}",
        ))

    return items


def _get_implication_tier(impl_id: str) -> str:
    """Look up the tier for an implication ID."""
    from shared.axiom_registry import load_implications

    if impl_id.startswith("ex-"):
        axiom_id = "executive_function"
    elif impl_id.startswith("mg-"):
        axiom_id = "management_governance"
    elif impl_id.startswith("cb-"):
        axiom_id = "corporate_boundary"
    else:
        axiom_id = "single_user"
    for impl in load_implications(axiom_id):
        if impl.id == impl_id:
            return impl.tier
    return "T2"


def check_project_memory() -> list[DriftItem]:
    """Check that all hapax repos have a ## Project Memory section in CLAUDE.md.

    This enforces the cross-repo memory standard so Claude Code has
    institutional knowledge seeded in every project.
    """
    items: list[DriftItem] = []
    home = str(HAPAX_HOME)

    for repo_dir in HAPAX_REPO_DIRS:
        if not repo_dir.is_dir():
            continue

        claude_md = repo_dir / "CLAUDE.md"
        short_path = str(repo_dir).replace(home, "~")

        if not claude_md.is_file():
            items.append(DriftItem(
                severity="medium",
                category="missing_project_memory",
                doc_file=f"{short_path}/CLAUDE.md",
                doc_claim="File does not exist",
                reality="All hapax repos must have a CLAUDE.md with ## Project Memory section",
                suggestion=f"Create {short_path}/CLAUDE.md with a ## Project Memory section",
            ))
            continue

        content = claude_md.read_text(errors="replace")
        if "## Project Memory" not in content:
            items.append(DriftItem(
                severity="medium",
                category="missing_project_memory",
                doc_file=f"{short_path}/CLAUDE.md",
                doc_claim="No ## Project Memory section found",
                reality="All hapax repos must have a ## Project Memory section for cross-session learning",
                suggestion=f"Add a ## Project Memory section to {short_path}/CLAUDE.md with stable patterns and conventions",
            ))

    return items


def check_doc_freshness() -> list[DriftItem]:
    """Check whether documentation files are potentially stale.

    Compares each DOC_FILE's git last-modified date against signals of system
    change (health report timestamps, container start times). If a doc hasn't
    been updated in >30 days but system state has changed more recently, it's
    flagged as potentially stale.

    Returns DriftItems with category="stale_doc" and severity="low".
    """
    import subprocess
    from datetime import datetime, timedelta, timezone

    stale_threshold = timedelta(days=30)
    now = datetime.now(timezone.utc)
    items: list[DriftItem] = []
    home = str(HAPAX_HOME)

    # Determine latest system change timestamp from available signals
    latest_system_change: datetime | None = None

    # Signal 1: health history last entry timestamp
    health_history = AI_AGENTS_DIR / "profiles" / "health-history.jsonl"
    if health_history.is_file():
        try:
            # Read last line efficiently
            with open(health_history, "rb") as f:
                f.seek(0, 2)  # seek to end
                size = f.tell()
                if size > 0:
                    # Read last 1KB to find the final line
                    f.seek(max(0, size - 1024))
                    last_lines = f.read().decode("utf-8", errors="replace").strip().splitlines()
                    if last_lines:
                        entry = json.loads(last_lines[-1])
                        ts = entry.get("timestamp", "")
                        if ts:
                            dt = datetime.fromisoformat(ts)
                            if latest_system_change is None or dt > latest_system_change:
                                latest_system_change = dt
        except (OSError, json.JSONDecodeError, ValueError):
            pass

    # Signal 2: Docker container start times
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.CreatedAt}}"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines():
                try:
                    # Docker format: "2026-03-01 10:30:45 +0000 UTC"
                    parts = line.strip().split()
                    if len(parts) >= 3:
                        dt_str = f"{parts[0]} {parts[1]} {parts[2]}"
                        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S %z")
                        if latest_system_change is None or dt > latest_system_change:
                            latest_system_change = dt
                except (ValueError, IndexError):
                    continue
    except (OSError, subprocess.TimeoutExpired):
        pass

    if latest_system_change is None:
        # No system change signals available — can't assess freshness
        return items

    for path in DOC_FILES:
        if not path.is_file():
            continue

        # Get git last-modified date for this file
        doc_last_modified: datetime | None = None
        try:
            result = subprocess.run(
                ["git", "log", "-1", "--format=%aI", "--", str(path)],
                capture_output=True, text=True, timeout=5,
                cwd=str(path.parent),
            )
            if result.returncode == 0 and result.stdout.strip():
                doc_last_modified = datetime.fromisoformat(result.stdout.strip())
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass

        if doc_last_modified is None:
            # Fall back to filesystem mtime
            try:
                mtime = path.stat().st_mtime
                doc_last_modified = datetime.fromtimestamp(mtime, tz=timezone.utc)
            except OSError:
                continue

        age = now - doc_last_modified
        if age > stale_threshold and latest_system_change > doc_last_modified:
            short_path = str(path).replace(home, "~")
            days_old = age.days
            items.append(DriftItem(
                severity="low",
                category="stale_doc",
                doc_file=short_path,
                doc_claim=f"Last updated {days_old} days ago ({doc_last_modified.strftime('%Y-%m-%d')})",
                reality=f"System state changed more recently ({latest_system_change.strftime('%Y-%m-%d')})",
                suggestion=f"Review {short_path} for accuracy — not updated in {days_old} days",
            ))

    return items


def check_screen_context_drift() -> list[DriftItem]:
    """Check if screen analyzer context file has drifted from live state.

    Compares the static context at ~/.local/share/hapax-voice/screen_context.md
    against live Docker services and systemd units. If the file is missing or
    significantly different, flags as drift and regenerates.
    """
    import datetime
    import subprocess

    context_path = Path.home() / ".local" / "share" / "hapax-voice" / "screen_context.md"
    items: list[DriftItem] = []

    # Check if file exists
    if not context_path.exists():
        items.append(DriftItem(
            severity="medium",
            category="missing_doc",
            doc_file=str(context_path).replace(str(Path.home()), "~"),
            doc_claim="Screen analyzer context file should exist",
            reality="File not found",
            suggestion="Run: uv run python scripts/generate_screen_context.py",
        ))
        return items

    # Check file age (stale if >7 days)
    file_mtime = datetime.datetime.fromtimestamp(context_path.stat().st_mtime, tz=datetime.timezone.utc)
    age_days = (datetime.datetime.now(tz=datetime.timezone.utc) - file_mtime).days
    if age_days > 7:
        items.append(DriftItem(
            severity="low",
            category="stale_doc",
            doc_file=str(context_path).replace(str(Path.home()), "~"),
            doc_claim=f"Screen context last generated {age_days} days ago",
            reality="Context may not reflect current system state",
            suggestion="Regenerate: uv run python scripts/generate_screen_context.py",
        ))

    # Quick drift check: compare Docker service count in file vs live
    content = context_path.read_text()
    try:
        llm_stack = Path.home() / "llm-stack"
        result = subprocess.run(
            ["docker", "compose", "ps", "--format", "{{.Name}}"],
            capture_output=True, text=True, timeout=15,
            cwd=str(llm_stack) if llm_stack.exists() else None,
        )
        live_services = set(result.stdout.strip().splitlines())

        # Find services running but not mentioned in context file
        missing_from_doc = [s for s in live_services if s and s not in content]

        if missing_from_doc:
            items.append(DriftItem(
                severity="medium",
                category="config_mismatch",
                doc_file=str(context_path).replace(str(Path.home()), "~"),
                doc_claim="Screen context should list all running services",
                reality=f"Services not in context: {', '.join(sorted(missing_from_doc)[:5])}",
                suggestion="Regenerate: uv run python scripts/generate_screen_context.py",
            ))
    except Exception as exc:
        log.debug("Docker check failed for screen context drift: %s", exc)

    # Check webcam devices (paths defined in EXPECTED_DEVICES)
    for label, dev_path in EXPECTED_DEVICES.items():
        if not Path(dev_path).exists():
            items.append(DriftItem(
                severity="low",
                category="config_mismatch",
                doc_file="hardware/webcam",
                doc_claim=f"{label} should be available at {dev_path}",
                reality=f"{label} not detected at expected device path",
                suggestion=f"Check USB connection for {label}, or update EXPECTED_DEVICES in drift_detector.py",
            ))

    return items


async def detect_drift(manifest: InfrastructureManifest | None = None) -> DriftReport:
    """Run drift detection: collect manifest, load docs, ask LLM to compare."""
    if manifest is None:
        manifest = await generate_manifest()

    # Run deterministic axiom code scan first (retroactive enforcement)
    axiom_violations = scan_axiom_violations()

    # Run sufficiency probes
    sufficiency_gaps = scan_sufficiency_gaps()

    # Run doc freshness check
    stale_docs = check_doc_freshness()

    # Run screen context drift check
    screen_context_drift = check_screen_context_drift()

    # Run project memory check
    memory_drift = check_project_memory()

    # Run document registry checks (coverage gaps, section validation, mutual awareness)
    from shared.registry_checks import check_document_registry
    registry_drift = check_document_registry()

    docs = load_docs()
    if not docs:
        return DriftReport(
            drift_items=[],
            docs_analyzed=[],
            summary="No documentation files found to analyze.",
        )

    # Build the prompt with manifest + docs
    manifest_json = manifest.model_dump_json(indent=2)

    doc_sections = []
    for path, content in docs.items():
        # Truncate very long docs to avoid token limits
        if len(content) > 8000:
            content = content[:8000] + "\n\n[... truncated ...]"
        doc_sections.append(f"### {path}\n```\n{content}\n```")

    # Build goals context for goal-capability gap detection
    from shared.operator import get_goals
    goals = get_goals()[:5]
    goals_section = ""
    if goals:
        goal_lines = []
        for g in goals:
            status = g.get("status", "unknown")
            goal_lines.append(f"- [{status}] {g.get('name', '')}: {g.get('description', '')}")
        goals_section = f"\n\n## Operator Goals\n{chr(10).join(goal_lines)}"

    # Build axiom compliance section
    axiom_section = ""
    try:
        from shared.axiom_registry import load_axioms, load_implications
        active_axioms = load_axioms()
        if active_axioms:
            axiom_lines = ["\n\n## Active Axioms (check for compliance)"]
            for ax in active_axioms:
                scope_label = f"[{ax.scope}]" if ax.scope == "constitutional" else f"[domain:{ax.domain}]"
                axiom_lines.append(f"\n### {ax.id} {scope_label} (weight={ax.weight}, type={ax.type})")
                axiom_lines.append(ax.text.strip())
                impls = load_implications(ax.id)
                blocking = [i for i in impls if i.enforcement in ("block", "review")]
                if blocking:
                    axiom_lines.append("Key implications to check:")
                    for impl in blocking:
                        axiom_lines.append(f"  - [{impl.tier}/{impl.mode}/{impl.level}] {impl.text}")
                sufficiency = [i for i in impls if i.mode == "sufficiency"]
                if sufficiency:
                    axiom_lines.append("Sufficiency requirements (check active support):")
                    for impl in sufficiency:
                        axiom_lines.append(f"  - [{impl.tier}/{impl.level}] {impl.text}")
            axiom_section = "\n".join(axiom_lines)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Could not load axioms for drift check: %s", e)

    prompt = f"""## Live Infrastructure Manifest (ground truth)
```json
{manifest_json}
```

## Documentation Files
{chr(10).join(doc_sections)}
{goals_section}
{axiom_section}

Analyze these documents against the live manifest. Find every discrepancy where
documentation doesn't match reality. Be thorough but ignore trivial version
string differences and wildcard model expansions."""

    try:
        result = await drift_agent.run(prompt, usage_limits=UsageLimits(request_limit=200))
    except Exception as exc:
        log.error("LLM drift analysis failed: %s", exc)
        deterministic = axiom_violations + sufficiency_gaps + stale_docs + screen_context_drift + memory_drift + registry_drift
        return DriftReport(
            drift_items=deterministic,
            docs_analyzed=list(docs.keys()),
            summary=f"Drift analysis failed: {exc}"
            + (f" ({len(deterministic)} deterministic finding(s) from code scan)" if deterministic else ""),
        )
    report = result.output
    report.docs_analyzed = list(docs.keys())

    # Merge deterministic findings into the report
    deterministic_items = axiom_violations + sufficiency_gaps + stale_docs + screen_context_drift + memory_drift + registry_drift
    if deterministic_items:
        report.drift_items = deterministic_items + report.drift_items
        parts = []
        if axiom_violations:
            parts.append(f"{len(axiom_violations)} axiom violation(s)")
        if sufficiency_gaps:
            parts.append(f"{len(sufficiency_gaps)} sufficiency gap(s)")
        if stale_docs:
            parts.append(f"{len(stale_docs)} stale doc(s)")
        if screen_context_drift:
            parts.append(f"{len(screen_context_drift)} screen context drift(s)")
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
        lines.append(f"Drift Report: {len(report.drift_items)} items ({high} high, {med} medium, {low} low)")
        lines.append("")

        for item in sorted(report.drift_items, key=lambda d: {"high": 0, "medium": 1, "low": 2}.get(d.severity, 3)):
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


# ── Fix mode ────────────────────────────────────────────────────────────────

class DocFix(BaseModel):
    """A corrected section of a documentation file."""
    doc_file: str = Field(description="Which documentation file this fix applies to")
    section_title: str = Field(description="The section or table being corrected")
    original: str = Field(description="The original text that needs changing (exact match from the doc)")
    corrected: str = Field(description="The corrected replacement text")
    explanation: str = Field(description="Brief explanation of what changed and why")


class FixReport(BaseModel):
    """Collection of documentation fixes."""
    fixes: list[DocFix] = Field(default_factory=list)
    summary: str = Field(description="One-line summary of all changes")


FIX_SYSTEM_PROMPT = """\
You are a documentation editor for a multi-repo infrastructure system. Given a
documentation file and a list of discrepancies (drift items), produce precise
text replacements to fix the documentation so it matches reality.

RULES:
- The "original" field must be an EXACT substring from the document (copy-paste).
- The "corrected" field is the replacement text.
- Only fix items listed in the drift report. Don't rewrite unrelated sections.
- Preserve the document's existing formatting style (markdown tables, headers, etc).
- For missing items (services not documented), add them to the appropriate existing
  table or section — don't create new sections.
- Keep fixes minimal and precise. Don't add commentary or notes in the doc itself.

CONTEXT TOOLS:
You have access to operator context tools. Use them when generating NEW content
(not when making mechanical edits like adding a table row):
- Call lookup_constraints("python,docker,git") when writing Conventions sections
- Call lookup_constraints() when scaffolding new documents
- Call lookup_patterns("workflow,development") when writing Project Memory stubs
Do NOT call tools for simple table row additions or heading insertions.

CATEGORY-SPECIFIC GUIDANCE:
- missing-section: Add the required section heading and a substantive stub paragraph
  explaining the section's purpose. Place it in a logical position relative to existing
  headings. Never add an empty heading — always include at least a sentence describing
  what belongs in the section.
- coverage-gap: Add the missing item to the relevant table or list. Match the existing
  row/entry format exactly. Include accurate details (don't invent values — use the
  suggestion field for guidance, and mark unknowns with "TODO").
- missing-required-doc: This means the entire file is absent. Generate a complete
  initial document with all required archetype sections populated with substantive
  stubs. The "original" should be empty string and "corrected" should be the full file.
- boundary-mismatch: One of the paired files must be updated to match the other.
  Prefer the version that is more complete or more recently updated.
- repo-awareness-gap: Add the missing repo to the registry table, matching existing
  row format. Include the repo name and a brief description of its purpose.
- spec-reference-gap: Add a brief reference to the architectural spec source in an
  appropriate location (e.g., a "Related Repos" or "Architecture" section).
"""

fix_agent = Agent(
    get_model("fast"),
    system_prompt=FIX_SYSTEM_PROMPT,
    output_type=FixReport,
)

# Register context tools so fixes respect operator conventions and axioms.
# Critical for generating substantive content (new docs, stub sections).
for _fix_tool_fn in get_context_tools():
    fix_agent.tool(_fix_tool_fn)


REGISTRY_CATEGORIES = frozenset({
    "missing-required-doc", "missing-section", "coverage-gap",
    "repo-awareness-gap", "spec-reference-gap", "boundary-mismatch",
})


def _build_fix_context(
    doc_path: str,
    items: list[DriftItem],
    *,
    registry: object | None = None,
) -> str:
    """Build archetype/registry context for the fix agent when registry items are present.

    Returns a context block to inject into the fix prompt, or empty string if
    no registry items are in the batch.

    Args:
        doc_path: The document file path being fixed.
        items: Drift items for this document.
        registry: Optional pre-loaded DocumentRegistry (for testing). If None,
            loads from the default path.
    """
    if not any(d.category in REGISTRY_CATEGORIES for d in items):
        return ""

    if registry is None:
        # Lazy-load registry to avoid import at module level
        try:
            from shared.document_registry import load_registry
            registry = load_registry(path=HAPAXROMANA_DIR / "docs" / "document-registry.yaml")
        except Exception:
            return ""

    if registry is None:
        return ""

    # Find the archetype for this document
    lines = ["## Document context (from registry)"]
    archetype_name = ""
    repo_name = ""

    for rname, repo in registry.repos.items():
        for doc in repo.required_docs:
            # Match by doc path suffix (doc_path may be "repo/file.md" or full path)
            if doc["path"] in doc_path or doc_path.endswith(doc["path"]):
                archetype_name = doc.get("archetype", "")
                repo_name = rname
                break
        if archetype_name:
            break

    if repo_name:
        lines.append(f"- Repository: {repo_name}")

    if archetype_name and archetype_name in registry.archetypes:
        arch = registry.archetypes[archetype_name]
        lines.append(f"- Document archetype: **{archetype_name}** — {arch.description}")
        if arch.required_sections:
            lines.append(f"- Required sections: {', '.join(arch.required_sections)}")
        if arch.composite:
            lines.append("- This is a composite document (may blend multiple concerns)")
        else:
            lines.append("- This is a single-purpose document (should stay focused)")

    # Add relevant coverage rule context for coverage-gap items
    coverage_items = [d for d in items if d.category == "coverage-gap"]
    if coverage_items:
        lines.append("")
        lines.append("### Coverage context")
        for rule in registry.coverage_rules:
            # Check if any coverage-gap item references this rule's doc
            for ci in coverage_items:
                if rule.reference_doc.replace("~", str(Path.home())) in ci.doc_file or ci.doc_file in rule.reference_doc:
                    lines.append(f"- Rule: {rule.description}")
                    if rule.reference_section:
                        lines.append(f"  Target section: {rule.reference_section}")
                    lines.append(f"  Match strategy: {rule.match_by}")
                    break

    return "\n".join(lines)


async def generate_fixes(report: DriftReport, docs: dict[str, str]) -> FixReport:
    """For high/medium drift items, generate corrected doc fragments."""
    actionable = [d for d in report.drift_items if d.severity in ("high", "medium")]
    if not actionable:
        return FixReport(fixes=[], summary="No high/medium severity items to fix.")

    # Group drift items by doc file
    by_file: dict[str, list[DriftItem]] = {}
    for item in actionable:
        by_file.setdefault(item.doc_file, []).append(item)

    all_fixes: list[DocFix] = []

    for doc_path, items in by_file.items():
        doc_content = docs.get(doc_path, "")
        if not doc_content:
            continue

        items_desc = "\n".join(
            f"- [{d.severity}] {d.category}: Doc says \"{d.doc_claim}\" but reality is \"{d.reality}\". Suggestion: {d.suggestion}"
            for d in items
        )

        # Inject registry context when fixing registry-originated drift items
        registry_context = _build_fix_context(doc_path, items)

        prompt = f"""## Document to fix: {doc_path}

```
{doc_content[:12000]}
```

{registry_context}

## Drift items to fix:
{items_desc}

Generate exact text replacements to fix each drift item in this document.
The "original" field MUST be a verbatim substring from the document above."""

        try:
            result = await fix_agent.run(prompt)
        except Exception as exc:
            log.error("LLM fix generation failed for %s: %s", doc_path, exc)
            continue
        all_fixes.extend(result.output.fixes)

    return FixReport(
        fixes=all_fixes,
        summary=f"{len(all_fixes)} fixes across {len(by_file)} files",
    )


def format_fixes(fix_report: FixReport) -> str:
    """Format fixes as a human-readable diff-style output."""
    if not fix_report.fixes:
        return "No fixes to apply."

    lines = [f"Proposed Fixes ({len(fix_report.fixes)} changes):", ""]

    for fix in fix_report.fixes:
        lines.append(f"--- {fix.doc_file}")
        lines.append(f"  Section: {fix.section_title}")
        lines.append(f"  Reason: {fix.explanation}")
        lines.append("")
        for orig_line in fix.original.splitlines():
            lines.append(f"  - {orig_line}")
        for corr_line in fix.corrected.splitlines():
            lines.append(f"  + {corr_line}")
        lines.append("")

    lines.append(f"Summary: {fix_report.summary}")
    lines.append("To apply: review each change, then manually update the files.")
    return "\n".join(lines)


# ── Apply mode ───────────────────────────────────────────────────────────────

class ApplyResult(BaseModel):
    """Result of applying fixes to documentation files."""
    applied: int = 0
    skipped: int = 0
    errors: list[str] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)


def _resolve_doc_path(doc_file: str) -> Path | None:
    """Resolve a doc_file reference (may use ~) to an absolute Path."""
    expanded = Path(doc_file.replace("~", str(HAPAX_HOME)))
    if expanded.is_file():
        return expanded
    # Try as-is
    p = Path(doc_file)
    if p.is_file():
        return p
    return None


def apply_fixes(fix_report: FixReport) -> ApplyResult:
    """Apply fixes directly to documentation files.

    Safety: only applies when `original` is an exact unique substring.
    Skips fixes where the original text isn't found or appears multiple times.
    """
    result = ApplyResult()
    changed: set[str] = set()

    for fix in fix_report.fixes:
        path = _resolve_doc_path(fix.doc_file)
        if path is None:
            result.skipped += 1
            result.errors.append(f"File not found: {fix.doc_file}")
            continue

        try:
            content = path.read_text()
        except OSError as e:
            result.skipped += 1
            result.errors.append(f"Cannot read {fix.doc_file}: {e}")
            continue

        # Safety: exact unique substring match
        count = content.count(fix.original)
        if count == 0:
            result.skipped += 1
            result.errors.append(
                f"Original text not found in {fix.doc_file}: "
                f"{fix.original[:60]}..."
            )
            continue
        if count > 1:
            result.skipped += 1
            result.errors.append(
                f"Original text found {count} times in {fix.doc_file} (ambiguous): "
                f"{fix.original[:60]}..."
            )
            continue

        # Apply the fix
        new_content = content.replace(fix.original, fix.corrected, 1)
        try:
            path.write_text(new_content)
            result.applied += 1
            changed.add(str(path))
        except OSError as e:
            result.skipped += 1
            result.errors.append(f"Cannot write {fix.doc_file}: {e}")

    result.changed_files = sorted(changed)
    return result


def _git_commit_fixes(changed_files: list[str], fix_count: int) -> bool:
    """Commit changed documentation files with a conventional commit message."""
    import subprocess

    if not changed_files:
        return False

    # Group files by repo (git root)
    repos: dict[str, list[str]] = {}
    for fpath in changed_files:
        try:
            git_root = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=str(Path(fpath).parent),
                capture_output=True, text=True, timeout=5,
            )
            if git_root.returncode == 0:
                root = git_root.stdout.strip()
                repos.setdefault(root, []).append(fpath)
            else:
                log.warning("Not in a git repo: %s", fpath)
        except Exception:
            log.warning("Could not determine git root for %s", fpath)

    committed = False
    for root, files in repos.items():
        try:
            # Stage files
            subprocess.run(
                ["git", "add"] + files,
                cwd=root, capture_output=True, text=True, timeout=10,
            )
            # Commit
            msg = (
                f"docs: auto-fix {len(files)} documentation drift item(s)\n\n"
                f"Applied by drift_detector --fix --apply.\n"
                f"Files: {', '.join(Path(f).name for f in files)}\n\n"
                f"Co-Authored-By: Claude <noreply@anthropic.com>"
            )
            result = subprocess.run(
                ["git", "commit", "-m", msg],
                cwd=root, capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                committed = True
                log.info("Committed drift fixes in %s", root)
            else:
                log.warning("Git commit failed in %s: %s", root, result.stderr)
        except Exception as e:
            log.warning("Git commit error in %s: %s", root, e)

    return committed


def _notify_fixes(apply_result: ApplyResult, committed: bool) -> None:
    """Send notification about applied drift fixes."""
    try:
        from shared.notify import send_notification
    except ImportError:
        log.debug("shared.notify not available, skipping notification")
        return

    if apply_result.applied == 0:
        return

    title = f"Drift auto-fix: {apply_result.applied} applied"
    body_parts = [
        f"Applied {apply_result.applied} fix(es) to {len(apply_result.changed_files)} file(s).",
    ]
    if apply_result.skipped:
        body_parts.append(f"Skipped {apply_result.skipped} (see logs).")
    if committed:
        body_parts.append("Changes committed to git.")
    body_parts.append("Files: " + ", ".join(Path(f).name for f in apply_result.changed_files))

    try:
        send_notification(title=title, body=" ".join(body_parts), priority="default")
    except Exception:
        log.debug("Notification send failed (non-critical)")


# ── CLI ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Documentation drift detector — LLM-powered comparison of docs vs reality",
        prog="python -m agents.drift_detector",
    )
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    parser.add_argument("--fix", action="store_true", help="Generate corrected documentation fragments")
    parser.add_argument("--apply", action="store_true", help="Apply fixes directly to files (requires --fix)")
    args = parser.parse_args()

    if args.apply and not args.fix:
        print("--apply requires --fix", file=sys.stderr)
        sys.exit(1)

    print("Collecting infrastructure manifest...", file=sys.stderr)
    manifest = await generate_manifest()

    print("Analyzing drift...", file=sys.stderr)
    report = await detect_drift(manifest)

    if args.fix:
        docs = load_docs()
        print("Generating fixes...", file=sys.stderr)
        fix_report = await generate_fixes(report, docs)

        if args.apply:
            print("Applying fixes...", file=sys.stderr)
            apply_result = apply_fixes(fix_report)

            # Auto-regenerate screen context if drift detected
            screen_drift = [i for i in report.drift_items if "screen_context.md" in i.doc_file]
            if screen_drift:
                try:
                    import subprocess
                    regen_result = subprocess.run(
                        ["uv", "run", "python", "scripts/generate_screen_context.py"],
                        capture_output=True, text=True, timeout=30,
                        cwd=str(AI_AGENTS_DIR),
                    )
                    if regen_result.returncode == 0:
                        log.info("Auto-regenerated screen analyzer context")
                except Exception as exc:
                    log.warning("Failed to auto-regenerate screen context: %s", exc)

            committed = _git_commit_fixes(apply_result.changed_files, apply_result.applied)
            _notify_fixes(apply_result, committed)

            print(f"Applied: {apply_result.applied}, Skipped: {apply_result.skipped}", file=sys.stderr)
            if apply_result.errors:
                for err in apply_result.errors:
                    print(f"  Skip: {err}", file=sys.stderr)
            if committed:
                print("Changes committed to git.", file=sys.stderr)

            # Re-scan after applying fixes so drift-report.json reflects current state
            if apply_result.applied > 0:
                print("Re-scanning after fixes...", file=sys.stderr)
                report = await detect_drift(manifest)
                # Save updated report (same as drift-watchdog)
                from shared.config import PROFILES_DIR
                report_path = PROFILES_DIR / "drift-report.json"
                report_path.write_text(report.model_dump_json(indent=2))
                print(f"Updated {report_path.name}: {len(report.drift_items)} items remaining", file=sys.stderr)

            if args.json:
                print(apply_result.model_dump_json(indent=2))
            else:
                print(f"\nDrift auto-fix complete. {apply_result.applied} applied, {len(report.drift_items)} remaining.")
                if apply_result.changed_files:
                    for f in apply_result.changed_files:
                        short = f.replace(str(HAPAX_HOME), "~")
                        print(f"  Updated: {short}")
        elif args.json:
            print(fix_report.model_dump_json(indent=2))
        else:
            print(format_fixes(fix_report))
    elif args.json:
        print(report.model_dump_json(indent=2))
    else:
        print(format_human(report))


if __name__ == "__main__":
    asyncio.run(main())
