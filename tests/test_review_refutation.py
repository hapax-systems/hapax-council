"""Tests for the review-plane refutation power-up (postmortem 2026-06-13).

``review_team._auto_refute_critical`` / ``_unresolved_criticals`` deterministically
refute a hallucinated literal Python-syntax critical (a "SyntaxError" claim on a
file that py_compiles clean) so it can no longer jam quorum — while a REAL syntax
error still blocks, EVERY other critical class (data "corruption", missing files,
non-Python "syntax") is left to block (only py_compile is definitive enough to
drop a critical — #4115 review), and a reviewer-supplied refuted/resolved field
can never self-clear.

(The parse-failure-resilience half of the power-up was dropped: recovering a
verdict from a prose-wrapped/embedded fence collides with the parser's
intentional anti-injection rejection of surrounded/multiple fences — see
test_extract_review_rejects_surrounded_yaml_fence. It needs a different, security-
preserving approach and is tracked separately.)
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import review_team  # noqa: E402

# ── auto-refutation ──────────────────────────────────────────────────────────


def test_false_syntaxerror_on_clean_file_is_refuted() -> None:
    # review_team.py itself compiles cleanly → a SyntaxError claim is false.
    refuted, evidence = review_team._auto_refute_critical(
        {"file": "scripts/review_team.py", "title": "SyntaxError in decorator", "detail": ""},
        repo_root=REPO_ROOT,
    )
    assert refuted is True
    assert "py_compile is clean" in evidence


def test_real_syntaxerror_is_not_refuted(tmp_path: Path) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text("def broken(:\n    pass\n", encoding="utf-8")
    refuted, _ = review_team._auto_refute_critical(
        {"file": "bad.py", "title": "SyntaxError: invalid syntax", "detail": ""},
        repo_root=tmp_path,
    )
    assert refuted is False  # a genuine syntax error must stand


def test_corruption_critical_on_existing_file_still_blocks() -> None:
    # #4115 review caught this: "corrupt"/"does not exist" appear in REAL criticals
    # and a finding's `file` is the bug location (which exists). Such a critical
    # must NOT be auto-refuted — only a literal Python SyntaxError is checkable.
    for title in (
        "race condition corrupts the ledger",
        "config key does not exist at startup",
        "memory corruption under load",
    ):
        refuted, _ = review_team._auto_refute_critical(
            {"file": "scripts/review_team.py", "title": title, "detail": ""},
            repo_root=REPO_ROOT,
        )
        assert refuted is False, title


def test_non_python_syntax_claim_is_not_refuted() -> None:
    # "syntax error" about a non-Python artifact (regex/SQL) on a clean .py must
    # not be refuted by py_compile — only the Python exception names qualify.
    refuted, _ = review_team._auto_refute_critical(
        {
            "file": "scripts/review_team.py",
            "title": "the regex pattern has a syntax error",
            "detail": "",
        },
        repo_root=REPO_ROOT,
    )
    assert refuted is False


def test_non_checkable_critical_is_not_refuted() -> None:
    refuted, _ = review_team._auto_refute_critical(
        {"file": "scripts/review_team.py", "title": "logic bug in verdict ladder", "detail": ""},
        repo_root=REPO_ROOT,
    )
    assert refuted is False


def test_unresolved_criticals_excludes_auto_refuted() -> None:
    reviews = [
        {
            "id": "claude-1",
            "verdict": "block",
            "findings": [
                {
                    "severity": "critical",
                    "file": "scripts/review_team.py",
                    "title": "SyntaxError in module",
                    "detail": "",
                }
            ],
        }
    ]
    # The only critical is a false SyntaxError on a clean file → count is 0.
    assert review_team._unresolved_criticals(reviews, repo_root=REPO_ROOT) == []


def test_unresolved_criticals_keeps_real_critical() -> None:
    reviews = [
        {
            "id": "codex-1",
            "verdict": "block",
            "findings": [
                {
                    "severity": "critical",
                    "file": "scripts/x.py",
                    "title": "race condition",
                    "detail": "",
                }
            ],
        }
    ]
    out = review_team._unresolved_criticals(reviews, repo_root=REPO_ROOT)
    assert len(out) == 1


def test_reviewer_supplied_refuted_field_does_not_clear() -> None:
    # SECURITY: only a COMPUTED deterministic check clears a critical. A reviewer
    # (or a prompt-injected reply) supplying refuted/resolved on a non-checkable
    # critical must NOT self-clear it — the critical still counts.
    reviews = [
        {
            "id": "gemini-1",
            "verdict": "block",
            "findings": [
                {"severity": "critical", "title": "real logic bug", "refuted": True},
                {"severity": "critical", "title": "real race", "resolved": True},
            ],
        }
    ]
    assert len(review_team._unresolved_criticals(reviews, repo_root=REPO_ROOT)) == 2
