"""Change-kind → salience + ``intent_family`` decision table.

Salience drives downstream affordance pipeline reactions when the
impingement enters ``/dev/shm/hapax-dmn/impingements.jsonl``. ntfy
fires only on the ``HIGH_SALIENCE_KINDS`` set so the operator's phone
isn't flooded by every benign visibility flip.

These weights are operator-pain-class signals (Content-ID match,
made-for-kids classification, lifecycle complete, ingest unbind →
1.0 / 0.95). Lower weights (priority change, monetization drift,
visibility) feed Hapax's organic reactions without paging the
operator at sub-second rates.
"""

from __future__ import annotations

# Field-level change kinds. The detector emits one of these per detected
# diff between an old and new snapshot.
KIND_LIFECYCLE_COMPLETE = "youtube_lifecycle_change"
KIND_PRIORITY_CHANGE = "youtube_priority_change"
KIND_INGEST_UNBIND = "youtube_ingest_break"
KIND_MONETIZATION_DRIFT = "youtube_monetization_drift"
KIND_METADATA_YT_EDITED = "youtube_metadata_yt_edited"
KIND_CONTENT_ID_MATCH = "youtube_content_id_match"
KIND_VISIBILITY_CHANGE = "youtube_visibility_change"
KIND_KIDS_CLASSIFICATION_CHANGE = "youtube_kids_classification_change"

ALL_KINDS: tuple[str, ...] = (
    KIND_LIFECYCLE_COMPLETE,
    KIND_PRIORITY_CHANGE,
    KIND_INGEST_UNBIND,
    KIND_MONETIZATION_DRIFT,
    KIND_METADATA_YT_EDITED,
    KIND_CONTENT_ID_MATCH,
    KIND_VISIBILITY_CHANGE,
    KIND_KIDS_CLASSIFICATION_CHANGE,
)

# Salience weights drive affordance recruitment. Operator-pain class at
# 1.0; structural-but-recoverable at 0.7-0.95; informational at 0.4-0.6.
SALIENCE_TABLE: dict[str, float] = {
    KIND_CONTENT_ID_MATCH: 1.0,
    KIND_KIDS_CLASSIFICATION_CHANGE: 1.0,
    KIND_INGEST_UNBIND: 0.95,
    KIND_LIFECYCLE_COMPLETE: 0.9,
    KIND_METADATA_YT_EDITED: 0.85,
    KIND_PRIORITY_CHANGE: 0.7,
    KIND_MONETIZATION_DRIFT: 0.6,
    KIND_VISIBILITY_CHANGE: 0.4,
}

# Impingement intent_family is namespaced under ``egress.`` so Ring 3's
# EgressManifestGate (when shipped) can subscribe by prefix.
INTENT_FAMILY_TABLE: dict[str, str] = {kind: f"egress.{kind}" for kind in ALL_KINDS}

# ntfy fires only on these. Phone alerts should be reserved for events
# where the operator has to *decide* something promptly.
HIGH_SALIENCE_KINDS: frozenset[str] = frozenset(
    {
        KIND_CONTENT_ID_MATCH,
        KIND_KIDS_CLASSIFICATION_CHANGE,
        KIND_LIFECYCLE_COMPLETE,
        KIND_INGEST_UNBIND,
    }
)


def salience_for(kind: str) -> float:
    """Return the salience weight for ``kind``; raises KeyError if unknown."""
    return SALIENCE_TABLE[kind]


def intent_family_for(kind: str) -> str:
    """Return the impingement ``intent_family`` for ``kind``."""
    return INTENT_FAMILY_TABLE[kind]


def is_high_salience(kind: str) -> bool:
    """True when the kind warrants an ntfy alert (not just a bus event)."""
    return kind in HIGH_SALIENCE_KINDS
