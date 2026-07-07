"""Tests for the vault Markdown publication bridge."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import publish_vault_artifact

REPO_ROOT = Path(__file__).resolve().parents[2]
SHOW_HN_DRAFT = (
    REPO_ROOT / "docs" / "publication-drafts" / "2026-05-10-show-hn-governance-that-ships.md"
)
PUBLICATION_GATE_RECEIPTS = {
    "source_artifact_public_safe": "public-gate:test-source-safe",
    "source_refs_present": "public-gate:test-source-refs",
    "rights_privacy_redaction_pass": "public-gate:test-rights-privacy-redaction",
    "target_surface_allowlist_pass": "public-gate:test-target-surfaces",
    "claim_review_current": "public-gate:test-claim-review",
    "no_direct_public_egress": "public-gate:test-no-direct-egress",
}


@pytest.fixture(autouse=True)
def durable_public_gate_receipts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "public-gate-receipts"
    root.mkdir()
    for gate, receipt_ref in PUBLICATION_GATE_RECEIPTS.items():
        suffix = receipt_ref.removeprefix("public-gate:")
        (root / f"{suffix}.yaml").write_text(
            f"gate_id: {gate}\nstatus: passed\n",
            encoding="utf-8",
        )
    monkeypatch.setattr(publish_vault_artifact, "PUBLIC_GATE_RECEIPT_ROOTS", (root,))


def _allowed_frontmatter(**extra: object) -> dict[str, object]:
    return {
        "title": "Draft",
        "slug": "draft",
        "Publication-Allowed": True,
        "publication_gate_receipts": dict(PUBLICATION_GATE_RECEIPTS),
        **extra,
    }


def _gate_receipts_yaml() -> str:
    lines = ["publication_gate_receipts:"]
    lines.extend(f"  {gate}: {receipt}" for gate, receipt in PUBLICATION_GATE_RECEIPTS.items())
    return "\n".join(lines) + "\n"


def _write_policy(
    tmp_path: Path,
    *,
    required_gates: tuple[object, ...],
    status: str = "guarded_public_channel",
    target_surfaces: tuple[str, ...] = ("omg-weblog",),
) -> Path:
    path = tmp_path / "policy.yaml"
    gate_lines = "\n".join(f"    - {gate}" for gate in required_gates)
    target_lines = "\n".join(f"    - {surface}" for surface in target_surfaces)
    path.write_text(
        "schema_version: 1\n"
        "publication_frontmatter_policy:\n"
        f"  status: {status}\n"
        "  target_surfaces:\n"
        f"{target_lines}\n"
        "  required_gates:\n"
        f"{gate_lines}\n",
        encoding="utf-8",
    )
    return path


class TestBuildArtifact:
    def test_carries_source_path_and_author_model(self, tmp_path) -> None:
        source = tmp_path / "draft.md"
        source.write_text(
            "---\ntitle: Draft\nslug: draft\nauthor_model: codex\n---\n\nBody\n",
            encoding="utf-8",
        )

        artifact = publish_vault_artifact._build_artifact(
            body_md="Body",
            frontmatter=_allowed_frontmatter(author_model="codex"),
            surfaces=["omg-weblog"],
            approver="Oudepode",
            source_path=source,
        )

        assert artifact.slug == "draft"
        assert artifact.source_path == str(source)
        assert artifact.author_model == "codex"
        assert artifact.is_approved()

    def test_resolves_existing_title_slug_frontmatter_casing(self) -> None:
        artifact = publish_vault_artifact._build_artifact(
            body_md="# Body Heading\n\nBody",
            frontmatter={
                "Title": "Canonical Draft",
                "Slug": "canonical-draft",
                "Publication-Allowed": "approved",
                "publication_gate_receipts": dict(PUBLICATION_GATE_RECEIPTS),
            },
            surfaces=["omg-weblog"],
            approver="Oudepode",
        )

        assert artifact.title == "Canonical Draft"
        assert artifact.slug == "canonical-draft"
        assert artifact.surfaces_targeted == ["omg-weblog"]

    def test_carries_publication_gate_context_and_override(self) -> None:
        artifact = publish_vault_artifact._build_artifact(
            body_md="Body",
            frontmatter=_allowed_frontmatter(
                publication_gate_context={
                    "numeric_expectations": {"42 hooks": 42},
                    "currentness_evidence_refs": ["receipt:hn-readiness"],
                },
                publication_gate_override={
                    "by_referent": "Oudepode",
                    "reason": "Reviewed receipts",
                },
            ),
            surfaces=["omg-weblog"],
            approver="Oudepode",
        )

        assert artifact.publication_gate_context == {
            "numeric_expectations": {"42 hooks": 42},
            "currentness_evidence_refs": ["receipt:hn-readiness"],
            "publication_gate_receipts": PUBLICATION_GATE_RECEIPTS,
        }
        assert artifact.publication_gate_override == {
            "by_referent": "Oudepode",
            "reason": "Reviewed receipts",
        }

    def test_requires_explicit_publication_allowed(self) -> None:
        with pytest.raises(publish_vault_artifact.PublicationGateError):
            publish_vault_artifact._build_artifact(
                body_md="Body",
                frontmatter={"title": "Draft", "slug": "draft"},
                surfaces=["omg-weblog"],
                approver="Oudepode",
            )

    def test_rejects_surface_outside_configured_allowlist(self) -> None:
        with pytest.raises(publish_vault_artifact.SurfaceAllowlistError):
            publish_vault_artifact._build_artifact(
                body_md="Body",
                frontmatter=_allowed_frontmatter(),
                surfaces=["perplexity-model-council"],
                approver="Oudepode",
            )

    def test_requires_publication_gate_receipts(self) -> None:
        with pytest.raises(publish_vault_artifact.PublicationGateError, match="source_refs"):
            publish_vault_artifact._build_artifact(
                body_md="Body",
                frontmatter={
                    "title": "Draft",
                    "slug": "draft",
                    "Publication-Allowed": True,
                },
                surfaces=["omg-weblog"],
                approver="Oudepode",
            )

    def test_rejects_forged_publication_gate_receipts(self) -> None:
        with pytest.raises(publish_vault_artifact.PublicationGateError, match="invalid"):
            publish_vault_artifact._build_artifact(
                body_md="Body",
                frontmatter=_allowed_frontmatter(
                    publication_gate_receipts={
                        gate: "public-gate:forged" for gate in PUBLICATION_GATE_RECEIPTS
                    }
                ),
                surfaces=["omg-weblog"],
                approver="Oudepode",
            )

    def test_rejects_non_mapping_publication_gate_receipts(self) -> None:
        with pytest.raises(publish_vault_artifact.PublicationGateError, match="mapping"):
            publish_vault_artifact._build_artifact(
                body_md="Body",
                frontmatter=_allowed_frontmatter(publication_gate_receipts=["public-gate:x"]),
                surfaces=["omg-weblog"],
                approver="Oudepode",
            )

    def test_rejects_empty_explicit_surface_list(self) -> None:
        with pytest.raises(publish_vault_artifact.SurfaceAllowlistError, match="non-empty"):
            publish_vault_artifact._build_artifact(
                body_md="Body",
                frontmatter=_allowed_frontmatter(),
                surfaces=[],
                approver="Oudepode",
            )

    def test_rejects_surfaces_without_orchestrator_dispatch(self) -> None:
        with pytest.raises(publish_vault_artifact.SurfaceAllowlistError, match="not dispatchable"):
            publish_vault_artifact._build_artifact(
                body_md="Body",
                frontmatter=_allowed_frontmatter(),
                surfaces=["omg-lol-statuslog"],
                approver="Oudepode",
            )

    def test_rejects_malformed_surface_policy(self, tmp_path) -> None:
        policy = tmp_path / "policy.yaml"
        policy.write_text(
            "schema_version: 1\npublication_frontmatter_policy:\n  status: guarded_public_channel\n",
            encoding="utf-8",
        )

        with pytest.raises(publish_vault_artifact.SurfaceAllowlistError):
            publish_vault_artifact._configured_publication_surfaces((policy,))

    def test_rejects_policy_missing_baseline_gate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        policy = _write_policy(
            tmp_path,
            required_gates=("source_artifact_public_safe", "source_refs_present"),
        )
        monkeypatch.setattr(publish_vault_artifact, "PUBLICATION_POLICY_PATHS", (policy,))

        with pytest.raises(
            publish_vault_artifact.PublicationGateError,
            match="missing baseline gate ids",
        ):
            publish_vault_artifact._build_artifact(
                body_md="Body",
                frontmatter=_allowed_frontmatter(),
                surfaces=["omg-weblog"],
                approver="Oudepode",
            )

    def test_rejects_malformed_required_gate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        policy = _write_policy(
            tmp_path,
            required_gates=(*publish_vault_artifact.PUBLICATION_BASELINE_REQUIRED_GATES, ""),
        )
        monkeypatch.setattr(publish_vault_artifact, "PUBLICATION_POLICY_PATHS", (policy,))

        with pytest.raises(
            publish_vault_artifact.PublicationGateError,
            match="blank or non-string",
        ):
            publish_vault_artifact._build_artifact(
                body_md="Body",
                frontmatter=_allowed_frontmatter(),
                surfaces=["omg-weblog"],
                approver="Oudepode",
            )

    def test_fanout_policy_requires_loop_prevention_gate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        policy = _write_policy(
            tmp_path,
            status="guarded_public_fanout",
            target_surfaces=("omg-lol-weblog-bearer-fanout",),
            required_gates=publish_vault_artifact.PUBLICATION_BASELINE_REQUIRED_GATES,
        )
        monkeypatch.setattr(publish_vault_artifact, "PUBLICATION_POLICY_PATHS", (policy,))

        with pytest.raises(
            publish_vault_artifact.PublicationGateError,
            match="fanout_loop_prevention_present",
        ):
            publish_vault_artifact._required_publication_gate_receipts(
                ["omg-lol-weblog-bearer-fanout"]
            )


def test_allowed_draft_dry_run_uses_existing_frontmatter_casing(tmp_path, capsys) -> None:
    draft = tmp_path / "draft.md"
    draft.write_text(
        (
            "---\n"
            "Title: Allowed Draft\n"
            "Slug: allowed-draft\n"
            "Publication-Allowed: true\n"
            f"{_gate_receipts_yaml()}"
            "---\n\n"
            "# Allowed Draft\n\nBody\n"
        ),
        encoding="utf-8",
    )

    rc = publish_vault_artifact.main(
        [
            str(draft),
            "--surfaces",
            "omg-weblog",
            "--state-root",
            str(tmp_path),
            "--dry-run",
        ]
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["title"] == "Allowed Draft"
    assert payload["slug"] == "allowed-draft"
    assert payload["surfaces_targeted"] == ["omg-weblog"]
    assert payload["approval"] == "approved"
    assert not (tmp_path / "publish" / "inbox").exists()


def test_missing_publication_allowed_refuses_publication(tmp_path, capsys) -> None:
    draft = tmp_path / "draft.md"
    draft.write_text(
        ("---\nTitle: Missing Gate\nSlug: missing-gate\n---\n\n# Missing Gate\n\nBody\n"),
        encoding="utf-8",
    )

    rc = publish_vault_artifact.main(
        [
            str(draft),
            "--surfaces",
            "omg-weblog",
            "--state-root",
            str(tmp_path),
            "--dry-run",
        ]
    )

    assert rc == 1
    assert capsys.readouterr().out == ""
    assert not (tmp_path / "publish" / "inbox").exists()


def test_malformed_publication_allowed_refuses_publication(tmp_path, capsys) -> None:
    draft = tmp_path / "draft.md"
    draft.write_text(
        (
            "---\n"
            "Title: Malformed Gate\n"
            "Slug: malformed-gate\n"
            "Publication-Allowed: not-yet\n"
            "---\n\n"
            "# Malformed Gate\n\nBody\n"
        ),
        encoding="utf-8",
    )

    rc = publish_vault_artifact.main(
        [
            str(draft),
            "--surfaces",
            "omg-weblog",
            "--state-root",
            str(tmp_path),
            "--dry-run",
        ]
    )

    assert rc == 1
    assert capsys.readouterr().out == ""
    assert not (tmp_path / "publish" / "inbox").exists()


def test_invalid_yaml_frontmatter_refuses_publication_even_when_allowed(tmp_path, capsys) -> None:
    draft = tmp_path / "draft.md"
    draft.write_text(
        (
            "---\n"
            "Title: Invalid YAML\n"
            "Slug: invalid-yaml\n"
            "Publication-Allowed: true\n"
            "broken: [unterminated\n"
            "---\n\n"
            "# Invalid YAML\n\nBody\n"
        ),
        encoding="utf-8",
    )

    rc = publish_vault_artifact.main(
        [
            str(draft),
            "--surfaces",
            "omg-weblog",
            "--state-root",
            str(tmp_path),
            "--dry-run",
        ]
    )

    assert rc == 1
    assert capsys.readouterr().out == ""
    assert not (tmp_path / "publish" / "inbox").exists()


def test_surface_outside_allowlist_refuses_publication(tmp_path, capsys) -> None:
    draft = tmp_path / "draft.md"
    draft.write_text(
        (
            "---\n"
            "Title: Bad Surface\n"
            "Slug: bad-surface\n"
            "Publication-Allowed: true\n"
            "---\n\n"
            "# Bad Surface\n\nBody\n"
        ),
        encoding="utf-8",
    )

    rc = publish_vault_artifact.main(
        [
            str(draft),
            "--surfaces",
            "perplexity-model-council",
            "--state-root",
            str(tmp_path),
            "--dry-run",
        ]
    )

    assert rc == 1
    assert capsys.readouterr().out == ""
    assert not (tmp_path / "publish" / "inbox").exists()


def test_empty_explicit_surface_list_refuses_publication(tmp_path, capsys) -> None:
    draft = tmp_path / "draft.md"
    draft.write_text(
        (
            "---\n"
            "Title: Empty Surfaces\n"
            "Slug: empty-surfaces\n"
            "Publication-Allowed: true\n"
            f"{_gate_receipts_yaml()}"
            "---\n\n"
            "# Empty Surfaces\n\nBody\n"
        ),
        encoding="utf-8",
    )

    rc = publish_vault_artifact.main(
        [
            str(draft),
            "--surfaces",
            ",",
            "--state-root",
            str(tmp_path),
            "--dry-run",
        ]
    )

    assert rc == 1
    assert capsys.readouterr().out == ""
    assert not (tmp_path / "publish" / "inbox").exists()


def test_superseded_show_hn_draft_dry_run_refuses_publication(tmp_path, capsys) -> None:
    rc = publish_vault_artifact.main(
        [
            str(SHOW_HN_DRAFT),
            "--surfaces",
            "omg-weblog",
            "--state-root",
            str(tmp_path),
            "--dry-run",
        ]
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""
    assert not (tmp_path / "publish" / "inbox").exists()
