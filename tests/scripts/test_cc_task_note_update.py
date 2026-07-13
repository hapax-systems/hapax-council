from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "cc-task-note-update"
SESSION_ID = "019f465c-8137-7a52-9348-5602a988dc3d"


def _note(updated_at: str, body: str, *, status: str = "in_progress") -> str:
    return f"""---
type: cc-task
task_id: test-task
title: Test task
status: {status}
assigned_to: codex/cx-test
updated_at: {updated_at}
authority_case: CASE-TEST-001
parent_spec: spec.md
route_metadata_schema: 1
mutation_scope_refs: [shared/]
---

## Session Log

{body}
"""


def _environment(home: Path, *, cache: Path | None = None) -> dict[str, str]:
    cache = cache or home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (cache / f"cc-active-task-cx-test-{SESSION_ID}").write_text("test-task\n")
    environment = {
        **os.environ,
        "HOME": str(home),
        "HAPAX_AGENT_ROLE": "cx-test",
        "HAPAX_AGENT_NAME": "cx-test",
        "HAPAX_SESSION_ID": SESSION_ID,
    }
    environment.pop("HAPAX_CC_OWNERSHIP_CACHE_DIR", None)
    if cache != home / ".cache" / "hapax":
        environment["HAPAX_CC_OWNERSHIP_CACHE_DIR"] = str(cache)
    return environment


def _content_path(tmp_path: Path) -> Path:
    return Path("/tmp") / f"hapax-note-update-{tmp_path.name}.md"


def test_updates_body_through_exact_session_cas(tmp_path: Path) -> None:
    active = tmp_path / "Documents/Personal/20-projects/hapax-cc-tasks/active"
    active.mkdir(parents=True)
    note = active / "test-task.md"
    before = _note("2026-07-13T00:00:00Z", "before")
    after = _note("2026-07-13T00:01:00Z", "after")
    note.write_text(before, encoding="utf-8")
    content_file = _content_path(tmp_path)
    content_file.write_text(after, encoding="utf-8")
    try:
        result = subprocess.run(
            [
                str(SCRIPT),
                "--task-id",
                "test-task",
                "--expected-sha256",
                hashlib.sha256(before.encode()).hexdigest(),
                "--content-file",
                str(content_file),
            ],
            capture_output=True,
            text=True,
            env=_environment(tmp_path),
            timeout=15,
            check=False,
        )
    finally:
        content_file.unlink(missing_ok=True)

    assert result.returncode == 0, result.stderr
    assert note.read_text(encoding="utf-8") == after


def test_refuses_lifecycle_frontmatter_change(tmp_path: Path) -> None:
    active = tmp_path / "Documents/Personal/20-projects/hapax-cc-tasks/active"
    active.mkdir(parents=True)
    note = active / "test-task.md"
    before = _note("2026-07-13T00:00:00Z", "before")
    proposed = _note("2026-07-13T00:01:00Z", "after", status="done")
    note.write_text(before, encoding="utf-8")
    content_file = _content_path(tmp_path)
    content_file.write_text(proposed, encoding="utf-8")
    try:
        result = subprocess.run(
            [
                str(SCRIPT),
                "--task-id",
                "test-task",
                "--expected-sha256",
                hashlib.sha256(before.encode()).hexdigest(),
                "--content-file",
                str(content_file),
            ],
            capture_output=True,
            text=True,
            env=_environment(tmp_path),
            timeout=15,
            check=False,
        )
    finally:
        content_file.unlink(missing_ok=True)

    assert result.returncode == 2
    assert "dedicated cc-* lifecycle writer" in result.stderr
    assert note.read_text(encoding="utf-8") == before


def test_refuses_semantically_equivalent_frontmatter_reformat(tmp_path: Path) -> None:
    active = tmp_path / "Documents/Personal/20-projects/hapax-cc-tasks/active"
    active.mkdir(parents=True)
    note = active / "test-task.md"
    before = _note("2026-07-13T00:00:00Z", "before")
    proposed = _note("2026-07-13T00:01:00Z", "after").replace(
        "title: Test task", 'title: "Test task"'
    )
    note.write_text(before, encoding="utf-8")
    content_file = _content_path(tmp_path)
    content_file.write_text(proposed, encoding="utf-8")
    try:
        result = subprocess.run(
            [
                str(SCRIPT),
                "--task-id",
                "test-task",
                "--expected-sha256",
                hashlib.sha256(before.encode()).hexdigest(),
                "--content-file",
                str(content_file),
            ],
            capture_output=True,
            text=True,
            env=_environment(tmp_path),
            timeout=15,
            check=False,
        )
    finally:
        content_file.unlink(missing_ok=True)

    assert result.returncode == 2
    assert "exact top-level updated_at line" in result.stderr
    assert note.read_text(encoding="utf-8") == before


def test_honors_shared_ownership_cache_override(tmp_path: Path) -> None:
    active = tmp_path / "Documents/Personal/20-projects/hapax-cc-tasks/active"
    active.mkdir(parents=True)
    note = active / "test-task.md"
    before = _note("2026-07-13T00:00:00Z", "before")
    after = _note("2026-07-13T00:01:00Z", "after")
    note.write_text(before, encoding="utf-8")
    content_file = _content_path(tmp_path)
    content_file.write_text(after, encoding="utf-8")
    cache = tmp_path / "shared-ownership"
    try:
        result = subprocess.run(
            [
                str(SCRIPT),
                "--task-id",
                "test-task",
                "--expected-sha256",
                hashlib.sha256(before.encode()).hexdigest(),
                "--content-file",
                str(content_file),
            ],
            capture_output=True,
            text=True,
            env=_environment(tmp_path, cache=cache),
            timeout=15,
            check=False,
        )
    finally:
        content_file.unlink(missing_ok=True)

    assert result.returncode == 0, result.stderr
    assert note.read_text(encoding="utf-8") == after
    assert list(cache.glob(".cc-ownership-txn.json.history-*-committed"))
    assert not (tmp_path / ".cache/hapax").exists()


def test_postcommit_audit_failure_reports_warning_without_false_refusal(
    tmp_path: Path,
) -> None:
    active = tmp_path / "Documents/Personal/20-projects/hapax-cc-tasks/active"
    active.mkdir(parents=True)
    note = active / "test-task.md"
    before = _note("2026-07-13T00:00:00Z", "before")
    after = _note("2026-07-13T00:01:00Z", "after")
    note.write_text(before, encoding="utf-8")
    content_file = _content_path(tmp_path)
    content_file.write_text(after, encoding="utf-8")
    cache = tmp_path / "shared-ownership"
    environment = _environment(tmp_path, cache=cache)
    (cache / "cc-task-note-update.jsonl").mkdir()
    try:
        result = subprocess.run(
            [
                str(SCRIPT),
                "--task-id",
                "test-task",
                "--expected-sha256",
                hashlib.sha256(before.encode()).hexdigest(),
                "--content-file",
                str(content_file),
            ],
            capture_output=True,
            text=True,
            env=environment,
            timeout=15,
            check=False,
        )
    finally:
        content_file.unlink(missing_ok=True)

    assert result.returncode == 0, result.stderr
    assert "note committed but audit ledger append failed" in result.stderr
    assert note.read_text(encoding="utf-8") == after
