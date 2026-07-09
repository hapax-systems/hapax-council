"""Operator-attribution scan — the ENFORCED privacy class, importable.

Single source for the two-tier diagnostic-attribution patterns, used by BOTH the
durable test guard (tests/test_operator_attribution_redaction.py) and the review
plane's ratification gate (scripts/review_team.py): the data-owner ledger may waive
review findings ONLY on files that are clean under this scan — the ledger can never
waive the enforced class itself.

Tier 1: same-sentence attribution (never allowlisted) — unbounded in distance, spanning
hard-wrapped prose but never bridging a table row, list item, or blank line. Tier 2:
paragraph-context co-occurrence (~300 chars crossing single newlines), allowlistable per
reviewed span via the hash-pinned ledger in tests/operator_attribution_reviewed_generic.txt.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

_DIAGNOSIS = (
    r"(?:\bADHD\b|\bAuDHD\b|\bautis\w*|\bneurodiverg\w*|\bRSD\b|rejection[- ]sensitiv\w*"
    r"|\bdysphor\w*|identity\s+diffusion"
    r"|\bdisorder\w*|executive\s+dysfunction|hyperfocus\w*|\bstim(?:ming|s|med)\b"
    r"|sensory\s+sensitiv\w*)"
)
_DIRECT_DIAGNOSIS = (
    rf"(?:{_DIAGNOSIS}|\bdiagnos(?:is|es)\b|\bdiagnosed\s+condition(?:s)?\b"
    r"|\b(?:medical|health|mental\s+health|neurodevelopmental|cognitive)\s+condition(?:s)?\b)"
)
#: A newline that continues one wrapped prose sentence, rather than starting a new
#: structural element. Blocked by: a blank line, a markdown table row/heading/quote/list
#: bullet/fence, or a new string literal; a sentence never bridges table cells or
#: adjacent list items.
_SOFT_WRAP = "\\n(?![ \t]*(?:\\n|[|#>`\"'*+\\]\\}\\)\\-]))"
#: A same-sentence run: ANY distance (no short window), terminated by .!? or by anything
#: `_SOFT_WRAP` refuses to cross. It spans hard-wrapped prose deliberately; otherwise a
#: wrapped sentence demotes from tier 1 (never allowlisted) to tier 2 (pinnable), failing
#: open on the enforced class. Lazy: `search` stops at the first diagnosis term.
_SAME_SENTENCE = rf"(?:(?![.!?])(?:[^\n]|{_SOFT_WRAP}))*?"
SENTENCE_PATTERNS = (
    re.compile(
        rf"operator\s+(?:has|with|is)\s+(?:an?\s+|the\s+)?{_DIRECT_DIAGNOSIS}",
        re.IGNORECASE,
    ),
    re.compile(r"\boperator\s+(?:is|was|were)\s+diagnosed\b", re.IGNORECASE),
    re.compile(rf"operator'?s\s+(?:specific\s+)?{_DIRECT_DIAGNOSIS}", re.IGNORECASE),
    re.compile(rf"{_DIAGNOSIS}{_SAME_SENTENCE}\boperator(?:'s)?\b", re.IGNORECASE),
    re.compile(rf"\boperator(?:'s)?\b{_SAME_SENTENCE}{_DIAGNOSIS}", re.IGNORECASE),
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
    # local filesystem paths / user-homed paths — the repo's claim-inventory taxonomy
    # counts these as personal/operator privacy; enumerable without leaking
    re.compile(r"/home/[a-z_][a-z0-9_-]*|~/[A-Za-z]|C:\\Users\\|Documents/Personal"),
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
        if not line or line.startswith("#"):
            continue
        # digest is the LAST field, so a path containing spaces still parses.
        # A line with no digest pins nothing (fail-closed: the span stays unreviewed).
        path, sep, digest = line.rpartition(" ")
        if sep:
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


#: Sentence/segment split for attribution-scoped affect detection. Hard-wrapped prose is
#: still one segment; structural Markdown breaks and quotation marks remain boundaries.
#: Quoted speech (the SYSTEM saying "I ...") is never operator attribution, and must not
#: bleed into an adjacent sentence that happens to name the operator.
_STRUCTURAL_SEGMENT_BREAK = r"\n(?=[ \t]*(?:\n|[|#>`\"'*+\]\}\)\-]))"
_SEGMENT_RE = re.compile(rf"(?<=[.!?])\s+|{_STRUCTURAL_SEGMENT_BREAK}|[\"“”]")
_OPERATOR_ATTRIBUTED_FIRST_PERSON_AFFECT_RE = re.compile(
    r"\boperator(?:['’]s)?\b"
    r"[^.!?]{0,120}\b(?:quote|said|says|stated|wrote|verbatim|asked)\b"
    r"[^.!?]{0,120}\bI\b"
    r"[^.!?]{0,80}\b(?:don['’]?t\s+like|do\s+not\s+like|dislike|hate|"
    r"can(?:not|['’]?t)\s+stand|am\s+(?:anxious|afraid|overwhelmed|"
    r"frustrated|upset|stressed|worried|exhausted))\b",
    re.IGNORECASE,
)


def operator_affect_asserted(text: str) -> bool:
    """True iff some segment ATTRIBUTES an affective/mental state TO THE OPERATOR.

    Reuses the repo's own detector (``mental_state_redaction.operator_mental_state_present``
    via ``publication_allowlist.cross_boundary_pii_blockers``), scoped to segments that
    name the operator in the third person. One extra narrow guard catches operator-
    attributed first-person affect quotes such as ``operator said "I don't like ..."``;
    the global egress detector deliberately avoids bare like/dislike opinion verbs.

    Why the scoping is required, not cosmetic: the bare detector deliberately keys on
    first-person markers so operator affect is caught when written as "I"/"my". In research
    documents ABOUT self-models and affect, those markers appear in quoted SYSTEM speech
    ("My self is whatever you want it to be") and rhetorical examples ("Am I doing well?").
    Applying the bare detector to a whole such file always fires, which would deadlock the
    data-owner ratification by construction — a ledger-named file could never be waived,
    so a consent-provenance critical on it would block forever with no path through.
    Segment-scoping keeps every genuine operator-attributed disclosure ("The operator is
    anxious about the release window") blocking, while not vetoing a document merely for
    discussing affect.
    """
    from shared.governance.mental_state_redaction import operator_mental_state_present

    if _OPERATOR_ATTRIBUTED_FIRST_PERSON_AFFECT_RE.search(" ".join(text.splitlines())):
        return True
    for segment in _SEGMENT_RE.split(text):
        if "operator" in segment.lower() and operator_mental_state_present(segment):
            return True
    return False


def file_waiver_safe(repo_root: Path, rel_path: str) -> bool:
    """True iff a data-owner waiver may apply to findings citing ``rel_path``: the file is
    clean under the enforced attribution class, asserts no operator affect, and contains no
    pattern-detectable non-residual PII DATUM (email/phone/SSN/address/DOB/user-homed path).

    This decides the waiver on FILE CONTENT, not finding prose: if the alleged datum were
    actually present, this returns False and the finding blocks; if it is absent, the
    allegation has no referent in the file. Fail-closed: unreadable = not safe.

    The mental-state class is guarded on four legs, none of which this relaxes:
      1. content, here — ``operator_affect_asserted`` (attribution-scoped, see above);
      2. prose — a finding ALLEGING a mental/emotional/cognitive/psychological/affective
         (or medical) datum is non-waivable by rule (``_NON_WAIVABLE_ALLEGATION_RE``);
      3. egress — ``operator_mental_state_present`` remains enforced unscoped on the
         publication path, which is what actually stops such content leaving the estate;
      4. pins — the ledger's ``files_sha256`` binds each waiver to the exact bytes the data
         owner inspected; any edit voids the pin and forces re-ratification.
    """
    if not file_enforced_class_clean(repo_root, rel_path):
        return False
    try:
        text = (repo_root / rel_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    if operator_affect_asserted(text):
        return False
    return not any(pattern.search(text) for pattern in NON_RESIDUAL_PII_PATTERNS)
