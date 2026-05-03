"""Tests for the cuepoint-substrate adapter."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from shared.content_programme_run_store import (
    ContentProgrammeRunEnvelope,
    build_fixture_envelope,
)
from shared.cuepoint_substrate_adapter import (
    CUEPOINT_SUBSTRATE_ID,
    DEFAULT_FRESHNESS_TTL_S,
    PRODUCER,
    TASK_ANCHOR,
    project_cuepoint_substrate,
)
from shared.format_public_event_adapter import ProgrammeBoundaryEvent

NOW_DT = datetime(2026, 4, 29, 13, 55, tzinfo=UTC)
NOW = NOW_DT.timestamp()


def _boundary(
    run: ContentProgrammeRunEnvelope,
    *,
    boundary_type: str = "live_cuepoint.candidate",
    duplicate_key_suffix: str = "001",
    emitted_offset_s: float = -60.0,
    live_ad_cuepoint_allowed: bool = True,
    vod_chapter_allowed: bool = True,
    cuepoint_unavailable_reason: str | None = None,
    research_vehicle_event_type: str = "cuepoint.candidate",
    state_kind: str = "cuepoint",
    allowed_surfaces: tuple[str, ...] = ("youtube_cuepoints", "youtube_chapters"),
    denied_surfaces: tuple[str, ...] = ("youtube_shorts", "monetization"),
    fallback_action: str = "hold",
    extra: dict[str, Any] | None = None,
) -> ProgrammeBoundaryEvent:
    """Build a PBE keyed off a fixture run.

    Defaults emit a `live_cuepoint.candidate` 60s before NOW with both
    live + VOD allowed, mapping to `cuepoint.candidate` RVPE on the
    youtube_cuepoints + youtube_chapters surfaces.
    """
    mapping = {
        "internal_only": False,
        "research_vehicle_event_type": research_vehicle_event_type,
        "state_kind": state_kind,
        "source_substrate_id": "programme_cuepoints",
        "allowed_surfaces": allowed_surfaces,
        "denied_surfaces": denied_surfaces,
        "fallback_action": fallback_action,
        "unavailable_reasons": (),
    }
    gate = {
        "gate_ref": run.gate_refs.grounding_gate_refs[0]
        if run.gate_refs.grounding_gate_refs
        else None,
        "gate_state": "pass",
        "claim_allowed": True,
        "public_claim_allowed": True,
        "infractions": (),
    }
    claim_shape = {
        "claim_kind": "ranking",
        "authority_ceiling": "evidence_bound",
        "confidence_label": "medium_high",
        "uncertainty": "Scope is limited to the cited evidence window.",
        "scope_limit": "Ranks only the declared source bundle.",
    }
    cuepoint_chapter_policy = {
        "live_ad_cuepoint_allowed": live_ad_cuepoint_allowed,
        "vod_chapter_allowed": vod_chapter_allowed,
        "live_cuepoint_distinct_from_vod_chapter": True,
        "chapter_label": "Cuepoint adapter test chapter",
        "timecode": "00:01",
        "cuepoint_unavailable_reason": cuepoint_unavailable_reason,
    }
    payload: dict[str, Any] = {
        "boundary_id": f"pbe_cuepoint_{duplicate_key_suffix}",
        "emitted_at": datetime.fromtimestamp(NOW + emitted_offset_s, tz=UTC),
        "programme_id": run.programme_id,
        "run_id": run.run_id,
        "format_id": run.format_id,
        "sequence": 1,
        "boundary_type": boundary_type,
        "public_private_mode": run.public_private_mode,
        "grounding_question": run.grounding_question,
        "summary": "Cuepoint substrate test boundary.",
        "evidence_refs": ("source:primary_doc_a", "grounding-gate:evidence_audit_a"),
        "no_expert_system_gate": gate,
        "claim_shape": claim_shape,
        "public_event_mapping": mapping,
        "cuepoint_chapter_policy": cuepoint_chapter_policy,
        "dry_run_unavailable_reasons": (),
        "duplicate_key": (
            f"{run.programme_id}:{run.run_id}:{boundary_type}:{duplicate_key_suffix}"
        ),
    }
    if extra:
        payload.update(extra)
    return ProgrammeBoundaryEvent.model_validate(payload)


# ── Module-level constants surface (regression pin) ──────────────────


class TestModuleConstants:
    def test_substrate_id_is_canonical(self) -> None:
        assert CUEPOINT_SUBSTRATE_ID == "cuepoint_chapter_inband"

    def test_producer_and_task_anchor_pinned(self) -> None:
        assert PRODUCER == "shared.cuepoint_substrate_adapter"
        assert TASK_ANCHOR == "cuepoint-substrate-adapter"

    def test_default_freshness_ttl_is_300s(self) -> None:
        assert DEFAULT_FRESHNESS_TTL_S == 300.0


# ── AC#3 happy paths: cuepoint vs chapter distinct kinds ────────────


class TestProjectCleared:
    def test_live_cuepoint_candidate_becomes_cuepoint_kind(self) -> None:
        run = build_fixture_envelope("public_safe_evidence_audit")
        boundary = _boundary(run, boundary_type="live_cuepoint.candidate")
        candidates, rejections = project_cuepoint_substrate([(run, boundary)], now=NOW)
        assert rejections == []
        assert len(candidates) == 1
        cand = candidates[0]
        assert cand.kind == "cuepoint"
        assert cand.event.event_type == "cuepoint.candidate"
        assert cand.boundary_id == boundary.boundary_id
        assert cand.run_id == run.run_id
        assert cand.programme_id == run.programme_id
        assert cand.idempotency_key == cand.decision.idempotency_key

    def test_chapter_boundary_becomes_chapter_kind(self) -> None:
        run = build_fixture_envelope("public_safe_evidence_audit")
        boundary = _boundary(
            run,
            boundary_type="chapter.boundary",
            research_vehicle_event_type="chapter.marker",
            state_kind="chapter",
            allowed_surfaces=("youtube_chapters", "archive"),
            denied_surfaces=("youtube_cuepoints", "youtube_shorts", "monetization"),
            fallback_action="chapter_only",
        )
        candidates, rejections = project_cuepoint_substrate([(run, boundary)], now=NOW)
        assert rejections == []
        assert len(candidates) == 1
        cand = candidates[0]
        assert cand.kind == "chapter"
        assert cand.event.event_type == "chapter.marker"

    def test_distinct_kinds_in_one_call(self) -> None:
        """Live cuepoint + VOD chapter from the same run should
        project to two distinct candidates with distinct kinds — the
        substrate-registry invariant is preserved end-to-end."""
        run = build_fixture_envelope("public_safe_evidence_audit")
        live = _boundary(run, boundary_type="live_cuepoint.candidate", duplicate_key_suffix="L1")
        chapter = _boundary(
            run,
            boundary_type="chapter.boundary",
            duplicate_key_suffix="C1",
            research_vehicle_event_type="chapter.marker",
            state_kind="chapter",
            allowed_surfaces=("youtube_chapters", "archive"),
            denied_surfaces=("youtube_cuepoints", "youtube_shorts", "monetization"),
            fallback_action="chapter_only",
        )
        candidates, rejections = project_cuepoint_substrate([(run, live), (run, chapter)], now=NOW)
        assert rejections == []
        assert len(candidates) == 2
        kinds = {c.kind for c in candidates}
        assert kinds == {"cuepoint", "chapter"}


# ── AC#1 boundary-type filter (mixed PBE stream) ────────────────────


class TestBoundaryTypeFilter:
    def test_unrelated_boundary_type_rejected(self) -> None:
        run = build_fixture_envelope("public_safe_evidence_audit")
        boundary = _boundary(
            run,
            boundary_type="rank.assigned",
            research_vehicle_event_type="programme.boundary",
            state_kind="programme_state",
            allowed_surfaces=("youtube_chapters", "archive"),
            denied_surfaces=("youtube_cuepoints", "youtube_shorts", "monetization"),
            fallback_action="chapter_only",
        )
        candidates, rejections = project_cuepoint_substrate([(run, boundary)], now=NOW)
        assert candidates == []
        assert len(rejections) == 1
        rej = rejections[0]
        assert rej.reason == "not_cuepoint_or_chapter"
        assert "rank.assigned" in rej.detail


# ── AC#5a stale rejection ───────────────────────────────────────────


class TestStale:
    def test_emitted_before_freshness_window_rejected(self) -> None:
        run = build_fixture_envelope("public_safe_evidence_audit")
        # 600s old > default 300s ttl
        boundary = _boundary(run, emitted_offset_s=-600.0)
        candidates, rejections = project_cuepoint_substrate([(run, boundary)], now=NOW)
        assert candidates == []
        assert len(rejections) == 1
        assert rejections[0].reason == "stale"
        assert "ttl=300" in rejections[0].detail

    def test_within_window_passes(self) -> None:
        run = build_fixture_envelope("public_safe_evidence_audit")
        boundary = _boundary(run, emitted_offset_s=-30.0)
        candidates, rejections = project_cuepoint_substrate([(run, boundary)], now=NOW)
        assert rejections == []
        assert len(candidates) == 1


# ── AC#5b duplicate suppression ─────────────────────────────────────


class TestIdempotency:
    def test_seen_key_rejects_as_duplicate(self) -> None:
        run = build_fixture_envelope("public_safe_evidence_audit")
        boundary = _boundary(run, duplicate_key_suffix="DUP1")
        candidates, rejections = project_cuepoint_substrate(
            [(run, boundary)],
            now=NOW,
            seen_keys=[boundary.duplicate_key],
        )
        assert candidates == []
        assert len(rejections) == 1
        assert rejections[0].reason == "duplicate"
        assert boundary.duplicate_key in rejections[0].detail

    def test_two_identical_in_one_call_dedupe(self) -> None:
        run = build_fixture_envelope("public_safe_evidence_audit")
        b1 = _boundary(run, duplicate_key_suffix="X")
        b2 = _boundary(run, duplicate_key_suffix="X")
        candidates, rejections = project_cuepoint_substrate([(run, b1), (run, b2)], now=NOW)
        assert len(candidates) == 1
        assert len(rejections) == 1
        assert rejections[0].reason == "duplicate"


# ── AC#5c chapter_only fallback ─────────────────────────────────────


class TestChapterOnlyFallback:
    def test_live_blocked_chapter_allowed_only_chapter_emits(self) -> None:
        """When live_ad_cuepoint_allowed=False AND vod_chapter_allowed=True,
        a chapter.boundary PBE still produces a chapter candidate; a
        live_cuepoint.candidate PBE under the same policy is refused
        by the inner adapter via the cuepoint_unavailable_reason
        propagation (not by the substrate gate itself)."""
        run = build_fixture_envelope("public_safe_evidence_audit")
        chapter = _boundary(
            run,
            boundary_type="chapter.boundary",
            research_vehicle_event_type="chapter.marker",
            state_kind="chapter",
            live_ad_cuepoint_allowed=False,
            vod_chapter_allowed=True,
            allowed_surfaces=("youtube_chapters", "archive"),
            denied_surfaces=("youtube_cuepoints", "youtube_shorts", "monetization"),
            fallback_action="chapter_only",
        )
        candidates, rejections = project_cuepoint_substrate([(run, chapter)], now=NOW)
        assert rejections == []
        assert len(candidates) == 1
        assert candidates[0].kind == "chapter"
        assert candidates[0].event.event_type == "chapter.marker"


# ── AC#5d blocked public claims ─────────────────────────────────────


class TestBlockedPublicClaims:
    def test_private_run_refused_by_inner_adapter(self) -> None:
        """A private programme run must produce no public RVPE — the
        inner format-adapter refuses on `private_mode` hard reason,
        which the substrate adapter surfaces as
        `format_adapter_refused`."""
        run = build_fixture_envelope("private_run")
        boundary = _boundary(run)
        candidates, rejections = project_cuepoint_substrate([(run, boundary)], now=NOW)
        assert candidates == []
        assert len(rejections) == 1
        assert rejections[0].reason == "format_adapter_refused"
        assert "private_mode" in rejections[0].detail

    def test_dry_run_refused_by_inner_adapter(self) -> None:
        run = build_fixture_envelope("dry_run_tier_list")
        boundary = _boundary(run)
        candidates, rejections = project_cuepoint_substrate([(run, boundary)], now=NOW)
        assert candidates == []
        assert len(rejections) == 1
        assert rejections[0].reason == "format_adapter_refused"
        assert "dry_run_mode" in rejections[0].detail


# ── Empty input ─────────────────────────────────────────────────────


class TestEmptyInput:
    def test_no_pairs_returns_empty(self) -> None:
        candidates, rejections = project_cuepoint_substrate([], now=NOW)
        assert candidates == []
        assert rejections == []
