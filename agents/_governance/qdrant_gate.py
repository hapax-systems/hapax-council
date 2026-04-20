"""Consent-gated Qdrant writer — intercepts upserts for person-adjacent collections.

Extends the single-chokepoint property (ConsentGatedWriter for filesystem,
ConsentGatedQdrant for vector DB) to cover all persistent data stores.

Every upsert to a person-adjacent collection passes through this gate:
1. Extract person IDs from point payloads
2. Check each non-operator person against ConsentRegistry
3. Allow or curtail the write with structured audit

Collections are classified as person-adjacent or exempt. Exempt collections
(operator-only data) pass through without checks. Person-adjacent collections
have payload fields that may contain person identifiers.

Dependencies: qdrant-client, pyyaml only (no pydantic-ai — must work in ingest venv).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# RFC 5322 simplified — matches most real-world email addresses
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


# ── Collection classification ────────────────────────────────────────────────

# Collections that may contain person-adjacent data, mapped to their consent
# data category. Upserts to these collections are consent-checked.
PERSON_ADJACENT_COLLECTIONS: dict[str, str] = {
    "documents": "document",
    "profile-facts": "document",
}

# Payload fields checked for person identifiers, per collection.
# Each tuple: (field_name, extraction_mode) where mode is "direct" or "list".
PERSON_FIELDS: dict[str, list[tuple[str, str]]] = {
    "documents": [
        ("people", "list"),
        ("attendees", "list"),
        ("from", "direct"),
        ("to", "direct"),
        ("sender", "direct"),
        ("organizer", "direct"),
    ],
    "profile-facts": [
        ("audience_key", "direct"),
        ("audience_name", "direct"),
    ],
}

# Operator identifiers that are always permitted (never consent-checked).
DEFAULT_OPERATOR_IDS: frozenset[str] = frozenset({"operator", "hapax"})


@dataclass(frozen=True)
class QdrantGateDecision:
    """Result of a consent gate check on a Qdrant upsert."""

    allowed: bool
    reason: str
    collection: str
    point_count: int
    curtailed_count: int = 0
    person_ids_found: tuple[str, ...] = ()
    unconsented: tuple[str, ...] = ()
    timestamp: str = ""


@dataclass
class ConsentGatedQdrant:
    """Consent-checking proxy for Qdrant upsert operations.

    Wraps a QdrantClient and intercepts upsert() calls for person-adjacent
    collections. Points with unconsented person IDs are removed from the
    batch before upserting. Points in exempt collections pass through.

    Usage:
        from .qdrant_gate import ConsentGatedQdrant
        gated = ConsentGatedQdrant(inner_client)
        gated.upsert(collection, points)  # consent-checked
        gated.inner.scroll(...)           # direct access for reads
    """

    inner: Any  # QdrantClient — typed as Any to avoid import dependency
    _operator_ids: frozenset[str] = field(default_factory=lambda: DEFAULT_OPERATOR_IDS)
    _audit_path: Path | None = None
    _decisions: list[QdrantGateDecision] = field(default_factory=list)
    _contract_check: Any = None  # Callable[[str, str], bool] — lazy loaded

    def _get_contract_check(self) -> Any:
        """Lazily load the contract check function."""
        if self._contract_check is not None:
            return self._contract_check
        try:
            from .consent import load_contracts

            registry = load_contracts()
            self._contract_check = registry.contract_check
            return self._contract_check
        except Exception:
            log.warning("Could not load consent registry for Qdrant gate", exc_info=True)
            # Fail-closed: deny all person-adjacent writes if registry unavailable
            return lambda person_id, category: False

    def upsert(
        self,
        collection_name: str,
        points: Any,
        **kwargs: Any,
    ) -> Any:
        """Consent-gated upsert. Filters unconsented points from person-adjacent collections."""
        if collection_name not in PERSON_ADJACENT_COLLECTIONS:
            return self.inner.upsert(collection_name, points, **kwargs)

        category = PERSON_ADJACENT_COLLECTIONS[collection_name]
        fields = PERSON_FIELDS.get(collection_name, [])
        check = self._get_contract_check()

        allowed_points = []
        curtailed = 0
        all_person_ids: set[str] = set()
        all_unconsented: set[str] = set()

        for point in points:
            payload = getattr(point, "payload", None) or {}
            person_ids = _extract_person_ids(payload, fields)
            all_person_ids.update(person_ids)

            # Check consent for each non-operator person
            unconsented = set()
            for pid in person_ids:
                if pid in self._operator_ids:
                    continue
                if not check(pid, category):
                    unconsented.add(pid)

            if unconsented:
                curtailed += 1
                all_unconsented.update(unconsented)
                log.info(
                    "Qdrant gate: CURTAILED point in %s — unconsented: %s",
                    collection_name,
                    sorted(unconsented),
                )
            else:
                allowed_points.append(point)

        now = datetime.now(UTC).isoformat()
        decision = QdrantGateDecision(
            allowed=len(allowed_points) > 0,
            reason="All points consented" if curtailed == 0 else f"{curtailed} points curtailed",
            collection=collection_name,
            point_count=len(points),
            curtailed_count=curtailed,
            person_ids_found=tuple(sorted(all_person_ids)),
            unconsented=tuple(sorted(all_unconsented)),
            timestamp=now,
        )
        self._decisions.append(decision)
        self._audit(decision)

        # Set context var for implicit tracking (AD-8)
        try:
            from .gate_token import GateToken, set_gate_token

            token = GateToken._mint(
                allowed=decision.allowed,
                reason=decision.reason,
                data_category=category,
                person_ids=decision.person_ids_found,
                gate_id=f"qdrant:{collection_name}",
            )
            set_gate_token(token)
        except Exception:
            pass

        if not allowed_points:
            log.info(
                "Qdrant gate: ALL points curtailed for %s (%d points)",
                collection_name,
                len(points),
            )
            return None

        if curtailed > 0:
            log.info(
                "Qdrant gate: %d of %d points allowed for %s",
                len(allowed_points),
                len(points),
                collection_name,
            )

        return self.inner.upsert(collection_name, allowed_points, **kwargs)

    def set_payload(
        self,
        collection_name: str,
        payload: dict[str, Any],
        points: Any,
        **kwargs: Any,
    ) -> Any:
        """Consent-gated set_payload. Checks person IDs in the new payload."""
        if collection_name not in PERSON_ADJACENT_COLLECTIONS:
            return self.inner.set_payload(collection_name, payload=payload, points=points, **kwargs)

        category = PERSON_ADJACENT_COLLECTIONS[collection_name]
        fields = PERSON_FIELDS.get(collection_name, [])
        check = self._get_contract_check()

        person_ids = _extract_person_ids(payload, fields)
        unconsented = set()
        for pid in person_ids:
            if pid in self._operator_ids:
                continue
            if not check(pid, category):
                unconsented.add(pid)

        if unconsented:
            now = datetime.now(UTC).isoformat()
            decision = QdrantGateDecision(
                allowed=False,
                reason=f"Payload contains unconsented persons: {sorted(unconsented)}",
                collection=collection_name,
                point_count=1,
                curtailed_count=1,
                person_ids_found=tuple(sorted(person_ids)),
                unconsented=tuple(sorted(unconsented)),
                timestamp=now,
            )
            self._decisions.append(decision)
            self._audit(decision)
            try:
                from .gate_token import GateToken, set_gate_token

                set_gate_token(
                    GateToken._mint(
                        allowed=False,
                        reason=decision.reason,
                        data_category=category,
                        gate_id=f"qdrant:{collection_name}",
                    )
                )
            except Exception:
                pass
            log.info(
                "Qdrant gate: CURTAILED set_payload on %s — unconsented: %s",
                collection_name,
                sorted(unconsented),
            )
            return None

        return self.inner.set_payload(collection_name, payload=payload, points=points, **kwargs)

    def delete(self, collection_name: str, **kwargs: Any) -> Any:
        """Passthrough — deletes are always allowed (support revocation purge)."""
        return self.inner.delete(collection_name, **kwargs)

    # --- Read-side mental-state redaction (#208 dead-bridge wiring) ----

    def _redact_points(self, collection_name: str, points: Any) -> Any:
        """Apply mental-state redaction to a read result when applicable.

        Lazy-import + lazy-redact so callers paying for ConsentGatedQdrant
        already get the read-side gate with no extra import on their end.
        Points that are not dicts (or whose payload isn't a dict) pass
        through — the redactor handles that shape-check itself.
        """
        if not points:
            return points
        try:
            from shared.governance.mental_state_redaction import (
                is_mental_state_collection,
                redact_query_result,
            )
        except Exception as import_err:
            # D-24 §8.5 (AUDIT fix): a mental-state collection read must
            # NEVER silently pass through un-redacted. If the redactor is
            # unimportable, refuse the read — fail-closed is the governance-
            # correct behaviour. Non-mental-state collections are allowed to
            # pass (nothing to redact there) so this function still runs
            # that cheap check first... but we can't tell which kind of
            # collection this is without is_mental_state_collection(). The
            # safe call: raise, and let the caller decide whether to
            # treat it as a cache-miss.
            log.error(
                "mental_state_redaction unavailable for collection %s — "
                "fail-closed per governance; refusing read",
                collection_name,
            )
            raise RuntimeError(
                f"mental_state_redaction module unavailable; cannot safely "
                f"read collection {collection_name!r}"
            ) from import_err
        if not is_mental_state_collection(collection_name):
            return points
        # redact_query_result expects a list of dicts. Qdrant's ScoredPoint
        # objects carry a .payload attribute rather than a dict key — convert
        # to dict shape, redact, convert back by writing to .payload.
        redacted = []
        for pt in points:
            if hasattr(pt, "payload") and isinstance(pt.payload, dict):
                as_dict = {"payload": pt.payload}
                new_payload = redact_query_result(collection_name, [as_dict])[0]["payload"]
                # Mutate in-place so downstream consumers see the redacted
                # view even if they held a reference before this call.
                pt.payload = new_payload
                redacted.append(pt)
            elif isinstance(pt, dict):
                redacted.extend(redact_query_result(collection_name, [pt]))
            else:
                redacted.append(pt)
        return redacted

    def search(self, collection_name: str, *args: Any, **kwargs: Any) -> Any:
        """Consent-gated search + mental-state read redaction."""
        result = self.inner.search(collection_name, *args, **kwargs)
        return self._redact_points(collection_name, result)

    def scroll(self, collection_name: str, *args: Any, **kwargs: Any) -> Any:
        """Consent-gated scroll + mental-state read redaction.

        Qdrant scroll returns ``(points, next_offset)``; redact only the
        first tuple element.
        """
        result = self.inner.scroll(collection_name, *args, **kwargs)
        if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], list):
            return (self._redact_points(collection_name, result[0]), result[1])
        return self._redact_points(collection_name, result)

    def retrieve(self, collection_name: str, *args: Any, **kwargs: Any) -> Any:
        """Consent-gated retrieve + mental-state read redaction."""
        result = self.inner.retrieve(collection_name, *args, **kwargs)
        return self._redact_points(collection_name, result)

    def query_points(self, collection_name: str, *args: Any, **kwargs: Any) -> Any:
        """Consent-gated query_points + mental-state read redaction.

        Qdrant's newer query_points API returns a ``QueryResponse`` with a
        ``.points`` attribute. Redact that attribute in-place and return
        the response.
        """
        result = self.inner.query_points(collection_name, *args, **kwargs)
        if hasattr(result, "points"):
            result.points = self._redact_points(collection_name, result.points)
        return result

    def reload_contracts(self) -> None:
        """Force reload of consent registry (after new contract created)."""
        self._contract_check = None

    @property
    def decisions(self) -> list[QdrantGateDecision]:
        return list(self._decisions)

    def __getattr__(self, name: str) -> Any:
        """Proxy all other methods to inner client (search, scroll, etc.)."""
        return getattr(self.inner, name)

    def _audit(self, decision: QdrantGateDecision) -> None:
        """Write decision to audit log if configured."""
        if not self._audit_path:
            return
        try:
            self._audit_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._audit_path, "a") as f:
                entry = {
                    "timestamp": decision.timestamp,
                    "allowed": decision.allowed,
                    "reason": decision.reason,
                    "collection": decision.collection,
                    "point_count": decision.point_count,
                    "curtailed_count": decision.curtailed_count,
                    "unconsented_count": len(decision.unconsented),
                }
                f.write(json.dumps(entry) + "\n")
        except Exception:
            log.debug("Failed to write Qdrant gate audit log", exc_info=True)


# ── Person ID extraction from Qdrant payloads ────────────────────────────────


def _extract_person_ids(
    payload: dict[str, Any],
    fields: list[tuple[str, str]],
) -> frozenset[str]:
    """Extract person identifiers from a Qdrant point payload.

    Checks configured fields for person identifiers. Also scans text
    fields for email addresses (high precision, low cost).
    """
    ids: set[str] = set()

    for field_name, mode in fields:
        val = payload.get(field_name)
        if val is None:
            continue

        if mode == "list" and isinstance(val, list):
            ids.update(str(v) for v in val if v)
        elif mode == "direct" and isinstance(val, str) and val:
            # Check if it's an email
            emails = _EMAIL_RE.findall(val)
            if emails:
                ids.update(emails)
            else:
                ids.add(val)

    # Also scan the "text" field for emails if present (ingest.py stores chunk text)
    text = payload.get("text", "")
    if isinstance(text, str) and text:
        ids.update(_EMAIL_RE.findall(text))

    return frozenset(ids)


def purge_qdrant_by_person(
    client: Any,
    person_id: str,
    collections: list[str] | None = None,
) -> int:
    """Purge all Qdrant points containing data about a specific person.

    Scans person-adjacent collections for points whose payload contains
    the person_id in any person-identifying field, and deletes them.

    Returns total number of points purged across all collections.
    """
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    target_collections = collections or list(PERSON_ADJACENT_COLLECTIONS.keys())
    total_purged = 0

    for collection in target_collections:
        fields = PERSON_FIELDS.get(collection, [])
        if not fields:
            continue

        for field_name, mode in fields:
            try:
                if mode == "list":
                    # For list fields, match any element containing person_id
                    qfilter = Filter(
                        must=[FieldCondition(key=field_name, match=MatchValue(value=person_id))]
                    )
                else:
                    # For direct fields, exact match
                    qfilter = Filter(
                        must=[FieldCondition(key=field_name, match=MatchValue(value=person_id))]
                    )

                # Paginated scroll to find ALL matching points
                from qdrant_client.models import PointIdsList

                offset = None
                while True:
                    results = client.scroll(
                        collection_name=collection,
                        scroll_filter=qfilter,
                        limit=1000,
                        offset=offset,
                    )
                    points, next_offset = results
                    if not points:
                        break
                    point_ids = [p.id for p in points]
                    client.delete(
                        collection_name=collection,
                        points_selector=PointIdsList(points=point_ids),
                    )
                    total_purged += len(point_ids)
                    log.info(
                        "Qdrant purge: deleted %d points from %s (field=%s, person=%s)",
                        len(point_ids),
                        collection,
                        field_name,
                        person_id,
                    )
                    if next_offset is None:
                        break
                    offset = next_offset
            except Exception:
                log.warning(
                    "Qdrant purge failed for %s/%s/%s",
                    collection,
                    field_name,
                    person_id,
                    exc_info=True,
                )

    return total_purged
