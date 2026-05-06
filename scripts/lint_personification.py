#!/usr/bin/env python3
"""CI gate — anti-personification linter sweep over high-signal surfaces.

Task #155 Stage 5: enforce fail-loud on the narrow set of files that feed
LLM prompt surfaces (voice pipeline + director loop), the persona module
that backs them, the content-prep segment prompt surfaces, the canonical
axiom documents, and prompt modules under ``agents/``.

Exits non-zero when any deny-list finding survives the carve-out windows.

Usage:
    uv run python scripts/lint_personification.py [--json]

Design notes:

- Reads files through ``shared.anti_personification_linter.lint_path``
  in **warn** mode (we want the full finding list, not early-abort).
  The script translates aggregated findings into the non-zero exit.
- Target globs mirror the surfaces that route through
  ``compose_persona_prompt`` or embed deny-list-adjacent language — adding
  a new prompt module means adding a glob line, not a new gate.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from shared.anti_personification_linter import Finding, lint_path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Globs scanned by the CI gate. Order is stable for deterministic output.
_TARGET_GLOBS: tuple[str, ...] = (
    "axioms/**/*.md",
    "agents/hapax_daimonion/persona.py",
    "agents/hapax_daimonion/conversation_pipeline.py",
    "agents/hapax_daimonion/conversational_policy.py",
    "agents/studio_compositor/director_loop.py",
    "agents/**/prompts/*.py",
    "agents/**/prompts/*.md",
    "agents/hapax_daimonion/autonomous_narrative/segment_prompts.py",
    "agents/hapax_daimonion/daily_segment_prep.py",
    "shared/segment_quality_actionability.py",
    "shared/segment_iteration_review.py",
)


def _collect_paths() -> list[Path]:
    seen: set[Path] = set()
    ordered: list[Path] = []
    for pattern in _TARGET_GLOBS:
        for p in sorted(REPO_ROOT.glob(pattern)):
            if p.is_file() and p not in seen:
                seen.add(p)
                ordered.append(p)
    return ordered


def _render_text(findings: list[Finding]) -> str:
    if not findings:
        return "anti-personification: clean (0 findings across target surfaces)\n"
    lines = [f"anti-personification: {len(findings)} finding(s)"]
    for f in findings:
        lines.append(f"  {f.file_path}:{f.line}:{f.col} [{f.rule_id}] {f.matched_text!r}")
    return "\n".join(lines) + "\n"


def _render_json(findings: list[Finding]) -> str:
    return json.dumps(
        {
            "count": len(findings),
            "findings": [
                {
                    "file_path": f.file_path,
                    "line": f.line,
                    "col": f.col,
                    "rule_id": f.rule_id,
                    "matched_text": f.matched_text,
                    "severity": f.severity,
                }
                for f in findings
            ],
        },
        indent=2,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()

    all_findings: list[Finding] = []
    for path in _collect_paths():
        all_findings.extend(lint_path(path, lint_mode="warn"))

    out = _render_json(all_findings) if args.json else _render_text(all_findings)
    sys.stdout.write(out)
    return 1 if all_findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
