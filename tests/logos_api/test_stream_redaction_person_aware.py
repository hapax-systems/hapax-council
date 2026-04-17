"""Tests for LRR Phase 6 §4.A person-aware per-route redaction (batch 2).

Covers the four endpoints whose redaction depends on per-person broadcast
consent (orientation, briefing, nudges, consent/contracts) + the
``references_non_broadcast_person_id`` helper.
"""

from __future__ import annotations

import pytest

# ── Helper: references_non_broadcast_person_id ───────────────────────────────


class _StubContract:
    def __init__(self, parties, active=True, broadcast=False):
        self.parties = parties
        self.active = active
        self._broadcast = broadcast


class _StubRegistry:
    """Minimal stand-in for logos._governance.ConsentRegistry."""

    def __init__(self, contracts):
        self._contracts = contracts

    def __iter__(self):
        return iter(self._contracts)

    def contract_check(self, person_id: str, data_category: str) -> bool:
        for c in self._contracts:
            if not c.active:
                continue
            if person_id in c.parties and data_category == "broadcast" and c._broadcast:
                return True
        return False


class TestReferencesNonBroadcastPersonId:
    def test_no_text_returns_false(self):
        from logos.api.deps.stream_redaction import references_non_broadcast_person_id

        assert references_non_broadcast_person_id("", _StubRegistry([])) is False

    def test_text_without_any_person_id_match(self):
        from logos.api.deps.stream_redaction import references_non_broadcast_person_id

        registry = _StubRegistry([_StubContract(parties=("operator", "wife"), broadcast=False)])
        assert (
            references_non_broadcast_person_id("remind me to buy groceries tomorrow", registry)
            is False
        )

    def test_text_mentions_non_broadcast_person_returns_true(self):
        from logos.api.deps.stream_redaction import references_non_broadcast_person_id

        registry = _StubRegistry([_StubContract(parties=("operator", "wife"), broadcast=False)])
        assert references_non_broadcast_person_id("call wife at 5pm", registry) is True

    def test_text_mentions_broadcast_consented_person_returns_false(self):
        from logos.api.deps.stream_redaction import references_non_broadcast_person_id

        registry = _StubRegistry([_StubContract(parties=("operator", "guest"), broadcast=True)])
        assert references_non_broadcast_person_id("guest joining the stream", registry) is False

    def test_operator_self_reference_ignored(self):
        from logos.api.deps.stream_redaction import references_non_broadcast_person_id

        registry = _StubRegistry([_StubContract(parties=("operator", "wife"), broadcast=False)])
        # operator is self, not a third party — self-reference should not
        # trigger the gate even without a broadcast contract for "operator"
        assert references_non_broadcast_person_id("operator is debugging", registry) is False

    def test_case_insensitive_match(self):
        from logos.api.deps.stream_redaction import references_non_broadcast_person_id

        registry = _StubRegistry([_StubContract(parties=("operator", "wife"), broadcast=False)])
        assert references_non_broadcast_person_id("ping WIFE later", registry) is True


# ── /api/orientation — P0-stale omit + next_action PII redact ────────────────


class TestOrientationRedaction:
    def _orientation_dict(self):
        """Shape matches OrientationState → asdict output."""
        return {
            "session": {},
            "domains": [
                {
                    "domain": "research",
                    "top_goal": {
                        "id": "g1",
                        "title": "Ship Cycle 2 preregistration",
                        "priority": "P0",
                        "status": "active",
                        "stale": True,
                    },
                    "next_action": "email alice@example.com with update",
                },
                {
                    "domain": "personal",
                    "top_goal": {
                        "id": "g2",
                        "title": "Daily practice",
                        "priority": "P1",
                        "status": "active",
                        "stale": False,
                    },
                    "next_action": "read a chapter",
                },
            ],
            "briefing_headline": "nominal",
        }

    @pytest.mark.asyncio
    async def test_private_returns_untouched(self, monkeypatch):
        monkeypatch.setattr("logos.api.routes.orientation.is_publicly_visible", lambda: False)
        import logos.api.routes.orientation as orient_mod

        class _FakeCache:
            orientation = self._orientation_dict()

            def slow_cache_age(self):
                return 0

        monkeypatch.setattr(orient_mod, "cache", _FakeCache())

        # bypass dataclass conversion since we already have a dict
        monkeypatch.setattr(orient_mod, "_to_dict", lambda x: x)

        response = await orient_mod.get_orientation()
        body = response.body
        assert b"Ship Cycle 2" in body  # P0-stale goal preserved
        assert b"alice@example.com" in body  # next_action unredacted

    @pytest.mark.asyncio
    async def test_public_omits_p0_stale_and_redacts_pii(self, monkeypatch):
        monkeypatch.setattr("logos.api.routes.orientation.is_publicly_visible", lambda: True)
        import logos.api.routes.orientation as orient_mod

        class _FakeCache:
            orientation = self._orientation_dict()

            def slow_cache_age(self):
                return 0

        monkeypatch.setattr(orient_mod, "cache", _FakeCache())
        monkeypatch.setattr(orient_mod, "_to_dict", lambda x: x)

        response = await orient_mod.get_orientation()
        body = response.body
        assert b"Ship Cycle 2" not in body  # P0-stale goal dropped
        assert b"alice@example.com" not in body  # email PII-redacted
        assert b"[redacted]" in body
        # P1 goal not P0-stale — preserved
        assert b"Daily practice" in body


# ── /api/briefing — action_items filtered by person_id ───────────────────────


class TestBriefingPersonAwareRedaction:
    def _briefing_dict(self):
        return {
            "headline": "Steady day",
            "action_items": [
                {
                    "priority": "high",
                    "action": "Follow up with wife about weekend",
                    "reason": "calendar conflict",
                },
                {
                    "priority": "medium",
                    "action": "Run pipeline tests",
                    "reason": "CI signal",
                },
            ],
        }

    @pytest.mark.asyncio
    async def test_private_returns_all_items(self, monkeypatch):
        monkeypatch.setattr("logos.api.routes.data.is_publicly_visible", lambda: False)
        import logos.api.routes.data as data_mod

        class _FakeCache:
            briefing = self._briefing_dict()

            def slow_cache_age(self):
                return 0

            def fast_cache_age(self):
                return 0

        monkeypatch.setattr(data_mod, "cache", _FakeCache())
        monkeypatch.setattr(data_mod, "_to_dict", lambda x: x)

        response = await data_mod.get_briefing()
        body = response.body
        assert b"wife" in body
        assert b"Run pipeline tests" in body

    @pytest.mark.asyncio
    async def test_public_omits_person_referencing_items(self, monkeypatch):
        monkeypatch.setattr("logos.api.routes.data.is_publicly_visible", lambda: True)

        def _fake_registry():
            return _StubRegistry([_StubContract(parties=("operator", "wife"), broadcast=False)])

        monkeypatch.setattr("logos.api.routes.data._load_consent_registry", _fake_registry)
        import logos.api.routes.data as data_mod

        class _FakeCache:
            briefing = self._briefing_dict()

            def slow_cache_age(self):
                return 0

            def fast_cache_age(self):
                return 0

        monkeypatch.setattr(data_mod, "cache", _FakeCache())
        monkeypatch.setattr(data_mod, "_to_dict", lambda x: x)

        response = await data_mod.get_briefing()
        body = response.body
        assert b"wife" not in body
        assert b"Run pipeline tests" in body

    @pytest.mark.asyncio
    async def test_public_registry_none_fails_closed(self, monkeypatch):
        """Registry load failure → drop all action_items on broadcast."""
        monkeypatch.setattr("logos.api.routes.data.is_publicly_visible", lambda: True)
        monkeypatch.setattr("logos.api.routes.data._load_consent_registry", lambda: None)
        import logos.api.routes.data as data_mod

        class _FakeCache:
            briefing = self._briefing_dict()

            def slow_cache_age(self):
                return 0

            def fast_cache_age(self):
                return 0

        monkeypatch.setattr(data_mod, "cache", _FakeCache())
        monkeypatch.setattr(data_mod, "_to_dict", lambda x: x)

        response = await data_mod.get_briefing()
        body = response.body
        assert b"action_items" in body
        # all items should be dropped
        assert b"Follow up" not in body
        assert b"Run pipeline tests" not in body


# ── /api/nudges — list filtered by person_id ─────────────────────────────────


class TestNudgesPersonAwareRedaction:
    def _nudges_list(self):
        return [
            {
                "category": "action",
                "title": "Follow up on guest Q",
                "detail": "guest asked about Cycle 2 preregistration during stream",
                "suggested_action": "Reply in chat",
            },
            {
                "category": "briefing",
                "title": "Morning briefing ready",
                "detail": "daily briefing generated",
                "suggested_action": "Review",
            },
        ]

    @pytest.mark.asyncio
    async def test_public_omits_nudges_mentioning_non_broadcast(self, monkeypatch):
        monkeypatch.setattr("logos.api.routes.data.is_publicly_visible", lambda: True)

        def _fake_registry():
            return _StubRegistry([_StubContract(parties=("operator", "guest"), broadcast=False)])

        monkeypatch.setattr("logos.api.routes.data._load_consent_registry", _fake_registry)
        import logos.api.routes.data as data_mod

        class _FakeCache:
            nudges = self._nudges_list()

            def slow_cache_age(self):
                return 0

            def fast_cache_age(self):
                return 0

        monkeypatch.setattr(data_mod, "cache", _FakeCache())
        monkeypatch.setattr(data_mod, "_to_dict", lambda x: x)

        response = await data_mod.get_nudges()
        body = response.body
        # guest-mentioning nudge dropped
        assert b"Cycle 2 preregistration" not in body
        # safe nudge preserved
        assert b"Morning briefing" in body

    @pytest.mark.asyncio
    async def test_public_with_broadcast_consent_preserves(self, monkeypatch):
        monkeypatch.setattr("logos.api.routes.data.is_publicly_visible", lambda: True)

        def _fake_registry():
            return _StubRegistry([_StubContract(parties=("operator", "guest"), broadcast=True)])

        monkeypatch.setattr("logos.api.routes.data._load_consent_registry", _fake_registry)
        import logos.api.routes.data as data_mod

        class _FakeCache:
            nudges = self._nudges_list()

            def slow_cache_age(self):
                return 0

            def fast_cache_age(self):
                return 0

        monkeypatch.setattr(data_mod, "cache", _FakeCache())
        monkeypatch.setattr(data_mod, "_to_dict", lambda x: x)

        response = await data_mod.get_nudges()
        body = response.body
        # guest has broadcast consent → nudge preserved
        assert b"Cycle 2 preregistration" in body


# ── /api/consent/contracts — parties names → party_N ─────────────────────────


class TestConsentContractsRedaction:
    @pytest.mark.asyncio
    async def test_public_replaces_party_names(self, monkeypatch):
        """Verify party names get replaced with positional labels on public."""
        monkeypatch.setattr("logos.api.deps.stream_redaction._is_publicly_visible", lambda: True)

        class _FakeContract:
            id = "contract-wife-001"
            parties = ("operator", "wife")
            scope = frozenset({"voice_text", "biometrics"})
            active = True
            created_at = "2026-01-01T00:00:00Z"
            revoked_at = None

        class _FakeRegistry:
            def __iter__(self):
                return iter([_FakeContract()])

        import logos.api.routes.consent as consent_mod

        monkeypatch.setattr("logos._governance.load_contracts", lambda: _FakeRegistry())

        result = await consent_mod.list_contracts()
        assert result["contracts"][0]["parties"] == ["operator", "party_1"]
        # scope still structural
        assert "voice_text" in result["contracts"][0]["scope"]
        assert "biometrics" in result["contracts"][0]["scope"]

    @pytest.mark.asyncio
    async def test_private_returns_real_party_names(self, monkeypatch):
        monkeypatch.setattr("logos.api.deps.stream_redaction._is_publicly_visible", lambda: False)

        class _FakeContract:
            id = "contract-wife-001"
            parties = ("operator", "wife")
            scope = frozenset({"voice_text"})
            active = True
            created_at = "2026-01-01T00:00:00Z"
            revoked_at = None

        class _FakeRegistry:
            def __iter__(self):
                return iter([_FakeContract()])

        import logos.api.routes.consent as consent_mod

        monkeypatch.setattr("logos._governance.load_contracts", lambda: _FakeRegistry())

        result = await consent_mod.list_contracts()
        assert result["contracts"][0]["parties"] == ["operator", "wife"]
