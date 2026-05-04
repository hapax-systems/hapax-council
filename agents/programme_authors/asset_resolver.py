"""Per-role asset resolution for the seven segmented-content programmes.

Each segmented-content :class:`~shared.programme.ProgrammeRole`
(``tier_list``, ``top_10``, ``rant``, ``react``, ``iceberg``,
``interview``, ``lecture``) has a distinct acquisition pattern. The
functions in this module assemble structured assets that the narrative
composer and director surfaces can consume without re-parsing the
free-form formatted strings :mod:`shared.knowledge_search` returns.

Failure posture
---------------

Every resolver fails *open*: a Qdrant timeout, a missing vault note,
or a content-resolver outage produces empty assets, never an
exception. The narrative composer is expected to degrade gracefully
when assets are sparse (a ``tier_list`` with zero candidates falls
back to "Hapax narrates the topic frame and invites chat to
contribute candidates"). Callers can detect emptiness via
``ProgrammeAssets.is_empty`` to surface "no grounding available" to
the operator without crashing the planner loop.

Async vs sync
-------------

Resolvers are synchronous because Qdrant + filesystem reads are quick
at our scale (sub-100ms per query, vault is ~1k notes). The
content-resolver path for ``react`` is a remote HTTP call and could
profitably be async — but the rest of the planner loop is synchronous
today, so we wrap it with the same blocking interface. Move to async
in a follow-up when the planner itself goes async.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# Operator vault paths that supply structured outline material.
# See `agents/obsidian_sync.py` for the canonical vault layout.
VAULT_ROOT: Path = Path("~/Documents/Personal").expanduser()
VAULT_AREAS: Path = VAULT_ROOT / "30-areas"
VAULT_PROJECTS: Path = VAULT_ROOT / "20-projects"
VAULT_RESOURCES: Path = VAULT_ROOT / "50-resources"

# Default assembly limits. Resolvers truncate at these unless the
# caller passes a tighter cap. Limits chosen to fit one programme
# segment without overflowing the narrative composer's context budget.
DEFAULT_TIER_LIST_CANDIDATES: int = 25
DEFAULT_TOP_10_CANDIDATES: int = 10
DEFAULT_RANT_POSITIONS: int = 8
DEFAULT_ICEBERG_LAYERS: int = 4
DEFAULT_LECTURE_OUTLINE_NOTES: int = 6
DEFAULT_INTERVIEW_PREP_HITS: int = 8


@dataclass(frozen=True)
class TierListAssets:
    """Resolved candidates for a ``tier_list`` programme."""

    topic: str
    candidates: tuple[str, ...]
    candidate_sources: tuple[str, ...]

    @property
    def is_empty(self) -> bool:
        return not self.candidates


@dataclass(frozen=True)
class Top10Assets:
    """Resolved ranked entries for a ``top_10`` programme."""

    topic: str
    ranked_candidates: tuple[str, ...]
    candidate_sources: tuple[str, ...]

    @property
    def is_empty(self) -> bool:
        return not self.ranked_candidates


@dataclass(frozen=True)
class RantAssets:
    """Resolved operator positions + corrections for a ``rant`` programme."""

    topic: str
    operator_positions: tuple[str, ...]
    prior_corrections: tuple[str, ...]

    @property
    def is_empty(self) -> bool:
        return not self.operator_positions and not self.prior_corrections


@dataclass(frozen=True)
class ReactAssets:
    """Resolved source media for a ``react`` programme."""

    source_uri: str
    resolved_title: str | None = None
    resolved_excerpt: str | None = None
    chapter_markers: tuple[str, ...] = ()
    resolution_failed: bool = False

    @property
    def is_empty(self) -> bool:
        return self.resolution_failed and self.resolved_title is None


@dataclass(frozen=True)
class IcebergAssets:
    """Resolved layered outline for an ``iceberg`` programme.

    ``layers`` is ordered surface → deepest. Each entry is a list of
    asset references (vault paths or RAG-hit identifiers) for that
    layer's beats.
    """

    topic: str
    layers: tuple[tuple[str, ...], ...]

    @property
    def is_empty(self) -> bool:
        return not any(self.layers)


@dataclass(frozen=True)
class InterviewAssets:
    """Resolved subject prep for an ``interview`` programme."""

    subject: str
    prep_hits: tuple[str, ...]
    prior_interaction_refs: tuple[str, ...]

    @property
    def is_empty(self) -> bool:
        return not self.prep_hits and not self.prior_interaction_refs


@dataclass(frozen=True)
class LectureAssets:
    """Resolved outline for a ``lecture`` programme.

    ``outline_notes`` is a list of vault note paths (relative to
    :data:`VAULT_ROOT`) that supply outline material. ``rag_fallbacks``
    captures RAG-only hits used when the vault is silent on the topic.
    """

    topic: str
    outline_notes: tuple[str, ...]
    rag_fallbacks: tuple[str, ...]

    @property
    def is_empty(self) -> bool:
        return not self.outline_notes and not self.rag_fallbacks


# Discriminated-union return type for :func:`resolve_assets`. Callers
# branch on role; mypy/pyright keep the per-role type tight.
ProgrammeAssets = (
    TierListAssets
    | Top10Assets
    | RantAssets
    | ReactAssets
    | IcebergAssets
    | InterviewAssets
    | LectureAssets
)


# --- Qdrant search helper (structured, not formatted-string) ----------------


def _qdrant_search(
    collection: str,
    query: str,
    *,
    limit: int,
) -> list[tuple[str, str, float]]:
    """Return (text, source, score) triples; empty list on any failure.

    :mod:`shared.knowledge_search` formats results as markdown for LLM
    consumption. The asset resolvers need raw structured access — same
    Qdrant call, different shape. Failing open keeps the planner from
    blocking on a Qdrant outage.
    """
    try:
        from shared.config import embed, get_qdrant
    except ImportError:
        log.debug("shared.config unavailable; skipping qdrant lookup")
        return []
    try:
        client = get_qdrant()
        vector = embed(query, prefix="search_query")
        results = client.query_points(collection, query=vector, limit=limit)
    except Exception:
        log.debug("qdrant query failed for collection=%s", collection, exc_info=True)
        return []
    out: list[tuple[str, str, float]] = []
    for pt in getattr(results, "points", []):
        payload = getattr(pt, "payload", {}) or {}
        text = (payload.get("text") or "").strip()
        if not text:
            continue
        source = str(payload.get("source") or payload.get("source_service") or "?")
        score = float(getattr(pt, "score", 0.0) or 0.0)
        out.append((text, source, score))
    return out


def _vault_notes_for_topic(
    topic: str,
    *,
    roots: tuple[Path, ...],
    limit: int,
) -> list[str]:
    """Return vault note paths whose content mentions ``topic``.

    Linear scan — fine at vault scale (~1k notes); if this becomes
    a bottleneck, switch to ripgrep or to a Qdrant-only path.
    Returns relative paths so they're stable across worktrees.
    """
    if not topic.strip():
        return []
    needle = topic.lower()
    hits: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.md"):
            try:
                if needle in path.read_text(encoding="utf-8", errors="ignore").lower():
                    rel = str(path.relative_to(VAULT_ROOT))
                    hits.append(rel)
                    if len(hits) >= limit:
                        return hits
            except OSError:
                log.debug("vault note read failed: %s", path, exc_info=True)
    return hits


# --- Per-role resolvers -----------------------------------------------------


def resolve_tier_list(
    topic: str,
    *,
    limit: int = DEFAULT_TIER_LIST_CANDIDATES,
) -> TierListAssets:
    """Pull candidate items + source attributions for a tier-list segment."""
    hits = _qdrant_search("documents", topic, limit=limit)
    return TierListAssets(
        topic=topic,
        candidates=tuple(text for text, _, _ in hits),
        candidate_sources=tuple(source for _, source, _ in hits),
    )


def resolve_top_10(
    topic: str,
    *,
    limit: int = DEFAULT_TOP_10_CANDIDATES,
) -> Top10Assets:
    """Pull ranked candidates for a top-10 countdown segment.

    Reuses the documents collection + relevance score for ranking;
    Qdrant returns highest-score-first so the order is the ranking.
    """
    hits = _qdrant_search("documents", topic, limit=limit)
    return Top10Assets(
        topic=topic,
        ranked_candidates=tuple(text for text, _, _ in hits[:limit]),
        candidate_sources=tuple(source for _, source, _ in hits[:limit]),
    )


def resolve_rant(
    topic: str,
    *,
    limit: int = DEFAULT_RANT_POSITIONS,
) -> RantAssets:
    """Pull operator positions + prior corrections grounding a rant.

    Operator profile + corrections are the two collections the rant
    composer must never invent past. Both fail open to empty tuples.
    """
    positions = _qdrant_search("profile-facts", topic, limit=limit)
    corrections = _qdrant_search("operator-corrections", topic, limit=limit)
    return RantAssets(
        topic=topic,
        operator_positions=tuple(text for text, _, _ in positions),
        prior_corrections=tuple(text for text, _, _ in corrections),
    )


def resolve_react(source_uri: str) -> ReactAssets:
    """Resolve a source URI through the content-resolver daemon.

    The content-resolver is the canonical pipe for external media
    (URLs, video clips, document references). On failure we surface
    the URI itself so the narrative composer can still announce the
    intended source while flagging that resolution failed.
    """
    if not source_uri.strip():
        return ReactAssets(source_uri=source_uri, resolution_failed=True)
    try:
        from agents.content_resolver_client import resolve as resolve_external
    except ImportError:
        log.debug("content_resolver_client unavailable; returning passthrough")
        return ReactAssets(source_uri=source_uri, resolution_failed=True)
    try:
        result = resolve_external(source_uri)
    except Exception:
        log.debug("content_resolver call failed for %s", source_uri, exc_info=True)
        return ReactAssets(source_uri=source_uri, resolution_failed=True)
    if result is None:
        return ReactAssets(source_uri=source_uri, resolution_failed=True)
    return ReactAssets(
        source_uri=source_uri,
        resolved_title=getattr(result, "title", None) or _maybe_get(result, "title"),
        resolved_excerpt=(getattr(result, "excerpt", None) or _maybe_get(result, "excerpt")),
        chapter_markers=tuple(
            getattr(result, "chapter_markers", None)
            or _maybe_get(result, "chapter_markers", default=())
            or ()
        ),
    )


def resolve_iceberg(
    topic: str,
    *,
    layers: int = DEFAULT_ICEBERG_LAYERS,
) -> IcebergAssets:
    """Build a layered outline from surface RAG → vault → operator edge.

    Layer 1 (surface): documents-collection RAG hits — common knowledge.
    Layer 2 (vault notes): operator's 30-areas notes for this topic.
    Layer 3 (specialized): operator's 20-projects notes (projects encode
    the operator's edge thinking — current research lines, custom
    rigs, in-flight work).
    Layer 4+ (deepest): falls through to specialised resources.

    With ``layers < 4`` we drop the deepest layers first, preserving the
    surface-to-vault gradient.
    """
    surface = [text for text, _, _ in _qdrant_search("documents", topic, limit=4)]
    areas = _vault_notes_for_topic(topic, roots=(VAULT_AREAS,), limit=4)
    projects = _vault_notes_for_topic(topic, roots=(VAULT_PROJECTS,), limit=4)
    resources = _vault_notes_for_topic(topic, roots=(VAULT_RESOURCES,), limit=4)
    full_layers: list[tuple[str, ...]] = [
        tuple(surface),
        tuple(areas),
        tuple(projects),
        tuple(resources),
    ]
    return IcebergAssets(topic=topic, layers=tuple(full_layers[:layers]))


def resolve_interview(
    subject: str,
    *,
    limit: int = DEFAULT_INTERVIEW_PREP_HITS,
) -> InterviewAssets:
    """Prep an interview against the named subject.

    Pulls subject-relevant material from documents + profile-facts
    (operator positions on or about the subject). ``prior_interaction_refs``
    is left as a placeholder for the consent-gated prior-conversation
    pull when the subject is a vault-resident voice; today it returns
    empty (consent infrastructure governs the future hook).
    """
    prep = _qdrant_search("documents", subject, limit=limit)
    profile_hits = _qdrant_search("profile-facts", subject, limit=limit)
    return InterviewAssets(
        subject=subject,
        prep_hits=tuple(text for text, _, _ in prep + profile_hits),
        prior_interaction_refs=(),
    )


def resolve_lecture(
    topic: str,
    *,
    limit: int = DEFAULT_LECTURE_OUTLINE_NOTES,
) -> LectureAssets:
    """Build an outline-friendly asset bundle for a lecture programme.

    Vault notes are preferred; RAG hits backstop when the vault is
    silent. The narrative composer is expected to cite vault notes by
    relative path inline so the lecture stays grounded.
    """
    notes = _vault_notes_for_topic(topic, roots=(VAULT_AREAS, VAULT_PROJECTS), limit=limit)
    rag_hits: list[str] = []
    if not notes:
        rag_hits = [text for text, _, _ in _qdrant_search("documents", topic, limit=limit)]
    return LectureAssets(
        topic=topic,
        outline_notes=tuple(notes),
        rag_fallbacks=tuple(rag_hits),
    )


# --- Unified entry point ----------------------------------------------------


def resolve_assets(
    role: str,
    topic: str | None = None,
    *,
    source_uri: str | None = None,
    subject: str | None = None,
) -> ProgrammeAssets | None:
    """Dispatch to the per-role resolver based on ``role``.

    Returns ``None`` for non-segmented-content roles (the operator-
    context roles ground in real-time activity, not declared topics).
    Callers in the planner / narrative composer can branch on ``None``
    to skip asset acquisition for those programmes.
    """
    role_value = getattr(role, "value", role)
    if role_value == "tier_list":
        return resolve_tier_list(topic or "")
    if role_value == "top_10":
        return resolve_top_10(topic or "")
    if role_value == "rant":
        return resolve_rant(topic or "")
    if role_value == "react":
        return resolve_react(source_uri or topic or "")
    if role_value == "iceberg":
        return resolve_iceberg(topic or "")
    if role_value == "interview":
        return resolve_interview(subject or topic or "")
    if role_value == "lecture":
        return resolve_lecture(topic or "")
    return None


# --- Helpers ----------------------------------------------------------------


def _maybe_get(obj: Any, key: str, *, default: Any = None) -> Any:
    """Read a dict-or-attr value, defensive to either shape."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)
