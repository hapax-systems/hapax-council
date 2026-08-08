"""Pin the CI composition the live-egress release mitigation relies on.

cc-task-release-arm-held-sensitive-class-20260808: the RELEASE_MITIGATION_CHECKS
entry for the audio/live-egress sensitive class names per-PR and merge-queue
checks as machine-verified evidence. Those names are only evidence while
(a) the behavioral job stays in the required aggregate's needs,
(b) the job's run step executes the egress pin file — and the file still
    CONTAINS the named pins, each carrying a substantive assertion and its
    behavior-defining symbols (structurally pinned with semantic anchors;
    semantic fidelity itself is the quorum's layer, as for every test file),
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
PROTOCOL_FILE = REPO_ROOT / "shared" / "capability_adapter_protocol.py"

#: The behavior pins the egress-boundary-pin job exists to execute, each mapped
#: to the behavior-defining symbols its body must reference (semantic anchors —
#: an `assert object()` forgery fails here). Extend deliberately: PR #4440 adds
#: the wired-send and receipt-privacy pins with their own anchors.
REQUIRED_EGRESS_PINS: dict[str, tuple[str, ...]] = {
    # authority-first: no relay execution before a LAUNCH decision
    "test_launch_raises_authority_violation_before_side_effect": ("AuthorityViolation",),
    # the send boundary asserts authority, then refuses not-yet-wired
    # (the wired-send assertions land with #4440)
    "test_send_asserts_authority_then_is_not_yet_wired": (
        "AuthorityViolation",
        "NotImplementedError",
    ),
    # send capability is type-level — never a runtime flag, never overridable
    "test_sendcapable_is_not_a_capability_adapter_subclass": ("SendCapableAdapter",),
    "test_worker_has_launch_and_sendcapable_has_send": ("hasattr", '"send"'),
    # non-send adapters carry no send surface at all
    "test_budget_authority_has_no_launch_or_send": ("BudgetAuthorityAdapter",),
    "test_review_seat_has_no_launch_or_send": ("ReviewSeatAdapter",),
}


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
    # over the pin file (not an echo or a passing mention). The job deliberately
    # carries NO docs_only conditions (asserted below); its only sentinel is the
    # duplicate-merge-group one, which reports success only when the queue
    # already validated the same SHA — deferred evidence, never skipped
    # evidence. The filter's own logic is pinned by
    # tests/test_ci_required_coverage_claims.py.
    job = _ci()["jobs"]["egress-boundary-pin"]
    assert "pull_request" in _on_block(_ci())
    assert "post_merge_duplicate_filter" in set(job["needs"])
    run_steps = [str(step.get("run", "")) for step in job["steps"]]
    assert any(
        re.search(r"uv run\b.*\bpytest\b[^\n]*tests/test_capability_adapter_protocol\.py", run)
        for run in run_steps
    ), "egress-boundary-pin no longer executes the egress pin file"


def test_egress_pin_file_still_contains_the_named_behavior_pins() -> None:
    # Structurally pinned with semantic anchors. Threat model, stated honestly:
    # this guard defeats SILENT STRUCTURAL drift — deleted functions, gutted
    # bodies, constant/assert-object forgeries, renamed symbols. It cannot
    # defeat a crafted semantically-vacuous forgery that still references the
    # anchored symbols; no static check can — semantic fidelity is the
    # quorum's layer (the same trust model every test file in this repo
    # stands on), with execution on every PR and the full suite at landing.
    tree = ast.parse(PIN_FILE.read_text(encoding="utf-8"))
    source = PIN_FILE.read_text(encoding="utf-8")
    functions = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    missing = [name for name in REQUIRED_EGRESS_PINS if name not in functions]
    assert not missing, f"egress pin file lost behavior pins: {missing}"

    def has_substantive_assertion(node: ast.AST) -> bool:
        for child in ast.walk(node):
            if isinstance(child, ast.Assert) and not isinstance(child.test, ast.Constant):
                return True
            if isinstance(child, ast.With):
                for item in child.items:
                    call = item.context_expr
                    if (
                        isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and call.func.attr == "raises"
                        and call.args
                    ):
                        return True
        return False

    failures: list[str] = []
    for name, anchors in REQUIRED_EGRESS_PINS.items():
        node = functions[name]
        if not has_substantive_assertion(node):
            failures.append(f"{name}: no substantive assertion")
            continue
        body = ast.get_source_segment(source, node) or ""
        absent = [anchor for anchor in anchors if anchor not in body]
        if absent:
            failures.append(f"{name}: lost its semantic anchors {absent}")
    assert not failures, "egress pins degraded: " + "; ".join(failures)


def test_composition_suite_itself_runs_in_the_required_full_shard() -> None:
    # This file is the evidence-integrity layer for the class; it must itself
    # execute in a required job. test-full-shard collects from the tests/ root
    # (so tests/ci/ is inside it) and is in all-green's needs — the landing
    # gate cannot pass without this suite running.
    shard_job = _ci()["jobs"]["test-full-shard"]
    run_steps = [str(step.get("run", "")) for step in shard_job["steps"]]
    assert any(re.search(r"pytest\s+tests/\s+--collect-only", run) for run in run_steps), (
        "test-full-shard no longer collects from the tests/ root — is tests/ci/ still inside?"
    )
    assert "test-full-shard" in set(_ci()["jobs"]["all-green"]["needs"])


#: The pins #4440's wired send must add to REQUIRED_EGRESS_PINS. The coupling
#: test below makes the extension machine-enforced rather than a comment
#: obligation: once send executes the relay, these names MUST be in the set.
WIRED_SEND_PINS: dict[str, tuple[str, ...]] = {
    "test_send_asserts_authority_before_any_egress_side_effect": ("AuthorityViolation",),
    "test_send_receipt_carries_no_message_body": ("message_sha256",),
    "test_send_routes_through_canonical_relay_and_mints_receipt": ("receipt",),
    "test_send_on_bare_mixin_fails_closed": ("send",),
    "test_send_cannot_be_overridden_no_boutique_paths": ("__init_subclass__",),
    "test_no_runtime_supports_send_flag_anywhere": ("supports_send",),
}


def _send_body() -> str:
    source = PROTOCOL_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "send":
            return ast.get_source_segment(source, node) or ""
    return ""


def test_pin_set_tracks_the_send_surface_state() -> None:
    # The behavioral evidence set is COUPLED to the send surface: while send is
    # the not-yet-wired refusal, the refusal pin is required and the wired pins
    # stay out; once send executes the relay (#4440), the wired-send and
    # receipt-privacy pins MUST be in the required set and the refusal pin is
    # superseded. The obligation to extend the evidence with the surface is
    # machine-enforced here, not a comment promise.
    wired = "NotImplementedError" not in _send_body()
    names = set(REQUIRED_EGRESS_PINS)
    if not wired:
        assert "test_send_asserts_authority_then_is_not_yet_wired" in names
        overlap = set(WIRED_SEND_PINS) & names
        assert not overlap, f"wired-send pins required before send is wired: {sorted(overlap)}"
    else:
        assert "test_send_asserts_authority_then_is_not_yet_wired" not in names
        missing = set(WIRED_SEND_PINS) - names
        assert not missing, f"send is wired but the required pin set lacks: {sorted(missing)}"


def test_pr_admission_slice_still_excludes_the_pin_file() -> (
    None
):  # The fact that justifies the dedicated job: if the PR admission slice ever
    # grows to include the pin file, say so deliberately (the job may then be
    # redundant), rather than letting the two drift into silent disagreement.
    test_job = _ci()["jobs"]["test"]
    run_steps = [str(step.get("run", "")) for step in test_job["steps"]]
    admission = [run for run in run_steps if "admission" in run or "--confcutdir" in run]
    assert admission, "PR admission slice step not found — has the test job changed shape?"
    assert not any("tests/test_capability_adapter_protocol.py" in run for run in admission), (
        "admission slice now runs the pin file — re-evaluate egress-boundary-pin's role"
    )


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
