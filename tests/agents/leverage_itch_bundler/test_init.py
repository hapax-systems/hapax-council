"""Phase 1 tests for ``agents.leverage_itch_bundler``."""

from __future__ import annotations

from pathlib import Path

from agents.leverage_itch_bundler import (
    ARTIFACT_DATASET,
    ARTIFACT_PAPER,
    ARTIFACT_WHEEL,
    BundleArtifact,
    BundleManifest,
    render_butler_command,
    render_dry_run_report,
    scan_local_artifacts,
)


def test_target_format():
    manifest = BundleManifest(user="oudepode", slug="hapax-velocity-bundle", artifacts=())
    assert manifest.target("paper") == "oudepode/hapax-velocity-bundle:paper"


def test_butler_command_argv_shape():
    manifest = BundleManifest(user="u", slug="s", artifacts=())
    artifact = BundleArtifact(
        role=ARTIFACT_PAPER,
        source_path=Path("/tmp/paper.pdf"),
        channel=ARTIFACT_PAPER,
        bytes=1234,
    )
    cmd = render_butler_command(manifest, artifact)
    assert cmd[0] == "butler"
    assert cmd[1] == "push"
    assert cmd[2] == "/tmp/paper.pdf"
    assert cmd[3] == "u/s:paper"


def test_butler_command_no_token_in_argv():
    """Token is sourced from $BUTLER_API_KEY at runtime, never in argv."""
    manifest = BundleManifest(user="u", slug="s", artifacts=())
    artifact = BundleArtifact(
        role=ARTIFACT_PAPER,
        source_path=Path("/tmp/p.pdf"),
        channel=ARTIFACT_PAPER,
        bytes=1,
    )
    cmd = render_butler_command(manifest, artifact)
    cmd_str = " ".join(cmd)
    for forbidden in ("--api-key", "BUTLER_API_KEY", "secret", "token"):
        assert forbidden not in cmd_str.lower()


def test_scan_empty_when_no_files(tmp_path):
    manifest = scan_local_artifacts(
        paper_path=tmp_path / "missing.pdf",
        dataset_path=tmp_path / "missing.zip",
        dist_dir=tmp_path / "no-dist",
    )
    assert manifest.artifacts == ()


def test_scan_finds_paper_and_dataset(tmp_path):
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"PDF")
    dataset = tmp_path / "corpus.zip"
    dataset.write_bytes(b"ZIP")
    manifest = scan_local_artifacts(
        paper_path=paper, dataset_path=dataset, dist_dir=tmp_path / "no-dist"
    )
    roles = {a.role for a in manifest.artifacts}
    assert roles == {ARTIFACT_PAPER, ARTIFACT_DATASET}


def test_scan_finds_wheels(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "hapax_velocity-0.1-py3-none-any.whl").write_bytes(b"WHL")
    (dist / "hapax_methodology-0.2-py3-none-any.whl").write_bytes(b"WHL")
    manifest = scan_local_artifacts(
        paper_path=tmp_path / "x.pdf",
        dataset_path=tmp_path / "y.zip",
        dist_dir=dist,
    )
    wheel_artifacts = [a for a in manifest.artifacts if a.role == ARTIFACT_WHEEL]
    assert len(wheel_artifacts) == 2


def test_dry_run_report_empty_manifest():
    manifest = BundleManifest(user="u", slug="s", artifacts=())
    report = render_dry_run_report(manifest)
    assert "Artifacts discovered: **0**" in report
    assert "no artifacts discovered" in report


def test_dry_run_report_with_artifacts():
    manifest = BundleManifest(
        user="oudepode",
        slug="hapax-velocity-bundle",
        artifacts=(
            BundleArtifact(
                role=ARTIFACT_PAPER,
                source_path=Path("/tmp/paper.pdf"),
                channel=ARTIFACT_PAPER,
                bytes=4096,
            ),
        ),
    )
    report = render_dry_run_report(manifest)
    assert "Artifacts discovered: **1**" in report
    assert "oudepode/hapax-velocity-bundle:paper" in report
    assert "butler push" in report
    assert "--commit" in report


def test_main_dry_run_ok(capsys):
    from agents.leverage_itch_bundler.__main__ import main

    rc = main([])
    assert rc == 0
    captured = capsys.readouterr()
    assert "Itch.io PWYW bundle dry-run" in captured.out


def test_main_commit_blocked():
    from agents.leverage_itch_bundler.__main__ import main

    rc = main(["--commit"])
    assert rc == 2
