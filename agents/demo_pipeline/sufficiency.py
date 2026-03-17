"""Knowledge sufficiency gate — checks available knowledge before demo generation."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from agents.demo_models import AudienceDossier, AudiencePersona, load_audiences, load_personas
from shared.config import PROFILES_DIR, get_qdrant
from shared.operator import get_operator

log = logging.getLogger(__name__)

from shared.config import HAPAXROMANA_DIR

_HAPAXROMANA_CLAUDE_MD = HAPAXROMANA_DIR / "CLAUDE.md"
_KNOWN_ARCHETYPES = {"family", "team-member", "leadership", "technical-peer"}

# Regex for detecting named-person references in audience text.
# Avoids importing from agents.demo (circular dependency).
_PERSON_REFERENCE_RE = re.compile(
    r"\bmy\s+(wife|husband|partner|friend|mom|dad|mother|father|brother|sister|boss|manager|son|daughter)\b",
    re.IGNORECASE,
)

# ── Literature-grounded knowledge dimensions ──────────────────────────────────
#
# 7 dimensions across 3 categories.  Each dimension has a literature citation
# and flags that drive the scoring logic in score_dimensions().

KNOWLEDGE_DIMENSIONS: list[dict] = [
    # PERSON dimensions — require dossier for "high" confidence
    {
        "key": "prior_knowledge",
        "category": "person",
        "label": "Prior Knowledge & Expertise Level",
        "citation": "Mayer (Cognitive Load Theory); Kalyuga (Expertise Reversal Effect)",
        "archetype_inferable": True,
        "dossier_required_for_high": True,
    },
    {
        "key": "goals_pain_points",
        "category": "person",
        "label": "Goals & Pain Points",
        "citation": "Duarte (Resonate) — audience as hero with current/desired state",
        "archetype_inferable": True,
        "dossier_required_for_high": True,
    },
    {
        "key": "attitudes_resistance",
        "category": "person",
        "label": "Attitudes & Resistance",
        "citation": "Duarte (Resonate); Monroe (Motivated Sequence)",
        "archetype_inferable": False,
        "dossier_required_for_high": True,
    },
    {
        "key": "decision_role",
        "category": "person",
        "label": "Decision Role & Authority",
        "citation": "Cohan (Great Demo!) — situation slides, discovery agreement",
        "archetype_inferable": False,
        "dossier_required_for_high": True,
    },
    # SUBJECT dimensions — inferable from archetype + system knowledge
    {
        "key": "relevant_subset",
        "category": "subject",
        "label": "Relevant Subset Mapping",
        "citation": "Falcone (Just F*ing Demo!) — show what matters to THIS audience",
        "archetype_inferable": True,
        "dossier_required_for_high": False,
    },
    {
        "key": "abstraction_vocabulary",
        "category": "subject",
        "label": "Appropriate Abstraction & Vocabulary",
        "citation": "Mayer (Coherence Principle); Sweller (Cognitive Load Theory)",
        "archetype_inferable": True,
        "dossier_required_for_high": False,
    },
    # CONTEXT dimension
    {
        "key": "situational_constraints",
        "category": "context",
        "label": "Situational Constraints & Stakes",
        "citation": "Bitzer (The Rhetorical Situation) — exigence + constraints",
        "archetype_inferable": False,
        "dossier_required_for_high": True,
    },
]


@dataclass
class DimensionScore:
    """Score for a single knowledge dimension."""

    key: str  # "prior_knowledge"
    category: str  # "person"
    label: str  # "Prior Knowledge & Expertise Level"
    confidence: Literal["high", "inferred", "low", "missing"]
    detail: str  # "Dossier provides: 'Never seen the system'"
    action: str  # "" or "Run --gather-dossier to collect"


_DIMENSION_KEYWORD_MAP: dict[str, list[str]] = {
    "prior_knowledge": ["experience", "expert", "beginner", "technical", "knowledge", "familiar"],
    "goals_pain_points": ["goal", "pain", "want", "need", "problem", "challenge", "wish"],
    "attitudes_resistance": ["attitude", "resist", "skeptic", "enthusiast", "concern", "objection"],
    "decision_role": ["decision", "authority", "budget", "approve", "role", "buyer", "stakeholder"],
    "situational_constraints": ["constraint", "deadline", "time", "stakes", "urgency"],
}


def _dossier_covers_dimension(dim_key: str, dossier: AudienceDossier) -> bool:
    """Check whether a dossier has data relevant to *dim_key*."""
    keywords = _DIMENSION_KEYWORD_MAP.get(dim_key, [])
    if not keywords:
        return False
    text = (dossier.context or "").lower()
    # Check calibration values only (not keys — "context" key causes false positives)
    for cal_val in dossier.calibration.values():
        if isinstance(cal_val, list):
            text += " " + " ".join(str(v).lower() for v in cal_val)
        elif isinstance(cal_val, str):
            text += " " + cal_val.lower()
    return any(kw in text for kw in keywords)


def score_dimensions(
    archetype: str,
    dossier: AudienceDossier | None,
    persona: AudiencePersona | None,
    has_system_knowledge: bool = False,
) -> list[DimensionScore]:
    """Score each knowledge dimension given available audience data.

    Scoring logic per dimension:
    - **high**: dossier provides explicit data for this dimension
    - **inferred**: archetype provides a reasonable default (archetype_inferable=True, persona exists)
    - **low**: archetype_inferable=True but no persona matched
    - **missing**: archetype_inferable=False and no dossier
    """
    scores: list[DimensionScore] = []

    for dim in KNOWLEDGE_DIMENSIONS:
        key = dim["key"]
        category = dim["category"]
        label = dim["label"]
        archetype_inferable: bool = dim["archetype_inferable"]
        dossier_required_for_high: bool = dim["dossier_required_for_high"]

        # --- SUBJECT dimensions: system knowledge + archetype, no dossier needed ---
        if category == "subject":
            if has_system_knowledge and persona is not None:
                confidence: Literal["high", "inferred", "low", "missing"] = "high"
                detail = "System knowledge + archetype persona available"
                action = ""
            elif persona is not None:
                confidence = "inferred"
                detail = f"Archetype '{archetype}' provides defaults"
                action = ""
            elif archetype_inferable:
                confidence = "low"
                detail = f"Archetype '{archetype}' not matched to persona"
                action = "Verify archetype or provide persona"
            else:
                confidence = "missing"
                detail = "No archetype or system knowledge"
                action = "Run --gather-dossier to collect"
            scores.append(DimensionScore(key, category, label, confidence, detail, action))
            continue

        # --- PERSON and CONTEXT dimensions ---
        # Check dossier first (for "high")
        if dossier is not None and _dossier_covers_dimension(key, dossier):
            confidence = "high"
            detail = f"Dossier provides data for '{label}'"
            action = ""
        elif dossier is not None and dossier_required_for_high:
            # Dossier exists but doesn't cover this dimension
            if archetype_inferable and persona is not None:
                confidence = "inferred"
                detail = f"Archetype '{archetype}' provides defaults; dossier lacks specifics"
                action = "Update dossier with dimension-specific info"
            elif archetype_inferable:
                confidence = "low"
                detail = f"Archetype '{archetype}' not matched to persona"
                action = "Verify archetype or provide persona"
            else:
                confidence = "missing"
                detail = "Dossier lacks data; not archetype-inferable"
                action = "Run --gather-dossier to collect"
        elif dossier is None:
            # No dossier at all
            if archetype_inferable and persona is not None:
                confidence = "inferred"
                detail = f"Archetype '{archetype}' provides defaults"
                action = "Run --gather-dossier for higher confidence"
            elif archetype_inferable:
                confidence = "low"
                detail = f"Archetype '{archetype}' not matched to persona"
                action = "Verify archetype or provide persona"
            else:
                confidence = "missing"
                detail = "No dossier; not archetype-inferable"
                action = "Run --gather-dossier to collect"
        else:
            # Shouldn't normally reach here — fallback
            confidence = "missing"
            detail = "Insufficient data"
            action = "Run --gather-dossier to collect"

        scores.append(DimensionScore(key, category, label, confidence, detail, action))

    return scores


def _audience_text_references_person(audience_text: str) -> bool:
    """Detect whether audience_text references a specific named person."""
    return bool(_PERSON_REFERENCE_RE.search(audience_text))


@dataclass
class KnowledgeCheck:
    name: str
    available: bool
    detail: str  # "4374 facts indexed" or "file not found"
    owner: Literal["system", "person"]


@dataclass
class SufficiencyResult:
    confidence: Literal["high", "adequate", "low", "blocked"]
    system_checks: list[KnowledgeCheck]
    audience_checks: list[KnowledgeCheck]
    enrichment_actions: list[str]  # source keys for gather_research
    audience_dossier: AudienceDossier | None
    dimension_scores: list[DimensionScore] = field(default_factory=list)


def check_sufficiency(
    scope: str,
    archetype: str,
    audience_text: str,
    health_report: object | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> SufficiencyResult:
    """Check knowledge sources needed for demo generation.

    Sync function — file stats + one optional Qdrant metadata call.
    Does NOT block on missing dossier — dossiers enrich, don't gate.
    """

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)
        else:
            log.info(msg)

    system_checks: list[KnowledgeCheck] = []
    enrichment_actions: list[str] = []

    # --- System checks ---

    # 1. architecture_docs
    progress("Checking architecture docs...")
    try:
        stat = _HAPAXROMANA_CLAUDE_MD.stat()
        available = stat.st_size > 1000
        detail = f"{stat.st_size} bytes" if available else f"too small ({stat.st_size} bytes)"
    except OSError:
        available = False
        detail = "file not found"
    system_checks.append(KnowledgeCheck("architecture_docs", available, detail, "system"))

    # 2. component_registry
    progress("Checking component registry...")
    reg_path = PROFILES_DIR / "component-registry.yaml"
    try:
        reg_path.stat()
        available = True
        detail = "exists"
    except OSError:
        available = False
        detail = "file not found"
    system_checks.append(KnowledgeCheck("component_registry", available, detail, "system"))

    # 3. health_data
    progress("Checking health data...")
    if health_report is not None:
        available = True
        detail = "from readiness gate"
    else:
        history_path = PROFILES_DIR / "health-history.jsonl"
        try:
            mtime = history_path.stat().st_mtime
            age_seconds = time.time() - mtime
            if age_seconds < 3600:
                available = True
                detail = f"updated {int(age_seconds)}s ago"
            else:
                available = False
                detail = f"stale ({int(age_seconds / 3600)}h old)"
        except OSError:
            available = False
            detail = "file not found"
    system_checks.append(KnowledgeCheck("health_data", available, detail, "system"))

    # 4. operator_manifest
    progress("Checking operator manifest...")
    try:
        manifest = get_operator()
        has_axioms = "axioms" in manifest
        available = has_axioms
        detail = "has axioms" if has_axioms else "missing axioms key"
    except Exception as e:
        available = False
        detail = f"error: {e}"
    system_checks.append(KnowledgeCheck("operator_manifest", available, detail, "system"))

    # 5. profile_facts (Qdrant)
    progress("Checking profile facts...")
    try:
        client = get_qdrant()
        info = client.get_collection("profile-facts")
        point_count = info.points_count or 0
        available = point_count > 100
        detail = f"{point_count} facts indexed"
    except Exception as e:
        available = False
        detail = f"unreachable: {e}"
    system_checks.append(KnowledgeCheck("profile_facts", available, detail, "system"))

    # 6. briefing
    progress("Checking briefing...")
    briefing_path = PROFILES_DIR / "briefing.md"
    try:
        mtime = briefing_path.stat().st_mtime
        age_seconds = time.time() - mtime
        if age_seconds < 48 * 3600:
            available = True
            detail = f"updated {int(age_seconds / 3600)}h ago"
        else:
            available = False
            detail = f"stale ({int(age_seconds / 3600)}h old)"
    except OSError:
        available = False
        detail = "file not found"
    system_checks.append(KnowledgeCheck("briefing", available, detail, "system"))

    # 7. architecture_rag (informational — doesn't block)
    progress("Checking architecture docs in RAG...")
    try:
        from qdrant_client.models import FieldCondition, Filter, MatchText

        from shared.config import embed

        arch_vector = embed("system architecture design", prefix="search_query")
        arch_filter = Filter(
            must=[FieldCondition(key="source", match=MatchText(text="hapaxromana"))]
        )
        arch_results = client.query_points(
            collection_name="documents",
            query=arch_vector,
            query_filter=arch_filter,
            limit=1,
        )
        arch_count = len(arch_results.points)
        arch_available = arch_count > 0
        arch_detail = (
            "indexed in Qdrant"
            if arch_available
            else "No architecture docs indexed. Run: ln -s ~/projects/hapaxromana ~/documents/rag-sources/hapaxromana"
        )
    except Exception as e:
        arch_available = False
        arch_detail = f"check failed: {e}"
    system_checks.append(KnowledgeCheck("architecture_rag", arch_available, arch_detail, "system"))

    # 8. profile_digest
    progress("Checking profile digest...")
    digest_path = PROFILES_DIR / "operator-digest.json"
    try:
        digest_path.stat()
        available = True
        detail = "exists"
    except OSError:
        available = False
        detail = "file not found"
    system_checks.append(KnowledgeCheck("profile_digest", available, detail, "system"))

    # 9. doc_freshness — count of hapaxromana doc chunks in Qdrant
    progress("Checking doc freshness...")
    try:
        from qdrant_client.models import FieldCondition, Filter, MatchText

        doc_filter = Filter(
            must=[FieldCondition(key="source", match=MatchText(text="hapaxromana"))]
        )
        doc_count_result = client.count(
            collection_name="documents",
            count_filter=doc_filter,
            exact=True,
        )
        doc_chunk_count = doc_count_result.count
        doc_available = doc_chunk_count >= 100
        doc_detail = (
            f"{doc_chunk_count} doc chunks indexed"
            if doc_available
            else "Project docs not indexed — run: ln -s ~/projects/hapaxromana ~/documents/rag-sources/hapaxromana && uv run python -m agents.ingest"
        )
    except Exception as e:
        doc_available = False
        doc_detail = f"check failed: {e}"
    system_checks.append(KnowledgeCheck("doc_freshness", doc_available, doc_detail, "system"))

    # --- Audience checks ---

    # 1. archetype_resolved
    arch_available = archetype in _KNOWN_ARCHETYPES
    audience_checks: list[KnowledgeCheck] = [
        KnowledgeCheck(
            "archetype_resolved",
            arch_available,
            f"matched '{archetype}'" if arch_available else f"unknown archetype '{archetype}'",
            "person",
        )
    ]

    # 2. named_dossier
    audience_dossier: AudienceDossier | None = None
    dossiers = load_audiences()
    audience_lower = audience_text.lower()
    for dossier_key, dossier in dossiers.items():
        if dossier_key in audience_lower:
            audience_dossier = dossier
            break

    audience_checks.append(
        KnowledgeCheck(
            "named_dossier",
            audience_dossier is not None,
            f"found: {audience_dossier.name}"
            if audience_dossier
            else f"No dossier for '{audience_text}'. Run: uv run python -m agents.demo --gather-dossier \"{audience_text}\"",
            "person",
        )
    )

    # --- Enrichment actions ---
    check_to_action = {
        "briefing": "briefing_stats",
        "profile_digest": "profile_digest",
    }
    for check in system_checks:
        if not check.available and check.name in check_to_action:
            enrichment_actions.append(check_to_action[check.name])

    # --- Confidence ---
    system_passing = sum(1 for c in system_checks if c.available)
    has_dossier = any(c.available for c in audience_checks if c.name == "named_dossier")

    system_total = len(system_checks)
    if system_passing < system_total * 0.4:
        confidence: Literal["high", "adequate", "low", "blocked"] = "blocked"
    elif system_passing < system_total * 0.8:
        confidence = "low"
    elif has_dossier:
        confidence = "high"
    else:
        confidence = "adequate"

    # --- Dimension scoring ---
    progress("Scoring knowledge dimensions...")
    personas = load_personas()
    persona = personas.get(archetype)
    has_system_knowledge = any(
        c.available for c in system_checks if c.name == "component_registry"
    ) and any(c.available for c in system_checks if c.name == "operator_manifest")
    dimension_scores = score_dimensions(
        archetype=archetype,
        dossier=audience_dossier,
        persona=persona,
        has_system_knowledge=has_system_knowledge,
    )

    # Cap confidence if any PERSON dimension is "missing" AND audience_text references
    # a named person — signals we're targeting a specific individual but lack key knowledge.
    has_missing_person_dim = any(
        d.category == "person" and d.confidence == "missing" for d in dimension_scores
    )
    if (
        confidence == "high"
        and has_missing_person_dim
        and _audience_text_references_person(audience_text)
    ):
        confidence = "adequate"

    progress(
        f"Knowledge sufficiency: {confidence} ({system_passing}/{len(system_checks)} system checks)"
    )

    return SufficiencyResult(
        confidence=confidence,
        system_checks=system_checks,
        audience_checks=audience_checks,
        enrichment_actions=enrichment_actions,
        audience_dossier=audience_dossier,
        dimension_scores=dimension_scores,
    )
