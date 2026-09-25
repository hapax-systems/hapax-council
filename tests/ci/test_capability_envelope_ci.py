"""The capability envelope's containment and canary tests run in required CI, and cannot pass by
skipping.

Review of #4784 (2026-09-25): the containment tests skipped on the stated CI, so the canary refusals
had only vault transcripts as witness. The job capability-envelope-containment installs
bubblewrap, lifts the runner's AppArmor user-namespace restriction, and runs the suite with
HAPAX_ENVELOPE_REQUIRE_BWRAP=1, under which a sandbox that cannot be built fails the tests.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"
JOB = "capability-envelope-containment"


def _jobs() -> dict:
    return yaml.safe_load(CI_YML.read_text(encoding="utf-8"))["jobs"]


def _run_text(job: dict) -> str:
    return "\n".join(str(step.get("run", "")) for step in job["steps"])


def test_the_containment_job_is_required_through_all_green():
    jobs = _jobs()
    assert JOB in jobs
    assert JOB in set(jobs["all-green"]["needs"])


def test_the_containment_job_installs_bubblewrap_and_allows_user_namespaces():
    text = _run_text(_jobs()[JOB])
    assert "apt-get install" in text and "bubblewrap" in text
    assert "kernel.apparmor_restrict_unprivileged_userns=0" in text


def test_the_containment_job_runs_the_envelope_suite_with_skips_forbidden():
    job = _jobs()[JOB]
    runs = [s for s in job["steps"] if "tests/capability_envelope" in str(s.get("run", ""))]
    assert runs, "the job must run tests/capability_envelope"
    for step in runs:
        assert step.get("env", {}).get("HAPAX_ENVELOPE_REQUIRE_BWRAP") == "1"
