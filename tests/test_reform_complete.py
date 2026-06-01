"""Tests for ``scripts/hapax-reform-complete`` — the reform-complete acceptance predicate.

The script splits live host probing (``gather_*``) from pure decision logic
(``decide_*``). These tests exercise the decision logic and the CLI exit-code
contract via ``--observations`` (which skips all live probing), so they are
deterministic and need no systemd / coord substrate — they run anywhere CI runs.
"""

import importlib.util
import json
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "hapax-reform-complete"


def _load_module():
    # The script is an extensionless executable, so a loader cannot be inferred from
    # the suffix — name it explicitly via SourceFileLoader.
    loader = SourceFileLoader("hapax_reform_complete", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec
    mod = importlib.util.module_from_spec(spec)
    # Register before exec so @dataclass can resolve cls.__module__ during class creation.
    sys.modules[loader.name] = mod
    loader.exec_module(mod)
    return mod


mod = _load_module()


def _all_good() -> dict:
    """A complete observations map where every realization is live."""
    return {
        "coord-ssot-ledger": {
            "ledger_db_exists": True,
            "ledger_db_writable": True,
            "jsonl_exists": True,
            "spool_is_dir": True,
            "tracked_ledger_count": 0,
            "drift_count": 0,
            "drift_check_rc": 0,
        },
        "opus-route-authority": {
            "receipt_exists": True,
            "receipt_fresh": True,
            "timer_enabled": "enabled",
            "timer_active": "active",
        },
        "lane-supervisor": {"timer_enabled": "enabled", "timer_active": "active"},
        "canonical-gate": {
            "live_gate_exists": True,
            "live_inv5": True,
            "repo_inv5": True,
            "live_matches_repo": True,
            "lane_missing_inv5": [],
            "lane_gate_count": 25,
        },
        "escape-grant": {
            "grant_dir_exists": True,
            "key_present": True,
            "shim_present": True,
            "gate_wired": True,
            "roundtrip_ok": True,
        },
        "coord-verbs": {
            "coord_repo_exists": True,
            "model_present": True,
            "refine_verb": True,
            "nonfallback_verb": True,
            "coord_verb_count": 49,
        },
        "shadow-cutover": {
            "eval_script_present": True,
            "predicate_reachable": True,
            "cutover_enforced": False,
        },
        "off-deprecation": {
            "retro_watch_present": True,
            "obligation_marker": True,
            "off_deprecated": True,
            "zombie_pidfiles": [],
        },
    }


# ── decider unit tests ────────────────────────────────────────────────────────


class TestCoordSsotLedger:
    def test_all_good_passes(self) -> None:
        assert mod.decide_coord_ssot_ledger(_all_good()["coord-ssot-ledger"]).ok

    def test_advisory_drift_is_not_a_failure(self) -> None:
        # The keystone calibration: coord-drift-check is advisory (rc 0 even on drift),
        # so a large advisory drift_count must NOT fail this realization.
        obs = _all_good()["coord-ssot-ledger"] | {"drift_count": 417, "drift_check_rc": 0}
        assert mod.decide_coord_ssot_ledger(obs).ok

    def test_drift_check_nonzero_rc_fails(self) -> None:
        obs = _all_good()["coord-ssot-ledger"] | {"drift_check_rc": 1}
        result = mod.decide_coord_ssot_ledger(obs)
        assert not result.ok
        assert "coord-drift-check" in result.reason

    def test_tracked_per_worktree_ledgers_fail(self) -> None:
        obs = _all_good()["coord-ssot-ledger"] | {"tracked_ledger_count": 17}
        result = mod.decide_coord_ssot_ledger(obs)
        assert not result.ok
        assert "git-tracked" in result.reason

    def test_missing_ledger_db_fails(self) -> None:
        obs = _all_good()["coord-ssot-ledger"] | {"ledger_db_exists": False}
        assert not mod.decide_coord_ssot_ledger(obs).ok


class TestOpusRouteAuthority:
    def test_fresh_receipt_passes(self) -> None:
        assert mod.decide_opus_route_authority(_all_good()["opus-route-authority"]).ok

    def test_absent_receipt_fails(self) -> None:
        obs = _all_good()["opus-route-authority"] | {"receipt_exists": False}
        result = mod.decide_opus_route_authority(obs)
        assert not result.ok
        assert "policy-rollback" in result.reason

    def test_expired_receipt_fails(self) -> None:
        obs = _all_good()["opus-route-authority"] | {"receipt_fresh": False}
        assert not mod.decide_opus_route_authority(obs).ok

    def test_inactive_timer_fails(self) -> None:
        obs = _all_good()["opus-route-authority"] | {"timer_active": "inactive"}
        assert not mod.decide_opus_route_authority(obs).ok


class TestLaneSupervisor:
    def test_enabled_active_passes(self) -> None:
        assert mod.decide_lane_supervisor(_all_good()["lane-supervisor"]).ok

    def test_disabled_timer_fails(self) -> None:
        obs = {"timer_enabled": "disabled", "timer_active": "inactive"}
        assert not mod.decide_lane_supervisor(obs).ok

    def test_enabled_but_inactive_fails(self) -> None:
        # A timer-activated oneshot's SERVICE may be inactive, but the TIMER itself
        # must be active; this guards the realization against a stopped timer.
        obs = {"timer_enabled": "enabled", "timer_active": "inactive"}
        assert not mod.decide_lane_supervisor(obs).ok


class TestCanonicalGate:
    def test_all_good_passes(self) -> None:
        assert mod.decide_canonical_gate(_all_good()["canonical-gate"]).ok

    def test_lane_source_missing_inv5_is_informational(self) -> None:
        # Calibration: unwired per-worktree gate source copies on feature branches do
        # not run; only the live gate + repo source matter for "INV-5 everywhere".
        obs = _all_good()["canonical-gate"] | {
            "lane_missing_inv5": ["/p/hapax-council--beta/hooks/scripts/cc-task-gate.sh"]
        }
        assert mod.decide_canonical_gate(obs).ok

    def test_live_repo_divergence_fails(self) -> None:
        obs = _all_good()["canonical-gate"] | {"live_matches_repo": False}
        assert not mod.decide_canonical_gate(obs).ok

    def test_repo_missing_inv5_fails(self) -> None:
        obs = _all_good()["canonical-gate"] | {"repo_inv5": False}
        result = mod.decide_canonical_gate(obs)
        assert not result.ok
        assert "INV-5" in result.reason

    def test_live_missing_inv5_fails(self) -> None:
        obs = _all_good()["canonical-gate"] | {"live_inv5": False}
        assert not mod.decide_canonical_gate(obs).ok


class TestEscapeGrant:
    def test_roundtrip_ok_passes(self) -> None:
        assert mod.decide_escape_grant(_all_good()["escape-grant"]).ok

    def test_absent_key_fails(self) -> None:
        obs = _all_good()["escape-grant"] | {"key_present": False}
        result = mod.decide_escape_grant(obs)
        assert not result.ok
        assert "inert" in result.reason

    def test_not_wired_fails(self) -> None:
        obs = _all_good()["escape-grant"] | {"gate_wired": False}
        assert not mod.decide_escape_grant(obs).ok

    def test_failed_roundtrip_fails(self) -> None:
        obs = _all_good()["escape-grant"] | {"roundtrip_ok": False}
        result = mod.decide_escape_grant(obs)
        assert not result.ok
        assert "INV-3/4" in result.reason


class TestCoordVerbs:
    def test_refine_plus_nonfallback_passes(self) -> None:
        assert mod.decide_coord_verbs(_all_good()["coord-verbs"]).ok

    def test_refine_present_but_all_fallback_fails(self) -> None:
        # The live state at authoring time: refine verb defined, but every coord verb
        # is a dry-run fallback stub — a genuine, must-report realization gap.
        obs = _all_good()["coord-verbs"] | {"nonfallback_verb": False}
        result = mod.decide_coord_verbs(obs)
        assert not result.ok
        assert "non-fallback" in result.reason

    def test_absent_refine_verb_fails(self) -> None:
        obs = _all_good()["coord-verbs"] | {"refine_verb": False}
        result = mod.decide_coord_verbs(obs)
        assert not result.ok
        assert "coord.request.refine" in result.reason

    def test_absent_repo_fails(self) -> None:
        obs = _all_good()["coord-verbs"] | {"coord_repo_exists": False}
        assert not mod.decide_coord_verbs(obs).ok


class TestShadowCutover:
    def test_predicate_reachable_passes(self) -> None:
        assert mod.decide_shadow_cutover(_all_good()["shadow-cutover"]).ok

    def test_enforced_only_passes(self) -> None:
        obs = {"predicate_reachable": False, "cutover_enforced": True, "eval_script_present": True}
        assert mod.decide_shadow_cutover(obs).ok

    def test_neither_fails(self) -> None:
        obs = {
            "predicate_reachable": False,
            "cutover_enforced": False,
            "eval_script_present": False,
        }
        assert not mod.decide_shadow_cutover(obs).ok


class TestOffDeprecation:
    def test_all_good_passes(self) -> None:
        assert mod.decide_off_deprecation(_all_good()["off-deprecation"]).ok

    def test_zombie_pidfile_fails(self) -> None:
        obs = _all_good()["off-deprecation"] | {"zombie_pidfiles": ["theta.pid"]}
        result = mod.decide_off_deprecation(obs)
        assert not result.ok
        assert "zombie" in result.reason

    def test_absent_retro_watch_fails(self) -> None:
        obs = _all_good()["off-deprecation"] | {"retro_watch_present": False}
        assert not mod.decide_off_deprecation(obs).ok

    def test_off_not_deprecated_fails(self) -> None:
        obs = _all_good()["off-deprecation"] | {"off_deprecated": False}
        assert not mod.decide_off_deprecation(obs).ok


# ── verdict aggregation + watermark ───────────────────────────────────────────


class TestAggregation:
    def test_all_good_is_complete(self) -> None:
        results = mod.decide_all(_all_good())
        assert all(r.ok for r in results)

    def test_missing_observation_reports_missing(self) -> None:
        obs = _all_good()
        del obs["lane-supervisor"]
        results = {r.check_id: r for r in mod.decide_all(obs)}
        assert not results["lane-supervisor"].ok
        assert "missing" in results["lane-supervisor"].reason


class TestWatermark:
    def test_roundtrip(self, tmp_path: Path) -> None:
        wm = tmp_path / "wm.json"
        mod.save_watermark(wm, {"a", "b"})
        assert mod.load_watermark(wm) == {"a", "b"}

    def test_absent_file_is_empty(self, tmp_path: Path) -> None:
        assert mod.load_watermark(tmp_path / "nope.json") == set()

    def test_corrupt_file_is_empty(self, tmp_path: Path) -> None:
        wm = tmp_path / "wm.json"
        wm.write_text("{ not json", encoding="utf-8")
        assert mod.load_watermark(wm) == set()


# ── CLI exit-code contract (subprocess; --observations skips live probing) ─────


def _run_cli(obs: dict, tmp_path: Path, *extra: str) -> subprocess.CompletedProcess:
    obs_file = tmp_path / "obs.json"
    obs_file.write_text(json.dumps(obs), encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--observations",
            str(obs_file),
            "--watermark",
            str(tmp_path / "wm.json"),
            "--no-ntfy",
            "--quiet",
            *extra,
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )


class TestCli:
    def test_all_good_exits_zero(self, tmp_path: Path) -> None:
        r = _run_cli(_all_good(), tmp_path)
        assert r.returncode == 0, r.stdout + r.stderr
        verdict = json.loads(r.stdout)
        assert verdict["complete"] is True
        assert verdict["failed"] == 0

    def test_one_gap_exits_one(self, tmp_path: Path) -> None:
        obs = _all_good()
        obs["coord-verbs"]["nonfallback_verb"] = False
        r = _run_cli(obs, tmp_path)
        assert r.returncode == 1
        verdict = json.loads(r.stdout)
        assert verdict["complete"] is False
        assert any("coord-verbs" in reason for reason in verdict["reasons"])

    def test_regression_only_quiet_for_never_passed(self, tmp_path: Path) -> None:
        # A check that has never passed (empty watermark) failing is NOT a regression,
        # so the periodic detector stays quiet while the reform is still being built.
        obs = _all_good()
        obs["coord-verbs"]["nonfallback_verb"] = False
        r = _run_cli(obs, tmp_path, "--regression-only")
        assert r.returncode == 0, r.stdout + r.stderr
        assert json.loads(r.stdout)["regressed"] == []

    def test_regression_only_fires_on_revert(self, tmp_path: Path) -> None:
        # Pre-seed the watermark so lane-supervisor "has passed before"; then revert it.
        (tmp_path / "wm.json").write_text(
            json.dumps({"passed_ever": ["lane-supervisor"]}), encoding="utf-8"
        )
        obs = _all_good()
        obs["lane-supervisor"] = {"timer_enabled": "disabled", "timer_active": "inactive"}
        obs_file = tmp_path / "obs.json"
        obs_file.write_text(json.dumps(obs), encoding="utf-8")
        r = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--observations",
                str(obs_file),
                "--watermark",
                str(tmp_path / "wm.json"),
                "--regression-only",
                "--no-ntfy",
                "--quiet",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert r.returncode == 1
        assert "lane-supervisor" in json.loads(r.stdout)["regressed"]

    def test_terminal_run_updates_watermark(self, tmp_path: Path) -> None:
        r = _run_cli(_all_good(), tmp_path)
        assert r.returncode == 0
        passed_ever = set(json.loads((tmp_path / "wm.json").read_text())["passed_ever"])
        assert set(mod.CHECK_IDS) <= passed_ever
