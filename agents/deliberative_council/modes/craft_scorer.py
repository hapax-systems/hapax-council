"""CRAFT scorer — Claim Risk Assessment For Triage.

Scores extracted claims on 6 dimensions for grounding priority.
Used to triage epistemic debt in AI-orchestrated research programs.

Dimensions (weighted):
  CHI Centrality (0.30) — is the claim in the paper's core argument?
  Domain Distance (0.25) — how far from the operator's expertise?
  Falsifiability Risk (0.20) — if wrong, does the paper fail?
  AI Provenance (0.10) — was this produced by a research agent?
  Dependency Depth (0.10) — how many downstream claims depend on this?
  Verification Status (0.05) — has CCTV disconfirmation been run?

Triage categories:
  A (>= 3.5): ground personally before CHI submission
  B (2.5-3.49): verify via CCTV, no deep personal understanding needed
  C (1.5-2.49): trust the tests
  D (< 1.5): already owned (operator's domain expertise)
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

CRAFT_WEIGHTS: dict[str, float] = {
    "chi_centrality": 0.30,
    "domain_distance": 0.25,
    "falsifiability_risk": 0.20,
    "ai_provenance": 0.10,
    "dependency_depth": 0.10,
    "verification_status": 0.05,
}

DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "enactivism": [
        "varela",
        "maturana",
        "autopoiesis",
        "enactive",
        "sense-making",
        "structural coupling",
        "embodied",
        "phenomenolog",
        "umwelt",
        "di paolo",
        "thompson",
        "gibson",
        "affordance",
        "ecological",
    ],
    "information_retrieval": [
        "cosine",
        "embedding",
        "vector",
        "qdrant",
        "retrieval",
        "similarity",
        "ranking",
        "recall",
        "precision",
        "ndcg",
        "mrr",
    ],
    "knowledge_graphs": [
        "link prediction",
        "adamic-adar",
        "resource allocation",
        "common neighbor",
        "graph topology",
        "transE",
        "knowledge graph",
    ],
    "bayesian_statistics": [
        "bayesian",
        "bocpd",
        "prior",
        "posterior",
        "conjugate",
        "normal-inverse-gamma",
        "kl divergence",
        "surprise",
        "thompson sampling",
        "beta distribution",
    ],
    "graph_theory": [
        "clustering coefficient",
        "connected component",
        "degree distribution",
        "phase transition",
        "erdos-renyi",
        "density",
        "adjacency",
    ],
    "pu_learning": [
        "positive-unlabeled",
        "pu learning",
        "unlabeled",
        "wsjf",
        "held-out",
        "evaluation",
        "link prediction benchmark",
    ],
}

OPERATOR_DOMAIN = "enactivism"


class TriageCategory(StrEnum):
    A = "ground_personally"
    B = "verify_cctv"
    C = "trust_tests"
    D = "already_owned"


class CraftScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    chi_centrality: int = 3
    domain_distance: int = 3
    falsifiability_risk: int = 3
    ai_provenance: int = 3
    dependency_depth: int = 2
    verification_status: int = 3
    composite: float = 0.0
    category: TriageCategory = TriageCategory.B


class ScoredClaim(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_path: str
    line_number: int
    text: str
    verb: str
    claim_category: str
    craft: CraftScore


def classify_domain(text: str) -> str:
    """Identify the primary technical domain of a claim by keyword matching."""
    text_lower = text.lower()
    scores: dict[str, int] = {}
    for domain, keywords in DOMAIN_KEYWORDS.items():
        scores[domain] = sum(1 for kw in keywords if kw in text_lower)
    best = max(scores, key=lambda d: scores[d])
    return best if scores[best] > 0 else "unknown"


def score_domain_distance(text: str) -> int:
    """Score 1-5: how far is this claim from the operator's expertise domain."""
    domain = classify_domain(text)
    if domain == OPERATOR_DOMAIN:
        return 1
    if domain == "unknown":
        return 3
    return 4


def score_ai_provenance(claim_category: str) -> int:
    """Score 1-5 based on claim category. Bridge claims are more likely AI-produced."""
    if claim_category == "bridge":
        return 4
    return 3


def score_verification_status(has_receipt: bool) -> int:
    """Score 1-5: lower if already verified."""
    return 1 if has_receipt else 4


def compute_composite(scores: dict[str, int]) -> float:
    """Weighted composite of all dimensions."""
    total = 0.0
    for dim, weight in CRAFT_WEIGHTS.items():
        total += scores.get(dim, 3) * weight
    return round(total, 2)


def assign_category(composite: float) -> TriageCategory:
    """Map composite score to triage category."""
    if composite >= 3.5:
        return TriageCategory.A
    if composite >= 2.5:
        return TriageCategory.B
    if composite >= 1.5:
        return TriageCategory.C
    return TriageCategory.D


def score_claim(
    source_path: str,
    line_number: int,
    text: str,
    verb: str,
    claim_category: str = "epistemic",
    *,
    chi_centrality: int = 3,
    has_disconfirmation_receipt: bool = False,
) -> ScoredClaim:
    """Score a single claim on all CRAFT dimensions."""
    scores = {
        "chi_centrality": chi_centrality,
        "domain_distance": score_domain_distance(text),
        "falsifiability_risk": 4 if claim_category == "bridge" else 3,
        "ai_provenance": score_ai_provenance(claim_category),
        "dependency_depth": 2,
        "verification_status": score_verification_status(has_disconfirmation_receipt),
    }
    composite = compute_composite(scores)
    category = assign_category(composite)

    return ScoredClaim(
        source_path=source_path,
        line_number=line_number,
        text=text,
        verb=verb,
        claim_category=claim_category,
        craft=CraftScore(
            chi_centrality=scores["chi_centrality"],
            domain_distance=scores["domain_distance"],
            falsifiability_risk=scores["falsifiability_risk"],
            ai_provenance=scores["ai_provenance"],
            dependency_depth=scores["dependency_depth"],
            verification_status=scores["verification_status"],
            composite=composite,
            category=category,
        ),
    )
