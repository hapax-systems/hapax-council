"""Extract assertions from prose/markdown sources.

Three extraction strategies:
1. CLAUDE.md directives containing MUST/NEVER/ALWAYS/MANDATORY/PROTECTED
2. Operator feedback memories (type: feedback in frontmatter)
3. Relay artifact claims and decisions (section-based extraction)
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from shared.assertion_model import (
    Assertion,
    AssertionType,
    ProvenanceRecord,
    SourceType,
)

EXTRACTION_VERSION = "1.0"

_DEONTIC_RE = re.compile(
    r"(?:^|\n)\s*[-*]?\s*([^\n]*\b(?:MUST|NEVER|ALWAYS|MANDATORY|PROTECTED)\b[^\n]*)",
)

_DEONTIC_KEYWORD_RE = re.compile(r"\b(MUST|NEVER|ALWAYS|MANDATORY|PROTECTED)\b")

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?(.*)", re.DOTALL)

_DECISION_HEADER_RE = re.compile(
    r"^#{1,4}\s+.*\b(Decision|Finding|Claim|SHIP spec|Conclusion|Result)\b",
    re.IGNORECASE | re.MULTILINE,
)


def _parse_frontmatter(text: str) -> tuple[dict[str, object], str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    try:
        fm = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return {}, text
    if not isinstance(fm, dict):
        return {}, text
    return fm, m.group(2)


def _line_number_of(text: str, pos: int) -> int:
    return text[:pos].count("\n") + 1


def _extract_deontic_lines(text: str) -> list[tuple[str, int, str]]:
    """Return (sentence, line_number, keyword) tuples for deontic lines."""
    results = []
    for m in _DEONTIC_RE.finditer(text):
        sentence = m.group(1).strip()
        sentence = re.sub(r"\s+", " ", sentence)
        if not sentence:
            continue
        kw_match = _DEONTIC_KEYWORD_RE.search(sentence)
        keyword = kw_match.group(1) if kw_match else "MUST"
        line = _line_number_of(text, m.start())
        results.append((sentence, line, keyword))
    return results


def extract_from_claude_md(path: Path) -> list[Assertion]:
    """Extract MUST/NEVER/ALWAYS/MANDATORY/PROTECTED directives from a CLAUDE.md file."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    _, body = _parse_frontmatter(text)
    assertions = []

    for sentence, line, keyword in _extract_deontic_lines(body):
        assertions.append(
            Assertion(
                text=sentence,
                source_type=SourceType.MARKDOWN,
                source_uri=str(path),
                source_span=(line, line),
                confidence=0.85,
                domain="operational",
                assertion_type=AssertionType.CONSTRAINT,
                provenance=ProvenanceRecord(
                    extraction_method="prose_claude_md_deontic",
                    extraction_version=EXTRACTION_VERSION,
                ),
                tags=[f"keyword:{keyword}"],
            )
        )

    return assertions


def extract_from_memory_file(path: Path) -> list[Assertion]:
    """Extract behavioral assertions from an operator feedback memory file."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    fm, body = _parse_frontmatter(text)
    if fm.get("type") != "feedback":
        return []

    body = body.strip()
    if not body:
        return []

    name = fm.get("name", path.stem)
    description = fm.get("description", "")

    paragraphs = re.split(r"\n\n+", body)
    rule_text = paragraphs[0].strip()
    rule_text = re.sub(r"\s+", " ", rule_text)

    tags = [f"memory_name:{name}"]
    if description:
        tags.append(f"description:{description}")

    assertions = [
        Assertion(
            text=rule_text,
            source_type=SourceType.MEMORY,
            source_uri=str(path),
            source_span=(1, 1),
            confidence=0.9,
            domain="behavioral",
            assertion_type=AssertionType.PREFERENCE,
            provenance=ProvenanceRecord(
                extraction_method="prose_memory_feedback",
                extraction_version=EXTRACTION_VERSION,
            ),
            tags=tags,
        )
    ]

    for para in paragraphs[1:]:
        para = para.strip()
        if para.startswith("**Why:**"):
            reason = para[len("**Why:**") :].strip()
            reason = re.sub(r"\s+", " ", reason)
            assertions.append(
                Assertion(
                    text=reason,
                    source_type=SourceType.MEMORY,
                    source_uri=str(path),
                    confidence=0.8,
                    domain="behavioral",
                    assertion_type=AssertionType.FACT,
                    provenance=ProvenanceRecord(
                        extraction_method="prose_memory_feedback_why",
                        extraction_version=EXTRACTION_VERSION,
                    ),
                    tags=[f"memory_name:{name}", "section:why"],
                )
            )
        elif para.startswith("**How to apply:**"):
            guidance = para[len("**How to apply:**") :].strip()
            guidance = re.sub(r"\s+", " ", guidance)
            assertions.append(
                Assertion(
                    text=guidance,
                    source_type=SourceType.MEMORY,
                    source_uri=str(path),
                    confidence=0.85,
                    domain="behavioral",
                    assertion_type=AssertionType.CONSTRAINT,
                    provenance=ProvenanceRecord(
                        extraction_method="prose_memory_feedback_how",
                        extraction_version=EXTRACTION_VERSION,
                    ),
                    tags=[f"memory_name:{name}", "section:how_to_apply"],
                )
            )

    return assertions


def _extract_section_body(text: str, header_start: int) -> str:
    """Extract body text from header_start until the next same-or-higher-level header."""
    lines = text[header_start:].split("\n")
    if not lines:
        return ""

    header_line = lines[0]
    header_match = re.match(r"^(#{1,4})\s", header_line)
    header_level = len(header_match.group(1)) if header_match else 1

    body_lines = []
    for line in lines[1:]:
        next_header = re.match(r"^(#{1,4})\s", line)
        if next_header and len(next_header.group(1)) <= header_level:
            break
        body_lines.append(line)

    return "\n".join(body_lines).strip()


def extract_from_relay_artifact(path: Path) -> list[Assertion]:
    """Extract claims and decisions from a relay artifact."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    _, body = _parse_frontmatter(text)
    assertions = []

    for m in _DECISION_HEADER_RE.finditer(body):
        section_type = m.group(1).lower()
        section_body = _extract_section_body(body, m.start())
        if not section_body:
            continue

        first_para = re.split(r"\n\n+", section_body)[0] if section_body else ""
        first_para = re.sub(r"\s+", " ", first_para).strip()
        if not first_para or len(first_para) < 10:
            continue

        if section_type in ("decision", "conclusion", "ship spec"):
            a_type = AssertionType.DECISION
            confidence = 0.85
        elif section_type == "finding":
            a_type = AssertionType.CLAIM
            confidence = 0.75
        else:
            a_type = AssertionType.CLAIM
            confidence = 0.7

        line = _line_number_of(body, m.start())
        assertions.append(
            Assertion(
                text=first_para,
                source_type=SourceType.RELAY,
                source_uri=str(path),
                source_span=(line, line),
                confidence=confidence,
                domain="project",
                assertion_type=a_type,
                provenance=ProvenanceRecord(
                    extraction_method="prose_relay_section",
                    extraction_version=EXTRACTION_VERSION,
                ),
                tags=[f"section_type:{section_type}"],
            )
        )

    return assertions


def extract_from_directory(
    root: Path,
    *,
    source_kind: str = "claude_md",
) -> list[Assertion]:
    """Recursively extract assertions from markdown files under root.

    source_kind controls extraction strategy:
      - "claude_md": CLAUDE.md directive extraction
      - "memory": feedback memory extraction
      - "relay": relay artifact extraction
    """
    results: list[Assertion] = []

    if source_kind == "claude_md":
        for md in sorted(root.rglob("CLAUDE.md")):
            results.extend(extract_from_claude_md(md))
    elif source_kind == "memory":
        for md in sorted(root.rglob("*.md")):
            if md.name == "MEMORY.md":
                continue
            results.extend(extract_from_memory_file(md))
    elif source_kind == "relay":
        for md in sorted(root.rglob("*.md")):
            results.extend(extract_from_relay_artifact(md))

    return results
