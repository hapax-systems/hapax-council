from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from shared.hkp_bundle_export import export_shadow_bundle
from shared.hkp_research_viewer import (
    REPORT_ROW_FIELDS,
    SUPPORT_LABEL,
    build_research_viewer_report,
)

GENERATED_AT = "2026-06-19T06:10:00Z"


def test_report_redacts_forbidden_fields_and_labels_rows(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_task(
        source_root / "tasks" / "demo.md",
        body="private body with SECRET_TOKEN=do-not-leak\n",
    )
    export = export_shadow_bundle(
        [source],
        bundle_id="viewer-demo",
        source_root=source_root,
        source_root_id="repo:test",
        generated_at=GENERATED_AT,
    )

    result = build_research_viewer_report(
        [export.bundle_path],
        report_id="viewer-report",
        generated_at=GENERATED_AT,
    )

    payload = result.as_dict()
    assert payload["support_label"] == SUPPORT_LABEL
    bundle = payload["bundles"][0]
    assert "bundle_path" not in bundle
    assert "input_ref_hash" not in bundle
    assert "source_root" not in bundle
    assert "source_commit" not in bundle
    row = bundle["rows"][0]
    assert row["support_label"] == SUPPORT_LABEL
    assert set(row) <= REPORT_ROW_FIELDS
    assert row["authority"] == {
        "level": "support_non_authoritative",
        "may_authorize": False,
        "ceiling_family": "evidence",
        "ceiling": "support_only",
        "promotion_required": "cc-task-with-authority-case",
    }
    serialized = json.dumps(payload, sort_keys=True)
    assert "do-not-leak" not in serialized
    assert "SECRET_TOKEN" not in serialized
    assert '"body"' not in serialized
    assert "private_source_path" not in serialized
    assert '"secret"' not in serialized
    assert result.markdown_path.is_relative_to(
        tmp_path / "home" / ".cache" / "hapax" / "hkp-reports"
    )
    assert result.json_path.is_file()


def test_report_omits_fields_forbidden_by_consumer_policy(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_task(source_root / "tasks" / "demo.md")
    export = export_shadow_bundle(
        [source],
        bundle_id="viewer-demo",
        source_root=source_root,
        source_root_id="repo:test",
        generated_at=GENERATED_AT,
    )
    policy_path = export.bundle_path / "_hkp" / "consumer_policy.yaml"
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    for row in policy["consumers"]:
        if row["consumer"] == "research_viewer":
            row["allowed_fields"].remove("description")
            row["forbidden_fields"].append("description")
    policy_path.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")

    result = build_research_viewer_report(
        [export.bundle_path],
        report_id="viewer-policy-report",
        generated_at=GENERATED_AT,
    )

    row = result.as_dict()["bundles"][0]["rows"][0]
    assert "title" in row
    assert "description" not in row
    serialized = json.dumps(result.as_dict(), sort_keys=True)
    assert '"description"' not in serialized


def test_report_omits_fields_absent_from_consumer_policy_allowed_fields(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_task(source_root / "tasks" / "demo.md")
    export = export_shadow_bundle(
        [source],
        bundle_id="viewer-demo",
        source_root=source_root,
        source_root_id="repo:test",
        generated_at=GENERATED_AT,
    )
    policy_path = export.bundle_path / "_hkp" / "consumer_policy.yaml"
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    for row in policy["consumers"]:
        if row["consumer"] == "research_viewer":
            row["allowed_fields"].remove("description")
    policy_path.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")

    result = build_research_viewer_report(
        [export.bundle_path],
        report_id="viewer-allowlist-report",
        generated_at=GENERATED_AT,
    )

    row = result.as_dict()["bundles"][0]["rows"][0]
    assert "title" in row
    assert "description" not in row
    assert '"description"' not in json.dumps(result.as_dict(), sort_keys=True)


def test_report_omits_support_fields_absent_from_consumer_policy_aliases(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_task(source_root / "tasks" / "demo.md")
    export = export_shadow_bundle(
        [source],
        bundle_id="viewer-demo",
        source_root=source_root,
        source_root_id="repo:test",
        generated_at=GENERATED_AT,
    )
    policy_path = export.bundle_path / "_hkp" / "consumer_policy.yaml"
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    for row in policy["consumers"]:
        if row["consumer"] == "research_viewer":
            for field in (
                "freshness",
                "posture",
                "validator_findings",
                "bundle_uid",
                "output_tree_hash",
            ):
                row["allowed_fields"].remove(field)
    policy_path.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")

    result = build_research_viewer_report(
        [export.bundle_path],
        report_id="viewer-support-allowlist-report",
        generated_at=GENERATED_AT,
    )

    bundle = result.as_dict()["bundles"][0]
    assert "bundle_uid" not in bundle
    assert "output_tree_hash" not in bundle
    assert "findings" not in bundle
    row = bundle["rows"][0]
    for field in (
        "bundle_uid",
        "output_tree_hash",
        "source_freshness",
        "freshness_state",
        "privacy_class",
        "egress_state",
        "public_export_allowed",
        "denied_consumers",
        "findings",
    ):
        assert field not in row


def test_report_rejects_denied_research_viewer_consumer_policy(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_task(source_root / "tasks" / "demo.md")
    export = export_shadow_bundle(
        [source],
        bundle_id="viewer-demo",
        source_root=source_root,
        source_root_id="repo:test",
        generated_at=GENERATED_AT,
    )
    policy_path = export.bundle_path / "_hkp" / "consumer_policy.yaml"
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    for row in policy["consumers"]:
        if row["consumer"] == "research_viewer":
            row["default"] = "deny"
            row["allowed_fields"] = []
    policy_path.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="denies research_viewer"):
        build_research_viewer_report(
            [export.bundle_path],
            report_id="viewer-policy-deny-report",
            generated_at=GENERATED_AT,
        )


def test_report_rejects_concept_posture_forbidden_research_viewer(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_task(source_root / "tasks" / "demo.md")
    export = export_shadow_bundle(
        [source],
        bundle_id="viewer-demo",
        source_root=source_root,
        source_root_id="repo:test",
        generated_at=GENERATED_AT,
    )
    concept_path = next((export.bundle_path / "concepts").glob("*.md"))
    frontmatter, body = _read_hkp_markdown(concept_path)
    frontmatter["posture"]["allowed_consumers"].remove("research_viewer")
    frontmatter["posture"]["forbidden_consumers"].append("research_viewer")
    _write_hkp_markdown(concept_path, frontmatter, body)

    with pytest.raises(ValueError, match="concept posture denies research_viewer"):
        build_research_viewer_report(
            [export.bundle_path],
            report_id="viewer-posture-deny-report",
            generated_at=GENERATED_AT,
        )


def test_report_includes_findings_and_source_freshness_markers(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = source_root / "scripts" / "tool.py"
    source.parent.mkdir(parents=True)
    source.write_text("print('no frontmatter')\n", encoding="utf-8")
    export_shadow_bundle(
        [source],
        bundle_id="viewer-code",
        source_root=source_root,
        source_root_id="repo:test",
        generated_at=GENERATED_AT,
    )

    result = build_research_viewer_report(
        ["viewer-code"],
        report_id="viewer-code-report",
        generated_at=GENERATED_AT,
    )

    bundle = result.as_dict()["bundles"][0]
    row = bundle["rows"][0]
    assert bundle["validator_ok"] is True
    assert row["source_freshness"] == ["fresh"]
    assert row["freshness_state"] == "fresh"
    assert row["privacy_class"] == "internal"
    assert row["egress_state"] == "private"
    assert "source_frontmatter_unparseable" in {finding["code"] for finding in row["findings"]}
    assert "qdrant_rag" in row["denied_consumers"]
    assert "public_export" in row["denied_consumers"]
    assert "support_non_authoritative_projection_state" in result.markdown_path.read_text(
        encoding="utf-8"
    )


def test_report_redacts_private_path_and_secret_text_from_findings(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_task(source_root / "tasks" / "demo.md")
    export = export_shadow_bundle(
        [source],
        bundle_id="viewer-demo",
        source_root=source_root,
        source_root_id="repo:test",
        generated_at=GENERATED_AT,
    )
    private_path = "/home/hapax/Documents/Personal/private.md"
    export.index_path.write_text(
        json.dumps(
            {
                "record_type": "finding",
                "severity": "warning",
                "subject": f"{private_path} SECRET_TOKEN=do-not-leak",
                "path": private_path,
                "message": f"leaked {private_path} SECRET_TOKEN=do-not-leak",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = build_research_viewer_report(
        [export.bundle_path],
        report_id="viewer-finding-redaction-report",
        generated_at=GENERATED_AT,
    )

    serialized = json.dumps(result.as_dict(), sort_keys=True)
    assert "/home/hapax" not in serialized
    assert "SECRET_TOKEN" not in serialized
    assert "[private-path-redacted]" in serialized
    assert "[secret-redacted]" in serialized
    assert "[outside-bundle-path-redacted]" in serialized


def test_report_default_discovery_reads_real_cache_bundles(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_task(source_root / "tasks" / "demo.md")
    export_shadow_bundle(
        [source],
        bundle_id="viewer-discovered",
        source_root=source_root,
        source_root_id="repo:test",
        generated_at=GENERATED_AT,
    )

    result = build_research_viewer_report(
        report_id="viewer-discovered-report",
        generated_at=GENERATED_AT,
    )

    assert result.as_dict()["bundle_count"] == 1
    assert result.as_dict()["bundles"][0]["bundle_id"] == "viewer-discovered"


def test_report_rejects_inputs_and_outputs_outside_cache(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    outside = tmp_path / "outside-bundle"
    outside.mkdir()

    with pytest.raises(ValueError, match="must be under"):
        build_research_viewer_report([outside])
    with pytest.raises(ValueError, match="must be under"):
        build_research_viewer_report(report_root=tmp_path / "reports-outside-cache")
    with pytest.raises(ValueError, match="must be under"):
        build_research_viewer_report(index_root=tmp_path / "index-outside-cache")


def test_report_rejects_discovered_symlinked_bundle(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    shadow_root = tmp_path / "home" / ".cache" / "hapax" / "hkp-shadow"
    shadow_root.mkdir(parents=True)
    outside = tmp_path / "outside-bundle"
    (outside / "_hkp").mkdir(parents=True)
    (outside / "_hkp" / "manifest.yaml").write_text("cache_only: true\n", encoding="utf-8")
    (shadow_root / "linked-bundle").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="must not traverse symlink component"):
        build_research_viewer_report(
            report_id="viewer-symlink-report",
            generated_at=GENERATED_AT,
        )


def test_report_rejects_explicit_symlinked_bundle(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    shadow_root = tmp_path / "home" / ".cache" / "hapax" / "hkp-shadow"
    shadow_root.mkdir(parents=True)
    outside = tmp_path / "outside-bundle"
    outside.mkdir()
    bundle_link = shadow_root / "linked-bundle"
    bundle_link.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="must not traverse symlink component"):
        build_research_viewer_report(
            [bundle_link],
            report_id="viewer-explicit-symlink-report",
            generated_at=GENERATED_AT,
        )


def test_report_rejects_symlinked_required_bundle_artifact(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_task(source_root / "tasks" / "demo.md")
    export = export_shadow_bundle(
        [source],
        bundle_id="viewer-demo",
        source_root=source_root,
        source_root_id="repo:test",
        generated_at=GENERATED_AT,
    )
    outside = tmp_path / "outside-policy.yaml"
    outside.write_text("consumers: []\n", encoding="utf-8")
    policy = export.bundle_path / "_hkp" / "consumer_policy.yaml"
    policy.unlink()
    policy.symlink_to(outside)

    with pytest.raises(ValueError, match="must not traverse symlink component"):
        build_research_viewer_report(
            [export.bundle_path],
            report_id="viewer-artifact-symlink-report",
            generated_at=GENERATED_AT,
        )


def test_report_rejects_broken_temp_symlink_before_write(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_task(source_root / "tasks" / "demo.md")
    export = export_shadow_bundle(
        [source],
        bundle_id="viewer-demo",
        source_root=source_root,
        source_root_id="repo:test",
        generated_at=GENERATED_AT,
    )
    report_dir = tmp_path / "home" / ".cache" / "hapax" / "hkp-reports" / "viewer-report"
    report_dir.mkdir(parents=True)
    outside = tmp_path / "outside-report.md"
    (report_dir / ".report.md.tmp").symlink_to(outside)

    with pytest.raises(ValueError, match="must not traverse symlink component"):
        build_research_viewer_report(
            [export.bundle_path],
            report_id="viewer-report",
            generated_at=GENERATED_AT,
        )
    assert not outside.exists()


def test_report_rejects_unsafe_report_id(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_task(source_root / "tasks" / "demo.md")
    export = export_shadow_bundle(
        [source],
        bundle_id="viewer-demo",
        source_root=source_root,
        source_root_id="repo:test",
        generated_at=GENERATED_AT,
    )

    with pytest.raises(ValueError, match="report_id is not a safe cache path component"):
        build_research_viewer_report([export.bundle_path], report_id="../escape")


def _write_task(path: Path, *, body: str = "body\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "---",
                "type: cc-task",
                "task_id: viewer-demo",
                'title: "Viewer Demo"',
                "authority_case: CASE-HKP-TEST",
                "parent_spec: /tmp/spec.md",
                "route_metadata_schema: 1",
                "quality_floor: deterministic_ok",
                "mutation_surface: source",
                "authority_level: authoritative",
                "---",
                "",
                body,
            ]
        ),
        encoding="utf-8",
    )
    return path


def _read_hkp_markdown(path: Path) -> tuple[dict[str, object], str]:
    text = path.read_text(encoding="utf-8")
    _, frontmatter_text, body = text.split("---", 2)
    return yaml.safe_load(frontmatter_text), body


def _write_hkp_markdown(path: Path, frontmatter: dict[str, object], body: str) -> None:
    path.write_text(
        "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---" + body,
        encoding="utf-8",
    )
