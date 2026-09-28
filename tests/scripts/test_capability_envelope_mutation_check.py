"""The envelope's mutation list stays applicable: every mutation matches its target exactly once.

The full mutation run (every mutation turns tests/capability_envelope red) executes in the CI job
capability-envelope-containment, where bubblewrap is available. This drift guard runs everywhere,
so an edit to the envelope that silently stops a mutation from applying is caught at once.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
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


@pytest.fixture
def fixture_repo(tmp_path: Path) -> Path:
    """A minimal repo with the same staged layout, so check() and main() run for real."""
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "__init__.py").write_text("", encoding="utf-8")
    package = shared / "capability_envelope"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "mod.py").write_text("MASK = True\n", encoding="utf-8")
    tests_root = tmp_path / "tests"
    tests_root.mkdir()
    (tests_root / "__init__.py").write_text("", encoding="utf-8")
    tests = tests_root / "capability_envelope"
    tests.mkdir()
    (tests / "test_mod.py").write_text(
        "from shared.capability_envelope.mod import MASK\n\n\ndef test_mask():\n    assert MASK\n",
        encoding="utf-8",
    )
    return tmp_path


def _mutation(module, **overrides):
    """A mutation the fixture repo's own test can kill."""
    fields = {
        "id": "FX",
        "target": "shared/capability_envelope/mod.py",
        "invariant": "the fixture invariant",
        "old": "MASK = True",
        "new": "MASK = False",
    }
    fields.update(overrides)
    return module.Mutation(**fields)


def test_check_kills_a_mutation_and_keeps_the_baseline_green(fixture_repo: Path):
    """gemini-1's minor (2026-09-28): the drift guard only imported the script, so check() and
    main() were never run. check() runs the fixture's suite for real: the baseline is green, the
    mutation turns it red, and the report says killed."""
    check = _check()
    report = check.check((_mutation(check),), fixture_repo)
    assert report["baseline"]["returncode"] == 0
    assert [r["outcome"] for r in report["mutations"]] == ["killed"]
    assert report["ok"] is True


def test_check_fails_when_a_mutation_survives_or_never_applied(fixture_repo: Path):
    check = _check()
    surviving = _mutation(check, id="SURV", new="MASK = True ")
    report = check.check((surviving,), fixture_repo)
    assert report["mutations"][0]["outcome"] == "survived"
    assert report["ok"] is False
    absent = _mutation(check, id="ABSENT", old="NOT THERE", new="STILL NOT")
    second = check.check((absent,), fixture_repo)
    assert second["mutations"][0]["outcome"].startswith("not-applied")
    assert second["ok"] is False


def test_main_writes_the_report_and_returns_the_verdict(
    fixture_repo: Path, tmp_path: Path, monkeypatch, capsys
):
    check = _check()
    monkeypatch.setattr(check, "MUTATIONS", (_mutation(check),))
    monkeypatch.setattr(check, "REPO_ROOT", fixture_repo)
    out = tmp_path / "report.json"
    assert check.main(["--only", "FX", "--out", str(out)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert "ALL KILLED" in capsys.readouterr().out

    surviving = _mutation(check, id="SURV", new="MASK = True ")
    monkeypatch.setattr(check, "MUTATIONS", (surviving,))
    assert check.main(["--only", "SURV"]) == 1
    assert "FAILED" in capsys.readouterr().out


def test_main_refuses_an_unknown_mutation_id(fixture_repo: Path, monkeypatch, capsys):
    """codex-1's minor (2026-09-28): an unknown id used to select nothing, and every() of nothing
    is true — ALL KILLED with exit 0 having run no mutation at all."""
    check = _check()
    monkeypatch.setattr(check, "MUTATIONS", (_mutation(check),))
    monkeypatch.setattr(check, "REPO_ROOT", fixture_repo)
    assert check.main(["--only", "NOT-A-MUTATION"]) == 2
    assert "unknown mutation id" in capsys.readouterr().err


def test_the_staged_tree_carries_no_conftest_of_its_own():
    """glm-1's minor (2026-09-28): `stage()` copies only the envelope package and its tests, so a
    root conftest cannot travel with them. Measured: staging the repository's `conftest.py` and
    `tests/conftest.py` fails COLLECTION in the minimal copy — they import and patch parts of the
    repository that are not there — while the envelope suite passes without them. The staged suite
    is therefore self-contained by construction, and this pins that it stays so."""
    check = _check()
    assert not any(Path(entry).name == "conftest.py" for entry in check.STAGED)
    assert not (SCRIPT.parents[1] / "tests" / "capability_envelope" / "conftest.py").exists()


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
