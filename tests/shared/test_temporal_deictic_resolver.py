"""Tests for ``shared.temporal_deictic_resolver``.

Per cc-task ``temporal-deictic-reference-resolver`` (WSJF 10.4, p0).

Coverage maps directly to the 8 cc-task acceptance scenarios:

  - public speech → TestPublicSpeech
  - private speech → TestPrivateSpeechFirewall
  - stale public → TestStaleness
  - ambiguous two events → TestAmbiguity
  - livestream visible → TestLivestreamVisual
  - livestream suppressed → covered by firewall + freshness
  - archive-only → TestArchive
  - no-referent → TestEmptyAndRefusal
"""

from __future__ import annotations

from shared.temporal_deictic_resolver import (
    AMBIGUITY_REFUSAL_THRESHOLD,
    DEFAULT_FRESH_LIVESTREAM_VISUAL_S,
    DEFAULT_FRESH_PUBLIC_SPEECH_S,
    Decision,
    DeicticReferenceQuery,
    ReferentCandidate,
    ReferentKind,
    ResolverResult,
    ScopeIntent,
    resolve_deictic_reference,
)

# ── Module surface ───────────────────────────────────────────────────


class TestModuleSurface:
    def test_referent_kind_taxonomy(self) -> None:
        assert {k.value for k in ReferentKind} == {
            "public_speech",
            "livestream_visual",
            "public_action_proposal",
            "archive",
            "private_speech",
            "private_screen",
        }

    def test_scope_intent_taxonomy(self) -> None:
        assert {s.value for s in ScopeIntent} == {
            "public_live",
            "public_archive",
            "private_dashboard",
            "internal_triage",
        }

    def test_decision_taxonomy(self) -> None:
        assert {d.value for d in Decision} == {
            "single_referent",
            "ambiguous",
            "stale",
            "private_only",
            "no_referent",
            "refused",
        }

    def test_default_thresholds(self) -> None:
        assert DEFAULT_FRESH_PUBLIC_SPEECH_S == 30.0
        assert DEFAULT_FRESH_LIVESTREAM_VISUAL_S == 10.0
        assert AMBIGUITY_REFUSAL_THRESHOLD == 0.40


# ── Fixture builders ─────────────────────────────────────────────────


def _public_speech(
    *, ref_id: str = "speech-1", age_s: float = 5.0, weight: float = 1.0
) -> ReferentCandidate:
    return ReferentCandidate(
        referent_id=ref_id,
        kind=ReferentKind.PUBLIC_SPEECH,
        aperture_ref="aperture.broadcast.live",
        captured_at_s=1000.0 - age_s,
        weight=weight,
        evidence_refs=("evt-1",),
        span_ref="span-1",
    )


def _livestream_visual(
    *, ref_id: str = "vis-1", age_s: float = 3.0, weight: float = 1.0
) -> ReferentCandidate:
    return ReferentCandidate(
        referent_id=ref_id,
        kind=ReferentKind.LIVESTREAM_VISUAL,
        aperture_ref="aperture.compositor.main",
        captured_at_s=1000.0 - age_s,
        weight=weight,
        evidence_refs=("frame-1",),
        span_ref="span-2",
    )


def _archive(
    *, ref_id: str = "arc-1", age_s: float = 3600.0, weight: float = 1.0
) -> ReferentCandidate:
    return ReferentCandidate(
        referent_id=ref_id,
        kind=ReferentKind.ARCHIVE,
        aperture_ref="aperture.vod.archive",
        captured_at_s=1000.0 - age_s,
        weight=weight,
    )


def _private_speech(
    *, ref_id: str = "priv-speech-1", age_s: float = 5.0, weight: float = 1.0
) -> ReferentCandidate:
    return ReferentCandidate(
        referent_id=ref_id,
        kind=ReferentKind.PRIVATE_SPEECH,
        aperture_ref="aperture.private.dashboard",
        captured_at_s=1000.0 - age_s,
        weight=weight,
    )


def _private_screen(
    *, ref_id: str = "priv-scr-1", age_s: float = 5.0, weight: float = 1.0
) -> ReferentCandidate:
    return ReferentCandidate(
        referent_id=ref_id,
        kind=ReferentKind.PRIVATE_SCREEN,
        aperture_ref="aperture.private.editor",
        captured_at_s=1000.0 - age_s,
        weight=weight,
    )


def _query(
    *, scope: ScopeIntent = ScopeIntent.PUBLIC_LIVE, now_s: float = 1000.0
) -> DeicticReferenceQuery:
    return DeicticReferenceQuery(
        utterance_text="what you just said on stream",
        scope_intent=scope,
        now_s=now_s,
    )


# ── Single-referent (public speech, fresh) ──────────────────────────


class TestPublicSpeech:
    def test_fresh_public_speech_resolves(self) -> None:
        result = resolve_deictic_reference(
            _query(),
            (_public_speech(age_s=5.0),),
        )
        assert result.decision is Decision.SINGLE_REFERENT
        assert result.referent_id == "speech-1"
        assert result.referent_kind is ReferentKind.PUBLIC_SPEECH
        assert result.aperture_ref == "aperture.broadcast.live"
        assert result.evidence_refs == ("evt-1",)
        assert result.span_ref == "span-1"

    def test_freshness_kwarg_override(self) -> None:
        # Tighten the speech freshness ceiling to 1s — a 5s-old
        # candidate now stales.
        result = resolve_deictic_reference(
            _query(),
            (_public_speech(age_s=5.0),),
            fresh_public_speech_s=1.0,
        )
        assert result.decision is Decision.STALE


# ── Livestream visual ─────────────────────────────────────────────────


class TestLivestreamVisual:
    def test_fresh_livestream_visual_resolves(self) -> None:
        result = resolve_deictic_reference(
            _query(),
            (_livestream_visual(age_s=3.0),),
        )
        assert result.decision is Decision.SINGLE_REFERENT
        assert result.referent_kind is ReferentKind.LIVESTREAM_VISUAL

    def test_livestream_visual_has_tighter_freshness(self) -> None:
        # 12s-old visual exceeds 10s ceiling → STALE.
        result = resolve_deictic_reference(
            _query(),
            (_livestream_visual(age_s=12.0),),
        )
        assert result.decision is Decision.STALE


# ── Archive ──────────────────────────────────────────────────────────


class TestArchive:
    def test_old_archive_still_resolves_for_archive_intent(self) -> None:
        # ARCHIVE has no freshness gate at this layer — even an
        # hour-old archive resolves cleanly.
        result = resolve_deictic_reference(
            _query(scope=ScopeIntent.PUBLIC_ARCHIVE),
            (_archive(age_s=3600.0),),
        )
        assert result.decision is Decision.SINGLE_REFERENT
        assert result.referent_kind is ReferentKind.ARCHIVE


# ── Private/public firewall ─────────────────────────────────────────


class TestPrivateSpeechFirewall:
    def test_private_speech_blocked_for_public_live(self) -> None:
        result = resolve_deictic_reference(
            _query(scope=ScopeIntent.PUBLIC_LIVE),
            (_private_speech(),),
        )
        assert result.decision is Decision.PRIVATE_ONLY
        assert "firewall_private_for_public_intent" in result.blockers

    def test_private_screen_blocked_for_public_archive(self) -> None:
        result = resolve_deictic_reference(
            _query(scope=ScopeIntent.PUBLIC_ARCHIVE),
            (_private_screen(),),
        )
        assert result.decision is Decision.PRIVATE_ONLY

    def test_private_speech_resolves_for_private_dashboard(self) -> None:
        result = resolve_deictic_reference(
            _query(scope=ScopeIntent.PRIVATE_DASHBOARD),
            (_private_speech(),),
        )
        assert result.decision is Decision.SINGLE_REFERENT
        assert result.referent_kind is ReferentKind.PRIVATE_SPEECH

    def test_private_and_public_candidates_public_intent_filters_private(
        self,
    ) -> None:
        # Mixed candidate set: private + public. Public intent should
        # filter the private and resolve to public.
        result = resolve_deictic_reference(
            _query(scope=ScopeIntent.PUBLIC_LIVE),
            (
                _private_speech(weight=2.0),
                _public_speech(weight=1.0),
            ),
        )
        assert result.decision is Decision.SINGLE_REFERENT
        assert result.referent_kind is ReferentKind.PUBLIC_SPEECH

    def test_private_dashboard_can_reference_public_event(self) -> None:
        # The firewall is one-way: private dashboards may legitimately
        # reference a public event.
        result = resolve_deictic_reference(
            _query(scope=ScopeIntent.PRIVATE_DASHBOARD),
            (_public_speech(),),
        )
        assert result.decision is Decision.SINGLE_REFERENT


# ── Staleness ────────────────────────────────────────────────────────


class TestStaleness:
    def test_stale_public_speech_returns_stale_decision(self) -> None:
        # 60s exceeds the 30s default ceiling.
        result = resolve_deictic_reference(
            _query(),
            (_public_speech(age_s=60.0),),
        )
        assert result.decision is Decision.STALE
        assert result.referent_id == "speech-1"  # still surfaced for clarification
        assert result.freshness_age_s == 60.0
        assert "freshness_exceeded" in result.blockers

    def test_stale_returns_freshest_stale_candidate(self) -> None:
        # Multiple stale candidates — the freshest one is surfaced
        # so the consumer can offer "you mean the one from <span>?".
        result = resolve_deictic_reference(
            _query(),
            (
                _public_speech(ref_id="old", age_s=120.0),
                _public_speech(ref_id="recent-stale", age_s=45.0),
            ),
        )
        assert result.decision is Decision.STALE
        assert result.referent_id == "recent-stale"

    def test_fresh_takes_precedence_over_stale(self) -> None:
        # When both fresh + stale candidates exist, fresh wins.
        result = resolve_deictic_reference(
            _query(),
            (
                _public_speech(ref_id="stale", age_s=60.0, weight=2.0),
                _public_speech(ref_id="fresh", age_s=5.0, weight=1.0),
            ),
        )
        assert result.decision is Decision.SINGLE_REFERENT
        assert result.referent_id == "fresh"


# ── Ambiguity ────────────────────────────────────────────────────────


class TestAmbiguity:
    def test_two_equal_weight_candidates_ambiguous(self) -> None:
        result = resolve_deictic_reference(
            _query(),
            (
                _public_speech(ref_id="a", weight=1.0),
                _public_speech(ref_id="b", weight=1.0),
            ),
        )
        assert result.decision is Decision.AMBIGUOUS
        assert result.ambiguity_score >= AMBIGUITY_REFUSAL_THRESHOLD
        assert "ambiguity_above_threshold" in result.blockers

    def test_dominant_weight_resolves_unambiguously(self) -> None:
        # 0.9 vs 0.1 → ambiguity score = 1.0 - (0.9 / 1.0) = 0.10
        # below the 0.40 threshold.
        result = resolve_deictic_reference(
            _query(),
            (
                _public_speech(ref_id="dominant", weight=0.9),
                _public_speech(ref_id="weak", weight=0.1),
            ),
        )
        assert result.decision is Decision.SINGLE_REFERENT
        assert result.referent_id == "dominant"

    def test_ambiguity_threshold_kwarg_override(self) -> None:
        # Equal-weight candidates with permissive threshold should
        # SINGLE_REFERENT instead of AMBIGUOUS.
        result = resolve_deictic_reference(
            _query(),
            (
                _public_speech(ref_id="a", weight=1.0),
                _public_speech(ref_id="b", weight=1.0),
            ),
            ambiguity_threshold=0.99,
        )
        assert result.decision is Decision.SINGLE_REFERENT


# ── No-referent / refused ────────────────────────────────────────────


class TestEmptyAndRefusal:
    def test_no_candidates_yields_no_referent(self) -> None:
        result = resolve_deictic_reference(_query(), ())
        assert result.decision is Decision.NO_REFERENT
        assert "no_candidates" in result.blockers

    def test_only_public_action_proposal_for_internal_triage_resolves(
        self,
    ) -> None:
        # PUBLIC_ACTION_PROPOSAL is in _PUBLIC_KINDS; INTERNAL_TRIAGE
        # accepts any kind. So this should resolve cleanly.
        candidate = ReferentCandidate(
            referent_id="action-1",
            kind=ReferentKind.PUBLIC_ACTION_PROPOSAL,
            aperture_ref="aperture.action",
            captured_at_s=995.0,  # 5s old
        )
        result = resolve_deictic_reference(
            _query(scope=ScopeIntent.INTERNAL_TRIAGE),
            (candidate,),
        )
        assert result.decision is Decision.SINGLE_REFERENT


# ── Result-shape contract ────────────────────────────────────────────


class TestResultShape:
    def test_single_referent_carries_all_fields(self) -> None:
        result = resolve_deictic_reference(_query(), (_public_speech(),))
        assert isinstance(result, ResolverResult)
        assert result.referent_id
        assert result.referent_kind is not None
        assert result.aperture_ref
        assert result.freshness_age_s is not None
        assert result.scope is ScopeIntent.PUBLIC_LIVE
        assert result.evidence_refs

    def test_no_referent_has_empty_referent_id(self) -> None:
        result = resolve_deictic_reference(_query(), ())
        assert result.referent_id == ""
        assert result.referent_kind is None
        assert result.freshness_age_s is None

    def test_scope_echoed_in_result(self) -> None:
        for scope in ScopeIntent:
            result = resolve_deictic_reference(
                DeicticReferenceQuery(
                    utterance_text="test",
                    scope_intent=scope,
                    now_s=1000.0,
                ),
                (),
            )
            assert result.scope is scope

    def test_blockers_tuple_iterable(self) -> None:
        result = resolve_deictic_reference(
            _query(),
            (_public_speech(age_s=60.0),),
        )
        assert isinstance(result.blockers, tuple)
        assert len(result.blockers) >= 1


# ── Decision matrix sweep ────────────────────────────────────────────


class TestDecisionMatrixSweep:
    def test_each_decision_reachable(self) -> None:
        # SINGLE_REFERENT
        r = resolve_deictic_reference(_query(), (_public_speech(),))
        assert r.decision is Decision.SINGLE_REFERENT

        # AMBIGUOUS
        r = resolve_deictic_reference(
            _query(),
            (
                _public_speech(ref_id="a", weight=1.0),
                _public_speech(ref_id="b", weight=1.0),
            ),
        )
        assert r.decision is Decision.AMBIGUOUS

        # STALE
        r = resolve_deictic_reference(
            _query(),
            (_public_speech(age_s=60.0),),
        )
        assert r.decision is Decision.STALE

        # PRIVATE_ONLY
        r = resolve_deictic_reference(
            _query(scope=ScopeIntent.PUBLIC_LIVE),
            (_private_speech(),),
        )
        assert r.decision is Decision.PRIVATE_ONLY

        # NO_REFERENT
        r = resolve_deictic_reference(_query(), ())
        assert r.decision is Decision.NO_REFERENT
