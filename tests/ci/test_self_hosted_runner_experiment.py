from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = REPO_ROOT / "config/ci/self-hosted-runner-experiment.yaml"
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/self-hosted-runner-experiment.yml"
DOC_PATH = REPO_ROOT / "docs/ci/self-hosted-runner-experiment.md"

REQUIRED_LABELS = {
    "self-hosted",
    "linux",
    "x64",
    "hapax-council-ci",
    "pr-safe",
    "no-secrets",
    "ephemeral-preferred",
}
FORBIDDEN_DEFAULT_EVENTS = {"pull_request", "pull_request_target", "push", "schedule"}
MAX_EXPERIMENT_TIMEOUT_MINUTES = 15


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        loaded = yaml.safe_load(fh)
    assert isinstance(loaded, dict)
    return loaded


def _workflow_on(workflow: dict[str, Any]) -> dict[str, Any]:
    # PyYAML still treats the GitHub Actions key "on" as a YAML 1.1 boolean.
    value = workflow.get("on", workflow.get(True))
    assert isinstance(value, dict)
    return value


def test_policy_declares_defer_gate_and_no_default_enrollment() -> None:
    policy = _load_yaml(POLICY_PATH)

    assert policy["status"] == "bounded_experiment"
    assert policy["current_decision"] == "defer"
    assert policy["workflow_boundary"]["default_enrollment"] == "none"
    assert policy["workflow_boundary"]["manual_dispatch_only"] is True
    assert policy["workflow_boundary"]["secrets_allowed"] is False
    assert policy["workflow_boundary"]["permissions"] == {"contents": "read"}

    gate = policy["decision_gate"]
    assert any("Three consecutive" in item for item in gate["adopt_when"])
    assert any("secrets" in item for item in gate["dismiss_when"])
    assert any("Cache/work roots" in item for item in gate["dismiss_when"])


def test_policy_limits_runner_labels_cache_paths_and_teardown() -> None:
    policy = _load_yaml(POLICY_PATH)

    assert set(policy["runner_boundary"]["required_labels"]) == REQUIRED_LABELS
    assert "secrets" in policy["runner_boundary"]["forbidden_labels"]
    assert policy["runner_boundary"]["service_user"] == "github-runner-hapax-ci"
    assert any("no pass store" in item for item in policy["runner_boundary"]["isolation"])

    cache_paths = policy["cache_paths"]
    assert cache_paths["root"] == "/var/cache/hapax/github-actions/self-hosted-runner-experiment"
    assert cache_paths["mode"] == "0700"
    assert cache_paths["retention_days"] == 7
    assert cache_paths["max_total_gib"] == 10

    teardown = policy["teardown"]
    assert teardown["reversible"] is True
    assert any("systemctl disable --now" in command for command in teardown["commands"])
    assert any("rm -rf /var/cache/hapax" in command for command in teardown["commands"])


def test_policy_allows_only_pr_safe_non_secret_experiment_jobs() -> None:
    policy = _load_yaml(POLICY_PATH)

    assert policy["workflow_boundary"]["allowed_events"] == ["workflow_dispatch"]
    assert set(policy["workflow_boundary"]["forbidden_events"]) == FORBIDDEN_DEFAULT_EVENTS

    allowed_jobs = policy["allowed_jobs"]
    assert {job["id"] for job in allowed_jobs} == {
        "boundary-smoke",
        "non-secret-static-ci-slice",
    }
    for job in allowed_jobs:
        assert job["secret_bearing"] is False
        assert job["pr_safe"] is True
        assert "secrets" not in job["command"].lower()

    excluded = {job["id"]: job["reason"] for job in policy["excluded_default_jobs"]}
    assert "ci.yml:test" in excluded
    assert "secrets-scan" in excluded
    assert "release-and-deploy-workflows" in excluded


def test_workflow_is_manual_only_read_only_and_secret_free() -> None:
    workflow = _load_yaml(WORKFLOW_PATH)
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    triggers = _workflow_on(workflow)

    assert set(triggers) == {"workflow_dispatch"}
    assert set(FORBIDDEN_DEFAULT_EVENTS).isdisjoint(triggers)
    assert workflow["permissions"] == {"contents": "read"}
    assert "secrets." not in workflow_text
    assert "pull_request_target:" not in workflow_text
    assert "\npull_request:" not in workflow_text
    assert "\npush:" not in workflow_text
    assert "\nschedule:" not in workflow_text


def test_workflow_self_hosted_job_has_static_boundary() -> None:
    workflow = _load_yaml(WORKFLOW_PATH)
    jobs = workflow["jobs"]
    assert set(jobs) == {"pr-safe-non-secret"}

    job = jobs["pr-safe-non-secret"]
    assert set(job["runs-on"]) == REQUIRED_LABELS
    assert job["timeout-minutes"] == MAX_EXPERIMENT_TIMEOUT_MINUTES
    assert job["env"]["HAPAX_CI_NO_SECRETS"] == "1"
    assert job["env"]["HAPAX_SELF_HOSTED_EXPERIMENT"] == "1"
    assert (
        job["env"]["UV_CACHE_DIR"]
        == "/var/cache/hapax/github-actions/self-hosted-runner-experiment/uv"
    )
    assert (
        job["env"]["XDG_CACHE_HOME"]
        == "/var/cache/hapax/github-actions/self-hosted-runner-experiment/xdg"
    )

    step_names = {step["name"] for step in job["steps"]}
    assert "Refuse non-manual invocation" in step_names
    assert "Verify bounded cache root" in step_names
    assert "Non-secret static CI slice" in step_names


def test_default_ci_remains_hosted_and_docs_record_the_decision_gate() -> None:
    ci_text = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    doc_text = DOC_PATH.read_text(encoding="utf-8")

    assert "self-hosted" not in ci_text
    assert "Current decision: **defer**." in doc_text
    assert "three consecutive manually dispatched runs are green" in doc_text
    assert "No existing `pull_request`, `push`, scheduled, release, deploy" in doc_text
    assert "config/ci/self-hosted-runner-experiment.yaml" in doc_text
