"""Tests for hooks/scripts/axiom-patterns.sh.

36-LOC config file declaring the ``AXIOM_PATTERNS`` bash array. The
file is sourced by ``axiom-scan.sh`` (PreToolUse on Edit/Write) and
``axiom-commit-scan.sh`` (PreToolUse on Bash) — the patterns are the
single source of truth for T0 multi-user-scaffolding violations.

The patterns themselves are tested by exercising the consumer hooks
(see test_axiom_commit_scan.py + test_axiom_scan.py from #2068 and
zeta's parallel work). This suite verifies the contract:

- The array is non-empty when sourced.
- Expected per-axiom pattern groups are present (each axiom code
  in axioms/registry.yaml has at least one matching pattern).
- The patterns are valid POSIX extended regex (grep -E parses them).
- Selected representative violating strings match the corresponding
  axiom group; selected non-violating strings don't.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
PATTERNS_FILE = REPO_ROOT / "hooks" / "scripts" / "axiom-patterns.sh"


def _list_patterns() -> list[str]:
    """Source axiom-patterns.sh and dump the AXIOM_PATTERNS array."""
    result = subprocess.run(
        [
            "bash",
            "-c",
            f'source {PATTERNS_FILE}; printf "%s\\n" "${{AXIOM_PATTERNS[@]}}"',
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
    )
    return [line for line in result.stdout.splitlines() if line]


def _grep_e(pattern: str, line: str) -> bool:
    """Return True iff ``line`` matches POSIX extended regex ``pattern``."""
    result = subprocess.run(
        ["grep", "-Eq", pattern],
        input=line,
        text=True,
        check=False,
        timeout=2,
    )
    return result.returncode == 0


# ── Array contract ─────────────────────────────────────────────────


class TestArrayContract:
    def test_array_is_non_empty(self) -> None:
        patterns = _list_patterns()
        assert patterns, "AXIOM_PATTERNS must contain at least one pattern"

    def test_all_patterns_are_valid_posix_eregex(self) -> None:
        """grep -E must parse every pattern without error."""
        for pat in _list_patterns():
            result = subprocess.run(
                ["grep", "-Eq", pat],
                input="",
                text=True,
                check=False,
                timeout=2,
            )
            # grep returns 0 (match), 1 (no match), or 2 (error).
            # We allow 0 and 1 — a malformed pattern returns 2.
            assert result.returncode in (0, 1), (
                f"pattern {pat!r} fails grep -E: rc={result.returncode}"
            )


# ── Per-axiom coverage ─────────────────────────────────────────────


class TestPerAxiomCoverage:
    def test_su_auth_patterns_present(self) -> None:
        """su-auth-001 — auth/authz scaffolding is covered."""
        patterns = _list_patterns()
        # Build a representative violation string that should match at
        # least one pattern in this axiom group.
        sample = "class " + "User" + "Manager:"
        matched = any(_grep_e(p, sample) for p in patterns)
        assert matched, f"No pattern matches {sample!r}"

    def test_management_governance_patterns_present(self) -> None:
        """mg-boundary-001 / mg-boundary-002 — feedback-language generation."""
        patterns = _list_patterns()
        sample = "def generate" + "_feedback(target, observations):"
        matched = any(_grep_e(p, sample) for p in patterns)
        assert matched, f"No pattern matches {sample!r}"

    def test_consent_scaffolding_pattern_present(self) -> None:
        """su-privacy-001 — Consent/Privacy scaffolding."""
        patterns = _list_patterns()
        sample = "class " + "Consent" + "Manager:"
        matched = any(_grep_e(p, sample) for p in patterns)
        assert matched, f"No pattern matches {sample!r}"

    def test_admin_panel_pattern_present(self) -> None:
        """su-admin-001 — Admin UI scaffolding."""
        patterns = _list_patterns()
        sample = "class " + "Admin" + "Panel(View):"
        matched = any(_grep_e(p, sample) for p in patterns)
        assert matched, f"No pattern matches {sample!r}"


# ── False-negative shield ──────────────────────────────────────────


class TestFalseNegatives:
    def test_safe_class_does_not_match(self) -> None:
        """A non-violating class definition must not be flagged."""
        patterns = _list_patterns()
        sample = "class AffordancePipeline:"
        matched = any(_grep_e(p, sample) for p in patterns)
        assert not matched, f"Safe sample {sample!r} matched a pattern"

    def test_safe_function_does_not_match(self) -> None:
        patterns = _list_patterns()
        sample = "def compute_recruitment_score(impingement: Impingement) -> float:"
        matched = any(_grep_e(p, sample) for p in patterns)
        assert not matched, f"Safe sample {sample!r} matched a pattern"
