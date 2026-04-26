#!/usr/bin/env python
"""Compose the velocity-findings preprint as a PreprintArtifact and
write it into the publish-orchestrator inbox.

Per cc-task ``leverage-attrib-arxiv-velocity-preprint`` (WSJF 8.0):
the daemon-tractable arXiv preprint flow is gated on endorser-
courtship, but the underlying Zenodo deposit is not — Zenodo mints
a DOI on publish without editorial review, and the resulting
RelatedIdentifier graph drives the citation-graph touch the
endorser-courtship path needs anyway.

This script:
1. Reads ``docs/research/2026-04-25-velocity-comparison.md`` (the
   shaped-source velocity findings).
2. Composes a :class:`PreprintArtifact` (slug, title, abstract, body,
   surfaces_targeted = ``["zenodo-doi"]``) and marks it APPROVED so
   the orchestrator dispatches it on the next cycle.
3. Writes to ``$HAPAX_STATE/publish/inbox/{slug}.json``.

Idempotent: rewriting the inbox file overwrites; the orchestrator's
dedup-by-DOI handles re-runs.

Usage:
  uv run python scripts/build-velocity-findings-preprint.py
  uv run python scripts/build-velocity-findings-preprint.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from shared.preprint_artifact import INBOX_DIR_NAME, ApprovalState, PreprintArtifact

SOURCE_DOC = REPO_ROOT / "docs" / "research" / "2026-04-25-velocity-comparison.md"

# Slug — URL-safe, stable across re-runs so the inbox file overwrites
# rather than accumulates duplicates. Date suffix lets future
# follow-up preprints (e.g. velocity-findings-2026-Q3) coexist.
SLUG = "velocity-findings-2026-04-25"

TITLE = "Hapax development velocity vs comparable LLM-driven projects"

# Abstract is composed from the source doc's §1 headline observations
# block — the most-condensed factual summary that survives venue-
# neutral framing.
ABSTRACT = (
    "Empirical comparison of single-operator multi-Claude-Code-session "
    "development velocity against documented LLM-driven reference points, "
    "calibrated to an 18-hour observation window of 2026-04-25. The window "
    "produced 30 PRs/day, 137 commits/day across six related repositories, "
    "approximately 33,500 LOC churn/day, 5.9 sustained research drops/day "
    "over 45 days (265 total), 21.8% formalised REFUSED-status work-state "
    "items, and a 47% first-attempt CI pass rate. Coordination across the "
    "four concurrent sessions is mediated by filesystem-as-bus reactive "
    "rules with no coordinator agent and no inter-session message passing. "
    "We frame the comparison set, calibration methodology, and the "
    "reproducibility constraints implied by the livestream-as-research-"
    "instrument substrate."
)


def build_artifact(source_path: Path = SOURCE_DOC) -> PreprintArtifact:
    """Compose the artifact in-memory; pure helper for testing."""
    if not source_path.is_file():
        raise FileNotFoundError(f"Source doc missing: {source_path}")
    body_md = source_path.read_text(encoding="utf-8")

    artifact = PreprintArtifact(
        slug=SLUG,
        title=TITLE,
        abstract=ABSTRACT,
        body_md=body_md,
        surfaces_targeted=["zenodo-doi"],
        approval=ApprovalState.APPROVED,
    )
    return artifact


def _default_state_root() -> Path:
    env = os.environ.get("HAPAX_STATE")
    if env:
        return Path(env)
    return Path.home() / "hapax-state"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compose + validate but do NOT write to inbox.",
    )
    parser.add_argument(
        "--state-root",
        type=Path,
        default=_default_state_root(),
        help="Override $HAPAX_STATE for testing.",
    )
    args = parser.parse_args()

    artifact = build_artifact()
    inbox_path = args.state_root / INBOX_DIR_NAME / f"{artifact.slug}.json"

    if args.dry_run:
        print(f"[dry-run] would write {inbox_path} ({len(artifact.body_md)} body chars)")
        return 0

    inbox_path.parent.mkdir(parents=True, exist_ok=True)
    inbox_path.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
    print(f"wrote {inbox_path} (slug={artifact.slug}, body={len(artifact.body_md)} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
