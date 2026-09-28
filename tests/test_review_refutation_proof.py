"""The proof producer observes test calls; summaries and error exits are not proof."""

import subprocess

import pytest

from scripts import review_refutation_proof as proof


def _repo(tmp_path, executable=False):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "shared").mkdir()
    (root / "tests").mkdir()
    (root / "shared/__init__.py").write_text("")
    (root / "shared/value.py").write_text("VALUE = 1\n")
    if executable:
        (root / "shared/value.py").chmod(0o755)
    (root / "tests/test_value.py").write_text(
        "from shared.value import VALUE\ndef test_value():\n    assert VALUE == 1\n"
    )

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root, text=True).strip()

    git("init", "-q")
    git("config", "user.name", "Fixture")
    git("config", "user.email", "fixture@example.invalid")
    git("add", ".")
    git("commit", "-qm", "fixture")
    head = git("rev-parse", "HEAD")
    (root / "shared/value.py").write_text("VALUE = 2\n")
    git("add", ".")
    git("commit", "-qm", "mutation")
    mutation = git("rev-parse", "HEAD")
    git("checkout", "-q", head)
    return root, head, mutation, git


@pytest.mark.parametrize("executable", [False, True])
def test_proof_observes_red_and_exact_restore(tmp_path, executable):
    root, head, mutation, git = _repo(tmp_path, executable)
    result = proof.produce_proof(root, head, mutation, ["tests/test_value.py::test_value"])
    assert result["head_sha"] == head
    assert [leg["returncode"] for leg in result["legs"]] == [0, 1, 0]
    assert [leg["calls"][0]["outcome"] for leg in result["legs"]] == ["passed", "failed", "passed"]
    assert result["files"][0]["before"] == result["files"][0]["restored"]
    assert result["files"][0]["before"] != result["files"][0]["mutated"]
    assert git("diff", "HEAD") == ""


@pytest.mark.parametrize("mutation_kind", ["tests", "same", "dirty", "symlink"])
def test_proof_refuses_unsafe_mutations(tmp_path, mutation_kind):
    root, head, mutation, git = _repo(tmp_path)
    if mutation_kind in ("tests", "symlink"):
        if mutation_kind == "tests":
            (root / "tests/test_value.py").write_text("def test_value(): pass\n")
        else:
            (root / "shared/value.py").unlink()
            (root / "shared/value.py").symlink_to("../tests/test_value.py")
        git("add", ".")
        git("commit", "-qm", "unsafe mutation")
        mutation = git("rev-parse", "HEAD")
        git("checkout", "-q", head)
    elif mutation_kind == "same":
        mutation = head
    else:
        (root / "shared/value.py").write_text("VALUE = 3\n")
    with pytest.raises(ValueError):
        proof.produce_proof(root, head, mutation, ["tests/test_value.py::test_value"])


@pytest.mark.parametrize("outcome", ["skipped", "error", "missing", "duplicate"])
def test_proof_requires_one_call_outcome_per_named_test(outcome):
    calls = (
        [] if outcome == "missing" else [{"nodeid": "tests/test_x.py::test_x", "outcome": outcome}]
    )
    if outcome == "duplicate":
        calls = [{"nodeid": "tests/test_x.py::test_x", "outcome": "passed"}] * 2
    assert not proof.calls_match(calls, ["tests/test_x.py::test_x"], "passed")


def test_proof_restores_even_when_red_leg_crashes(tmp_path, monkeypatch):
    root, head, mutation, git = _repo(tmp_path)
    real = proof.run_tests

    def crash_on_mutation(root, tests):
        if (root / "shared/value.py").read_text() == "VALUE = 2\n":
            raise OSError("synthetic runner loss")
        return real(root, tests)

    monkeypatch.setattr(proof, "run_tests", crash_on_mutation)
    with pytest.raises(OSError):
        proof.produce_proof(root, head, mutation, ["tests/test_value.py::test_value"])
    assert git("diff", "HEAD") == ""


@pytest.mark.parametrize(
    "kind", ["baseline_fail", "red_pass", "red_error", "red_skip", "restore_fail", "wrong_head"]
)
def test_incomplete_observation_never_produces_receipt(tmp_path, kind):
    root, head, mutation, git = _repo(tmp_path)
    if kind == "wrong_head":
        head = "0" * 40
    elif kind in ("red_pass", "red_error"):
        (root / "shared/value.py").write_text(
            "VALUE = 1 + 0\n" if kind == "red_pass" else "VALUE = (\n"
        )
        git("add", ".")
        git("commit", "-qm", "ineffective or untestable mutation")
        mutation = git("rev-parse", "HEAD")
        git("checkout", "-q", head)
    else:
        source = "from shared.value import VALUE\n"
        if kind == "baseline_fail":
            source += "def test_value():\n    assert VALUE == 99\n"
        elif kind == "red_skip":
            source += 'import pytest\ndef test_value():\n    if VALUE == 2: pytest.skip("synthetic")\n    assert VALUE == 1\n'
        else:
            source += 'from pathlib import Path\ndef test_value():\n    p = Path("counter")\n    n = int(p.read_text()) + 1 if p.exists() else 1\n    p.write_text(str(n))\n    assert VALUE == 1 and n != 3\n'
        (root / "tests/test_value.py").write_text(source)
        git("add", ".")
        git("commit", "-qm", "fixture observation")
        head = git("rev-parse", "HEAD")
        (root / "shared/value.py").write_text("VALUE = 2\n")
        git("add", ".")
        git("commit", "-qm", "fixture mutation")
        mutation = git("rev-parse", "HEAD")
        git("checkout", "-q", head)
    with pytest.raises(ValueError):
        proof.produce_proof(root, head, mutation, ["tests/test_value.py::test_value"])
    assert git("diff", "HEAD") == ""


@pytest.mark.parametrize("actions,workspace", [("false", "correct"), ("true", "different")])
def test_cli_refuses_non_disposable_context(tmp_path, monkeypatch, actions, workspace):
    import sys

    root, head, mutation, git = _repo(tmp_path)
    monkeypatch.chdir(root)
    monkeypatch.setenv("GITHUB_ACTIONS", actions)
    monkeypatch.setenv("GITHUB_WORKSPACE", str(root if workspace == "correct" else tmp_path))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "proof",
            "--head",
            head,
            "--mutation",
            mutation,
            "--tests-json",
            '["tests/test_value.py::test_value"]',
            "--output",
            str(tmp_path / "proof.json"),
        ],
    )
    with pytest.raises(SystemExit):
        proof.main()
    assert not (tmp_path / "proof.json").exists()
