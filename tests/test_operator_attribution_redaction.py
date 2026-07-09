"""Durable scan: operator-attributed diagnostic text stays off public surfaces.

The 2026-07-09 privacy redaction removed operator-attributed diagnostic phrasing from
docs, code constants, prompts, profiles, and fixtures. This scan pins the CLASS at two
tiers:

- Tier 1 (same-sentence attribution): a diagnosis/neurotype term and "operator" in one
  sentence. Never allowlisted — any hit is a regression.
- Tier 2 (paragraph-context attribution): the same co-occurrence within a ~300-char
  paragraph window (crossing single newlines, never blank lines). Genuinely generic
  research/corpus paragraphs are pinned in REVIEWED_GENERIC by content hash — editing a
  pinned paragraph re-triggers review fail-closed; new co-occurrences fail closed.

The exclusion list is EMPTY: the operator-hands axioms edit landed 2026-07-09, so every
tracked surface — including axioms/** — is in scope.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

_DIAGNOSIS = r"(?:ADHD|AuDHD|autis\w*|neurodiverg\w*)"
#: Tier 1 — same-sentence attribution (never allowlisted).
SENTENCE_PATTERNS = (
    re.compile(rf"operator\s+(?:has|with|is)\s+{_DIAGNOSIS}", re.IGNORECASE),
    re.compile(rf"operator'?s\s+(?:specific\s+)?{_DIAGNOSIS}", re.IGNORECASE),
    re.compile(rf"{_DIAGNOSIS}[^.\n]{{0,60}}\boperator\b", re.IGNORECASE),
    re.compile(rf"\boperator\b[^.\n]{{0,60}}{_DIAGNOSIS}", re.IGNORECASE),
)
#: Tier 2 — paragraph-context co-occurrence (allowlistable when reviewed generic).
_PARA = r"(?:[^\n]|\n(?!\s*\n)){0,300}?"
PARAGRAPH_PATTERNS = (
    re.compile(rf"{_DIAGNOSIS}{_PARA}\boperator(?:'s)?\b", re.IGNORECASE | re.DOTALL),
    re.compile(rf"\boperator(?:'s)?\b{_PARA}{_DIAGNOSIS}", re.IGNORECASE | re.DOTALL),
)

#: (repo-relative path, sha256[:12] of the whitespace-normalized matched span).
#: Reviewed 2026-07-09: generic literature/corpus discussion in the same paragraph as a
#: system-design "operator" sentence, with no diagnosis attributed to the operator.
#: Any edit to a pinned span changes its hash and fails the scan closed for re-review.
REVIEWED_GENERIC: set[tuple[str, str]] = set()  # populated below by _pin()


def _pin(path: str, digest: str) -> None:
    REVIEWED_GENERIC.add((path, digest))


def _span_digest(span: str) -> str:
    normalized = " ".join(span.split()).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]


# --- reviewed-generic pins (2026-07-09 sweep) --------------------------------------
# Populated from the audited sweep; see the PR #4472 round-4 resolution comment.
_PINS_FILE = Path(__file__).with_name("operator_attribution_reviewed_generic.txt")
if _PINS_FILE.exists():
    for _line in _PINS_FILE.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#"):
            _path, _, _digest = _line.partition(" ")
            _pin(_path, _digest)

TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".yaml",
    ".yml",
    ".json",
    ".jsonl",
    ".ts",
    ".txt",
    ".j2",
    ".sh",
}
#: This test module and its pins file mention the terms by necessity.
SELF_PATHS = {
    "tests/test_operator_attribution_redaction.py",
    "tests/operator_attribution_reviewed_generic.txt",
}


def _tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.splitlines()


def _line_of(text: str, pos: int) -> int:
    return text[:pos].count("\n") + 1


def test_no_operator_attributed_diagnostic_text_on_tracked_surfaces() -> None:
    sentence_offenders: list[str] = []
    paragraph_offenders: list[str] = []
    for rel in _tracked_files():
        if rel in SELF_PATHS:
            continue
        path = REPO_ROOT / rel
        if path.suffix not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pattern in SENTENCE_PATTERNS:
            match = pattern.search(text)
            if match:
                sentence_offenders.append(
                    f"{rel}:{_line_of(text, match.start())}: {match.group(0)!r}"
                )
                break
        seen_spans: set[str] = set()
        for pattern in PARAGRAPH_PATTERNS:
            for match in pattern.finditer(text):
                digest = _span_digest(match.group(0))
                if digest in seen_spans or (rel, digest) in REVIEWED_GENERIC:
                    continue
                seen_spans.add(digest)
                paragraph_offenders.append(
                    f"{rel}:{_line_of(text, match.start())} [span {digest}]: "
                    f"{' '.join(match.group(0).split())[:120]!r}"
                )
    assert not sentence_offenders, (
        "operator-attributed diagnostic text (same-sentence tier — never allowlisted):\n"
        + "\n".join(sentence_offenders)
    )
    assert not paragraph_offenders, (
        "paragraph-context diagnosis/operator co-occurrence not pinned as reviewed-generic "
        "(redact it, or — ONLY if genuinely generic — add 'path digest' to "
        "tests/operator_attribution_reviewed_generic.txt):\n" + "\n".join(paragraph_offenders)
    )
