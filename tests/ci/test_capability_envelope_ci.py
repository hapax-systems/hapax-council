"""The capability envelope's containment and canary tests run in required CI, and cannot pass by
skipping.

Review of #4784 (2026-09-25): the containment tests skipped on the stated CI, so the canary refusals
had only vault transcripts as witness. The job capability-envelope-containment installs
bubblewrap, lifts the runner's AppArmor user-namespace restriction, and runs the suite with
HAPAX_ENVELOPE_REQUIRE_BWRAP=1, under which a sandbox that cannot be built fails the tests.

Review of #4784 (glm-1, 2026-09-28): these pins matched substrings, so a step could keep the
substring while losing the guarantee. Each step is now pinned by its EXACT run text and its exact
env, plus the guard that no other step runs the suite without the variable.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"
JOB = "capability-envelope-containment"
GATED = "needs.post_merge_duplicate_filter.outputs.duplicate_merge_group != 'true'"
ENVELOPE_ENV = {"HAPAX_ENVELOPE_REQUIRE_BWRAP": "1"}
INSTALL_RUN = (
    "sudo apt-get update -qq\n"
    "sudo apt-get install -y -qq bubblewrap\n"
    "sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0\n"
    "bwrap --version\n"
)
_CI_RUN = "uv run --no-project --with pytest==9.0.2 --with pyyaml --with pydantic "
SUITE_RUN = _CI_RUN + "pytest --confcutdir=tests tests/capability_envelope -q --tb=short -rs\n"
MUTATION_RUN = _CI_RUN + "python scripts/capability-envelope-mutation-check\n"


def _jobs() -> dict:
    return yaml.safe_load(CI_YML.read_text(encoding="utf-8"))["jobs"]


def _step_with_run(job: dict, run: str) -> dict:
    """The one step whose run text is EXACTLY ``run`` (equality, never a substring)."""
    matches = [s for s in job["steps"] if s.get("run") == run]
    assert len(matches) == 1, f"expected exactly one step running {run!r}, got {len(matches)}"
    return matches[0]


def test_the_containment_job_is_required_through_all_green():
    jobs = _jobs()
    assert JOB in jobs
    assert JOB in set(jobs["all-green"]["needs"])


def test_the_containment_job_installs_bubblewrap_and_allows_user_namespaces():
    step = _step_with_run(_jobs()[JOB], INSTALL_RUN)
    assert step.get("if") == GATED


def test_the_containment_job_runs_the_envelope_suite_with_skips_forbidden():
    step = _step_with_run(_jobs()[JOB], SUITE_RUN)
    assert step.get("env") == ENVELOPE_ENV
    assert step.get("if") == GATED


def test_the_containment_job_runs_the_mutation_check_with_skips_forbidden():
    """Review of #4784 (muse-1): the mutation red/green proof must run from the repo, not live
    only in vault transcripts."""
    step = _step_with_run(_jobs()[JOB], MUTATION_RUN)
    assert step.get("env") == ENVELOPE_ENV
    assert step.get("if") == GATED


def test_no_other_step_runs_the_envelope_suite_without_forbidding_skips():
    """Guard beside the exact pins: if a later edit adds a second way to run the suite, it must
    carry the variable too."""
    job = _jobs()[JOB]
    for step in job["steps"]:
        run = str(step.get("run") or "")
        if "tests/capability_envelope" not in run:
            continue
        assert step.get("env", {}).get("HAPAX_ENVELOPE_REQUIRE_BWRAP") == "1", run
