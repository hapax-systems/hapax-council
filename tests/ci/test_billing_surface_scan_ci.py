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


def test_billing_surface_scan_executes_the_scanner() -> None:
    # Anchored command shape: the run step must be a uv-run python invocation
    # over the scanner script.
    run_steps = [str(step.get("run", "")) for step in _job()["steps"]]
    joined = "\n".join(run_steps)
    assert re.search(r"uv run\b.*\bpython\b.*scripts/check-billing-surface-diff\.py", joined), (
        "billing-surface-scan no longer executes the diff scanner"
    )


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
