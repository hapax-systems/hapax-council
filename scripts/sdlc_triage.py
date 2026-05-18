#!/usr/bin/env python3
"""SDLC Issue Triage Agent.

Classifies GitHub issues by type, complexity, and axiom relevance.
Outputs structured JSON for workflow consumption.

Usage::

    uv run python -m scripts.sdlc_triage --issue-number 42
    uv run python -m scripts.sdlc_triage --issue-number 42 --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

# Ensure project root is importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents._axiom_registry import load_axioms
from sdlc.github import fetch_issue
from sdlc.trace_export import TraceContext, is_file_export

# ---------------------------------------------------------------------------
# Model routing
# ---------------------------------------------------------------------------

DEFAULT_TRIAGE_MODEL = "balanced"


def _litellm_route_name(model_name: str) -> str:
    """Map legacy provider-prefixed model names to local LiteLLM routes."""
    model_name = model_name.strip()
    for prefix in ("anthropic:", "anthropic/"):
        if model_name.startswith(prefix):
            return model_name.removeprefix(prefix)
    return model_name


def _configured_triage_model() -> str:
    return _litellm_route_name(os.environ.get("SDLC_TRIAGE_MODEL", DEFAULT_TRIAGE_MODEL))


# ---------------------------------------------------------------------------
# Structured output model
# ---------------------------------------------------------------------------


class TriageResult(BaseModel):
    type: Literal["bug", "feature", "chore"]
    complexity: Literal["S", "M", "L"]
    axiom_relevance: list[str]
    reject_reason: str | None = None
    file_hints: list[str] = []


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

PROTECTED_PATHS = [
    "agents/health_monitor.py",
    "shared/alert_state.py",
    "shared/axiom_enforcement.py",
    "shared/config.py",
    "axioms/",
    "hooks/",
    "systemd/",
    "hapax-backup-*.sh",
]


def _build_system_prompt(axioms: list) -> str:
    axiom_text = "\n".join(f"- **{a.id}**: {a.text.strip()}" for a in axioms)
    return f"""\
You are the triage agent for hapax-council, a single-user personal operating system.

Your job is to classify a GitHub issue by type, complexity, and axiom relevance.

## Constitutional Axioms
{axiom_text}

## Complexity Heuristics
- **S** (small): Single file change, isolated fix, clear solution path.
- **M** (medium): 2-5 files, moderate logic changes, tests need updating.
- **L** (large): Architectural, cross-cutting, > 5 files, ambiguous requirements.

## Rejection Criteria (set reject_reason if any apply)
- Complexity is L (too large for automated implementation).
- Requirements are ambiguous or missing acceptance criteria.
- Changes touch protected paths: {", ".join(PROTECTED_PATHS)}.
- Issue requires architectural decisions the operator should make.

## Output
Return a JSON object with:
- type: "bug" | "feature" | "chore"
- complexity: "S" | "M" | "L"
- axiom_relevance: list of axiom IDs relevant to this change (can be empty)
- reject_reason: null if agent-eligible, or a string explaining why not
- file_hints: list of file paths likely involved (best guess from issue description)
"""


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------


def _build_triage_agent(model_name: str, system: str):
    from pydantic_ai import Agent

    from shared.config import get_model

    return Agent(
        get_model(model_name),
        system_prompt=system,
        output_type=TriageResult,
    )


def _call_llm(system: str, user: str, *, dry_run: bool = False) -> TriageResult:
    if dry_run:
        return TriageResult(
            type="chore",
            complexity="S",
            axiom_relevance=[],
            reject_reason=None,
            file_hints=[],
        )

    agent = _build_triage_agent(_configured_triage_model(), system)
    result = agent.run_sync(user)
    return result.output


# ---------------------------------------------------------------------------
# Similar-issue search
# ---------------------------------------------------------------------------

_TRIAGE_STOP_WORDS = frozenset(
    [
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "can",
        "shall",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "between",
        "out",
        "off",
        "over",
        "under",
        "again",
        "further",
        "then",
        "once",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "not",
        "no",
        "nor",
        "and",
        "but",
        "or",
        "so",
        "if",
        "when",
        "where",
        "how",
        "what",
        "which",
        "who",
        "whom",
        "why",
    ]
)


def _extract_search_keywords(title: str, body: str, max_keywords: int = 5) -> list[str]:
    """Extract salient keywords from issue text for search."""
    text = f"{title} {body}"
    words = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", text.lower())
    seen: set[str] = set()
    keywords: list[str] = []
    for w in words:
        if w not in _TRIAGE_STOP_WORDS and w not in seen:
            seen.add(w)
            keywords.append(w)
        if len(keywords) >= max_keywords:
            break
    return keywords


def find_similar_closed(
    issue_title: str,
    issue_body: str,
    *,
    skip_github: bool = False,
) -> list[dict]:
    """Find closed issues/PRs similar to the given issue.

    Two strategies: GitHub search (network) and local event log scan.
    Returns list of dicts with number, title, labels, source.
    """
    keywords = _extract_search_keywords(issue_title, issue_body)
    if not keywords:
        return []

    results: list[dict] = []

    if not skip_github:
        try:
            from sdlc.github import search_closed_issues

            query = " ".join(keywords[:4])
            gh_results = search_closed_issues(query, limit=5)
            for item in gh_results:
                item["source"] = "github"
                results.append(item)
        except Exception:
            pass

    return results


def _format_similar_issues(similar: list[dict]) -> str:
    """Format similar closed issues as context for the triage prompt."""
    if not similar:
        return ""
    lines = ["\n## Similar Past Issues (Closed)"]
    for item in similar[:5]:
        labels_str = ", ".join(item.get("labels", []))
        suffix = f" [{labels_str}]" if labels_str else ""
        lines.append(f"- #{item['number']}: {item['title']}{suffix}")
    lines.append("")
    lines.append("Consider whether this issue is a duplicate or regression of the above.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run_triage(
    issue_number: int, *, dry_run: bool = False, skip_similar: bool = False
) -> TriageResult:
    """Triage a GitHub issue and return structured result."""
    issue = fetch_issue(issue_number)
    axioms = load_axioms(scope="constitutional")

    system_prompt = _build_system_prompt(axioms)
    user_prompt = f"# {issue.title}\n\n{issue.body}"

    similar = find_similar_closed(issue.title, issue.body, skip_github=skip_similar)
    similar_context = _format_similar_issues(similar)
    if similar_context:
        user_prompt += similar_context

    model = _configured_triage_model()
    t0 = time.monotonic()

    trace_id = f"sdlc-triage-{issue_number}"
    with TraceContext("triage", trace_id, issue_number=issue_number) as span:
        result = _call_llm(system_prompt, user_prompt, dry_run=dry_run)
        span.model = model
        span.output_text = result.model_dump_json()

    duration_ms = int((time.monotonic() - t0) * 1000)

    try:
        from sdlc.log import log_sdlc_event

        log_sdlc_event(
            "triage",
            issue_number=issue_number,
            result={
                "type": result.type,
                "complexity": result.complexity,
                "reject_reason": result.reject_reason,
                "axiom_relevance": result.axiom_relevance,
                "file_hints": result.file_hints[:10],  # cap to avoid huge entries
            },
            duration_ms=duration_ms,
            model_used=model,
            dry_run=dry_run,
            metadata={"trace_id": f"sdlc-triage-{issue_number}"},
        )
    except Exception:
        pass

    try:
        from sdlc.audit import log_audit

        log_audit(
            action="sdlc_triage",
            actor="sdlc_pipeline",
            check_name=f"triage-issue-{issue_number}",
            outcome="rejected" if result.reject_reason else "accepted",
            classification=f"{result.type}/{result.complexity}",
            duration_ms=duration_ms,
            metadata={"axiom_relevance": result.axiom_relevance},
        )
    except Exception:
        pass

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="SDLC Issue Triage Agent")
    parser.add_argument("--issue-number", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true", help="Use fixture response")
    parser.add_argument("--skip-similar", action="store_true", help="Skip similar-issue search")
    args = parser.parse_args()

    if not args.dry_run and not is_file_export():
        try:
            from shared import langfuse_config  # noqa: F401
        except ImportError:
            pass

    result = run_triage(args.issue_number, dry_run=args.dry_run, skip_similar=args.skip_similar)
    print(json.dumps(result.model_dump(), indent=2))


if __name__ == "__main__":
    main()
