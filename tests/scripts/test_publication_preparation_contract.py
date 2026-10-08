"""Isolated preparation-to-admission cases. All authority is synthetic fixture data."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import yaml

from scripts import mint_public_gate_receipts as minter
from scripts import publish_vault_artifact as publish
from shared import public_gate_receipts as receipts
from shared.review_artifact_manifest import artifact_head_sha, build_artifact_manifest

SECRET = "offline-contract-fixture-only"  # pragma: allowlist secret
TASK = "test-preparation-contract"
CASE = "CASE-SYSTEM-INTEGRITY-20260611"
GATES = publish.PUBLICATION_BASELINE_REQUIRED_GATES
REFS = {g: f"public-gate:preparation-{g.replace('_', '-')}" for g in GATES}


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "vault"
    root.mkdir()
    source = root / "draft.md"
    source.write_text(
        "---\ntitle: Prepared correction\nslug: prepared-correction\nsurfaces_targeted: [bluesky-post]\n---\nPrepared correction.\n"
    )
    authority = tmp_path / "authority"
    authority.mkdir()
    receipt_root = tmp_path / "receipts"
    monkeypatch.setenv(receipts.PUBLIC_GATE_AUTHORITY_SECRET_ENV, SECRET)
    monkeypatch.setenv(receipts.PUBLIC_GATE_AUTHORITY_ROOTS_ENV, str(authority))
    monkeypatch.setattr(receipts, "PUBLIC_GATE_AUTHORITY_ROOTS", (authority,))
    monkeypatch.setattr(publish, "VAULT_ARTIFACT_ROOT", root)
    monkeypatch.setattr(publish, "PUBLIC_GATE_RECEIPT_ROOTS", (receipt_root,))
    # Ensure no credential/provider lookup, even if a future implementation regresses.
    monkeypatch.setattr(minter, "get_secret", lambda *a, **kw: SECRET)
    return dict(
        root=root,
        source=source,
        authority=authority,
        receipts=receipt_root,
        dossier=authority / f"{TASK}.review-dossier.yaml",
        tmp=tmp_path,
    )


def draft(env):
    return publish._parse_publication_markdown(env["source"])


def signed_dossier(env, **overrides):
    fm, body = draft(env)
    # The installed source has no prepare-only builder. This fixture constructs its
    # public projection with validation suppressed solely to reproduce that source.
    with patch.object(publish, "_assert_publication_gate_receipts"):
        projected = publish._build_artifact(
            body_md=body,
            frontmatter={**fm, "Publication-Allowed": True},
            surfaces=["bluesky-post"],
            approver="Oudepode",
            source_path=env["source"],
        )
    manifest, _ = build_artifact_manifest([env["source"]], env["root"], max_chars=80000)
    data = dict(
        dossier_schema=1,
        task_id=TASK,
        head_sha=artifact_head_sha(manifest),
        review_team_verdict="quorum-accept",
        quorum_required=2,
        accept_count=2,
        writer_family="codex",
        reviewers=[dict(family=f, verdict="accept") for f in ["gemini", "glm"]],
        authority_issuer="review-team:gemini,glm",
        required_gates=list(GATES),
        authorized_public_gate_receipts=list(REFS.values()),
        artifact_review=dict(artifact_root=str(env["root"]), manifest=manifest),
        **publish._publication_gate_receipt_bindings(projected),
    )
    data["target_surfaces"] = list(data["target_surfaces"])
    data.update(overrides)
    data["authority_signature"] = receipts.public_gate_authority_signature(data, SECRET)
    env["dossier"].write_text(yaml.safe_dump(data, sort_keys=False))
    return data


def mint(env, **overrides):
    return minter.mint(
        **(
            dict(
                task_id=TASK,
                artifact=env["source"],
                artifact_root=env["root"],
                authority_case=CASE,
                receipt_root=env["receipts"],
                receipt_refs=REFS,
            )
            | overrides
        )
    )


def build(env, **overrides):
    fm, body = draft(env)
    return publish._build_artifact(
        **(
            dict(
                body_md=body,
                frontmatter=fm,
                surfaces=["bluesky-post"],
                approver="Oudepode",
                source_path=env["source"],
                review_task=TASK,
                receipt_refs=REFS,
            )
            | overrides
        )
    )


def test_installed_false_then_clearance_changes_head(env):
    env["source"].write_text(
        "---\nPublication-Allowed: false\npublication_gate_receipts: {}\n---\nBody\n"
    )
    original = receipts.vault_artifact_expected_head_sha(env["source"], env["root"])
    fm, body = draft(env)
    with pytest.raises(publish.PublicationGateError, match="Publication-Allowed"):
        publish._build_artifact(
            body_md=body,
            frontmatter=fm,
            surfaces=["bluesky-post"],
            approver="Oudepode",
            source_path=env["source"],
        )
    env["source"].write_text(env["source"].read_text().replace("false", "true"))
    assert receipts.vault_artifact_expected_head_sha(env["source"], env["root"]) != original


def test_unreviewed_path_cannot_mint_legacy_receipts(env):
    fm, body = draft(env)
    env["source"].write_text(
        "---\n"
        + yaml.safe_dump({**fm, "Publication-Allowed": True, "publication_gate_receipts": REFS})
        + "---\n"
        + body
    )
    signed_dossier(env)
    other = env["root"] / "unreviewed-copy.md"
    other.write_bytes(env["source"].read_bytes())
    with pytest.raises(minter.MintError, match="subject_head_mismatch"):
        minter.mint(
            task_id=TASK,
            artifact=other,
            artifact_root=env["root"],
            authority_case=CASE,
            receipt_root=env["receipts"],
        )
    assert not env["receipts"].exists()


def test_preparation_never_self_clears_and_complete_receipts_release_same_bytes(env):
    before = env["source"].read_bytes()
    fm, body = draft(env)
    prepared = publish._prepare_artifact(
        body_md=body, frontmatter=fm, surfaces=["bluesky-post"], source_path=env["source"]
    )
    assert not prepared.is_approved()
    assert prepared.approved_at is None
    with pytest.raises(publish.PublicationGateError):
        build(env)
    signed_dossier(env)
    with pytest.raises(publish.PublicationGateError, match="receipt refs"):
        build(env)
    result = mint(env)
    assert len(result["receipts"]) == 6
    artifact = build(env)
    assert artifact.is_approved()
    assert env["source"].read_bytes() == before
    assert artifact.publication_gate_context["publication_gate_receipts"] == REFS
    assert not (env["tmp"] / "publish").exists()


@pytest.mark.parametrize(
    "change",
    [
        "body",
        "path",
        "unsigned",
        "self",
        "missing_gate",
        "wrong_surface",
        "wrong_fingerprint",
        "unknown_ref",
    ],
)
def test_external_admission_rejects_unsafe_authority(env, change):
    changes = {
        "unsigned": {},
        "body": {},
        "path": {},
        "self": {
            "reviewers": [
                dict(family="codex", verdict="accept"),
                dict(family="gemini", verdict="accept"),
            ]
        },
        "missing_gate": {"required_gates": list(GATES)[1:]},
        "wrong_surface": {"target_surfaces": ["omg-weblog"]},
        "wrong_fingerprint": {"artifact_fingerprint": "0" * 64},
        "unknown_ref": {
            "authorized_public_gate_receipts": [*REFS.values(), "public-gate:not-authorized"]
        },
    }
    signed_dossier(env, **changes[change])
    if change == "body":
        env["source"].write_text(env["source"].read_text() + "Changed.\n")
    elif change == "path":
        other = env["root"] / "other.md"
        other.write_bytes(env["source"].read_bytes())
        env["source"] = other
    elif change == "unsigned":
        data = yaml.safe_load(env["dossier"].read_text())
        data["authority_signature"] = "hmac-sha256:" + "0" * 64
        env["dossier"].write_text(yaml.safe_dump(data))
    with pytest.raises(minter.MintError):
        mint(env)
    assert not env["receipts"].exists()
    with pytest.raises(publish.PublicationGateError):
        build(env)


@pytest.mark.parametrize(
    "key,value",
    [
        ("Publication-Allowed", False),
        ("publication_allowed", "withheld"),
        ("publication-allowed", True),
        ("Publication-Allowed", "garbage"),
        ("Publication-Allowed", None),
    ],
)
def test_external_mode_refuses_mixed_or_withheld_clearance(env, key, value):
    fm, body = draft(env)
    env["source"].write_text("---\n" + yaml.safe_dump({**fm, key: value}) + "---\n" + body)
    signed_dossier(env)
    with pytest.raises(minter.MintError, match="mixed_clearance"):
        mint(env)
    with pytest.raises(publish.PublicationGateError):
        build(env)
    assert not env["receipts"].exists()


def test_external_receipts_are_create_once_and_tampered_receipt_blocks(env):
    signed_dossier(env)
    mint(env)
    files = {p: p.read_bytes() for p in env["receipts"].glob("*.yaml")}
    assert {x["state"] for x in mint(env)["receipts"].values()} == {"unchanged"}
    target = next(iter(files))
    target.write_text("sentinel\n")
    with pytest.raises(minter.MintError, match="receipt_exists"):
        mint(env)
    assert target.read_text() == "sentinel\n"
    with pytest.raises(publish.PublicationGateError):
        build(env)


def test_external_mode_still_refuses_missing_and_malformed_legacy_clearance(env):
    fm, body = draft(env)
    with pytest.raises(publish.PublicationGateError):
        publish._build_artifact(
            body_md=body,
            frontmatter=fm,
            surfaces=["bluesky-post"],
            approver="Oudepode",
            source_path=env["source"],
        )


def test_false_empty_accepted_artifact_still_cannot_complete_installed_sequence(env):
    fm, body = draft(env)
    env["source"].write_text(
        "---\n"
        + yaml.safe_dump({**fm, "Publication-Allowed": False, "publication_gate_receipts": {}})
        + "---\n"
        + body
    )
    signed_dossier(env)
    with pytest.raises(minter.MintError, match="receipts_missing"):
        minter.mint(
            task_id=TASK,
            artifact=env["source"],
            artifact_root=env["root"],
            authority_case=CASE,
            receipt_root=env["receipts"],
        )
    env["source"].write_text(
        env["source"].read_text().replace("Publication-Allowed: false", "Publication-Allowed: true")
    )
    with pytest.raises(minter.MintError, match="artifact_changed"):
        minter.mint(
            task_id=TASK,
            artifact=env["source"],
            artifact_root=env["root"],
            authority_case=CASE,
            receipt_root=env["receipts"],
        )
    assert not env["receipts"].exists()


def test_both_real_clis_require_acceptance_then_receipts_before_enqueue(env, capsys, monkeypatch):
    receipt_map = env["tmp"] / "mint-destinations.yaml"
    receipt_map.write_text(yaml.safe_dump(REFS))
    argv = [
        str(env["source"]),
        "--surfaces",
        "bluesky-post",
        "--review-task",
        TASK,
        "--receipt-map",
        str(receipt_map),
        "--state-root",
        str(env["tmp"] / "state"),
    ]
    assert publish.main(argv) == 1
    assert not (env["tmp"] / "state").exists()
    signed_dossier(env)
    assert publish.main(argv) == 1
    assert not (env["tmp"] / "state").exists()
    assert (
        minter.main(
            [
                "--task-id",
                TASK,
                "--artifact",
                str(env["source"]),
                "--artifact-root",
                str(env["root"]),
                "--authority-case",
                CASE,
                "--receipt-root",
                str(env["receipts"]),
                "--receipt-map",
                str(receipt_map),
            ]
        )
        == 0
    )
    assert publish.main([*argv, "--dry-run"]) == 0
    assert not (env["tmp"] / "state").exists()
    assert publish.main(argv) == 0
    from shared.preprint_artifact import PreprintArtifact

    artifact = PreprintArtifact.model_validate_json(
        (env["tmp"] / "state/publish/inbox/prepared-correction.json").read_text()
    )
    assert artifact.is_approved()
    # Existing orchestrator gate consumes the same artifact and signed per-gate receipts.
    from agents.publish_orchestrator import orchestrator

    monkeypatch.setattr(orchestrator, "PUBLICATION_SOURCE_PATH_ROOTS", (env["root"],))
    Orchestrator = orchestrator.Orchestrator
    orch = Orchestrator(
        state_root=env["tmp"] / "orchestrator",
        public_gate_receipt_roots=(env["receipts"],),
        publication_allowed_surfaces={"bluesky-post"},
    )
    result = orch._public_gate_receipts_child(artifact)
    assert result.decision.value == "pass", result.findings
    env["source"].write_text(env["source"].read_text() + "Changed after enqueue.\n")
    assert orch._public_gate_receipts_child(artifact).decision.value == "hold"


def test_orchestrator_preserves_vault_subject_while_recording_gate_result(env, monkeypatch):
    from prometheus_client import CollectorRegistry

    from agents.publish_orchestrator import orchestrator
    from shared.preprint_artifact import PreprintArtifact

    monkeypatch.setattr(orchestrator, "PUBLICATION_SOURCE_PATH_ROOTS", (env["root"],))
    artifact = PreprintArtifact(
        slug="pending",
        title="Pending",
        body_md="Body",
        abstract="Body",
        source_path=str(env["source"]),
        surfaces_targeted=["bluesky-post"],
    )
    artifact.publication_gate_result = {
        "decision": "hold",
        "flagged_issues": ["pending exact acceptance"],
    }
    before = env["source"].read_bytes()
    orch = orchestrator.Orchestrator(
        state_root=env["tmp"] / "held-state", registry=CollectorRegistry()
    )
    orch._attach_gate_frontmatter(artifact)
    assert env["source"].read_bytes() == before
    assert artifact.publication_gate_result["decision"] == "hold"


def test_real_cor0004_body_and_attribution_survive_preparation_without_clearance(env):
    from agents.cross_surface.bluesky_post import _compose_artifact_text

    frozen = Path(__file__).parents[1] / "fixtures/cor0004-r4.md"
    fm, body = publish._parse_publication_markdown(frozen)
    fm.pop("Publication-Allowed")
    fm.pop("publication_gate_receipts")
    env["source"].write_text("---\n" + yaml.safe_dump(fm, sort_keys=False) + "---\n" + body)
    fm, body = draft(env)
    prepared = publish._prepare_artifact(
        body_md=body, frontmatter=fm, surfaces=["bluesky-post"], source_path=env["source"]
    )
    rendered = _compose_artifact_text(prepared)
    assert not prepared.is_approved()
    assert rendered == body.strip() == fm["attribution_block"]
    assert len(rendered) == 218 and len(rendered.encode()) == 220
    signed_dossier(env)
    before = env["source"].read_bytes()
    mint(env)
    assert _compose_artifact_text(build(env)) == rendered
    assert env["source"].read_bytes() == before


def test_signed_root_blocks_identical_relative_path_replay(env, monkeypatch):
    signed_dossier(env)
    mint(env)
    original = env["source"].read_bytes()
    other_root = env["tmp"] / "other-vault"
    other_root.mkdir()
    other = other_root / env["source"].name
    other.write_bytes(original)
    assert receipts.vault_artifact_expected_head_sha(other, other_root) == (
        receipts.vault_artifact_expected_head_sha(env["source"], env["root"])
    )
    with pytest.raises(minter.MintError, match="artifact_root.*next action"):
        mint(env, artifact=other, artifact_root=other_root, receipt_root=env["tmp"] / "replay")
    monkeypatch.setattr(publish, "VAULT_ARTIFACT_ROOT", other_root)
    env["source"] = other
    with pytest.raises(publish.PublicationGateError, match="artifact_root.*next action"):
        build(env)
    assert not (env["tmp"] / "replay").exists()
    assert other.read_bytes() == original


@pytest.mark.parametrize("signed_root", [None, "relative-root", 42])
def test_signed_root_must_be_absolute_and_present(env, signed_root):
    data = signed_dossier(env)
    signed_dossier(env, artifact_review={**data["artifact_review"], "artifact_root": signed_root})
    with pytest.raises(minter.MintError, match="artifact_root.*next action"):
        mint(env)
    assert not env["receipts"].exists()


def test_signed_root_accepts_equivalent_canonical_path(env):
    signed_dossier(env)
    alias = env["tmp"] / "vault-alias"
    alias.symlink_to(env["root"], target_is_directory=True)
    mint(env, artifact_root=alias)
    assert build(env).is_approved()


EXTRA_GATE = "fanout_loop_prevention_present"
EXTRA_REFS = {**REFS, EXTRA_GATE: "public-gate:preparation-loop-prevention"}


def extra_gate_acceptance(env):
    signed_dossier(
        env,
        required_gates=list(EXTRA_REFS),
        authorized_public_gate_receipts=list(EXTRA_REFS.values()),
    )
    mint(env, receipt_refs=EXTRA_REFS)
    return env["receipts"] / "preparation-loop-prevention.yaml"


@pytest.mark.parametrize("damage", ["missing", "invalid"])
def test_every_signed_required_gate_is_checked_before_approval(env, damage):
    extra = extra_gate_acceptance(env)
    if damage == "missing":
        extra.unlink()
    else:
        extra.write_text("invalid receipt\n")
    before = env["source"].read_bytes()
    with pytest.raises(publish.PublicationGateError, match=EXTRA_GATE):
        build(env, receipt_refs=EXTRA_REFS)
    assert env["source"].read_bytes() == before
    assert not (env["tmp"] / "state").exists()


@pytest.mark.parametrize("damage", ["missing_file", "missing_ref"])
def test_signed_requirements_survive_serialization_and_dispatch(env, monkeypatch, damage):
    from prometheus_client import CollectorRegistry

    from agents.publish_orchestrator import orchestrator
    from shared.preprint_artifact import PreprintArtifact

    extra = extra_gate_acceptance(env)
    artifact = PreprintArtifact.model_validate_json(
        build(env, receipt_refs=EXTRA_REFS).model_dump_json()
    )
    monkeypatch.setattr(orchestrator, "PUBLICATION_SOURCE_PATH_ROOTS", (env["root"],))
    orch = orchestrator.Orchestrator(
        state_root=env["tmp"] / "dispatch-state",
        public_gate_receipt_roots=(env["receipts"],),
        publication_allowed_surfaces={"bluesky-post"},
        registry=CollectorRegistry(),
    )
    assert orch._public_gate_receipts_child(artifact).decision.value == "pass"
    if damage == "missing_file":
        extra.unlink()
    else:
        del artifact.publication_gate_context["publication_gate_receipts"][EXTRA_GATE]
    pool = Mock()
    orch._hardening_gate.evaluate = Mock(
        side_effect=AssertionError("receipt gate must stop dispatch")
    )
    before = env["source"].read_bytes()
    orch._dispatch(artifact, pool=pool)
    pool.submit.assert_not_called()
    assert artifact.publication_gate_result["decision"] == "hold"
    assert EXTRA_GATE in str(artifact.publication_gate_result)
    assert env["source"].read_bytes() == before


@pytest.mark.parametrize("required", [None, "gate", [None], [""]])
def test_dispatch_refuses_malformed_carried_requirements(env, monkeypatch, required):
    from prometheus_client import CollectorRegistry

    from agents.publish_orchestrator import orchestrator

    signed_dossier(env)
    mint(env)
    artifact = build(env)
    artifact.publication_gate_context["required_publication_gate_receipts"] = required
    monkeypatch.setattr(orchestrator, "PUBLICATION_SOURCE_PATH_ROOTS", (env["root"],))
    orch = orchestrator.Orchestrator(
        state_root=env["tmp"] / "malformed-state",
        public_gate_receipt_roots=(env["receipts"],),
        registry=CollectorRegistry(),
    )
    result = orch._public_gate_receipts_child(artifact)
    assert result.decision.value == "hold"
    assert "required_publication_gate_receipts malformed; next action:" in str(result.findings)


@pytest.mark.parametrize("context_key", ["publication_gate_context", "Publication_Gate_Context"])
def test_external_clearance_rejects_recognized_context_casing(env, context_key):
    fm, body = draft(env)
    env["source"].write_text(
        "---\n"
        + yaml.safe_dump({**fm, context_key: {"publication_gate_receipts": REFS}})
        + "---\n"
        + body
    )
    signed_dossier(env)
    with pytest.raises(minter.MintError, match="mixed_clearance"):
        mint(env)
    with pytest.raises(publish.PublicationGateError, match="mixed_clearance"):
        build(env)
    assert not env["receipts"].exists()


@pytest.mark.parametrize("contents", [None, b"\xff", b"[", b"[]", b"{}", b"gate: 7"])
def test_bad_external_maps_hold_both_clis_without_writes(env, contents, capsys, caplog):
    path = env["tmp"] / "bad-map.yaml"
    if contents is not None:
        path.write_bytes(contents)
    before = env["source"].read_bytes()
    assert (
        minter.main(
            [
                "--task-id",
                TASK,
                "--artifact",
                str(env["source"]),
                "--artifact-root",
                str(env["root"]),
                "--authority-case",
                CASE,
                "--receipt-root",
                str(env["receipts"]),
                "--receipt-map",
                str(path),
            ]
        )
        == 1
    )
    assert "next action:" in capsys.readouterr().err
    assert (
        publish.main(
            [
                str(env["source"]),
                "--surfaces",
                "bluesky-post",
                "--review-task",
                TASK,
                "--receipt-map",
                str(path),
                "--state-root",
                str(env["tmp"] / "state"),
            ]
        )
        == 1
    )
    assert "next action:" in caplog.text
    assert str(path) in caplog.text
    if contents == b"\xff":
        assert "UTF-8" in caplog.text
    assert not env["receipts"].exists()
    assert not (env["tmp"] / "state").exists()
    assert env["source"].read_bytes() == before


@pytest.mark.parametrize(
    "overrides",
    [
        {"review_task": None},
        {"receipt_refs": None},
        {"source_path": None},
        {"review_task": ""},
    ],
)
def test_incomplete_external_arguments_refuse_actionably(env, overrides):
    with pytest.raises(publish.PublicationGateError, match="external clearance.*next action"):
        build(env, **overrides)
    assert not env["receipts"].exists()


@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({"task_id": "../other"}, "task_malformed"),
        ({"receipt_refs": {"gate": 7}}, "receipt_map_malformed"),
        ({"receipt_refs": {"": "public-gate:ref"}}, "receipt_map_malformed"),
    ],
)
def test_minter_new_refusals_have_repair_actions(env, overrides, reason):
    signed_dossier(env)
    with pytest.raises(minter.MintError, match=reason + ".*next action"):
        mint(env, **overrides)
    assert not env["receipts"].exists()


@pytest.mark.parametrize("change", ["path", "fingerprint"])
def test_subject_mismatch_has_exact_repair_action(env, change):
    signed_dossier(env, **({"artifact_fingerprint": "0" * 64} if change == "fingerprint" else {}))
    if change == "path":
        other = env["root"] / "different.md"
        other.write_bytes(env["source"].read_bytes())
        env["source"] = other
    with pytest.raises(minter.MintError, match="subject_.*mismatch.*next action.*acceptance"):
        mint(env)
    assert not env["receipts"].exists()


def test_projection_mismatch_has_repair_action(env):
    signed_dossier(env)
    mint(env)
    fm, _ = draft(env)
    with pytest.raises(publish.PublicationGateError, match="projection differs.*next action"):
        build(env, frontmatter={**fm, "title": "Changed projection"})


def test_invalid_utf8_dossier_refuses_before_any_receipt_write(env):
    env["dossier"].write_bytes(b"\xff")
    with pytest.raises(minter.MintError, match="unreadable.*next action.*UTF-8"):
        mint(env)
    assert not env["receipts"].exists()


def test_unclassifiable_source_warns_preserves_and_prevents_dispatch(env, monkeypatch, caplog):
    from prometheus_client import CollectorRegistry

    from agents.publish_orchestrator import orchestrator

    signed_dossier(env)
    mint(env)
    artifact = build(env)
    before = env["source"].read_bytes()
    orch = orchestrator.Orchestrator(
        state_root=env["tmp"] / "unclassifiable-state", registry=CollectorRegistry()
    )
    with patch.object(
        orchestrator,
        "_vault_artifact_source",
        side_effect=(
            orchestrator.VaultArtifactHeadUnavailable(
                "fixture", "source classification unavailable"
            )
        ),
    ):
        orch._attach_gate_frontmatter(artifact)
        assert "unclassifiable" in caplog.text
        assert "next action:" in caplog.text
        pool = Mock()
        orch._hardening_gate.evaluate = Mock(side_effect=AssertionError("must stop before review"))
        orch._dispatch(artifact, pool=pool)
    pool.submit.assert_not_called()
    assert artifact.publication_gate_result["decision"] == "hold"
    assert env["source"].read_bytes() == before
