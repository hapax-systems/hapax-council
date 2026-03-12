#!/usr/bin/env python3
"""SDLC Axiom Compliance Judge.

Two-tier compliance gate: structural (deterministic) + semantic (LLM judge).
Runs after review approval, before human merge decision.

Usage::

    uv run python -m scripts.sdlc_axiom_judge --pr-number 10
    uv run python -m scripts.sdlc_axiom_judge --pr-number 10 --dry-run
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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.axiom_enforcement import check_full
from shared.axiom_registry import load_axioms, load_implications
from shared.langfuse_trace_export import TraceContext, is_file_export
from shared.sdlc_github import (
    add_pr_labels,
    fetch_pr,
    fetch_pr_changed_files,
    fetch_pr_diff,
    post_pr_comment,
)

# ---------------------------------------------------------------------------
# Structured output
# ---------------------------------------------------------------------------

PROTECTED_PATHS = [
    r"^agents/health_monitor\.py$",
    r"^shared/alert_state\.py$",
    r"^shared/axiom_enforcement\.py$",
    r"^shared/axiom_registry\.py$",
    r"^shared/axiom_tools\.py$",
    r"^shared/config\.py$",
    r"^axioms/",
    r"^hooks/",
    r"^systemd/",
    r"^hapax-backup-.*\.sh$",
    r"^\.github/",
]

# Conventional commit pattern.
COMMIT_MSG_RE = re.compile(
    r"^(feat|fix|docs|style|refactor|perf|test|chore|ci|build|revert)"
    r"(\(.+?\))?!?:\s.+"
)

# Max diff lines by complexity.
DIFF_LIMITS = {"S": 500, "M": 1500, "L": 5000}


class StructuralResult(BaseModel):
    passed: bool
    violations: list[str] = []


class SemanticVerdict(BaseModel):
    axiom_id: str
    compliant: bool
    tier_violated: str | None = None
    reasoning: str = ""


class AxiomGateResult(BaseModel):
    structural: StructuralResult
    semantic: list[SemanticVerdict] = []
    precedent_compliant: bool = True
    precedent_violations: list[str] = []
    overall: Literal["pass", "block", "advisory"]
    summary: str = ""


# ---------------------------------------------------------------------------
# Structural checks (deterministic, no LLM)
# ---------------------------------------------------------------------------


def _check_structural(
    changed_files: list[str],
    diff: str,
    pr_title: str,
    complexity: str = "M",
) -> StructuralResult:
    violations = []

    # Protected path check.
    for fpath in changed_files:
        for pattern in PROTECTED_PATHS:
            if re.match(pattern, fpath):
                violations.append(f"Protected path modified: {fpath}")
                break

    # Diff size check.
    diff_lines = len(diff.splitlines())
    limit = DIFF_LIMITS.get(complexity, 1500)
    if diff_lines > limit:
        violations.append(
            f"Diff size ({diff_lines} lines) exceeds {complexity} limit ({limit})"
        )

    # Commit message format (check PR title as proxy).
    if not COMMIT_MSG_RE.match(pr_title) and not pr_title.startswith("[agent]"):
        violations.append(f"PR title doesn't follow conventional commits: {pr_title}")

    return StructuralResult(passed=len(violations) == 0, violations=violations)


# ---------------------------------------------------------------------------
# Semantic checks (LLM judge)
# ---------------------------------------------------------------------------


def _build_judge_prompt(axioms: list, implications_by_axiom: dict) -> str:
    sections = []
    for axiom in axioms:
        impls = implications_by_axiom.get(axiom.id, [])
        impl_text = "\n".join(
            f"  - [{i.tier}] {i.text}" for i in impls[:5]
        )
        sections.append(
            f"### Axiom: {axiom.id}\n{axiom.text.strip()}\n\n"
            f"Key implications:\n{impl_text}"
        )

    return f"""\
You are the axiom compliance judge for hapax-council.

Evaluate whether a code change complies with each constitutional axiom.
Be strict on T0 (block-level) implications, lenient on T2/T3.

## Axioms and Implications

{chr(10).join(sections)}

## Instructions
For each axiom, determine:
1. Is the change compliant?
2. If not, what tier is violated? (T0 = hard block, T1 = needs review, T2/T3 = advisory)
3. Brief reasoning (1-2 sentences).

Return a JSON array of objects: [{{axiom_id, compliant, tier_violated, reasoning}}, ...]
"""


def _call_judge(system: str, diff: str, *, dry_run: bool = False) -> list[SemanticVerdict]:
    if dry_run:
        return [
            SemanticVerdict(axiom_id="single_user", compliant=True, reasoning="Dry run."),
        ]

    user_prompt = f"## Code Diff\n```diff\n{diff[:30000]}\n```"

    try:
        import anthropic

        client = anthropic.Anthropic()
        response = client.messages.create(
            model=os.environ.get("SDLC_JUDGE_MODEL", "claude-haiku-4-5-20251001"),
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = response.content[0].text
    except ImportError:
        from pydantic_ai import Agent

        agent = Agent(
            os.environ.get("SDLC_JUDGE_MODEL", "anthropic:claude-haiku-4-5-20251001"),
            system_prompt=system,
            output_type=list[SemanticVerdict],
        )
        result = agent.run_sync(user_prompt)
        return result.output

    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]

    raw = json.loads(text.strip())
    return [SemanticVerdict.model_validate(v) for v in raw]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _detect_complexity(pr_labels: list[str]) -> str:
    for lb in pr_labels:
        if lb.startswith("complexity:"):
            return lb.split(":")[1]
    return "M"


def run_axiom_gate(pr_number: int, *, dry_run: bool = False) -> AxiomGateResult:
    """Run full axiom compliance gate on a PR."""
    pr = fetch_pr(pr_number) if not dry_run else None
    diff = fetch_pr_diff(pr_number) if not dry_run else ""
    changed_files = fetch_pr_changed_files(pr_number) if not dry_run else []
    pr_title = pr.title if pr else "[agent] dry run"
    complexity = _detect_complexity(pr.labels if pr else [])

    axioms = load_axioms(scope="constitutional")

    model = os.environ.get("SDLC_JUDGE_MODEL", "claude-haiku-4-5-20251001")
    t0 = time.monotonic()

    # 1. Structural checks.
    structural = _check_structural(changed_files, diff, pr_title, complexity)

    # 2. Semantic checks (LLM judge).
    implications_by_axiom = {}
    for axiom in axioms:
        implications_by_axiom[axiom.id] = load_implications(axiom.id)

    judge_prompt = _build_judge_prompt(axioms, implications_by_axiom)

    trace_id = f"sdlc-axiom-gate-{pr_number}"
    with TraceContext("axiom-gate", trace_id, pr_number=pr_number) as span:
        semantic = _call_judge(judge_prompt, diff, dry_run=dry_run)
        span.model = model
        span.output_text = json.dumps([v.model_dump() for v in semantic])

    # 3. Precedent check via existing enforcement module.
    precedent_violations = []
    precedent_compliant = True
    if not dry_run:
        try:
            pr_summary = f"PR #{pr_number}: {pr_title}"
            cr = check_full(pr_summary)
            if not cr.compliant:
                precedent_compliant = False
                precedent_violations = list(cr.violations)
        except Exception:
            pass  # Precedent store may not be available.

    # 4. Determine overall result.
    has_t0_violation = any(
        not v.compliant and v.tier_violated == "T0" for v in semantic
    )
    has_structural_failure = not structural.passed
    has_advisory = any(
        not v.compliant and v.tier_violated != "T0" for v in semantic
    )

    if has_t0_violation or has_structural_failure:
        overall: Literal["pass", "block", "advisory"] = "block"
    elif has_advisory or not precedent_compliant:
        overall = "advisory"
    else:
        overall = "pass"

    result = AxiomGateResult(
        structural=structural,
        semantic=semantic,
        precedent_compliant=precedent_compliant,
        precedent_violations=precedent_violations,
        overall=overall,
        summary=_build_summary(structural, semantic, precedent_violations, overall),
    )

    duration_ms = int((time.monotonic() - t0) * 1000)

    try:
        from shared.sdlc_log import log_sdlc_event
        log_sdlc_event(
            "axiom-gate",
            pr_number=pr_number,
            result={"overall": result.overall, "structural_passed": result.structural.passed},
            duration_ms=duration_ms,
            model_used=model,
            dry_run=dry_run,
        )
    except Exception:
        pass

    if not dry_run:
        _post_gate_results(pr_number, result)

    return result


def _build_summary(
    structural: StructuralResult,
    semantic: list[SemanticVerdict],
    precedent_violations: list[str],
    overall: str,
) -> str:
    parts = []
    if not structural.passed:
        parts.append(f"Structural: {len(structural.violations)} violation(s)")
    t0_count = sum(1 for v in semantic if not v.compliant and v.tier_violated == "T0")
    advisory_count = sum(1 for v in semantic if not v.compliant and v.tier_violated != "T0")
    if t0_count:
        parts.append(f"T0 violations: {t0_count}")
    if advisory_count:
        parts.append(f"Advisory findings: {advisory_count}")
    if precedent_violations:
        parts.append(f"Precedent violations: {len(precedent_violations)}")
    if not parts:
        parts.append("All checks passed")
    return f"Overall: {overall.upper()}. " + ". ".join(parts) + "."


def _post_gate_results(pr_number: int, result: AxiomGateResult) -> None:
    """Post axiom gate results as PR comment."""
    icon = {"pass": "✅", "block": "🚫", "advisory": "⚠️"}[result.overall]
    parts = [f"## {icon} Axiom Compliance Gate\n\n**Result:** {result.overall.upper()}\n"]

    if result.structural.violations:
        parts.append("### Structural Violations")
        for v in result.structural.violations:
            parts.append(f"- {v}")

    blocking = [v for v in result.semantic if not v.compliant and v.tier_violated == "T0"]
    advisory = [v for v in result.semantic if not v.compliant and v.tier_violated != "T0"]

    if blocking:
        parts.append("\n### T0 Violations (Blocking)")
        for v in blocking:
            parts.append(f"- **{v.axiom_id}**: {v.reasoning}")

    if advisory:
        parts.append("\n### Advisory Findings")
        for v in advisory:
            parts.append(f"- **{v.axiom_id}** [{v.tier_violated}]: {v.reasoning}")

    if result.precedent_violations:
        parts.append("\n### Precedent Violations")
        for v in result.precedent_violations:
            parts.append(f"- {v}")

    parts.append(f"\n{result.summary}")

    post_pr_comment(pr_number, "\n".join(parts))

    if result.overall == "block":
        add_pr_labels(pr_number, "axiom:blocked")
    elif result.overall == "advisory":
        add_pr_labels(pr_number, "axiom:precedent-review")
    else:
        add_pr_labels(pr_number, "sdlc:ready-for-human")


def main() -> None:
    parser = argparse.ArgumentParser(description="SDLC Axiom Compliance Judge")
    parser.add_argument("--pr-number", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.dry_run and not is_file_export():
        try:
            from shared import langfuse_config  # noqa: F401
        except ImportError:
            pass

    result = run_axiom_gate(args.pr_number, dry_run=args.dry_run)
    print(json.dumps(result.model_dump(), indent=2))


if __name__ == "__main__":
    main()
