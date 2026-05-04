"""Grounding triage — pre-emission Bayesian self-check for narration.

Computes P(grounding_positive | candidate, context) from existing
system signals: impingement bus content, chronicle speech history,
claim posteriors, and grounding bridge GQI.

This is NOT a rule-based filter. It is a continuous posterior that
answers the constitutional question: "does saying this help my
grounding or hurt it?"

Design reference:
    Friston (2010) — Free Energy Principle / surprise minimization
    Sperber et al. (2010) — Epistemic Vigilance
    Tian et al. EMNLP 2023 — numeric posteriors for calibration
    Clark (2013) — Predictive Processing

Constitutional compliance:
    - No boolean gates; all factors are continuous [0, 1]
    - No blacklists; grounding is assessed by what IS present
      (specificity, novelty, claim coverage), not what ISN'T
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
from pathlib import Path

log = logging.getLogger(__name__)

_IMPINGEMENTS_FILE = Path("/dev/shm/hapax-dmn/impingements.jsonl")
_SPEECH_CHRONICLE = Path("/dev/shm/hapax-daimonion/speech-chronicle.jsonl")

# Grounding posterior thresholds — tuned from production logs:
# p=0.27 for 'Hapax observes a shift' → silence (generic observation)
# p=0.45+ for 'CPAL evaluator gain dropped 0.02' → emit (specific)
EMIT_FLOOR: float = 0.30       # below this → silence
RECOMPOSE_FLOOR: float = 0.35  # below this → marginal (logged)

# Technical noun pattern: capitalized words, dotted identifiers,
# hyphenated compound terms, numbers with units
_TECHNICAL_NOUN_RE = re.compile(
    r"\b(?:"
    r"[A-Z][a-z]+(?:[A-Z][a-z]+)+"  # CamelCase
    r"|[a-z]+\.[a-z]+(?:\.[a-z]+)*"  # dotted.identifiers
    r"|[a-z]+-[a-z]+-[a-z]+"  # triple-hyphenated
    r"|[A-Z]{2,}"  # ACRONYMS
    r"|\d+(?:\.\d+)?(?:s|ms|Hz|%|x|GB|MB|KB)"  # numbers with units
    r")\b"
)


def _extract_technical_terms(text: str) -> set[str]:
    """Extract technical nouns from text."""
    return set(_TECHNICAL_NOUN_RE.findall(text))


def _read_recent_impingements(window_s: float = 120.0) -> list[dict]:
    """Read impingements from the last window_s seconds."""
    now = time.time()
    cutoff = now - window_s
    results = []
    try:
        if not _IMPINGEMENTS_FILE.exists():
            return []
        for line in _IMPINGEMENTS_FILE.read_text(encoding="utf-8").splitlines()[-50:]:
            try:
                imp = json.loads(line)
                if imp.get("timestamp", 0) >= cutoff:
                    results.append(imp)
            except json.JSONDecodeError:
                continue
    except Exception:
        log.debug("grounding_triage: impingement read failed", exc_info=True)
    return results


def _read_recent_speech(window_s: float = 300.0) -> list[str]:
    """Read recently spoken narration texts from chronicle."""
    now = time.time()
    cutoff = now - window_s
    texts = []
    try:
        if not _SPEECH_CHRONICLE.exists():
            return []
        for line in _SPEECH_CHRONICLE.read_text(encoding="utf-8").splitlines()[-20:]:
            try:
                entry = json.loads(line)
                if entry.get("ts", 0) >= cutoff:
                    texts.append(entry.get("text", ""))
            except json.JSONDecodeError:
                continue
    except Exception:
        log.debug("grounding_triage: speech chronicle read failed", exc_info=True)
    return texts


def specificity_score(candidate: str, impingements: list[dict]) -> float:
    """Compute term overlap between candidate and active impingement context.

    High overlap = grounded in what's actually happening.
    Low overlap = generic or fabricated.
    """
    candidate_terms = set(candidate.lower().split())

    # Collect content terms from impingements
    context_terms: set[str] = set()
    for imp in impingements:
        content = imp.get("content", {})
        if isinstance(content, dict):
            for v in content.values():
                if isinstance(v, str):
                    context_terms.update(v.lower().split())
        narrative = content.get("narrative", "") if isinstance(content, dict) else ""
        if narrative:
            context_terms.update(narrative.lower().split())

    if not context_terms:
        # No impingement context — can't assess specificity
        # Return neutral rather than penalizing
        return 0.5

    # Jaccard-like: what fraction of candidate words appear in context?
    overlap = candidate_terms & context_terms
    # Remove stopwords from consideration
    stopwords = {"the", "a", "an", "is", "are", "was", "were", "in", "on",
                 "at", "to", "for", "of", "and", "or", "but", "not", "with",
                 "this", "that", "it", "has", "have", "had", "be", "been",
                 "from", "by", "as", "its", "we", "our", "the"}
    meaningful_candidate = candidate_terms - stopwords
    meaningful_overlap = overlap - stopwords

    if not meaningful_candidate:
        return 0.5

    return len(meaningful_overlap) / len(meaningful_candidate)


def novelty_score(candidate: str, recent_speech: list[str]) -> float:
    """Compute information novelty vs recent narrations.

    1.0 = completely new content.
    0.0 = pure repetition.
    """
    if not recent_speech:
        return 1.0  # nothing said recently → everything is novel

    candidate_words = set(candidate.lower().split())
    max_overlap = 0.0

    for spoken in recent_speech:
        spoken_words = set(spoken.lower().split())
        if not spoken_words:
            continue
        overlap = len(candidate_words & spoken_words) / max(len(candidate_words), 1)
        max_overlap = max(max_overlap, overlap)

    return 1.0 - max_overlap


def technical_density(candidate: str) -> float:
    """Fraction of sentences containing at least one technical noun.

    1.0 = every sentence has specific content.
    0.0 = pure filler.
    """
    sentences = [s.strip() for s in re.split(r'[.!?]+', candidate) if s.strip()]
    if not sentences:
        return 0.0

    technical_count = sum(
        1 for s in sentences
        if _TECHNICAL_NOUN_RE.search(s)
    )
    return technical_count / len(sentences)


def grounding_posterior(
    candidate: str,
    *,
    impingements: list[dict] | None = None,
    recent_speech: list[str] | None = None,
    gqi: float = 0.8,
) -> float:
    """Compute P(grounding_positive | candidate, context).

    Returns a float in [0, 1]. Higher = more grounded.
    All factors are continuous, no boolean gates.
    """
    if impingements is None:
        impingements = _read_recent_impingements()
    if recent_speech is None:
        recent_speech = _read_recent_speech()

    factors = [
        specificity_score(candidate, impingements),
        novelty_score(candidate, recent_speech),
        technical_density(candidate),
        gqi,
    ]

    # Geometric mean — each factor contributes equally, scale-independent
    log_sum = sum(math.log(max(f, 0.01)) for f in factors)
    posterior = math.exp(log_sum / len(factors))

    log.debug(
        "grounding_triage: posterior=%.3f (spec=%.2f nov=%.2f tech=%.2f gqi=%.2f) | %s",
        posterior,
        factors[0], factors[1], factors[2], factors[3],
        candidate[:60],
    )
    return posterior


def triage(
    candidate: str,
    *,
    impingements: list[dict] | None = None,
    recent_speech: list[str] | None = None,
    gqi: float = 0.8,
) -> tuple[str, float]:
    """Triage a candidate utterance.

    Returns (action, posterior) where action is:
    - "emit": posterior >= RECOMPOSE_FLOOR, safe to emit
    - "silence": posterior < EMIT_FLOOR, better to say nothing
    - "marginal": in between, caller decides

    This function NEVER returns a modified string. It assesses,
    it does not rewrite. The candidate is either grounded enough
    to emit or it isn't.
    """
    p = grounding_posterior(
        candidate,
        impingements=impingements,
        recent_speech=recent_speech,
        gqi=gqi,
    )

    if p >= RECOMPOSE_FLOOR:
        return "emit", p
    elif p < EMIT_FLOOR:
        log.info(
            "grounding_triage: SILENCE (p=%.3f < %.2f) | %s",
            p, EMIT_FLOOR, candidate[:80],
        )
        return "silence", p
    else:
        log.info(
            "grounding_triage: MARGINAL (p=%.3f) | %s",
            p, candidate[:80],
        )
        return "marginal", p


__all__ = [
    "EMIT_FLOOR",
    "RECOMPOSE_FLOOR",
    "grounding_posterior",
    "novelty_score",
    "specificity_score",
    "technical_density",
    "triage",
]
