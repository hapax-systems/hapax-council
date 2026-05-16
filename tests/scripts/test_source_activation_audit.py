"""Tests for the source activation consumer audit script."""

from __future__ import annotations

from pathlib import Path

from scripts.hapax_source_activation_audit import (
    ConsumerEntry,
    _classify_unit_usage,
    scan_hooks,
    scan_systemd_units,
)


CANONICAL = "/home/hapax/projects/hapax-council"


def test_classify_workdir():
    content = f"[Service]\nWorkingDirectory={CANONICAL}\nExecStart=/usr/bin/true\n"
    assert _classify_unit_usage(content) == "workdir"


def test_classify_execstart():
    content = f"[Service]\nExecStart=uv run --directory {CANONICAL} python -m foo\n"
    assert _classify_unit_usage(content) == "execstart"


def test_classify_doc_only():
    content = f"[Unit]\nDocumentation=file:///{CANONICAL}/docs/foo.md\n[Service]\nExecStart=/usr/bin/true\n"
    assert _classify_unit_usage(content) == "doc-only"


def test_classify_workdir_plus_exec():
    content = (
        f"[Service]\nWorkingDirectory={CANONICAL}\nExecStart=uv run --directory {CANONICAL} foo\n"
    )
    assert _classify_unit_usage(content) == "workdir+exec"


def test_scan_hooks_allowlists_canonical_protect(tmp_path: Path):
    hook = tmp_path / "canonical-worktree-protect.sh"
    hook.write_text(f"#!/bin/bash\n# {CANONICAL}\n")
    entries = scan_hooks(tmp_path)
    assert len(entries) == 1
    assert entries[0].classification == "intentional-canonical"


def test_scan_hooks_flags_non_allowlisted(tmp_path: Path):
    hook = tmp_path / "some-hook.sh"
    hook.write_text(f"#!/bin/bash\ncd {CANONICAL}\n")
    entries = scan_hooks(tmp_path)
    assert len(entries) == 1
    assert entries[0].classification == "needs-migration"
