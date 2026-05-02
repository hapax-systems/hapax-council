"""Tests for the --verify-auto-gtm-predictions and --verify-v1-stability flags."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import yaml

RUNNER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "braided_value_snapshot_runner.py"


def _runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("braided_value_snapshot_runner", RUNNER_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_task(root: Path, directory: str, task_id: str, frontmatter: dict) -> Path:
    note_dir = root / directory
    note_dir.mkdir(parents=True, exist_ok=True)
    fm = {"type": "cc-task", "task_id": task_id, **frontmatter}
    path = note_dir / f"{task_id}.md"
    path.write_text(f"---\n{yaml.safe_dump(fm, sort_keys=False)}---\n", encoding="utf-8")
    return path


# ── verify-auto-gtm-predictions ────────────────────────────────────────


class TestVerifyAutoGtmPredictions:
    def test_missing_task_fails(self, tmp_path: Path) -> None:
        mod = _runner()
        from datetime import UTC, datetime

        # Vault has zero Auto-GTM tasks → all 7 missing → 7 FAIL lines, exit 1.
        exit_code, lines = mod._verify_auto_gtm_predictions(
            task_root=tmp_path, now=datetime(2026, 5, 1, tzinfo=UTC), tolerance=0.1
        )
        assert exit_code == 1
        assert all("not found" in line for line in lines)
        assert len(lines) == len(mod.SPEC_AUTO_GTM_PREDICTIONS)

    def test_v1_schema_task_fails_verification(self, tmp_path: Path) -> None:
        """An Auto-GTM task that's still on v1 schema is a verification fail."""

        mod = _runner()
        from datetime import UTC, datetime

        _write_task(
            tmp_path,
            "active",
            "wyoming-llc-dba-legal-entity-bootstrap",
            {
                "braid_schema": 1,
                "braid_engagement": 5,
                "braid_monetary": 10,
                "braid_research": 4,
                "braid_tree_effect": 10,
                "braid_evidence_confidence": 9,
                "braid_risk_penalty": 0.3,
                "braid_score": 6.4,
            },
        )
        exit_code, lines = mod._verify_auto_gtm_predictions(
            task_root=tmp_path, now=datetime(2026, 5, 1, tzinfo=UTC), tolerance=0.1
        )
        assert exit_code == 1
        wyoming_line = next(line for line in lines if "wyoming-llc-dba" in line)
        assert "expected '1.1'" in wyoming_line

    def test_v11_in_tolerance_passes(self, tmp_path: Path) -> None:
        """An Auto-GTM task using the canonical frontmatter dimensions passes."""

        mod = _runner()
        from datetime import UTC, datetime

        # Wyoming-llc canonical dimensions per spec §Predicted re-ranking
        # (frontmatter snapshot 2026-05-01T15:10Z). v1.1 formula computes 6.28:
        #   0.30*4 + 0.25*(19/3) + 0.20*10 + 0.10*(12/1.5) + 0.10*1
        #   + 0.05*0 + 0.10*9 - 0.3 = 6.28
        _write_task(
            tmp_path,
            "active",
            "wyoming-llc-dba-legal-entity-bootstrap",
            {
                "braid_schema": 1.1,
                "braid_engagement": 5,
                "braid_monetary": 10,
                "braid_research": 4,
                "braid_tree_effect": 10,
                "braid_evidence_confidence": 9,
                "braid_risk_penalty": 0.3,
                "braid_forcing_function_window": "none",
                "braid_unblock_breadth": 12,
                "braid_polysemic_channels": [6],
                "braid_axiomatic_strain": 0,
                "braid_score": 6.28,
            },
        )
        # Other 6 tasks intentionally absent so they show FAIL but the
        # wyoming line shows OK.
        exit_code, lines = mod._verify_auto_gtm_predictions(
            task_root=tmp_path, now=datetime(2026, 5, 1, tzinfo=UTC), tolerance=0.1
        )
        wyoming_line = next(line for line in lines if "wyoming-llc-dba" in line)
        assert wyoming_line.startswith("OK"), wyoming_line


# ── verify-v1-stability ────────────────────────────────────────────────


class TestVerifyV1Stability:
    def test_empty_vault_passes(self, tmp_path: Path) -> None:
        mod = _runner()
        exit_code, lines = mod._verify_v1_stability(task_root=tmp_path, tolerance=0.1)
        assert exit_code == 0
        assert any("v1 stability" in line for line in lines)

    def test_v1_task_with_drifting_score_fails(self, tmp_path: Path) -> None:
        mod = _runner()
        _write_task(
            tmp_path,
            "active",
            "drifting-task",
            {
                "braid_schema": 1,
                "braid_engagement": 5,
                "braid_monetary": 5,
                "braid_research": 5,
                "braid_tree_effect": 5,
                "braid_evidence_confidence": 5,
                "braid_risk_penalty": 0.0,
                "braid_score": 99.0,  # absurd declared value
            },
        )
        exit_code, lines = mod._verify_v1_stability(task_root=tmp_path, tolerance=0.1)
        assert exit_code == 1
        assert any("drifting-task" in line for line in lines)

    def test_v11_tasks_skipped(self, tmp_path: Path) -> None:
        """v1.1 tasks must not affect v1-stability check."""

        mod = _runner()
        _write_task(
            tmp_path,
            "active",
            "v11-task",
            {
                "braid_schema": 1.1,
                "braid_engagement": 5,
                "braid_monetary": 5,
                "braid_research": 5,
                "braid_tree_effect": 5,
                "braid_evidence_confidence": 5,
                "braid_risk_penalty": 0.0,
                "braid_score": 99.0,  # absurd, but should be skipped
            },
        )
        exit_code, _ = mod._verify_v1_stability(task_root=tmp_path, tolerance=0.1)
        assert exit_code == 0

    def test_v1_within_tolerance_passes(self, tmp_path: Path) -> None:
        mod = _runner()
        # 0.35*5 + 0.30*5 + 0.25*5 + 0.10*5 - 0 = 1.75+1.5+1.25+0.5 = 5.0
        _write_task(
            tmp_path,
            "active",
            "stable-task",
            {
                "braid_schema": 1,
                "braid_engagement": 5,
                "braid_monetary": 5,
                "braid_research": 5,
                "braid_tree_effect": 5,
                "braid_evidence_confidence": 5,
                "braid_risk_penalty": 0.0,
                "braid_score": 5.0,
            },
        )
        exit_code, _ = mod._verify_v1_stability(task_root=tmp_path, tolerance=0.1)
        assert exit_code == 0

    def test_carveout_task_drift_is_exempt(self, tmp_path: Path, monkeypatch) -> None:
        """A v1 task in BRAID_V1_STABILITY_CARVEOUT can drift without failing."""

        mod = _runner()
        # gcp-youtube-quota-extension-runner is in the carveout (positive
        # +0.40 drift in the 2026-05-02 snapshot).
        carved_id = next(iter(mod.BRAID_V1_STABILITY_CARVEOUT))
        _write_task(
            tmp_path,
            "active",
            carved_id,
            {
                "braid_schema": 1,
                "braid_engagement": 5,
                "braid_monetary": 5,
                "braid_research": 5,
                "braid_tree_effect": 5,
                "braid_evidence_confidence": 5,
                "braid_risk_penalty": 0.0,
                "braid_score": 99.0,  # absurd drift, but carved out
            },
        )
        exit_code, lines = mod._verify_v1_stability(task_root=tmp_path, tolerance=0.1)
        assert exit_code == 0, lines
        # The OK summary line should mention the carveout count.
        assert any("carveout exempt" in line for line in lines), lines
        # The carved task ID must NOT appear as a FAIL line.
        assert not any(carved_id in line and "FAIL" in line for line in lines), lines

    def test_carveout_does_not_mask_new_drift(self, tmp_path: Path) -> None:
        """A v1 task NOT in the carveout still fails on drift (keeps verifier honest)."""

        mod = _runner()
        _write_task(
            tmp_path,
            "active",
            "newly-introduced-drifting-task",
            {
                "braid_schema": 1,
                "braid_engagement": 5,
                "braid_monetary": 5,
                "braid_research": 5,
                "braid_tree_effect": 5,
                "braid_evidence_confidence": 5,
                "braid_risk_penalty": 0.0,
                "braid_score": 99.0,
            },
        )
        exit_code, lines = mod._verify_v1_stability(task_root=tmp_path, tolerance=0.1)
        assert exit_code == 1
        assert any("newly-introduced-drifting-task" in line for line in lines)


# ── SPEC_AUTO_GTM_PREDICTIONS pin ──────────────────────────────────────


class TestSpecPredictionsPin:
    def test_seven_tasks_pinned(self) -> None:
        mod = _runner()
        assert len(mod.SPEC_AUTO_GTM_PREDICTIONS) == 7
        # Sanity: each entry is a non-zero float.
        for task_id, predicted in mod.SPEC_AUTO_GTM_PREDICTIONS.items():
            assert isinstance(predicted, float) and predicted > 0, (
                f"{task_id} prediction must be positive float"
            )

    def test_predictions_match_canonical_v11_outputs(self) -> None:
        """Spec table = formula outputs for the seven Auto-GTM tasks.

        Locks the contract resolved by cc-task
        ``braid-v11-spec-doc-and-prediction-reconcile`` (2026-05-02): the
        prediction table is canonical only when each entry equals what the
        v1.1 formula produces from the task's frontmatter dimensions. If
        the operator revises a frontmatter dimension, the spec table must
        be updated in lockstep — or the verifier will fail.
        """

        mod = _runner()
        # Snapshot the seven canonical predictions from the spec doc
        # §Predicted re-ranking table.
        expected = {
            "wyoming-llc-dba-legal-entity-bootstrap": 6.28,
            "citable-nexus-front-door-static-site": 6.88,
            "publication-bus-monetization-rails-surfaces": 5.70,
            "immediate-q2-2026-grant-submission-batch": 5.85,
            "refusal-brief-article-50-case-study": 7.50,
            "eu-ai-act-art-50-c2pa-watermark-fingerprint-mvp": 5.97,
            "auto-clip-shorts-livestream-pipeline": 5.03,
        }
        assert expected == mod.SPEC_AUTO_GTM_PREDICTIONS


class TestV1StabilityCarveoutPin:
    def test_carveout_is_frozenset(self) -> None:
        """Carveout is immutable at module level — no dynamic mutation."""

        mod = _runner()
        assert isinstance(mod.BRAID_V1_STABILITY_CARVEOUT, frozenset)

    def test_carveout_membership_pin(self) -> None:
        """Pin the 28 carveout entries from the 2026-05-02 reconcile snapshot.

        Adding a new v1 task that drifts after this date should fail the
        verifier rather than be auto-carved-out. Removing an entry
        requires the operator to either (a) revise the declared score to
        match formula or (b) document why the carveout is no longer
        needed.
        """

        mod = _runner()
        assert len(mod.BRAID_V1_STABILITY_CARVEOUT) == 28
        # Sanity: a few canonical members from the 2026-05-02 snapshot.
        assert "gcp-youtube-quota-extension-runner" in mod.BRAID_V1_STABILITY_CARVEOUT
        assert "braided-value-formal-model-and-wsjf-calibration" in mod.BRAID_V1_STABILITY_CARVEOUT
        assert "playwright-grant-submission-runner" in mod.BRAID_V1_STABILITY_CARVEOUT


# ── CLI integration ────────────────────────────────────────────────────


class TestCliIntegration:
    def test_main_flag_exits_nonzero_on_drift(self, tmp_path: Path) -> None:
        mod = _runner()
        # No Auto-GTM tasks → all FAIL → exit 1.
        rc = mod.main(
            [
                "--task-root",
                str(tmp_path),
                "--verify-auto-gtm-predictions",
                "--now",
                "2026-05-01T00:00:00Z",
            ]
        )
        assert rc == 1

    def test_main_v1_stability_exits_zero_on_clean_vault(self, tmp_path: Path) -> None:
        mod = _runner()
        rc = mod.main(["--task-root", str(tmp_path), "--verify-v1-stability"])
        assert rc == 0
