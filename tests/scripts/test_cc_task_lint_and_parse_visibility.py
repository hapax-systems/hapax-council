"""SDLC legibility triad (operator directive 2026-06-10): unparseable task
notes must be loudly visible, never silently dropped as 'unlinked'."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_lint_flags_ansi_frontmatter(tmp_path):
    lint_mod = _load("cc_task_lint", REPO / "scripts" / "cc-task-lint")
    note = tmp_path / "x.md"
    note.write_text('---\ntype: cc-task\ntask_id: x\nwitness: "\x1b[0;32mPASS\x1b[0m"\n---\nbody\n')
    problems, _ = lint_mod.lint(note, contract=True)
    assert any("ANSI" in p for p in problems)


def test_lint_passes_clean_note(tmp_path):
    lint_mod = _load("cc_task_lint", REPO / "scripts" / "cc-task-lint")
    note = tmp_path / "x.md"
    note.write_text(
        "---\ntype: cc-task\ntask_id: x\nstatus: offered\n"
        "authority_case: C-1\nparent_spec: spec.md\n---\nbody\n"
    )
    problems, warnings = lint_mod.lint(note, contract=True)
    assert problems == [] and warnings == []


def test_autoqueue_frontmatter_returns_reason(tmp_path):
    aq = _load("cc_pr_autoqueue", REPO / "scripts" / "cc-pr-autoqueue.py")
    bad = tmp_path / "bad.md"
    bad.write_text('---\ntask_id: y\nwitness: "\x1b[0;31mFAIL\x1b[0m"\n---\n')
    fm, err = aq._frontmatter(bad)
    assert fm is None and "ANSI" in err
    good = tmp_path / "good.md"
    good.write_text("---\ntask_id: y\n---\n")
    fm, err = aq._frontmatter(good)
    assert err is None and fm["task_id"] == "y"


def test_loader_records_parse_failures(tmp_path):
    aq = _load("cc_pr_autoqueue2", REPO / "scripts" / "cc-pr-autoqueue.py")
    (tmp_path / "active").mkdir()
    (tmp_path / "active" / "broken.md").write_text(
        '---\ntype: cc-task\ntask_id: z\nw: "\x1b[1m"\n---\n'
    )
    aq.TASK_NOTE_PARSE_FAILURES.clear()
    notes = aq.load_task_notes(tmp_path)
    assert notes == []
    assert aq.TASK_NOTE_PARSE_FAILURES and aq.TASK_NOTE_PARSE_FAILURES[0][0] == "broken.md"
