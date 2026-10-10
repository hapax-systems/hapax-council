"""The seat memory export is a projection of the existing Claude source."""

import json
import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/hapax-seat-memory-export"


def run_export(source: Path, dest: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPT), "--source-dir", str(source), "--dest-dir", str(dest)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_changed_source_refreshes_read_only_projection_without_rewriting_unchanged(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "MEMORY.md").write_text("[one](one.md)\n", encoding="utf-8")
    (source / "one.md").write_text("first\n", encoding="utf-8")
    dest = tmp_path / "vault" / "memory-export-current"

    first = run_export(source, dest)
    assert first.returncode == 0, first.stderr
    assert json.loads(first.stdout)["status"] == "updated"
    assert (dest / "one.md").read_bytes() == b"first\n"
    assert (dest / "one.md").stat().st_mode & 0o222 == 0
    first_mtime = (dest / "one.md").stat().st_mtime_ns

    second = run_export(source, dest)
    assert second.returncode == 0, second.stderr
    assert json.loads(second.stdout)["status"] == "unchanged"
    assert (dest / "one.md").stat().st_mtime_ns == first_mtime

    (source / "one.md").write_text("second\n", encoding="utf-8")
    third = run_export(source, dest)
    assert third.returncode == 0, third.stderr
    assert (dest / "one.md").read_bytes() == b"second\n"
    assert "second" not in third.stdout
    assert len(json.loads((dest / "INDEX.json").read_text())["files"]) == 2


def test_export_refuses_symlinked_source_note_without_touching_destination(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "private.md"
    outside.write_text("private\n", encoding="utf-8")
    (source / "MEMORY.md").write_text("index\n", encoding="utf-8")
    (source / "escape.md").symlink_to(outside)
    dest = tmp_path / "vault" / "memory-export-current"
    result = run_export(source, dest)
    assert result.returncode != 0
    assert "source_symlink" in result.stderr
    assert not dest.exists()
    assert "private" not in result.stdout + result.stderr


def test_export_refuses_symlinked_destination(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "MEMORY.md").write_text("index\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    dest = tmp_path / "memory-export-current"
    os.symlink(outside, dest)
    result = run_export(source, dest)
    assert result.returncode != 0
    assert "destination_symlink" in result.stderr
    assert list(outside.iterdir()) == []


def test_deleted_source_note_is_removed_only_when_it_matches_managed_export(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "MEMORY.md").write_text("index\n", encoding="utf-8")
    note = source / "retired.md"
    note.write_text("retired data\n", encoding="utf-8")
    dest = tmp_path / "vault" / "memory-export-current"
    assert run_export(source, dest).returncode == 0
    note.unlink()
    assert run_export(source, dest).returncode == 0
    assert not (dest / "retired.md").exists()

    note.write_text("new data\n", encoding="utf-8")
    assert run_export(source, dest).returncode == 0
    note.unlink()
    (dest / "retired.md").chmod(0o644)
    (dest / "retired.md").write_text("operator edit\n", encoding="utf-8")
    refused = run_export(source, dest)
    assert refused.returncode != 0
    assert "managed_file_changed" in refused.stderr
    assert (dest / "retired.md").read_text() == "operator edit\n"
