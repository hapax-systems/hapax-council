"""Classifier-label grounding normalizer envelope.

Per cc-task ``archive-and-classifier-label-grounding-normalizer``
(WSJF 9.2). Legacy classifiers in ``agents/video_processor.py``,
``agents/audio_processor.py``, ``agents/studio_compositor/
chat_classifier.py``, ``agents/studio_compositor/scene_classifier.py``,
``agents/hapax_daimonion/activity_mode.py``, etc. emit raw labels
(scene tags, chat tier, activity mode, value scores, camera
recommendations, circadian alignment, album / track / lyrics) as
plain strings or dicts. Without ceilings + evidence + freshness, those
labels drift into public-truth territory — a posture the constitution
explicitly refuses ("not an expert system; raw classifier output is
prior, not verdict").

This module ships the **wrapping envelope** every classifier consults
before any consumer (demo, replay, dataset, monetization, public
broadcast) can use the label. Phase 0 (this PR) ships the schema +
fixture taxonomy; Phase 1 follow-on wires the listed agents to wrap
their raw output and have the consumers consult ``can_publish_label``.

Spec reference (acceptance criteria from cc-task):

* Raw value_score / scene / chat tier / activity mode / camera
  recommendation / circadian alignment represented as priors with
  authority ceilings.
* Public/archive/replay/demo/dataset/monetization consumers REQUIRE
  WCS evidence + public-event refs + rights/privacy posture +
  freshness + correction path before using.
* Failed scene classification does NOT publish a scene label.
* Chat ``high_value`` / ``research_relevant`` are aggregate/triage
  only.
* Camera recommendations route through WCS gates before affecting
  public visual posture.
* Album/track/lyric require playback witness + rights gate.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass

# ── Constants ────────────────────────────────────────────────────────

#: Default freshness ceiling (seconds). Labels older than this are
#: stale and cannot publish to PUBLIC consumers regardless of other
#: evidence. PRIVATE / TRIAGE consumers may still consult them.
DEFAULT_FRESHNESS_S: float = 30.0

#: Minimum classifier confidence for a label to count as anything
#: above DIAGNOSTIC. Raw zero-confidence output is always diagnostic.
MIN_CONFIDENCE_FOR_PRIOR: float = 0.30


class LabelKind(enum.StrEnum):
    """The taxonomy of classifier labels the envelope wraps.

    The kinds map 1:1 to the legacy classifier modules listed in the
    cc-task acceptance criteria. Phase 1 wires each module to wrap
    its output in this envelope.
    """

    VALUE_SCORE = "value_score"
    SCENE = "scene"
    CHAT_TIER = "chat_tier"
    ACTIVITY_MODE = "activity_mode"
    CAMERA_RECOMMENDATION = "camera_recommendation"
    CIRCADIAN_ALIGNMENT = "circadian_alignment"
    ALBUM = "album"
    TRACK = "track"
    LYRIC = "lyric"


class AuthorityCeiling(enum.StrEnum):
    """Maximum claim authority the label can authorize.

    Mirrors the PerceptualField + livestream-role taxonomy so a single
    consumer reads one ceiling vocabulary across percept fields,
    speech acts, and classifier labels.
    """

    NONE = "none"
    DIAGNOSTIC = "diagnostic"
    """Triage / debug only; never reaches a consumer surface."""

    PRIVATE_TRIAGE = "private_triage"
    """Internal heuristic / prior; private routing only."""

    AGGREGATE = "aggregate"
    """May contribute to aggregate analytics / posteriors; never names
    an individual or surfaces as a single-source claim."""

    PUBLIC_VISIBLE = "public_visible"
    """May render in operator-private + public-archive surfaces."""

    PUBLIC_LIVE = "public_live"
    """May render on the live broadcast (highest authority)."""


class ConsumerKind(enum.StrEnum):
    """Where the label is being routed.

    Each consumer has its own minimum-evidence floor enforced by
    ``can_publish_label``.
    """

    PRIVATE = "private"
    """Internal log / triage / debug; no audience exposure."""

    DASHBOARD = "dashboard"
    """Operator-only dashboard surface."""

    PUBLIC_ARCHIVE = "public_archive"
    """VOD / replay write."""

    PUBLIC_LIVE = "public_live"
    """Live broadcast egress."""

    DEMO = "demo"
    """Public demo / sizzle reel."""

    DATASET = "dataset"
    """Research / training dataset publication."""

    MONETIZATION = "monetization"
    """Sponsor / advertiser / revenue surface."""


@dataclass(frozen=True)
class LabelEnvelope:
    """Wrapped classifier label — schema for the cc-task contract.

    All fields are explicit; the envelope cannot be constructed
    without declaring ceiling, evidence, and rights/privacy posture.
    Defaults bias toward fail-CLOSED:

    * confidence ``0.0`` → DIAGNOSTIC ceiling regardless of declared
      ceiling.
    * ``classifier_failed=True`` → DIAGNOSTIC ceiling + label is
      NEVER consumable by anything but PRIVATE.
    * ``rights_clear`` defaults False — rights-gated kinds (album,
      track, lyric) refuse without explicit clearance.
    * ``privacy_clear`` defaults False — person-bearing kinds refuse
      without explicit clearance.
    """

    label_kind: LabelKind
    raw_value: str
    """The classifier's raw output (label name, scene id, tier name,
    etc). Empty string when classifier_failed=True."""

    confidence: float
    """Classifier confidence [0.0, 1.0]. Below
    :data:`MIN_CONFIDENCE_FOR_PRIOR` the envelope is downgraded to
    DIAGNOSTIC."""

    declared_ceiling: AuthorityCeiling
    """The ceiling the classifier intended for this label. The
    effective ceiling (after fail-CLOSED downgrades) is exposed via
    :attr:`effective_ceiling`."""

    captured_at_s: float
    """Wall-clock timestamp of when the classifier produced the label
    (``time.time()``). Used by ``can_publish_label`` to enforce
    freshness."""

    classifier_failed: bool = False
    """When True the label is unconsumable; only DIAGNOSTIC ceiling
    accepted; ``raw_value`` should be empty."""

    wcs_evidence_ref: str = ""
    """Reference to a WCS evidence row supporting the label.
    Required for PUBLIC consumers."""

    public_event_ref: str = ""
    """Reference to a chronicle public-event row publishing the
    label. Required for PUBLIC_LIVE + PUBLIC_ARCHIVE."""

    rights_clear: bool = False
    """Operator-confirmed rights posture. Required for ALBUM /
    TRACK / LYRIC kinds at any non-PRIVATE consumer."""

    privacy_clear: bool = False
    """Operator-confirmed privacy posture (no person-data leak).
    Required for chat-classifier kinds and camera recommendations
    at any non-PRIVATE consumer."""

    correction_path_ref: str = ""
    """Pointer to the correction surface (correction articulation
    record, refusal-annex) consumers should display alongside the
    label. Empty allowed; consumers that surface labels SHOULD
    populate when known."""

    @property
    def effective_ceiling(self) -> AuthorityCeiling:
        """Apply fail-CLOSED downgrades to ``declared_ceiling``.

        Three downgrade triggers:

        * ``classifier_failed=True`` → DIAGNOSTIC.
        * ``confidence < MIN_CONFIDENCE_FOR_PRIOR`` → DIAGNOSTIC.
        * Otherwise the declared ceiling is kept (further consumer-
          side gating handled by ``can_publish_label``).
        """
        if self.classifier_failed:
            return AuthorityCeiling.DIAGNOSTIC
        if self.confidence < MIN_CONFIDENCE_FOR_PRIOR:
            return AuthorityCeiling.DIAGNOSTIC
        return self.declared_ceiling

    def is_fresh(
        self,
        *,
        now_s: float | None = None,
        freshness_s: float = DEFAULT_FRESHNESS_S,
    ) -> bool:
        """Whether the label is within the freshness window."""
        ts = time.time() if now_s is None else now_s
        return (ts - self.captured_at_s) <= freshness_s


@dataclass(frozen=True)
class PublishVerdict:
    """Verdict from :func:`can_publish_label`."""

    allowed: bool
    reason: str
    """Short rationale; on REFUSE this names the missing evidence
    so the consumer can either skip the label or surface a
    correction articulation."""


# ── Per-kind required-evidence map ───────────────────────────────────

#: Kinds that require ``rights_clear=True`` for any non-PRIVATE
#: consumer (because they reference upstream copyrighted work).
_RIGHTS_GATED_KINDS: frozenset[LabelKind] = frozenset(
    {LabelKind.ALBUM, LabelKind.TRACK, LabelKind.LYRIC}
)

#: Kinds that require ``privacy_clear=True`` for any non-PRIVATE
#: consumer (because they may reference a non-operator person or
#: privacy-sensitive scene).
_PRIVACY_GATED_KINDS: frozenset[LabelKind] = frozenset(
    {
        LabelKind.CHAT_TIER,
        LabelKind.CAMERA_RECOMMENDATION,
        LabelKind.SCENE,
    }
)

#: Consumer kinds that require non-empty ``wcs_evidence_ref``.
_WCS_REQUIRED_CONSUMERS: frozenset[ConsumerKind] = frozenset(
    {
        ConsumerKind.PUBLIC_ARCHIVE,
        ConsumerKind.PUBLIC_LIVE,
        ConsumerKind.DEMO,
        ConsumerKind.DATASET,
        ConsumerKind.MONETIZATION,
    }
)

#: Consumer kinds that require non-empty ``public_event_ref`` (the
#: label must be backed by a publishable chronicle event).
_PUBLIC_EVENT_REQUIRED_CONSUMERS: frozenset[ConsumerKind] = frozenset(
    {ConsumerKind.PUBLIC_LIVE, ConsumerKind.PUBLIC_ARCHIVE}
)

#: Mapping from consumer to the minimum effective ceiling it accepts.
_CONSUMER_MIN_CEILING: dict[ConsumerKind, AuthorityCeiling] = {
    ConsumerKind.PRIVATE: AuthorityCeiling.DIAGNOSTIC,
    ConsumerKind.DASHBOARD: AuthorityCeiling.PRIVATE_TRIAGE,
    ConsumerKind.DATASET: AuthorityCeiling.AGGREGATE,
    ConsumerKind.PUBLIC_ARCHIVE: AuthorityCeiling.PUBLIC_VISIBLE,
    ConsumerKind.PUBLIC_LIVE: AuthorityCeiling.PUBLIC_LIVE,
    ConsumerKind.DEMO: AuthorityCeiling.PUBLIC_VISIBLE,
    ConsumerKind.MONETIZATION: AuthorityCeiling.PUBLIC_VISIBLE,
}

#: Linear order of ceilings, used by the consumer-min check.
_CEILING_ORDER: dict[AuthorityCeiling, int] = {
    AuthorityCeiling.NONE: 0,
    AuthorityCeiling.DIAGNOSTIC: 1,
    AuthorityCeiling.PRIVATE_TRIAGE: 2,
    AuthorityCeiling.AGGREGATE: 3,
    AuthorityCeiling.PUBLIC_VISIBLE: 4,
    AuthorityCeiling.PUBLIC_LIVE: 5,
}


def _ceiling_meets(actual: AuthorityCeiling, minimum: AuthorityCeiling) -> bool:
    return _CEILING_ORDER[actual] >= _CEILING_ORDER[minimum]


def can_publish_label(
    envelope: LabelEnvelope,
    *,
    consumer: ConsumerKind,
    now_s: float | None = None,
    freshness_s: float = DEFAULT_FRESHNESS_S,
) -> PublishVerdict:
    """Decide whether ``envelope`` may publish to ``consumer``.

    Fail-CLOSED on every missing evidence axis (rights, privacy, WCS,
    public-event, freshness, ceiling). The verdict's ``reason``
    names the failing axis so the consumer can construct a refusal
    articulation rather than silently dropping the label.

    The freshness ceiling is a kwarg so per-consumer surfaces can
    tighten or loosen the window; default 30s comes from
    :data:`DEFAULT_FRESHNESS_S`.
    """
    # Classifier-failed labels are PRIVATE-only.
    if envelope.classifier_failed and consumer is not ConsumerKind.PRIVATE:
        return PublishVerdict(
            allowed=False,
            reason="classifier_failed=True; label only consumable by PRIVATE",
        )

    # Effective ceiling must meet consumer floor.
    consumer_min = _CONSUMER_MIN_CEILING[consumer]
    if not _ceiling_meets(envelope.effective_ceiling, consumer_min):
        return PublishVerdict(
            allowed=False,
            reason=(
                f"effective_ceiling={envelope.effective_ceiling.value} "
                f"below {consumer.value} consumer floor "
                f"({consumer_min.value})"
            ),
        )

    # PRIVATE consumer accepts anything that passed the above.
    if consumer is ConsumerKind.PRIVATE:
        return PublishVerdict(
            allowed=True,
            reason=f"private consumer; ceiling={envelope.effective_ceiling.value}",
        )

    # Rights-gated kinds need rights_clear for non-PRIVATE consumers.
    if envelope.label_kind in _RIGHTS_GATED_KINDS and not envelope.rights_clear:
        return PublishVerdict(
            allowed=False,
            reason=(
                f"label_kind={envelope.label_kind.value} requires "
                f"rights_clear=True for {consumer.value} consumer"
            ),
        )

    # Privacy-gated kinds need privacy_clear for non-PRIVATE consumers.
    if envelope.label_kind in _PRIVACY_GATED_KINDS and not envelope.privacy_clear:
        return PublishVerdict(
            allowed=False,
            reason=(
                f"label_kind={envelope.label_kind.value} requires "
                f"privacy_clear=True for {consumer.value} consumer"
            ),
        )

    # WCS evidence required for the relevant consumers.
    if consumer in _WCS_REQUIRED_CONSUMERS and not envelope.wcs_evidence_ref:
        return PublishVerdict(
            allowed=False,
            reason=(f"{consumer.value} consumer requires non-empty wcs_evidence_ref"),
        )

    # Public-event ref required for live + archive.
    if consumer in _PUBLIC_EVENT_REQUIRED_CONSUMERS and not envelope.public_event_ref:
        return PublishVerdict(
            allowed=False,
            reason=(f"{consumer.value} consumer requires non-empty public_event_ref"),
        )

    # Freshness check (PUBLIC consumers only — dashboard/dataset can
    # consult stale priors).
    if consumer in _WCS_REQUIRED_CONSUMERS and not envelope.is_fresh(
        now_s=now_s, freshness_s=freshness_s
    ):
        return PublishVerdict(
            allowed=False,
            reason=(f"{consumer.value} consumer requires fresh label (window={freshness_s}s)"),
        )

    return PublishVerdict(
        allowed=True,
        reason=(
            f"{consumer.value} consumer; ceiling={envelope.effective_ceiling.value}, "
            f"all evidence axes satisfied"
        ),
    )


__all__ = [
    "DEFAULT_FRESHNESS_S",
    "MIN_CONFIDENCE_FOR_PRIOR",
    "AuthorityCeiling",
    "ConsumerKind",
    "LabelEnvelope",
    "LabelKind",
    "PublishVerdict",
    "can_publish_label",
]
