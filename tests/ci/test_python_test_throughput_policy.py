from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / ".github/workflows/ci.yml"
EVIDENCE = REPO_ROOT / "config/ci/python-test-throughput-evidence.yaml"
RUNTIME_WEIGHTS = REPO_ROOT / "config/ci/python-test-runtime-weights.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        loaded = yaml.safe_load(fh)
    assert isinstance(loaded, dict)
    return loaded


def _workflow_job_block(workflow_text: str, job_name: str) -> str:
    match = re.search(
        rf"\n  {re.escape(job_name)}:\n(?P<body>.*?)(?=\n  [A-Za-z0-9_-]+:\n|\Z)",
        workflow_text,
        re.DOTALL,
    )
    assert match is not None, f"missing workflow job {job_name}"
    return match.group(0)


def test_required_test_check_keeps_full_pytest_on_merge_queue_and_main() -> None:
    ci_text = CI_WORKFLOW.read_text(encoding="utf-8")
    test_block = _workflow_job_block(ci_text, "test")
    shard_block = _workflow_job_block(ci_text, "test-full-shard")
    title_card_block = _workflow_job_block(ci_text, "test-title-cards")

    assert "merge_group:" in ci_text
    assert "push:" in ci_text
    assert "branches: [main]" in ci_text
    assert (
        "needs: [docs_only_filter, post_merge_duplicate_filter, test-full-shard, "
        "test-title-cards]" in test_block
    )
    assert "if: always()" in test_block
    assert "Determine Python test mode" in test_block
    assert 'if [ "$GITHUB_EVENT_NAME" = "pull_request" ]; then' in test_block
    assert 'elif [ "$GITHUB_EVENT_NAME" = "merge_group" ]; then' in test_block
    assert 'echo "mode=merge-group-shards" >> "$GITHUB_OUTPUT"' in test_block
    assert 'echo "mode=full" >> "$GITHUB_OUTPUT"' in test_block
    assert "Verify merge-queue full pytest shards" in test_block
    assert "needs.test-full-shard.result" in test_block
    assert "needs.test-title-cards.result" in test_block
    assert "Serial title-card result" in test_block
    assert "steps.test_mode.outputs.mode == 'full'" in test_block
    assert "timeout -s KILL 1200" in test_block
    assert "uv sync --extra ci --frozen" in test_block
    assert (
        'uv run --no-sync python scripts/ci_verify_pango_font.py "Px437 IBM VGA 8x16"' in test_block
    )
    assert "uv run --no-sync pytest tests/ -q --tb=line --durations=25" in test_block
    assert "--ignore=tests/test_demo_title_cards.py" in test_block
    assert "--ignore=tests/test_demo_video_integration.py" in test_block
    assert "Run serial title-card tests" in test_block
    assert "tests/test_demo_video_integration.py" in test_block

    assert "github.event_name == 'merge_group'" in shard_block
    assert "strategy:" in shard_block
    assert "shard: [1, 2, 3, 4]" in shard_block
    assert "shard_count: [4]" in shard_block
    assert "Run full pytest shard" in shard_block
    assert "--collect-only -q" in shard_block
    assert "scripts/ci_select_pytest_shard.py" in shard_block
    assert "config/ci/python-test-runtime-weights.yaml" in shard_block
    assert "uv sync --extra ci --frozen" in shard_block
    assert "uv run --no-sync pytest tests/ --collect-only -q" in shard_block
    assert "uv run --no-sync python scripts/ci_select_pytest_shard.py" in shard_block
    assert "selected $unit_count test units" in shard_block
    assert "xargs -d '\\n' -a \"$shard_files\" uv run --no-sync pytest -q --tb=line" in shard_block
    assert "--durations=0 --durations-min=0" in shard_block
    assert "--pytest-output /tmp/pytest-output.txt" in shard_block
    assert '--duration-artifact "$duration_artifact"' in shard_block
    assert "--require-durations" in shard_block
    assert "Upload pytest node duration artifacts" in shard_block
    assert "actions/upload-artifact@v7" in shard_block
    assert "pytest-node-durations-shard-${{ matrix.shard }}-of-${{ matrix.shard_count }}" in (
        shard_block
    )
    assert "--ignore=tests/test_demo_title_cards.py" in shard_block
    assert "--ignore=tests/test_demo_video_integration.py" in shard_block

    assert "github.event_name == 'merge_group'" in title_card_block
    assert "Install system deps for serial title-card tests" in title_card_block
    assert (
        "sudo apt-get install -y libcairo2-dev libgirepository-2.0-dev gobject-introspection"
    ) in title_card_block
    assert "uv sync --extra ci --frozen" in title_card_block
    assert "uv run --no-sync pytest" in title_card_block
    assert "tests/test_demo_title_cards.py" in title_card_block
    assert "tests/test_demo_video_integration.py" in title_card_block


def test_pull_request_test_job_uses_fast_admission_slice_without_self_hosted() -> None:
    ci_text = CI_WORKFLOW.read_text(encoding="utf-8")
    test_block = _workflow_job_block(ci_text, "test")

    assert "self-hosted" not in ci_text
    assert "Run PR Python admission slice" in test_block
    assert "steps.test_mode.outputs.mode == 'pr-admission'" in test_block
    assert "PYTHONPATH: ${{ github.workspace }}" in test_block
    assert "uv run --no-project --with pytest==9.0.2 --with pyyaml pytest" in test_block
    assert "--confcutdir=tests" in test_block
    assert "uv sync --extra ci --group dev" not in test_block
    assert "tests/ci/test_self_hosted_runner_experiment.py" in test_block
    assert "tests/ci/test_python_test_throughput_policy.py" in test_block
    assert "tests/test_ci_required_coverage_claims.py" in test_block
    assert "tests/shared/test_ci_discovery.py" in test_block


def test_python_test_throughput_evidence_records_gated_decision() -> None:
    evidence = _load_yaml(EVIDENCE)

    assert evidence["task_id"] == "ci-python-test-throughput-evidence-gate"
    assert evidence["decision"] == "fast_pr_admission_slice_and_merge_queue_shards"
    assert evidence["self_hosted_comparison"]["required_test_adoption"] == "defer"
    assert evidence["self_hosted_comparison"]["observed_manual_runs"] == 0
    assert evidence["rollout_policy"]["pull_request"] == "pr_admission_slice"
    assert evidence["rollout_policy"]["merge_group"] == "full_pytest_sharded"
    assert evidence["rollout_policy"]["merge_group_shards"] == 4
    assert (
        evidence["rollout_policy"]["merge_group_shard_selector"]
        == "scripts/ci_select_pytest_shard.py"
    )
    assert (
        evidence["rollout_policy"]["merge_group_shard_unit"]
        == "file_or_configured_pytest_node_prefix"
    )
    assert (
        evidence["rollout_policy"]["runtime_weight_source"]
        == "config/ci/python-test-runtime-weights.yaml"
    )
    assert (
        evidence["rollout_policy"]["merge_group_duration_artifact"]
        == "pytest-node-durations-shard-N-of-4"
    )
    assert (
        evidence["rollout_policy"]["merge_group_duration_artifact_schema"]
        == "pytest_node_durations/v1"
    )
    assert evidence["rollout_policy"]["merge_group_uv_policy"] == "frozen_sync_then_no_sync_run"
    assert evidence["rollout_policy"]["push_main"] == "full_pytest"
    assert (
        evidence["rollout_policy"]["workflow_level_path_filters_for_required_check"] == "forbidden"
    )
    assert evidence["parity_status"]["self_hosted_vs_hosted"] == "unavailable_no_self_hosted_runs"


def test_python_runtime_weights_record_merge_queue_evidence() -> None:
    weights = _load_yaml(RUNTIME_WEIGHTS)

    assert weights["task_id"] == "ci-merge-queue-runtime-weighted-pytest-shards-20260518"
    assert weights["weight_units"] == "collected_test_equivalent"
    assert weights["unknown_file_fallback"] == "collected_test_count"
    assert weights["assignment_policy"]["selector"] == "scripts/ci_select_pytest_shard.py"
    assert weights["assignment_policy"]["unit"] == "file_or_configured_pytest_node_prefix"
    assert weights["assignment_policy"]["partially_split_file_fallback"] == "exact_collected_nodeid"
    first_pass_evidence = weights["evidence"][0]
    assert first_pass_evidence["pr"] == 3444
    assert first_pass_evidence["run_id"] == 26035987726
    assert first_pass_evidence["shard_pytest_seconds"] == {
        "1": 246.32,
        "2": 250.29,
        "3": 236.20,
        "4": 884.43,
    }
    recent_evidence = {item["run_id"]: item for item in weights["evidence"]}
    assert recent_evidence[26059880890]["shard_pytest_seconds"] == {
        "1": 801.17,
        "2": 197.01,
        "3": 290.09,
        "4": 279.82,
    }
    assert recent_evidence[26060944340]["shard_pytest_seconds"] == {
        "1": 799.43,
        "2": 253.82,
        "3": 265.32,
        "4": 258.48,
    }
    assert recent_evidence[26065012238]["shard_pytest_seconds"] == {
        "1": 221.25,
        "2": 265.57,
        "3": 263.52,
        "4": 415.06,
    }
    predictions = weights["prediction_receipts"]
    assert predictions["before_refresh"]["predicted_shard_weights"] == {
        "1": 11587,
        "2": 11586,
        "3": 11586,
        "4": 11586,
    }
    assert predictions["after_refresh"]["predicted_shard_weights"] == {
        "1": 13831,
        "2": 13830,
        "3": 13830,
        "4": 13830,
    }
    split_groups = weights["split_groups"]
    assert (
        split_groups[
            "tests/studio_compositor/test_compositor_wiring.py::TestStudioCompositorBudgetWiring"
        ]["collected_test_equivalent_weight"]
        == 4200
    )
    assert (
        split_groups["tests/studio_compositor/test_compositor_wiring.py::TestFeatureProbeLog"][
            "collected_test_equivalent_weight"
        ]
        == 1800
    )
    assert (
        split_groups[
            "tests/scripts/test_post_merge_smoke.py::"
            "TestM8MidiClockPeerGate::test_skips_when_m8_absent"
        ]["collected_test_equivalent_weight"]
        == 2800
    )
    assert (
        split_groups[
            "tests/studio_compositor/test_preset_family_selector_deprecation.py::"
            "TestPresetFamilySelectorDeprecation::test_no_new_importers"
        ]["collected_test_equivalent_weight"]
        == 3200
    )
    slow_file = weights["files"]["tests/studio_compositor/test_compositor_wiring.py"]
    assert slow_file["collected_test_equivalent_weight"] == 9000
    assert slow_file["evidence"]["top_25_duration_seconds_for_file"] == 192.90
