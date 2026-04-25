"""Polysemic-audit CI gate scaffold (V5 weave wk1 d2 — epsilon).

Scans an artifact (markdown / HTML / plain text) for unintended
cross-domain readings. The audit's purpose is to flag terms whose
established meanings diverge across legal / governance / AI-safety
registers when used in close proximity in the same artifact —
academic readers carrying multiple decoder stacks see different
artifacts otherwise.

Per V5 weave § 12 invariant 5: every artifact passes this gate
before approval-queue entry.

Wk1 d2 (this scaffold): seed registry of 3 terms (``compliance``,
``governance``, ``safety``) that cover the V5-spec'd "legal /
governance / AI-safety polysemy" core. Detection is single-pass
heuristic — false-negative bias is intentional (better to miss a
borderline polysemy than to spam approval-queue noise).

Wk1 d4 (PUB-CITATION-A consumer): registry expansion + CI integration
+ per-artifact severity threshold tuning. The ``audit_artifact``
contract is stable from wk1 d2.

Detection heuristic
-------------------

For each polysemic term in :data:`SEED_POLYSEMIC_TERMS`:

  1. Tokenize the artifact into sentences (very rough — split on
     ``.``, ``!``, ``?``).
  2. For each sentence, identify which register(s) the surrounding
     terms fingerprint into. Registers are heuristically detected
     via per-register marker-term sets.
  3. If two distinct registers fire across the artifact AND the
     polysemic term appears in both register-firing sentences:
     emit a :class:`PolysemicConcern`.

This is a pragmatic detector, not a semantic one. Future work
(post-V5) could swap in an LLM-based audit; today's contract just
needs a deterministic, fast, in-process gate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PolysemicConcern:
    """One flagged cross-domain reading."""

    term: str
    excerpt: str
    registers: tuple[str, ...]


@dataclass(frozen=True)
class PolysemicAuditResult:
    """Outcome of a polysemic-audit run."""

    passed: bool
    concerns: tuple[PolysemicConcern, ...]


# Per-register fingerprint terms — words whose presence localizes
# a sentence into a particular register. Conservative seed; expansion
# at wk1 d4 PUB-CITATION-A.
_REGISTER_MARKERS: dict[str, frozenset[str]] = {
    "legal": frozenset(
        {
            "gdpr",
            "hipaa",
            "regulation",
            "regulatory",
            "statute",
            "statutory",
            "osha",
            "regulations",
        }
    ),
    "ai_safety": frozenset(
        {
            "alignment",
            "axiom",
            "axioms",
            "model",
            "directives",
            "directive",
            "axiom-bound",
            "operator",
            "prompt",
            "orchestrator",
        }
    ),
    "corporate_governance": frozenset(
        {
            "board",
            "boards",
            "shareholder",
            "shareholders",
            "corporate",
            "executive",
        }
    ),
    "product_safety": frozenset(
        {
            "product",
            "device",
            "operational",
            "workplace",
            "occupational",
        }
    ),
}


# Seed polysemic-term registry: terms whose meaning diverges across
# the registers above.
SEED_POLYSEMIC_TERMS: frozenset[str] = frozenset(
    {
        "compliance",
        "governance",
        "safety",
    }
)


_SENTENCE_SPLIT = re.compile(r"[.!?]+\s+")


def _identify_registers(sentence: str) -> set[str]:
    """Return the set of registers a sentence fingerprints into.

    Lowercased substring match — fast, no dependency on an NLP toolkit.
    Multiple registers can fire for a single sentence (legitimate cross-
    register prose like a definitions paragraph).
    """
    lowered = sentence.lower()
    fired: set[str] = set()
    for register, markers in _REGISTER_MARKERS.items():
        if any(marker in lowered for marker in markers):
            fired.add(register)
    return fired


def audit_artifact(
    text: str,
    *,
    acknowledged_terms: frozenset[str] | None = None,
) -> PolysemicAuditResult:
    """Scan ``text`` for cross-register polysemy on seed terms.

    Returns a result with ``passed=True, concerns=()`` for clean text
    (empty / single-register / unambiguous). For text where a seed
    term appears across two distinct registers, emits one
    :class:`PolysemicConcern` per term.

    ``acknowledged_terms`` (optional) is a frozenset of seed terms the
    operator has explicitly acknowledged as multi-register-by-design
    for this artifact. Concerns on acknowledged terms are filtered
    out of the result. The audit's documented remediation ("explicit
    register-shift sentence at the top of each section") is
    operator-ratified when this set lists a term — meaning the
    artifact's prose handles the register translation explicitly,
    and the heuristic's flag is a known false-positive.

    Acknowledgement is a manual operator action per artifact, not a
    blanket toggle. Listing a term in ``acknowledged_terms`` is the
    same architectural posture as ``feedback_no_operator_approval_waits``
    directive #10 admin-merge: a documented, contextual override that
    preserves the gate's signal for unknown future cases.
    """
    if not text or not text.strip():
        return PolysemicAuditResult(passed=True, concerns=())

    ack: frozenset[str] = acknowledged_terms or frozenset()

    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]

    # For each polysemic term, collect the set of registers in which
    # it appears across the artifact's sentences.
    concerns: list[PolysemicConcern] = []
    for term in SEED_POLYSEMIC_TERMS:
        if term in ack:
            continue
        registers_seen: set[str] = set()
        excerpt_parts: list[str] = []
        for sentence in sentences:
            if term not in sentence.lower():
                continue
            sentence_registers = _identify_registers(sentence)
            if sentence_registers:
                registers_seen.update(sentence_registers)
                excerpt_parts.append(sentence[:80])
        # Flag when 2+ distinct registers fire for the same term.
        if len(registers_seen) >= 2:
            concerns.append(
                PolysemicConcern(
                    term=term,
                    excerpt=" ... ".join(excerpt_parts[:2]),
                    registers=tuple(sorted(registers_seen)),
                )
            )

    return PolysemicAuditResult(
        passed=(len(concerns) == 0),
        concerns=tuple(concerns),
    )


__all__ = [
    "PolysemicAuditResult",
    "PolysemicConcern",
    "SEED_POLYSEMIC_TERMS",
    "audit_artifact",
]
