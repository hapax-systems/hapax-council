"""Pin the CI composition the live-egress release mitigation relies on.

cc-task-release-arm-held-sensitive-class-20260808: the RELEASE_MITIGATION_CHECKS
entry for the audio/live-egress sensitive class names per-PR and merge-queue
checks as machine-verified evidence. Those names are only evidence while
(a) the behavioral checks are real ci.yml jobs the required aggregate needs,
(b) the merge-queue full shard stays merge_group-only (so an armed PR cannot
land without the full suite, where the egress-behavior pins live), and
(c) the arm-time evidence workflows still trigger per-PR. If any of these
facts changes, the gate's evidence silently degrades — this file makes it
loud instead.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"
AUTHORITY_CASE_YML = REPO_ROOT / ".github" / "workflows" / "authority-case-check.yml"


def _ci() -> dict:
    return yaml.safe_load(CI_YML.read_text(encoding="utf-8"))


def test_all_green_aggregate_keeps_the_behavioral_and_declaration_layers() -> None:
    # all-green is the single required aggregate on main. The per-PR
    # egress-boundary-pin job (runs the egress-behavior pins in
    # tests/test_capability_adapter_protocol.py), the merge-queue
    # test-full-shard, and the capability-surface-delta declaration gate
    # must all stay in its needs.
    needs = set(_ci()["jobs"]["all-green"]["needs"])
    for job in ("egress-boundary-pin", "test-full-shard", "capability-surface-delta"):
        assert job in needs, f"all-green lost its dependency on {job}"


def test_egress_boundary_pin_job_runs_the_pin_file_per_pr() -> None:
    # The behavioral premise of the release gate: the job exists, triggers on
    # pull_request (via the workflow-level `on`), and its run step executes
    # exactly the egress-behavior pin file — not a near approximation.
    job = _ci()["jobs"]["egress-boundary-pin"]
    assert "pull_request" in _on_block(_ci())
    steps = job["steps"]
    run_steps = [str(step.get("run", "")) for step in steps]
    assert any(
        "tests/test_capability_adapter_protocol.py" in run and "pytest" in run
        for run in run_steps
    ), "egress-boundary-pin no longer runs the egress-behavior pin file"


def test_pr_admission_slice_still_excludes_the_pin_file() -> None:
    # The fact that justifies the dedicated job: if the PR admission slice ever
    # grows to include the pin file, say so deliberately (the job may then be
    # redundant), rather than letting the two drift into silent disagreement.
    test_job = _ci()["jobs"]["test"]
    run_steps = [str(step.get("run", "")) for step in test_job["steps"]]
    admission = [run for run in run_steps if "admission" in run or "--confcutdir" in run]
    assert admission, "PR admission slice step not found — has the test job changed shape?"
    assert not any(
        "tests/test_capability_adapter_protocol.py" in run for run in admission
    ), "admission slice now runs the pin file — re-evaluate egress-boundary-pin's role"


def test_full_shard_stays_merge_group_only() -> None:
    # The full suite (every egress-behavior pin) must remain merge_group-only:
    # skipped on pull_request, executed before any queued PR can land.
    condition = str(_ci()["jobs"]["test-full-shard"]["if"])
    assert "github.event_name == 'merge_group'" in condition


def _on_block(doc: dict) -> dict:
    # YAML 1.1 parses the bare key `on` as boolean True; accept both spellings.
    return doc.get("on", doc.get(True, {}))


def test_arm_time_evidence_workflows_trigger_per_pr() -> None:
    # authority-case-check is its own workflow; secrets-scan is a ci.yml job.
    # Both must keep triggering on pull_request or the arm-time evidence
    # silently stops being produced (and the gate then holds everything —
    # fail-closed — which this test makes deliberate rather than accidental).
    authority = yaml.safe_load(AUTHORITY_CASE_YML.read_text(encoding="utf-8"))
    assert "pull_request" in _on_block(authority)
    assert "secrets-scan" in _ci()["jobs"]
    assert "pull_request" in _on_block(_ci())
