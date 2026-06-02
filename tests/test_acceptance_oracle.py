"""Tests for ``scripts/hapax-acceptance-oracle`` — the kind=build acceptance oracle.

Like ``scripts/hapax-reform-complete``, the script splits impure host probing
(``gather``: parse note, resolve a clean SHA, run tests in an ephemeral worktree,
diff test files) from the pure decision logic (``decide``). These tests exercise
the pure logic, the verdict/exit-code contract, the findings-record shape, and the
``--observations`` CLI path (which skips ALL live probing) — so they are
deterministic and run anywhere CI runs: no git worktree, no subprocess test run.
"""

import importlib.util
import json
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "hapax-acceptance-oracle"


def _load_module():
    loader = SourceFileLoader("hapax_acceptance_oracle", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec
    mod = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = mod
    loader.exec_module(mod)
    return mod


mod = _load_module()


def _obs(**overrides):
    """A baseline in-scope observation that would PASS, with field overrides."""
    base = {
        "task_id": "demo-build-20260602",
        "kind": "build",
        "mutation_surface": "source",
        "deterministic_tests": ["uv run pytest tests/test_demo.py -q"],
        "checkbox_complete": True,
        "oracle_off": False,
        "load_ok": True,
        "clean_tree_sha": "abc1234",
        "authorizes_test_changes": False,
        "tampered_test_paths": [],
        "test_failures": [],
        "n_tests_run": 1,
    }
    base.update(overrides)
    return mod.Observation.from_dict(base)


# --- exit-code contract -----------------------------------------------------


def test_exit_codes_are_pass0_fail2_indeterminate3():
    assert mod.EXIT[mod.PASS] == 0
    assert mod.EXIT[mod.FAIL] == 2
    assert mod.EXIT[mod.INDETERMINATE] == 3
    assert mod.Verdict(mod.PASS).exit_code == 0
    assert mod.Verdict(mod.FAIL, ("x",)).exit_code == 2
    assert mod.Verdict(mod.INDETERMINATE, ("x",)).exit_code == 3


# --- pure decide(): the happy path and every INDETERMINATE / FAIL branch ----


def test_all_pass_yields_PASS():
    assert mod.decide(_obs()).verdict == mod.PASS


def test_bypass_env_is_indeterminate_never_blocks():
    v = mod.decide(_obs(oracle_off=True))
    assert v.verdict == mod.INDETERMINATE
    assert any("bypass" in r for r in v.reasons)


def test_out_of_scope_kind_is_indeterminate_not_fail():
    v = mod.decide(_obs(kind="research_packet"))
    assert v.verdict == mod.INDETERMINATE
    assert any("out-of-scope-class" in r for r in v.reasons)


def test_out_of_scope_surface_is_indeterminate_not_fail():
    v = mod.decide(_obs(mutation_surface="vault_docs"))
    assert v.verdict == mod.INDETERMINATE
    assert any("out-of-scope-class" in r for r in v.reasons)


def test_high_load_defers_indeterminate():
    v = mod.decide(_obs(load_ok=False))
    assert v.verdict == mod.INDETERMINATE
    assert any("deferred-high-load" in r for r in v.reasons)


def test_no_clean_tree_is_indeterminate_post_commit_only():
    v = mod.decide(_obs(clean_tree_sha=None))
    assert v.verdict == mod.INDETERMINATE
    assert any("no-clean-tree" in r for r in v.reasons)


def test_no_declared_tests_is_indeterminate_coverage_gap():
    v = mod.decide(_obs(deterministic_tests=[]))
    assert v.verdict == mod.INDETERMINATE
    assert any("no-declared-tests" in r for r in v.reasons)


def test_test_failure_yields_FAIL_with_reason():
    v = mod.decide(_obs(test_failures=["uv run pytest tests/test_demo.py -q"]))
    assert v.verdict == mod.FAIL
    assert any("test-failed" in r for r in v.reasons)


def test_test_file_tamper_unauthorized_is_FAIL_even_when_tests_pass():
    # EvilGenie: the lane edits the very tests it must satisfy, then they "pass".
    v = mod.decide(_obs(tampered_test_paths=["tests/test_demo.py"], test_failures=[]))
    assert v.verdict == mod.FAIL
    assert any("test-file-tamper" in r for r in v.reasons)


def test_test_file_tamper_authorized_does_not_fail_for_tamper():
    # A task whose explicit job is to fix/add tests sets authorizes_test_changes.
    v = mod.decide(_obs(tampered_test_paths=["tests/test_demo.py"], authorizes_test_changes=True))
    assert v.verdict == mod.PASS


def test_authorized_tamper_still_fails_on_real_test_failure():
    v = mod.decide(
        _obs(
            tampered_test_paths=["tests/test_demo.py"],
            authorizes_test_changes=True,
            test_failures=["uv run pytest tests/test_demo.py -q"],
        )
    )
    assert v.verdict == mod.FAIL
    assert any("test-failed" in r for r in v.reasons)


def test_indeterminate_precedes_fail_when_both_apply():
    # An out-of-scope task with a (hypothetical) test failure must NOT block: scope
    # short-circuits to INDETERMINATE before any FAIL is considered.
    v = mod.decide(_obs(kind="research_packet", test_failures=["x"]))
    assert v.verdict == mod.INDETERMINATE


# --- divergence labelling (the headline experiment metric) ------------------


def test_divergence_oracle_fail_checkbox_pass_is_a_false_closure():
    assert mod.divergence(mod.FAIL, True) == "oracle-fail-checkbox-pass"


def test_divergence_pass_checkbox_incomplete():
    assert mod.divergence(mod.PASS, False) == "oracle-pass-checkbox-incomplete"


def test_divergence_aligned():
    assert mod.divergence(mod.PASS, True) == "aligned"
    assert mod.divergence(mod.INDETERMINATE, True) == "aligned"


# --- test-path extraction (anti-tamper diff target) -------------------------


def test_extract_test_paths_pulls_tests_args_from_commands():
    cmds = [
        "uv run pytest tests/test_a.py tests/shared/test_b.py -q",
        "uv run pytest tests/scripts/test_c.py::test_x -q",
    ]
    paths = mod.extract_test_paths(cmds)
    assert "tests/test_a.py" in paths
    assert "tests/shared/test_b.py" in paths
    # the ::node-id suffix is stripped to the file path
    assert any(p.startswith("tests/scripts/test_c.py") for p in paths)


def test_extract_test_paths_empty_for_no_test_tokens():
    assert mod.extract_test_paths(["uv run ruff check shared/foo.py"]) == []


# --- findings record shape (ISO ts, never a float; divergence present) ------


def test_finding_record_has_iso_ts_and_divergence():
    obs = _obs(test_failures=["uv run pytest tests/test_demo.py -q"])
    v = mod.decide(obs)
    rec = mod.finding_record(obs, v, ts="2026-06-02T07:00:00Z")
    assert rec["ts"] == "2026-06-02T07:00:00Z"
    assert isinstance(rec["ts"], str)  # ISO string, NOT a time.time() float
    assert rec["task_id"] == "demo-build-20260602"
    assert rec["verdict"] == mod.FAIL
    assert rec["divergence"] == "oracle-fail-checkbox-pass"
    assert rec["checkbox_complete"] is True
    assert rec["clean_tree_sha"] == "abc1234"


def test_now_iso_is_z_suffixed_string():
    s = mod.now_iso()
    assert isinstance(s, str) and s.endswith("Z") and "T" in s


# --- CLI exit-code contract via --observations (no live probing) ------------


def _run_cli(args, obs_dict=None, tmp_path=None):
    cli = [sys.executable, str(SCRIPT), *args, "--no-ledger", "--json"]
    if obs_dict is not None:
        f = tmp_path / "obs.json"
        f.write_text(json.dumps(obs_dict))
        cli = [sys.executable, str(SCRIPT), "--observations", str(f), "--no-ledger", "--json"]
    return subprocess.run(cli, capture_output=True, text=True)


def test_cli_observations_pass_exits_0(tmp_path):
    d = {
        "task_id": "t",
        "kind": "build",
        "mutation_surface": "source",
        "deterministic_tests": ["uv run pytest tests/x.py -q"],
        "checkbox_complete": True,
        "clean_tree_sha": "deadbee",
        "n_tests_run": 1,
    }
    r = _run_cli([], obs_dict=d, tmp_path=tmp_path)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["verdict"] == "PASS"


def test_cli_observations_fail_exits_2(tmp_path):
    d = {
        "task_id": "t",
        "kind": "build",
        "mutation_surface": "source",
        "deterministic_tests": ["uv run pytest tests/x.py -q"],
        "checkbox_complete": True,
        "clean_tree_sha": "deadbee",
        "test_failures": ["uv run pytest tests/x.py -q"],
        "n_tests_run": 1,
    }
    r = _run_cli([], obs_dict=d, tmp_path=tmp_path)
    assert r.returncode == 2, r.stderr
    assert json.loads(r.stdout)["verdict"] == "FAIL"


def test_cli_observations_indeterminate_exits_3(tmp_path):
    d = {
        "task_id": "t",
        "kind": "vault_docs",  # out of scope
        "mutation_surface": "vault_docs",
        "checkbox_complete": True,
    }
    r = _run_cli([], obs_dict=d, tmp_path=tmp_path)
    assert r.returncode == 3, r.stderr
    assert json.loads(r.stdout)["verdict"] == "INDETERMINATE"
