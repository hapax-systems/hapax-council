"""Regression tests for the ``authority-case-check.yml`` PR-body parse step.

Guards the SIGPIPE hardening from task
``reform-fix-authority-case-check-sigpipe-20260601`` (AuthorityCase
CASE-SDLC-REFORM-001).

The original parse step extracted ids with ``grep -oiE 'PATTERN' | head -1``
under ``set -euo pipefail``. When ``grep``'s ``-o`` output exceeds its stdio
buffer (~4 KiB) it flushes in pieces; ``head -1`` closes the pipe after the
first line, so ``grep``'s next write takes SIGPIPE -> exit 141 -> ``pipefail``
+ ``set -e`` -> the whole step exits 1. This deterministically red-blocked any
methodology PR whose body was long enough to carry that many matches.

These tests execute the *actual* ``run:`` script lifted from the workflow YAML
(so they track CI, not a copy) against crafted PR bodies and assert the step
exits 0 with the ids correctly extracted.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "authority-case-check.yml"


def _parse_step_script() -> str:
    """Return the shell of the ``id: parse`` step, exactly as CI runs it."""
    data = yaml.safe_load(WORKFLOW.read_text())
    steps = data["jobs"]["authority-case-check"]["steps"]
    for step in steps:
        if step.get("id") == "parse":
            return step["run"]
    raise AssertionError("step with id 'parse' not found in authority-case-check.yml")


def _run_parse(pr_body: str) -> tuple[int, dict[str, str]]:
    """Run the parse step against ``pr_body``; return (exit_code, GITHUB_OUTPUT dict).

    Replicates the CI contract: ``PR_BODY`` and ``GITHUB_OUTPUT`` are the only
    inputs the script consumes. Every emitted line must be a well-formed
    ``key=value`` (a stray bare line means a multiline value corrupted
    GITHUB_OUTPUT -- the regression we are guarding against).
    """
    script = _parse_step_script()
    fd, out_path = tempfile.mkstemp(suffix=".github_output")
    os.close(fd)
    try:
        proc = subprocess.run(
            ["bash", "-c", script],
            env={**os.environ, "PR_BODY": pr_body, "GITHUB_OUTPUT": out_path},
            capture_output=True,
            text=True,
        )
        outputs: dict[str, str] = {}
        for line in Path(out_path).read_text().splitlines():
            if line == "":
                continue
            assert "=" in line, (
                f"malformed GITHUB_OUTPUT line {line!r} "
                f"(multiline value escaped into the output?)\nstderr: {proc.stderr}"
            )
            key, _, value = line.partition("=")
            outputs[key] = value
        return proc.returncode, outputs
    finally:
        Path(out_path).unlink(missing_ok=True)


def _long_filler(approx_bytes: int) -> str:
    line = "- methodology prose: lorem ipsum dolor sit amet consectetur adipiscing elit.\n"
    return line * (approx_bytes // len(line) + 1)


def test_long_body_single_early_ref_parses() -> None:
    """AC: a >2 KiB body with one early CASE-/cc-task ref parses to exit 0."""
    body = (
        "## Summary\n"
        "AuthorityCase: CASE-SDLC-REFORM-001\n"
        "cc-task: `reform-fix-authority-case-check-sigpipe-20260601`\n\n" + _long_filler(3000)
    )
    assert len(body) > 2048
    code, out = _run_parse(body)
    assert code == 0, "parse step must not red-block a long body"
    assert out["case_id"] == "CASE-SDLC-REFORM-001"
    assert out["cc_task"] == "reform-fix-authority-case-check-sigpipe-20260601"
    assert out["pre_methodology"] == "false"


def test_many_match_long_body_does_not_sigpipe() -> None:
    """The deterministic trigger: enough matches to overflow grep's stdio buffer.

    Pre-fix (``grep -oiE ... | head -1``) this body exits 141 -> step fails.
    Post-fix (``grep -m1`` stops after the first matching line) it exits 0 and
    still yields the first match.
    """
    lines = ["AuthorityCase: CASE-SDLC-REFORM-001", ""]
    for i in range(600):
        lines.append(f"see CASE-OTHER-{i:04d} and CASE-EXTRA-{i:04d} for prior context")
    body = "\n".join(lines)
    assert len(body) > 2048
    code, out = _run_parse(body)
    assert code == 0, "many-match body must not SIGPIPE the parse step"
    assert out["case_id"] == "CASE-SDLC-REFORM-001"


def test_same_line_multi_match_yields_single_id() -> None:
    """Two refs on one line must not collapse into a multiline id.

    ``grep -m1`` stops after the first matching *line*, but ``-o`` still emits
    every match on that line; without a first-match trim the id would carry an
    embedded newline and corrupt GITHUB_OUTPUT.
    """
    body = "supersedes CASE-OLD-001, now tracked under CASE-NEW-002 going forward\n"
    code, out = _run_parse(body)
    assert code == 0
    assert "\n" not in out["case_id"]
    assert out["case_id"] == "CASE-OLD-001"


def test_no_reference_body_parses_clean() -> None:
    """No ref of any kind: exit 0 (no-match must not trip ``set -e``), ids empty."""
    code, out = _run_parse("just a routine change with no governance reference\n")
    assert code == 0
    assert out["case_id"] == ""
    assert out["slice_id"] == ""
    assert out["cc_task"] == ""
    assert out["pre_methodology"] == "false"


def test_slice_and_pre_methodology_detected() -> None:
    body = "Refs SLICE-REFORM-007 under pre-methodology migration compat.\n" + _long_filler(2500)
    code, out = _run_parse(body)
    assert code == 0
    assert out["slice_id"] == "SLICE-REFORM-007"
    assert out["pre_methodology"] == "true"


def test_legacy_cc_task_only() -> None:
    body = "cc-task: `reform-some-legacy-task-20260601` with no AuthorityCase.\n"
    code, out = _run_parse(body)
    assert code == 0
    assert out["case_id"] == ""
    assert out["cc_task"] == "reform-some-legacy-task-20260601"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
