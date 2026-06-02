"""The acceptance-oracle shadow hook in ``scripts/cc-task-closure-check.py`` must be
OFF by default and must never alter the closure gate's behavior.

These tests pin: (1) ``gate()`` exit codes are unchanged, (2) ``shadow_observe`` is a
no-op unless ``HAPAX_ACCEPTANCE_ORACLE_SHADOW=1``, and (3) when enabled it spawns the
oracle detached against the note — advisory-only.
"""

import importlib.util
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "cc-task-closure-check.py"


def _load():
    loader = SourceFileLoader("cc_task_closure_check", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = mod
    loader.exec_module(mod)
    return mod


mod = _load()


def test_gate_exit_codes_unchanged(tmp_path):
    checked = tmp_path / "c.md"
    checked.write_text("---\ntype: cc-task\n---\n## Acceptance criteria\n- [x] done\n")
    unchecked = tmp_path / "u.md"
    unchecked.write_text("---\ntype: cc-task\n---\n## Acceptance criteria\n- [ ] not done\n")
    assert mod.gate(checked)[0] == 0
    assert mod.gate(unchecked)[0] == 2


def test_shadow_observe_noop_when_env_unset(monkeypatch):
    monkeypatch.delenv("HAPAX_ACCEPTANCE_ORACLE_SHADOW", raising=False)
    calls = []
    monkeypatch.setattr(mod.subprocess, "Popen", lambda *a, **k: calls.append((a, k)))
    mod.shadow_observe(Path("/nonexistent/note.md"))
    assert calls == []


def test_shadow_observe_spawns_detached_when_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("HAPAX_ACCEPTANCE_ORACLE_SHADOW", "1")
    calls = []
    monkeypatch.setattr(mod.subprocess, "Popen", lambda *a, **k: calls.append((a, k)))
    note = tmp_path / "note.md"
    note.write_text("---\ntype: cc-task\n---\n")
    mod.shadow_observe(note)
    assert len(calls) == 1
    argv, kwargs = calls[0][0][0], calls[0][1]
    assert any("hapax-acceptance-oracle" in str(token) for token in argv)
    assert "--note" in argv and str(note) in argv
    assert kwargs.get("start_new_session") is True  # detached


def test_main_permitted_closure_does_not_spawn_when_disabled(monkeypatch, tmp_path):
    monkeypatch.delenv("HAPAX_ACCEPTANCE_ORACLE_SHADOW", raising=False)
    calls = []
    monkeypatch.setattr(mod.subprocess, "Popen", lambda *a, **k: calls.append((a, k)))
    note = tmp_path / "ok.md"
    note.write_text("---\ntype: cc-task\n---\n## Acceptance criteria\n- [x] done\n")
    assert mod.main(["cc-task-closure-check.py", str(note)]) == 0
    assert calls == []
