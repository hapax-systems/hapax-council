"""Assertion normalization, deduplication, and entailment detection.

Phase 3 of the Unb-AIRy discursive plane. Takes raw assertions from
extractors (Phase 1/2) and produces a deduplicated, normalized corpus
with entailment relationships marked via supersession links.

Pipeline: normalize text → embed → cosine similarity → NLI entailment → merge.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from shared.assertion_model import Assertion, ProvenanceRecord

log = logging.getLogger(__name__)

# ── Text Normalization ─────────────────────────────��─────────────────────────

_MULTI_SPACE = re.compile(r"\s+")
_TRAILING_PUNCT = re.compile(r"[.;,]+$")
_BULLET_PREFIX = re.compile(r"^[-*•]\s+")


def normalize_text(text: str) -> str:
    """Canonicalize assertion text for comparison."""
    t = text.strip()
    t = _BULLET_PREFIX.sub("", t)
    t = _MULTI_SPACE.sub(" ", t)
    t = t.lower()
    t = t.replace("‘", "'").replace("’", "'")
    t = t.replace("“", '"').replace("”", '"')
    t = t.replace("—", "--").replace("–", "-")
    t = _TRAILING_PUNCT.sub("", t)
    return t


def normalize_assertion(assertion: Assertion) -> Assertion:
    """Return a copy with normalized text. Does not recompute assertion_id."""
    normalized = normalize_text(assertion.text)
    if normalized == assertion.text:
        return assertion
    return assertion.model_copy(update={"text": normalized})


# ── Cosine Similarity ────────────────────────────────────────────────────────


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


# ── Duplicate Detection ───────────────────��──────────────────────────────────

DEDUP_COSINE_THRESHOLD = 0.85


@dataclass
class DuplicateGroup:
    """A group of assertions that are semantically equivalent."""

    canonical: int
    duplicates: list[int] = field(default_factory=list)
    similarities: list[float] = field(default_factory=list)


def find_duplicate_groups(
    assertions: list[Assertion],
    embeddings: list[list[float]],
    *,
    threshold: float = DEDUP_COSINE_THRESHOLD,
) -> list[DuplicateGroup]:
    """Identify groups of semantically duplicate assertions via greedy clustering.

    Args:
        assertions: List of assertions (parallel with embeddings).
        embeddings: Pre-computed embedding vectors (same length as assertions).
        threshold: Cosine similarity threshold for duplicate detection.

    Returns:
        List of DuplicateGroup, each containing indices into the input list.
    """
    if len(assertions) != len(embeddings):
        raise ValueError("assertions and embeddings must have same length")

    groups: list[DuplicateGroup] = []
    assigned: set[int] = set()

    for i in range(len(assertions)):
        if i in assigned:
            continue

        group = DuplicateGroup(canonical=i)
        assigned.add(i)

        for j in range(i + 1, len(assertions)):
            if j in assigned:
                continue
            sim = cosine_similarity(embeddings[i], embeddings[j])
            if sim >= threshold:
                group.duplicates.append(j)
                group.similarities.append(sim)
                assigned.add(j)

        if group.duplicates:
            groups.append(group)

    return groups


# ── NLI Entailment Detection ─────────────────────────────────────────────────


@dataclass
class EntailmentResult:
    """Result of NLI classification between two assertions."""

    premise_idx: int
    hypothesis_idx: int
    label: str  # "entailment", "contradiction", "neutral"
    confidence: float


NLI_PROMPT_TEMPLATE = """Classify the logical relationship between these two assertions.

Premise: {premise}
Hypothesis: {hypothesis}

Respond with exactly one of:
- entailment (the premise logically implies the hypothesis)
- contradiction (the premise contradicts the hypothesis)
- neutral (no clear logical relationship)

Then a confidence score 0.0-1.0.

Format: <label> <confidence>"""


def parse_nli_response(response: str) -> tuple[str, float]:
    """Parse LLM NLI response into label and confidence."""
    text = response.strip().lower()
    for label in ("entailment", "contradiction", "neutral"):
        if label in text:
            parts = text.split()
            confidence = 0.5
            for part in parts:
                try:
                    val = float(part)
                    if 0.0 <= val <= 1.0:
                        confidence = val
                        break
                except ValueError:
                    continue
            return label, confidence
    return "neutral", 0.5


async def classify_entailment_batch(
    pairs: list[tuple[str, str]],
    *,
    model_alias: str = "extraction",
) -> list[tuple[str, float]]:
    """Classify entailment for multiple premise-hypothesis pairs via LLM.

    Uses the 'extraction' model route (cheapest suitable LLM) for NLI.
    """
    import httpx

    from shared.config import LITELLM_BASE, LITELLM_KEY

    results: list[tuple[str, float]] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for premise, hypothesis in pairs:
            prompt = NLI_PROMPT_TEMPLATE.format(premise=premise, hypothesis=hypothesis)
            try:
                resp = await client.post(
                    f"{LITELLM_BASE}/chat/completions",
                    headers={"Authorization": f"Bearer {LITELLM_KEY}"},
                    json={
                        "model": model_alias,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 20,
                        "temperature": 0.0,
                    },
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                results.append(parse_nli_response(content))
            except (httpx.HTTPError, KeyError, IndexError):
                log.warning("NLI call failed for pair, defaulting to neutral")
                results.append(("neutral", 0.5))

    return results


def find_entailment_candidates(
    assertions: list[Assertion],
    embeddings: list[list[float]],
    *,
    similarity_floor: float = 0.70,
    similarity_ceiling: float = DEDUP_COSINE_THRESHOLD,
) -> list[tuple[int, int]]:
    """Find assertion pairs similar but not duplicates — candidates for entailment.

    Pairs with similarity >= ceiling are duplicates (handled by dedup).
    Pairs with similarity in [floor, ceiling) may have entailment relationships.
    """
    candidates: list[tuple[int, int]] = []
    n = len(assertions)
    for i in range(n):
        for j in range(i + 1, n):
            sim = cosine_similarity(embeddings[i], embeddings[j])
            if similarity_floor <= sim < similarity_ceiling:
                candidates.append((i, j))
    return candidates


async def detect_entailments(
    assertions: list[Assertion],
    embeddings: list[list[float]],
    *,
    similarity_floor: float = 0.70,
    model_alias: str = "extraction",
) -> list[EntailmentResult]:
    """Run NLI on candidate pairs to detect entailment/contradiction.

    Returns EntailmentResult for each pair where the relationship is
    non-neutral with confidence >= 0.6.
    """
    candidates = find_entailment_candidates(
        assertions, embeddings, similarity_floor=similarity_floor
    )
    if not candidates:
        return []

    pairs = [(assertions[i].text, assertions[j].text) for i, j in candidates]
    raw_results = await classify_entailment_batch(pairs, model_alias=model_alias)

    results: list[EntailmentResult] = []
    for (i, j), (label, confidence) in zip(candidates, raw_results, strict=True):
        if label != "neutral" and confidence >= 0.6:
            results.append(
                EntailmentResult(
                    premise_idx=i,
                    hypothesis_idx=j,
                    label=label,
                    confidence=confidence,
                )
            )
    return results


# ── Merge Strategy ─────────────────────────��─────────────────────────���───────


def merge_duplicates(
    assertions: list[Assertion],
    groups: list[DuplicateGroup],
) -> list[Assertion]:
    """Merge duplicate groups: keep highest-confidence, mark others superseded.

    Returns the full list with supersession links set. Non-grouped assertions
    are returned unchanged.
    """
    result = [a.model_copy() for a in assertions]

    for group in groups:
        all_indices = [group.canonical] + group.duplicates
        best_idx = max(all_indices, key=lambda i: result[i].confidence)
        best_id = result[best_idx].assertion_id

        for idx in all_indices:
            if idx == best_idx:
                continue
            result[idx] = result[idx].model_copy(
                update={
                    "superseded_by": best_id,
                    "provenance": ProvenanceRecord(
                        source_commit=result[idx].provenance.source_commit,
                        extraction_method=result[idx].provenance.extraction_method,
                        extracted_at=result[idx].provenance.extracted_at,
                        extraction_version=result[idx].provenance.extraction_version,
                        modification_history=[
                            *result[idx].provenance.modification_history,
                            {
                                "action": "superseded_by_dedup",
                                "canonical_id": best_id,
                                "timestamp": datetime.now(UTC).isoformat(),
                            },
                        ],
                    ),
                }
            )

    return result


def apply_entailments(
    assertions: list[Assertion],
    entailments: list[EntailmentResult],
) -> list[Assertion]:
    """Apply entailment results: if A entails B, mark B as superseded by A.

    For contradictions, adds a tag but does not supersede (contradictions
    are valuable to surface, not suppress).
    """
    result = [a.model_copy() for a in assertions]

    for ent in entailments:
        if ent.label == "entailment":
            premise_id = result[ent.premise_idx].assertion_id
            hyp = result[ent.hypothesis_idx]
            if hyp.superseded_by is None:
                result[ent.hypothesis_idx] = hyp.model_copy(
                    update={
                        "superseded_by": premise_id,
                        "provenance": ProvenanceRecord(
                            source_commit=hyp.provenance.source_commit,
                            extraction_method=hyp.provenance.extraction_method,
                            extracted_at=hyp.provenance.extracted_at,
                            extraction_version=hyp.provenance.extraction_version,
                            modification_history=[
                                *hyp.provenance.modification_history,
                                {
                                    "action": "superseded_by_entailment",
                                    "premise_id": premise_id,
                                    "confidence": ent.confidence,
                                    "timestamp": datetime.now(UTC).isoformat(),
                                },
                            ],
                        ),
                    }
                )
        elif ent.label == "contradiction":
            contra_id = result[ent.premise_idx].assertion_id
            hyp = result[ent.hypothesis_idx]
            new_tags = [*hyp.tags, f"contradicts:{contra_id}"]
            result[ent.hypothesis_idx] = hyp.model_copy(update={"tags": new_tags})

            prem = result[ent.premise_idx]
            prem_tags = [*prem.tags, f"contradicts:{hyp.assertion_id}"]
            result[ent.premise_idx] = prem.model_copy(update={"tags": prem_tags})

    return result


# ── Full Pipeline ────────────────────────────────────────────────────���───────


@dataclass
class NormalizationResult:
    """Output of the full normalization pipeline."""

    assertions: list[Assertion]
    duplicate_groups: list[DuplicateGroup]
    entailments: list[EntailmentResult]
    total_input: int
    total_superseded: int


async def run_normalization_pipeline(
    assertions: list[Assertion],
    embeddings: list[list[float]],
    *,
    dedup_threshold: float = DEDUP_COSINE_THRESHOLD,
    entailment_floor: float = 0.70,
    model_alias: str = "extraction",
    skip_nli: bool = False,
) -> NormalizationResult:
    """Run the full normalization pipeline on a set of assertions.

    Steps:
    1. Normalize assertion text
    2. Find duplicate groups via cosine similarity
    3. Merge duplicates (keep highest confidence)
    4. Detect entailment relationships via NLI (unless skip_nli=True)
    5. Apply entailment supersession
    """
    normalized = [normalize_assertion(a) for a in assertions]

    groups = find_duplicate_groups(normalized, embeddings, threshold=dedup_threshold)
    merged = merge_duplicates(normalized, groups)

    entailments: list[EntailmentResult] = []
    if not skip_nli:
        entailments = await detect_entailments(
            merged,
            embeddings,
            similarity_floor=entailment_floor,
            model_alias=model_alias,
        )
        merged = apply_entailments(merged, entailments)

    total_superseded = sum(1 for a in merged if a.superseded_by is not None)

    return NormalizationResult(
        assertions=merged,
        duplicate_groups=groups,
        entailments=entailments,
        total_input=len(assertions),
        total_superseded=total_superseded,
    )


# ── CLI Entry Point ──────────────────────────────────────────────────────────


def _cli_main(argv: list[str] | None = None) -> int:
    """Run assertion normalization pass over extracted assertions."""
    import argparse
    import asyncio
    import json
    import sys
    from pathlib import Path

    parser = argparse.ArgumentParser(
        description="Normalize and deduplicate extracted assertions.",
    )
    parser.add_argument(
        "input",
        type=Path,
        help="JSON file containing extracted assertions (list of Assertion dicts).",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output JSON file (default: stdout).",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEDUP_COSINE_THRESHOLD,
        help=f"Cosine similarity threshold for dedup (default: {DEDUP_COSINE_THRESHOLD}).",
    )
    parser.add_argument(
        "--skip-nli",
        action="store_true",
        help="Skip NLI entailment detection (faster, dedup-only mode).",
    )
    parser.add_argument(
        "--skip-embed",
        action="store_true",
        help="Assertions already have embeddings in the JSON (key: _embedding).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if not args.input.exists():
        log.error("Input file not found: %s", args.input)
        return 1

    raw = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        log.error("Input must be a JSON array of assertion objects")
        return 1

    assertions = [Assertion.model_validate(item) for item in raw]
    log.info("Loaded %d assertions from %s", len(assertions), args.input)

    if args.skip_embed:
        embeddings = [item.get("_embedding", []) for item in raw]
        if any(not e for e in embeddings):
            log.error("--skip-embed requires every item to have an _embedding field")
            return 1
    else:
        from shared.config import embed_batch_safe

        texts = [a.text for a in assertions]
        log.info("Embedding %d assertions...", len(texts))
        embeddings = embed_batch_safe(texts) or []
        if not embeddings:
            log.error("Embedding failed (Ollama unavailable?)")
            return 1

    result = asyncio.run(
        run_normalization_pipeline(
            assertions,
            embeddings,
            dedup_threshold=args.threshold,
            skip_nli=args.skip_nli,
        )
    )

    output_data = {
        "total_input": result.total_input,
        "total_superseded": result.total_superseded,
        "duplicate_groups": len(result.duplicate_groups),
        "entailments_detected": len(result.entailments),
        "assertions": [a.model_dump(mode="json") for a in result.assertions],
    }

    output_json = json.dumps(output_data, indent=2, default=str)
    if args.output:
        args.output.write_text(output_json, encoding="utf-8")
        log.info(
            "Wrote %d assertions (%d superseded) to %s",
            result.total_input,
            result.total_superseded,
            args.output,
        )
    else:
        sys.stdout.write(output_json + "\n")

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(_cli_main())
