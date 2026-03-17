"""Tests for GateToken linear discipline — consent formalism #4.

Verifies token creation, unforgeability, audit serialization,
and the require_token structural enforcement pattern.
"""

from __future__ import annotations

import pytest

from shared.governance.gate_token import GateToken, require_token


class TestGateTokenCreation:
    def test_mint_allow(self):
        token = GateToken._mint(
            allowed=True,
            reason="All consent checks passed",
            data_category="behavioral",
            person_ids=("alice",),
            provenance=("c1",),
            gate_id="gate-1",
        )
        assert token.is_allow is True
        assert token.is_deny is False
        assert token.data_category == "behavioral"
        assert len(token.nonce) == 32  # 16 bytes hex

    def test_mint_deny(self):
        token = GateToken._mint(
            allowed=False,
            reason="No contract for alice",
            gate_id="gate-1",
        )
        assert token.is_deny is True
        assert token.is_allow is False

    def test_unique_nonces(self):
        """Each token gets a unique nonce."""
        tokens = [
            GateToken._mint(allowed=True, reason="ok", gate_id="g")
            for _ in range(100)
        ]
        nonces = {t.nonce for t in tokens}
        assert len(nonces) == 100

    def test_frozen(self):
        """Tokens are immutable."""
        token = GateToken._mint(allowed=True, reason="ok", gate_id="g")
        with pytest.raises(Exception):
            token.allowed = False  # type: ignore[misc]

    def test_timestamp_populated(self):
        import time

        before = time.time()
        token = GateToken._mint(allowed=True, reason="ok", gate_id="g")
        after = time.time()
        assert before <= token.timestamp <= after


class TestAuditSerialization:
    def test_audit_dict(self):
        token = GateToken._mint(
            allowed=True,
            reason="All checks passed",
            data_category="behavioral",
            person_ids=("alice", "bob"),
            provenance=("c1", "c2"),
            gate_id="gate-main",
        )
        d = token.audit_dict()
        assert d["allowed"] is True
        assert d["reason"] == "All checks passed"
        assert d["person_ids"] == ["alice", "bob"]
        assert d["provenance"] == ["c1", "c2"]
        assert d["gate_id"] == "gate-main"
        assert "nonce" in d
        assert "timestamp" in d

    def test_audit_dict_json_serializable(self):
        import json

        token = GateToken._mint(allowed=True, reason="ok", gate_id="g")
        json.dumps(token.audit_dict())  # should not raise


class TestRequireToken:
    def test_require_allow_token_passes(self):
        token = GateToken._mint(allowed=True, reason="ok", gate_id="g")
        require_token(token)  # should not raise

    def test_require_deny_token_raises(self):
        token = GateToken._mint(allowed=False, reason="No contract", gate_id="g")
        with pytest.raises(ValueError, match="No contract"):
            require_token(token)

    def test_require_deny_token_with_must_allow_false(self):
        """With must_allow=False, deny tokens are accepted."""
        token = GateToken._mint(allowed=False, reason="denied", gate_id="g")
        require_token(token, must_allow=False)  # should not raise

    def test_structural_enforcement_pattern(self):
        """Demonstrate the structural enforcement pattern."""

        def persist_data(data: str, token: GateToken) -> str:
            """Function that structurally requires consent proof."""
            require_token(token)
            return f"persisted: {data}"

        # With valid token: works
        good_token = GateToken._mint(allowed=True, reason="ok", gate_id="g")
        assert persist_data("hello", good_token) == "persisted: hello"

        # With denied token: structural rejection
        bad_token = GateToken._mint(allowed=False, reason="no consent", gate_id="g")
        with pytest.raises(ValueError):
            persist_data("hello", bad_token)
