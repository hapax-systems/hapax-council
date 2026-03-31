#!/usr/bin/env python3
"""SDLC Planning Agent.

Reads an issue + triage output, queries codebase context, and produces
an implementation plan with files to modify and acceptance criteria.

Usage::

    uv run python -m scripts.sdlc_plan --issue-number 42
    uv run python -m scripts.sdlc_plan --issue-number 42 --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents._axiom_registry import load_axioms
from sdlc.github import fetch_issue, post_issue_comment
from sdlc.trace_export import TraceContext, is_file_export

# ---------------------------------------------------------------------------
# Structured output
# ---------------------------------------------------------------------------


class FileChange(BaseModel):
    path: str
    reason: str
    change_type: str  # "modify" | "create" | "delete"


class PlanResult(BaseModel):
    files_to_modify: list[FileChange]
    acceptance_criteria: list[str]
    test_strategy: str
    implementation_notes: str
    estimated_diff_lines: int


# ---------------------------------------------------------------------------
# Codebase context
# ---------------------------------------------------------------------------

CODEBASE_MAP_PATH = Path(__file__).resolve().parent.parent / "codebase-map.json"


def _load_codebase_context(issue_text: str) -> str:
    """Load codebase context — prefer Qdrant, fall back to static map."""
    # Try Qdrant first (available on self-hosted runner).
    try:
        from agents._config import embed, get_qdrant

        client = get_qdrant()
        vector = embed(issue_text, prefix="search_query")
        results = client.query_points(
            collection_name="documents",
            query=vector,
            limit=10,
        )
        if results.points:
            chunks = []
            for pt in results.points:
                path = pt.payload.get("path", "unknown")
                content = pt.payload.get("content", "")[:500]
                chunks.append(f"### {path}\n```\n{content}\n```")
            return "\n\n".join(chunks)
    except Exception:
        pass

    # Fall back to static codebase map.
    if CODEBASE_MAP_PATH.exists():
        data = json.loads(CODEBASE_MAP_PATH.read_text())
        entries = []
        for f in data.get("files", [])[:30]:
            sig = ", ".join(f.get("functions", [])[:5])
            entries.append(f"- `{f['path']}`: {f.get('docstring', '')[:80]} [{sig}]")
        return "\n".join(entries)

    return "(No codebase context available — working from issue description only.)"


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


def _build_system_prompt(axioms: list) -> str:
    axiom_text = "\n".join(f"- **{a.id}**: {a.text.strip()}" for a in axioms)
    return f"""\
You are the planning agent for hapax-council, a single-user personal operating system.

Your job is to produce a concrete implementation plan for a triaged GitHub issue.

## Constitutional Axioms
{axiom_text}

## Instructions
1. Identify the exact files that need modification (be specific with paths).
2. For each file, explain what changes are needed and why.
3. Write clear acceptance criteria that can be verified by automated tests.
4. Describe the test strategy (what tests to add/modify).
5. Estimate the total diff size in lines.

## Constraints
- Never plan changes to protected paths: agents/health_monitor.py, shared/alert_state.py,
  shared/axiom_enforcement.py, shared/config.py, axioms/, hooks/, systemd/.
- Keep changes minimal — prefer modifying existing code over creating new files.
- Plans should be implementable in a single PR with < 500 lines of diff.

## Output
Return a JSON object with: files_to_modify, acceptance_criteria, test_strategy,
implementation_notes, estimated_diff_lines.
"""


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------


def _call_llm(system: str, user: str, *, dry_run: bool = False) -> PlanResult:
    if dry_run:
        return PlanResult(
            files_to_modify=[],
            acceptance_criteria=["Tests pass"],
            test_strategy="Add unit tests",
            implementation_notes="Dry run — no plan generated.",
            estimated_diff_lines=0,
        )

    try:
        import anthropic

        client = anthropic.Anthropic()
        response = client.messages.create(
            model=os.environ.get("SDLC_PLAN_MODEL", "claude-sonnet-4-6"),
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = response.content[0].text
    except ImportError:
        from pydantic_ai import Agent

        agent = Agent(
            os.environ.get("SDLC_PLAN_MODEL", "anthropic:claude-sonnet-4-6"),
            system_prompt=system,
            output_type=PlanResult,
        )
        result = agent.run_sync(user)
        return result.output

    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]
    return PlanResult.model_validate_json(text.strip())


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run_plan(issue_number: int, *, dry_run: bool = False, post_comment: bool = True) -> PlanResult:
    """Generate an implementation plan for a triaged issue."""
    issue = fetch_issue(issue_number)
    axioms = load_axioms(scope="constitutional")
    context = _load_codebase_context(f"{issue.title}\n{issue.body}")

    system_prompt = _build_system_prompt(axioms)
    user_prompt = f"""\
# Issue #{issue.number}: {issue.title}

{issue.body}

## Codebase Context
{context}
"""

    model = os.environ.get("SDLC_PLAN_MODEL", "claude-sonnet-4-6")
    t0 = time.monotonic()

    trace_id = f"sdlc-plan-{issue_number}"
    with TraceContext("planning", trace_id, issue_number=issue_number) as span:
        result = _call_llm(system_prompt, user_prompt, dry_run=dry_run)
        span.model = model
        span.output_text = result.model_dump_json()

    duration_ms = int((time.monotonic() - t0) * 1000)

    try:
        from sdlc.log import log_sdlc_event

        log_sdlc_event(
            "plan",
            issue_number=issue_number,
            result={
                "files_count": len(result.files_to_modify),
                "files": [
                    {"path": f.path, "change_type": f.change_type} for f in result.files_to_modify
                ][:10],
                "criteria_count": len(result.acceptance_criteria),
                "estimated_diff_lines": result.estimated_diff_lines,
            },
            duration_ms=duration_ms,
            model_used=model,
            dry_run=dry_run,
            metadata={"trace_id": f"sdlc-plan-{issue_number}"},
        )
    except Exception:
        pass

    try:
        from sdlc.audit import log_audit

        log_audit(
            action="sdlc_plan",
            actor="sdlc_pipeline",
            check_name=f"plan-issue-{issue_number}",
            outcome="completed",
            duration_ms=duration_ms,
            metadata={
                "files_count": len(result.files_to_modify),
                "estimated_diff_lines": result.estimated_diff_lines,
            },
        )
    except Exception:
        pass

    if post_comment and not dry_run:
        files_list = "\n".join(
            f"- `{f.path}` ({f.change_type}): {f.reason}" for f in result.files_to_modify
        )
        criteria_list = "\n".join(f"- [ ] {c}" for c in result.acceptance_criteria)
        comment = f"""\
## 🤖 Implementation Plan

### Files to Modify
{files_list}

### Acceptance Criteria
{criteria_list}

### Test Strategy
{result.test_strategy}

### Notes
{result.implementation_notes}

*Estimated diff: ~{result.estimated_diff_lines} lines*
"""
        post_issue_comment(issue_number, comment)

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="SDLC Planning Agent")
    parser.add_argument("--issue-number", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-comment", action="store_true", help="Skip posting to GitHub")
    args = parser.parse_args()

    if not args.dry_run and not is_file_export():
        try:
            from shared import langfuse_config  # noqa: F401
        except ImportError:
            pass

    result = run_plan(
        args.issue_number,
        dry_run=args.dry_run,
        post_comment=not args.no_comment,
    )
    print(json.dumps(result.model_dump(), indent=2))


if __name__ == "__main__":
    main()
