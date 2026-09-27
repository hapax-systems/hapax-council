"""Pin the CI composition the provider-billing release mitigation relies on.

cc-task-provider-billing-sensitive-release-mitigation-gate-20260926: the
RELEASE_MITIGATION_CHECKS entry for the provider_billing_sensitive class names
the ``billing-surface-scan`` check as machine-verified evidence. That name is
only evidence while
(a) the job stays in ci.yml and triggers on every pull_request,
(b) the job's run step executes the diff scanner (not an echo or a mention),
(c) the job is unskippable at job level and its produced check-run name stays
    its job key — the map names it verbatim,
(d) the job carries no docs-only sentinel: the class's evidence must EXECUTE
    on every diff (the scan is seconds), and
(e) the job stays OUT of the all-green aggregate: like secrets-scan it is an
    evidence producer the autoqueue reads for one sensitivity class, not a
    universal merge blocker (a PR that legitimately adds a provider route is
    provider_spend / human-released work, never auto-armed).
If any of these facts changes, the class's evidence silently degrades — this
file makes it loud instead.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from shared.sdlc_lifecycle import RELEASE_MITIGATION_CHECKS

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"
SCANNER = REPO_ROOT / "scripts" / "check-billing-surface-diff.py"

BILLING_SCAN_CHECK = "billing-surface-scan"


def _ci() -> dict:
    return yaml.safe_load(CI_YML.read_text(encoding="utf-8"))


def _on_block(doc: dict) -> dict:
    # YAML 1.1 parses the bare key `on` as boolean True; accept both spellings.
    return doc.get("on", doc.get(True, {}))


def _job() -> dict:
    return _ci()["jobs"][BILLING_SCAN_CHECK]


def test_mitigation_map_names_the_job_and_the_job_exists() -> None:
    # The producer binding: the class's evidence tuple names the check, and the
    # check is a real ci.yml job.
    assert BILLING_SCAN_CHECK in RELEASE_MITIGATION_CHECKS["provider_billing_sensitive"]
    assert BILLING_SCAN_CHECK in _ci()["jobs"]


def test_scanner_script_exists() -> None:
    assert SCANNER.is_file()


def test_billing_surface_scan_triggers_per_pr() -> None:
    # The arm-time evidence must be produced on every PR head; without the
    # pull_request trigger the gate holds every billing-sensitive PR closed.
    assert "pull_request" in _on_block(_ci())


def test_billing_surface_scan_is_unskippable_and_names_itself() -> None:
    # all-green treats `skipped` as acceptable, so the evidence job must be
    # impossible to skip wholesale: no job-level `if`. And no `name:` override
    # may drift the produced check-run name away from the map's string.
    job = _job()
    assert "if" not in job, "billing-surface-scan must never be skippable at job level"
    assert job.get("name", BILLING_SCAN_CHECK) == BILLING_SCAN_CHECK


def test_billing_surface_scan_names_the_scanner_in_a_uv_run_step() -> None:
    """A SHAPE pin: the run step is a uv-run python invocation over the scanner script.

    It deliberately does NOT claim the scanner executes — that is
    `test_the_scanner_the_step_names_executes_and_gates` below. Named for what it proves,
    because "executes the scanner" is what this test used to be called while only grepping
    YAML (codex-1's round-6 major on #4805).
    """

    run_steps = [str(step.get("run", "")) for step in _job()["steps"]]
    joined = "\n".join(run_steps)
    assert re.search(r"uv run\b.*\bpython\b.*scripts/check-billing-surface-diff\.py", joined), (
        "billing-surface-scan no longer executes the diff scanner"
    )


def _run_step_shell() -> str:
    return "\n".join(str(step.get("run", "")) for step in _job()["steps"])


def test_the_scanner_the_step_names_executes_and_gates(tmp_path: Path) -> None:
    """codex-1's round-6 major on #4805, closed: show the scanner RUNS and gates.

    Every other test in this file pins the job's *shape*. This one executes the very tool the
    run step names — the path is taken from the step, not from this file's constants — over a
    clean diff and over the same diff with a planted credential read, and requires the exit
    codes the gate actually depends on (0 clean, 1 on a planted finding). A step naming a
    script that never ran, or a scanner that never failed, would pass every shape pin here and
    fail this one.
    """

    import subprocess
    import sys

    step = _run_step_shell()
    named = str(SCANNER.relative_to(REPO_ROOT))
    assert named in step, f"the run step does not name {named}"
    assert "uv run" in step and "--base" in step and "--head" in step, (
        "the run step no longer invokes the scanner's production entry point"
    )

    header = (
        "diff --git a/shared/foo.py b/shared/foo.py\n"
        "--- a/shared/foo.py\n"
        "+++ b/shared/foo.py\n"
        "@@ -1,0 +1,1 @@\n"
    )
    clean = tmp_path / "clean.diff"
    clean.write_text(f"{header}+x = 1\n", encoding="utf-8")
    planted = tmp_path / "planted.diff"
    planted.write_text(f'{header}+key = os.environ["OPENAI_API_KEY"]\n', encoding="utf-8")

    clean_run = subprocess.run(
        [sys.executable, str(SCANNER), "--diff-file", str(clean)],
        capture_output=True,
        text=True,
    )
    assert clean_run.returncode == 0, (
        f"the named scanner failed a clean diff: rc={clean_run.returncode} "
        f"{clean_run.stdout}{clean_run.stderr}"
    )
    planted_run = subprocess.run(
        [sys.executable, str(SCANNER), "--diff-file", str(planted)],
        capture_output=True,
        text=True,
    )
    assert planted_run.returncode == 1, (
        f"a planted billing surface did not fail the scan: rc={planted_run.returncode} "
        f"{planted_run.stdout}{planted_run.stderr}"
    )
    assert "credential-env-read" in planted_run.stdout, (
        f"the planted finding was not reported: {planted_run.stdout!r}"
    )


def test_duplicate_merge_group_success_path_is_pinned() -> None:
    """gemini's and claude's long-standing minor: the sentinel path is now pinned.

    A SHAPE pin, and named as one: it proves the sentinel step exists, is gated on the
    duplicate-merge-group output, reports the job's success, and that every other step of the
    job is skipped when that output is true — deferred evidence, never skipped evidence. It
    does not simulate the merge-group event.
    """

    steps = _job()["steps"]
    sentinel = [step for step in steps if "duplicate" in str(step.get("name", "")).lower()]
    assert len(sentinel) == 1, f"expected exactly one sentinel step, found {len(sentinel)}"
    step = sentinel[0]
    assert step.get("if") == (
        "needs.post_merge_duplicate_filter.outputs.duplicate_merge_group == 'true'"
    ), f"the sentinel step is not gated on the duplicate-merge-group output: {step.get('if')!r}"
    assert "success" in str(step.get("run", "")).lower(), (
        "the sentinel step does not report the job's success"
    )
    for other in steps:
        if other is step:
            continue
        assert str(other.get("if", "")).endswith("!= 'true'"), (
            f"step {other.get('name') or other.get('uses')!r} would run on a duplicate merge group"
        )


def test_the_base_sha_fallback_is_pinned() -> None:
    """claude's round-6 minor: the empty/zero base fallback is pinned as a SHAPE.

    The step falls back to `PR_HEAD^` when the event carries no usable base. This pins the
    shell's shape only; the shell itself is not executed here, and the test says so rather than
    leaving a reader to assume otherwise.
    """

    step = _run_step_shell()
    assert 'base="$PR_BASE"' in step, "the run step no longer reads the event base"
    assert 'if [ -z "$base" ]' in step, "the empty-base test is gone"
    assert f'"{"0" * 40}"' in step, "the all-zero base test is gone"
    assert 'base="$PR_HEAD^"' in step, "the fallback to the parent commit is gone"


def test_billing_surface_scan_never_reports_success_without_running() -> None:
    # Behavioral evidence must EXECUTE: no docs-only sentinel — a docs-only
    # classified diff still runs the scan. The duplicate-merge-group sentinel
    # stays: it means the queue already validated the SHA (deferred evidence).
    for step in _job()["steps"]:
        condition = str(step.get("if", ""))
        assert "docs_only" not in condition, (
            f"step {step.get('name')!r} gained a docs-only bypass — evidence for the "
            "provider_billing_sensitive class must always execute"
        )


def test_billing_surface_scan_stays_out_of_the_required_aggregate() -> None:
    # Evidence producer, not a universal merge blocker (secrets-scan precedent):
    # a finding fails only the evidence read for billing-sensitive classes.
    needs = set(_ci()["jobs"]["all-green"]["needs"])
    assert BILLING_SCAN_CHECK not in needs
