"""Deontic consistency checker for axiom implications (E-3).

Lightweight alternative to a full ASP solver. With only 4 axioms and ~57
implications, we can check for conflicts directly:

1. Load all implications, classify by mode:
   - compatibility → prohibitions (what the system must NOT do)
   - sufficiency → obligations (what the system MUST do)
2. Check for pairs where an obligation requires something a prohibition forbids.
3. Check for tier conflicts (domain T0 vs constitutional T0).
4. Report findings.

Usage:
    uv run python sdlc/consistency_check.py
    uv run python sdlc/consistency_check.py --verbose
    uv run python sdlc/consistency_check.py --json
    uv run python sdlc/consistency_check.py --json --check-resolutions
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

AXIOMS_PATH = Path(
    os.environ.get("AXIOMS_PATH", str(Path(__file__).resolve().parent.parent / "axioms"))
)

# Known architectural constraints extracted from agent-architecture.md
# These are prohibitions that exist outside the implication YAML.
ARCHITECTURAL_CONSTRAINTS = [
    {
        "id": "arch-no-direct-provider-api",
        "text": "Agents must route through LiteLLM, never direct provider APIs",
        "mode": "compatibility",
        "source": "agent-architecture.md",
    },
    {
        "id": "arch-single-invocation-path",
        "text": "Agents are invoked by Claude Code, CLI, or n8n — not by each other",
        "mode": "compatibility",
        "source": "agent-architecture.md",
    },
    {
        "id": "arch-tier1-is-command-center",
        "text": "Claude Code (Tier 1) is the command center; Tier 2/3 are infrastructure",
        "mode": "compatibility",
        "source": "agent-architecture.md",
    },
]


@dataclass
class Implication:
    id: str
    axiom_id: str
    tier: str
    text: str
    enforcement: str
    mode: str
    level: str
    source: str = "implications"


@dataclass
class Conflict:
    obligation: Implication
    prohibition: Implication
    reason: str
    severity: str  # "error" | "warning"


def load_all_implications() -> list[Implication]:
    """Load all implications from all axiom YAML files."""
    impls: list[Implication] = []
    impl_dir = AXIOMS_PATH / "implications"
    if not impl_dir.exists():
        log.warning("Implications directory not found: %s", impl_dir)
        return impls

    for yaml_file in sorted(impl_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(yaml_file.read_text())
        except Exception as e:
            log.error("Failed to parse %s: %s", yaml_file, e)
            continue

        axiom_id = data.get("axiom_id", yaml_file.stem)
        for entry in data.get("implications", []):
            impls.append(
                Implication(
                    id=entry["id"],
                    axiom_id=axiom_id,
                    tier=entry.get("tier", "T2"),
                    text=entry.get("text", ""),
                    enforcement=entry.get("enforcement", "warn"),
                    mode=entry.get("mode", "compatibility"),
                    level=entry.get("level", "component"),
                )
            )

    # Add architectural constraints as compatibility implications
    for c in ARCHITECTURAL_CONSTRAINTS:
        impls.append(
            Implication(
                id=c["id"],
                axiom_id="architecture",
                tier="T0",
                text=c["text"],
                enforcement="block",
                mode="compatibility",
                level="system",
                source=c["source"],
            )
        )

    return impls


def _extract_action_phrases(text: str) -> set[str]:
    """Extract specific action phrases from implication text.

    Returns normalized 2-3 word action phrases, not generic deontic words.
    """
    import re

    lower = text.lower()
    # Extract verb-object phrases after deontic operators
    phrases = set()
    # "must [not] VERB OBJECT" patterns
    for m in re.finditer(
        r"(?:must|shall|should|need to|required to)\s+(?:not\s+)?([\w]+(?:\s+[\w]+){0,2})",
        lower,
    ):
        phrase = m.group(1).strip()
        # Skip very generic phrases
        if phrase not in ("be", "have", "do", "include", "provide", "use"):
            phrases.add(phrase)
    return phrases


def _text_conflicts(obligation_text: str, prohibition_text: str) -> bool:
    """Check if an obligation and prohibition have a genuine semantic conflict.

    Uses specific action phrase overlap rather than generic keyword matching.
    Only flags when the same concrete action is both required and forbidden.
    """
    import re

    ob_lower = obligation_text.lower()
    pr_lower = prohibition_text.lower()

    # Direct opposition: same action required and forbidden
    ob_actions = _extract_action_phrases(ob_lower)
    pr_actions = _extract_action_phrases(pr_lower)

    # Check for action overlap where one requires and other forbids
    overlap = ob_actions & pr_actions
    if overlap:
        # Verify deontic opposition (obligation requires, prohibition forbids)
        ob_requires = "must" in ob_lower and "must not" not in ob_lower
        pr_forbids = "must not" in pr_lower or "never" in pr_lower or "prohibit" in pr_lower
        if ob_requires and pr_forbids:
            return True

    # Check for specific contradictory patterns
    contradict_patterns = [
        # "agents must invoke" vs "agents must not invoke each other"
        (r"agent.*must\s+invoke", r"agent.*must\s+not\s+invoke"),
        (r"must\s+dispatch", r"must\s+not\s+dispatch"),
        (r"automate.*recurring", r"never\s+automate"),
        (r"require.*multi.?user", r"no\s+multi.?user"),
    ]

    for ob_pat, pr_pat in contradict_patterns:
        if re.search(ob_pat, ob_lower) and re.search(pr_pat, pr_lower):
            return True
        if re.search(pr_pat, ob_lower) and re.search(ob_pat, pr_lower):
            return True

    return False


def check_consistency(implications: list[Implication], *, verbose: bool = False) -> list[Conflict]:
    """Check for deontic conflicts between obligations and prohibitions."""
    obligations = [i for i in implications if i.mode == "sufficiency"]
    prohibitions = [i for i in implications if i.mode == "compatibility"]

    conflicts: list[Conflict] = []

    # Check obligation vs prohibition pairs
    for ob in obligations:
        for pr in prohibitions:
            if _text_conflicts(ob.text, pr.text):
                severity = "error" if ob.tier == "T0" and pr.tier == "T0" else "warning"
                conflicts.append(
                    Conflict(
                        obligation=ob,
                        prohibition=pr,
                        reason=f"Obligation ({ob.id}) may conflict with prohibition ({pr.id})",
                        severity=severity,
                    )
                )

    # Check for tier conflicts within the same axiom
    by_axiom: dict[str, list[Implication]] = {}
    for imp in implications:
        by_axiom.setdefault(imp.axiom_id, []).append(imp)

    for axiom_id, axiom_impls in by_axiom.items():
        t0_blocks = [i for i in axiom_impls if i.tier == "T0" and i.enforcement == "block"]
        for i, a in enumerate(t0_blocks):
            for b in t0_blocks[i + 1 :]:
                if _text_conflicts(a.text, b.text):
                    conflicts.append(
                        Conflict(
                            obligation=a,
                            prohibition=b,
                            reason=f"Intra-axiom T0 conflict in {axiom_id}",
                            severity="error",
                        )
                    )

    return conflicts


def load_resolutions(*, path: Path = AXIOMS_PATH) -> dict[str, dict]:
    """Load contradiction resolutions from precedents YAML.

    Returns a dict keyed by "obligation_id:prohibition_id" pairs.
    """
    resolutions_file = path / "precedents" / "contradiction-resolutions.yaml"
    if not resolutions_file.exists():
        return {}

    try:
        data = yaml.safe_load(resolutions_file.read_text())
    except Exception as e:
        log.warning("Failed to load resolutions: %s", e)
        return {}

    result: dict[str, dict] = {}
    for entry in data.get("resolutions", []):
        key = f"{entry.get('obligation_id', '')}:{entry.get('prohibition_id', '')}"
        result[key] = entry
    return result


def format_results(conflicts: list[Conflict], *, verbose: bool = False) -> str:
    """Format conflict results for human consumption."""
    if not conflicts:
        return "No deontic conflicts detected."

    lines = [f"Found {len(conflicts)} potential conflict(s):\n"]
    errors = [c for c in conflicts if c.severity == "error"]
    warnings = [c for c in conflicts if c.severity == "warning"]

    if errors:
        lines.append(f"ERRORS ({len(errors)}):")
        for c in errors:
            lines.append(f"  [{c.severity.upper()}] {c.reason}")
            lines.append(f"    Obligation: [{c.obligation.id}] {c.obligation.text[:80]}")
            lines.append(f"    Prohibition: [{c.prohibition.id}] {c.prohibition.text[:80]}")
            lines.append("")

    if warnings:
        lines.append(f"WARNINGS ({len(warnings)}):")
        for c in warnings:
            lines.append(f"  [{c.severity.upper()}] {c.reason}")
            if verbose:
                lines.append(f"    Obligation: [{c.obligation.id}] {c.obligation.text[:80]}")
                lines.append(f"    Prohibition: [{c.prohibition.id}] {c.prohibition.text[:80]}")
            lines.append("")

    return "\n".join(lines)


def format_results_json(
    conflicts: list[Conflict],
    implications: list[Implication],
    *,
    check_resolutions: bool = False,
) -> str:
    """Format conflict results as structured JSON for downstream tools.

    Output schema:
        {conflicts: [{obligation_id, prohibition_id, reason, severity, resolved_by_precedent?}],
         summary: {errors, warnings, resolved, total_implications, obligations, prohibitions}}
    """
    resolutions = load_resolutions() if check_resolutions else {}

    conflict_entries = []
    resolved_count = 0
    for c in conflicts:
        key = f"{c.obligation.id}:{c.prohibition.id}"
        resolution = resolutions.get(key)
        entry: dict = {
            "obligation_id": c.obligation.id,
            "prohibition_id": c.prohibition.id,
            "reason": c.reason,
            "severity": c.severity,
        }
        if resolution:
            entry["resolved_by_precedent"] = resolution.get("precedent_id", "")
            entry["resolution_note"] = resolution.get("resolution", "")
            resolved_count += 1
        conflict_entries.append(entry)

    obligations = [i for i in implications if i.mode == "sufficiency"]
    prohibitions = [i for i in implications if i.mode == "compatibility"]

    result = {
        "conflicts": conflict_entries,
        "summary": {
            "errors": len([c for c in conflicts if c.severity == "error"]),
            "warnings": len([c for c in conflicts if c.severity == "warning"]),
            "resolved": resolved_count,
            "total_implications": len(implications),
            "obligations": len(obligations),
            "prohibitions": len(prohibitions),
        },
    }
    return json.dumps(result, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deontic consistency checker for axiom implications"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show full details for warnings"
    )
    parser.add_argument("--json", action="store_true", help="Output structured JSON")
    parser.add_argument(
        "--check-resolutions",
        action="store_true",
        help="Cross-reference conflicts against precedent resolutions",
    )
    args = parser.parse_args()

    implications = load_all_implications()

    if not args.json:
        print(
            f"Loaded {len(implications)} implications"
            f" ({len(ARCHITECTURAL_CONSTRAINTS)} architectural constraints)"
        )
        obligations = [i for i in implications if i.mode == "sufficiency"]
        prohibitions = [i for i in implications if i.mode == "compatibility"]
        print(f"  Obligations (sufficiency): {len(obligations)}")
        print(f"  Prohibitions (compatibility): {len(prohibitions)}")
        print()

    conflicts = check_consistency(implications, verbose=args.verbose)

    if args.json:
        print(
            format_results_json(
                conflicts,
                implications,
                check_resolutions=args.check_resolutions,
            )
        )
    else:
        print(format_results(conflicts, verbose=args.verbose))

    if any(c.severity == "error" for c in conflicts):
        sys.exit(1)


if __name__ == "__main__":
    main()
