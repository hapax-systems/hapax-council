"""CRAFT claim pipeline — extract, score, and populate assertions.

Extracts epistemic and bridge claims from the research corpus,
scores them with the CRAFT 6-dimension model, and upserts scored
claims to the Qdrant assertions collection.

Run: uv run python -m agents.craft_claim_pipeline [--scope docs/research/]
"""

from __future__ import annotations

import argparse
import json
import logging
import uuid
from pathlib import Path

log = logging.getLogger(__name__)


def run_pipeline(
    scopes: list[Path],
    *,
    chi_centrality: int = 3,
    dry_run: bool = False,
) -> dict[str, int]:
    from agents.deliberative_council.modes.audit import discover_artifacts, extract_claims
    from agents.deliberative_council.modes.craft_scorer import (
        ScoredClaim,
        TriageCategory,
        score_claim,
    )

    all_scored: list[ScoredClaim] = []
    for scope in scopes:
        artifacts = discover_artifacts(scope)
        log.info("Scope %s: %d artifacts", scope, len(artifacts))
        for artifact in artifacts:
            claims = extract_claims(artifact)
            for claim in claims:
                scored = score_claim(
                    source_path=claim.source_path,
                    line_number=claim.line_number,
                    text=claim.text,
                    verb=claim.verb,
                    claim_category=claim.category,
                    chi_centrality=chi_centrality,
                )
                all_scored.append(scored)

    all_scored.sort(key=lambda s: s.craft.composite, reverse=True)

    cats = {t: 0 for t in TriageCategory}
    for s in all_scored:
        cats[s.craft.category] += 1

    log.info(
        "Extracted %d claims: A=%d B=%d C=%d D=%d",
        len(all_scored),
        cats[TriageCategory.A],
        cats[TriageCategory.B],
        cats[TriageCategory.C],
        cats[TriageCategory.D],
    )

    if not dry_run and all_scored:
        _populate_assertions(all_scored)

    return {
        "total": len(all_scored),
        "category_a": cats[TriageCategory.A],
        "category_b": cats[TriageCategory.B],
        "category_c": cats[TriageCategory.C],
        "category_d": cats[TriageCategory.D],
    }


def _populate_assertions(scored: list) -> None:
    """Upsert scored claims to Qdrant assertions collection."""
    from qdrant_client.models import PointStruct

    from shared.config import get_qdrant

    client = get_qdrant()
    points = []
    for s in scored:
        pid = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"claim:{s.source_path}:{s.line_number}:{s.text[:50]}",
            )
        )
        points.append(
            PointStruct(
                id=pid,
                vector=[0.0] * 768,
                payload={
                    "source_type": "claim",
                    "source_path": s.source_path,
                    "line_number": s.line_number,
                    "text": s.text,
                    "verb": s.verb,
                    "claim_category": s.claim_category,
                    "craft_composite": s.craft.composite,
                    "craft_category": s.craft.category,
                    "craft_chi_centrality": s.craft.chi_centrality,
                    "craft_domain_distance": s.craft.domain_distance,
                    "craft_falsifiability_risk": s.craft.falsifiability_risk,
                    "craft_ai_provenance": s.craft.ai_provenance,
                    "craft_dependency_depth": s.craft.dependency_depth,
                    "craft_verification_status": s.craft.verification_status,
                    "grounding_status": "unexamined",
                },
            )
        )

    if points:
        for i in range(0, len(points), 100):
            client.upsert("assertions", points[i : i + 100], wait=True)
        log.info("Upserted %d claim assertions to Qdrant", len(points))


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--scope",
        type=Path,
        action="append",
        default=[],
        help="Directory or file to scan (repeatable)",
    )
    p.add_argument("--chi-centrality", type=int, default=3)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    scopes = args.scope or [
        Path("docs/research"),
        Path("docs/superpowers/specs"),
        Path.home() / "projects" / "hapax-research",
    ]

    result = run_pipeline(scopes, chi_centrality=args.chi_centrality, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
