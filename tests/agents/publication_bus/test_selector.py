"""PBX-R8: isolated producer/caller/consumer checks; no public or provider effects."""

from __future__ import annotations

import json
import os
import stat
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


@pytest.mark.parametrize(
    "kind",
    ["identical", "event_id", "evidence_ref", "similar", "unmatched", "malformed", "missing"],
)
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
                            "record": {
                                "id": {
                                    "event_id": case[1].event_id,
                                    "evidence_ref": case[1].source.evidence_ref,
                                }.get(kind, "clm-2026-0001"),
                                "title": case[2].title if kind == "similar" else "Different title",
                            },
                            "body": case[2].body_md if kind == "identical" else "different",
                            "sha256": "0" * 64,
                        }
                    ],
                }
            )
        )
    result = run(case)
    assert result["status"] == ("created" if kind == "unmatched" else "held")
    assert result["judgment"] == ("unresolved" if kind == "similar" else "not_invoked")
    if kind in {"identical", "event_id", "evidence_ref"}:
        assert result["features"]["register"]["novelty"] == "duplicate"
        assert result["reasons"] == ["register_duplicate"]
    elif kind in {"similar", "unmatched"}:
        assert result["features"]["register"]["novelty"] == (
            "judgment_required" if kind == "similar" else "unmatched_in_snapshot"
        )
        assert result["reasons"] == (["register_similarity"] if kind == "similar" else [])
    else:
        assert result["reasons"] == ["register_unreadable_or_invalid"]
    assert bool(list(case[0].rglob("*.json"))) == (kind == "unmatched")


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


@pytest.mark.parametrize("form", ["post", "artifact"])
def test_unknown_surface_is_held_without_invented_binding(case, form):
    # A known short target removes an unrelated length hold, so this test
    # actually detects a fabricated policy binding for the unknown target.
    case[2].surfaces_targeted = ["osf-preprint", "bluesky-post"]
    intent(case[2])["content_form"] = form
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
    assert statuses.count("created") == 1
    assert statuses.count("replay") == 3
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


@pytest.mark.parametrize(
    "surface", ["omg-weblog", "oudepode-omg-weblog", "zenodo-doi", "zenodo-refusal-deposit"]
)
@pytest.mark.parametrize("with_short_surface", [False, True])
def test_durable_aliases_retain_class_a(case, surface, with_short_surface):
    case[1].surface_policy.allowed_surfaces.append("zenodo")
    case[2].surfaces_targeted = [surface] + (["bluesky-post"] if with_short_surface else [])
    intent(case[2]).update(manual_dispatch=True, external_utterance_refs=["fixture:reply"])
    result = run(case)
    assert result["status"] == "created"
    receipt = intent(PreprintArtifact.model_validate_json(Path(result["path"]).read_bytes()))
    assert receipt["content_class"] == "A"
    assert receipt["applicable_classes"] == ["A", "C"]
    assert receipt["non_author_admission_required"] is True
    assert "retro" in receipt["feedback_obligations"]
    assert receipt["reactive_obligations"]
    assert receipt["manual_obligations"]
    # A short-form declaration cannot weaken the canonical durable target.
    intent(case[2])["content_class"] = "B"
    assert "class_violation" in run(case)["reasons"]


@pytest.mark.parametrize(
    "field", ["freshness_ref", "evidence_refs", "attribution_refs", "optional_attribution"]
)
@pytest.mark.parametrize("blank", ["", " ", "\t\n"])
def test_blank_reference_elements_cannot_produce(case, field, blank):
    data = case[1].model_dump(mode="json")
    if field == "freshness_ref":
        data["source"][field] = blank
    elif field == "evidence_refs":
        data["provenance"][field] = ["fixture:valid", blank]
    else:
        data.update(attribution_refs=["fixture:valid", blank])
        if field == "attribution_refs":
            data["rights_class"] = "third_party_attributed"
    event = ResearchVehiclePublicEvent.model_validate(data)
    result = run((case[0], event, *case[2:]))
    assert result["status"] == "held"
    assert ("attribution_missing" if "attribution" in field else "provenance_incomplete") in result[
        "reasons"
    ]
    assert not case[2].draft_path(state_root=case[0]).exists()


def test_installed_draft_fsync_failure_and_recovery(case, monkeypatch):
    original_fsync = os.fsync
    directory_calls = []

    def fail_directory(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            directory_calls.append(fd)
            raise OSError(5, "PRIVATE ERROR BODY")
        original_fsync(fd)

    monkeypatch.setattr(selector.os, "fsync", fail_directory)
    first = run(case)
    path = case[2].draft_path(state_root=case[0])
    assert directory_calls and path.is_file()
    before = (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_ino)
    assert first["status"] == "held"
    assert first.get("path") == str(path)
    assert first["installed"] is True
    assert first["durability"] == "unconfirmed"
    assert "PRIVATE ERROR BODY" not in json.dumps(first)
    assert first["diagnostics"][0]["next_action"]
    retry = run(case)
    assert len(directory_calls) == 2
    assert retry["status"] == "held"
    assert retry["path"] == str(path)
    assert retry["durability"] == "unconfirmed"
    monkeypatch.setattr(selector.os, "fsync", original_fsync)
    recovered = run(case)
    assert recovered["status"] == "replay"
    assert recovered["durability"] == "confirmed"
    assert (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_ino) == before
    assert list(path.parent.iterdir()) == [path]


@pytest.mark.parametrize("edge", ["body_html", "no_surfaces", "dotdot", "missing_draft", "fifo"])
def test_reported_error_branches(case, edge):
    state, event, artifact, register = case
    if edge == "body_html":
        artifact.body_html = "<p>unexamined</p>"
    elif edge == "no_surfaces":
        artifact.surfaces_targeted = []
    elif edge == "dotdot":
        state = state / ".." / "state"
    elif edge == "missing_draft":
        (state / "publish/draft").rmdir()
    else:
        os.mkfifo(artifact.draft_path(state_root=state))
    result = run((state, event, artifact, register))
    assert result["status"] == ("conflict" if edge == "fifo" else "held")
    expected = {
        "body_html": "empty_or_unexamined_content",
        "no_surfaces": "no_target_surface",
        "dotdot": "unsafe_state_root",
        "missing_draft": "draft_write_refused:2",
        "fifo": "draft_conflict",
    }
    assert expected[edge] in result["reasons"]
    assert result["diagnostics"] and all(d["next_action"] for d in result["diagnostics"])
    if edge == "fifo":
        assert stat.S_ISFIFO(artifact.draft_path(state_root=state).stat().st_mode)
    else:
        assert list(case[0].rglob("*.json")) == []


@pytest.mark.parametrize("input_name", ["event", "artifact"])
@pytest.mark.parametrize("failure", ["missing", "invalid_json", "invalid_field"])
def test_cli_input_errors_are_actionable_and_private(case, tmp_path, capsys, input_name, failure):
    paths = {"event": tmp_path / "event.json", "artifact": tmp_path / "artifact.json"}
    paths["event"].write_text(case[1].model_dump_json())
    paths["artifact"].write_text(case[2].model_dump_json())
    bad_path = paths[input_name]
    field = "salience" if input_name == "event" else "surfaces_targeted"
    if failure == "missing":
        bad_path.unlink()
    elif failure == "invalid_json":
        bad_path.write_text("PRIVATE INPUT BODY")
    else:
        data = json.loads(bad_path.read_text())
        data[field] = "PRIVATE INPUT BODY"
        bad_path.write_text(json.dumps(data))
    args = ["--register", str(case[3]), "--state-root", str(case[0])]
    for name, path in paths.items():
        args.extend([f"--{name}", str(path)])
    assert selector.main(args) == 2
    captured = capsys.readouterr()
    assert "PRIVATE INPUT BODY" not in captured.out + captured.err
    result = json.loads(captured.out)
    assert result["status"] == "held"
    diagnostic = result["diagnostics"][0]
    assert diagnostic["input"] == input_name
    assert diagnostic["path"] == str(bad_path)
    assert diagnostic["next_action"]
    if failure == "invalid_field":
        assert field in json.dumps(diagnostic["fields"])
    assert list(case[0].rglob("*.json")) == []


@pytest.mark.parametrize("failure", ["unsafe_slug", "register", "class", "write", "durability"])
def test_cli_selection_refusals_have_safe_repair_guidance(
    case, tmp_path, capsys, monkeypatch, failure
):
    if failure == "unsafe_slug":
        case[2].slug = "../PRIVATE INPUT BODY"
    elif failure == "register":
        case[3].write_text("PRIVATE INPUT BODY")
    elif failure == "class":
        intent(case[2]).update(content_form="artifact", content_class="B")
    elif failure == "write":
        (case[0] / "publish/draft").rmdir()
    else:
        original_fsync = os.fsync

        def fail_directory(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError(5, "PRIVATE INPUT BODY")
            original_fsync(fd)

        monkeypatch.setattr(selector.os, "fsync", fail_directory)
    event_path, artifact_path = tmp_path / "event.json", tmp_path / "artifact.json"
    event_path.write_text(case[1].model_dump_json())
    artifact_path.write_text(case[2].model_dump_json())
    args = [
        "--event",
        str(event_path),
        "--artifact",
        str(artifact_path),
        "--register",
        str(case[3]),
        "--state-root",
        str(case[0]),
    ]
    for _ in range(2 if failure == "durability" else 1):
        assert selector.main(args) == 2
        captured = capsys.readouterr()
        assert "PRIVATE INPUT BODY" not in captured.out + captured.err
        result = json.loads(captured.out)
        assert result["status"] == "held"
        assert result["diagnostics"] and all(d["next_action"] for d in result["diagnostics"])
        if failure == "register":
            assert result["diagnostics"][0]["path"] == str(case[3])
        if failure == "durability":
            assert result["path"] == str(case[2].draft_path(state_root=case[0]))
            assert result["installed"] is True
            assert result["durability"] == "unconfirmed"
        else:
            assert list(case[0].rglob("*.json")) == []


def test_replay_rechecks_existing_file_durability(case, monkeypatch):
    first = run(case)
    path = Path(first["path"])
    before = (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_ino)
    original_fsync = os.fsync
    failures = []

    def fail_existing_file(fd):
        if os.fstat(fd).st_ino == before[2]:
            failures.append(fd)
            raise OSError(5, "PRIVATE ERROR BODY")
        original_fsync(fd)

    monkeypatch.setattr(selector.os, "fsync", fail_existing_file)
    result = run(case)
    assert failures
    assert result["status"] == "held"
    assert result["path"] == str(path)
    assert result["installed"] is True
    assert result["durability"] == "unconfirmed"
    assert "PRIVATE ERROR BODY" not in json.dumps(result)
    monkeypatch.setattr(selector.os, "fsync", original_fsync)
    assert run(case)["status"] == "replay"
    assert (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_ino) == before


@pytest.mark.parametrize(
    "edge",
    ["created", "replay", "directory_sync", "existing_sync", "file_sync", "link", "conflict"],
)
def test_cleanup_failure_preserves_primary_effect(case, monkeypatch, capsys, tmp_path, edge):
    path = case[2].draft_path(state_root=case[0])
    if edge in {"replay", "existing_sync"}:
        assert run(case)["status"] == "created"
    elif edge == "conflict":
        path.write_bytes(b"predecessor")
    before = (
        (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns) if path.exists() else None
    )
    original_fsync, original_link = os.fsync, os.link
    failures = []

    def fail_unlink(name, *, dir_fd):
        assert name.startswith(".selector-") and name.endswith(".tmp")
        failures.append("cleanup")
        raise OSError(13, "PRIVATE CLEANUP BODY")

    def fail_sync(fd):
        mode = os.fstat(fd).st_mode
        if (
            (edge == "directory_sync" and stat.S_ISDIR(mode))
            or (edge == "file_sync" and stat.S_ISREG(mode))
            or (edge == "existing_sync" and os.fstat(fd).st_ino == before[1])
        ):
            failures.append("sync")
            raise OSError(5, "PRIVATE SYNC BODY")
        original_fsync(fd)

    def fail_link(*args, **kwargs):
        if edge == "link":
            failures.append("link")
            raise OSError(28, "PRIVATE LINK BODY")
        return original_link(*args, **kwargs)

    event_path, artifact_path = tmp_path / "event.json", tmp_path / "artifact.json"
    event_path.write_text(case[1].model_dump_json())
    artifact_path.write_text(case[2].model_dump_json())
    with monkeypatch.context() as patch:
        patch.setattr(selector.os, "unlink", fail_unlink)
        patch.setattr(selector.os, "fsync", fail_sync)
        patch.setattr(selector.os, "link", fail_link)
        assert (
            selector.main(
                [
                    "--event",
                    str(event_path),
                    "--artifact",
                    str(artifact_path),
                    "--register",
                    str(case[3]),
                    "--state-root",
                    str(case[0]),
                ]
            )
            == 2
        )
    captured = capsys.readouterr()
    assert "PRIVATE" not in captured.out + captured.err
    result = json.loads(captured.out)
    assert failures.count("cleanup") == 1
    assert result["status"] == ("conflict" if edge == "conflict" else "held")
    primary = {
        "directory_sync": ["draft_durability_unconfirmed:5"],
        "existing_sync": ["draft_durability_unconfirmed:5"],
        "file_sync": ["draft_write_refused:5"],
        "link": ["draft_write_refused:28"],
        "conflict": ["draft_conflict"],
    }.get(edge, [])
    assert result["reasons"] == primary + ["draft_cleanup_failed:13"]
    assert all(d["next_action"] for d in result["diagnostics"])
    assert [d["reason"] for d in result["diagnostics"]] == result["reasons"]
    if edge in {"created", "replay", "directory_sync", "existing_sync"}:
        assert result.get("path") == str(path)
        assert result.get("installed") is True
        assert result.get("durability") == (
            "unconfirmed" if edge in {"directory_sync", "existing_sync"} else "confirmed"
        )
        assert (
            PreprintArtifact.model_validate_json(path.read_bytes()).approval == ApprovalState.DRAFT
        )
        installed = (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns)
        recovery = run(case)
        assert recovery["status"] == "replay"
        assert recovery["durability"] == "confirmed"
        assert (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns) == installed
    else:
        assert "installed" not in result and "durability" not in result
        assert path.exists() == (edge == "conflict")
    if before:
        assert (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns) == before
    assert len(list(path.parent.glob(".selector-*.tmp"))) == 1
    assert len(list(path.parent.glob("*.json"))) == int(path.exists())
    assert failures.count("sync") == int(edge in {"directory_sync", "existing_sync", "file_sync"})
    assert failures.count("link") == int(edge == "link")


@pytest.mark.parametrize(
    "field",
    [
        "content_form",
        "external_utterance_refs",
        "manual_dispatch",
        "expected_effect",
        "cancel_predicate",
        "judgment_required",
        "content_class",
    ],
)
@pytest.mark.parametrize("shape", ["mapping", "list", "mixed_list"])
def test_cli_malformed_declarations_never_echo_payload(case, tmp_path, field, shape):
    sentinel = "PRIVATE DECLARATION BODY"
    value = {
        "mapping": {"body": sentinel},
        "list": [{"body": sentinel}],
        "mixed_list": [sentinel, None],
    }[shape]
    intent(case[2])[field] = value
    event_path, artifact_path = tmp_path / "event.json", tmp_path / "artifact.json"
    event_path.write_text(case[1].model_dump_json())
    artifact_path.write_text(case[2].model_dump_json())
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
            str(case[3]),
            "--state-root",
            str(case[0]),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert process.returncode == 2, process.stderr
    assert sentinel not in process.stdout + process.stderr
    result = json.loads(process.stdout)
    assert result["status"] == "held"
    assert result["diagnostics"] and all(d["next_action"] for d in result["diagnostics"])
    if field in {"content_form", "external_utterance_refs"}:
        assert result["features"][field] == {"valid": False, "type": type(value).__name__}
        assert result["judgment"] == "unresolved"
    assert list((case[0] / "publish/draft").iterdir()) == []


@pytest.mark.parametrize("field", ["content_form", "external_utterance_refs"])
@pytest.mark.parametrize("value", ["PRIVATE DECLARATION BODY", None, 42, False])
def test_cli_invalid_scalar_declarations_are_summarized(case, tmp_path, capsys, field, value):
    intent(case[2])[field] = value
    event_path, artifact_path = tmp_path / "event.json", tmp_path / "artifact.json"
    event_path.write_text(case[1].model_dump_json())
    artifact_path.write_text(case[2].model_dump_json())
    assert (
        selector.main(
            [
                "--event",
                str(event_path),
                "--artifact",
                str(artifact_path),
                "--register",
                str(case[3]),
                "--state-root",
                str(case[0]),
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert "PRIVATE DECLARATION BODY" not in captured.out + captured.err
    result = json.loads(captured.out)
    assert result["features"][field] == {"valid": False, "type": type(value).__name__}
    assert result["judgment"] == "unresolved"
    assert list((case[0] / "publish/draft").iterdir()) == []
