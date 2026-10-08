"""Isolated preparation-to-admission cases. All authority is synthetic fixture data."""

from pathlib import Path
from unittest.mock import patch

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
        **dict(
            task_id=TASK,
            artifact=env["source"],
            artifact_root=env["root"],
            authority_case=CASE,
            receipt_root=env["receipts"],
            receipt_refs=REFS,
            **overrides,
        )
    )


def build(env, **overrides):
    fm, body = draft(env)
    return publish._build_artifact(
        **dict(
            body_md=body,
            frontmatter=fm,
            surfaces=["bluesky-post"],
            approver="Oudepode",
            source_path=env["source"],
            review_task=TASK,
            receipt_refs=REFS,
            **overrides,
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
