# shared/axiom_derivation.py
"""One-shot axiom implication derivation pipeline.

Generates concrete implications from axiom text using LLM self-consistency.
Operator-triggered only. Output is reviewed and committed to hapaxromana.

Usage:
    uv run python -m shared.axiom_derivation --axiom single_user
    uv run python -m shared.axiom_derivation --axiom executive_function --output implications.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import yaml

log = logging.getLogger(__name__)


INTERPRETIVE_CANONS = """\
Apply these interpretive strategies (canons of construction):

1. **Textualist**: What does the axiom literally say? Derive implications from its exact words.
2. **Purposivist**: What is the axiom trying to achieve? Derive implications from its intent.
3. **Absurdity doctrine**: Would this interpretation produce results no reasonable person would endorse? If so, discard it.
4. **Omitted-case canon**: Don't add things the axiom doesn't state or reasonably imply.

For each implication, note which canon primarily drove the derivation."""


def build_derivation_prompt(
    axiom_id: str,
    axiom_text: str,
    codebase_context: str,
) -> str:
    """Build the LLM prompt for axiom decomposition."""
    return f"""\
You are deriving concrete, enforceable implications from a system axiom.

## Axiom: {axiom_id}

{axiom_text.strip()}

## Codebase Context

{codebase_context}

## Interpretive Framework

{INTERPRETIVE_CANONS}

## Instructions

Derive concrete implications of this axiom for the current codebase.
For each implication, assign:
- **id**: short identifier (format: {axiom_id[:2]}-category-NNN, e.g., su-arch-001)
- **tier**: T0 (existential — blocks work), T1 (significant — requires review),
  T2 (minor — automated warning), T3 (cosmetic — lint only)
- **text**: one-sentence concrete implication
- **enforcement**: block, review, warn, or lint
- **canon**: which interpretive canon primarily drove this derivation

Output as a YAML block:
```yaml
implications:
  - id: ...
    tier: ...
    text: ...
    enforcement: ...
    canon: ...
```

Focus on implications that are:
1. Concrete enough to check mechanically or through LLM review
2. Relevant to the current codebase (not hypothetical)
3. Non-obvious (don't restate the axiom itself)
"""


def parse_implications_output(text: str) -> list[dict]:
    """Parse YAML implications from LLM output."""
    match = re.search(r"```(?:yaml)?\s*\n(.*?)```", text, re.DOTALL)
    if not match:
        try:
            data = yaml.safe_load(text)
            if isinstance(data, dict) and "implications" in data:
                return data["implications"]
        except Exception:
            pass
        return []

    try:
        data = yaml.safe_load(match.group(1))
    except Exception as e:
        log.error("Failed to parse YAML from LLM output: %s", e)
        return []

    if isinstance(data, dict) and "implications" in data:
        return data["implications"]
    return []


def merge_self_consistent(runs: list[list[dict]]) -> list[dict]:
    """Merge multiple derivation runs using majority vote.

    Implications with the same ID across runs are merged — the majority
    tier/enforcement wins. Implications appearing in only one run are
    kept only if they appear in at least ceil(N/2) runs.
    """
    if not runs:
        return []
    if len(runs) == 1:
        return runs[0]

    # Group by implication ID
    by_id: dict[str, list[dict]] = {}
    for run in runs:
        for impl in run:
            impl_id = impl.get("id", "")
            if impl_id:
                by_id.setdefault(impl_id, []).append(impl)

    threshold = max(1, len(runs) // 2)  # Majority: appears in > half of runs
    merged = []
    for _impl_id, versions in by_id.items():
        if len(versions) < threshold:
            continue

        tiers = Counter(v.get("tier", "T2") for v in versions)
        enforcements = Counter(v.get("enforcement", "warn") for v in versions)

        base = versions[0].copy()
        base["tier"] = tiers.most_common(1)[0][0]
        base["enforcement"] = enforcements.most_common(1)[0][0]
        merged.append(base)

    return merged


async def derive_implications(
    axiom_id: str,
    *,
    n: int = 3,
    output_path: Path | None = None,
) -> list[dict]:
    """Run the full derivation pipeline with self-consistency."""
    from shared.axiom_registry import get_axiom
    from shared.config import get_model

    axiom = get_axiom(axiom_id)
    if not axiom:
        log.error("Axiom '%s' not found in registry", axiom_id)
        return []

    # Gather codebase context
    import subprocess

    from shared.config import AI_AGENTS_DIR

    result = subprocess.run(
        [
            "find",
            str(AI_AGENTS_DIR),
            "-name",
            "*.py",
            "-path",
            "*/agents/*",
            "-o",
            "-name",
            "*.py",
            "-path",
            "*/shared/*",
        ],
        capture_output=True,
        text=True,
    )
    file_tree = result.stdout.strip() if result.returncode == 0 else "File tree unavailable"

    prompt = build_derivation_prompt(axiom_id, axiom.text, file_tree)

    # Run N derivations
    from pydantic_ai import Agent

    agent = Agent(get_model("balanced"))

    runs = []
    for i in range(n):
        log.info("Derivation run %d/%d for axiom '%s'", i + 1, n, axiom_id)
        run_result = await agent.run(prompt)
        impls = parse_implications_output(run_result.output)
        runs.append(impls)
        log.info("  Run %d produced %d implications", i + 1, len(impls))

    # Merge with self-consistency
    merged = merge_self_consistent(runs)
    log.info("Merged: %d implications after self-consistency", len(merged))

    # Output
    output = {
        "axiom_id": axiom_id,
        "derived_at": datetime.now(UTC).isoformat()[:10],
        "model": "balanced",
        "derivation_version": 1,
        "implications": merged,
    }

    if output_path:
        output_path.write_text(yaml.dump(output, default_flow_style=False, sort_keys=False))
        log.info("Written to %s", output_path)
    else:
        print(yaml.dump(output, default_flow_style=False, sort_keys=False))

    return merged


async def _main():
    parser = argparse.ArgumentParser(description="Derive axiom implications")
    parser.add_argument("--axiom", required=True, help="Axiom ID to derive implications for")
    parser.add_argument("--n", type=int, default=3, help="Number of self-consistency runs")
    parser.add_argument("--output", type=Path, help="Output YAML file path")
    args = parser.parse_args()

    from shared.log_setup import configure_logging

    configure_logging(agent="axiom-derivation")
    await derive_implications(args.axiom, n=args.n, output_path=args.output)


if __name__ == "__main__":
    asyncio.run(_main())
