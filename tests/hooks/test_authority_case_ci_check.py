"""Tests for AuthorityCase CI check parsing logic.

Validates the PR body parsing that the authority-case-check.yml workflow
performs: case ID extraction, slice ID extraction, pre-methodology
detection, legacy cc-task detection, and protected path identification.
"""

from __future__ import annotations

import re


def _parse_case_ref(pr_body: str) -> dict[str, str | bool]:
    """Replicate the parsing logic from authority-case-check.yml."""
    case_id = ""
    m = re.search(r"CASE-[A-Z0-9-]+", pr_body, re.IGNORECASE)
    if m:
        case_id = m.group(0)

    slice_id = ""
    m = re.search(r"SLICE-[A-Z0-9-]+", pr_body, re.IGNORECASE)
    if m:
        slice_id = m.group(0)

    pre_methodology = bool(re.search(r"pre-methodology|pre_methodology", pr_body, re.IGNORECASE))

    cc_task = ""
    m = re.search(r"cc-task:\s*`?([a-z0-9-]+)", pr_body, re.IGNORECASE)
    if m:
        cc_task = m.group(1)

    return {
        "case_id": case_id,
        "slice_id": slice_id,
        "pre_methodology": pre_methodology,
        "cc_task": cc_task,
    }


def _check_protected_paths(changed_files: list[str]) -> list[str]:
    """Replicate the protected path check from authority-case-check.yml."""
    protected = []
    for f in changed_files:
        if (
            f.startswith("axioms/")
            or f.startswith("shared/governance/")
            or f in ("CODEOWNERS", ".github/CODEOWNERS")
        ):
            protected.append(f)
    return protected


class TestCaseIdParsing:
    def test_standard_case_reference(self) -> None:
        body = "**Case:** CASE-SDLC-REFORM-001\n**Slice:** SLICE-002"
        result = _parse_case_ref(body)
        assert result["case_id"] == "CASE-SDLC-REFORM-001"
        assert result["slice_id"] == "SLICE-002"

    def test_case_in_body_text(self) -> None:
        body = "Implements CASE-AUDIO-FIX-042 / SLICE-001-HOOKS"
        result = _parse_case_ref(body)
        assert result["case_id"] == "CASE-AUDIO-FIX-042"
        assert result["slice_id"] == "SLICE-001-HOOKS"

    def test_pre_methodology_marker(self) -> None:
        body = "**Case:** pre-methodology\n**Slice:** N/A"
        result = _parse_case_ref(body)
        assert result["pre_methodology"] is True
        assert result["case_id"] == ""

    def test_legacy_cc_task(self) -> None:
        body = "cc-task: `v4l2-obs-auto-reset-timeout`"
        result = _parse_case_ref(body)
        assert result["cc_task"] == "v4l2-obs-auto-reset-timeout"
        assert result["case_id"] == ""

    def test_no_reference(self) -> None:
        body = "## Summary\nFixed a bug.\n## Test plan\nManual."
        result = _parse_case_ref(body)
        assert result["case_id"] == ""
        assert result["cc_task"] == ""
        assert result["pre_methodology"] is False

    def test_both_case_and_cc_task(self) -> None:
        body = "CASE-SDLC-REFORM-001 / SLICE-004\ncc-task: `some-task`"
        result = _parse_case_ref(body)
        assert result["case_id"] == "CASE-SDLC-REFORM-001"
        assert result["cc_task"] == "some-task"


class TestProtectedPaths:
    def test_axiom_files_protected(self) -> None:
        changed = ["axioms/registry.yaml", "agents/foo.py"]
        assert _check_protected_paths(changed) == ["axioms/registry.yaml"]

    def test_governance_files_protected(self) -> None:
        changed = ["shared/governance/consent.py", "shared/config.py"]
        assert _check_protected_paths(changed) == ["shared/governance/consent.py"]

    def test_codeowners_protected(self) -> None:
        changed = ["CODEOWNERS", "README.md"]
        assert _check_protected_paths(changed) == ["CODEOWNERS"]

    def test_no_protected_paths(self) -> None:
        changed = ["agents/foo.py", "tests/test_foo.py", "scripts/bar.sh"]
        assert _check_protected_paths(changed) == []

    def test_multiple_protected(self) -> None:
        changed = ["axioms/new.yaml", "shared/governance/new.py", "CODEOWNERS"]
        assert len(_check_protected_paths(changed)) == 3
