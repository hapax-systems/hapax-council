"""scout.py — Horizon scanner for external fitness evaluation.

Evaluates whether each stack component is still the best choice by searching
for alternatives, updates, and benchmark comparisons. Reads a component
registry, performs web searches via Tavily API, then uses an LLM to evaluate
findings against operator constraints and preferences.

Where the drift detector asks "does documentation match reality?", the scout
asks "does reality match the frontier?"

Usage:
    uv run python -m agents.scout                    # Scan all components
    uv run python -m agents.scout --json             # Machine-readable JSON
    uv run python -m agents.scout --save             # Save to profiles/scout-report.{json,md}
    uv run python -m agents.scout --component vector-database  # Scan one component
    uv run python -m agents.scout --dry-run          # Show what would be searched, no API calls
    uv run python -m agents.scout --notify           # Desktop notification if recommendations found
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

import yaml
from pydantic import BaseModel, Field
from pydantic_ai import Agent

from agents._operator import get_system_prompt_fragment

# ── Vendored from shared/config.py ──────────────────────────────────────────
_LITELLM_BASE: str = os.environ.get(
    "LITELLM_API_BASE", os.environ.get("LITELLM_BASE_URL", "http://localhost:4000")
)
_LITELLM_KEY: str = os.environ.get("LITELLM_API_KEY", "")
_MODELS: dict[str, str] = {
    "fast": "gemini-flash",
    "balanced": "claude-sonnet",
    "long-context": "gemini-flash",
    "reasoning": "qwen3:8b",
    "coding": "qwen3:8b",
    "local-fast": "qwen3:8b",
}


def get_model(alias_or_id: str = "balanced"):
    """Create a LiteLLM-backed chat model (vendored from shared.config)."""
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.litellm import LiteLLMProvider

    model_id = _MODELS.get(alias_or_id, alias_or_id)
    return OpenAIChatModel(
        model_id,
        provider=LiteLLMProvider(api_base=_LITELLM_BASE, api_key=_LITELLM_KEY),
    )


# ── End vendored ────────────────────────────────────────────────────────────

# Import Langfuse OTel config (side-effect: configures exporter)
try:
    from shared import langfuse_config  # noqa: F401
except ImportError:
    pass

from opentelemetry import trace

_tracer = trace.get_tracer(__name__)

log = logging.getLogger("scout")

PROFILES_DIR: Path = Path(__file__).resolve().parent.parent / "profiles"

REGISTRY_FILE = PROFILES_DIR / "component-registry.yaml"
REPORT_JSON = PROFILES_DIR / "scout-report.json"
REPORT_MD = PROFILES_DIR / "scout-report.md"
DECISIONS_FILE = PROFILES_DIR / "scout-decisions.jsonl"
DECISION_COOLDOWN_DAYS = 90

TAVILY_API_KEY = os.environ.get(
    "TAVILY_API_KEY",
    "",
)


# ── Schemas ──────────────────────────────────────────────────────────────────


class Finding(BaseModel):
    """A single finding about an alternative or update."""

    name: str = Field(description="Name of the alternative or update")
    description: str = Field(description="What it is and why it's relevant, 1-2 sentences")
    url: str = Field(default="", description="Source URL if available")


class Recommendation(BaseModel):
    """Evaluation of a single component against external landscape."""

    component: str = Field(description="Component key from registry")
    current: str = Field(description="What we're currently using")
    tier: str = Field(description="adopt, evaluate, monitor, or current-best")
    summary: str = Field(description="1-2 sentence assessment")
    findings: list[Finding] = Field(
        default_factory=list, description="Notable alternatives or updates found"
    )
    migration_effort: str = Field(default="", description="low, medium, or high")
    confidence: str = Field(
        default="medium", description="low, medium, or high — how confident is this assessment"
    )


class ScoutReport(BaseModel):
    """Complete horizon scan report."""

    generated_at: str = Field(description="ISO timestamp")
    components_scanned: int = Field(default=0)
    recommendations: list[Recommendation] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list, description="Components that failed to scan")
    skipped: list[str] = Field(
        default_factory=list, description="Components skipped due to active decisions"
    )


def load_decisions(path: Path | None = None) -> dict[str, dict]:
    """Load scout decisions, returning latest decision per component."""
    path = path or DECISIONS_FILE
    if not path.is_file():
        return {}
    decisions: dict[str, dict] = {}
    for line in path.read_text().strip().splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            component = record.get("component", "")
            existing = decisions.get(component)
            if existing is None or record.get("timestamp", "") > existing.get("timestamp", ""):
                decisions[component] = record
        except json.JSONDecodeError:
            continue
    return decisions


# ── Component Registry ───────────────────────────────────────────────────────


@dataclass
class ComponentSpec:
    """Parsed component from the registry YAML."""

    key: str
    role: str
    current: str
    provider: str
    constraints: list[str]
    preferences: list[str]
    search_hints: list[str]
    eval_notes: str


def load_registry(filter_component: str | None = None) -> list[ComponentSpec]:
    """Load component registry from YAML."""
    with _tracer.start_as_current_span("scout.load_registry"):
        if not REGISTRY_FILE.exists():
            log.error(f"Component registry not found: {REGISTRY_FILE}")
            return []

        data = yaml.safe_load(REGISTRY_FILE.read_text())
        components = []
        for key, spec in data.get("components", {}).items():
            if filter_component and key != filter_component:
                continue
            components.append(
                ComponentSpec(
                    key=key,
                    role=spec.get("role", ""),
                    current=spec.get("current", ""),
                    provider=spec.get("provider", ""),
                    constraints=spec.get("constraints", []),
                    preferences=spec.get("preferences", []),
                    search_hints=spec.get("search_hints", []),
                    eval_notes=spec.get("eval_notes", ""),
                )
            )
        return components


# ── Web Search ───────────────────────────────────────────────────────────────


def _tavily_search(query: str, max_results: int = 5) -> list[dict]:
    """Search via Tavily REST API. Returns list of {title, url, content}."""
    if not TAVILY_API_KEY:
        log.warning("TAVILY_API_KEY not set — skipping web search")
        return []

    payload = json.dumps(
        {
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
            "include_answer": False,
        }
    ).encode()

    req = Request(
        "https://api.tavily.com/search",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {TAVILY_API_KEY}",
        },
        method="POST",
    )

    try:
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "content": r.get("content", ""),
                }
                for r in data.get("results", [])
            ]
    except (URLError, TimeoutError, json.JSONDecodeError) as e:
        log.warning(f"Tavily search failed for '{query}': {e}")
        return []


def search_component(spec: ComponentSpec) -> str:
    """Run all search hints for a component, return aggregated results as text."""
    with _tracer.start_as_current_span(
        "scout.search_component", attributes={"component": spec.key}
    ):
        all_results: list[dict] = []
        seen_urls: set[str] = set()

        for hint in spec.search_hints:
            results = _tavily_search(hint, max_results=3)
            for r in results:
                if r["url"] not in seen_urls:
                    seen_urls.add(r["url"])
                    all_results.append(r)

            # Rate limit: brief pause between searches
            time.sleep(0.5)

        if not all_results:
            return "No search results found."

        lines = []
        for r in all_results:
            lines.append(f"### {r['title']}")
            lines.append(f"URL: {r['url']}")
            lines.append(r["content"])
            lines.append("")

        return "\n".join(lines)


# ── LLM Evaluation ──────────────────────────────────────────────────────────

EVAL_SYSTEM_PROMPT = """\
You are a technology evaluation agent for an LLM infrastructure stack. Given information
about a current component and web search results about alternatives, produce a structured
recommendation.

EVALUATION CRITERIA:
- Does the current solution still meet all hard constraints?
- Are there alternatives that better satisfy the soft preferences?
- What is the migration effort (low/medium/high)?
- How confident are you in this assessment (low/medium/high)?

RECOMMENDATION TIERS:
- "adopt": Clear improvement exists. Low risk, reversible, should switch.
- "evaluate": Promising alternative found. Needs deeper investigation or operator testing.
- "monitor": Something interesting is emerging but not ready or not clearly better yet.
- "current-best": Current choice is still the best fit. No action needed.

GUIDELINES:
- Be conservative. "current-best" is the right call most of the time.
- Only recommend "adopt" when the improvement is clear AND migration cost is justified.
- State epistemic confidence honestly. Web search results may be outdated or biased.
- Consider the eval_notes — they contain context about migration costs and what matters.
- If search results are thin or inconclusive, say so and rate confidence as "low".
- Never recommend something you're not reasonably sure exists and works.
- Include specific names, versions, and URLs in findings.
- Distinguish between 'genuinely better for this operator's constraints' and 'newer/more novel.'
  Recency alone is not an advantage. A newer tool with equivalent functionality is NOT worth the
  migration cost. Weight stability, ecosystem maturity, and migration effort heavily — switching
  costs are real and compound.

Call lookup_constraints() for additional operator constraints.
"""

eval_agent = Agent(
    get_model("balanced"),
    system_prompt=get_system_prompt_fragment("scout") + "\n\n" + EVAL_SYSTEM_PROMPT,
    output_type=Recommendation,
)

# Register on-demand operator context tools
from shared.context_tools import get_context_tools

for _tool_fn in get_context_tools():
    eval_agent.tool(_tool_fn)

from shared.axiom_tools import get_axiom_tools

for _tool_fn in get_axiom_tools():
    eval_agent.tool(_tool_fn)


async def evaluate_component(
    spec: ComponentSpec,
    search_results: str,
    usage_context: str = "",
) -> Recommendation:
    """Use LLM to evaluate a component against search findings."""
    with _tracer.start_as_current_span(
        "scout.evaluate_component", attributes={"component": spec.key}
    ):
        usage_block = ""
        if usage_context:
            usage_block = f"\n**Operator usage:** {usage_context}\nConsider usage frequency and centrality when assessing migration risk and urgency.\n"

        # Skip LLM evaluation when no search results available
        if search_results.strip() == "No search results found.":
            return Recommendation(
                component=spec.key,
                current=spec.current,
                tier="current-best",
                summary="No web search results available for evaluation",
                confidence="low",
            )

        prompt = f"""## Component: {spec.key}

**Current solution:** {spec.current}
**Role:** {spec.role}
**Provider:** {spec.provider}

**Hard constraints (must satisfy):**
{chr(10).join(f"- {c}" for c in spec.constraints)}

**Soft preferences (nice to have):**
{chr(10).join(f"- {p}" for p in spec.preferences)}

**Migration notes:** {spec.eval_notes}
{usage_block}
## Search Results

{search_results}

Evaluate whether the current solution is still the best choice, or if any
alternative deserves attention. Be specific about what you found."""

        try:
            result = await eval_agent.run(prompt)
        except Exception as exc:
            log.error("LLM evaluation failed for %s: %s", spec.key, exc)
            return Recommendation(
                component=spec.key,
                current=spec.current,
                tier="current-best",
                summary=f"Evaluation failed: {exc}",
                confidence="low",
            )
        rec = result.output
        # Ensure component key is set correctly
        rec.component = spec.key
        rec.current = spec.current
        return rec


# ── Main Pipeline ────────────────────────────────────────────────────────────


def _build_usage_map() -> dict[str, str]:
    """Build component-key → usage description map from Langfuse data."""
    with _tracer.start_as_current_span("scout.build_usage_map"):
        try:
            from shared.langfuse_client import is_available, langfuse_get
        except ImportError:
            return {}

        if not is_available():
            return {}

        try:
            since = (datetime.now(UTC) - timedelta(days=7)).isoformat()
            result = langfuse_get(
                "/observations",
                {
                    "fromStartTime": since,
                    "type": "GENERATION",
                    "limit": 100,
                    "page": 1,
                },
            )
            observations = result.get("data", [])
            total = result.get("meta", {}).get("totalItems", len(observations))

            # Count calls as a proxy for gateway usage
            usage_map: dict[str, str] = {}
            if total > 0:
                usage_map["litellm"] = f"Gateway for {total} LLM calls in last 7 days"

            # Count by model to infer provider usage
            model_counts: dict[str, int] = {}
            for obs in observations:
                model = obs.get("model", "unknown")
                model_counts[model] = model_counts.get(model, 0) + 1

            for model, count in sorted(model_counts.items(), key=lambda x: -x[1])[:5]:
                if "ollama" in model.lower() or model in (
                    "qwen3:8b",
                    "qwen3:8b",
                    "nomic-embed",
                ):
                    usage_map.setdefault(
                        "ollama", f"Serving local models, {count}+ calls in 7 days"
                    )
                if "embed" in model.lower():
                    usage_map.setdefault("embedding-model", f"{count} embedding calls in 7 days")

            return usage_map
        except Exception as e:
            log.debug(f"Failed to build usage map: {e}")
            return {}


async def run_scout(
    filter_component: str | None = None,
    dry_run: bool = False,
) -> ScoutReport:
    """Run the full scout pipeline: load registry, search, evaluate."""
    with _tracer.start_as_current_span(
        "scout.run",
        attributes={"agent.name": "scout", "agent.repo": "hapax-council"},
    ):
        return await _run_scout_impl(filter_component, dry_run)


async def _run_scout_impl(
    filter_component: str | None = None,
    dry_run: bool = False,
) -> ScoutReport:
    """Implementation of run_scout, wrapped by OTel span."""
    components = load_registry(filter_component)
    if not components:
        return ScoutReport(
            generated_at=datetime.now(UTC).isoformat()[:19] + "Z",
            errors=["No components found in registry"],
        )

    if dry_run:
        # Show what would be searched without making API calls
        for spec in components:
            print(f"\n{spec.key} ({spec.current}):", file=sys.stderr)
            for hint in spec.search_hints:
                print(f"  → {hint}", file=sys.stderr)
        return ScoutReport(
            generated_at=datetime.now(UTC).isoformat()[:19] + "Z",
            components_scanned=0,
        )

    # Build usage context from Langfuse (graceful degradation if unavailable)
    usage_map = _build_usage_map()

    # Load operator decisions for cooldown suppression
    decisions = load_decisions()

    report = ScoutReport(
        generated_at=datetime.now(UTC).isoformat()[:19] + "Z",
    )

    for spec in components:
        # Check decision cooldown
        decision = decisions.get(spec.key)
        if decision and decision.get("decision") in ("dismissed", "deferred"):
            try:
                decided_at = datetime.fromisoformat(decision["timestamp"])
                age_days = (datetime.now(UTC) - decided_at).days
                if age_days < DECISION_COOLDOWN_DAYS:
                    report.skipped.append(f"{spec.key} ({decision['decision']} {age_days}d ago)")
                    print(
                        f"Skipping: {spec.key} ({decision['decision']} {age_days}d ago, cooldown active)",
                        file=sys.stderr,
                    )
                    continue
            except (ValueError, KeyError):
                pass  # Malformed timestamp — evaluate normally

        log.info(f"Scanning: {spec.key} ({spec.current})")
        print(f"Scanning: {spec.key}...", file=sys.stderr)

        try:
            # Phase 1: Web search (no LLM)
            search_results = search_component(spec)

            # Phase 2: LLM evaluation (with usage context if available)
            rec = await evaluate_component(
                spec,
                search_results,
                usage_context=usage_map.get(spec.key, ""),
            )
            report.recommendations.append(rec)
            report.components_scanned += 1

            tier_icon = {"adopt": "▲", "evaluate": "?", "monitor": "○", "current-best": "✓"}
            print(f"  [{tier_icon.get(rec.tier, '?')}] {rec.tier}: {rec.summary}", file=sys.stderr)

        except Exception as e:
            log.error(f"Failed to scan {spec.key}: {e}")
            report.errors.append(f"{spec.key}: {e}")

    return report


# ── Formatters ───────────────────────────────────────────────────────────────


def format_report_md(report: ScoutReport) -> str:
    """Format scout report as markdown."""
    lines = [
        "# Scout Report — Horizon Scan",
        f"*Generated {report.generated_at} — {report.components_scanned} components scanned*",
        "",
    ]

    # Group by tier
    tier_order = ["adopt", "evaluate", "monitor", "current-best"]
    tier_labels = {
        "adopt": "Adopt — Switch to these",
        "evaluate": "Evaluate — Worth investigating",
        "monitor": "Monitor — Track for later",
        "current-best": "Current Best — No change needed",
    }

    for tier in tier_order:
        recs = [r for r in report.recommendations if r.tier == tier]
        if not recs:
            continue

        lines.append(f"## {tier_labels.get(tier, tier)}")
        lines.append("")

        for rec in recs:
            lines.append(f"### {rec.component}")
            lines.append(f"**Current:** {rec.current}")
            lines.append(f"**Assessment:** {rec.summary}")
            if rec.migration_effort:
                lines.append(f"**Migration effort:** {rec.migration_effort}")
            lines.append(f"**Confidence:** {rec.confidence}")
            lines.append("")

            if rec.findings:
                for f in rec.findings:
                    url_part = f" ([link]({f.url}))" if f.url else ""
                    lines.append(f"- **{f.name}**{url_part}: {f.description}")
                lines.append("")

    if report.skipped:
        lines.append("## Skipped (decision cooldown)")
        for s in report.skipped:
            lines.append(f"- {s}")
        lines.append("")

    if report.errors:
        lines.append("## Errors")
        for err in report.errors:
            lines.append(f"- {err}")
        lines.append("")

    return "\n".join(lines)


def format_report_human(report: ScoutReport) -> str:
    """Format scout report for terminal display."""
    lines = [
        f"Scout Report — {report.generated_at}",
        f"{report.components_scanned} components scanned",
        "",
    ]

    tier_icons = {"adopt": "▲", "evaluate": "?", "monitor": "○", "current-best": "✓"}

    # Show actionable items first
    for rec in sorted(
        report.recommendations,
        key=lambda r: (
            ["adopt", "evaluate", "monitor", "current-best"].index(r.tier)
            if r.tier in ["adopt", "evaluate", "monitor", "current-best"]
            else 99
        ),
    ):
        icon = tier_icons.get(rec.tier, "?")
        lines.append(f"  [{icon}] {rec.component}: {rec.tier} ({rec.confidence} confidence)")
        lines.append(f"      {rec.summary}")
        if rec.findings and rec.tier in ("adopt", "evaluate"):
            for f in rec.findings[:2]:
                lines.append(f"      → {f.name}: {f.description}")
        lines.append("")

    if report.errors:
        lines.append("Errors:")
        for err in report.errors:
            lines.append(f"  - {err}")

    return "\n".join(lines)


# ── Notification ─────────────────────────────────────────────────────────────


def send_notification(report: ScoutReport) -> None:
    """Send desktop notification if there are actionable recommendations."""
    actionable = [r for r in report.recommendations if r.tier in ("adopt", "evaluate")]
    if not actionable:
        return

    summary = f"Scout: {len(actionable)} component(s) need attention"
    body = "\n".join(f"- {r.component}: {r.tier}" for r in actionable[:3])

    from agents._notify import send_notification as _notify

    _notify("Horizon Scan", f"{summary}\n{body}", priority="default", tags=["telescope"])


# ── CLI ──────────────────────────────────────────────────────────────────────


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Horizon scanner — evaluate stack components against external landscape",
        prog="python -m agents.scout",
    )
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    parser.add_argument(
        "--save", action="store_true", help="Save to profiles/scout-report.{json,md}"
    )
    parser.add_argument("--component", type=str, default=None, help="Scan only this component key")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show search queries without calling APIs"
    )
    parser.add_argument(
        "--notify", action="store_true", help="Desktop notification if recommendations found"
    )
    args = parser.parse_args()

    from agents._log_setup import configure_logging

    configure_logging(agent="scout")

    # Load Tavily API key from pass if not in environment
    global TAVILY_API_KEY
    if not TAVILY_API_KEY:
        try:
            result = subprocess.run(
                ["pass", "show", "api/tavily"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                TAVILY_API_KEY = result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    if not TAVILY_API_KEY and not args.dry_run:
        print("Error: TAVILY_API_KEY not set and not found in pass store", file=sys.stderr)
        print("Set TAVILY_API_KEY or run: pass insert api/tavily", file=sys.stderr)
        sys.exit(1)

    report = await run_scout(
        filter_component=args.component,
        dry_run=args.dry_run,
    )

    if args.save and not args.dry_run:
        REPORT_JSON.write_text(report.model_dump_json(indent=2))
        REPORT_MD.write_text(format_report_md(report))
        print(f"Saved to {REPORT_JSON} and {REPORT_MD}", file=sys.stderr)

    if args.notify and not args.dry_run:
        send_notification(report)

    if args.json:
        print(report.model_dump_json(indent=2))
    elif not args.dry_run:
        print(format_report_human(report))


if __name__ == "__main__":
    asyncio.run(main())
