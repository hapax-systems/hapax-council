"""Pin the CI evidence the two egress release classes rely on.

release-mitigation-gate-audio-or-live-egress-20260927: RELEASE_MITIGATION_CHECKS
names ``outbound-send-surface-scan`` for the outbound-message class, and the
estate assessment names ``passive-validator`` (audio-graph-validate.yml) for
audio-routing surfaces in the audio/live class. A name is only evidence while
the job that produces it exists under that exact check-run name, executes
rather than skipping, and triggers on the paths the gate reads. This file makes
any drift loud instead of silently holding (or silently admitting) releases.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from shared.release_gate import AUDIO_ROUTING_EVIDENCE, AUDIO_ROUTING_SURFACES
from shared.sdlc_lifecycle import RELEASE_MITIGATION_CHECKS

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
CI_YML = WORKFLOWS / "ci.yml"
AUDIO_YML = WORKFLOWS / "audio-graph-validate.yml"
SCAN_JOB = "outbound-send-surface-scan"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _on_block(doc: dict) -> dict:
    # YAML 1.1 parses the bare key `on` as boolean True; accept both spellings.
    return doc.get("on", doc.get(True, {}))


def test_the_outbound_class_names_the_scan_job() -> None:
    assert SCAN_JOB in RELEASE_MITIGATION_CHECKS["outbound_message_egress_sensitive"]


def test_scan_job_runs_the_scanner_over_the_pr_diff() -> None:
    job = _load(CI_YML)["jobs"][SCAN_JOB]
    assert "post_merge_duplicate_filter" in set(job["needs"])
    runs = [str(step.get("run", "")) for step in job["steps"]]
    assert any(
        re.search(
            r"uv run\b[^\n]*python scripts/check-outbound-send-surface-diff\.py "
            r'--base "\$base" --head "\$PR_HEAD"',
            run,
        )
        for run in runs
    ), "the scan job no longer executes the scanner over base...head"
    checkout = next(step for step in job["steps"] if "actions/checkout" in str(step.get("uses")))
    assert checkout.get("with", {}).get("fetch-depth") == 0, "the three-dot diff needs the base"


def test_scan_job_verifies_the_fallback_base_exists() -> None:
    # Follow-up item (4): with no PR base (all-zero or empty) the job falls
    # back to PR_HEAD^. That fallback must be verified as a commit before use,
    # and a missing one fails the job rather than diffing against nothing.
    job = _load(CI_YML)["jobs"][SCAN_JOB]
    run = next(
        str(s["run"])
        for s in job["steps"]
        if "check-outbound-send-surface-diff" in str(s.get("run"))
    )
    fallback = run.index('base="$PR_HEAD^"')
    verify = run.index('git cat-file -e "${base}^{commit}"')
    scan = run.index("check-outbound-send-surface-diff.py")
    assert fallback < verify < scan
    assert "exit 1" in run[verify:scan]


def test_scan_job_is_unskippable_and_names_itself() -> None:
    # all-green treats `skipped` as acceptable and this job is not in its needs,
    # so a skipped job would read as absent evidence. It must always execute: no
    # job-level `if`, no docs-only sentinel, and no `name:` override drifting the
    # check-run name away from the map's string.
    job = _load(CI_YML)["jobs"][SCAN_JOB]
    assert "if" not in job
    assert job.get("name", SCAN_JOB) == SCAN_JOB
    for step in job["steps"]:
        assert "docs_only" not in str(step.get("if", "")), step.get("name")


def test_scan_job_is_evidence_not_a_merge_gate() -> None:
    # Like secrets-scan: a finding fails only this class's evidence read, never
    # every PR's merge.
    assert SCAN_JOB not in set(_load(CI_YML)["jobs"]["all-green"]["needs"])
    assert "pull_request" in _on_block(_load(CI_YML))


def test_audio_routing_surfaces_mirror_the_audio_workflow_filter() -> None:
    # The audio evidence exists exactly where the gate requires it: the job's
    # trigger paths and the gate's audio surfaces are the same list.
    on = _on_block(_load(AUDIO_YML))
    assert tuple(on["pull_request"]["paths"]) == AUDIO_ROUTING_SURFACES
    assert tuple(on["push"]["paths"]) == AUDIO_ROUTING_SURFACES
    assert "merge_group" in on


#: Audio key files (docs/audio-topology-reference.md §8) the passive validator
#: exercises through their own unit suites. Follow-up item (5): a path joins
#: AUDIO_ROUTING_SURFACES only if the job actually executes its behaviour.
AUDIO_KEY_FILE_SUITES = {
    "shared/s4_scenes.py": "tests/shared/test_s4_scenes.py",
    "agents/faderfox_bridge.py": "tests/agents/test_faderfox_bridge.py",
}


def test_audio_key_files_are_surfaces_only_because_the_job_runs_their_suites() -> None:
    job = _load(AUDIO_YML)["jobs"][AUDIO_ROUTING_EVIDENCE]
    runs = "\n".join(str(step.get("run", "")) for step in job["steps"])
    for source, suite in AUDIO_KEY_FILE_SUITES.items():
        assert source in AUDIO_ROUTING_SURFACES, source
        assert suite in AUDIO_ROUTING_SURFACES, suite
        assert re.search(rf"uv run pytest\b[^\n]*(\\\n[^\n]*)*{re.escape(suite)}", runs), (
            f"passive-validator must execute {suite} to be evidence for {source}"
        )


def test_audio_evidence_names_a_unique_unskippable_job() -> None:
    audio = _load(AUDIO_YML)
    job = audio["jobs"][AUDIO_ROUTING_EVIDENCE]
    assert "if" not in job
    assert job.get("name", AUDIO_ROUTING_EVIDENCE) == AUDIO_ROUTING_EVIDENCE
    producers = [
        path.name
        for path in sorted(WORKFLOWS.glob("*.y*ml"))
        for key, other in (_load(path).get("jobs") or {}).items()
        if (other or {}).get("name", key) == AUDIO_ROUTING_EVIDENCE
    ]
    assert producers == ["audio-graph-validate.yml"], producers
