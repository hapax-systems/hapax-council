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

The self-exemption list is guard-only: the operator-hands axioms edit landed 2026-07-09,
so every tracked UTF-8 text surface that is not a known binary/asset suffix, including
axioms/**, is in scope. SELF_PATHS exempts only the guard machinery that necessarily
names the class.

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

import pytest
import yaml

from shared.operator_attribution_scan import (
    PARAGRAPH_PATTERNS,
    SENTENCE_PATTERNS,
    file_enforced_class_clean,
    file_waiver_safe,
    load_reviewed_generic,
    span_digest,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

BINARY_OR_ASSET_SUFFIXES = {
    ".apkg",
    ".bsp",
    ".dat",
    ".jpg",
    ".jpeg",
    ".ogg",
    ".png",
    ".prt",
    ".qc",
    ".rnd",
    ".syx",
    ".ttf",
    ".wad",
    ".wav",
    ".woff2",
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


def _is_scannable_text_path(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() not in BINARY_OR_ASSET_SUFFIXES


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
        if not _is_scannable_text_path(path):
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


def test_same_sentence_diagnostic_guard_has_no_short_window(tmp_path: Path) -> None:
    rel = "docs/research/x.md"
    doc = tmp_path / rel
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(
        "The operator " + ("with a long intervening clause " * 20) + "has " + "AD" + "HD.\n",
        encoding="utf-8",
    )

    assert not file_enforced_class_clean(tmp_path, rel)


def test_scannable_text_paths_include_uncommon_tracked_text_extensions(tmp_path: Path) -> None:
    for suffix in (".tsx", ".rs", ".conf", ".toml", ".env", ".html", ".wgsl", ".frag"):
        path = tmp_path / f"surface{suffix}"
        path.write_text("text\n", encoding="utf-8")
        assert _is_scannable_text_path(path), suffix


def test_same_sentence_guard_spans_hard_wrapped_prose(tmp_path: Path) -> None:
    """A wrapped sentence stays TIER 1. Prose is always hard-wrapped, so a newline-bounded
    tier 1 would demote it into the pinnable tier-2 window; a fail-open on the class."""
    rel = "docs/research/x.md"
    doc = tmp_path / rel
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("The operator is a person\nwho has " + "AD" + "HD.\n", encoding="utf-8")

    assert not file_enforced_class_clean(tmp_path, rel)


@pytest.mark.parametrize(
    "text",
    [
        "The operator has a diagn" + "osis.\n",
        "The operator was diagn" + "osed with a condition.\n",
        "The operator has a diagn" + "osed condition.\n",
        "The operator has executive dysfunction.\n",
        "The operator has hyperfocus during work sessions.\n",
        "The operator is stimming during review.\n",
        "The operator's sensory sensitivity is relevant.\n",
        "The operator has a disorder.\n",
    ],
)
def test_same_sentence_guard_matches_expanded_diagnostic_terms(tmp_path: Path, text: str) -> None:
    rel = "docs/research/x.md"
    doc = tmp_path / rel
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(text, encoding="utf-8")

    assert any(pattern.search(text) for pattern in SENTENCE_PATTERNS)
    assert not file_enforced_class_clean(tmp_path, rel)


def test_same_sentence_guard_matches_hard_wrapped_expanded_diagnostic_terms(
    tmp_path: Path,
) -> None:
    rel = "docs/research/x.md"
    doc = tmp_path / rel
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(
        "The operator has a long-term\nexecutive dysfunction pattern.\n", encoding="utf-8"
    )

    assert not file_enforced_class_clean(tmp_path, rel)


def test_same_sentence_guard_does_not_bridge_structural_lines(tmp_path: Path) -> None:
    """A sentence never spans markdown table rows or adjacent list items; separate
    elements, whose unrelated co-occurrence must not read as same-sentence attribution."""
    text = (
        "| the operator's expectations | calibrated |\n"
        "| detachment | identity" + " diffusion |\n"
        "- operator config notes\n"
        "- " + "AD" + "HD research references\n"
    )

    for pattern in SENTENCE_PATTERNS:
        assert not pattern.search(text), pattern.pattern


def test_same_sentence_guard_does_not_bridge_expanded_terms_across_structural_lines(
    tmp_path: Path,
) -> None:
    """Expanded terms still obey Markdown/table/list boundaries."""
    text = (
        "| the operator's expectations | calibrated |\n"
        "| diagnosis | generic |\n"
        "- operator config notes\n"
        "- executive dysfunction research references\n"
    )

    for pattern in SENTENCE_PATTERNS:
        assert not pattern.search(text), pattern.pattern


def test_waiver_safety_blocks_operator_mental_state_content(tmp_path: Path) -> None:
    rel = "docs/research/x.md"
    doc = tmp_path / rel
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(
        "The " + "operator" + " is " + "anx" + "ious about the release window.\n",
        encoding="utf-8",
    )

    assert not file_waiver_safe(tmp_path, rel)


def test_waiver_safety_blocks_hard_wrapped_operator_mental_state_content(
    tmp_path: Path,
) -> None:
    rel = "docs/research/x.md"
    doc = tmp_path / rel
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(
        "The " + "operator" + " is\n" + "anx" + "ious about the release window.\n",
        encoding="utf-8",
    )

    assert not file_waiver_safe(tmp_path, rel)


def test_waiver_safety_blocks_hard_wrapped_expanded_diagnostic_content(
    tmp_path: Path,
) -> None:
    rel = "docs/research/x.md"
    doc = tmp_path / rel
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("The operator has\nsensory sensitivity.\n", encoding="utf-8")

    assert not file_waiver_safe(tmp_path, rel)


def test_waiver_safety_blocks_operator_attributed_first_person_affect_quote(
    tmp_path: Path,
) -> None:
    rel = "docs/research/x.md"
    doc = tmp_path / rel
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(
        'Motivating operator quote: "I don\'t like emptiness at all."\n',
        encoding="utf-8",
    )

    assert not file_waiver_safe(tmp_path, rel)


def test_waiver_safety_allows_system_attributed_first_person_affect_quote(
    tmp_path: Path,
) -> None:
    rel = "docs/research/x.md"
    doc = tmp_path / rel
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(
        'The system says: "I don\'t like empty panels."\n',
        encoding="utf-8",
    )

    assert file_waiver_safe(tmp_path, rel)


def test_waiver_safety_allows_non_operator_affect_discussion(tmp_path: Path) -> None:
    rel = "docs/research/x.md"
    doc = tmp_path / rel
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(
        "The study discusses anxiety detection interfaces in general.\n", encoding="utf-8"
    )

    assert file_waiver_safe(tmp_path, rel)


def test_reviewed_generic_pins_parse_paths_containing_spaces(tmp_path: Path) -> None:
    """The digest is the LAST field, so a path with spaces still pins correctly."""
    pins_file = tmp_path / "tests" / "operator_attribution_reviewed_generic.txt"
    pins_file.parent.mkdir(parents=True, exist_ok=True)
    digest = "a" * 12
    pins_file.write_text(
        f"# comment\ndocs/a b.md {digest}\ndocs/plain.md {digest}\nmalformed-no-digest\n",
        encoding="utf-8",
    )

    pins = load_reviewed_generic(tmp_path)

    assert ("docs/a b.md", digest) in pins
    assert ("docs/plain.md", digest) in pins
    # A line with no digest pins nothing; fail-closed, the span stays unreviewed.
    assert not any(path == "malformed-no-digest" for path, _ in pins)
    assert len(pins) == 2


def test_operator_ratification_ledger_files_are_waiver_safe() -> None:
    ledger_path = REPO_ROOT / "config" / "governance" / "operator-ratifications.yaml"
    payload = yaml.safe_load(ledger_path.read_text(encoding="utf-8"))
    offenders: list[str] = []
    for entry in payload.get("ratifications") or []:
        for rel in entry.get("files") or []:
            if not file_waiver_safe(REPO_ROOT, str(rel)):
                offenders.append(str(rel))

    assert offenders == []
