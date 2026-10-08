"""Tests for the public-gate receipt minter (scripts/mint_public_gate_receipts.py)."""

from __future__ import annotations

import logging
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
CLAUDE = {"id": "claude-1", "family": "claude", "verdict": "accept"}
GEMINI = {"id": "gemini-1", "family": "gemini", "verdict": "accept"}
GLM = {"id": "glm-1", "family": "glm", "verdict": "accept"}
CODEX = {"id": "codex-1", "family": "codex", "verdict": "accept"}
MUSE = {"id": "muse-1", "family": "muse", "verdict": "accept"}

# Redacted structural basis: frozen cor0004 R3 dossier a3c55eee413ab144... (2026-10-08).
# All signatures and artifact bytes are created with the isolated test key, never copied.
MUSE_PROVENANCE = {
    "registry_id": "review-lenses",
    "family_substitution": {
        "seated_families": ["codex", "gemini", "muse"],
        "substitute_families_seated": ["muse"],
    },
}


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
        "---\nPublication-Allowed: true\ntitle: Announcement\n"
        f"slug: {SLUG}\nsurfaces_targeted:\n  - omg-weblog\n"
        f"publication_gate_receipts:\n{gates}\n---\n\n{body}"
    )


def _dossier(env, **overrides) -> None:
    payload = {
        "dossier_schema": 1,
        "task_id": TASK_ID,
        "head_sha": artifact_head_sha(env["manifest"]),
        "review_team_verdict": "quorum-accept",
        "quorum_required": 2,
        "accept_count": 2,
        "writer_family": "claude",
        "required_gates": list(env["declared"]),
        "authorized_public_gate_receipts": list(env["declared"].values()),
        "artifact_slug": env["bindings"]["artifact_slug"],
        "artifact_fingerprint": env["bindings"]["artifact_fingerprint"],
        "target_surfaces": list(env["bindings"]["target_surfaces"]),
        "artifact_review": {"artifact_root": str(env["root"]), "manifest": env["manifest"]},
        "reviewers": [GEMINI, GLM],
        "authority_issuer": "review-team:gemini,glm",
    }
    payload.update(overrides)
    payload["authority_signature"] = public_gate_receipts.public_gate_authority_signature(
        {k: v for k, v in payload.items() if k != "authority_signature"}, SECRET
    )
    env["dossier"].write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _mint(env, **overrides) -> dict:
    return minter.mint(
        **{
            "task_id": TASK_ID,
            "artifact": env["source"],
            "artifact_root": env["root"],
            "authority_case": CASE,
            "receipt_root": env["receipts"],
            **overrides,
        }
    )


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

    # The writer may vote, but never counts: two distinct families still meet the quorum.
    _dossier(env, reviewers=[CLAUDE, GEMINI, GLM])
    assert {item["state"] for item in _mint(env)["receipts"].values()} == {"unchanged"}


def test_signed_muse_substitution_mints_consumable_receipts(env) -> None:
    _dossier(env, writer_family="codex", reviewers=[GEMINI, CODEX, MUSE], **MUSE_PROVENANCE)
    _mint(env)
    for gate, ref in env["declared"].items():
        assert public_gate_receipts.public_gate_receipt_value_present(
            ref,
            expected_gate=gate,
            roots=(env["receipts"],),
            bindings=env["bindings"],
            expected_head_sha=artifact_head_sha(env["manifest"]),
        )


@pytest.mark.parametrize(
    "change",
    [
        {"registry_id": "bespoke"},
        {"family_substitution": {}},
        {"family_substitution": {"seated_families": ["muse"]}},
        {"family_substitution": {"substitute_families_seated": ["muse"]}},
        {"family_substitution": "muse"},
        {"reviewers": [CODEX, MUSE]},
        {"reviewers": [MUSE, MUSE]},
        {"reviewers": [GEMINI, {**MUSE, "family": "meta"}]},
        {"reviewers": [GEMINI, {**MUSE, "family": "local"}]},
        {"reviewers": [GEMINI, {**MUSE, "family": "vibe"}]},
        {"reviewers": [GEMINI, {**MUSE, "family": "featherless"}]},
    ],
)
def test_muse_cannot_supply_an_ungrounded_or_duplicate_vote(env, change) -> None:
    _dossier(
        env,
        **{
            "writer_family": "codex",
            "reviewers": [GEMINI, MUSE],
            **MUSE_PROVENANCE,
            **change,
        },
    )
    with pytest.raises(minter.MintError, match="mint_public_gate_quorum_not_independent"):
        _mint(env)
    assert not env["receipts"].exists()


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "read",
        "decode",
        "unmeasured",
        "command",
        "substitute",
        "duplicate",
        "schema",
        "malformed",
        "root_shape",
        "families_shape",
    ],
)
def test_muse_requires_the_trusted_registry_declaration(
    env, monkeypatch, caplog, capsys, damage
) -> None:
    registry = Path(__file__).resolve().parents[2] / "config/review-lenses/registry.yaml"
    data = yaml.safe_load(registry.read_text())
    if damage == "unmeasured":
        data["diff_capacity"]["seats"]["muse-1"].update(status="unmeasured", limit_bytes=80_000)
    elif damage in {"command", "substitute"}:
        row = next(r for r in data["families"] if r["family"] == "muse")
        row["reviewer_command" if damage == "command" else "substitute"] = (
            ["arbitrary-provider"] if damage == "command" else False
        )
    elif damage == "duplicate":
        data["families"].append(next(r for r in data["families"] if r["family"] == "muse"))
    elif damage == "schema":
        data["registry_schema"] = 2
    elif damage == "families_shape":
        data["families"] = {}
    elif damage == "root_shape":
        data = []
    path = env["root"] / "registry.yaml"
    if damage != "missing":
        path.write_text(
            "[private-registry-payload" if damage == "malformed" else yaml.safe_dump(data)
        )
    if damage == "decode":
        path.write_bytes(b"private-registry-payload\xff")
    if damage == "read":
        read_text = Path.read_text

        def unreadable(self, *args, **kwargs):
            if self == path:
                raise PermissionError("private-registry-payload")
            return read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", unreadable)
    _dossier(env, writer_family="codex", reviewers=[GEMINI, MUSE], **MUSE_PROVENANCE)
    _mint(env)
    monkeypatch.setattr(public_gate_receipts, "PUBLIC_GATE_REVIEW_REGISTRY_PATH", path)
    # Eligibility must still hold when an already minted receipt is consumed.
    for gate, ref in env["declared"].items():
        assert not public_gate_receipts.public_gate_receipt_value_present(
            ref,
            expected_gate=gate,
            roots=(env["receipts"],),
            bindings=env["bindings"],
            expected_head_sha=artifact_head_sha(env["manifest"]),
        )
    before = {p.name: p.read_bytes() for p in env["receipts"].iterdir()}
    with pytest.raises(minter.MintError, match="mint_public_gate_review_registry_invalid") as exc:
        _mint(env)
    assert {p.name: p.read_bytes() for p in env["receipts"].iterdir()} == before
    reason = {
        "missing": "missing",
        "read": "read_error",
        "decode": "decode_error",
        "malformed": "yaml_error",
        "schema": "invalid_registry",
        "root_shape": "invalid_registry",
        "families_shape": "invalid_registry",
        "unmeasured": "invalid_capacity",
    }.get(damage, "invalid_muse_declaration")
    assert minter.main(_argv(env)) == 1
    captured = capsys.readouterr()
    assert not captured.out
    for message in (caplog.text, str(exc.value), captured.err):
        assert str(path) in message
        assert reason in message
        assert "next action:" in message
        assert "private-registry-payload" not in message
    assert any(record.levelno == logging.WARNING for record in caplog.records)


@pytest.mark.parametrize("boundary", ["mint", "consume"])
@pytest.mark.parametrize(
    ("location", "key", "value"),
    [
        ("default", "measurement_file", None),
        ("default", "measurement_sha256", None),
        ("default", "measurement_sha256", "private-registry-payload"),
        ("default", "measurement_sha256", "A" * 64),
        ("muse-1", "limit_bytes", -1),
        ("muse-1", "limit_bytes", 0),
        ("muse-1", "limit_bytes", True),
        ("muse-1", "limit_bytes", "61494"),
        ("muse-1", "prompt_limit_bytes", -1),
        ("muse-1", "prompt_limit_bytes", 0),
        ("muse-1", "prompt_limit_bytes", True),
        ("muse-1", "prompt_limit_bytes", "95534"),
        ("muse-1", "measurement_file", None),
        ("muse-1", "measurement_sha256", None),
        ("muse-1", "status", ["measured"]),
        ("muse-1", "status", "private-registry-payload"),
        ("capacity", "default", None),
        ("capacity", "seats", []),
        ("seats", "muse-1", []),
        ("registry", "diff_capacity", None),
    ],
)
def test_invalid_inherited_capacity_refuses_at_use(
    env, monkeypatch, caplog, boundary, location, key, value
) -> None:
    _dossier(env, writer_family="codex", reviewers=[GEMINI, MUSE], **MUSE_PROVENANCE)
    if boundary == "consume":
        _mint(env)
    data = yaml.safe_load(public_gate_receipts.PUBLIC_GATE_REVIEW_REGISTRY_PATH.read_text())
    capacity = data["diff_capacity"]
    target = {
        "registry": data,
        "capacity": capacity,
        "default": capacity["default"],
        "seats": capacity["seats"],
        "muse-1": capacity["seats"]["muse-1"],
    }[location]
    target[key] = value
    path = env["root"] / "registry.yaml"
    path.write_text(yaml.safe_dump(data))
    monkeypatch.setattr(public_gate_receipts, "PUBLIC_GATE_REVIEW_REGISTRY_PATH", path)
    if boundary == "mint":
        with pytest.raises(minter.MintError, match="invalid_capacity") as exc:
            _mint(env)
        assert "next action:" in str(exc.value)
        assert str(path) in str(exc.value)
        assert not env["receipts"].exists()
    else:
        for gate, ref in env["declared"].items():
            assert not public_gate_receipts.public_gate_receipt_value_present(
                ref,
                expected_gate=gate,
                roots=(env["receipts"],),
                bindings=env["bindings"],
                expected_head_sha=artifact_head_sha(env["manifest"]),
            )
    assert "invalid_capacity" in caplog.text
    assert "next action:" in caplog.text
    assert str(path) in caplog.text
    assert "private-registry-payload" not in caplog.text
    assert any(record.levelno == logging.WARNING for record in caplog.records)


def test_muse_capacity_inherits_valid_default_fields(env, monkeypatch) -> None:
    data = yaml.safe_load(public_gate_receipts.PUBLIC_GATE_REVIEW_REGISTRY_PATH.read_text())
    capacity = data["diff_capacity"]
    capacity["default"].update(capacity["seats"]["muse-1"])
    capacity["seats"]["muse-1"] = {}
    path = env["root"] / "registry.yaml"
    path.write_text(yaml.safe_dump(data))
    monkeypatch.setattr(public_gate_receipts, "PUBLIC_GATE_REVIEW_REGISTRY_PATH", path)
    test_signed_muse_substitution_mints_consumable_receipts(env)


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
                "authorized_public_gate_receipts": [
                    f"public-gate:{SLUG}.{gate.replace('_', '-')}" for gate in GATES
                ]
            },
            "mint_public_gate_receipt_ref_malformed",
        ),
        (
            {
                "required_gates": _AUTHORIZED,
                "authorized_public_gate_receipts": [REF[gate] for gate in _AUTHORIZED],
            },
            "mint_public_gate_missing:claim_review_current",
        ),
        (
            {"writer_family": "claude", "reviewers": [CLAUDE, CLAUDE]},
            "mint_public_gate_quorum_not_independent:0/2",
        ),
        # D5 F1: the validator refuses quorum_required < 1, so the minter must too — before the
        # independence check, or a quorum-0 dossier mints zero-independence receipts create-once
        # that the validator then refuses, wedging the refs.
        (
            {
                "quorum_required": 0,
                "accept_count": 0,
                "writer_family": "claude",
                "reviewers": [CLAUDE],
            },
            "mint_public_gate_quorum_below_floor:0",
        ),
        # D5 F2: independence counts only the validator's allowlist, so an alias family does not count.
        (
            {
                "writer_family": "claude",
                "reviewers": [GLM, {"id": "glm-alias", "family": "glm-1", "verdict": "accept"}],
            },
            "mint_public_gate_quorum_not_independent:1/2",
        ),
        # D5 F2: a writer family outside the allowlist is refused, so "the writer counts nowhere"
        # cannot be dodged by an alias.
        (
            {"writer_family": "anthropic", "reviewers": [GEMINI, GLM]},
            "mint_public_gate_writer_family_not_allowlisted:anthropic",
        ),
        (
            {"writer_family": "claude", "reviewers": [CLAUDE, GEMINI]},
            "mint_public_gate_quorum_not_independent:1/2",
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


def test_refuses_a_non_injective_gate_to_ref_pairing(env) -> None:
    """D5 F3: two gates sharing one ref must refuse before any write, leaving no partial mint."""

    duplicated = dict(REF)
    duplicated["claim_review_current"] = duplicated["source_refs_present"]
    env["source"].write_text(_artifact_text(refs=duplicated), encoding="utf-8")
    manifest, _ = build_artifact_manifest([env["source"]], env["root"], max_chars=100_000)
    _dossier(
        env,
        head_sha=artifact_head_sha(manifest),
        artifact_review={"artifact_root": str(env["root"]), "manifest": manifest},
        required_gates=list(duplicated),
        authorized_public_gate_receipts=list(duplicated.values()),
    )

    with pytest.raises(minter.MintError, match="mint_public_gate_receipt_pairing_not_injective"):
        _mint(env)

    assert not env["receipts"].exists()


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
