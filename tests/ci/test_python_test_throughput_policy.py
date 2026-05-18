from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / ".github/workflows/ci.yml"
EVIDENCE = REPO_ROOT / "config/ci/python-test-throughput-evidence.yaml"


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

    assert "merge_group:" in ci_text
    assert "push:" in ci_text
    assert "branches: [main]" in ci_text
    assert "needs: [docs_only_filter, post_merge_duplicate_filter, test-full-shard]" in test_block
    assert "if: always()" in test_block
    assert "Determine Python test mode" in test_block
    assert 'if [ "$GITHUB_EVENT_NAME" = "pull_request" ]; then' in test_block
    assert 'elif [ "$GITHUB_EVENT_NAME" = "merge_group" ]; then' in test_block
    assert 'echo "mode=merge-group-shards" >> "$GITHUB_OUTPUT"' in test_block
    assert 'echo "mode=full" >> "$GITHUB_OUTPUT"' in test_block
    assert "Verify merge-queue full pytest shards" in test_block
    assert "needs.test-full-shard.result" in test_block
    assert "steps.test_mode.outputs.mode == 'full'" in test_block
    assert "timeout -s KILL 1200" in test_block
    assert "uv run pytest tests/ -q --tb=line --durations=25" in test_block

    assert "github.event_name == 'merge_group'" in shard_block
    assert "strategy:" in shard_block
    assert "shard: [1, 2]" in shard_block
    assert "shard_count: [2]" in shard_block
    assert "Run full pytest shard" in shard_block
    assert "--collect-only -q" in shard_block
    assert 'xargs -a "$shard_files" uv run pytest -q --tb=line --durations=25' in shard_block


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
    assert evidence["rollout_policy"]["push_main"] == "full_pytest"
    assert (
        evidence["rollout_policy"]["workflow_level_path_filters_for_required_check"] == "forbidden"
    )
    assert evidence["parity_status"]["self_hosted_vs_hosted"] == "unavailable_no_self_hosted_runs"
