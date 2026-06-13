"""Tests for the review-plane refutation power-up (postmortem 2026-06-13).

``review_team._auto_refute_critical`` / ``_unresolved_criticals`` deterministically
refute false criticals (a "SyntaxError" claim on a file that py_compiles clean; a
"corrupted/missing file" claim on a present file) so a hallucinated critical can no
longer jam quorum — while a REAL syntax error / genuinely missing file still
blocks, and a reviewer-supplied refuted/resolved field can never self-clear.

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
    assert "py_compile clean" in evidence


def test_real_syntaxerror_is_not_refuted(tmp_path: Path) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text("def broken(:\n    pass\n", encoding="utf-8")
    refuted, _ = review_team._auto_refute_critical(
        {"file": "bad.py", "title": "SyntaxError: invalid syntax", "detail": ""},
        repo_root=tmp_path,
    )
    assert refuted is False  # a genuine syntax error must stand


def test_corrupted_claim_on_existing_file_is_refuted() -> None:
    refuted, evidence = review_team._auto_refute_critical(
        {"file": "scripts/review_team.py", "title": "corrupted filename", "detail": ""},
        repo_root=REPO_ROOT,
    )
    assert refuted is True
    assert "exists" in evidence


def test_missing_file_claim_on_absent_file_is_not_refuted(tmp_path: Path) -> None:
    refuted, _ = review_team._auto_refute_critical(
        {"file": "nope/gone.py", "title": "missing file", "detail": ""},
        repo_root=tmp_path,
    )
    assert refuted is False  # genuinely absent → stands


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
