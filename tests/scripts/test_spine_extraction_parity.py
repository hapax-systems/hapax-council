"""The spine-extraction parity checker, and the three ways it must not fail quietly.

Measured 2026-08-10 across the 15 modules present in both trees: 108 public symbols exist in
council and not in spine, and **zero** exist in spine and not in council. That zero is why the
relationship is an extraction rather than a fork -- a fork drifts both ways.

So the invariant is not equality. `coord_projection` is 8,888 lines in council against 527 in
spine, and demanding byte parity would demand the extraction not be an extraction. What must hold
is that spine stays a strict subset, and that the gap stays *declared*.

Self-contained per the repo testing convention (no shared conftest fixtures).
"""

from __future__ import annotations

import importlib.util
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check-spine-extraction-parity.py"


def _load() -> ModuleType:
    name = "spine_extraction_parity_test_module"
    sys.modules.pop(name, None)
    loader = SourceFileLoader(name, str(SCRIPT))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


def _tree(root: Path, name: str, body: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(body, encoding="utf-8")
    return root


def test_strict_subset_passes(tmp_path: Path) -> None:
    """Spine may lag; that is what an extraction is."""
    module = _load()
    council = _tree(tmp_path / "c", "m.py", "def a():\n    pass\ndef b():\n    pass\n")
    spine = _tree(tmp_path / "s", "m.py", "def a():\n    pass\n")
    module.NOT_EXTRACTED = {"m.py": ("b",)}
    code, lines = module.check(council, spine)
    assert code == module.OK, lines


def test_spine_only_symbol_is_a_finding(tmp_path: Path) -> None:
    """A name spine exports that council lacks is dead code or a leaked private name."""
    module = _load()
    council = _tree(tmp_path / "c", "m.py", "def a():\n    pass\n")
    spine = _tree(tmp_path / "s", "m.py", "def a():\n    pass\ndef leaked():\n    pass\n")
    module.NOT_EXTRACTED = {}
    code, lines = module.check(council, spine)
    assert code == module.FINDING
    assert any("SPINE-ONLY" in line for line in lines)
    assert any("leaked" in line for line in lines)


def test_undeclared_council_symbol_is_a_finding(tmp_path: Path) -> None:
    """The whole point: distinguish 'kept private on purpose' from 'forgotten'.

    A symbol added to council and silently not extracted is invisible without this.
    """
    module = _load()
    council = _tree(tmp_path / "c", "m.py", "def a():\n    pass\ndef forgotten():\n    pass\n")
    spine = _tree(tmp_path / "s", "m.py", "def a():\n    pass\n")
    module.NOT_EXTRACTED = {}  # `forgotten` is not declared
    code, lines = module.check(council, spine)
    assert code == module.FINDING
    assert any("UNDECLARED GAP" in line for line in lines)
    assert any("forgotten" in line for line in lines)
    assert any("Silence is the third option" in line for line in lines)


def test_declaring_the_gap_clears_it(tmp_path: Path) -> None:
    module = _load()
    council = _tree(tmp_path / "c", "m.py", "def a():\n    pass\ndef kept():\n    pass\n")
    spine = _tree(tmp_path / "s", "m.py", "def a():\n    pass\n")
    module.NOT_EXTRACTED = {"m.py": ("kept",)}
    assert module.check(council, spine)[0] == module.OK


def test_missing_spine_tree_is_indeterminate_not_a_pass(tmp_path: Path) -> None:
    """An unevaluated check reporting success is the failure mode this estate keeps finding.

    Exit 2, never 0, and the message says nothing was checked.
    """
    module = _load()
    council = _tree(tmp_path / "c", "m.py", "def a():\n    pass\n")
    rc = module.main(["--council", str(council), "--spine", str(tmp_path / "nope")])
    assert rc == module.INDETERMINATE
    assert rc != module.OK


def test_no_overlapping_modules_is_indeterminate(tmp_path: Path) -> None:
    """Two trees that share no module names compared nothing; that is not agreement."""
    module = _load()
    council = _tree(tmp_path / "c", "one.py", "def a():\n    pass\n")
    spine = _tree(tmp_path / "s", "two.py", "def b():\n    pass\n")
    code, lines = module.check(council, spine)
    assert code == module.INDETERMINATE
    assert any("nothing was compared" in line for line in lines)


def test_bodies_may_differ_without_a_finding(tmp_path: Path) -> None:
    """Explicitly permitted: coord_projection is 8,888 lines vs 527 and that is correct."""
    module = _load()
    council = _tree(tmp_path / "c", "m.py", "def a():\n    x = 1\n    y = 2\n    return x + y\n")
    spine = _tree(tmp_path / "s", "m.py", "def a():\n    return 3\n")
    module.NOT_EXTRACTED = {}
    assert module.check(council, spine)[0] == module.OK


def test_live_trees_hold_the_invariant() -> None:
    """The pinned baseline must match reality, or the declaration has rotted.

    Skips when hapax-spine is absent -- but `main` returns INDETERMINATE in that case, which is
    covered above, so absence cannot be mistaken for agreement.
    """
    module = _load()
    if not module.DEFAULT_SPINE.is_dir():
        import pytest

        pytest.skip("hapax-spine not present on this host")
    code, lines = module.check(module.DEFAULT_COUNCIL, module.DEFAULT_SPINE)
    assert code == module.OK, "\n".join(lines)
