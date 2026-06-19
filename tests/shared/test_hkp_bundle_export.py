from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from shared.hkp_bundle_export import (
    _tree_hash,
    build_derived_index,
    build_shadow_catalog,
    export_shadow_bundle,
)
from shared.hkp_bundle_schema import STALE_SOURCE_STATES, validate_bundle

GENERATED_AT = "2026-06-18T20:03:41Z"
INDEX_REPORTED_SOURCE_STATES = tuple(sorted(STALE_SOURCE_STATES))


def test_exporter_emits_validator_clean_cache_bundle(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_task(source_root / "tasks" / "demo.md")

    result = export_shadow_bundle(
        [source],
        bundle_id="demo-bundle",
        source_root=source_root,
        source_root_id="repo:test",
        source_commit="abc123",
        generated_at=GENERATED_AT,
    )

    assert result.bundle_path.is_relative_to(tmp_path / "home" / ".cache" / "hapax" / "hkp-shadow")
    assert result.index_path.is_file()
    assert validate_bundle(result.bundle_path).ok is True
    assert (result.bundle_path / "index.md").is_file()
    assert (result.bundle_path / "log.md").is_file()
    assert (result.bundle_path / "_hkp" / "manifest.yaml").is_file()
    assert (result.bundle_path / "_hkp" / "consumer_policy.yaml").is_file()
    assert (result.bundle_path / "_hkp" / "edges.jsonl").is_file()
    assert (result.bundle_path / "_hkp" / "events.jsonl").is_file()
    assert (result.bundle_path / "_hkp" / "snapshot.json").is_file()
    assert (result.bundle_path / "_hkp" / "checksums.json").is_file()
    assert result.edge_count == 1

    manifest = yaml.safe_load((result.bundle_path / "_hkp" / "manifest.yaml").read_text())
    assert manifest["source_root"] == "repo:test"
    assert manifest["cache_only"] is True
    assert manifest["output_tree_hash"] == _tree_hash(result.bundle_path)
    assert manifest["allowed_consumers"] == ["research_viewer", "local_prompt_context"]
    assert {"qdrant_rag", "public_export", "dispatcher", "close_gate"} <= set(
        manifest["forbidden_consumers"]
    )

    concept_text = next((result.bundle_path / "concepts").glob("*.md")).read_text()
    assert str(source_root) not in concept_text
    concept = yaml.safe_load(concept_text.split("---", 2)[1])
    source_ref = concept["source_refs"][0]
    assert source_ref["uri"] == "repo:test/tasks/demo.md"
    assert source_ref["content_hash"].startswith("sha256:")
    assert source_ref["hash_scope"] == "full_content"
    assert source_ref["observed_at"] == GENERATED_AT
    assert source_ref["checked_at"] == GENERATED_AT
    assert source_ref["stale_after"] == "P7D"
    assert concept["authority"]["may_authorize"] is False
    assert "qdrant_rag" not in concept["posture"]["allowed_consumers"]

    events = [
        json.loads(line)
        for line in (result.bundle_path / "_hkp" / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    event_ids = {event["event_id"] for event in events}
    assert set(concept["projection_provenance"]["projection_event_ids"]) <= event_ids
    edges = [
        json.loads(line)
        for line in (result.bundle_path / "_hkp" / "edges.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert {edge["generated_from"]["projection_event_id"] for edge in edges} <= event_ids


def test_exporter_is_deterministic_for_same_inputs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_task(source_root / "tasks" / "demo.md")

    first = export_shadow_bundle(
        [source],
        bundle_id="demo-bundle",
        source_root=source_root,
        source_root_id="repo:test",
        generated_at=GENERATED_AT,
    )
    first_checksums = (first.bundle_path / "_hkp" / "checksums.json").read_text()

    second = export_shadow_bundle(
        [source],
        bundle_id="demo-bundle",
        source_root=source_root,
        source_root_id="repo:test",
        generated_at=GENERATED_AT,
    )

    assert second.output_tree_hash == first.output_tree_hash
    assert (second.bundle_path / "_hkp" / "checksums.json").read_text() == first_checksums


def test_exporter_preserves_append_only_log_on_bundle_rerun(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_task(source_root / "tasks" / "demo.md")

    first = export_shadow_bundle(
        [source],
        bundle_id="demo-bundle",
        source_root=source_root,
        source_root_id="repo:test",
        generated_at=GENERATED_AT,
    )
    second = export_shadow_bundle(
        [source],
        bundle_id="demo-bundle",
        source_root=source_root,
        source_root_id="repo:test",
        generated_at="2026-06-18T20:04:41Z",
    )

    log_lines = (second.bundle_path / "log.md").read_text(encoding="utf-8").splitlines()
    assert f"- `{GENERATED_AT}` `{first.bundle_uid}` generated from 1 source ref(s)." in log_lines
    assert (
        f"- `2026-06-18T20:04:41Z` `{second.bundle_uid}` generated from 1 source ref(s)."
        in log_lines
    )


def test_exporter_rejects_non_cache_output_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_task(source_root / "tasks" / "demo.md")

    with pytest.raises(ValueError) as exc_info:
        export_shadow_bundle(
            [source],
            bundle_id="demo-bundle",
            source_root=source_root,
            source_root_id="repo:test",
            output_root=tmp_path / "not-cache",
            generated_at=GENERATED_AT,
        )
    assert "HKP bundle output must be under" in str(exc_info.value)
    assert "next-action" in str(exc_info.value)


def test_exporter_rejects_non_file_source_with_next_action(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"

    with pytest.raises(ValueError) as exc_info:
        export_shadow_bundle(
            [source_root / "missing.md"],
            bundle_id="demo-bundle",
            source_root=source_root,
            source_root_id="repo:test",
            generated_at=GENERATED_AT,
        )
    assert "source path is not a file" in str(exc_info.value)
    assert "next-action" in str(exc_info.value)


def test_exporter_rejects_source_outside_root_with_next_action(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    outside = _write_task(tmp_path / "outside" / "demo.md")

    with pytest.raises(ValueError) as exc_info:
        export_shadow_bundle(
            [outside],
            bundle_id="demo-bundle",
            source_root=source_root,
            source_root_id="repo:test",
            generated_at=GENERATED_AT,
        )
    assert "source path must be under source_root" in str(exc_info.value)
    assert "next-action" in str(exc_info.value)


def test_exporter_reports_unparseable_frontmatter(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = source_root / "tasks" / "bad.md"
    source.parent.mkdir(parents=True)
    source.write_text("---\ntitle: [unterminated\n---\n# Bad\n", encoding="utf-8")

    result = export_shadow_bundle(
        [source],
        bundle_id="bad-frontmatter-bundle",
        source_root=source_root,
        source_root_id="repo:test",
        generated_at=GENERATED_AT,
    )

    assert "source_frontmatter_unparseable" in {finding.code for finding in result.findings}
    finding = next(
        finding for finding in result.findings if finding.code == "source_frontmatter_unparseable"
    )
    assert finding.severity == "warning"
    assert "next-action" in finding.message


def test_exporter_reports_code_unparseable_frontmatter_as_error(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = source_root / "src" / "bad.py"
    source.parent.mkdir(parents=True)
    source.write_text("---\ntitle: [unterminated\n---\nprint('bad')\n", encoding="utf-8")

    result = export_shadow_bundle(
        [source],
        bundle_id="bad-code-frontmatter-bundle",
        source_root=source_root,
        source_root_id="repo:test",
        generated_at=GENERATED_AT,
    )

    finding = next(
        finding for finding in result.findings if finding.code == "source_frontmatter_unparseable"
    )
    assert finding.severity == "error"
    assert "next-action" in finding.message


def test_exporter_rejects_non_cache_index_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_task(source_root / "tasks" / "demo.md")

    with pytest.raises(ValueError) as exc_info:
        export_shadow_bundle(
            [source],
            bundle_id="demo-bundle",
            source_root=source_root,
            source_root_id="repo:test",
            index_root=tmp_path / "not-cache-index",
            generated_at=GENERATED_AT,
        )
    assert "HKP derived index must be under" in str(exc_info.value)
    assert "next-action" in str(exc_info.value)


@pytest.mark.parametrize("bundle_id", [".", "", "/", "foo/bar", "foo bar", "../demo"])
def test_exporter_rejects_unsafe_bundle_id(tmp_path: Path, monkeypatch, bundle_id: str) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_task(source_root / "tasks" / "demo.md")

    with pytest.raises(ValueError) as exc_info:
        export_shadow_bundle(
            [source],
            bundle_id=bundle_id,
            source_root=source_root,
            source_root_id="repo:test",
            generated_at=GENERATED_AT,
        )
    assert "bundle_id is not a safe cache path component" in str(exc_info.value)
    assert "next-action" in str(exc_info.value)


def test_exporter_rejects_symlinked_cache_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_task(source_root / "tasks" / "demo.md")
    outside = tmp_path / "outside-cache-target"
    outside.mkdir()
    shadow_root = tmp_path / "home" / ".cache" / "hapax" / "hkp-shadow"
    shadow_root.parent.mkdir(parents=True)
    shadow_root.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError) as exc_info:
        export_shadow_bundle(
            [source],
            bundle_id="demo-bundle",
            source_root=source_root,
            source_root_id="repo:test",
            generated_at=GENERATED_AT,
        )
    assert "must not traverse symlink component" in str(exc_info.value)
    assert "next-action" in str(exc_info.value)


def test_exporter_allows_relocated_parent_cache(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    source_root = tmp_path / "repo"
    source = _write_task(source_root / "tasks" / "demo.md")
    cache_target = tmp_path / "cache-target"
    cache_target.mkdir()
    home.mkdir()
    (home / ".cache").symlink_to(cache_target, target_is_directory=True)

    result = export_shadow_bundle(
        [source],
        bundle_id="demo-bundle",
        source_root=source_root,
        source_root_id="repo:test",
        generated_at=GENERATED_AT,
    )

    assert result.bundle_path == home / ".cache" / "hapax" / "hkp-shadow" / "demo-bundle"
    assert (cache_target / "hapax" / "hkp-shadow" / "demo-bundle").is_dir()


def test_derived_index_rejects_non_cache_index_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_task(source_root / "tasks" / "demo.md")
    result = export_shadow_bundle(
        [source],
        bundle_id="demo-bundle",
        source_root=source_root,
        source_root_id="repo:test",
        generated_at=GENERATED_AT,
    )

    with pytest.raises(ValueError) as exc_info:
        build_derived_index(result.bundle_path, index_path=tmp_path / "index.jsonl")
    assert "HKP derived index must be under" in str(exc_info.value)
    assert "next-action" in str(exc_info.value)


def test_derived_index_rejects_non_cache_bundle_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    index_path = tmp_path / "home" / ".cache" / "hapax" / "hkp-shadow-index" / "index.jsonl"

    with pytest.raises(ValueError) as exc_info:
        build_derived_index(tmp_path / "outside-bundle", index_path=index_path)
    assert "HKP bundle input must be under" in str(exc_info.value)
    assert "next-action" in str(exc_info.value)


def test_derived_index_rejects_symlinked_index_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_task(source_root / "tasks" / "demo.md")
    result = export_shadow_bundle(
        [source],
        bundle_id="demo-bundle",
        source_root=source_root,
        source_root_id="repo:test",
        generated_at=GENERATED_AT,
    )
    outside = tmp_path / "outside-index.jsonl"
    outside.write_text("outside\n", encoding="utf-8")
    index_path = tmp_path / "home" / ".cache" / "hapax" / "hkp-shadow-index" / "symlink.jsonl"
    index_path.symlink_to(outside)

    with pytest.raises(ValueError) as exc_info:
        build_derived_index(result.bundle_path, index_path=index_path)
    assert "must not traverse symlink component" in str(exc_info.value)
    assert outside.read_text(encoding="utf-8") == "outside\n"


def test_exporter_preserves_duplicate_source_ids_for_index_findings(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    first = _write_task(source_root / "tasks" / "first.md")
    second = _write_task(source_root / "tasks" / "second.md")

    result = export_shadow_bundle(
        [first, second],
        bundle_id="duplicate-source-id-bundle",
        source_root=source_root,
        source_root_id="repo:test",
        generated_at=GENERATED_AT,
    )

    concept_paths = sorted(path.name for path in (result.bundle_path / "concepts").glob("*.md"))
    assert len(concept_paths) == 2
    assert concept_paths[0] != concept_paths[1]
    assert "duplicate_concept_uid" in {finding.code for finding in result.findings}
    rows = _jsonl_rows(result.index_path)
    assert any(
        row["record_type"] == "finding" and row["code"] == "duplicate_concept_uid" for row in rows
    )


def test_exporter_rejects_bundle_regular_file_collision(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_task(source_root / "tasks" / "demo.md")
    shadow_root = tmp_path / "home" / ".cache" / "hapax" / "hkp-shadow"
    shadow_root.mkdir(parents=True)
    (shadow_root / "demo-bundle").write_text("not a bundle\n", encoding="utf-8")

    with pytest.raises(ValueError) as exc_info:
        export_shadow_bundle(
            [source],
            bundle_id="demo-bundle",
            source_root=source_root,
            source_root_id="repo:test",
            generated_at=GENERATED_AT,
        )

    assert "path collision is not a directory" in str(exc_info.value)
    assert "next-action" in str(exc_info.value)
    assert (shadow_root / "demo-bundle").read_text(encoding="utf-8") == "not a bundle\n"


def test_exporter_cleans_stale_temp_and_backup_regular_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_task(source_root / "tasks" / "demo.md")
    shadow_root = tmp_path / "home" / ".cache" / "hapax" / "hkp-shadow"
    shadow_root.mkdir(parents=True)
    (shadow_root / ".demo-bundle.tmp").write_text("stale temp\n", encoding="utf-8")
    (shadow_root / ".demo-bundle.previous").write_text("stale backup\n", encoding="utf-8")

    result = export_shadow_bundle(
        [source],
        bundle_id="demo-bundle",
        source_root=source_root,
        source_root_id="repo:test",
        generated_at=GENERATED_AT,
    )

    assert validate_bundle(result.bundle_path).ok is True
    assert not (shadow_root / ".demo-bundle.tmp").exists()
    assert not (shadow_root / ".demo-bundle.previous").exists()


def test_exporter_rejects_symlinked_temp_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_task(source_root / "tasks" / "demo.md")
    shadow_root = tmp_path / "home" / ".cache" / "hapax" / "hkp-shadow"
    shadow_root.mkdir(parents=True)
    outside = tmp_path / "outside-temp"
    outside.mkdir()
    (shadow_root / ".demo-bundle.tmp").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError) as exc_info:
        export_shadow_bundle(
            [source],
            bundle_id="demo-bundle",
            source_root=source_root,
            source_root_id="repo:test",
            generated_at=GENERATED_AT,
        )

    assert "must not traverse symlink component" in str(exc_info.value)
    assert "next-action" in str(exc_info.value)


def test_exporter_rolls_back_existing_bundle_when_replace_fails(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_task(source_root / "tasks" / "demo.md")
    result = export_shadow_bundle(
        [source],
        bundle_id="demo-bundle",
        source_root=source_root,
        source_root_id="repo:test",
        generated_at=GENERATED_AT,
    )
    original_log = (result.bundle_path / "log.md").read_text(encoding="utf-8")
    original_replace = Path.replace

    def fail_tmp_replace(self: Path, target: Path | str) -> Path:
        target_path = Path(target)
        if self.name == ".demo-bundle.tmp" and target_path.name == "demo-bundle":
            raise OSError("forced replace failure")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_tmp_replace)

    with pytest.raises(ValueError) as exc_info:
        export_shadow_bundle(
            [source],
            bundle_id="demo-bundle",
            source_root=source_root,
            source_root_id="repo:test",
            generated_at="2026-06-18T20:04:41Z",
        )

    assert "failed to replace HKP bundle output atomically" in str(exc_info.value)
    assert "next-action" in str(exc_info.value)
    assert (result.bundle_path / "log.md").read_text(encoding="utf-8") == original_log
    assert not (result.bundle_path.parent / ".demo-bundle.tmp").exists()
    assert not (result.bundle_path.parent / ".demo-bundle.previous").exists()


def test_exporter_reports_secondary_rollback_failure(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_task(source_root / "tasks" / "demo.md")
    result = export_shadow_bundle(
        [source],
        bundle_id="demo-bundle",
        source_root=source_root,
        source_root_id="repo:test",
        generated_at=GENERATED_AT,
    )
    original_replace = Path.replace

    def fail_tmp_and_backup_replace(self: Path, target: Path | str) -> Path:
        target_path = Path(target)
        if self.name == ".demo-bundle.tmp" and target_path.name == "demo-bundle":
            raise OSError("forced replace failure")
        if self.name == ".demo-bundle.previous" and target_path.name == "demo-bundle":
            raise OSError("forced rollback failure")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_tmp_and_backup_replace)

    with pytest.raises(ValueError) as exc_info:
        export_shadow_bundle(
            [source],
            bundle_id="demo-bundle",
            source_root=source_root,
            source_root_id="repo:test",
            generated_at="2026-06-18T20:04:41Z",
        )

    message = str(exc_info.value)
    assert "rollback failed" in message
    assert "forced replace failure" in message
    assert "forced rollback failure" in message
    assert "next-action" in message
    assert not (result.bundle_path.parent / ".demo-bundle.tmp").exists()
    assert (result.bundle_path.parent / ".demo-bundle.previous").is_dir()


def test_exporter_cleans_index_temp_when_atomic_index_replace_fails(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_task(source_root / "tasks" / "demo.md")
    original_replace = Path.replace
    failed_tmp_path: Path | None = None

    def fail_index_tmp_replace(self: Path, target: Path | str) -> Path:
        nonlocal failed_tmp_path
        target_path = Path(target)
        if target_path.name == "demo-bundle.jsonl":
            failed_tmp_path = self
            raise OSError("forced index replace failure")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_index_tmp_replace)

    with pytest.raises(ValueError) as exc_info:
        export_shadow_bundle(
            [source],
            bundle_id="demo-bundle",
            source_root=source_root,
            source_root_id="repo:test",
            generated_at=GENERATED_AT,
        )

    assert "failed to write HKP derived index atomically" in str(exc_info.value)
    assert "next-action" in str(exc_info.value)
    assert failed_tmp_path is not None
    assert not failed_tmp_path.exists()


def test_manifest_and_checksums_are_excluded_from_tree_hash(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_task(source_root / "tasks" / "demo.md")
    result = export_shadow_bundle(
        [source],
        bundle_id="demo-bundle",
        source_root=source_root,
        source_root_id="repo:test",
        generated_at=GENERATED_AT,
    )
    initial_tree_hash = _tree_hash(result.bundle_path)

    manifest_path = result.bundle_path / "_hkp" / "manifest.yaml"
    manifest_path.write_text(manifest_path.read_text(encoding="utf-8") + "# ignored\n")
    checksums_path = result.bundle_path / "_hkp" / "checksums.json"
    checksums_path.write_text(checksums_path.read_text(encoding="utf-8") + "\n")

    assert _tree_hash(result.bundle_path) == initial_tree_hash
    (result.bundle_path / "index.md").write_text("changed\n", encoding="utf-8")
    assert _tree_hash(result.bundle_path) != initial_tree_hash


def test_derived_index_reports_validation_and_route_findings(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_task(source_root / "tasks" / "demo.md", include_route_metadata=False)
    result = export_shadow_bundle(
        [source],
        bundle_id="demo-bundle",
        source_root=source_root,
        source_root_id="repo:test",
        generated_at=GENERATED_AT,
    )
    export_route_finding = next(
        finding for finding in result.findings if finding.code == "route_metadata_gap"
    )
    assert export_route_finding.severity == "error"
    assert "next-action" in export_route_finding.message
    concept_path = next((result.bundle_path / "concepts").glob("*.md"))
    concept_path.write_text(
        concept_path.read_text(encoding="utf-8") + "\nBroken [link](missing.md).\n",
        encoding="utf-8",
    )
    index_path = tmp_path / "home" / ".cache" / "hapax" / "hkp-shadow-index" / "index.jsonl"

    findings = build_derived_index(result.bundle_path, index_path=index_path)

    codes = {finding.code for finding in findings}
    assert "broken_markdown_link" in codes
    assert "route_metadata_gap" in codes
    route_finding = next(finding for finding in findings if finding.code == "route_metadata_gap")
    assert route_finding.severity == "error"
    assert "next-action" in route_finding.message
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines()]
    assert any(
        row["record_type"] == "finding"
        and row["code"] == "route_metadata_gap"
        and row["severity"] == "error"
        for row in rows
    )


def test_derived_index_route_gap_warning_for_non_authority_source_class(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_task(source_root / "tasks" / "demo.md")
    result = export_shadow_bundle(
        [source],
        bundle_id="demo-bundle",
        source_root=source_root,
        source_root_id="repo:test",
        generated_at=GENERATED_AT,
    )
    concept_path = next((result.bundle_path / "concepts").glob("*.md"))
    concept_text = concept_path.read_text(encoding="utf-8")
    frontmatter = yaml.safe_load(concept_text.split("---", 2)[1])
    frontmatter["source_refs"][0]["source_authority_class"] = "none"
    frontmatter["extensions"]["hapax"]["route_metadata_gaps"] = ["authority_case"]
    concept_path.write_text(
        "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\n\n# Demo\n",
        encoding="utf-8",
    )
    index_path = tmp_path / "home" / ".cache" / "hapax" / "hkp-shadow-index" / "index.jsonl"

    findings = build_derived_index(result.bundle_path, index_path=index_path)

    route_finding = next(finding for finding in findings if finding.code == "route_metadata_gap")
    assert route_finding.severity == "warning"


def test_derived_index_route_gap_error_if_later_source_ref_is_authoritative(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_task(source_root / "tasks" / "demo.md")
    result = export_shadow_bundle(
        [source],
        bundle_id="demo-bundle",
        source_root=source_root,
        source_root_id="repo:test",
        generated_at=GENERATED_AT,
    )
    concept_path = next((result.bundle_path / "concepts").glob("*.md"))
    concept_text = concept_path.read_text(encoding="utf-8")
    frontmatter = yaml.safe_load(concept_text.split("---", 2)[1])
    secondary_ref = dict(frontmatter["source_refs"][0])
    frontmatter["source_refs"][0]["source_authority_class"] = "none"
    secondary_ref["ref_id"] = "src:authoritative-secondary"
    secondary_ref["source_authority_class"] = "source_mutation"
    frontmatter["source_refs"].append(secondary_ref)
    frontmatter["extensions"]["hapax"]["route_metadata_gaps"] = ["authority_case"]
    concept_path.write_text(
        "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\n\n# Demo\n",
        encoding="utf-8",
    )
    index_path = tmp_path / "home" / ".cache" / "hapax" / "hkp-shadow-index" / "index.jsonl"

    findings = build_derived_index(result.bundle_path, index_path=index_path)

    route_finding = next(finding for finding in findings if finding.code == "route_metadata_gap")
    assert route_finding.severity == "error"


@pytest.mark.parametrize("state", INDEX_REPORTED_SOURCE_STATES)
def test_derived_index_reports_source_freshness_state(
    tmp_path: Path, monkeypatch, state: str
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_task(source_root / "tasks" / "demo.md")
    result = export_shadow_bundle(
        [source],
        bundle_id="demo-bundle",
        source_root=source_root,
        source_root_id="repo:test",
        generated_at=GENERATED_AT,
    )
    concept_path = next((result.bundle_path / "concepts").glob("*.md"))
    concept_text = concept_path.read_text(encoding="utf-8")
    frontmatter = yaml.safe_load(concept_text.split("---", 2)[1])
    frontmatter["freshness"]["state"] = state
    concept_path.write_text(
        "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\n\n# Demo\n",
        encoding="utf-8",
    )
    index_path = tmp_path / "home" / ".cache" / "hapax" / "hkp-shadow-index" / "index.jsonl"

    findings = build_derived_index(result.bundle_path, index_path=index_path)

    assert f"source_{state}" in {finding.code for finding in findings}


def test_derived_index_explicitly_reports_stale_and_missing_states(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_task(source_root / "tasks" / "demo.md")
    result = export_shadow_bundle(
        [source],
        bundle_id="demo-bundle",
        source_root=source_root,
        source_root_id="repo:test",
        generated_at=GENERATED_AT,
    )
    concept_path = next((result.bundle_path / "concepts").glob("*.md"))
    concept_text = concept_path.read_text(encoding="utf-8")
    missing_frontmatter = yaml.safe_load(concept_text.split("---", 2)[1])
    missing_frontmatter["freshness"]["state"] = "missing"
    concept_path.write_text(
        "---\n" + yaml.safe_dump(missing_frontmatter, sort_keys=False) + "---\n\n# Missing\n",
        encoding="utf-8",
    )
    stale_frontmatter = dict(missing_frontmatter)
    stale_frontmatter["concept_uid"] = "hkp:cc-task:stale-task"
    stale_frontmatter["concept_path"] = "stale-task"
    stale_frontmatter["freshness"] = {**missing_frontmatter["freshness"], "state": "stale"}
    (result.bundle_path / "concepts" / "stale.md").write_text(
        "---\n" + yaml.safe_dump(stale_frontmatter, sort_keys=False) + "---\n\n# Stale\n",
        encoding="utf-8",
    )
    index_path = tmp_path / "home" / ".cache" / "hapax" / "hkp-shadow-index" / "index.jsonl"

    findings = build_derived_index(result.bundle_path, index_path=index_path)

    codes = {finding.code for finding in findings}
    assert "source_missing" in codes
    assert "source_stale" in codes


def test_derived_index_does_not_report_fresh_source_state(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_task(source_root / "tasks" / "demo.md")
    result = export_shadow_bundle(
        [source],
        bundle_id="demo-bundle",
        source_root=source_root,
        source_root_id="repo:test",
        generated_at=GENERATED_AT,
    )
    index_path = tmp_path / "home" / ".cache" / "hapax" / "hkp-shadow-index" / "index.jsonl"

    findings = build_derived_index(result.bundle_path, index_path=index_path)

    assert "source_fresh" not in {finding.code for finding in findings}


def test_derived_index_reports_duplicate_source_ids(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_task(source_root / "tasks" / "demo.md")
    result = export_shadow_bundle(
        [source],
        bundle_id="demo-bundle",
        source_root=source_root,
        source_root_id="repo:test",
        generated_at=GENERATED_AT,
    )
    concept_path = next((result.bundle_path / "concepts").glob("*.md"))
    duplicate = result.bundle_path / "concepts" / "duplicate.md"
    duplicate.write_text(concept_path.read_text(encoding="utf-8"), encoding="utf-8")
    index_path = tmp_path / "home" / ".cache" / "hapax" / "hkp-shadow-index" / "index.jsonl"

    findings = build_derived_index(result.bundle_path, index_path=index_path)

    assert "duplicate_concept_uid" in {finding.code for finding in findings}


def test_shadow_catalog_summarizes_bundle_findings(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    clean_source = _write_task(source_root / "tasks" / "clean.md")
    gap_source = _write_task(
        source_root / "tasks" / "missing-route.md",
        include_route_metadata=False,
    )
    clean = export_shadow_bundle(
        [clean_source],
        bundle_id="clean-bundle",
        source_root=source_root,
        source_root_id="repo:test",
        generated_at=GENERATED_AT,
    )
    gap = export_shadow_bundle(
        [gap_source],
        bundle_id="gap-bundle",
        source_root=source_root,
        source_root_id="repo:test",
        generated_at=GENERATED_AT,
    )

    result = build_shadow_catalog(generated_at=GENERATED_AT)

    assert result.catalog_path.is_relative_to(
        tmp_path / "home" / ".cache" / "hapax" / "hkp-shadow-index"
    )
    assert result.bundle_count == 2
    assert result.finding_count >= 1
    assert result.error_count >= 1
    rows = _jsonl_rows(result.catalog_path)
    assert rows[0]["record_type"] == "catalog"
    assert {row["bundle_id"] for row in rows if row["record_type"] == "bundle_summary"} == {
        "clean-bundle",
        "gap-bundle",
    }
    gap_summary = next(
        row
        for row in rows
        if row["record_type"] == "bundle_summary" and row["bundle_id"] == "gap-bundle"
    )
    assert gap_summary["validator_ok"] is True
    assert gap_summary["catalog_ok"] is False
    assert any(
        row["record_type"] == "finding"
        and row["bundle_id"] == "gap-bundle"
        and row["code"] == "route_metadata_gap"
        for row in rows
    )
    assert clean.bundle_path.is_dir()
    assert gap.bundle_path.is_dir()


def test_shadow_catalog_writes_empty_catalog_when_shadow_root_is_absent(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    result = build_shadow_catalog(generated_at=GENERATED_AT)

    assert result.ok is True
    assert result.bundle_count == 0
    assert result.catalog_path.is_file()
    assert _jsonl_rows(result.catalog_path) == [
        {
            "record_type": "catalog",
            "generated_at": GENERATED_AT,
            "shadow_root": str(tmp_path / "home" / ".cache" / "hapax" / "hkp-shadow"),
            "bundle_count": 0,
            "finding_count": 0,
            "error_count": 0,
        }
    ]


def test_shadow_catalog_rejects_non_cache_roots(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    with pytest.raises(ValueError) as shadow_exc:
        build_shadow_catalog(shadow_root=tmp_path / "outside-shadow")
    assert "HKP shadow catalog input must be under" in str(shadow_exc.value)
    assert "next-action" in str(shadow_exc.value)

    with pytest.raises(ValueError) as index_exc:
        build_shadow_catalog(index_root=tmp_path / "outside-index")
    assert "HKP shadow catalog must be under" in str(index_exc.value)
    assert "next-action" in str(index_exc.value)


def test_shadow_catalog_rejects_symlinked_shadow_bundle_child(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    shadow_root = tmp_path / "home" / ".cache" / "hapax" / "hkp-shadow"
    shadow_root.mkdir(parents=True)
    outside = tmp_path / "outside-bundle"
    outside.mkdir()
    (shadow_root / "linked-bundle").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError) as exc_info:
        build_shadow_catalog(generated_at=GENERATED_AT)

    assert "must not traverse symlink component" in str(exc_info.value)
    assert "next-action" in str(exc_info.value)


def test_shadow_catalog_rejects_non_directory_shadow_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    shadow_root = tmp_path / "home" / ".cache" / "hapax" / "hkp-shadow"
    shadow_root.parent.mkdir(parents=True)
    shadow_root.write_text("not a directory\n", encoding="utf-8")

    with pytest.raises(ValueError) as exc_info:
        build_shadow_catalog(generated_at=GENERATED_AT)

    assert "HKP shadow catalog input must be a directory" in str(exc_info.value)
    assert "next-action" in str(exc_info.value)


def test_shadow_catalog_rejects_non_directory_index_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    index_root = tmp_path / "home" / ".cache" / "hapax" / "hkp-shadow-index"
    index_root.parent.mkdir(parents=True)
    index_root.write_text("not a directory\n", encoding="utf-8")

    with pytest.raises(ValueError) as exc_info:
        build_shadow_catalog(generated_at=GENERATED_AT)

    assert "HKP shadow catalog output must be a directory" in str(exc_info.value)
    assert "next-action" in str(exc_info.value)


def _jsonl_rows(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _write_task(path: Path, *, include_route_metadata: bool = True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "type": "cc-task",
        "task_id": "demo-task",
        "title": "Demo task",
        "status": "done",
        "depends_on": ["upstream-task"],
        "privacy_class": "internal",
    }
    if include_route_metadata:
        frontmatter.update(
            {
                "authority_case": "CASE-SDLC-REFORM-001",
                "parent_spec": "/redacted/spec.md",
                "route_metadata_schema": 1,
                "quality_floor": "frontier_required",
                "mutation_surface": "source",
                "authority_level": "authoritative",
            }
        )
    path.write_text(
        "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\n\n# Demo\nPrivate body.\n",
        encoding="utf-8",
    )
    return path
