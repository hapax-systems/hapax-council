"""Hermeneutic spiral persistence — accumulated fore-understanding across prep cycles.

Persists source-consequence maps to the ``source-consequences`` Qdrant
collection so each prep cycle's interpretive encounters inform the next.
Closes gap 1.10/2.4: the hermeneutic circle was one-turn.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

_log = logging.getLogger(__name__)

COLLECTION_NAME = "source-consequences"
SCHEMA_VERSION = 1
_MAX_PRIOR_RESULTS = 30
_EMBED_PREFIX_DOCUMENT = "search_document"
_EMBED_PREFIX_QUERY = "search_query"

type ConsequenceKind = Literal[
    "ranking_or_order_changed",
    "visible_or_layout_obligation_changed",
    "scope_or_refusal_changed",
    "claim_shape_changed",
    "scope_confidence_or_action_delta",
]
type DeltaKind = Literal[
    "new_consequence",
    "reinforced_consequence",
    "revised_consequence",
    "novel_dimension",
]


class HermeneuticDelta(BaseModel):
    """What a prep cycle revealed about the system's commitments or blind spots."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    delta_id: str
    programme_id: str
    role: str
    topic: str
    cycle_timestamp: datetime
    delta_kind: DeltaKind
    source_ref: str
    consequence_kind: ConsequenceKind
    changed_dimensions: tuple[str, ...] = Field(default_factory=tuple)
    prior_encounter_ids: tuple[str, ...] = Field(default_factory=tuple)
    summary: str


def _point_id(programme_id: str, source_ref: str, beat_index: int) -> str:
    seed = f"source-consequence:{programme_id}:{source_ref}:{beat_index}"
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, seed))


def _embed_text(entry: Mapping[str, Any], *, topic: str, role: str) -> str:
    consequence = entry.get("consequence", "")
    source_ref = entry.get("source_ref", "")
    dims = ", ".join(entry.get("changed_dimensions", []))
    return (
        f"Source consequence for {role} segment on {topic}: "
        f"{source_ref} caused {consequence} affecting {dims}"
    )


def persist_source_consequences(
    source_consequence_map: Sequence[Mapping[str, Any]],
    *,
    programme_id: str,
    role: str,
    topic: str,
    prep_session_id: str,
) -> int:
    """Persist source-consequence map entries to Qdrant.

    Returns the number of points upserted (0 on empty map or embedding failure).
    """
    if not source_consequence_map:
        return 0

    try:
        from qdrant_client.models import PointStruct

        from shared.config import embed_batch_safe, get_qdrant
    except Exception:
        _log.warning("persist_source_consequences: qdrant/embedding deps unavailable")
        return 0

    now = datetime.now(tz=UTC).isoformat()
    texts: list[str] = []
    payloads: list[dict[str, Any]] = []
    point_ids: list[str] = []

    for entry in source_consequence_map:
        if not isinstance(entry, Mapping):
            continue
        beat_index = entry.get("beat_index", 0)
        source_ref = str(entry.get("source_ref", ""))
        if not source_ref:
            continue

        texts.append(_embed_text(entry, topic=topic, role=role))
        point_ids.append(_point_id(programme_id, source_ref, beat_index))
        payloads.append(
            {
                "schema_version": SCHEMA_VERSION,
                "programme_id": programme_id,
                "role": role,
                "topic": topic,
                "beat_index": beat_index,
                "source_ref": source_ref,
                "evidence_ref": entry.get("evidence_ref", ""),
                "consequence_kind": entry.get("consequence", "claim_shape_changed"),
                "changed_dimensions": entry.get("changed_dimensions", []),
                "prep_session_id": prep_session_id,
                "persisted_at": now,
            }
        )

    embeddings = embed_batch_safe(texts, prefix=_EMBED_PREFIX_DOCUMENT)
    if embeddings is None:
        _log.warning("persist_source_consequences: embedding failed, skipping persistence")
        return 0

    points: list[PointStruct] = []
    for pid, vector, payload in zip(point_ids, embeddings, payloads, strict=True):
        if vector is None:
            continue
        points.append(PointStruct(id=pid, vector=vector, payload=payload))

    if not points:
        return 0

    try:
        get_qdrant().upsert(collection_name=COLLECTION_NAME, points=points)
        _log.info(
            "persist_source_consequences: upserted %d points for %s", len(points), programme_id
        )
        return len(points)
    except Exception:
        _log.exception("persist_source_consequences: upsert failed")
        return 0


def retrieve_fore_understanding(
    *,
    topic: str,
    role: str,
    limit: int = _MAX_PRIOR_RESULTS,
) -> list[dict[str, Any]]:
    """Retrieve accumulated prior source-consequence encounters for a topic/role.

    Returns payload dicts from prior cycles, newest first.
    """
    try:
        from shared.config import embed, get_qdrant
    except Exception:
        _log.warning("retrieve_fore_understanding: deps unavailable")
        return []

    query_text = f"Source consequences for {role} segment on {topic}"
    try:
        vector = embed(query_text, prefix=_EMBED_PREFIX_QUERY)
    except Exception:
        _log.warning("retrieve_fore_understanding: embedding failed")
        return []

    try:
        client = get_qdrant()
        results = client.query_points(
            collection_name=COLLECTION_NAME,
            query=vector,
            limit=limit,
            with_payload=True,
        )
        priors = []
        for point in results.points:
            payload = dict(point.payload) if point.payload else {}
            payload["_point_id"] = str(point.id)
            payload["_score"] = point.score
            priors.append(payload)
        return priors
    except Exception:
        _log.warning("retrieve_fore_understanding: query failed")
        return []


def compute_hermeneutic_delta(
    current_map: Sequence[Mapping[str, Any]],
    prior_encounters: Sequence[Mapping[str, Any]],
    *,
    programme_id: str,
    role: str,
    topic: str,
) -> list[HermeneuticDelta]:
    """Compare current cycle's consequences against accumulated priors.

    Produces delta records that capture what this cycle revealed: new
    consequences never seen before, reinforced patterns, revised
    interpretations, or novel dimension coverage.
    """
    now = datetime.now(tz=UTC)
    deltas: list[HermeneuticDelta] = []

    prior_by_source: dict[str, list[Mapping[str, Any]]] = {}
    for prior in prior_encounters:
        src = str(prior.get("source_ref", ""))
        if src:
            prior_by_source.setdefault(src, []).append(prior)

    prior_dims: set[str] = set()
    for prior in prior_encounters:
        for dim in prior.get("changed_dimensions", []):
            prior_dims.add(dim)

    for entry in current_map:
        if not isinstance(entry, Mapping):
            continue
        source_ref = str(entry.get("source_ref", ""))
        if not source_ref:
            continue

        consequence_kind = entry.get("consequence", "claim_shape_changed")
        changed_dims = tuple(entry.get("changed_dimensions", []))
        matching_priors = prior_by_source.get(source_ref, [])

        if not matching_priors:
            novel_dims = [d for d in changed_dims if d not in prior_dims]
            if novel_dims and prior_dims:
                delta_kind: DeltaKind = "novel_dimension"
            else:
                delta_kind = "new_consequence"
            prior_ids: tuple[str, ...] = ()
        else:
            prior_kinds = {str(p.get("consequence_kind", "")) for p in matching_priors}
            prior_ids = tuple(
                str(p.get("_point_id", "")) for p in matching_priors if p.get("_point_id")
            )
            if consequence_kind in prior_kinds:
                delta_kind = "reinforced_consequence"
            else:
                delta_kind = "revised_consequence"

        beat_index = entry.get("beat_index", 0)
        delta_id = f"delta:{programme_id}:{source_ref}:{beat_index}:{now.isoformat()}"

        summary = _delta_summary(delta_kind, source_ref, consequence_kind, changed_dims)

        deltas.append(
            HermeneuticDelta(
                delta_id=delta_id,
                programme_id=programme_id,
                role=role,
                topic=topic,
                cycle_timestamp=now,
                delta_kind=delta_kind,
                source_ref=source_ref,
                consequence_kind=consequence_kind,
                changed_dimensions=changed_dims,
                prior_encounter_ids=prior_ids,
                summary=summary,
            )
        )

    return deltas


def _delta_summary(
    delta_kind: DeltaKind,
    source_ref: str,
    consequence_kind: str,
    changed_dims: tuple[str, ...],
) -> str:
    dims_str = ", ".join(changed_dims) if changed_dims else "claim"
    match delta_kind:
        case "new_consequence":
            return f"First encounter: {source_ref} introduced {consequence_kind} on {dims_str}"
        case "reinforced_consequence":
            return f"Reinforced: {source_ref} again caused {consequence_kind} on {dims_str}"
        case "revised_consequence":
            return (
                f"Revised: {source_ref} now causes {consequence_kind} on {dims_str} "
                f"(previously different consequence type)"
            )
        case "novel_dimension":
            return (
                f"Novel dimension: {source_ref} caused {consequence_kind} "
                f"affecting previously unseen {dims_str}"
            )
