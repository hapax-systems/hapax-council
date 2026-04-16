#!/usr/bin/env python3
"""SDLC Adversarial Review Agent.

Reviews agent-authored PRs independently — receives only the diff and fresh
codebase context, never the author's reasoning or planning documents.

Usage::

    uv run python -m scripts.sdlc_review --pr-number 10
    uv run python -m scripts.sdlc_review --pr-number 10 --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents._axiom_registry import load_axioms
from sdlc.github import (
    add_pr_labels,
    fetch_pr_changed_files,
    fetch_pr_diff,
    post_pr_comment,
)
from sdlc.trace_export import TraceContext, is_file_export

# ---------------------------------------------------------------------------
# Structured output
# ---------------------------------------------------------------------------


class ReviewFinding(BaseModel):
    file: str
    line: int | None = None
    severity: Literal["HIGH", "MEDIUM", "LOW"]
    description: str
    suggestion: str = ""


class AxiomConcern(BaseModel):
    axiom_id: str
    concern: str
    severity: Literal["HIGH", "MEDIUM", "LOW"]


class ReviewResult(BaseModel):
    verdict: Literal["approve", "request_changes"]
    findings: list[ReviewFinding] = []
    axiom_concerns: list[AxiomConcern] = []
    summary: str = ""


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


def _build_system_prompt(axioms: list) -> str:
    axiom_text = "\n".join(f"- **{a.id}**: {a.text.strip()}" for a in axioms)
    return f"""\
You are an independent code reviewer for hapax-council, a single-user personal OS.

CRITICAL: You are reviewing code written by another AI agent. You have NOT seen the
implementation plan, the author's reasoning, or any chain-of-thought. You are reviewing
the diff on its own merits.

## Constitutional Axioms
{axiom_text}

## Review Focus
1. **Correctness**: Logic errors, off-by-one, missing edge cases, race conditions.
2. **Security**: Hardcoded secrets, injection vectors, unsafe deserialization, path traversal.
3. **Axiom compliance**: Does this change violate any constitutional axiom?
4. **Test coverage**: Are new code paths tested? Are edge cases covered?
5. **Regression risk**: Could this change break existing functionality?

## Rules
- Only report HIGH and MEDIUM severity findings. Ignore LOW/nitpick/style.
- Do NOT comment on formatting or style — Ruff handles that.
- Be specific: reference file paths and line numbers.
- Suggest concrete fixes, not vague advice.
- If the code is clean, say so. Do NOT manufacture findings.
- Include the file path and approximate line number for each finding.

## Output
Return a JSON object with: verdict ("approve" or "request_changes"),
findings (list of {{file, line, severity, description, suggestion}}),
axiom_concerns (list of {{axiom_id, concern, severity}}),
summary (brief overall assessment).
"""


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------


def _call_llm(system: str, user: str, *, dry_run: bool = False) -> ReviewResult:
    if dry_run:
        return ReviewResult(
            verdict="approve",
            findings=[],
            axiom_concerns=[],
            summary="Dry run — no review performed.",
        )

    try:
        import anthropic

        client = anthropic.Anthropic()
        response = client.messages.create(
            model=os.environ.get("SDLC_REVIEW_MODEL", "claude-sonnet-4-6"),
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = response.content[0].text
    except ImportError:
        from pydantic_ai import Agent

        agent = Agent(
            os.environ.get("SDLC_REVIEW_MODEL", "anthropic:claude-sonnet-4-6"),
            system_prompt=system,
            output_type=ReviewResult,
        )
        result = agent.run_sync(user)
        return result.output

    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]
    return ReviewResult.model_validate_json(text.strip())


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run_review(pr_number: int, *, dry_run: bool = False) -> ReviewResult:
    """Review a pull request adversarially."""
    diff = "" if dry_run else fetch_pr_diff(pr_number)
    changed_files = [] if dry_run else fetch_pr_changed_files(pr_number)
    axioms = load_axioms(scope="constitutional")

    system_prompt = _build_system_prompt(axioms)
    user_prompt = f"""\
## Changed Files
{chr(10).join(f"- `{f}`" for f in changed_files)}

## Diff
```diff
{diff[:50000]}
```
"""

    model = os.environ.get("SDLC_REVIEW_MODEL", "claude-sonnet-4-6")
    t0 = time.monotonic()

    trace_id = f"sdlc-review-{pr_number}"
    with TraceContext("review", trace_id, pr_number=pr_number) as span:
        result = _call_llm(system_prompt, user_prompt, dry_run=dry_run)
        span.model = model
        span.output_text = result.model_dump_json()

    duration_ms = int((time.monotonic() - t0) * 1000)

    if not dry_run:
        _post_review_results(pr_number, result)

    try:
        from sdlc.log import log_sdlc_event

        log_sdlc_event(
            "review",
            pr_number=pr_number,
            result={
                "verdict": result.verdict,
                "findings_count": len(result.findings),
                "high_findings": sum(
                    1 for f in result.findings if getattr(f, "severity", "") == "HIGH"
                ),
                "medium_findings": sum(
                    1 for f in result.findings if getattr(f, "severity", "") == "MEDIUM"
                ),
                "axiom_concerns_count": len(result.axiom_concerns),
                "axiom_concerns": [
                    {"axiom_id": c.axiom_id, "severity": c.severity} for c in result.axiom_concerns
                ][:5]
                if result.axiom_concerns
                else [],
            },
            duration_ms=duration_ms,
            model_used=model,
            dry_run=dry_run,
            metadata={"trace_id": f"sdlc-review-{pr_number}"},
        )
    except Exception:
        pass

    try:
        from sdlc.audit import log_audit

        log_audit(
            action="sdlc_review",
            actor="sdlc_pipeline",
            check_name=f"review-pr-{pr_number}",
            outcome=result.verdict,
            pr_number=pr_number,
            duration_ms=duration_ms,
            metadata={"findings_count": len(result.findings)},
        )
    except Exception:
        pass

    return result


def _post_review_results(pr_number: int, result: ReviewResult) -> None:
    """Post review findings as PR comment and set appropriate labels."""
    parts = [f"## 🔍 Adversarial Review\n\n**Verdict:** {result.verdict.upper()}\n"]

    if result.findings:
        parts.append("### Findings\n")
        for f in result.findings:
            loc = f"`{f.file}:{f.line}`" if f.line else f"`{f.file}`"
            parts.append(f"- **{f.severity}** ({loc}): {f.description}")
            if f.suggestion:
                parts.append(f"  - *Suggestion:* {f.suggestion}")

    if result.axiom_concerns:
        parts.append("\n### Axiom Concerns\n")
        for ac in result.axiom_concerns:
            parts.append(f"- **{ac.severity}** [{ac.axiom_id}]: {ac.concern}")

    if result.summary:
        parts.append(f"\n### Summary\n{result.summary}")

    post_pr_comment(pr_number, "\n".join(parts))

    if result.verdict == "request_changes":
        add_pr_labels(pr_number, "changes-requested")


def main() -> None:
    parser = argparse.ArgumentParser(description="SDLC Adversarial Review Agent")
    parser.add_argument("--pr-number", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.dry_run and not is_file_export():
        try:
            from shared import langfuse_config  # noqa: F401
        except ImportError:
            pass

    result = run_review(args.pr_number, dry_run=args.dry_run)
    print(json.dumps(result.model_dump(), indent=2))


if __name__ == "__main__":
    main()
