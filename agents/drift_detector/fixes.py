"""Fix generation — LLM-powered documentation correction."""

from __future__ import annotations

import logging

from pydantic_ai import Agent

from .context_tools import get_context_tools
from .fix_context import REGISTRY_CATEGORIES, _build_fix_context
from .models import DocFix, DriftItem, DriftReport, FixReport

# Re-export for backward compatibility
REGISTRY_CATEGORIES = REGISTRY_CATEGORIES  # noqa: F811
_build_fix_context = _build_fix_context  # noqa: F811

log = logging.getLogger("drift_detector")


FIX_SYSTEM_PROMPT = """\
You are a documentation editor for a multi-repo infrastructure system. Given a
documentation file and a list of discrepancies (drift items), produce precise
text replacements to fix the documentation so it matches reality.

RULES:
- The "original" field must be an EXACT substring from the document (copy-paste).
- The "corrected" field is the replacement text.
- Only fix items listed in the drift report. Don't rewrite unrelated sections.
- Preserve the document's existing formatting style.
- For missing items, add them to the appropriate existing table or section.
- Keep fixes minimal and precise.

CONTEXT TOOLS:
- Call lookup_constraints("python,docker,git") when writing Conventions sections
- Call lookup_constraints() when scaffolding new documents
- Call lookup_patterns("workflow,development") when writing Project Memory stubs
Do NOT call tools for simple table row additions or heading insertions.

CATEGORY GUIDANCE:
- missing-section: Add heading + substantive stub paragraph.
- coverage-gap: Add item matching existing format. Mark unknowns with "TODO".
- missing-required-doc: Generate complete initial document with all required sections.
- boundary-mismatch: Update to match the more complete/recent version.
- repo-awareness-gap: Add repo to registry table matching existing format.
- spec-reference-gap: Add brief reference in appropriate location.
"""


def _get_fix_model():
    from .config import get_model

    return get_model("fast")


fix_agent = Agent(
    _get_fix_model(),
    system_prompt=FIX_SYSTEM_PROMPT,
    output_type=FixReport,
)

for _fix_tool_fn in get_context_tools():
    fix_agent.tool(_fix_tool_fn)


async def generate_fixes(report: DriftReport, docs: dict[str, str]) -> FixReport:
    """For high/medium drift items, generate corrected doc fragments."""
    actionable = [d for d in report.drift_items if d.severity in ("high", "medium")]
    if not actionable:
        return FixReport(fixes=[], summary="No high/medium severity items to fix.")

    by_file: dict[str, list[DriftItem]] = {}
    for item in actionable:
        by_file.setdefault(item.doc_file, []).append(item)

    all_fixes: list[DocFix] = []

    for doc_path, items in by_file.items():
        doc_content = docs.get(doc_path, "")
        if not doc_content:
            continue

        items_desc = "\n".join(
            f'- [{d.severity}] {d.category}: Doc says "{d.doc_claim}" '
            f'but reality is "{d.reality}". Suggestion: {d.suggestion}'
            for d in items
        )

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
