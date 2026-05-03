"""Tests for the caption-substrate adapter."""

from __future__ import annotations

from agents.live_captions.reader import CaptionEvent
from agents.live_captions.routing import RoutingPolicy
from shared.caption_substrate_adapter import (
    CAPTION_SUBSTRATE_ID,
    DEFAULT_FRESHNESS_TTL_S,
    PRODUCER,
    TASK_ANCHOR,
    derive_idempotency_key,
    project_caption_substrate,
)

NOW = 1709876543.123  # arbitrary fixed adapter clock


def _allow_all() -> RoutingPolicy:
    return RoutingPolicy(allow=frozenset(), deny=frozenset(), default_allow=True)


def _allow_only_oudepode() -> RoutingPolicy:
    return RoutingPolicy(
        allow=frozenset({"oudepode"}),
        deny=frozenset(),
        default_allow=False,
    )


def _make_event(
    *,
    ts: float = NOW - 0.5,
    text: str = "hello world",
    duration_ms: int = 1500,
    speaker: str | None = "oudepode",
) -> CaptionEvent:
    return CaptionEvent(ts=ts, text=text, duration_ms=duration_ms, speaker=speaker)


# ── AC#3 happy path: cleared → caption.segment RVPE with provenance ─


class TestProjectCleared:
    def test_routed_caption_becomes_caption_segment_event(self) -> None:
        events = [_make_event(text="ok", speaker="oudepode")]
        candidates, rejections = project_caption_substrate(
            events,
            routing=_allow_all(),
            now=NOW,
            av_offset_s=0.18,
        )
        assert rejections == []
        assert len(candidates) == 1
        cand = candidates[0]
        assert cand.event.event_type == "caption.segment"
        assert cand.event.state_kind == "caption_text"
        assert cand.event.source.substrate_id == CAPTION_SUBSTRATE_ID
        assert cand.event.source.producer == PRODUCER
        assert cand.event.source.task_anchor == TASK_ANCHOR
        assert cand.av_offset_s == 0.18
        assert cand.idempotency_key == derive_idempotency_key(
            ts=NOW - 0.5, text="ok", speaker="oudepode"
        )
        assert cand.event.event_id.startswith("caption.segment:")
        assert cand.event.event_id.endswith(cand.idempotency_key)

    def test_surface_policy_includes_youtube_captions_and_captions(self) -> None:
        events = [_make_event()]
        candidates, _ = project_caption_substrate(
            events,
            routing=_allow_all(),
            now=NOW,
            av_offset_s=0.18,
        )
        cand = candidates[0]
        allowed = list(cand.event.surface_policy.allowed_surfaces)
        assert "youtube_captions" in allowed
        assert "captions" in allowed

    def test_routed_caption_records_av_offset_in_provenance(self) -> None:
        events = [_make_event()]
        candidates, _ = project_caption_substrate(
            events,
            routing=_allow_all(),
            now=NOW,
            av_offset_s=0.180,
        )
        prov = candidates[0].event.provenance
        joined = "|".join(prov.evidence_refs)
        assert "av_offset_s=0.180000" in joined


# ── AC#4a stale caption input rejected ──────────────────────────────


class TestStale:
    def test_event_older_than_freshness_ttl_is_rejected(self) -> None:
        stale_ts = NOW - DEFAULT_FRESHNESS_TTL_S - 5.0
        events = [_make_event(ts=stale_ts, text="old")]
        candidates, rejections = project_caption_substrate(
            events,
            routing=_allow_all(),
            now=NOW,
            av_offset_s=0.0,
        )
        assert candidates == []
        assert len(rejections) == 1
        assert rejections[0].reason == "stale"
        assert "ttl=" in rejections[0].detail

    def test_event_within_window_passes(self) -> None:
        fresh_ts = NOW - 1.0
        events = [_make_event(ts=fresh_ts)]
        candidates, rejections = project_caption_substrate(
            events,
            routing=_allow_all(),
            now=NOW,
            av_offset_s=0.0,
        )
        assert rejections == []
        assert len(candidates) == 1


# ── AC#4b denied routing rejected with provenance ───────────────────


class TestDeniedRouting:
    def test_speaker_not_in_allow_with_default_deny_is_rejected(self) -> None:
        events = [_make_event(text="guest", speaker="guest_alice")]
        candidates, rejections = project_caption_substrate(
            events,
            routing=_allow_only_oudepode(),
            now=NOW,
            av_offset_s=0.18,
        )
        assert candidates == []
        assert len(rejections) == 1
        rej = rejections[0]
        assert rej.reason == "denied_routing"
        assert "guest_alice" in rej.detail
        assert rej.speaker == "guest_alice"

    def test_explicit_deny_wins_over_allow(self) -> None:
        policy = RoutingPolicy(
            allow=frozenset({"alice"}),
            deny=frozenset({"alice"}),
            default_allow=True,
        )
        events = [_make_event(speaker="alice")]
        candidates, rejections = project_caption_substrate(
            events,
            routing=policy,
            now=NOW,
            av_offset_s=0.0,
        )
        assert candidates == []
        assert len(rejections) == 1
        assert rejections[0].reason == "denied_routing"


# ── AC#4c duplicate segment suppression ─────────────────────────────


class TestIdempotency:
    def test_same_event_in_seen_keys_is_rejected_as_duplicate(self) -> None:
        event = _make_event(text="dup", speaker="oudepode")
        key = derive_idempotency_key(ts=event.ts, text=event.text, speaker=event.speaker)
        candidates, rejections = project_caption_substrate(
            [event],
            routing=_allow_all(),
            now=NOW,
            av_offset_s=0.0,
            seen_keys=[key],
        )
        assert candidates == []
        assert len(rejections) == 1
        assert rejections[0].reason == "duplicate"

    def test_two_identical_events_in_one_call_dedupe(self) -> None:
        e1 = _make_event(text="hi", ts=NOW - 0.4)
        e2 = _make_event(text="hi", ts=NOW - 0.4)
        candidates, rejections = project_caption_substrate(
            [e1, e2],
            routing=_allow_all(),
            now=NOW,
            av_offset_s=0.0,
        )
        assert len(candidates) == 1
        assert len(rejections) == 1
        assert rejections[0].reason == "duplicate"

    def test_idempotency_key_normalises_none_and_empty_speaker(self) -> None:
        none_key = derive_idempotency_key(ts=1.0, text="x", speaker=None)
        empty_key = derive_idempotency_key(ts=1.0, text="x", speaker="")
        assert none_key == empty_key


# ── AC#4d public-claim blocked when AV-offset unavailable ───────────


class TestPublicClaimBlocking:
    def test_no_av_offset_marks_dry_run_with_reason(self) -> None:
        events = [_make_event()]
        candidates, _ = project_caption_substrate(
            events,
            routing=_allow_all(),
            now=NOW,
            av_offset_s=None,
        )
        cand = candidates[0]
        sp = cand.event.surface_policy
        assert sp.fallback_action == "dry_run"
        assert sp.dry_run_reason is not None
        assert "av_offset_unavailable" in sp.dry_run_reason
        assert cand.av_offset_s is None
        joined = "|".join(cand.event.provenance.evidence_refs)
        assert "av_offset_unavailable" in joined

    def test_av_offset_present_marks_hold_fallback_no_dry_run(self) -> None:
        events = [_make_event()]
        candidates, _ = project_caption_substrate(
            events,
            routing=_allow_all(),
            now=NOW,
            av_offset_s=0.18,
        )
        sp = candidates[0].event.surface_policy
        assert sp.fallback_action == "hold"
        assert sp.dry_run_reason is None

    def test_requires_audio_safe_and_provenance_always_true(self) -> None:
        events = [_make_event()]
        candidates, _ = project_caption_substrate(
            events,
            routing=_allow_all(),
            now=NOW,
            av_offset_s=0.18,
        )
        sp = candidates[0].event.surface_policy
        assert sp.requires_audio_safe is True
        assert sp.requires_provenance is True


# ── Empty input ─────────────────────────────────────────────────────


class TestEmptyInput:
    def test_no_events_returns_empty_pair(self) -> None:
        candidates, rejections = project_caption_substrate(
            [],
            routing=_allow_all(),
            now=NOW,
            av_offset_s=0.0,
        )
        assert candidates == []
        assert rejections == []
