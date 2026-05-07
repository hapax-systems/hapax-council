"""Cross-surface private-to-public negative fixture matrix.

The fixture suite uses one distinctive private sentinel across the public
adapter classes named by the cc-task. It covers both the ``corporate_boundary``
axiom (raw private/corporate context must not cross into public surfaces) and
the ``interpersonal_transparency`` axiom (raw interpersonal/private-contact
context must not be persisted or amplified by public adapters). It is
intentionally test-only: every network or live surface is represented by pure
gates, temp files, dry-run paths, or mocked/public-event decisions.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agents.live_captions.reader import CaptionEvent
from agents.live_captions.routing import RoutedCaptionWriter, RoutingPolicy
from agents.live_captions.writer import CaptionWriter
from agents.metadata_composer.public_claim_gate import (
    ClaimEvidence,
    ClaimKind,
    Decision,
    evaluate_public_claim,
)
from agents.studio_compositor.youtube_description import assemble_description
from shared.caption_substrate_adapter import project_caption_substrate
from shared.cross_surface_event_contract import decide_cross_surface_fanout
from shared.director_read_model_public_event_gate import derive_public_event_moves
from shared.preprint_artifact import PreprintArtifact
from shared.private_to_public_bridge import (
    BridgeOutcome,
    BridgeRequest,
    _format_impingement_content,
    evaluate_bridge,
)
from shared.publication_artifact_public_event import build_publication_artifact_public_event
from shared.research_vehicle_public_event import (
    EventType,
    PublicEventChapterRef,
    PublicEventProvenance,
    PublicEventSource,
    PublicEventSurfacePolicy,
    ResearchVehiclePublicEvent,
    StateKind,
    Surface,
)
from shared.self_grounding_envelope import (
    ApertureSnapshot,
    AudioSafetySnapshot,
    AudioSafetyState,
    EgressSnapshot,
    EnvelopeInputs,
    LivestreamEgressState,
    ProgrammeAuthorizationState,
    ProgrammeSnapshot,
    RoleSnapshot,
    build_envelope_projection,
)
from shared.self_presence import AuthorityCeiling, ExposureMode, PublicPrivateMode

_DESTINATION_CHANNEL_PATH = (
    Path(__file__).resolve().parents[2]
    / "agents"
    / "hapax_daimonion"
    / "cpal"
    / "destination_channel.py"
)
_DESTINATION_CHANNEL_SPEC = importlib.util.spec_from_file_location(
    "_private_public_fixture_destination_channel",
    _DESTINATION_CHANNEL_PATH,
)
assert _DESTINATION_CHANNEL_SPEC is not None
assert _DESTINATION_CHANNEL_SPEC.loader is not None
_destination_channel = importlib.util.module_from_spec(_DESTINATION_CHANNEL_SPEC)
sys.modules[_DESTINATION_CHANNEL_SPEC.name] = _destination_channel
_DESTINATION_CHANNEL_SPEC.loader.exec_module(_destination_channel)
DestinationChannel = _destination_channel.DestinationChannel
resolve_playback_decision = _destination_channel.resolve_playback_decision

PRIVATE_SENTINEL = "PRIVATE_SENTINEL_DO_NOT_PUBLISH_20260505_XSURF_9F4C2A"
RAW_PRIVATE_TEXT = f"operator-private side note: {PRIVATE_SENTINEL}"
INTERPERSONAL_PRIVATE_TEXT = f"private viewer handle @opaque_contact: {PRIVATE_SENTINEL}"
TRANSFORMED_PUBLIC_TEXT = "Hapax observes a public-safe broadcast transition."
NOW = 1_800_000_000.0
GENERATED_AT = datetime(2026, 5, 5, 1, 10, tzinfo=UTC)

AXIOM_FIXTURE_TEXT: dict[str, str] = {
    "corporate_boundary": RAW_PRIVATE_TEXT,
    "interpersonal_transparency": INTERPERSONAL_PRIVATE_TEXT,
}

PUBLIC_SURFACE_MATRIX: dict[str, set[str]] = {
    "broadcast_speech_playback": {"livestream_voice"},
    "live_captions": {"captions", "youtube_captions"},
    "youtube_metadata": {
        "youtube_title",
        "youtube_description",
        "youtube_tags",
        "youtube_livechat",
        "youtube_cuepoints",
        "youtube_chapters",
        "youtube_captions",
        "youtube_shorts",
        "youtube_channel_sections",
        "youtube_channel_trailer",
        "pinned-comment",
    },
    "metadata_claims": {
        "live_now",
        "current_activity",
        "programme_role",
        "archive",
        "replay",
        "support",
        "monetization",
        "license_class",
        "publication_state",
        "disabled_issues",
    },
    "archive_public_events": {
        "archive",
        "replay",
        "omg_statuslog",
        "omg_weblog",
        "omg_now",
        "publication.artifact",
        "chronicle.high_salience",
        "aesthetic.frame_capture",
        "health",
    },
    "social_publication": {
        "arena",
        "mastodon",
        "bluesky",
        "discord",
        "zenodo",
        "github_readme",
        "github_profile",
        "github_release",
        "github_package",
        "github_pages",
        "internet-archive-ias3",
        "osf-preprint",
        "osf-prereg",
        "philarchive-deposit",
        "bridgy-webmention-publish",
        "alphaxiv-comments",
    },
}


def _assert_no_sentinel(value: object) -> None:
    dumped = json.dumps(value, default=str, sort_keys=True)
    assert PRIVATE_SENTINEL not in dumped


def _write_private_monitor_ready(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "bridge_nodes_present": True,
                "exact_target_present": True,
                "fallback_policy": "no_default_fallback",
                "operator_visible_reason": (
                    "Exact private monitor target and fail-closed bridge are present."
                ),
                "reason_code": "exact_private_monitor_bound",
                "sanitized": True,
                "state": "ready",
                "target_ref": "audio.yeti_monitor",
            }
        ),
        encoding="utf-8",
    )


def _role(*, public: bool) -> RoleSnapshot:
    if public:
        return RoleSnapshot(
            role_id="role:public-narrator",
            office="public_narrator",
            addressee_mode="public_audience",
            route_posture="broadcast_authorized",
        )
    return RoleSnapshot(
        role_id="role:private-assistant",
        office="private_assistant",
        addressee_mode="operator",
        route_posture="private_default",
    )


def _aperture(*, public: bool, blocked: bool = False) -> ApertureSnapshot:
    if blocked:
        return ApertureSnapshot(
            aperture_id="aperture:blocked-test",
            kind="private_assistant",
            exposure_mode=ExposureMode.BLOCKED,
            public_private_mode=PublicPrivateMode.PUBLIC_FORBIDDEN,
            requires_programme_authorization=False,
            requires_audio_safety=False,
            requires_egress_witness=False,
        )
    if public:
        return ApertureSnapshot(
            aperture_id="aperture:public-broadcast-voice",
            kind="public_broadcast_voice",
            exposure_mode=ExposureMode.PUBLIC_CANDIDATE,
            public_private_mode=PublicPrivateMode.PUBLIC_CANDIDATE,
            requires_programme_authorization=True,
            requires_audio_safety=True,
            requires_egress_witness=True,
        )
    return ApertureSnapshot(
        aperture_id="aperture:private-assistant",
        kind="private_assistant",
        exposure_mode=ExposureMode.PRIVATE,
        public_private_mode=PublicPrivateMode.PRIVATE,
        requires_programme_authorization=False,
        requires_audio_safety=False,
        requires_egress_witness=False,
    )


def _envelope(
    *,
    public: bool,
    blocked: bool = False,
    private_risk: bool = False,
):
    kwargs: dict[str, Any] = {
        "role": _role(public=public),
        "aperture": _aperture(public=public, blocked=blocked),
    }
    if public:
        kwargs.update(
            {
                "programme": ProgrammeSnapshot(
                    programme_id="prog:test",
                    authorization_state=ProgrammeAuthorizationState.FRESH,
                    authorized_at="2026-05-05T01:00:00Z",
                    expires_at="2026-05-05T02:00:00Z",
                ),
                "audio_safety": AudioSafetySnapshot(
                    state=AudioSafetyState.SAFE,
                    evidence_refs=("audio:safe",),
                ),
                "egress": EgressSnapshot(
                    state=LivestreamEgressState.WITNESSED,
                    evidence_refs=("egress:obs",),
                ),
                "source_context_refs": ("ctx:autonomous-narration",),
                "wcs_snapshot_refs": ("wcs:snapshot-1",),
                "chronicle_refs": ("chronicle:event-1",),
            }
        )
    if private_risk:
        kwargs["private_risk_flags"] = ("operator_private_context",)
    return build_envelope_projection(EnvelopeInputs(**kwargs))


def _surface_policy(
    *,
    allowed: list[Surface],
    denied: list[Surface] | None = None,
    fallback_action: str = "hold",
    dry_run_reason: str | None = None,
) -> PublicEventSurfacePolicy:
    return PublicEventSurfacePolicy(
        allowed_surfaces=allowed,
        denied_surfaces=denied or [],
        claim_live=True,
        claim_archive=True,
        claim_monetizable=False,
        requires_egress_public_claim=True,
        requires_audio_safe=True,
        requires_provenance=True,
        requires_human_review=False,
        rate_limit_key="private-public-fixture",
        redaction_policy="operator_referent",
        fallback_action=fallback_action,  # type: ignore[arg-type]
        dry_run_reason=dry_run_reason,
    )


def _private_rvpe(
    *,
    event_type: EventType,
    state_kind: StateKind,
    allowed: list[Surface],
    chapter_label: str = RAW_PRIVATE_TEXT,
) -> ResearchVehiclePublicEvent:
    event_id = f"rvpe:private_public_fixture:{event_type.replace('.', '_')}"
    return ResearchVehiclePublicEvent(
        event_id=event_id,
        event_type=event_type,
        occurred_at="2026-05-05T01:00:00Z",
        broadcast_id="broadcast-test",
        programme_id="prog:test",
        condition_id=None,
        source=PublicEventSource(
            producer="tests.private_public_cross_surface",
            substrate_id="fixture",
            task_anchor="private-public-cross-surface-negative-fixtures",
            evidence_ref="tests#private-public-fixture",
            freshness_ref="tests.age_s",
        ),
        salience=0.72,
        state_kind=state_kind,
        rights_class="operator_original",
        privacy_class="operator_private",
        provenance=PublicEventProvenance(
            token="fixture-token",
            generated_at="2026-05-05T01:00:01Z",
            producer="tests.private_public_cross_surface",
            evidence_refs=["tests.fixture.evidence"],
            rights_basis="operator original fixture",
            citation_refs=[],
        ),
        public_url="https://example.invalid/public-fixture",
        frame_ref=None,
        chapter_ref=PublicEventChapterRef(
            kind="chapter",
            label=chapter_label,
            timecode="00:00",
            source_event_id=event_id,
        ),
        attribution_refs=[],
        surface_policy=_surface_policy(allowed=allowed),
    )


def test_fixture_matrix_covers_named_public_surface_groups() -> None:
    required_groups = {
        "broadcast_speech_playback",
        "live_captions",
        "youtube_metadata",
        "metadata_claims",
        "archive_public_events",
        "social_publication",
    }
    assert set(PUBLIC_SURFACE_MATRIX) == required_groups
    assert all(PUBLIC_SURFACE_MATRIX.values())
    assert set(AXIOM_FIXTURE_TEXT) == {"corporate_boundary", "interpersonal_transparency"}
    assert all(PRIVATE_SENTINEL in text for text in AXIOM_FIXTURE_TEXT.values())


@pytest.mark.parametrize(
    ("case", "bridge_request", "expected"),
    [
        (
            "private_response",
            BridgeRequest(narrative_text=RAW_PRIVATE_TEXT, envelope=_envelope(public=False)),
            BridgeOutcome.PRIVATE_RESPONSE,
        ),
        (
            "dry_run",
            BridgeRequest(
                narrative_text=RAW_PRIVATE_TEXT,
                envelope=_envelope(public=True, private_risk=True),
                explicit_public_intent=True,
            ),
            BridgeOutcome.DRY_RUN,
        ),
        (
            "held",
            BridgeRequest(
                narrative_text=RAW_PRIVATE_TEXT,
                programme_id="prog:other",
                envelope=_envelope(public=True),
                explicit_public_intent=True,
            ),
            BridgeOutcome.HELD,
        ),
        (
            "refusal",
            BridgeRequest(
                narrative_text=RAW_PRIVATE_TEXT,
                envelope=_envelope(public=False, blocked=True),
                explicit_public_intent=True,
            ),
            BridgeOutcome.REFUSAL,
        ),
    ],
)
def test_negative_bridge_outcomes_do_not_authorize_public(
    case: str,
    bridge_request: BridgeRequest,
    expected: BridgeOutcome,
) -> None:
    result = evaluate_bridge(bridge_request)

    assert case == result.outcome.value
    assert result.outcome is expected
    assert result.public_broadcast_intent is False
    assert result.route_posture != "broadcast_authorized"
    assert result.claim_ceiling is not AuthorityCeiling.PUBLIC_GATE_REQUIRED


def test_bridge_positive_fixture_is_transformed_and_metadata_backed() -> None:
    request = BridgeRequest(
        narrative_text=TRANSFORMED_PUBLIC_TEXT,
        programme_id="prog:test",
        speech_event_id="speech:fixture",
        impulse_id="impulse:fixture",
        triad_ids=("triad:fixture",),
        operator_referent="Oudepode",
        envelope=_envelope(public=True),
        requested_aperture_id="aperture:public-broadcast-voice",
        explicit_public_intent=True,
    )

    result = evaluate_bridge(request)
    content = _format_impingement_content(request, result)

    assert result.outcome is BridgeOutcome.PUBLIC_ACTION_PROPOSAL
    assert content["bridge_outcome"] == "public_action_proposal"
    assert content["public_broadcast_intent"] is True
    assert content["route_posture"] == "broadcast_authorized"
    assert content["programme_authorization"]["authorized"] is True
    assert content["programme_authorization_ref"] == "programme:prog:test"
    assert content["evidence_refs"]
    _assert_no_sentinel(content)


def test_private_sentinel_does_not_reach_broadcast_playback(tmp_path: Path) -> None:
    request = BridgeRequest(narrative_text=RAW_PRIVATE_TEXT, envelope=_envelope(public=False))
    result = evaluate_bridge(request)
    content = _format_impingement_content(request, result)
    private_status_path = tmp_path / "private-monitor-target.json"
    _write_private_monitor_ready(private_status_path)

    decision = resolve_playback_decision(
        SimpleNamespace(source="operator.sidechat", content=content),
        private_monitor_status_path=private_status_path,
        now=private_status_path.stat().st_mtime,
    )

    assert decision.destination is DestinationChannel.PRIVATE
    assert decision.allowed is True
    assert decision.safety_gate["explicit_broadcast_intent"] is False


def test_private_sentinel_caption_routing_blocks_jsonl_and_substrate(tmp_path) -> None:
    captions_path = tmp_path / "captions.jsonl"
    policy = RoutingPolicy(
        allow=frozenset({"oudepode"}),
        deny=frozenset({"operator_private"}),
        default_allow=False,
    )
    routed = RoutedCaptionWriter(
        policy=policy,
        writer=CaptionWriter(captions_path=captions_path),
    )

    emitted = routed.emit(
        ts=NOW,
        text=RAW_PRIVATE_TEXT,
        duration_ms=1200,
        speaker="operator_private",
    )
    candidates, rejections = project_caption_substrate(
        [CaptionEvent(ts=NOW, text=RAW_PRIVATE_TEXT, duration_ms=1200, speaker="operator_private")],
        routing=policy,
        now=NOW,
        av_offset_s=0.18,
    )

    assert emitted is False
    assert not captions_path.exists()
    assert candidates == []
    assert len(rejections) == 1
    assert rejections[0].reason == "denied_routing"


def test_public_claim_gate_refuses_private_sentinel_without_live_witness() -> None:
    decision = evaluate_public_claim(
        ClaimKind.LIVE_NOW,
        ClaimEvidence(
            broadcast_id=PRIVATE_SENTINEL,
            broadcast_age_s=120.0,
            egress_active=False,
        ),
    )

    assert decision.decision is Decision.REFUSE
    assert decision.allows_emission is False
    _assert_no_sentinel(decision)


@pytest.mark.parametrize(
    ("aperture", "action", "surface", "event_type", "state_kind"),
    [
        ("youtube", "publish", "youtube_captions", "caption.segment", "caption_text"),
        (
            "youtube_channel_trailer",
            "link",
            "youtube_channel_trailer",
            "broadcast.boundary",
            "live_state",
        ),
        ("omg_statuslog", "publish", "omg_statuslog", "omg.statuslog", "public_post"),
        ("omg_weblog", "publish", "omg_weblog", "publication.artifact", "archive_artifact"),
        ("arena", "publish", "arena", "arena_block.candidate", "public_post"),
        ("mastodon", "publish", "mastodon", "chronicle.high_salience", "research_observation"),
        ("bluesky", "publish", "bluesky", "chronicle.high_salience", "research_observation"),
        ("discord", "publish", "discord", "chronicle.high_salience", "research_observation"),
        ("shorts", "publish", "youtube_shorts", "shorts.upload", "short_form"),
        ("archive", "archive", "archive", "archive.segment", "archive_artifact"),
        ("replay", "replay", "replay", "archive.segment", "archive_artifact"),
    ],
)
@pytest.mark.parametrize("axiom", sorted(AXIOM_FIXTURE_TEXT))
def test_operator_private_public_events_are_denied_by_every_fanout_aperture(
    axiom,
    aperture,
    action,
    surface,
    event_type,
    state_kind,
) -> None:
    event = _private_rvpe(
        event_type=event_type,
        state_kind=state_kind,
        allowed=[surface],
        chapter_label=AXIOM_FIXTURE_TEXT[axiom],
    )

    decision = decide_cross_surface_fanout(event, aperture, action)

    assert decision.decision == "deny"
    assert "privacy_blocked" in decision.reasons
    _assert_no_sentinel(decision)


def test_director_moves_hold_operator_private_sentinel_event() -> None:
    event = _private_rvpe(
        event_type="caption.segment",
        state_kind="caption_text",
        allowed=["youtube_captions"],
    )

    moves = derive_public_event_moves([event])

    assert len(moves) == 1
    assert moves[0].state != "allow"
    assert "privacy_class_operator_private" in moves[0].blocker_reasons
    _assert_no_sentinel(moves)


def test_publication_artifact_public_event_omits_private_sentinel_fields(tmp_path) -> None:
    artifact = PreprintArtifact(
        slug="sentinel-fixture",
        title=f"Private title {PRIVATE_SENTINEL}",
        abstract=f"Private abstract {PRIVATE_SENTINEL}",
        body_md=f"# Private body\n\n{PRIVATE_SENTINEL}",
        surfaces_targeted=["zenodo-refusal-deposit", "omg-weblog"],
    )
    artifact.mark_approved(by_referent="Oudepode")

    decision = build_publication_artifact_public_event(
        artifact,
        artifact_fingerprint="fixture-fingerprint",
        state_root=tmp_path,
        stage="inbox",
        generated_at=GENERATED_AT,
    )

    assert decision.public_event is not None
    _assert_no_sentinel(decision.public_event)
    assert artifact.slug in decision.public_event.model_dump_json()


def test_refused_publication_surfaces_are_not_dispatchable() -> None:
    from agents.publication_bus.surface_registry import (
        SURFACE_REGISTRY,
        AutomationStatus,
        dispatch_registry,
    )

    dispatchable = dispatch_registry()
    assert SURFACE_REGISTRY["discord-webhook"].automation_status is AutomationStatus.REFUSED
    assert SURFACE_REGISTRY["alphaxiv-comments"].automation_status is AutomationStatus.REFUSED
    assert "discord-webhook" not in dispatchable
    assert "alphaxiv-comments" not in dispatchable


def test_public_claim_gate_blocks_text_bearing_private_activity_sentinel() -> None:
    """Text-bearing public-claim evidence must REFUSE when the value
    carries a `PRIVATE_SENTINEL_DO_NOT_PUBLISH_*` token.

    Closed by ``cc-task metadata-current-activity-private-sentinel-text-hygiene``:
    ``_eval_current_activity`` scans the evidence string for the
    sentinel pattern and fails CLOSED before any emission.
    """
    decision = evaluate_public_claim(
        ClaimKind.CURRENT_ACTIVITY,
        ClaimEvidence(current_activity=RAW_PRIVATE_TEXT),
    )

    assert decision.allows_emission is False


def test_public_claim_gate_blocks_text_bearing_private_programme_role_sentinel() -> None:
    """The other free-text claim kind, ``programme_role``, must also
    REFUSE when carrying a ``PRIVATE_SENTINEL_DO_NOT_PUBLISH_*`` token.
    Same fail-CLOSED posture as ``current_activity``.
    """
    decision = evaluate_public_claim(
        ClaimKind.PROGRAMME_ROLE,
        ClaimEvidence(programme_role=RAW_PRIVATE_TEXT, programme_role_age_s=1.0),
    )

    assert decision.allows_emission is False


def test_youtube_description_assembler_blocks_private_sentinel() -> None:
    """YouTube description assembler must redact every
    ``PRIVATE_SENTINEL_DO_NOT_PUBLISH_*`` token before composition.

    Closed by ``cc-task youtube-description-assembler-private-sentinel-filtering``:
    ``assemble_description`` runs ``_redact_private_sentinels`` on every
    text input (and attribution title/url) so the rendered description
    cannot leak the sentinel to the public YouTube surface.
    """
    description = assemble_description(
        condition_id=PRIVATE_SENTINEL,
        claim_id=None,
        objective_title=RAW_PRIVATE_TEXT,
        substrate_model="fixture",
    )

    assert PRIVATE_SENTINEL not in description
