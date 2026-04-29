"""Regression tests for the director runtime vocabulary builder."""

from __future__ import annotations

import json
from pathlib import Path

from shared.cameras import CameraSpec
from shared.claim import Claim, EvidenceRef, TemporalProfile
from shared.director_vocabulary import (
    STABLE_DIRECTOR_VERBS,
    DirectorRightsState,
    PrivateControlBinding,
    build_director_vocabulary,
    visible_ward_ids_from_properties,
)

NOW = 1_777_426_200.0


def _rights_public() -> DirectorRightsState:
    return DirectorRightsState(
        egress_public_claim_allowed=True,
        audio_safe=True,
        privacy_safe=True,
        rights_safe=True,
        monetization_safe=True,
        detail="test public floor",
    )


def _substrate(
    substrate_id: str,
    *,
    status: str = "public-live",
    verbs: list[str] | None = None,
    claim_live: bool = True,
    fallback_reason: str = "substrate unavailable",
) -> dict:
    return {
        "schema_version": 1,
        "substrate_id": substrate_id,
        "display_name": substrate_id.replace("_", " ").title(),
        "substrate_type": "spectacle_lane",
        "producer": {"owner": "test", "state": "state", "evidence": "evidence"},
        "consumer": {"owner": "test", "state": "state", "evidence": "evidence"},
        "freshness_ttl_s": 30,
        "rights_class": "operator_original",
        "provenance_token": f"{substrate_id}.event",
        "privacy_class": "public_safe",
        "public_private_modes": ["private", "dry_run", "public_live"],
        "render_target": "test-render-target",
        "director_vocabulary": [substrate_id.replace("_", " ")],
        "director_affordances": verbs or ["foreground", "hold", "mark boundary"],
        "programme_bias_hooks": ["programme_boundary"],
        "objective_links": ["test-objective"],
        "public_claim_permissions": {
            "claim_live": claim_live,
            "claim_archive": True,
            "claim_monetizable": False,
            "requires_egress_public_claim": True,
            "requires_audio_safe": True,
            "requires_provenance": True,
            "requires_operator_action": False,
        },
        "health_signal": {
            "owner": "test-health",
            "status_ref": f"{substrate_id}.status",
            "freshness_ref": f"{substrate_id}.age_s",
        },
        "fallback": {"mode": "dry_run_badge", "reason": fallback_reason},
        "kill_switch_behavior": {
            "trigger": "test trigger",
            "action": "suppress",
            "operator_recovery": "repair evidence",
        },
        "integration_status": status,
    }


def _lane(
    lane_id: str,
    *,
    state: str = "mounted",
    mounted: bool = True,
    renderable: bool = True,
    verbs: list[str] | None = None,
    fallback_reason: str = "lane unavailable",
) -> dict:
    return {
        "schema_version": 1,
        "lane_id": lane_id,
        "display_name": lane_id.replace("_", " ").title(),
        "lane_kind": "ward",
        "content_substrate_refs": [lane_id],
        "state": state,
        "mounted": mounted,
        "renderable": renderable,
        "renderability_evidence": {
            "owner": "test",
            "status_ref": f"{lane_id}.state",
            "freshness_ref": f"{lane_id}.age_s",
            "evidence_kind": "health_signal",
        },
        "claim_bearing": "public_live" if state == "public-live" else "private",
        "rights_risk": "none",
        "consent_risk": "none",
        "monetization_risk": "low",
        "director_verbs": verbs or list(STABLE_DIRECTOR_VERBS),
        "programme_hooks": ["programme_boundary"],
        "fallback": {"mode": "no_op_explain", "reason": fallback_reason},
        "public_claim_allowed": state == "public-live",
    }


def test_stable_verbs_preserved_and_format_actions_stay_separate() -> None:
    vocab = build_director_vocabulary(
        substrates=[_substrate("captions")],
        lanes=[_lane("captions", verbs=list(STABLE_DIRECTOR_VERBS))],
        rights_state=_rights_public(),
        format_actions=["rank", "compare"],
        now=NOW,
    )

    lane = next(entry for entry in vocab.entries if entry.target_id == "captions")

    assert vocab.stable_verbs == STABLE_DIRECTOR_VERBS
    assert lane.verbs == list(STABLE_DIRECTOR_VERBS)
    assert "rank" not in lane.verbs
    assert vocab.for_content_runner()["format_actions"] == ["rank", "compare"]


def test_unmounted_lane_emits_reason_without_allowed_lane_verbs() -> None:
    vocab = build_director_vocabulary(
        substrates=[_substrate("chat_ambient", status="dormant")],
        lanes=[
            _lane(
                "chat_ambient",
                state="candidate",
                mounted=False,
                renderable=False,
                verbs=["foreground", "hold", "suppress"],
                fallback_reason="aggregate chat ward is not mounted",
            )
        ],
        rights_state=_rights_public(),
        now=NOW,
    )

    lane = next(
        entry
        for entry in vocab.entries
        if entry.target_type == "spectacle_lane" and entry.target_id == "chat_ambient"
    )

    assert lane.verbs == []
    assert lane.public_claim_allowed is False
    assert lane.unavailable_reason == "aggregate chat ward is not mounted"
    assert vocab.unavailable_reasons["spectacle_lane:chat_ambient"] == (
        "aggregate chat ward is not mounted"
    )


def test_re_splay_device_is_explicit_no_op_until_hardware_evidence_exists() -> None:
    vocab = build_director_vocabulary(
        substrates=[
            _substrate(
                "re_splay_m8",
                status="unavailable",
                fallback_reason="M8 hardware smoke has not landed",
            )
        ],
        lanes=[
            _lane(
                "re_splay",
                state="blocked",
                mounted=False,
                renderable=False,
                verbs=["foreground", "hold", "suppress"],
                fallback_reason="No mounted-lane claim until hardware smoke",
            )
        ],
        rights_state=_rights_public(),
        now=NOW,
    )

    device = next(entry for entry in vocab.entries if entry.target_type == "re_splay_device")

    assert device.target_id == "re_splay_m8"
    assert device.verbs == []
    assert device.fallback_mode == "no_op"
    assert device.public_claim_allowed is False
    assert device.evidence[0].status == "missing"
    assert device.unavailable_reason == "No mounted-lane claim until hardware smoke"


def test_camera_vocabulary_uses_live_status_and_marks_inactive_roles_unavailable() -> None:
    camera_specs = (
        CameraSpec("c920-desk", "desk", 1280, 720, "c920", False),
        CameraSpec("brio-room", "room-brio", 1280, 720, "brio", True),
    )

    vocab = build_director_vocabulary(
        camera_specs=camera_specs,
        camera_status={"c920-desk": "active", "brio-room": "offline"},
        camera_status_observed_at=NOW - 2.0,
        rights_state=_rights_public(),
        now=NOW,
    )

    desk = next(entry for entry in vocab.entries if entry.target_id == "c920-desk")
    room = next(entry for entry in vocab.entries if entry.target_id == "brio-room")

    assert "foreground" in desk.verbs
    assert desk.public_claim_allowed is True
    assert room.verbs == []
    assert "offline" in room.unavailable_reason


def test_active_ward_claim_binding_adds_claim_terms_and_evidence() -> None:
    claim = Claim(
        name="vinyl_spinning",
        domain="activity",
        proposition="vinyl is spinning",
        posterior=0.91,
        prior_source="maximum_entropy",
        prior_provenance_ref="test-prior",
        evidence_sources=[
            EvidenceRef(
                signal_name="turntable_motion",
                value=True,
                timestamp=NOW - 1.0,
                frame_source="broadcast_frame",
            )
        ],
        last_update_t=NOW - 1.0,
        temporal_profile=TemporalProfile(
            enter_threshold=0.7,
            exit_threshold=0.3,
            k_enter=1,
            k_exit=1,
        ),
        narration_floor=0.7,
        staleness_cutoff_s=5.0,
    )

    vocab = build_director_vocabulary(
        active_wards=["album"],
        ward_claims={"album": claim},
        now=NOW,
    )

    ward = next(entry for entry in vocab.entries if entry.target_id == "album")

    assert "vinyl_spinning" in ward.terms
    assert "vinyl is spinning" in ward.terms
    assert "claim:vinyl_spinning" in ward.source_refs
    assert any(e.source_type == "claim_binding" and e.status == "fresh" for e in ward.evidence)


def test_private_controls_are_exported_private_only_for_scheduler_and_runner() -> None:
    vocab = build_director_vocabulary(
        private_controls=[
            PrivateControlBinding(
                control_id="stream_deck.key.7",
                display_name="Stream Deck key 7",
                source_ref="control:stream_deck.key.7",
                command="studio.activity.override",
                terms=["Vinyl"],
            )
        ],
        now=NOW,
    )

    control = next(entry for entry in vocab.entries if entry.target_id == "stream_deck.key.7")
    scheduler_view = vocab.for_programme_scheduler()
    runner_view = vocab.for_content_runner()

    assert control.public_claim_allowed is False
    assert control.fallback_mode == "private_only"
    assert control.verbs == ["route_attention", "hold", "suppress", "stabilize"]
    assert "private_control:stream_deck.key.7" in runner_view["verbs_by_target"]
    assert any(t["target_id"] == "stream_deck.key.7" for t in scheduler_view["targets"])


def test_visible_ward_ids_from_properties_ignores_hidden_and_expired(tmp_path: Path) -> None:
    path = tmp_path / "ward-properties.json"
    path.write_text(
        json.dumps(
            {
                "wards": {
                    "visible": {"visible": True, "expires_at": NOW + 10},
                    "hidden": {"visible": False, "expires_at": NOW + 10},
                    "expired": {"visible": True, "expires_at": NOW - 10},
                }
            }
        ),
        encoding="utf-8",
    )

    assert visible_ward_ids_from_properties(path, now=NOW) == {"visible"}
