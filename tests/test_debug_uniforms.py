"""Tests for ``agents.reverie.debug_uniforms`` (delta PR-3).

Covers the snapshot builder, the healthy/degraded classification, the
text and JSON report formats, and the exit-code contract that CI and
local smoke tests depend on.
"""

from __future__ import annotations

import json
from pathlib import Path

from agents.reverie import debug_uniforms


def _write_v2_plan(path: Path, passes: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 2, "targets": {"main": {"passes": passes}}}))


def _write_v1_plan(path: Path, passes: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"passes": passes}))


def _pass(node_id: str, uniforms: dict) -> dict:
    return {"node_id": node_id, "uniforms": uniforms}


class TestSnapshot:
    def test_healthy_matches_plan_defaults(self, tmp_path: Path) -> None:
        plan_path = tmp_path / "plan.json"
        _write_v2_plan(
            plan_path,
            [
                _pass("noise", {"amplitude": 0.7, "frequency_x": 1.5}),
                _pass("color", {"brightness": 1.0, "saturation": 1.0}),
            ],
        )
        uniforms_path = tmp_path / "uniforms.json"
        uniforms_path.write_text(
            json.dumps(
                {
                    "noise.amplitude": 0.7,
                    "noise.frequency_x": 1.5,
                    "color.brightness": 1.0,
                    "color.saturation": 1.0,
                    "signal.stance": 0.0,
                }
            )
        )

        snap = debug_uniforms.snapshot(uniforms_path, plan_path)

        assert snap.uniforms_exists is True
        assert snap.plan_exists is True
        assert snap.uniforms_key_count == 5
        assert snap.plan_defaults_count == 4
        assert snap.deficit == 0
        assert snap.healthy is True
        assert snap.missing_defaults == []
        # signal.stance is an intentional cross-cutting key — should not
        # be flagged as "extra".
        assert snap.extra_keys == []

    def test_degraded_when_deficit_exceeds_threshold(self, tmp_path: Path) -> None:
        plan_path = tmp_path / "plan.json"
        uniforms = {f"node{i}.param": 0.1 * i for i in range(10)}
        _write_v2_plan(
            plan_path,
            [_pass(f"node{i}", {"param": 0.1 * i}) for i in range(10)],
        )
        uniforms_path = tmp_path / "uniforms.json"
        # Only write 3 of 10 — deficit of 7, above ALLOWED_DEFICIT (5)
        partial = {k: v for k, v in list(uniforms.items())[:3]}
        uniforms_path.write_text(json.dumps(partial))

        snap = debug_uniforms.snapshot(uniforms_path, plan_path)

        assert snap.uniforms_key_count == 3
        assert snap.plan_defaults_count == 10
        assert snap.deficit == 7
        assert snap.healthy is False
        assert len(snap.missing_defaults) == 7

    def test_deficit_at_threshold_is_healthy(self, tmp_path: Path) -> None:
        plan_path = tmp_path / "plan.json"
        _write_v2_plan(
            plan_path,
            [_pass(f"node{i}", {"param": 0.0}) for i in range(10)],
        )
        uniforms_path = tmp_path / "uniforms.json"
        # 5 of 10 → deficit == 5 == ALLOWED_DEFICIT, still healthy
        uniforms_path.write_text(json.dumps({f"node{i}.param": 0.0 for i in range(5)}))

        snap = debug_uniforms.snapshot(uniforms_path, plan_path)

        assert snap.deficit == debug_uniforms.ALLOWED_DEFICIT
        assert snap.healthy is True

    def test_missing_uniforms_file(self, tmp_path: Path) -> None:
        plan_path = tmp_path / "plan.json"
        _write_v2_plan(plan_path, [_pass("noise", {"amplitude": 0.7})])
        snap = debug_uniforms.snapshot(tmp_path / "does-not-exist.json", plan_path)
        assert snap.uniforms_exists is False
        assert snap.healthy is False

    def test_missing_plan_file(self, tmp_path: Path) -> None:
        uniforms_path = tmp_path / "uniforms.json"
        uniforms_path.write_text(json.dumps({"x": 1.0}))
        snap = debug_uniforms.snapshot(uniforms_path, tmp_path / "no-plan.json")
        assert snap.plan_exists is False
        assert snap.healthy is False

    def test_malformed_uniforms_json(self, tmp_path: Path) -> None:
        plan_path = tmp_path / "plan.json"
        _write_v2_plan(plan_path, [_pass("noise", {"amplitude": 0.7})])
        uniforms_path = tmp_path / "uniforms.json"
        uniforms_path.write_text("{not json")
        snap = debug_uniforms.snapshot(uniforms_path, plan_path)
        assert snap.uniforms_exists is False
        assert snap.healthy is False

    def test_v1_plan_schema_supported(self, tmp_path: Path) -> None:
        """v1 flat-passes plans must still work (pre-refactor callers)."""
        plan_path = tmp_path / "plan.json"
        _write_v1_plan(plan_path, [_pass("noise", {"amplitude": 0.7})])
        uniforms_path = tmp_path / "uniforms.json"
        uniforms_path.write_text(json.dumps({"noise.amplitude": 0.7}))
        snap = debug_uniforms.snapshot(uniforms_path, plan_path)
        assert snap.plan_defaults_count == 1
        assert snap.healthy is True

    def test_nonnumeric_keys_not_counted_toward_coverage(self, tmp_path: Path) -> None:
        plan_path = tmp_path / "plan.json"
        _write_v2_plan(plan_path, [_pass("noise", {"amplitude": 0.7})])
        uniforms_path = tmp_path / "uniforms.json"
        uniforms_path.write_text(json.dumps({"noise.amplitude": 0.7, "version": "v2"}))
        snap = debug_uniforms.snapshot(uniforms_path, plan_path)
        # "version" is non-numeric → not counted toward key_count, listed separately
        assert snap.uniforms_key_count == 1
        assert snap.nonnumeric_keys == ["version"]

    def test_signal_and_fb_trace_keys_are_not_flagged_as_extras(self, tmp_path: Path) -> None:
        plan_path = tmp_path / "plan.json"
        _write_v2_plan(plan_path, [_pass("noise", {"amplitude": 0.7})])
        uniforms_path = tmp_path / "uniforms.json"
        uniforms_path.write_text(
            json.dumps(
                {
                    "noise.amplitude": 0.7,
                    "signal.stance": 0.0,
                    "signal.color_warmth": 0.85,
                    "fb.trace_center_x": 0.5,
                    "fb.trace_center_y": 0.5,
                    "rogue.key": 1.0,
                }
            )
        )
        snap = debug_uniforms.snapshot(uniforms_path, plan_path)
        assert snap.extra_keys == ["rogue.key"]


class TestCLIExitCode:
    def test_exit_zero_when_healthy(self, tmp_path: Path, capsys) -> None:
        plan_path = tmp_path / "plan.json"
        _write_v2_plan(plan_path, [_pass("noise", {"amplitude": 0.7})])
        uniforms_path = tmp_path / "uniforms.json"
        uniforms_path.write_text(json.dumps({"noise.amplitude": 0.7}))

        rc = debug_uniforms.main(["--uniforms", str(uniforms_path), "--plan", str(plan_path)])

        assert rc == 0
        captured = capsys.readouterr()
        assert "HEALTHY" in captured.out

    def test_exit_two_when_deficit_exceeds_threshold(self, tmp_path: Path, capsys) -> None:
        plan_path = tmp_path / "plan.json"
        _write_v2_plan(
            plan_path,
            [_pass(f"node{i}", {"param": 0.0}) for i in range(10)],
        )
        uniforms_path = tmp_path / "uniforms.json"
        uniforms_path.write_text(json.dumps({"node0.param": 0.0}))

        rc = debug_uniforms.main(["--uniforms", str(uniforms_path), "--plan", str(plan_path)])

        assert rc == 2
        captured = capsys.readouterr()
        assert "DEGRADED" in captured.out

    def test_json_output_parses_and_contains_counts(self, tmp_path: Path, capsys) -> None:
        plan_path = tmp_path / "plan.json"
        _write_v2_plan(plan_path, [_pass("noise", {"amplitude": 0.7})])
        uniforms_path = tmp_path / "uniforms.json"
        uniforms_path.write_text(json.dumps({"noise.amplitude": 0.7}))

        debug_uniforms.main(
            [
                "--uniforms",
                str(uniforms_path),
                "--plan",
                str(plan_path),
                "--json",
            ]
        )
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert payload["uniforms_key_count"] == 1
        assert payload["plan_defaults_count"] == 1
        assert payload["uniforms_exists"] is True
        assert payload["plan_exists"] is True

    def test_verbose_lists_all_missing_keys(self, tmp_path: Path, capsys) -> None:
        plan_path = tmp_path / "plan.json"
        _write_v2_plan(
            plan_path,
            [_pass(f"node{i}", {"param": 0.0}) for i in range(20)],
        )
        uniforms_path = tmp_path / "uniforms.json"
        uniforms_path.write_text(json.dumps({}))

        debug_uniforms.main(
            [
                "--uniforms",
                str(uniforms_path),
                "--plan",
                str(plan_path),
                "--verbose",
            ]
        )
        captured = capsys.readouterr()
        # All 20 missing keys should be listed
        for i in range(20):
            assert f"node{i}.param" in captured.out
