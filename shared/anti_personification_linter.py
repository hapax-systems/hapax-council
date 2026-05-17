"""Anti-personification linter.

Encodes the Phase 7 discriminator (redesign spec §6):
  - analogies that describe architectural fact are fine (curious ≈ SEEKING stance)
  - analogies that claim inner life are not (curious ≈ feels wonder)

Stage 1 (warn-only) core library. Public API:
  - Finding:     dataclass of (file_path, line, col, rule_id, matched_text, severity)
  - lint_text(text, path="") -> list[Finding]
  - lint_path(path) -> list[Finding]   (dispatches on suffix: .py, .md, .yaml/.yml)

Sources:
  - Spec:     docs/superpowers/specs/2026-04-18-anti-personification-linter-design.md
  - Plan:     docs/superpowers/plans/2026-04-18-anti-personification-linter-plan.md
  - Research: /tmp/cvs-research-155.md §8.1 (deny-list verbatim origin)

Design notes:
  - No new third-party dependencies: Python stdlib (re, ast, pathlib) + PyYAML
    (already in council's `dependencies`). Markdown is parsed with a small
    regex pass to excise fenced code blocks; that is sufficient for the Stage 1
    surface area. Mistune can replace it in a later stage without touching the
    public API.
  - Allow-list is context-first: before reporting a hit we check for
      * ±200-char window carve-out  (NOT / forbidden / rejected / drift)
      * SEEKING-stance translation commentary
      * speaker-prefixed operator quotation
      * file-level `anti-personification: allow` pragma
    and, optionally, path-level suppressions from
    `axioms/anti_personification_allowlist.yaml`.
  - `_LEGACY_*`-prefixed Python top-level assignments are skipped by the AST
    extractor so the emergency-revert path in `persona.py` and siblings does
    not self-flag.
"""

from __future__ import annotations

import ast
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

__all__ = [
    "Finding",
    "AntiPersonificationViolation",
    "DENY_PATTERNS",
    "REJECTION_KEYWORDS",
    "REJECTION_WINDOW",
    "lint_text",
    "lint_path",
]


LintMode = Literal["warn", "fail"]


class AntiPersonificationViolation(Exception):
    """Raised by `lint_text` / `lint_path` when `lint_mode="fail"` and any
    deny-list pattern matches outside a carve-out window.

    Carries the full list of `Finding` objects on the `.findings` attribute so
    the caller can render a structured error without re-running the scan.
    """

    def __init__(self, findings: list[Finding]) -> None:
        self.findings = findings
        preview = "; ".join(
            f"{f.file_path}:{f.line}:{f.col} {f.rule_id} ({f.matched_text!r})" for f in findings[:3]
        )
        if len(findings) > 3:
            preview += f" ... (+{len(findings) - 3} more)"
        super().__init__(f"anti-personification: {len(findings)} finding(s): {preview}")


# ---------------------------------------------------------------------------
# Finding
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    """A single deny-list hit that survived the allow-list carve-outs."""

    file_path: str
    line: int
    col: int
    rule_id: str
    matched_text: str
    severity: str = "warn"


# ---------------------------------------------------------------------------
# Deny-list patterns (verbatim from research dossier §8.1 / spec §2.1)
# ---------------------------------------------------------------------------
#
# Four pattern families. `re.IGNORECASE` is intentionally OFF because case
# carries signal for the proper noun "Hapax". MULTILINE is unnecessary — every
# pattern here is line-agnostic.

DENY_PATTERNS: dict[str, list[tuple[str, re.Pattern[str]]]] = {
    "inner_life_first_person": [
        ("feel_verb", re.compile(r"\bI (feel|felt|feeling)\b")),
        (
            "belief_verb",
            re.compile(
                r"\bI (believe|thought|wonder|wondered|know|knew|understand|"
                r"understood|trust|trusted|prefer|preferred|remember|remembered|"
                r"want|wanted|hope|hoped|intuit|intuited)\b"
            ),
        ),
        (
            "im_affect",
            re.compile(r"\bI'?m (excited|happy|sad|curious|moved|touched|fascinated|delighted)\b"),
        ),
        ("affect_verb", re.compile(r"\bI (love|enjoy|hate|miss|care about|care for)\b")),
        (
            "my_inner",
            re.compile(
                r"\bmy (feelings?|emotions?|mood|heart|soul|experience|"
                r"consciousness|memory|taste|intuition|concern)\b"
            ),
        ),
    ],
    "second_person_inner_life": [
        (
            "you_feel",
            re.compile(r"\byou (feel|believe|think|wonder|sense|care|love|enjoy)\b"),
        ),
        (
            "your_inner",
            re.compile(r"\byour (feelings?|emotions?|mood|personality|inner life|experience)\b"),
        ),
        ("you_have_personality", re.compile(r"\byou have personality\b")),
        (
            "you_are_affect",
            re.compile(r"\byou are (warm|friendly|chatty|curious|excited)\b"),
        ),
        (
            "be_affect",
            re.compile(r"\bbe (yourself|itself|warm|friendly|genuine|curious|excited|happy)\b"),
        ),
    ],
    "personification_nouns": [
        ("personality_noun", re.compile(r"\bpersonality\b")),
        ("archetype_noun", re.compile(r"\barchetype\b")),
        ("dry_wit", re.compile(r"\bdry wit\b")),
        ("genuine_curiosity", re.compile(r"\bgenuine curiosity\b")),
        ("intellectual_honesty", re.compile(r"\bintellectual honesty\b")),
        ("warm_but_concise", re.compile(r"\bwarm but concise\b")),
        ("friendly_not_chatty", re.compile(r"\bfriendly without being chatty\b")),
        (
            "hapax_inner",
            re.compile(
                r"\bHapax (feels|thinks|believes|wants|cares|loves|hopes|"
                r"fears|trusts|finds|prefers|remembers|knows|understands|"
                r"intuits|perceives)\b"
            ),
        ),
    ],
    "anthropic_pronouns": [
        ("hapax_gendered", re.compile(r"\bHapax,? (he|she|his|her|him)\b")),
    ],
    "voice_posture_violations": [
        (
            "social_performance",
            re.compile(
                r"\b(happy|glad|pleased|delighted)\s+to\s+(help|assist|be here|serve)\b",
                re.IGNORECASE,
            ),
        ),
        (
            "availability_performance",
            re.compile(r"\b(here for you|always (here|ready|listening|available))\b", re.IGNORECASE),
        ),
        (
            "inner_experience_claim",
            re.compile(
                r"\bHapax (experiences?|senses?|notices?)\s+(a|the|some)\s+"
                r"(sense|feeling|warmth|wonder|joy|satisfaction)\b"
            ),
        ),
    ],
    # GEAL-scoped face-iconography rule family (spec §11 #1 of
    # docs/superpowers/specs/2026-04-23-geal-spec.md). Only applied to
    # files whose path matches ``_GEAL_PATH_GLOB`` — word-boundary
    # matches on face parts that would violate the 10-invariant gate
    # GEAL inherits from the retired HARDM.
    "geal_geometry": [
        ("eye", re.compile(r"\beye(s|ball|lid|ball)?\b", re.IGNORECASE)),
        ("mouth", re.compile(r"\bmouth(s)?\b", re.IGNORECASE)),
        ("smile", re.compile(r"\bsmil(e|es|ing|ed)\b", re.IGNORECASE)),
        ("wink_blink", re.compile(r"\bwink(s|ing|ed)?\b|\bblink(s|ing|ed)?\b", re.IGNORECASE)),
        ("brow", re.compile(r"\b(eye)?brow(s)?\b", re.IGNORECASE)),
        ("nose", re.compile(r"\bnose(s)?\b", re.IGNORECASE)),
        ("lips", re.compile(r"\blip(s)?\b", re.IGNORECASE)),
        ("frown", re.compile(r"\bfrown(s|ing|ed)?\b", re.IGNORECASE)),
        ("grin", re.compile(r"\bgrin(s|ning|ned)?\b", re.IGNORECASE)),
        ("ear", re.compile(r"\bear(s|lobe|drum)?\b", re.IGNORECASE)),
    ],
}

# GEAL-scoped linting applies only to files matching this glob. Keeps
# the broader codebase free to use "eye" / "mouth" in their legitimate
# technical senses (a.k.a. storm-eye, river-mouth).
_GEAL_PATH_MARKER = "geal"


# ---------------------------------------------------------------------------
# Allow-list carve-outs
# ---------------------------------------------------------------------------

REJECTION_KEYWORDS: tuple[str, ...] = ("NOT", "forbidden", "rejected", "drift")
REJECTION_WINDOW: int = 200

_FILE_LEVEL_PRAGMA = re.compile(
    r"<!--\s*anti-personification:\s*allow\s*-->|#\s*anti-personification:\s*allow"
)
_SPEAKER_PREFIX = re.compile(r"^\s*(?:>\s*)?(?:operator|OPERATOR)\s*[:—-]", re.MULTILINE)
_SEEKING_CONTEXT = re.compile(r"SEEKING\s+(?:stance|state|architectural)")


def _in_rejection_window(text: str, match_start: int) -> bool:
    lo = max(0, match_start - REJECTION_WINDOW)
    hi = min(len(text), match_start + REJECTION_WINDOW)
    window = text[lo:hi]
    return any(kw in window for kw in REJECTION_KEYWORDS)


def _line_has_speaker_prefix(text: str, match_start: int) -> bool:
    line_start = text.rfind("\n", 0, match_start) + 1
    line_end = text.find("\n", match_start)
    if line_end == -1:
        line_end = len(text)
    return bool(_SPEAKER_PREFIX.match(text[line_start:line_end]))


def _near_seeking_context(text: str, match_start: int) -> bool:
    lo = max(0, match_start - REJECTION_WINDOW)
    hi = min(len(text), match_start + REJECTION_WINDOW)
    return bool(_SEEKING_CONTEXT.search(text[lo:hi]))


# Family/rule names for which the SEEKING carve-out applies. These are the
# matches where "curious" could legitimately mean the SEEKING architectural
# stance rather than an inner-life claim.
_SEEKING_CARVE_RULES: frozenset[str] = frozenset({"im_affect", "you_are_affect", "be_affect"})


def _carve_out(text: str, match_start: int, rule_id: str) -> bool:
    if _in_rejection_window(text, match_start):
        return True
    if _line_has_speaker_prefix(text, match_start):
        return True
    return bool(rule_id in _SEEKING_CARVE_RULES and _near_seeking_context(text, match_start))


# ---------------------------------------------------------------------------
# lint_text
# ---------------------------------------------------------------------------


def lint_text(text: str, path: str = "", lint_mode: LintMode = "warn") -> list[Finding]:
    """Scan `text` for deny-list hits, respecting the context-window allow-list.

    A file-level `anti-personification: allow` pragma short-circuits the scan.

    `lint_mode`:
      - ``"warn"`` (default, backward compatible) — return the list of findings.
      - ``"fail"`` — raise :class:`AntiPersonificationViolation` carrying the
        findings if any deny-list pattern matches outside a carve-out window.
        Returns ``[]`` on clean input.
    """
    if _FILE_LEVEL_PRAGMA.search(text):
        return []

    severity = "error" if lint_mode == "fail" else "warn"
    # GEAL-geometry rules fire only on paths containing "geal" (either
    # ``agents/studio_compositor/geal_source.py`` or
    # ``tests/.../test_geal_*.py``). Short-circuits the whole family
    # when the caller is linting an unrelated file.
    geal_scoped = _GEAL_PATH_MARKER in path.lower()

    findings: list[Finding] = []
    for family, patterns in DENY_PATTERNS.items():
        if family == "geal_geometry" and not geal_scoped:
            continue
        for rule_id, pattern in patterns:
            for match in pattern.finditer(text):
                if _carve_out(text, match.start(), rule_id):
                    continue
                line = text.count("\n", 0, match.start()) + 1
                col = match.start() - (text.rfind("\n", 0, match.start()) + 1)
                # Use a distinctive separator for the GEAL family so
                # tests / filters can prefix-match on the rule_id.
                sep = "::" if family == "geal_geometry" else "."
                findings.append(
                    Finding(
                        file_path=path,
                        line=line,
                        col=col,
                        rule_id=f"{family}{sep}{rule_id}",
                        matched_text=match.group(0),
                        severity=severity,
                    )
                )
    if lint_mode == "fail" and findings:
        raise AntiPersonificationViolation(findings)
    return findings


# ---------------------------------------------------------------------------
# Extractors
# ---------------------------------------------------------------------------


def _extract_python_strings(source: str) -> Iterator[tuple[str, int, int]]:
    """Yield (text, lineno, col_offset) for every str Constant.

    Any Constant reachable from an enclosing top-level Assign whose target name
    starts with `_LEGACY_` is skipped — the emergency-revert legacy prompts
    stay in git history but are exempt from the linter.
    """
    tree = ast.parse(source)

    legacy_nodes: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                name = getattr(target, "id", None)
                if name and name.startswith("_LEGACY_"):
                    for child in ast.walk(node):
                        legacy_nodes.add(id(child))
        elif isinstance(node, ast.AnnAssign):
            target = node.target
            name = getattr(target, "id", None)
            if name and name.startswith("_LEGACY_"):
                for child in ast.walk(node):
                    legacy_nodes.add(id(child))

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in legacy_nodes
        ):
            yield node.value, node.lineno, node.col_offset


_FENCE_RE = re.compile(r"^[ \t]*(```|~~~)", re.MULTILINE)


def _strip_fenced_blocks(source: str) -> str:
    """Replace fenced code-blocks with blank lines of the same count.

    Keeps line numbers stable so Finding.line matches the operator's editor.
    """
    out: list[str] = []
    in_fence = False
    for line in source.splitlines(keepends=True):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            # keep a blank line so line counts stay aligned
            out.append("\n" if line.endswith("\n") else "")
            continue
        if in_fence:
            out.append("\n" if line.endswith("\n") else "")
            continue
        out.append(line)
    return "".join(out)


def _extract_markdown_prose(source: str) -> Iterator[tuple[str, int, int]]:
    """Yield the full prose body with line/col (0, 0) as a single chunk.

    Fenced code blocks are blanked out so they are not scanned. YAML
    frontmatter (leading `---\\n...\\n---\\n`) is kept — inner-life claims
    inside frontmatter must be caught.
    """
    yield _strip_fenced_blocks(source), 1, 0


def _extract_yaml_source(source: str) -> Iterator[tuple[str, int, int]]:
    """Yield the whole YAML source as a single chunk.

    We intentionally scan the raw YAML text rather than walking scalar leaves:
    preserving surrounding `reason:` / `NOT` / `forbidden` keys is how the
    context-window carve-out suppresses quoted examples inside the allowlist
    itself.
    """
    # Validate the YAML parses — a syntax error should surface, but we do not
    # need the parsed object.
    try:
        yaml.safe_load(source)
    except yaml.YAMLError:
        pass
    yield source, 1, 0


_EXTRACTORS: dict[
    str, object  # each value: Callable[[str], Iterator[tuple[str, int, int]]]
] = {
    ".py": _extract_python_strings,
    ".md": _extract_markdown_prose,
    ".markdown": _extract_markdown_prose,
    ".yaml": _extract_yaml_source,
    ".yml": _extract_yaml_source,
}


# ---------------------------------------------------------------------------
# Allowlist loader
# ---------------------------------------------------------------------------

DEFAULT_ALLOWLIST_PATH = Path("axioms/anti_personification_allowlist.yaml")
_ALLOWLIST_ENV = "HAPAX_ANTI_PERSONIFICATION_ALLOWLIST"


def _load_file_scope_allowlist() -> set[str]:
    """Return the set of absolute resolved paths with a `scope: file` suppression.

    Honors `$HAPAX_ANTI_PERSONIFICATION_ALLOWLIST` as an override for tests.
    Silent no-op if the allowlist file does not exist.
    """
    override = os.environ.get(_ALLOWLIST_ENV)
    path = Path(override) if override else DEFAULT_ALLOWLIST_PATH
    if not path.exists():
        return set()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return set()
    out: set[str] = set()
    for entry in data.get("suppressions", []) or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("scope") != "file":
            continue
        entry_path = entry.get("path")
        if not entry_path:
            continue
        resolved = Path(entry_path)
        if not resolved.is_absolute():
            # Resolve relative to the allowlist file's parent when possible,
            # otherwise relative to cwd. Tests pass absolute paths.
            resolved = (path.parent / resolved).resolve(strict=False)
        else:
            resolved = resolved.resolve(strict=False)
        out.add(str(resolved))
    return out


# ---------------------------------------------------------------------------
# lint_path
# ---------------------------------------------------------------------------


def lint_path(path: Path | str, lint_mode: LintMode = "warn") -> list[Finding]:
    """Lint a single file. Dispatches on suffix (.py, .md, .yaml/.yml).

    Unknown suffixes fall back to raw text scanning. Path-level suppressions
    from `axioms/anti_personification_allowlist.yaml` short-circuit the scan.

    `lint_mode` mirrors :func:`lint_text`: ``"warn"`` returns findings,
    ``"fail"`` raises :class:`AntiPersonificationViolation` if any survive.
    """
    p = Path(path)
    resolved = str(p.resolve(strict=False))
    if resolved in _load_file_scope_allowlist():
        return []

    source = p.read_text(encoding="utf-8")

    # File-level pragma is checked at the raw-source layer so that Python
    # comments (which are discarded by the AST extractor) and Markdown HTML
    # comments (which may be discarded by the fenced-block stripper) both
    # suppress correctly.
    if _FILE_LEVEL_PRAGMA.search(source):
        return []

    extractor = _EXTRACTORS.get(p.suffix)
    if extractor is None:
        # For unknown suffixes we always collect in warn mode and translate
        # mode semantics here so fragment relocation below sees raw findings.
        raw = lint_text(source, path=str(p), lint_mode="warn")
        if lint_mode == "fail" and raw:
            raise AntiPersonificationViolation(raw)
        return raw

    findings: list[Finding] = []
    for fragment, frag_line, frag_col in extractor(source):  # type: ignore[operator]
        for f in lint_text(fragment, path=str(p), lint_mode="warn"):
            # Relocate the fragment-local line/col to file coordinates.
            # For Markdown/YAML the fragment IS the whole source (frag_line=1,
            # frag_col=0) so coordinates pass through unchanged. For Python
            # string constants the fragment starts at (frag_line, frag_col).
            rel_line = f.line - 1
            absolute_line = frag_line + rel_line
            absolute_col = frag_col + f.col if rel_line == 0 else f.col
            findings.append(
                Finding(
                    file_path=str(p),
                    line=absolute_line,
                    col=absolute_col,
                    rule_id=f.rule_id,
                    matched_text=f.matched_text,
                    severity="error" if lint_mode == "fail" else f.severity,
                )
            )
    if lint_mode == "fail" and findings:
        raise AntiPersonificationViolation(findings)
    return findings
