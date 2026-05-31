"""Tests for the reform ENGINE auto-advance dispatcher.

Covers the manifest-drain decision engine added to ``scripts/hapax-rte-state``
(reader → readiness → lane-idle → PR throttle → dispatch plan → execution) and
the ``cc-pr-merge-watcher.py`` nudge-next trigger that complements the RTE poll.

The two scripts are hyphenated / extensionless, so they are loaded by path via
``importlib`` (the same pattern as ``tests/test_archive_search.py``).

Everything is dependency-injected (lease dir, vault root, command runner) so no
test touches the real ``~/.cache/hapax`` lease dir, the real vault, ``gh``, or a
real lane launch.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(mod_name: str, rel_path: str):
    # Both scripts are hyphenated; hapax-rte-state is also extensionless, so an
    # explicit SourceFileLoader is required (importlib cannot infer a loader).
    loader = SourceFileLoader(mod_name, str(REPO_ROOT / rel_path))
    spec = importlib.util.spec_from_loader(mod_name, loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    loader.exec_module(mod)
    return mod


rte = _load("hapax_rte_state", "scripts/hapax-rte-state")
watcher = _load("cc_pr_merge_watcher", "scripts/cc-pr-merge-watcher.py")


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #

SAMPLE_MANIFEST = """\
meta:
  spec: /tmp/spec.md
auto_advance:
  pr_throttle: "<= 2x lane-count"
units:
  - id: UNIT-a
    lane: gamma
    hard_deps: []
    authority_case: CASE-X-001
    status: MERGED
    summary: already merged dep
  - id: UNIT-b
    lane: epsilon
    hard_deps: [UNIT-a]
    authority_case: CASE-X-002
    status: pending
    summary: ready because its only dep is merged
  - id: UNIT-c
    lane: delta
    hard_deps: [UNIT-b]
    authority_case: CASE-X-003
    status: pending
    summary: not ready because UNIT-b is still pending
  - id: UNIT-d
    lane: theta
    hard_deps: []
    authority_case: CASE-X-004
    status: MERGING
    summary: in the merge queue, not dispatchable
  - id: UNIT-e
    lane: beta
    hard_deps: [UNIT-missing]
    authority_case: CASE-X-005
    status: pending
    summary: dep id absent from manifest, treated as not merged
fixes:
  - id: FIX-thing
    lane: zeta
    hard_deps: []
    scope: [scripts/x]
    summary: an immediate fix with no explicit status field
"""


def _write_manifest(tmp_path: Path, text: str = SAMPLE_MANIFEST) -> Path:
    p = tmp_path / "reform-execution-manifest.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def _units(tmp_path: Path):
    return rte.load_reform_manifest(_write_manifest(tmp_path))


def _by_id(units):
    return {u.id: u for u in units}


class FakeRunner:
    """Captures argv lists and returns scripted CompletedProcess results."""

    def __init__(self, stdout: str = "", returncode: int = 0, raises: bool = False):
        self.calls: list[list[str]] = []
        self._stdout = stdout
        self._rc = returncode
        self._raises = raises

    def __call__(self, cmd, **kwargs):
        self.calls.append(list(cmd))
        if self._raises:
            raise OSError("boom")
        return subprocess.CompletedProcess(cmd, self._rc, self._stdout, "")


# --------------------------------------------------------------------------- #
# Manifest reader
# --------------------------------------------------------------------------- #


def test_load_manifest_reads_units_and_fixes(tmp_path):
    units = _units(tmp_path)
    ids = {u.id for u in units}
    assert ids == {"UNIT-a", "UNIT-b", "UNIT-c", "UNIT-d", "UNIT-e", "FIX-thing"}


def test_load_manifest_parses_fields(tmp_path):
    b = _by_id(_units(tmp_path))["UNIT-b"]
    assert b.lane == "epsilon"
    assert b.hard_deps == ("UNIT-a",)
    assert b.status == "pending"
    assert b.authority_case == "CASE-X-002"


def test_load_manifest_fix_without_status_is_empty(tmp_path):
    fix = _by_id(_units(tmp_path))["FIX-thing"]
    assert fix.status == ""
    assert fix.lane == "zeta"
    assert fix.hard_deps == ()


def test_load_manifest_missing_file_returns_empty(tmp_path):
    assert rte.load_reform_manifest(tmp_path / "nope.yaml") == []


def test_load_manifest_malformed_yaml_returns_empty(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("units: [this is : not valid", encoding="utf-8")
    assert rte.load_reform_manifest(bad) == []


def test_load_manifest_tolerates_malformed_sibling_section(tmp_path):
    # The real manifest's auto_advance block has unquoted colons in prose, so
    # whole-document YAML parsing raises. The units/fixes sections must still
    # load — this pins the resilience that makes the dispatcher work live.
    text = (
        "meta:\n"
        "  spec: /tmp/s.md\n"
        "auto_advance:\n"
        "  dispatcher: scripts/hapax-rte-state (270s) — each tick: dispatch ready units\n"
        "units:\n"
        "  - id: UNIT-z\n"
        "    lane: gamma\n"
        "    hard_deps: []\n"
        "    status: pending\n"
        "    summary: survives a malformed sibling section\n"
        "fixes:\n"
        "  - id: FIX-z\n"
        "    lane: zeta\n"
        "    hard_deps: []\n"
        "    summary: also survives\n"
    )
    p = tmp_path / "m.yaml"
    p.write_text(text, encoding="utf-8")
    ids = {u.id for u in rte.load_reform_manifest(p)}
    assert ids == {"UNIT-z", "FIX-z"}


# --------------------------------------------------------------------------- #
# Status predicates + readiness
# --------------------------------------------------------------------------- #


def test_merged_predicate(tmp_path):
    by = _by_id(_units(tmp_path))
    assert rte.unit_is_merged(by["UNIT-a"]) is True
    assert rte.unit_is_merged(by["UNIT-b"]) is False
    assert rte.unit_is_merged(by["UNIT-d"]) is False  # MERGING != MERGED


def test_dispatchable_predicate(tmp_path):
    by = _by_id(_units(tmp_path))
    assert rte.unit_is_dispatchable(by["UNIT-b"]) is True  # pending
    assert rte.unit_is_dispatchable(by["FIX-thing"]) is True  # blank status
    assert rte.unit_is_dispatchable(by["UNIT-a"]) is False  # merged
    assert rte.unit_is_dispatchable(by["UNIT-d"]) is False  # merging


def test_ready_units_only_when_deps_merged(tmp_path):
    ready = {u.id for u in rte.ready_units(_units(tmp_path))}
    # UNIT-b: dep UNIT-a merged -> ready. FIX-thing: no deps -> ready.
    # UNIT-c: dep UNIT-b pending -> not ready. UNIT-e: dep unknown -> not ready.
    # UNIT-a merged, UNIT-d merging -> not dispatchable.
    assert ready == {"UNIT-b", "FIX-thing"}


def test_ready_units_unknown_dep_blocks(tmp_path):
    ready_ids = {u.id for u in rte.ready_units(_units(tmp_path))}
    assert "UNIT-e" not in ready_ids


# --------------------------------------------------------------------------- #
# Lane-idle detection
# --------------------------------------------------------------------------- #


def test_lane_idle_when_no_lease(tmp_path):
    assert rte.lane_is_idle("gamma", lease_dir=tmp_path) is True


def test_lane_busy_when_lease_present(tmp_path):
    (tmp_path / "cc-active-task-gamma").write_text("some-task-id\n", encoding="utf-8")
    assert rte.lane_is_idle("gamma", lease_dir=tmp_path) is False


def test_lane_idle_when_lease_empty(tmp_path):
    (tmp_path / "cc-active-task-gamma").write_text("  \n", encoding="utf-8")
    assert rte.lane_is_idle("gamma", lease_dir=tmp_path) is True


def test_lane_busy_when_session_keyed_lease_present(tmp_path):
    (tmp_path / "cc-active-task-theta-abcd-uuid").write_text("t\n", encoding="utf-8")
    assert rte.lane_is_idle("theta", lease_dir=tmp_path) is False


def test_lane_idle_not_confused_by_prefix(tmp_path):
    # cc-active-task-theta must not make "eta" look busy.
    (tmp_path / "cc-active-task-theta").write_text("t\n", encoding="utf-8")
    assert rte.lane_is_idle("eta", lease_dir=tmp_path) is True


# --------------------------------------------------------------------------- #
# PR throttle
# --------------------------------------------------------------------------- #


def test_lane_count_distinct(tmp_path):
    assert rte.manifest_lane_count(_units(tmp_path)) == 6


def test_headroom_basic():
    # cap = 2 * 6 = 12; 9 open -> 3 headroom
    assert rte.dispatch_headroom(9, 6) == 3


def test_headroom_unknown_is_zero():
    # gh failure -> fail-closed, no dispatch
    assert rte.dispatch_headroom(None, 6) == 0


def test_headroom_over_cap_is_zero():
    assert rte.dispatch_headroom(20, 6) == 0


def test_count_open_prs_parses_json():
    runner = FakeRunner(stdout='[{"number":1},{"number":2},{"number":3}]')
    assert rte.count_open_prs(repo_root=Path("/x"), runner=runner) == 3
    assert runner.calls[0][0] == "gh"


def test_count_open_prs_failure_returns_none():
    runner = FakeRunner(returncode=1)
    assert rte.count_open_prs(repo_root=Path("/x"), runner=runner) is None


# --------------------------------------------------------------------------- #
# Dispatch plan
# --------------------------------------------------------------------------- #


def test_plan_dispatches_ready_units_on_idle_lanes(tmp_path):
    units = _units(tmp_path)
    plan = rte.plan_dispatch(units, idle_lanes={"epsilon", "zeta"}, headroom=5)
    assert {d.unit_id for d in plan} == {"UNIT-b", "FIX-thing"}


def test_plan_skips_ready_unit_on_busy_lane(tmp_path):
    units = _units(tmp_path)
    plan = rte.plan_dispatch(units, idle_lanes={"zeta"}, headroom=5)
    assert {d.unit_id for d in plan} == {"FIX-thing"}  # epsilon busy -> UNIT-b skipped


def test_plan_respects_headroom(tmp_path):
    units = _units(tmp_path)
    plan = rte.plan_dispatch(units, idle_lanes={"epsilon", "zeta"}, headroom=1)
    assert len(plan) == 1


def test_plan_zero_headroom_dispatches_nothing(tmp_path):
    units = _units(tmp_path)
    plan = rte.plan_dispatch(units, idle_lanes={"epsilon", "zeta"}, headroom=0)
    assert plan == []


def test_plan_one_per_lane(tmp_path):
    # two ready units on the same idle lane -> only one dispatched this sweep
    text = (
        SAMPLE_MANIFEST
        + """\
  - id: FIX-second
    lane: zeta
    hard_deps: []
    summary: another zeta fix
"""
    )
    units = rte.load_reform_manifest(_write_manifest(tmp_path, text))
    plan = rte.plan_dispatch(units, idle_lanes={"zeta"}, headroom=5)
    assert len([d for d in plan if d.lane == "zeta"]) == 1


# --------------------------------------------------------------------------- #
# Task resolution
# --------------------------------------------------------------------------- #


def _vault_with_task(tmp_path: Path, task_id: str, status: str = "offered") -> Path:
    active = tmp_path / "active"
    active.mkdir(parents=True, exist_ok=True)
    (active / f"{task_id}.md").write_text(
        f"---\ntask_id: {task_id}\nstatus: {status}\n---\n# t\n", encoding="utf-8"
    )
    return tmp_path


def test_resolve_task_matches_slug(tmp_path):
    vault = _vault_with_task(tmp_path, "reform-unit-b-20260531")
    by = _by_id(_units(tmp_path))
    assert rte.resolve_task_for_unit(by["UNIT-b"], vault_root=vault) == "reform-unit-b-20260531"


def test_resolve_task_none_when_absent(tmp_path):
    vault = _vault_with_task(tmp_path, "reform-unit-b-20260531")
    by = _by_id(_units(tmp_path))
    assert rte.resolve_task_for_unit(by["UNIT-c"], vault_root=vault) is None


# --------------------------------------------------------------------------- #
# Conductor prompt + dispatch command construction
# --------------------------------------------------------------------------- #


def test_conductor_prompt_mentions_unit_and_recipe(tmp_path):
    unit = _by_id(_units(tmp_path))["UNIT-b"]
    prompt = rte._conductor_prompt(unit.id, unit.lane, unit.summary)
    assert "UNIT-b" in prompt
    assert "reform-execution-manifest" in prompt
    assert "TDD" in prompt


def test_dispatch_command_greek_lane(tmp_path):
    decision = rte.DispatchDecision(
        unit_id="UNIT-b", lane="epsilon", authority_case="CASE-X-002", summary="s"
    )
    launch, send = rte.dispatch_command(decision, "reform-unit-b-20260531", repo_root=REPO_ROOT)
    assert any("hapax-claude" in part and "send" not in part for part in launch)
    assert "epsilon" in launch
    assert "reform-unit-b-20260531" in launch
    assert any("hapax-claude-send" in part for part in send)
    assert "--require-ack" in send


def test_dispatch_command_codex_lane(tmp_path):
    decision = rte.DispatchDecision(
        unit_id="UNIT-x", lane="cx-cyan", authority_case="CASE-Y", summary="s"
    )
    launch, send = rte.dispatch_command(decision, "reform-x-20260531", repo_root=REPO_ROOT)
    assert any("hapax-codex" in part for part in launch)
    assert "cx-cyan" in launch


# --------------------------------------------------------------------------- #
# run_dispatch orchestration
# --------------------------------------------------------------------------- #


def test_run_dispatch_dry_run_no_side_effects(tmp_path):
    manifest = _write_manifest(tmp_path)
    vault = _vault_with_task(tmp_path, "reform-unit-b-20260531")
    runner = FakeRunner(stdout="[]")  # 0 open PRs
    result = rte.run_dispatch(
        manifest_path=manifest,
        lease_dir=tmp_path,  # no lease files -> all lanes idle
        vault_root=vault,
        repo_root=REPO_ROOT,
        runner=runner,
        dry_run=True,
    )
    assert "UNIT-b" in result["ready"]
    assert result["dispatched"] == []
    # dry-run must not launch any lane (only the gh PR-count read is allowed)
    assert all(c[0] == "gh" for c in runner.calls)


def test_run_dispatch_executes_resolved_task(tmp_path):
    manifest = _write_manifest(tmp_path)
    vault = _vault_with_task(tmp_path, "reform-unit-b-20260531")
    runner = FakeRunner(stdout="[]")  # gh returns 0 open PRs -> headroom
    result = rte.run_dispatch(
        manifest_path=manifest,
        lease_dir=tmp_path,
        vault_root=vault,
        repo_root=REPO_ROOT,
        runner=runner,
        dry_run=False,
    )
    assert "UNIT-b" in result["dispatched"]
    # a lane launch must have happened
    assert any(any("hapax-claude" in p for p in c) for c in runner.calls)


def test_run_dispatch_skips_unit_without_task(tmp_path):
    manifest = _write_manifest(tmp_path)
    # vault has NO matching task for UNIT-b
    (tmp_path / "active").mkdir()
    runner = FakeRunner(stdout="[]")
    result = rte.run_dispatch(
        manifest_path=manifest,
        lease_dir=tmp_path,
        vault_root=tmp_path,
        repo_root=REPO_ROOT,
        runner=runner,
        dry_run=False,
    )
    assert "UNIT-b" not in result["dispatched"]
    assert "UNIT-b" in result["skipped_no_task"]


def test_run_dispatch_throttled_dispatches_nothing(tmp_path):
    manifest = _write_manifest(tmp_path)
    vault = _vault_with_task(tmp_path, "reform-unit-b-20260531")
    # 99 open PRs -> over any cap -> zero headroom
    runner = FakeRunner(stdout="[" + ",".join(f'{{"number":{i}}}' for i in range(99)) + "]")
    result = rte.run_dispatch(
        manifest_path=manifest,
        lease_dir=tmp_path,
        vault_root=vault,
        repo_root=REPO_ROOT,
        runner=runner,
        dry_run=False,
    )
    assert result["dispatched"] == []
    assert result.get("throttled") is True


# --------------------------------------------------------------------------- #
# cc-pr-merge-watcher nudge-next trigger
# --------------------------------------------------------------------------- #


def test_trigger_dispatch_invokes_rte_state(tmp_path, monkeypatch):
    monkeypatch.delenv("HAPAX_REFORM_AUTO_DISPATCH", raising=False)
    runner = FakeRunner()
    ok = watcher.trigger_reform_dispatch(repo_root=REPO_ROOT, runner=runner)
    assert ok is True
    assert len(runner.calls) == 1
    cmd = runner.calls[0]
    assert any("hapax-rte-state" in p for p in cmd)
    assert "--dispatch" in cmd


def test_trigger_dispatch_disabled_by_env(tmp_path, monkeypatch):
    monkeypatch.setenv("HAPAX_REFORM_AUTO_DISPATCH", "0")
    runner = FakeRunner()
    ok = watcher.trigger_reform_dispatch(repo_root=REPO_ROOT, runner=runner)
    assert ok is False
    assert runner.calls == []


def test_trigger_dispatch_fail_open(tmp_path, monkeypatch):
    monkeypatch.delenv("HAPAX_REFORM_AUTO_DISPATCH", raising=False)
    runner = FakeRunner(raises=True)
    # must not propagate the error
    assert watcher.trigger_reform_dispatch(repo_root=REPO_ROOT, runner=runner) is False


def _patch_watcher_main(monkeypatch, closed: int):
    """Stub run_watcher + reconcile so main()'s nudge wiring can be tested alone."""
    monkeypatch.setattr(
        watcher,
        "run_watcher",
        lambda **kw: {"merged": 1, "linked": 1, "closed": closed, "failed": 0, "skipped": 0},
    )
    monkeypatch.setattr(
        watcher, "reconcile_stale_pr_states", lambda **kw: {"scanned": 0, "stale": 0}
    )
    calls: list[dict] = []
    monkeypatch.setattr(watcher, "trigger_reform_dispatch", lambda **kw: calls.append(kw) or True)
    return calls


def test_main_nudges_dispatch_after_close(monkeypatch):
    calls = _patch_watcher_main(monkeypatch, closed=1)
    assert watcher.main([]) == 0
    assert len(calls) == 1  # main nudged the dispatcher exactly once


def test_main_no_nudge_when_nothing_closed(monkeypatch):
    calls = _patch_watcher_main(monkeypatch, closed=0)
    assert watcher.main([]) == 0
    assert calls == []  # nothing closed -> no nudge


def test_main_no_nudge_on_dry_run(monkeypatch):
    calls = _patch_watcher_main(monkeypatch, closed=1)
    assert watcher.main(["--dry-run"]) == 0
    assert calls == []  # dry-run must never nudge a real dispatch
