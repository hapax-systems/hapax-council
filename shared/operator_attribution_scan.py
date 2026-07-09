"""Operator-attribution scan — the ENFORCED privacy class, importable.

Single source for the two-tier diagnostic-attribution patterns, used by BOTH the
durable test guard (tests/test_operator_attribution_redaction.py) and the review
plane's ratification gate (scripts/review_team.py): the data-owner ledger may waive
review findings ONLY on files that are clean under this scan — the ledger can never
waive the enforced class itself.

Tier 1: same-sentence attribution (never allowlisted). Tier 2: paragraph-context
co-occurrence (~300 chars crossing single newlines), allowlistable per reviewed span
via the hash-pinned ledger in tests/operator_attribution_reviewed_generic.txt.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

_DIAGNOSIS = (
    r"(?:\bADHD\b|\bAuDHD\b|\bautis\w*|\bneurodiverg\w*|\bRSD\b|rejection[- ]sensitiv\w*"
    r"|\bdysphor\w*|identity\s+diffusion)"
)
SENTENCE_PATTERNS = (
    re.compile(rf"operator\s+(?:has|with|is)\s+{_DIAGNOSIS}", re.IGNORECASE),
    re.compile(rf"operator'?s\s+(?:specific\s+)?{_DIAGNOSIS}", re.IGNORECASE),
    re.compile(rf"{_DIAGNOSIS}[^.\n]{{0,60}}\boperator\b", re.IGNORECASE),
    re.compile(rf"\boperator\b[^.\n]{{0,60}}{_DIAGNOSIS}", re.IGNORECASE),
)
_PARA = r"(?:[^\n]|\n(?!\s*\n)){0,300}?"
PARAGRAPH_PATTERNS = (
    re.compile(rf"{_DIAGNOSIS}{_PARA}\boperator(?:'s)?\b", re.IGNORECASE | re.DOTALL),
    re.compile(rf"\boperator(?:'s)?\b{_PARA}{_DIAGNOSIS}", re.IGNORECASE | re.DOTALL),
)

REVIEWED_GENERIC_RELPATH = Path("tests/operator_attribution_reviewed_generic.txt")

#: NON-residual PII classes — generic, content-level detectors for datum classes the
#: ratification ledger may NEVER waive (the residual class is diagnosis/neurotype
#: LINKAGE only). Used by the review plane's waiver-safety check: a ratified file
#: containing any of these is not waiver-safe, so a finding alleging such a leak stays
#: blocking. Estate-specific literals (names, places) remain pii-guard's write-time
#: job — they cannot appear as patterns in public source without themselves leaking.
NON_RESIDUAL_PII_PATTERNS = (
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),  # email
    re.compile(r"(?:\+?\d{1,2}[\s.-])?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b"),  # phone
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),  # SSN-shaped
    re.compile(
        r"\b\d{1,5}\s+[A-Z][a-z]+\s+(?:St|Street|Ave|Avenue|Blvd|Road|Rd|Drive|Dr|Lane|Ln|Court|Ct|Way)\b"
    ),  # street address
    re.compile(r"\bDOB\b|\bdate\s+of\s+birth\b|\bborn\s+(?:on\s+)?\d", re.IGNORECASE),
)


def span_digest(span: str) -> str:
    normalized = " ".join(span.split()).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]


def load_reviewed_generic(repo_root: Path) -> set[tuple[str, str]]:
    """(path, digest) pins for reviewed-generic tier-2 spans; missing file = no pins."""
    pins_path = repo_root / REVIEWED_GENERIC_RELPATH
    pins: set[tuple[str, str]] = set()
    if not pins_path.is_file():
        return pins
    for line in pins_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            path, _, digest = line.partition(" ")
            pins.add((path, digest))
    return pins


def file_enforced_class_clean(repo_root: Path, rel_path: str) -> bool:
    """True iff ``rel_path`` at ``repo_root`` carries NO enforced-class attribution:
    no tier-1 match, and every tier-2 span is pinned reviewed-generic. Fail-closed:
    an unreadable file is NOT clean."""
    path = repo_root / rel_path
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    for pattern in SENTENCE_PATTERNS:
        if pattern.search(text):
            return False
    pins = load_reviewed_generic(repo_root)
    for pattern in PARAGRAPH_PATTERNS:
        for match in pattern.finditer(text):
            if (rel_path, span_digest(match.group(0))) not in pins:
                return False
    return True


def file_waiver_safe(repo_root: Path, rel_path: str) -> bool:
    """True iff a data-owner waiver may apply to findings citing ``rel_path``: the file
    is clean under the enforced attribution class AND contains no detectable
    non-residual PII datum. This decides the waiver on FILE CONTENT, not finding
    prose: if the alleged datum (address, phone, ...) were actually present, this
    returns False and the finding blocks; if it is absent, the allegation has no
    referent in the file. Fail-closed: unreadable = not safe."""
    if not file_enforced_class_clean(repo_root, rel_path):
        return False
    try:
        text = (repo_root / rel_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return not any(pattern.search(text) for pattern in NON_RESIDUAL_PII_PATTERNS)
