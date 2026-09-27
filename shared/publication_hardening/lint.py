"""Publication hardening lint — structural checks beyond Vale's capabilities."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from shared.anti_personification_linter import lint_text as lint_anti_personification_text


@dataclass(frozen=True)
class LintFinding:
    file: str
    line: int
    level: str  # "error" | "warning"
    rule: str
    message: str


OVERCLAIM_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (
        re.compile(r"\bevery file write\b", re.IGNORECASE),
        "error",
        "Scope file-write coverage to governed paths and supporting receipts.",
    ),
    (
        re.compile(r"\bevery commit\b", re.IGNORECASE),
        "error",
        "Scope commit coverage to governed paths and supporting receipts.",
    ),
    (
        re.compile(r"\bevery deployment decision\b", re.IGNORECASE),
        "error",
        "Scope deployment coverage to governed paths and supporting receipts.",
    ),
    (
        re.compile(r"\bphysically cannot\b", re.IGNORECASE),
        "error",
        "Replace physical impossibility language with governed-path blocking language.",
    ),
    (
        re.compile(r"\bno test results,\s*no push\b", re.IGNORECASE),
        "error",
        "Replace slogan form with scoped push-gate evidence language.",
    ),
    (
        re.compile(r"\bconstitutionally incapable\b", re.IGNORECASE),
        "error",
        "Avoid absolute incapability claims; scope to mechanical gates on governed paths.",
    ),
    (
        re.compile(r"\ball code, infrastructure, and governance mechanisms\b", re.IGNORECASE),
        "error",
        "Avoid all-surface production claims unless each surface has a current receipt.",
    ),
    (
        re.compile(r"\bexistence proof\b", re.IGNORECASE),
        "warning",
        "Existence-proof claims need an audit receipt and may need hypothesis framing.",
    ),
    (
        re.compile(r"\bunbounded\b", re.IGNORECASE),
        "warning",
        "Unbounded value/resource language needs a claim ceiling or citation.",
    ),
    (
        re.compile(r"\bShapley Values? for Output Tokens\b", re.IGNORECASE),
        "warning",
        "Token Capital Shapley framing is audit-quarantined until repaired.",
    ),
)

GENERATED_TEXT_BANNED_TERMS: tuple[str, ...] = (
    "paradigm",
    "leverage",
    "leverages",
    "leveraging",
    "leveraged",
    "synergy",
    "synergies",
    "synergistic",
    "utilize",
    "utilizes",
    "utilizing",
    "utilization",
    "facilitate",
    "facilitates",
    "facilitating",
    "facilitation",
    "operationalize",
    "operationalizes",
    "operationalizing",
    "incentivize",
    "incentivizes",
    "incentivizing",
    "holistic",
    "holistically",
    "scalable",
    "best-in-class",
    "best in class",
    "cutting-edge",
    "cutting edge",
    "game-changer",
    "game changer",
    "move the needle",
    "low-hanging fruit",
    "deep dive",
    "circle back",
    "touch base",
    "at the end of the day",
    "going forward",
    "stakeholder alignment",
    "value proposition",
    "thought leader",
    "thought leadership",
    "disruptive",
    "innovative solution",
    "paradigm shift",
    "ecosystem",
    "empower",
    "empowers",
    "empowering",
    "democratize",
    "democratizes",
    "democratizing",
    "robust",
    "seamless",
    "seamlessly",
    "next-generation",
    "next generation",
    "world-class",
    "world class",
    "bleeding-edge",
    "bleeding edge",
    "best practice",
    "best practices",
    "mission-critical",
    "mission critical",
    "end-to-end",
    "turnkey",
    "actionable insights",
    "data-driven",
)

GENERATED_TEXT_BANNED_TERMS_PATTERN = re.compile(
    r"\b(?:"
    + "|".join(re.escape(term).replace(r"\ ", r"\s+") for term in GENERATED_TEXT_BANNED_TERMS)
    + r")\b",
    re.IGNORECASE,
)

FORMAL_REGISTER_PATTERNS: tuple[tuple[re.Pattern[str], str, str, str], ...] = (
    (
        GENERATED_TEXT_BANNED_TERMS_PATTERN,
        "error",
        "Hapax.FormalRegister",
        "Use concrete publication prose instead of generic marketing or jargon terms.",
    ),
    (
        re.compile(r"[\U0001F300-\U0001FAFF]"),
        "error",
        "Hapax.FormalRegister",
        "Remove emoji from publication prose.",
    ),
    (
        re.compile(r"!{2,}"),
        "error",
        "Hapax.FormalRegister",
        "Use formal punctuation; repeated exclamation marks are not publication prose.",
    ),
    (
        re.compile(
            r"^\s*(so[\s,]|today\s+we['\u2019]?re|welcome\s+back|hey\s+"
            r"(everyone|everybody|friends|folks|guys|y['\u2019]?all)|what['\u2019]?s\s+up|"
            r"in\s+today['\u2019]?s\s+(video|stream|episode|broadcast))",
            re.IGNORECASE,
        ),
        "error",
        "Hapax.FormalRegister",
        "Use observer-facing research prose, not creator-opener language.",
    ),
    (
        re.compile(
            r"\b(subscribe|like\s+and\s+(follow|subscribe|share)|smash\s+"
            r"(that\s+)?(like|subscribe)|hit\s+the\s+bell|comment\s+"
            r"(below|down\s+below)|don['\u2019]?t\s+forget\s+to\s+"
            r"(like|subscribe|share))\b",
            re.IGNORECASE,
        ),
        "error",
        "Hapax.FormalRegister",
        "Remove creator-economy calls to action from research publication prose.",
    ),
    (
        re.compile(
            r"\b(amazing|incredible|absolutely\s+"
            r"(stunning|beautiful|amazing|incredible|phenomenal)|"
            r"mind[\s-]?blowing|game[\s-]?changer)\b",
            re.IGNORECASE,
        ),
        "error",
        "Hapax.FormalRegister",
        "Replace hollow affirmation with concrete evidence or omit it.",
    ),
)

SYSTEM_INNER_LIFE_PATTERNS: tuple[tuple[re.Pattern[str], str, str, str], ...] = (
    (
        re.compile(
            r"\b(?:Hapax|the system|this system|system|the agent|agent|"
            r"the publisher|publisher|the orchestrator|orchestrator|"
            r"the bus|bus)\s+(feels|thinks|believes|wants|cares|hopes|"
            r"fears|perceives|trusts|prefers|remembers|knows|understands|"
            r"intuits)\b",
            re.IGNORECASE,
        ),
        "error",
        "Hapax.NonAnthropomorphicRegister",
        "Use operational vocabulary; do not attribute inner life to Hapax or a system component.",
    ),
    (
        re.compile(r"\bHapax['\u2019]?s voice\b", re.IGNORECASE),
        "error",
        "Hapax.NonAnthropomorphicRegister",
        "Name the concrete TTS/audio surface instead of treating voice as a personality surface.",
    ),
    (
        re.compile(
            r"\b(your feelings|your show|your opinions|your affect|"
            r"your personality|alien mind|distributed mind|"
            r"operator-flavou?red|operator-colou?red)\b",
            re.IGNORECASE,
        ),
        "error",
        "Hapax.NonAnthropomorphicRegister",
        "Remove human-host, personality, or inner-life framing.",
    ),
)


def check_heading_hierarchy(path: Path) -> list[LintFinding]:
    """Flag heading level skips (e.g., h2 directly to h4)."""
    return check_heading_hierarchy_text(
        path.read_text(encoding="utf-8"),
        file_label=str(path),
    )


def check_heading_hierarchy_text(text: str, *, file_label: str = "<artifact>") -> list[LintFinding]:
    """Flag heading level skips in raw Markdown text."""
    findings: list[LintFinding] = []
    heading_re = re.compile(r"^(#{1,6})\s")
    prev_level = 0

    for lineno, line in enumerate(text.splitlines(), start=1):
        m = heading_re.match(line)
        if not m:
            continue
        level = len(m.group(1))
        if prev_level > 0 and level > prev_level + 1:
            findings.append(
                LintFinding(
                    file=file_label,
                    line=lineno,
                    level="error",
                    rule="Hapax.HeadingHierarchy",
                    message=(f"Heading skips from h{prev_level} to h{level}. Don't skip levels."),
                )
            )
        prev_level = level

    return findings


def check_public_claim_overreach(path: Path) -> list[LintFinding]:
    """Flag public-claim phrases that exceeded audit-supported scope."""
    return check_public_claim_overreach_text(
        path.read_text(encoding="utf-8"),
        file_label=str(path),
    )


def check_public_claim_overreach_text(
    text: str,
    *,
    file_label: str = "<artifact>",
) -> list[LintFinding]:
    """Flag public-claim phrases in raw text that exceeded audit-supported scope."""
    findings: list[LintFinding] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for pattern, level, message in OVERCLAIM_PATTERNS:
            if not pattern.search(line):
                continue
            findings.append(
                LintFinding(
                    file=file_label,
                    line=lineno,
                    level=level,
                    rule="Hapax.PublicClaimOverreach",
                    message=message,
                )
            )
    return findings


def check_formal_register_text(
    text: str,
    *,
    file_label: str = "<artifact>",
) -> list[LintFinding]:
    """Flag generated-publication prose that violates formal register."""
    findings: list[LintFinding] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for pattern, level, rule, message in FORMAL_REGISTER_PATTERNS:
            if not pattern.search(line):
                continue
            findings.append(
                LintFinding(
                    file=file_label,
                    line=lineno,
                    level=level,
                    rule=rule,
                    message=message,
                )
            )
    return findings


def check_non_anthropomorphic_register_text(
    text: str,
    *,
    file_label: str = "<artifact>",
) -> list[LintFinding]:
    """Flag inner-life or personality framing in publication prose."""
    findings: list[LintFinding] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for pattern, level, rule, message in SYSTEM_INNER_LIFE_PATTERNS:
            if not pattern.search(line):
                continue
            findings.append(
                LintFinding(
                    file=file_label,
                    line=lineno,
                    level=level,
                    rule=rule,
                    message=message,
                )
            )

    for finding in lint_anti_personification_text(text, path=file_label):
        findings.append(
            LintFinding(
                file=file_label,
                line=finding.line,
                level="error",
                rule="Hapax.NonAnthropomorphicRegister",
                message=(
                    f"Anti-personification finding {finding.rule_id}: "
                    "describe operations, evidence, or readback instead."
                ),
            )
        )
    return findings


REGISTER_CARRIAGE_RULE = "Hapax.RegisterCarriage"

# The six devices, verbatim from AMENDMENT-ADOPTED-register-writerly-carriage-20260925.md
# (sha256 42dac12b60f5e99c5e42b5b457099bd2f06239820b4a839c174f477630d35989).
REGISTER_CARRIAGE_DEVICES: tuple[tuple[int, str], ...] = (
    (1, "fragments or verbless sentences used for effect"),
    (2, "tricolon: three or more parallel phrases used for rhythm, not to enumerate real items"),
    (3, "aphorisms, maxims, slogans, taglines and closing flourishes"),
    (4, "antithesis for effect"),
    (5, "rhetorical questions the text does not put to the reader to answer"),
    (
        6,
        "dramatic one-line paragraphs, and series of short declaratives or imperatives for emphasis",
    ),
)

# The amendment's "Not forbidden" list as DOCUMENTED KEEP DISPOSITIONS, never silent exemptions:
# a finding in one of these shapes still carries the keep category it may be disposed under.
REGISTER_KEEP_DISPOSITIONS: tuple[tuple[str, str], ...] = (
    ("section_label", "plain label or heading that names a section"),
    ("literal_enumeration", "literal enumeration of real items"),
    ("answered_question", "question the section literally answers"),
    ("data_line", "data line"),
    ("plain_instruction", "plain instruction"),
    ("scope_negation", "scope statement whose negation carries a limit"),
)

_REGISTER_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\u201c\"'(])")
# The FRAGMENT device's finite-verb test, quiet on plain prose: the port's cheap `\w+(ed|es)\b`
# proxy fired on participles and imperatives and swallowed real fragments. Keeps auxiliaries,
# pronoun+verb, and an -ed/-es inflection not hyphen-preceded, plus an imperative carve-out.
_REGISTER_FINITE_AUX = re.compile(
    r"\b(is|are|was|were|be|been|being|am|has|have|had|do|does|did|can|could|will|would|shall|"
    r"should|may|might|must|isn't|aren't|wasn't|don't|doesn't|didn't|won't|cannot|can't)\b"
    r"|\b(it|this|that|they|we|he|she|who|which) \w+s\b"
    r"|(?<!-)\b\w+(?:ed|es)\b",
    re.IGNORECASE,
)


def _register_is_fragment(unit: str) -> bool:
    """Over-inclusive: a unit with no finite-verb signal, or an imperative-led short unit."""
    head = unit.split()[0] if unit.split() else ""
    if head and _REGISTER_IMPERATIVE_HEAD.match(unit) and _register_words(unit) <= 12:
        # A bare imperative is a fragment even though its head may carry an -ed/-s suffix.
        return not _REGISTER_FINITE_AUX.search(unit.split(" ", 1)[1] if " " in unit else "")
    return not _REGISTER_FINITE_AUX.search(unit)


_REGISTER_IMPERATIVE_HEAD = re.compile(
    r"\A(?:proceed|download|use|read|see|check|inspect|run|open|fix|test|score|record|publish|state|keep|position|"
    r"visit|send|add|remove|report|review|note|reproduce|recompute|follow|apply)\b",
    re.IGNORECASE,
)
_REGISTER_SCOPE_NEGATION = re.compile(
    r"\b(?:does not|do not|is not|are not|cannot|not a|not an|never)\b[^.;]{0,80}"
    r"\b(?:verif\w+|certif\w+|guarantee\w*|evidence|proof|measure\w*|identif\w+|truth|"
    r"endorse\w*|authoriz\w*|permission|exhaustive|replicat\w+)\b",
    re.IGNORECASE,
)
_REGISTER_ENUMERATION = re.compile(r"\s·\s|\s\((?:\d+|[a-z])\)\s|\A\s*\d+\.\s")
#: A comma series ("Apples, oranges, and pears.") is the commonest literal enumeration and was
#: flagged with no keep disposition: two commas in one short, clause-unbroken line is an
#: enumeration, not a tricolon.
_REGISTER_COMMA_SERIES = re.compile(r"\A[^.;:!?\n]*,[^,.;:!?\n]*,[^,.;:!?\n]*[.!?]?\Z")
_REGISTER_COMMA_SERIES_MAX_WORDS = 16


def _register_words(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9\u2019'%-]+", text))


def _register_sentences(unit: str) -> list[str]:
    return [part.strip() for part in _REGISTER_SENTENCE_SPLIT.split(unit) if part.strip()]


def _register_units(text: str) -> list[tuple[int, str]]:
    """Block units with their first 1-based line number: blank-line separated paragraphs."""
    units: list[tuple[int, str]] = []
    current: list[str] = []
    start = 0
    for lineno, line in enumerate(text.splitlines(), start=1):
        if line.strip():
            if not current:
                start = lineno
            current.append(line.strip())
            continue
        if current:
            units.append((start, " ".join(current)))
            current = []
    if current:
        units.append((start, " ".join(current)))
    return units


def _register_keep_hint(unit: str, sentences: list[str]) -> str | None:
    """The keep category this unit may be disposed under, when its shape names one."""
    stripped = unit.strip()
    if stripped.endswith("?") and re.match(r"\A\s*(?:\d+\.|\(\d+\))\s", stripped):
        return "answered_question"
    if (
        _REGISTER_ENUMERATION.match(stripped)
        or "\u00b7" in stripped
        or (
            _REGISTER_COMMA_SERIES.match(stripped)
            and _register_words(stripped) <= _REGISTER_COMMA_SERIES_MAX_WORDS
        )
    ):
        return "literal_enumeration"
    if _REGISTER_SCOPE_NEGATION.search(stripped):
        return "scope_negation"
    if re.search(r"\d", stripped) and len(re.findall(r"\d", stripped)) >= max(
        2, len(stripped.split()) // 3
    ):
        return "data_line"
    if _REGISTER_IMPERATIVE_HEAD.match(stripped) and not stripped.endswith(("!", "?")):
        return "plain_instruction"
    if (
        len(sentences) == 1
        and len(stripped.split()) <= 6
        and not stripped.endswith((".", "!", "?"))
    ):
        return "section_label"
    return None


#: Block-level tags: one register unit each, linted by block units rather than tag-stripped text
#: (stripping merges nav chrome and invents findings). A wrapper holding a nested block is skipped.
_REGISTER_BLOCK_TAGS = (
    "p|h[1-6]|li|td|th|dd|dt|blockquote|figcaption|"
    "div|main|section|article|header|footer|aside|figure"
)
#: Non-content regions of a built page: never a register unit.
_REGISTER_HTML_BOILERPLATE = "nav|script|style|head|noscript|template|svg"


def _register_html_units(text: str) -> list[tuple[int, str]]:
    """Leaf block units from built HTML, plus a residue fallback, with 1-based line numbers.

    A body containing a block element is not a unit (an outer ``<li>`` yields its ``<p>``s), and
    copy outside the block tags is linted by a residue pass over non-boilerplate text.
    """
    boilerplate = re.compile(
        rf"<({_REGISTER_HTML_BOILERPLATE})\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL
    )
    masked = _register_blank_spans(text, [(m.start(), m.end()) for m in boilerplate.finditer(text)])
    block = _REGISTER_BLOCK_TAGS
    body = rf"(?:(?!<\s*/?\s*(?:{block})\b).)*"
    units: list[tuple[int, str]] = []
    block_spans: list[tuple[int, int]] = []
    for match in re.finditer(
        rf"<({block})\b[^>]*>({body})</\1>", masked, re.IGNORECASE | re.DOTALL
    ):
        block_spans.append((match.start(), match.end()))
        inner = re.sub(r"<[^>]+>", " ", match.group(2))
        inner = re.sub(r"\s+", " ", inner).strip()
        if inner:
            units.append((text[: match.start()].count("\n") + 1, inner))
    residue = re.sub(r"<[^>]+>", " ", _register_blank_spans(masked, block_spans))
    units.extend(_register_units(residue))
    units.sort(key=lambda unit: unit[0])
    return units


def _register_blank_spans(text: str, spans: list[tuple[int, int]]) -> str:
    """Blank each span, preserving newlines so every later line number stays true."""
    characters = list(text)
    for start, end in spans:
        for index in range(start, end):
            if characters[index] != "\n":
                characters[index] = " "
    return "".join(characters)


#: File extensions linted as built HTML. Chosen by extension, never by content.
_REGISTER_HTML_SUFFIXES = (".html", ".htm")


def _register_parser_mode(file_label: str) -> str:
    """``html`` or ``text``, by the file's extension. A content sniff was a fail-open: a Markdown
    draft merely *mentioning* ``<p>`` was read as HTML, its paragraphs skipped, and the gate passed
    it silently. A path-less label is text."""
    return "html" if Path(file_label).suffix.lower() in _REGISTER_HTML_SUFFIXES else "text"


def check_register_carriage_text(
    text: str,
    *,
    file_label: str = "<artifact>",
) -> list[LintFinding]:
    """Flag writerly and rhetorical carriage (the six devices), over-inclusive by design.

    One finding per (unit, device): the device number, the line, the text, and (when the unit's
    shape names one) the documented keep disposition it may be recorded under.
    """
    findings: list[LintFinding] = []
    units = (
        _register_html_units(text)
        if _register_parser_mode(file_label) == "html"
        else _register_units(text)
    )
    for lineno, unit in units:
        if _register_words(unit) < 3:
            continue
        sentences = _register_sentences(unit)
        short = [s for s in sentences if _register_words(s) <= 6]
        hint = _register_keep_hint(unit, sentences)
        hint_text = (
            f" Keep disposition available: {dict(REGISTER_KEEP_DISPOSITIONS)[hint]}."
            if hint
            else ""
        )
        hits: list[tuple[int, str]] = []

        fragment = next(
            (s for s in sentences if 3 <= _register_words(s) <= 14 and _register_is_fragment(s)),
            None,
        )
        if (
            fragment is None
            and not unit.endswith((".", "!", "?"))
            and 3 <= _register_words(unit) <= 14
            and _register_is_fragment(unit)
        ):
            fragment = unit
        if fragment is not None:
            hits.append((1, fragment))
        clauses = (
            [clause.strip() for clause in re.split(r"[,;]", sentences[0]) if clause.strip()]
            if sentences
            else []
        )
        core_clauses = [c for c in clauses if _register_words(c) <= 8]
        parallel_wh = re.findall(r"\bwhat\b[^,;.]{0,80}", unit)
        series_parts = [part.strip() for part in re.split(r"\s[·/]\s", unit) if part.strip()]
        if (
            len(short) >= 3
            or (len(clauses) >= 3 and len(core_clauses) >= 2)
            or len(parallel_wh) >= 3
            or len(series_parts) >= 3
        ):
            evidence = (
                " / ".join(short[:3])
                if len(short) >= 3
                else (
                    " / ".join(series_parts[:3])
                    if len(series_parts) >= 3
                    else (sentences[0] if sentences else unit)
                )
            )
            hits.append((2, evidence))
        if len(sentences) >= 2 and _register_words(sentences[-1]) <= 6:
            hits.append((3, sentences[-1]))
        elif (
            (
                len(sentences) == 1
                and _register_words(unit) <= 8
                and not re.match(r"\A\s*(?:what|which|how|why|when|where)\b", unit, re.IGNORECASE)
            )
            or _register_words(unit) <= 16
            and re.search(
                r"\b(?:no|not|never)\b[^.;]{0,50}\b(?:allegiance|outcome|score|correction|evidence|"
                r"guarantee|permission|certification|credit|truth|proof|register\w*|claims?|promise\w*)\b",
                unit,
                re.IGNORECASE,
            )
        ):
            hits.append((3, unit))
        if (
            re.search(r"\b(?:is|are|was|were) not\b[^.;]{0,60}\b(?:or|but)\b", unit, re.IGNORECASE)
            or re.search(r"\b\w+(?: \w+){0,3}, not (?:a |an |the )?\w+", unit)
            or re.search(r"\bnot\b[^.;]{1,60}\bbut\b", unit, re.IGNORECASE)
            or re.search(r"\bnot\b[^.;]{1,40};", unit, re.IGNORECASE)
        ):
            hits.append((4, unit))
        for sentence in sentences:
            if sentence.endswith("?"):
                hits.append((5, sentence))
                break
        imperative_units = sentences + [
            part.strip()
            for part in re.split(r"\s[·/]\s", unit)
            if part.strip() and part.strip() not in sentences
        ]
        imperatives = [
            s
            for s in imperative_units
            if _REGISTER_IMPERATIVE_HEAD.match(s) and _register_words(s) <= 12
        ]
        if len(sentences) >= 2 and all(_register_words(s) <= 6 for s in sentences):
            hits.append((6, " / ".join(sentences)))
        elif len(sentences) == 1 and _register_words(unit) <= 7 and unit.endswith("."):
            hits.append((6, unit))
        elif len(imperatives) >= 2:
            hits.append((6, " / ".join(imperatives)))
        elif len(series_parts) >= 2 and any(
            _REGISTER_IMPERATIVE_HEAD.match(part) for part in series_parts
        ):
            hits.append((6, " / ".join(series_parts[:3])))
        elif (
            len(sentences) >= 2
            and _register_words(sentences[0]) <= 6
            and re.match(r"\A\s*(?:what|which|how|why|when|where)\b", sentences[0], re.IGNORECASE)
        ):
            hits.append((6, sentences[0]))

        names = dict(REGISTER_CARRIAGE_DEVICES)
        for device, evidence in hits:
            findings.append(
                LintFinding(
                    file=file_label,
                    line=lineno,
                    level="warning",
                    rule=REGISTER_CARRIAGE_RULE,
                    message=(
                        f"Device {device} ({names[device]}): {evidence!r}. Rewrite as a plain "
                        f"statement that carries the same content."
                        f"{hint_text}"
                    ),
                )
            )

    return findings


def run_vale(path: Path, config: Path | None = None) -> list[LintFinding]:
    """Run Vale and parse JSON output into LintFindings."""
    import json

    cmd = ["vale", "--output=JSON"]
    if config:
        cmd.append(f"--config={config}")
    cmd.append(str(path))

    findings: list[LintFinding] = []
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        return findings

    if not result.stdout.strip():
        return findings

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return findings

    for file_path, alerts in data.items():
        for alert in alerts:
            severity = alert.get("Severity", "warning").lower()
            findings.append(
                LintFinding(
                    file=file_path,
                    line=alert.get("Line", 0),
                    level=severity if severity in ("error", "warning") else "warning",
                    rule=alert.get("Check", "unknown"),
                    message=alert.get("Message", ""),
                )
            )

    return findings


def lint_file(path: Path, config: Path | None = None) -> list[LintFinding]:
    """Run all lint checks on a single file."""
    findings: list[LintFinding] = []
    findings.extend(check_heading_hierarchy(path))
    findings.extend(check_public_claim_overreach(path))
    text = path.read_text(encoding="utf-8")
    findings.extend(check_formal_register_text(text, file_label=str(path)))
    findings.extend(check_register_carriage_text(text, file_label=str(path)))
    findings.extend(check_non_anthropomorphic_register_text(text, file_label=str(path)))
    findings.extend(run_vale(path, config=config))
    return findings


def lint_text(text: str, *, file_label: str = "<artifact>") -> list[LintFinding]:
    """Run publication lint checks that do not require a file path."""
    findings: list[LintFinding] = []
    findings.extend(check_heading_hierarchy_text(text, file_label=file_label))
    findings.extend(check_public_claim_overreach_text(text, file_label=file_label))
    findings.extend(check_formal_register_text(text, file_label=file_label))
    findings.extend(check_register_carriage_text(text, file_label=file_label))
    findings.extend(check_non_anthropomorphic_register_text(text, file_label=file_label))
    return findings
