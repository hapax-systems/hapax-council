"""Unit tests for agents.metadata_composer.composer.compose_metadata."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from hypothesis import given
from hypothesis import strategies as st

from agents.metadata_composer import (
    ChapterMarker,
    ComposedMetadata,
    compose_metadata,
    state_readers,
)
from agents.metadata_composer import composer as composer_mod
from agents.metadata_composer.public_claim_gate import ClaimEvidence


@pytest.fixture(autouse=True)
def _clear_state_cache():
    state_readers._reset_cache()
    yield
    state_readers._reset_cache()


def _make_snapshot(**overrides) -> state_readers.StateSnapshot:
    defaults = {
        "working_mode": "research",
        "programme": None,
        "stimmung_tone": "ambient",
        "director_activity": "observe",
        "chronicle_events": [],
    }
    defaults.update(overrides)
    return state_readers.StateSnapshot(**defaults)


def _live_evidence(**overrides) -> ClaimEvidence:
    defaults = {
        "broadcast_id": "bx",
        "broadcast_age_s": 1.0,
        "egress_active": True,
        "current_activity": "witnessed activity",
        "programme_role": "research",
        "programme_role_age_s": 1.0,
    }
    defaults.update(overrides)
    return ClaimEvidence(**defaults)


def _vod_evidence(**overrides) -> ClaimEvidence:
    defaults = {
        "archive_url": "https://youtu.be/archive",
        "rights_clear": True,
    }
    defaults.update(overrides)
    return ClaimEvidence(**defaults)


# ── scope dispatch ─────────────────────────────────────────────────────────


def test_vod_boundary_returns_full_metadata():
    with (
        patch.object(state_readers, "snapshot", return_value=_make_snapshot()),
        patch.object(state_readers, "read_chronicle", return_value=[]),
    ):
        result = compose_metadata(
            "vod_boundary",
            broadcast_id="bx",
            vod_time_range=(0.0, 100.0),
            llm_call=lambda **_: None,
            claim_evidence=_vod_evidence(),
        )
    assert isinstance(result, ComposedMetadata)
    assert result.title
    assert result.description
    assert result.description_chapters is not None
    assert any(c.timestamp_s == 0 for c in result.description_chapters)
    assert result.tags
    assert result.grounding_provenance["scope"] == "vod_boundary"


def test_live_update_omits_chapters():
    with patch.object(state_readers, "snapshot", return_value=_make_snapshot()):
        result = compose_metadata(
            "live_update",
            broadcast_id="bx",
            llm_call=lambda **_: None,
            claim_evidence=_live_evidence(),
        )
    assert isinstance(result, ComposedMetadata)
    assert result.description_chapters is None
    assert result.pinned_comment == ""


def test_cross_surface_uses_event_in_provenance():
    event = {
        "event_type": "transition",
        "ts": 1.0,
        "payload": {"intent_family": "programme.boundary", "salience": 0.85},
    }
    with patch.object(state_readers, "snapshot", return_value=_make_snapshot()):
        result = compose_metadata(
            "cross_surface",
            triggering_event=event,
            llm_call=lambda **_: None,
            claim_evidence=_live_evidence(),
        )
    assert isinstance(result, ComposedMetadata)
    assert result.grounding_provenance["triggering_event_kind"] == "transition"
    assert result.grounding_provenance["triggering_event_salience"] == 0.85
    assert "programme.boundary" in result.bluesky_post


def test_allowed_metadata_references_public_claim_gate():
    with patch.object(state_readers, "snapshot", return_value=_make_snapshot()):
        result = compose_metadata(
            "live_update",
            broadcast_id="bx",
            llm_call=lambda **_: None,
            claim_evidence=_live_evidence(),
        )
    gate = result.grounding_provenance["public_claim_gate"]
    assert gate["gate"] == "metadata-public-claim-gate"
    assert gate["allowed"] is True
    assert gate["decisions"]["live_now"]["decision"] == "allow"


def test_live_update_stale_broadcast_id_refuses_public_copy():
    with patch.object(state_readers, "snapshot", return_value=_make_snapshot()):
        result = compose_metadata(
            "live_update",
            broadcast_id="bx",
            llm_call=lambda **_: "unsupported live copy",
            claim_evidence=_live_evidence(broadcast_age_s=120.0),
        )
    gate = result.grounding_provenance["public_claim_gate"]
    assert gate["allowed"] is False
    assert gate["decisions"]["live_now"]["decision"] == "refuse"
    assert "stale" in gate["decisions"]["live_now"]["reason"]
    assert "Public metadata refusal" in result.description
    assert "unsupported live copy" not in result.description


def test_live_update_missing_egress_refuses_public_copy():
    with patch.object(state_readers, "snapshot", return_value=_make_snapshot()):
        result = compose_metadata(
            "live_update",
            broadcast_id="bx",
            llm_call=lambda **_: None,
            claim_evidence=_live_evidence(egress_active=False),
        )
    gate = result.grounding_provenance["public_claim_gate"]
    assert gate["allowed"] is False
    assert "egress_active" in gate["decisions"]["live_now"]["reason"]
    assert "not currently broadcasting" in result.description


def test_vod_boundary_missing_rights_refuses_archive_copy():
    with (
        patch.object(state_readers, "snapshot", return_value=_make_snapshot()),
        patch.object(state_readers, "read_chronicle", return_value=[]),
    ):
        result = compose_metadata(
            "vod_boundary",
            broadcast_id="bx",
            vod_time_range=(0.0, 60.0),
            llm_call=lambda **_: None,
            claim_evidence=_vod_evidence(rights_clear=False),
        )
    gate = result.grounding_provenance["public_claim_gate"]
    assert gate["allowed"] is False
    assert gate["decisions"]["archive"]["decision"] == "refuse"
    assert gate["decisions"]["replay"]["decision"] == "refuse"
    assert "rights pending" in result.description
    assert result.description_chapters is None


def test_cross_surface_missing_monetization_readiness_refuses_claim():
    event = {
        "event_type": "monetization.review",
        "ts": 1.0,
        "payload": {
            "intent_family": "monetization.review",
            "salience": 0.9,
            "public_claims": ["monetization"],
        },
    }
    with patch.object(state_readers, "snapshot", return_value=_make_snapshot()):
        result = compose_metadata(
            "cross_surface",
            triggering_event=event,
            llm_call=lambda **_: None,
            claim_evidence=_live_evidence(monetization_active=False),
        )
    gate = result.grounding_provenance["public_claim_gate"]
    assert gate["allowed"] is False
    assert gate["decisions"]["live_now"]["decision"] == "allow"
    assert gate["decisions"]["monetization"]["decision"] == "refuse"
    assert "not currently monetized" in result.description


def test_unknown_scope_raises():
    with pytest.raises(ValueError, match="unknown scope"):
        compose_metadata("garbage")  # type: ignore[arg-type]


def test_vod_boundary_requires_time_range():
    with pytest.raises(ValueError, match="vod_boundary"):
        compose_metadata("vod_boundary", broadcast_id="bx")


def test_cross_surface_requires_event():
    with pytest.raises(ValueError, match="cross_surface"):
        compose_metadata("cross_surface")


# ── char limits enforced ───────────────────────────────────────────────────


def test_field_limits_enforced():
    with (
        patch.object(state_readers, "snapshot", return_value=_make_snapshot()),
        patch.object(state_readers, "read_chronicle", return_value=[]),
    ):
        # Push the deterministic prose through with a no-op LLM stub
        result = compose_metadata(
            "vod_boundary",
            broadcast_id="bx",
            vod_time_range=(0.0, 60.0),
            llm_call=lambda **_: None,
            claim_evidence=_vod_evidence(),
        )
    assert len(result.title) <= composer_mod.TITLE_LIMIT
    assert len(result.description) <= composer_mod.DESCRIPTION_LIMIT
    assert len(result.shorts_caption) <= composer_mod.SHORTS_CAPTION_LIMIT
    assert len(result.bluesky_post) <= composer_mod.BLUESKY_LIMIT
    assert len(result.discord_embed_title) <= composer_mod.DISCORD_TITLE_LIMIT
    assert len(result.mastodon_post) <= composer_mod.MASTODON_LIMIT
    tag_total = sum(len(t) for t in result.tags) + max(0, len(result.tags) - 1)
    assert tag_total <= composer_mod.TAGS_TOTAL_LIMIT


# ── LLM polish + register fallback ─────────────────────────────────────────


def test_llm_polish_called_with_seed():
    seen: list[dict] = []

    def stub(*, seed, scope, kind, referent=None):
        seen.append({"seed": seed, "scope": scope, "kind": kind, "referent": referent})
        return f"polished: {seed[:30]}"

    with patch.object(state_readers, "snapshot", return_value=_make_snapshot()):
        compose_metadata(
            "live_update",
            broadcast_id="bx",
            llm_call=stub,
            claim_evidence=_live_evidence(),
        )

    assert len(seen) >= 1
    assert all(s["kind"] in {"title", "description"} for s in seen)


def test_register_violation_falls_back_to_seed():
    """If the LLM emits a personification verb, the fallback seed wins."""

    def bad_stub(*, seed, scope, kind, referent=None):
        return "Hapax feels excited about today's stream!"

    with patch.object(state_readers, "snapshot", return_value=_make_snapshot()):
        result = compose_metadata(
            "live_update",
            broadcast_id="bx",
            llm_call=bad_stub,
            claim_evidence=_live_evidence(),
        )

    assert "feels" not in result.title
    assert "feels" not in result.description


def test_llm_failure_falls_back_to_seed():
    def crashing_stub(**_):
        raise RuntimeError("network gone")

    with patch.object(state_readers, "snapshot", return_value=_make_snapshot()):
        result = compose_metadata(
            "live_update",
            broadcast_id="bx",
            llm_call=crashing_stub,
            claim_evidence=_live_evidence(),
        )

    assert isinstance(result, ComposedMetadata)
    assert result.title


# ── helper unit tests ─────────────────────────────────────────────────────


def test_truncate_tags_caps_total_length():
    too_many = [f"tag{i:03d}" for i in range(200)]
    truncated = composer_mod._truncate_tags(too_many)
    total = sum(len(t) for t in truncated) + max(0, len(truncated) - 1)
    assert total <= composer_mod.TAGS_TOTAL_LIMIT


def test_format_chapter_line_under_one_hour():
    line = composer_mod._format_chapter_line(ChapterMarker(timestamp_s=754, label="X"))
    assert line == "12:34 X"


def test_format_chapter_line_over_one_hour():
    line = composer_mod._format_chapter_line(ChapterMarker(timestamp_s=5025, label="X"))
    assert line == "1:23:45 X"


def test_format_description_with_chapters_prepends_scaffold():
    chapters = [
        ChapterMarker(timestamp_s=0, label="Opening"),
        ChapterMarker(timestamp_s=120, label="Beat"),
    ]
    result = composer_mod._format_description_with_chapters("body text", chapters)
    assert "00:00 Opening" in result
    assert "02:00 Beat" in result
    assert result.endswith("body text")


def test_format_description_no_chapters_returns_body():
    assert composer_mod._format_description_with_chapters("body", []) == "body"


# ── operator referent integration (su-non-formal-referent-001 / PR #1277) ─


def test_referent_threaded_into_grounding_when_picker_available():
    """When OperatorReferentPicker is importable, grounding records the picked referent."""
    fake_picker = type(
        "FakePicker",
        (),
        {
            "pick_for_vod_segment": staticmethod(lambda seg_id: "Oudepode"),
            "pick": staticmethod(lambda seed=None: "Oudepode"),
        },
    )
    with (
        patch.dict(
            "sys.modules",
            {"shared.operator_referent": type("M", (), {"OperatorReferentPicker": fake_picker})()},
        ),
        patch.object(state_readers, "snapshot", return_value=_make_snapshot()),
    ):
        result = compose_metadata(
            "live_update",
            broadcast_id="bx",
            llm_call=lambda **_: None,
            claim_evidence=_live_evidence(),
        )
    assert result.grounding_provenance["operator_referent"] == "Oudepode"


def test_referent_threaded_into_llm_call():
    seen: list[dict] = []

    def stub(*, seed, scope, kind, referent=None):
        seen.append({"referent": referent})
        return None

    fake_picker = type(
        "FakePicker",
        (),
        {
            "pick_for_vod_segment": staticmethod(lambda seg_id: "OTO"),
            "pick": staticmethod(lambda seed=None: "OTO"),
        },
    )
    with (
        patch.dict(
            "sys.modules",
            {"shared.operator_referent": type("M", (), {"OperatorReferentPicker": fake_picker})()},
        ),
        patch.object(state_readers, "snapshot", return_value=_make_snapshot()),
    ):
        compose_metadata(
            "live_update",
            broadcast_id="bx",
            llm_call=stub,
            claim_evidence=_live_evidence(),
        )

    assert seen and all(s["referent"] == "OTO" for s in seen)


def test_referent_none_when_picker_unavailable():
    """If the operator_referent module is missing (pre-#1277), composer ships standalone."""
    with (
        patch.dict("sys.modules", {"shared.operator_referent": None}),
        patch.object(state_readers, "snapshot", return_value=_make_snapshot()),
    ):
        result = compose_metadata(
            "live_update",
            broadcast_id="bx",
            llm_call=lambda **_: None,
            claim_evidence=_live_evidence(),
        )
    assert result.grounding_provenance["operator_referent"] is None


def test_referent_seeded_per_vod_for_consistency():
    """Same broadcast_id → same referent across multiple compose calls."""

    captured: list[str | None] = []

    fake_picker_module = type(
        "M",
        (),
        {
            "OperatorReferentPicker": type(
                "P",
                (),
                {
                    "pick_for_vod_segment": staticmethod(lambda seg_id: f"referent-for-{seg_id}"),
                    "pick": staticmethod(lambda seed=None: "fallback"),
                },
            ),
        },
    )()
    with (
        patch.dict("sys.modules", {"shared.operator_referent": fake_picker_module}),
        patch.object(state_readers, "snapshot", return_value=_make_snapshot()),
    ):
        r1 = compose_metadata(
            "live_update",
            broadcast_id="vod-7",
            llm_call=lambda **_: None,
            claim_evidence=_live_evidence(broadcast_id="vod-7"),
        )
        r2 = compose_metadata(
            "live_update",
            broadcast_id="vod-7",
            llm_call=lambda **_: None,
            claim_evidence=_live_evidence(broadcast_id="vod-7"),
        )
        captured.append(r1.grounding_provenance["operator_referent"])
        captured.append(r2.grounding_provenance["operator_referent"])

    assert captured[0] == captured[1] == "referent-for-vod-7"


# ── Hypothesis property: composer is deterministic ────────────────────────


@given(
    working_mode=st.sampled_from(["research", "rnd", "fortress"]),
    stimmung_tone=st.sampled_from(["ambient", "focused", "hothouse"]),
    director_activity=st.sampled_from(["observe", "create", "respond"]),
)
def test_compose_live_update_deterministic_for_state(
    working_mode, stimmung_tone, director_activity
):
    """Same state in → same outputs out (no hidden time/random dependency)."""
    snap = _make_snapshot(
        working_mode=working_mode,
        stimmung_tone=stimmung_tone,
        director_activity=director_activity,
    )

    state_readers._reset_cache()
    with patch.object(state_readers, "snapshot", return_value=snap):
        r1 = compose_metadata(
            "live_update",
            broadcast_id="bx",
            llm_call=lambda **_: None,
            claim_evidence=_live_evidence(),
        )
    state_readers._reset_cache()
    with patch.object(state_readers, "snapshot", return_value=snap):
        r2 = compose_metadata(
            "live_update",
            broadcast_id="bx",
            llm_call=lambda **_: None,
            claim_evidence=_live_evidence(),
        )

    assert r1.title == r2.title
    assert r1.description == r2.description
    assert r1.tags == r2.tags
    assert r1.shorts_caption == r2.shorts_caption
