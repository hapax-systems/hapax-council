"""Re-reviews must stop destroying their predecessors.

`review_dossier_path` returns one file per task, so every re-review overwrote the last one.
Measured 2026-08-10 across 426 dossiers / 420 distinct task ids: **417 tasks retained exactly one
head_sha, ZERO retained two.** The corpus therefore held no consecutive pair anywhere — no
instance of "round N blocked on X; round N+1, after fix Y, accepted".

That absence is why review-team quality is unmeasurable. Under a 1-of-M veto (block_on_named_
critical decides 431 of 432 dossiers) soundness is governed by per-family VETO PRECISION, and
precision needs a label. A consecutive pair is the cheapest label available, and the estate was
deleting every one at the instant it was created.

The fix is additive: the canonical path keeps being written so no reader changes, and a
head-keyed copy accumulates alongside it.

Self-contained per the repo testing convention (no shared conftest fixtures).
"""

from __future__ import annotations

import importlib.util
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "review_team.py"


def _load() -> ModuleType:
    name = "review_team_history_test_module"
    sys.modules.pop(name, None)
    loader = SourceFileLoader(name, str(SCRIPT))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


HEAD_A = "a04b2b741f0e9c3d5b6a7c8e9f0a1b2c3d4e5f60"
HEAD_B = "87a7d9ca2e1f3b4c5d6e7f8091a2b3c4d5e6f708"


def test_canonical_path_is_unchanged(tmp_path: Path) -> None:
    """Every existing reader resolves here; changing it would break the gate."""
    module = _load()
    note = tmp_path / "some-task.md"
    got = module.review_dossier_path(note, "some-task")
    assert got.name == f"some-task{module.REVIEW_DOSSIER_SUFFIX}"
    assert got.parent == tmp_path


def test_two_heads_produce_two_distinct_history_files(tmp_path: Path) -> None:
    """The whole point: a second review of the same task no longer overwrites the first."""
    module = _load()
    note = tmp_path / "some-task.md"
    a = module.review_dossier_history_path(note, "some-task", HEAD_A)
    b = module.review_dossier_history_path(note, "some-task", HEAD_B)
    assert a != b
    assert a != module.review_dossier_path(note, "some-task")
    assert HEAD_A[:12] in a.name
    assert HEAD_B[:12] in b.name


def test_same_head_is_idempotent(tmp_path: Path) -> None:
    """Re-running a review on an unchanged head must not accumulate duplicates."""
    module = _load()
    note = tmp_path / "some-task.md"
    first = module.review_dossier_history_path(note, "some-task", HEAD_A)
    second = module.review_dossier_history_path(note, "some-task", HEAD_A)
    assert first == second


def test_unkeyable_head_falls_back_to_canonical(tmp_path: Path) -> None:
    """A history entry keyed to a guess is worse than no history entry.

    Falling back to the canonical path means the caller's `!=` check suppresses the extra write
    rather than inventing a filename from junk.
    """
    module = _load()
    note = tmp_path / "some-task.md"
    canonical = module.review_dossier_path(note, "some-task")
    for bad in ("", None, "abc", "zzzz", "no-hex-here"):
        assert module.review_dossier_history_path(note, "some-task", bad) == canonical


def test_head_key_is_normalised(tmp_path: Path) -> None:
    """Upper/lower case and a short-but-valid head must not create sibling duplicates."""
    module = _load()
    note = tmp_path / "some-task.md"
    lower = module.review_dossier_history_path(note, "some-task", HEAD_A)
    upper = module.review_dossier_history_path(note, "some-task", HEAD_A.upper())
    assert lower == upper


def test_history_and_canonical_are_siblings(tmp_path: Path) -> None:
    """Both must land beside the note so the vault stays one directory per task family."""
    module = _load()
    note = tmp_path / "nested" / "some-task.md"
    note.parent.mkdir(parents=True)
    canonical = module.review_dossier_path(note, "some-task")
    history = module.review_dossier_history_path(note, "some-task", HEAD_A)
    assert canonical.parent == history.parent == note.parent
