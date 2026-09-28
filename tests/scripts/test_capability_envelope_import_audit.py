"""The real-harness import audit's world and verdict (the harness runs themselves need
credentials and are rerun by an operator or lane; see docs/runbooks/capability-envelope.md)."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "capability-envelope-import-audit"


def _audit():
    loader = importlib.machinery.SourceFileLoader("capability_envelope_import_audit", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


def test_the_world_seeds_a_unique_sentinel_at_every_common_import_path(tmp_path: Path):
    audit = _audit()
    world = audit.build_world(tmp_path / "world", tmp_path / "home")
    tokens = list(world.tokens.values())
    assert len(tokens) == len(set(tokens)) == 8
    for rel in ("ancestor/AGENTS.md", "ancestor/repo/CLAUDE.md", "mirror-home/AGENTS.md"):
        path = world.root / rel
        assert world.tokens[path] in path.read_text()


def test_the_world_is_create_once(tmp_path: Path):
    audit = _audit()
    audit.build_world(tmp_path / "world", tmp_path / "home")
    with pytest.raises(FileExistsError):
        audit.build_world(tmp_path / "world", tmp_path / "home")


def _obs(**overrides):
    base = {"returncode": 0, "tokens_in_reply": [], "sentinels_opened": [], "markers": []}
    return {**base, **overrides}


@pytest.mark.parametrize(
    ("enveloped", "expected"),
    [
        (_obs(sentinels_opened=["mirror-home/AGENTS.md"]), ("leak", 1)),
        (_obs(tokens_in_reply=["ancestor/AGENTS.md"]), ("leak", 1)),
        (_obs(markers=["undeclared-user-hook-ran"]), ("leak", 1)),
        (_obs(returncode=1, sentinels_opened=["x"]), ("leak", 1)),
        (_obs(returncode=1), ("inconclusive", 2)),
        (_obs(markers=["declared-hook-fired"]), ("clean", 0)),
    ],
    ids=["opened", "token", "undeclared-marker", "leak-outranks-failure", "failed", "clean"],
)
def test_the_verdict(enveloped: dict, expected: tuple[str, int]):
    baseline = _obs(sentinels_opened=["mirror-home/AGENTS.md"])
    assert _audit().verdict(baseline, enveloped, ("undeclared-user-hook-ran",)) == expected


def test_a_clean_run_without_a_witnessed_baseline_import_says_so():
    """Review of #4784 (codex-1): the control is what makes a clean run evidence. With no
    witnessed baseline import the same observation is what a dead probe produces, so the audit
    reports it and exits non-zero — never 0."""
    audit = _audit()
    assert audit.verdict(_obs(), _obs(), ()) == ("clean-no-control", 2)


def test_main_exits_nonzero_when_the_baseline_control_witnessed_nothing(tmp_path, monkeypatch):
    """The exit code, not only the label: a clean-no-control audit must not leave a caller with a
    passing status. Runs main() end to end with the harness launch stubbed out."""
    import json

    audit = _audit()

    class _World:
        def __init__(self, root: Path):
            self.root = root
            self.home = root / "home"
            self.spool = root / "spool"
            self.home.mkdir(parents=True, exist_ok=True)
            self.spool.mkdir(parents=True, exist_ok=True)
            self.markers = ("declared-hook-fired",)

    monkeypatch.setattr(audit, "build_world", lambda root, home: _World(root))
    monkeypatch.setitem(audit.LAUNCHES, "claude", lambda world: None)
    # The baseline control witnessed nothing; the enveloped run imported nothing.
    monkeypatch.setattr(audit, "run_baseline", lambda world, launch: _obs())
    monkeypatch.setattr(audit, "run_enveloped", lambda world, launch: _obs())
    out = tmp_path / "report.json"
    code = audit.main(["--harness", "claude", "--out", str(out), "--root", str(tmp_path / "w")])
    assert code == 2
    assert json.loads(out.read_text(encoding="utf-8"))["verdict"] == "clean-no-control"
