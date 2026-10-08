"""PBX-R8: isolated producer/caller/consumer checks; no public or provider effects."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from prometheus_client import CollectorRegistry

from agents.publication_bus import selector
from agents.publish_orchestrator.orchestrator import Orchestrator
from shared.preprint_artifact import ApprovalState, PreprintArtifact
from shared.research_vehicle_public_event import ResearchVehiclePublicEvent


@pytest.fixture
def case(tmp_path):
    state = tmp_path / "state"
    (state / "publish/draft").mkdir(parents=True)
    event = ResearchVehiclePublicEvent.model_validate(
        {
            "event_id": "chronicle:fixture-1",
            "event_type": "chronicle.high_salience",
            "occurred_at": "2026-10-07T23:00:00Z",
            "broadcast_id": None,
            "programme_id": None,
            "condition_id": None,
            "salience": 0.9,
            "state_kind": "research_observation",
            "rights_class": "operator_original",
            "privacy_class": "public_safe",
            "public_url": None,
            "frame_ref": None,
            "chapter_ref": None,
            "source": {
                "producer": "fixture",
                "substrate_id": "fixture",
                "task_anchor": "fixture-task",
                "evidence_ref": "fixture:observation",
                "freshness_ref": "fixture:as-of",
            },
            "provenance": {
                "token": None,
                "generated_at": "2026-10-07T23:00:00Z",
                "producer": "fixture",
                "evidence_refs": ["fixture:observation"],
                "rights_basis": "original",
            },
            "surface_policy": {
                "allowed_surfaces": ["bluesky", "omg_weblog"],
                "denied_surfaces": [],
                "claim_live": False,
                "claim_archive": False,
                "claim_monetizable": False,
                "requires_egress_public_claim": True,
                "requires_audio_safe": False,
                "requires_provenance": True,
                "requires_human_review": False,
                "rate_limit_key": None,
                "redaction_policy": "none",
                "fallback_action": "hold",
                "dry_run_reason": None,
            },
        }
    )
    artifact = PreprintArtifact(
        slug="fixture-selection",
        title="An observation",
        body_md="A bounded observation.",
        surfaces_targeted=["bluesky-post"],
        author_model="fixture-author",
        attribution_block="Machine-assisted fixture.",
        publication_gate_context={
            "authority_case": "CASE-FIXTURE",
            "parent_spec": "fixture:spec",
            "emission_intent": {
                "content_form": "post",
                "external_utterance_refs": [],
                "manual_dispatch": False,
                "expected_effect": "Invite examination of the observation.",
                "cancel_predicate": "Cancel if the source observation is withdrawn.",
            },
        },
    )
    register = tmp_path / "register.json"
    register.write_text(
        json.dumps({"schema_version": "1.0", "snapshot": "fixture-snapshot", "records": []})
    )
    return state, event, artifact, register


def run(case):
    state, event, artifact, register = case
    return selector.produce(event, artifact, register_path=register, state_root=state)


def intent(artifact):
    return artifact.publication_gate_context["emission_intent"]


@pytest.mark.parametrize("slug", ["../escape", "/tmp/escape", "a/b", "..", "a\\b"])
def test_unsafe_slug_never_writes(case, slug):
    case[2].slug = slug
    assert run(case)["status"] == "held"
    assert list(case[0].rglob("*.json")) == []


@pytest.mark.parametrize("component", ["publish", "draft"])
def test_symlink_directory_never_writes(case, tmp_path, component):
    state = case[0]
    outside = tmp_path / "outside"
    outside.mkdir()
    draft = state / "publish/draft"
    draft.rmdir()
    target = draft if component == "draft" else state / "publish"
    if component == "publish":
        target.rmdir()
        (outside / "draft").mkdir()
    target.symlink_to(outside, target_is_directory=True)
    assert run(case)["status"] == "held"
    assert list(outside.rglob("*.json")) == []


def test_existing_file_never_overwritten(case):
    path = case[2].draft_path(state_root=case[0])
    path.write_bytes(b"predecessor")
    before = path.stat()
    assert run(case)["status"] == "conflict"
    assert path.read_bytes() == b"predecessor"
    assert path.stat().st_mtime_ns == before.st_mtime_ns


def test_final_symlink_never_followed(case, tmp_path):
    outside = tmp_path / "outside.json"
    outside.write_text("predecessor")
    case[2].draft_path(state_root=case[0]).symlink_to(outside)
    assert run(case)["status"] == "conflict"
    assert outside.read_text() == "predecessor"


@pytest.mark.parametrize(
    "change", ["missing_effect", "unknown_form", "missing_reactive", "judgment"]
)
def test_fuzzy_boundary_holds_and_logs(case, caplog, change):
    meta = intent(case[2])
    if change == "missing_effect":
        meta.pop("expected_effect")
    elif change == "unknown_form":
        meta["content_form"] = "uncertain"
    elif change == "missing_reactive":
        meta.pop("external_utterance_refs")
    else:
        meta["judgment_required"] = True
    with caplog.at_level("INFO"):
        result = run(case)
    assert result["status"] == "held"
    assert result["judgment"] == "unresolved"
    assert "unresolved" in caplog.text
    assert list(case[0].rglob("*.json")) == []


@pytest.mark.parametrize(
    "field,value", [("privacy_class", "unknown"), ("rights_class", "third_party_uncleared")]
)
def test_hygiene_hold(case, field, value):
    state, event, artifact, register = case
    event = event.model_copy(update={field: value})
    assert run((state, event, artifact, register))["status"] == "held"
    assert not artifact.draft_path(state_root=state).exists()


@pytest.mark.parametrize(
    "form,reply,long,class_name,classes",
    [
        ("post", False, False, "B", ["B"]),
        ("post", True, False, "C", ["B", "C"]),
        ("artifact", False, False, "A", ["A"]),
        ("artifact", True, False, "A", ["A", "C"]),
        ("post", True, True, "A", ["A", "C"]),
    ],
)
def test_strictest_class_and_universal_floor(case, form, reply, long, class_name, classes):
    artifact = case[2]
    intent(artifact).update(
        content_form=form,
        manual_dispatch=True,
        external_utterance_refs=["https://example.org/utterance"] if reply else [],
    )
    if long:
        artifact.body_md = "long " * 100
    result = run(case)
    assert result["status"] == "created"
    loaded = PreprintArtifact.model_validate_json(Path(result["path"]).read_text())
    receipt = loaded.publication_gate_context["emission_intent"]
    assert receipt["content_class"] == class_name
    assert receipt["applicable_classes"] == classes
    assert receipt["manual_dispatch"] is True
    assert receipt["manual_obligations"] == [
        "intent_receipt",
        "manual_discharge",
        "manual_readback_not_independent",
    ]
    assert receipt["feedback_obligations"] == ["readback", "capture", "correction"] + (
        ["retro"] if class_name == "A" else []
    )
    assert len(receipt["admission_checklist"]) == 7
    assert all(x["status"] == "not_run" for x in receipt["admission_checklist"])
    assert receipt["publication_authorized"] is False
    assert receipt["non_author_admission_required"] == (class_name == "A")
    assert loaded.approval == ApprovalState.DRAFT
    assert loaded.author_model == artifact.author_model
    assert loaded.attribution_block == artifact.attribution_block
    assert receipt["source_event"] == case[1].model_dump(mode="json")
    assert receipt["register"]["source"] == selector.REGISTER_URL
    assert len(receipt["intent_sha256"]) == 64


def test_replay_is_byte_and_mtime_preserving(case):
    first = run(case)
    path = Path(first["path"])
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    assert run(case)["status"] == "replay"
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    intent(case[2])["expected_effect"] = "A changed hypothesis."
    assert run(case)["status"] == "conflict"
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


@pytest.mark.parametrize("kind", ["identical", "similar", "malformed", "missing"])
def test_register_novelty_never_falls_open(case, kind):
    register = case[3]
    if kind == "missing":
        register.unlink()
    elif kind == "malformed":
        register.write_text('{"schema_version":"1.0","snapshot":"x","records":[null]}')
    else:
        register.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "snapshot": "fixture",
                    "records": [
                        {
                            "record": {"id": "clm-2026-0001", "title": case[2].title},
                            "body": case[2].body_md if kind == "identical" else "different",
                            "sha256": "0" * 64,
                        }
                    ],
                }
            )
        )
    result = run(case)
    assert result["status"] == "held"
    assert list(case[0].rglob("*.json")) == []


def test_cli_to_actual_orchestrator_draft_loader_without_dispatch(case, tmp_path, monkeypatch):
    state, event, artifact, register = case
    event_path, artifact_path = tmp_path / "event.json", tmp_path / "artifact.json"
    event_path.write_text(event.model_dump_json())
    artifact_path.write_text(artifact.model_dump_json())
    assert (
        selector.main(
            [
                "--event",
                str(event_path),
                "--artifact",
                str(artifact_path),
                "--register",
                str(register),
                "--state-root",
                str(state),
            ]
        )
        == 0
    )
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "agents.publication_bus",
            "select",
            "--event",
            str(event_path),
            "--artifact",
            str(artifact_path),
            "--register",
            str(register),
            "--state-root",
            str(state),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout)["status"] == "replay"
    # The actual consumer sees a valid artifact, and its inbox scan finds no dispatchable work.
    orchestrator = Orchestrator(
        state_root=state,
        registry=CollectorRegistry(),
        public_event_path=None,
        operator_notify=lambda *a, **kw: None,
    )
    monkeypatch.setattr(orchestrator, "_dispatch", lambda *a, **kw: pytest.fail("public dispatch"))
    loaded = orchestrator._load_artifact(artifact.draft_path(state_root=state))
    assert loaded.publication_gate_context["emission_intent"]["content_class"] == "B"
    assert orchestrator.run_once() == 0
    assert not (state / "publish/inbox").exists()


def test_approved_input_cannot_be_laundered(case):
    case[2].mark_approved(by_referent="fixture")
    assert run(case)["status"] == "held"
    assert list(case[0].rglob("*.json")) == []


@pytest.mark.parametrize("declared", ["B", "C", "M"])
def test_class_downgrade_is_held(case, declared):
    intent(case[2]).update(content_form="artifact", content_class=declared)
    result = run(case)
    assert result["status"] == "held"
    assert "class_violation" in result["reasons"]


def test_unknown_surface_is_held_without_invented_binding(case):
    case[2].surfaces_targeted = ["osf-preprint"]
    case[1].surface_policy.allowed_surfaces.append("zenodo")
    assert run(case)["status"] == "held"


@pytest.mark.parametrize("event_type", ["publication.artifact", "fanout.decision", "omg.weblog"])
def test_lifecycle_event_does_not_loop(case, event_type):
    state, event, artifact, register = case
    assert (
        run((state, event.model_copy(update={"event_type": event_type}), artifact, register))[
            "status"
        ]
        == "held"
    )


def test_intent_hash_binds_content_class_transport_effect_and_source(case):
    from hashlib import sha256

    result = run(case)
    payload = json.loads(Path(result["path"]).read_bytes())
    digest = payload["publication_gate_context"]["emission_intent"].pop("intent_sha256")
    raw = (
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode()
    assert sha256(raw).hexdigest() == digest
    assert "intent_sha256" not in intent(case[2])  # original candidate was not mutated


def test_concurrent_create_has_one_winner_and_complete_bytes(case):
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses = list(pool.map(lambda _: run(case)["status"], range(4)))
    assert sorted(statuses) == ["created", "replay", "replay", "replay"]
    path = case[2].draft_path(state_root=case[0])
    assert PreprintArtifact.model_validate_json(path.read_bytes()).slug == case[2].slug
    assert list(path.parent.iterdir()) == [path]


@pytest.mark.parametrize(
    "field,value",
    [
        ("content_form", []),
        ("manual_dispatch", "false"),
        ("external_utterance_refs", [None]),
        ("expected_effect", 1),
    ],
)
def test_malformed_declarations_hold(case, field, value):
    intent(case[2])[field] = value
    assert run(case)["status"] == "held"


def test_root_symlink_does_not_escape(case, tmp_path):
    link = tmp_path / "state-link"
    link.symlink_to(case[0], target_is_directory=True)
    assert run((link, *case[1:]))["status"] == "held"
    assert list(case[0].rglob("*.json")) == []


def test_io_failure_stays_held_and_no_partial_intent(case, monkeypatch):
    monkeypatch.setattr(
        selector.os, "fsync", lambda fd: (_ for _ in ()).throw(OSError(5, "fixture"))
    )
    assert run(case)["status"] == "held"
    assert list((case[0] / "publish/draft").iterdir()) == []


@pytest.mark.parametrize(
    "policy_field,value",
    [
        ("allowed_surfaces", []),
        ("denied_surfaces", ["bluesky"]),
        ("redaction_policy", "human_review"),
        ("dry_run_reason", "held"),
        ("fallback_action", "deny"),
        ("requires_human_review", True),
        ("requires_audio_safe", True),
    ],
)
def test_source_policy_holds(case, policy_field, value):
    state, event, artifact, register = case
    policy = event.surface_policy.model_copy(update={policy_field: value})
    event = event.model_copy(update={"surface_policy": policy})
    assert run((state, event, artifact, register))["status"] == "held"
    assert not artifact.draft_path(state_root=state).exists()


def test_missing_provenance_holds(case):
    state, event, artifact, register = case
    event = event.model_copy(
        update={"source": event.source.model_copy(update={"freshness_ref": None})}
    )
    assert run((state, event, artifact, register))["status"] == "held"


def test_authority_provenance_not_synthesized(case):
    case[2].publication_gate_context.pop("authority_case")
    assert run(case)["status"] == "held"


def test_long_abstract_cannot_hide_in_short_post(case):
    case[2].abstract = "A sustained argument. " * 30
    result = run(case)
    assert result["status"] == "created"
    assert result["features"]["content_class"] == "A"


def test_reactive_duties_retained_for_long_reply(case):
    intent(case[2]).update(
        content_form="artifact", external_utterance_refs=["https://example.org/reply"]
    )
    result = run(case)
    loaded = PreprintArtifact.model_validate_json(Path(result["path"]).read_bytes())
    receipt = intent(loaded)
    assert receipt["reactive_obligations"] == [
        "pointers_only_while_disposition_open",
        "delete_pointer_on_request",
    ]
    assert receipt["register"]["observation"] == "supplied_local_snapshot_only"
    assert receipt["register"]["snapshot_path"] == str(case[3])
