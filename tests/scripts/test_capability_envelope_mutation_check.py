"""The envelope's mutation list stays applicable: every mutation matches its target exactly once.

The full mutation run (every mutation turns tests/capability_envelope red) executes in the CI job
capability-envelope-containment, where bubblewrap is available. This drift guard runs everywhere,
so an edit to the envelope that silently stops a mutation from applying is caught at once.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "capability-envelope-mutation-check"


def _check():
    loader = importlib.machinery.SourceFileLoader("capability_envelope_mutation_check", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


MUTATIONS = _check().MUTATIONS


@pytest.mark.parametrize("mutation", MUTATIONS, ids=[m.id for m in MUTATIONS])
def test_each_mutation_applies_exactly_once(mutation):
    text = (_check().REPO_ROOT / mutation.target).read_text(encoding="utf-8")
    assert text.count(mutation.old) == 1, f"{mutation.id} ({mutation.invariant}) no longer applies"
    assert mutation.new != mutation.old


def test_mutation_ids_are_unique_and_cover_both_modules():
    ids = [m.id for m in MUTATIONS]
    assert len(ids) == len(set(ids))
    assert {m.target for m in MUTATIONS} == {
        "shared/capability_envelope/render.py",
        "shared/capability_envelope/declaration.py",
    }


def test_the_staged_copy_holds_the_package_and_its_tests(tmp_path: Path):
    check = _check()
    tree = check.stage(check.REPO_ROOT, tmp_path / "tree")
    assert (tree / "shared/capability_envelope/render.py").is_file()
    assert (tree / "tests/capability_envelope/test_envelope.py").is_file()
    assert not any(p.name == "__pycache__" for p in tree.rglob("*"))
