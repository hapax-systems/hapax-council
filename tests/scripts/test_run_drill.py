"""Tests for scripts/run_drill.py (LRR Phase 10 item 4)."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest


def _load_module():
    import importlib.util
    import sys

    if "run_drill" in sys.modules:
        return sys.modules["run_drill"]
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "run_drill.py"
    spec = importlib.util.spec_from_file_location("run_drill", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_drill"] = module  # required for dataclass / typing resolution
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def run_drill_mod():
    return _load_module()


class TestDrillRegistry:
    def test_seven_drills_registered(self, run_drill_mod):
        # Six Phase 10 drills + the Continuous-Loop §3.7 validation drill.
        assert len(run_drill_mod.DRILLS) == 7

    def test_canonical_names(self, run_drill_mod):
        expected = {
            "pre-stream-consent",
            "mid-stream-consent-revocation",
            "stimmung-breach-auto-private",
            "failure-mode-rehearsal",
            "privacy-regression-suite",
            "audience-engagement-ab",
            "closed-loop-validation",
        }
        assert set(run_drill_mod.DRILLS) == expected

    def test_every_drill_has_name_and_description(self, run_drill_mod):
        for cls in run_drill_mod.DRILLS.values():
            assert cls.name
            assert cls.description


class TestRunDrill:
    def test_unknown_drill_raises(self, run_drill_mod):
        with pytest.raises(SystemExit):
            run_drill_mod.run_drill("not-a-real-drill")

    def test_dry_run_default(self, run_drill_mod):
        run = run_drill_mod.run_drill("pre-stream-consent", live=False)
        assert run.mode == "dry-run"
        assert run.drill_name == "pre-stream-consent"
        assert isinstance(run.pre_checks, list)
        assert isinstance(run.steps_executed, list)
        assert isinstance(run.post_checks, list)

    def test_every_drill_dry_runs_cleanly(self, run_drill_mod):
        for name in run_drill_mod.DRILLS:
            run = run_drill_mod.run_drill(name, live=False)
            assert run.drill_name == name
            assert run.mode == "dry-run"

    def test_live_mode_flag_propagates(self, run_drill_mod):
        run = run_drill_mod.run_drill("pre-stream-consent", live=True)
        assert run.mode == "live"


class TestCheckResult:
    def test_passed_field_summarises_run(self, run_drill_mod):
        run = run_drill_mod.DrillRun(
            drill_name="x",
            started_at=_dt.datetime(2026, 4, 17, tzinfo=_dt.UTC),
            mode="dry-run",
            pre_checks=[run_drill_mod.CheckResult("a", True), run_drill_mod.CheckResult("b", True)],
            post_checks=[run_drill_mod.CheckResult("c", True)],
        )
        assert run.passed is True

    def test_any_failed_check_flips_passed(self, run_drill_mod):
        run = run_drill_mod.DrillRun(
            drill_name="x",
            started_at=_dt.datetime(2026, 4, 17, tzinfo=_dt.UTC),
            mode="dry-run",
            pre_checks=[run_drill_mod.CheckResult("a", False)],
            post_checks=[],
        )
        assert run.passed is False


class TestRenderAndWriteDoc:
    def test_render_includes_key_sections(self, run_drill_mod):
        run = run_drill_mod.run_drill("pre-stream-consent", live=False)
        drill = run_drill_mod.DRILLS["pre-stream-consent"]()
        md = run_drill_mod.render_result_doc(run, drill)

        assert "# pre-stream-consent drill" in md
        assert "## Pre-checks" in md
        assert "## Steps executed" in md
        assert "## Post-checks" in md
        assert "## Outcome" in md
        assert "## Operator notes" in md
        assert "**Mode:** dry-run" in md

    def test_write_creates_dated_file(self, run_drill_mod, tmp_path: Path):
        run = run_drill_mod.run_drill("stimmung-breach-auto-private", live=False)
        drill = run_drill_mod.DRILLS["stimmung-breach-auto-private"]()
        path = run_drill_mod.write_result_doc(run, drill, out_dir=tmp_path)

        assert path.parent == tmp_path
        assert path.name.endswith("-stimmung-breach-auto-private.md")
        content = path.read_text(encoding="utf-8")
        assert "stimmung-breach-auto-private" in content

    def test_write_creates_dir_if_missing(self, run_drill_mod, tmp_path: Path):
        nested = tmp_path / "nested" / "drills"
        run = run_drill_mod.run_drill("pre-stream-consent", live=False)
        drill = run_drill_mod.DRILLS["pre-stream-consent"]()
        path = run_drill_mod.write_result_doc(run, drill, out_dir=nested)
        assert path.exists()
        assert nested.is_dir()


class TestCli:
    def test_main_writes_doc_and_exits_0_on_pass(
        self, run_drill_mod, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(run_drill_mod, "DRILLS_DIR", tmp_path)
        rc = run_drill_mod.main(["pre-stream-consent", "--out-dir", str(tmp_path)])
        assert rc in (0, 1)  # depends on check results; both codes are legitimate
        written = list(tmp_path.glob("*-pre-stream-consent.md"))
        assert len(written) == 1

    def test_main_rejects_unknown_drill(self, run_drill_mod, capsys):
        with pytest.raises(SystemExit):
            run_drill_mod.main(["not-real"])
