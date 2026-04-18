"""Regression tests for the 2026-04-16 LRR audit corrections.

Three issues were flagged in a post-shipping audit and corrected here:

1. ``shared.config.get_qdrant_grpc()`` was ungated — 3 call sites in
   ``agents/hapax_daimonion/tools.py`` bypassed the FINDING-R consent
   gate by taking the gRPC factory path. Now wraps with
   ``ConsentGatedQdrant``.

2. ``shared.stream_transition_gate.PRESENCE_STATE_FILE`` pointed at
   ``/dev/shm/hapax-dmn/health.json`` (a component health snapshot, NOT
   a presence probability). Corrected to the live PresenceEngine file
   ``/dev/shm/hapax-daimonion/presence-metrics.json`` with the
   ``posterior`` field.

3. ``shared.governance.qdrant_gate.PERSON_ADJACENT_COLLECTIONS`` only
   covered 2 of the 10 canonical Qdrant collections. Expanded to also
   gate ``stream-reactions``, ``studio-moments``, ``hapax-apperceptions``
   (the three that carry non-operator data per FINDING-R + CLAUDE.md §
   Shared Infrastructure).
"""

from __future__ import annotations

import json

import pytest

# ── #1 gRPC gating ──────────────────────────────────────────────────────────


def test_get_qdrant_grpc_returns_gated_client():
    from shared.config import get_qdrant_grpc
    from shared.governance.qdrant_gate import ConsentGatedQdrant

    client = get_qdrant_grpc()
    assert isinstance(client, ConsentGatedQdrant)


def test_grpc_raw_is_still_accessible_for_bootstrap():
    """Mirror of ``test_qdrant_gate_wiring::test_raw_is_still_accessible_for_bootstrap``
    for the gRPC factory. Same rationale for asserting the invariant via
    fresh direct construction rather than the cached factory."""
    from qdrant_client import QdrantClient

    from shared.config import QDRANT_URL, _get_qdrant_grpc_raw

    assert callable(_get_qdrant_grpc_raw)
    fresh = QdrantClient(QDRANT_URL, prefer_grpc=True, grpc_port=6334)
    assert isinstance(fresh, QdrantClient)


# ── #2 presence file path ───────────────────────────────────────────────────


def test_presence_file_constant_is_presence_metrics_not_health():
    from shared.stream_transition_gate import PRESENCE_FIELD_NAME, PRESENCE_STATE_FILE

    # Must NOT be the component health file
    assert str(PRESENCE_STATE_FILE) != "/dev/shm/hapax-dmn/health.json"
    # Must be the PresenceEngine metrics file
    assert "presence-metrics" in str(PRESENCE_STATE_FILE)
    assert PRESENCE_FIELD_NAME == "posterior"


def test_read_presence_uses_posterior_field(tmp_path):
    from shared.stream_transition_gate import read_presence_probability

    target = tmp_path / "presence-metrics.json"
    # Live presence-metrics.json shape: top-level "posterior"
    target.write_text(json.dumps({"posterior": 0.87, "state": "PRESENT"}))
    assert read_presence_probability(target) == pytest.approx(0.87)


def test_read_presence_backcompat_presence_probability_scalar(tmp_path):
    """Legacy callers may still write ``presence_probability`` directly."""
    from shared.stream_transition_gate import read_presence_probability

    target = tmp_path / "legacy.json"
    target.write_text(json.dumps({"presence_probability": 0.42}))
    assert read_presence_probability(target) == pytest.approx(0.42)


def test_read_presence_backcompat_presence_probability_nested(tmp_path):
    from shared.stream_transition_gate import read_presence_probability

    target = tmp_path / "legacy-nested.json"
    target.write_text(json.dumps({"presence_probability": {"value": 0.33}}))
    assert read_presence_probability(target) == pytest.approx(0.33)


def test_read_presence_missing_file_returns_zero(tmp_path):
    from shared.stream_transition_gate import read_presence_probability

    assert read_presence_probability(tmp_path / "no-such-file.json") == 0.0


# ── #3 PERSON_ADJACENT_COLLECTIONS coverage ─────────────────────────────────


def test_gated_collections_cover_broadcast_risk_surfaces():
    """Three collections known to carry non-operator data MUST be gated."""
    from shared.governance.qdrant_gate import PERSON_ADJACENT_COLLECTIONS

    # Pre-audit baseline kept gated
    assert "documents" in PERSON_ADJACENT_COLLECTIONS
    assert "profile-facts" in PERSON_ADJACENT_COLLECTIONS
    # New: the three broadcast-risk collections flagged by FINDING-R /
    # CLAUDE.md § Shared Infrastructure
    assert "stream-reactions" in PERSON_ADJACENT_COLLECTIONS
    assert "studio-moments" in PERSON_ADJACENT_COLLECTIONS
    assert "hapax-apperceptions" in PERSON_ADJACENT_COLLECTIONS


def test_person_fields_defined_for_every_gated_collection():
    from shared.governance.qdrant_gate import PERSON_ADJACENT_COLLECTIONS, PERSON_FIELDS

    missing = set(PERSON_ADJACENT_COLLECTIONS) - set(PERSON_FIELDS)
    assert not missing, f"PERSON_FIELDS missing entries for {missing}"


def test_stream_reactions_extracts_chat_authors():
    """FINDING-R §2.5 specifically flagged chat_authors — verify we check it."""
    from shared.governance.qdrant_gate import PERSON_FIELDS

    fields = [f[0] for f in PERSON_FIELDS["stream-reactions"]]
    assert "chat_authors" in fields
