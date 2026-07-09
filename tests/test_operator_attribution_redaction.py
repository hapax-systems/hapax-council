"""Durable scan: operator-attributed diagnostic text stays off public surfaces.

The 2026-07-09 privacy redaction removed operator-attributed diagnostic phrasing from
docs, code constants, prompts, profiles, and fixtures. This scan pins the CLASS at two
tiers (patterns live in shared/operator_attribution_scan.py — the SAME module the
review plane's ratification gate uses, so the ledger can never waive what this scan
enforces):

- Tier 1 (same-sentence attribution): a diagnosis/neurotype term and "operator" in one
  sentence. Never allowlisted — any hit is a regression.
- Tier 2 (paragraph-context attribution): the same co-occurrence within a ~300-char
  paragraph window (crossing single newlines, never blank lines). Genuinely generic
  research/corpus paragraphs are pinned in REVIEWED_GENERIC by content hash — editing a
  pinned paragraph re-triggers review fail-closed; new co-occurrences fail closed.

The policy exclusion list is empty: the operator-hands axioms edit landed 2026-07-09,
so every tracked text surface in TEXT_SUFFIXES — including axioms/** — is in scope.
SELF_PATHS exempts only the guard machinery that necessarily names the class.

SCOPE OF THE REDACTION CLASS (operator-ratified 2026-07-09, decision-memo item 27,
disposition accept-residual): the class this guard enforces is diagnostic ATTRIBUTION
to the operator at the two tiers above. Profile-grounded design research (documents
whose thesis is designing for a cognitive profile) is an operator-accepted residual:
the privacy owner ratified that such research may ground design in neurotype
literature without that constituting an operator diagnosis claim, provided no
tier-1/tier-2 attribution exists. Section- or document-level "linkage" beyond these
tiers is intentionally OUT of the enforced class by the privacy owner's own decision;
the hash-pinned ledger is the standing mechanism if the owner later narrows it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from shared.operator_attribution_scan import (
    PARAGRAPH_PATTERNS,
    SENTENCE_PATTERNS,
    file_waiver_safe,
    load_reviewed_generic,
    span_digest,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

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
#: Guard machinery that mentions the terms by necessity: the shared pattern module,
#: this test module, the pins file, and the operator-ratification ledger.
SELF_PATHS = {
    "shared/operator_attribution_scan.py",
    "tests/test_operator_attribution_redaction.py",
    "tests/operator_attribution_reviewed_generic.txt",
    "config/governance/operator-ratifications.yaml",
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
    reviewed_generic = load_reviewed_generic(REPO_ROOT)
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
                digest = span_digest(match.group(0))
                if digest in seen_spans or (rel, digest) in reviewed_generic:
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


def test_waiver_safety_blocks_operator_mental_state_content(tmp_path: Path) -> None:
    rel = "docs/research/x.md"
    doc = tmp_path / rel
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(
        "The " + "operator" + " is " + "anx" + "ious about the release window.\n",
        encoding="utf-8",
    )

    assert not file_waiver_safe(tmp_path, rel)


def test_waiver_safety_allows_non_operator_affect_discussion(tmp_path: Path) -> None:
    rel = "docs/research/x.md"
    doc = tmp_path / rel
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(
        "The study discusses anxiety detection interfaces in general.\n", encoding="utf-8"
    )

    assert file_waiver_safe(tmp_path, rel)
