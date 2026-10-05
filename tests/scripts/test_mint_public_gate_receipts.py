"""Tests for the public-gate receipt minter (scripts/mint_public_gate_receipts.py)."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest
import yaml

from scripts import mint_public_gate_receipts as minter
from scripts import publish_vault_artifact as publish
from shared import public_gate_receipts
from shared.review_artifact_manifest import artifact_head_sha, build_artifact_manifest

TASK_ID = "c1-edition2-announcement-copy-20261004"
SECRET = "test-public-gate-authority-secret"  # pragma: allowlist secret
CASE = "CASE-SYSTEM-INTEGRITY-20260611"
GATES = publish.PUBLICATION_BASELINE_REQUIRED_GATES
SLUG = "announcement"
REF = {gate: f"public-gate:{SLUG}-{gate.replace('_', '-')}" for gate in GATES}


def _argv(env) -> list[str]:
    return [
        "--task-id",
        TASK_ID,
        "--authority-case",
        CASE,
        "--artifact",
        str(env["source"]),
        "--artifact-root",
        str(env["root"]),
        "--receipt-root",
        str(env["receipts"]),
    ]


def _artifact_text(refs=REF, body="Body\n") -> str:
    gates = "\n".join(f"  {gate}: {ref}" for gate, ref in refs.items())
    return (
        "---\n"
        "Publication-Allowed: true\n"
        "title: Announcement\n"
        f"slug: {SLUG}\n"
        "surfaces_targeted:\n  - omg-weblog\n"
        f"publication_gate_receipts:\n{gates}\n"
        "---\n\n"
        f"{body}"
    )


def _dossier(env, **overrides) -> None:
    payload = {
        "dossier_schema": 1,
        "task_id": TASK_ID,
        "head_sha": artifact_head_sha(env["manifest"]),
        "review_team_verdict": "quorum-accept",
        "quorum_required": 2,
        "accept_count": 3,
        "writer_family": "claude",
        "required_gates": list(env["declared"]),
        "authorized_public_gate_receipts": list(env["declared"].values()),
        "artifact_slug": env["bindings"]["artifact_slug"],
        "artifact_fingerprint": env["bindings"]["artifact_fingerprint"],
        "target_surfaces": list(env["bindings"]["target_surfaces"]),
        "artifact_review": {"artifact_root": str(env["root"]), "manifest": env["manifest"]},
        "reviewers": [
            {"id": "gemini-1", "family": "gemini", "verdict": "accept"},
            {"id": "glm-1", "family": "glm", "verdict": "accept-with-findings"},
            {"id": "claude-1", "family": "claude", "verdict": "accept-with-findings"},
        ],
        "authority_issuer": "review-team:gemini,glm,claude",
    }
    payload.update(overrides)
    payload["authority_signature"] = public_gate_receipts.public_gate_authority_signature(
        {key: value for key, value in payload.items() if key != "authority_signature"}, SECRET
    )
    env["dossier"].write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _mint(env, **overrides) -> dict:
    kwargs = {
        "task_id": TASK_ID,
        "artifact": env["source"],
        "artifact_root": env["root"],
        "authority_case": CASE,
        "receipt_root": env["receipts"],
    }
    kwargs.update(overrides)
    return minter.mint(**kwargs)


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    root = tmp_path / "Personal"
    source = root / "frame" / "announcement.md"
    source.parent.mkdir(parents=True)
    source.write_text(_artifact_text(), encoding="utf-8")
    authority = tmp_path / "authority"
    authority.mkdir()
    monkeypatch.setattr(public_gate_receipts, "PUBLIC_GATE_AUTHORITY_ROOTS", (authority,))
    monkeypatch.setenv(public_gate_receipts.PUBLIC_GATE_AUTHORITY_SECRET_ENV, SECRET)
    frontmatter, body = publish._parse_publication_markdown(source)
    with mock.patch.object(publish, "_assert_publication_gate_receipts"):
        artifact = publish._build_artifact(
            body_md=body,
            frontmatter=frontmatter,
            surfaces=["omg-weblog"],
            approver="Oudepode",
            source_path=source,
        )
    manifest, _ = build_artifact_manifest([source], root, max_chars=100_000)
    return {
        "root": root,
        "source": source,
        "receipts": tmp_path / "receipts",
        "dossier": authority / f"{TASK_ID}.review-dossier.yaml",
        "manifest": manifest,
        "bindings": publish._publication_gate_receipt_bindings(artifact),
        "declared": publish._publication_gate_receipts(frontmatter),
    }


def test_mints_receipts_the_validator_accepts(env) -> None:
    _dossier(env)
    summary = _mint(env)

    assert sorted(summary["receipts"]) == sorted(GATES)
    for gate, ref in env["declared"].items():
        assert public_gate_receipts.public_gate_receipt_value_present(
            ref,
            expected_gate=gate,
            roots=(env["receipts"],),
            bindings=env["bindings"],
            expected_head_sha=artifact_head_sha(env["manifest"]),
        ), gate
        assert summary["receipts"][gate]["state"] == "written"
    text = (env["receipts"] / f"{SLUG}-claim-review-current.yaml").read_text(encoding="utf-8")
    assert "authority_signature: hmac-sha256:" in text
    assert SECRET not in text
    assert minter.main(_argv(env)) == 0

    # A tampered signature no longer grounds: the same acceptance now holds.
    payload = yaml.safe_load(env["dossier"].read_text(encoding="utf-8"))
    payload["authority_signature"] = "hmac-sha256:" + "0" * 64
    env["dossier"].write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    with pytest.raises(minter.MintError, match="mint_public_gate_acceptance_unsigned"):
        _mint(env)


_AUTHORIZED = [gate for gate in GATES if gate != "claim_review_current"]


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"head_sha": "a" * 40}, "mint_public_gate_head_not_an_artifact_head"),
        ({"review_team_verdict": "blocked"}, "mint_public_gate_not_quorum_accept"),
        ({"artifact_fingerprint": ""}, "mint_public_gate_bindings_missing"),
        (
            {"authorized_public_gate_receipts": [*REF.values(), "public-gate:extra.yaml"]},
            "mint_public_gate_receipt_unauthorized",
        ),
        (
            {
                "required_gates": _AUTHORIZED,
                "authorized_public_gate_receipts": [REF[gate] for gate in _AUTHORIZED],
            },
            "mint_public_gate_missing:claim_review_current",
        ),
        (
            {
                "writer_family": "claude",
                "reviewers": [{"id": "claude-1", "family": "claude", "verdict": "accept"}],
            },
            "mint_public_gate_writer_family_majority:claude:1/1",
        ),
    ],
)
def test_refuses_an_acceptance_that_is_not_grounding(env, overrides, reason) -> None:
    _dossier(env, **overrides)

    with pytest.raises(minter.MintError, match=reason):
        _mint(env)

    assert not env["receipts"].exists()


def test_refuses_when_the_artifact_bytes_changed(env) -> None:
    _dossier(env)
    env["source"].write_text(_artifact_text(body="Changed\n"), encoding="utf-8")

    with pytest.raises(minter.MintError, match="mint_public_gate_artifact_changed"):
        _mint(env)


def test_refuses_a_ref_the_validator_could_never_resolve(env) -> None:
    dotted = {gate: f"public-gate:{SLUG}.{gate.replace('_', '-')}" for gate in GATES}
    env["source"].write_text(_artifact_text(refs=dotted), encoding="utf-8")
    manifest, _ = build_artifact_manifest([env["source"]], env["root"], max_chars=100_000)
    _dossier(
        env,
        head_sha=artifact_head_sha(manifest),
        artifact_review={"artifact_root": str(env["root"]), "manifest": manifest},
        authorized_public_gate_receipts=list(dotted.values()),
    )

    with pytest.raises(minter.MintError, match="mint_public_gate_receipt_ref_malformed"):
        _mint(env)


def test_receipts_are_create_once(env) -> None:
    _dossier(env)
    _mint(env)
    assert {item["state"] for item in _mint(env)["receipts"].values()} == {"unchanged"}

    target = env["receipts"] / f"{SLUG}-claim-review-current.yaml"
    target.write_text("gate_id: claim_review_current\nstatus: passed\n", encoding="utf-8")

    with pytest.raises(minter.MintError, match="mint_public_gate_receipt_exists"):
        _mint(env)
    assert target.read_text(encoding="utf-8") == "gate_id: claim_review_current\nstatus: passed\n"


def test_main_reports_a_hold_on_stderr(env, capsys) -> None:
    _dossier(env, head_sha="a" * 40)

    assert minter.main(_argv(env)) == 1
    assert "mint_public_gate_head_not_an_artifact_head" in capsys.readouterr().err
