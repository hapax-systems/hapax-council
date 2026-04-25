"""Tests for ``agents.operator_awareness.state``."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from agents.operator_awareness.state import (
    AwarenessState,
    CrossAccountBlock,
    DaimonionBlock,
    FleetBlock,
    GovernanceBlock,
    HealthBlock,
    MarketingOutreachBlock,
    MusicBlock,
    ProgrammeBlock,
    PublishingBlock,
    RefusalEvent,
    ResearchDispatchBlock,
    SprintBlock,
    StreamBlock,
    write_state_atomic,
)


def _now() -> datetime:
    return datetime.now(UTC)


# ── Top-level model defaults ──────────────────────────────────────


class TestAwarenessStateDefaults:
    def test_minimal_construction_works(self):
        state = AwarenessState(timestamp=_now())
        assert state.schema_version == 1
        assert state.ttl_seconds == 90
        assert isinstance(state.marketing_outreach, MarketingOutreachBlock)
        assert isinstance(state.health_system, HealthBlock)
        assert state.refusals_recent == []

    def test_all_13_blocks_have_typed_defaults(self):
        state = AwarenessState(timestamp=_now())
        # Each of the 13 declared categories is a typed sub-block.
        assert isinstance(state.marketing_outreach, MarketingOutreachBlock)
        assert isinstance(state.research_dispatches, ResearchDispatchBlock)
        assert isinstance(state.music_soundcloud, MusicBlock)
        assert isinstance(state.publishing_pipeline, PublishingBlock)
        assert isinstance(state.health_system, HealthBlock)
        assert isinstance(state.daimonion_voice, DaimonionBlock)
        assert isinstance(state.stream, StreamBlock)
        assert isinstance(state.cross_account, CrossAccountBlock)
        assert isinstance(state.governance, GovernanceBlock)
        assert isinstance(state.content_programmes, ProgrammeBlock)
        assert isinstance(state.hardware_fleet, FleetBlock)
        assert isinstance(state.time_sprint, SprintBlock)
        # 13th: refusals_recent is the list-of-events spine.
        assert state.refusals_recent == []

    def test_frozen(self):
        """Pydantic frozen=True — surfaces can't mutate the spine."""
        state = AwarenessState(timestamp=_now())
        try:
            state.schema_version = 2
        except (TypeError, ValueError):
            return
        # Pydantic v2 raises on frozen mutation; if we got here it didn't.
        raise AssertionError("AwarenessState should be frozen")


# ── Block public flag ────────────────────────────────────────────


class TestPublicFlag:
    def test_default_block_public_is_false(self):
        """New blocks default private — public_filter strips on omg.lol fanout."""
        for block_type in (
            MarketingOutreachBlock,
            ResearchDispatchBlock,
            MusicBlock,
            PublishingBlock,
            HealthBlock,
            DaimonionBlock,
            StreamBlock,
            CrossAccountBlock,
            GovernanceBlock,
            ProgrammeBlock,
            FleetBlock,
            SprintBlock,
        ):
            block = block_type()
            assert block.public is False, f"{block_type.__name__} default public must be False"

    def test_explicit_public_true_persists(self):
        block = StreamBlock(public=True, live=True)
        assert block.public is True
        assert block.live is True


# ── RefusalEvent (constitutional substrate) ──────────────────────


class TestRefusalEvent:
    def test_required_fields(self):
        ev = RefusalEvent(
            timestamp=_now(),
            surface="twitter",
            reason="ToS prohibits automation",
        )
        assert ev.surface == "twitter"
        assert ev.reason == "ToS prohibits automation"
        assert ev.refused_artifact_slug is None

    def test_optional_artifact_slug(self):
        ev = RefusalEvent(
            timestamp=_now(),
            surface="linkedin",
            reason="ToS §8.2 + 23% account-restriction rate",
            refused_artifact_slug="constitutional-brief",
        )
        assert ev.refused_artifact_slug == "constitutional-brief"

    def test_frozen(self):
        ev = RefusalEvent(timestamp=_now(), surface="x", reason="y")
        try:
            ev.surface = "z"
        except (TypeError, ValueError):
            return
        raise AssertionError("RefusalEvent should be frozen")


# ── State serialisation ──────────────────────────────────────────


class TestSerialisation:
    def test_round_trips_through_json(self):
        original = AwarenessState(
            timestamp=_now(),
            health_system=HealthBlock(
                public=True,
                overall_status="healthy",
                failed_units=0,
            ),
            refusals_recent=[
                RefusalEvent(timestamp=_now(), surface="x", reason="y"),
            ],
        )
        payload = original.model_dump_json()
        decoded = AwarenessState.model_validate_json(payload)
        assert decoded.health_system.overall_status == "healthy"
        assert len(decoded.refusals_recent) == 1
        assert decoded.refusals_recent[0].surface == "x"

    def test_unknown_top_level_field_rejected(self):
        """Schema is strict — unknown fields would crash readers."""
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            AwarenessState.model_validate(
                {"timestamp": _now().isoformat(), "unknown_block": {}},
            )


# ── Atomic writer ────────────────────────────────────────────────


class TestWriteStateAtomic:
    def test_writes_full_payload(self, tmp_path):
        state = AwarenessState(
            timestamp=_now(),
            health_system=HealthBlock(overall_status="healthy"),
        )
        out = tmp_path / "state.json"
        ok = write_state_atomic(state, out)
        assert ok is True
        loaded = json.loads(out.read_text(encoding="utf-8"))
        assert loaded["health_system"]["overall_status"] == "healthy"
        assert loaded["schema_version"] == 1

    def test_creates_parent_dir(self, tmp_path):
        state = AwarenessState(timestamp=_now())
        out = tmp_path / "deep" / "nested" / "state.json"
        ok = write_state_atomic(state, out)
        assert ok is True
        assert out.exists()

    def test_overwrites_atomically(self, tmp_path):
        out = tmp_path / "state.json"
        # Pre-existing content.
        out.write_text("STALE", encoding="utf-8")
        state = AwarenessState(
            timestamp=_now(),
            health_system=HealthBlock(overall_status="degraded"),
        )
        ok = write_state_atomic(state, out)
        assert ok is True
        loaded = json.loads(out.read_text(encoding="utf-8"))
        assert loaded["health_system"]["overall_status"] == "degraded"

    def test_no_tmp_file_left_behind(self, tmp_path):
        """Successful write atomically renames; no .tmp.{pid} stays."""
        state = AwarenessState(timestamp=_now())
        out = tmp_path / "state.json"
        write_state_atomic(state, out)
        leftover = list(tmp_path.glob(".json.tmp.*"))
        assert leftover == []

    def test_unwritable_parent_returns_false(self, tmp_path, monkeypatch):
        """Failure path: log + return False, don't raise."""

        def _fail_mkdir(*_args, **_kwargs):
            raise OSError("read-only fs")

        from pathlib import Path as _Path

        monkeypatch.setattr(_Path, "mkdir", _fail_mkdir)
        state = AwarenessState(timestamp=_now())
        out = tmp_path / "blocked" / "state.json"
        ok = write_state_atomic(state, out)
        assert ok is False
        assert not out.exists()
