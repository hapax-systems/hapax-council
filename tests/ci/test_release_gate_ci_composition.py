"""Pin the CI composition the live-egress release mitigation relies on.

cc-task-release-arm-held-sensitive-class-20260808: the RELEASE_MITIGATION_CHECKS
entry for the audio/live-egress sensitive class names per-PR and merge-queue
checks as machine-verified evidence. Those names are only evidence while
(a) the behavioral job stays in the required aggregate's needs,
(b) the job's run step executes the egress pin file — and the file still
    CONTAINS the named behavior pins (content-addressed, not name-addressed),
(c) the merge-queue full shard stays merge_group-only (so an armed PR cannot
    land without the full suite), and
(d) the arm-time evidence workflows keep their per-PR triggers.
If any of these facts changes, the gate's evidence silently degrades — this
file makes it loud instead.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"
AUTHORITY_CASE_YML = REPO_ROOT / ".github" / "workflows" / "authority-case-check.yml"
PIN_FILE = REPO_ROOT / "tests" / "test_capability_adapter_protocol.py"

#: The behavior pins the egress-boundary-pin job exists to execute. Extend
#: deliberately: PR #4440 adds the wired-send and receipt-privacy pins.
REQUIRED_EGRESS_PINS = (
    # authority-first: no relay execution before a LAUNCH decision
    "test_launch_raises_authority_violation_before_side_effect",
    # the send boundary asserts authority (refuses not-yet-wired at main;
    # the wired-send assertions land with #4440)
    "test_send_asserts_authority_then_is_not_yet_wired",
    # send capability is type-level — never a runtime flag, never overridable
    "test_sendcapable_is_not_a_capability_adapter_subclass",
    "test_worker_has_launch_and_sendcapable_has_send",
    # non-send adapters carry no send surface at all
    "test_budget_authority_has_no_launch_or_send",
    "test_review_seat_has_no_launch_or_send",
)


def _ci() -> dict:
    return yaml.safe_load(CI_YML.read_text(encoding="utf-8"))


def _on_block(doc: dict) -> dict:
    # YAML 1.1 parses the bare key `on` as boolean True; accept both spellings.
    return doc.get("on", doc.get(True, {}))


def test_all_green_aggregate_keeps_the_behavioral_and_declaration_layers() -> None:
    # all-green is the single required aggregate on main. The per-PR
    # egress-boundary-pin job, the merge-queue test-full-shard, and the
    # capability-surface-delta declaration gate must all stay in its needs.
    needs = set(_ci()["jobs"]["all-green"]["needs"])
    for job in ("egress-boundary-pin", "test-full-shard", "capability-surface-delta"):
        assert job in needs, f"all-green lost its dependency on {job}"


def test_egress_boundary_pin_job_executes_the_pin_file_per_pr() -> None:
    # Anchored command shape: the run step must be a uv-run pytest invocation
    # over the pin file (not an echo or a passing mention), and the job must
    # keep its docs_only_filter wiring (the sentinel the sibling jobs share;
    # the filter itself is pinned by tests/test_ci_required_coverage_claims.py).
    job = _ci()["jobs"]["egress-boundary-pin"]
    assert "pull_request" in _on_block(_ci())
    assert "post_merge_duplicate_filter" in set(job["needs"])
    run_steps = [str(step.get("run", "")) for step in job["steps"]]
    assert any(
        re.search(
            r"uv run\b.*\bpytest\b[^\n]*tests/test_capability_adapter_protocol\.py", run
        )
        for run in run_steps
    ), "egress-boundary-pin no longer executes the egress pin file"


def test_egress_pin_file_still_contains_the_named_behavior_pins() -> None:
    # Content-addressed, not name-addressed: the job is behavioral evidence
    # only while the file it runs actually contains these pins.
    tree = ast.parse(PIN_FILE.read_text(encoding="utf-8"))
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    missing = [name for name in REQUIRED_EGRESS_PINS if name not in defined]
    assert not missing, f"egress pin file lost behavior pins: {missing}"


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


def test_egress_boundary_pin_never_reports_success_without_running() -> None:
    # Behavioral evidence must EXECUTE: unlike sibling jobs, this job carries
    # no docs-only sentinel — a docs-only-classified diff still runs the pins
    # (~40s; the class's evidence may never be vacuous). The duplicate
    # merge-group sentinel stays: it means the queue already validated the SHA.
    job = _ci()["jobs"]["egress-boundary-pin"]
    for step in job["steps"]:
        condition = str(step.get("if", ""))
        assert "docs_only" not in condition, (
            f"step {step.get('name')!r} gained a docs-only bypass — behavioral evidence "
            "for the egress class must always execute"
        )


def test_full_shard_stays_merge_group_only() -> None:
    # The full suite (every egress-behavior pin) must remain merge_group-only:
    # skipped on pull_request, executed before any queued PR can land.
    condition = str(_ci()["jobs"]["test-full-shard"]["if"])
    assert "github.event_name == 'merge_group'" in condition


def test_arm_time_evidence_workflows_trigger_per_pr() -> None:
    # authority-case-check is its own workflow; secrets-scan is a ci.yml job.
    # Both must keep triggering on pull_request or the arm-time evidence
    # silently stops being produced (and the gate then holds everything —
    # fail-closed — which this test makes deliberate rather than accidental).
    authority = yaml.safe_load(AUTHORITY_CASE_YML.read_text(encoding="utf-8"))
    assert "pull_request" in _on_block(authority)
    assert "secrets-scan" in _ci()["jobs"]
    assert "pull_request" in _on_block(_ci())
