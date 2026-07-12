"""Tests for executable SDLC dispatch worktree guards."""

from __future__ import annotations

from pathlib import Path

from shared.sdlc_dispatch_guards import (
    CLAIM_DISPATCH_PROTOCOL_VERSION,
    DISPATCH_CLAIM_GUARD_MARKERS,
    check_worktree_claim_guard,
)


def _write_claim(worktree: Path, body: str, *, executable: bool = True) -> Path:
    script = worktree / "scripts" / "cc-claim"
    script.parent.mkdir(parents=True)
    script.write_text(f"#!/usr/bin/env bash\n{body}", encoding="utf-8")
    script.chmod(0o755 if executable else 0o644)
    return script


def test_worktree_claim_guard_executes_exact_local_protocol_probe(tmp_path: Path) -> None:
    worktree = tmp_path / "lane"
    marker = tmp_path / "probe-ran"
    _write_claim(
        worktree,
        f"""printf '%s' "$PWD" > {marker}
printf '%s\\n' '{CLAIM_DISPATCH_PROTOCOL_VERSION}'
""",
    )

    ok, reason = check_worktree_claim_guard(worktree)

    assert ok is True
    assert CLAIM_DISPATCH_PROTOCOL_VERSION in reason
    assert marker.read_text(encoding="utf-8") == str(worktree.resolve())


def test_worktree_claim_guard_rejects_legacy_text_markers_without_protocol(
    tmp_path: Path,
) -> None:
    worktree = tmp_path / "lane"
    _write_claim(
        worktree,
        f"# {' '.join(DISPATCH_CLAIM_GUARD_MARKERS)}\necho legacy\n",
    )

    ok, reason = check_worktree_claim_guard(worktree)

    assert ok is False
    assert "expected dispatch protocol" in reason


def test_worktree_claim_guard_rejects_extra_protocol_output(tmp_path: Path) -> None:
    worktree = tmp_path / "lane"
    _write_claim(
        worktree,
        f"printf '%s\\n%s\\n' '{CLAIM_DISPATCH_PROTOCOL_VERSION}' extra\n",
    )

    ok, reason = check_worktree_claim_guard(worktree)

    assert ok is False
    assert "stale cc-claim" in reason


def test_worktree_claim_guard_requires_executable_probe(tmp_path: Path) -> None:
    worktree = tmp_path / "lane"
    script = _write_claim(
        worktree,
        f"printf '%s\\n' '{CLAIM_DISPATCH_PROTOCOL_VERSION}'\n",
        executable=False,
    )

    ok, reason = check_worktree_claim_guard(worktree)

    assert ok is False
    assert reason == f"cc-claim is not executable at {script.resolve()}"
