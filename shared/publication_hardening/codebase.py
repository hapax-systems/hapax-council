"""Deterministic codebase consistency checks for publication hardening."""

from __future__ import annotations

import ast
import re
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CodebaseDecision(StrEnum):
    """Decision for a verifier finding or full report."""

    PASS = "pass"
    HOLD = "hold"
    REJECT = "reject"


class CodebaseModel(BaseModel):
    """Strict immutable base for codebase verification models."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class CodebaseFinding(CodebaseModel):
    """One deterministic child predicate."""

    check_id: str
    decision: CodebaseDecision
    message: str
    value: str | None = None
    line: int | None = Field(default=None, ge=1)
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)


class NumericClaim(CodebaseModel):
    """A numeric claim extracted from publication text."""

    text: str
    value: str
    subject: str
    line: int


class CurrentnessClaim(CodebaseModel):
    """A currentness-sensitive claim extracted from publication text."""

    text: str
    keyword: str
    line: int


class CodebaseVerificationReport(CodebaseModel):
    """Structured verifier report for later publication gate aggregation."""

    schema_version: Literal[1] = 1
    decision: CodebaseDecision
    findings: tuple[CodebaseFinding, ...] = Field(default_factory=tuple)
    numeric_claims: tuple[NumericClaim, ...] = Field(default_factory=tuple)
    currentness_claims: tuple[CurrentnessClaim, ...] = Field(default_factory=tuple)

    def passes(self) -> bool:
        return self.decision == CodebaseDecision.PASS


ShellSyntaxChecker = Callable[[str], str | None]

_CODE_FENCE_RE = re.compile(
    r"(?P<fence>```|~~~)(?P<lang>[A-Za-z0-9_+-]*)[^\n]*\n(?P<body>.*?)(?P=fence)",
    re.DOTALL,
)
_PATH_RE = re.compile(
    r"(?<![\w:/.-])(?P<path>(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+"
    r"\.(?:py|md|yaml|yml|json|toml|sh|rs|ts|tsx|js|jsx|wgsl|service|timer|conf))"
)
_BACKTICK_RE = re.compile(r"`([^`\n]+)`")
_MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)\s]+)\)")
_NUMBER_RE = re.compile(
    r"\b(?P<value>\d+(?:,\d{3})*(?:\.\d+)?\+?)\s+"
    r"(?P<subject>[A-Za-z][A-Za-z0-9_./-]*(?:\s+[A-Za-z][A-Za-z0-9_./-]*){0,5})"
)
_CURRENTNESS_RE = re.compile(
    r"\b(current|currently|now|live|latest|today)\b",
    re.IGNORECASE,
)


def verify_publication_codebase(
    text: str,
    *,
    repo_root: Path | str,
    numeric_expectations: Mapping[str, object] | None = None,
    currentness_evidence_refs: Sequence[str] = (),
    shell_syntax_checker: ShellSyntaxChecker | None = None,
) -> CodebaseVerificationReport:
    """Verify publication text against local repo facts.

    This function never performs network calls and never executes draft code.
    Shell snippets are syntax-checked only; tests may inject the checker.
    """

    verifier = CodebaseConsistencyVerifier(
        repo_root=Path(repo_root),
        numeric_expectations=numeric_expectations,
        currentness_evidence_refs=currentness_evidence_refs,
        shell_syntax_checker=shell_syntax_checker,
    )
    return verifier.verify_text(text)


class CodebaseConsistencyVerifier:
    """Local deterministic verifier for publication-hardening gates."""

    def __init__(
        self,
        *,
        repo_root: Path,
        numeric_expectations: Mapping[str, object] | None = None,
        currentness_evidence_refs: Sequence[str] = (),
        shell_syntax_checker: ShellSyntaxChecker | None = None,
    ) -> None:
        self.repo_root = repo_root.resolve()
        self.numeric_expectations = dict(numeric_expectations or {})
        self.currentness_evidence_refs = tuple(str(ref) for ref in currentness_evidence_refs)
        self.shell_syntax_checker = shell_syntax_checker or _default_shell_syntax_checker

    def verify_text(self, text: str) -> CodebaseVerificationReport:
        findings: list[CodebaseFinding] = []

        code_spans = _code_spans(text)
        findings.extend(self._check_repo_paths(text, code_spans))
        findings.extend(self._check_code_fences(text))

        numeric_claims = _extract_numeric_claims(_strip_code_fences(text))
        findings.extend(self._check_numeric_claims(numeric_claims))

        currentness_claims = _extract_currentness_claims(_strip_code_fences(text))
        findings.extend(self._check_currentness_claims(currentness_claims))

        return CodebaseVerificationReport(
            decision=_aggregate_decision(findings),
            findings=tuple(findings),
            numeric_claims=tuple(numeric_claims),
            currentness_claims=tuple(currentness_claims),
        )

    def _check_repo_paths(
        self,
        text: str,
        code_spans: Sequence[tuple[int, int]],
    ) -> list[CodebaseFinding]:
        findings: list[CodebaseFinding] = []
        seen: set[str] = set()
        for ref, offset in _extract_path_refs(text):
            if _offset_in_spans(offset, code_spans):
                continue
            if ref in seen:
                continue
            seen.add(ref)
            resolved = _resolve_repo_path(ref, self.repo_root)
            line = _line_for_offset(text, offset)
            if resolved is None:
                findings.append(
                    CodebaseFinding(
                        check_id="repo_path_outside_root",
                        decision=CodebaseDecision.HOLD,
                        message=f"Path reference is outside repo root or unsupported: {ref}",
                        value=ref,
                        line=line,
                    )
                )
            elif resolved.exists():
                findings.append(
                    CodebaseFinding(
                        check_id="repo_path_exists",
                        decision=CodebaseDecision.PASS,
                        message=f"Path exists: {ref}",
                        value=ref,
                        line=line,
                        evidence_refs=(str(resolved),),
                    )
                )
            else:
                findings.append(
                    CodebaseFinding(
                        check_id="repo_path_missing",
                        decision=CodebaseDecision.HOLD,
                        message=f"Path reference is missing: {ref}",
                        value=ref,
                        line=line,
                    )
                )
        return findings

    def _check_code_fences(self, text: str) -> list[CodebaseFinding]:
        findings: list[CodebaseFinding] = []
        for fence in _CODE_FENCE_RE.finditer(text):
            lang = fence.group("lang").lower()
            body = fence.group("body")
            line = _line_for_offset(text, fence.start())
            if lang in {"py", "python"}:
                findings.extend(self._check_python_snippet(body, line))
            elif lang in {"sh", "shell", "bash"}:
                findings.append(self._check_shell_snippet(body, line))
        return findings

    def _check_python_snippet(self, body: str, line: int) -> list[CodebaseFinding]:
        try:
            tree = ast.parse(body)
        except SyntaxError as exc:
            return [
                CodebaseFinding(
                    check_id="python_snippet_syntax",
                    decision=CodebaseDecision.REJECT,
                    message=f"Python snippet syntax error: {exc.msg}",
                    line=line + max((exc.lineno or 1) - 1, 0),
                )
            ]

        findings = [
            CodebaseFinding(
                check_id="python_snippet_syntax",
                decision=CodebaseDecision.PASS,
                message="Python snippet parses with ast.parse",
                line=line,
            )
        ]
        findings.extend(self._check_imports(tree, line))
        return findings

    def _check_shell_snippet(self, body: str, line: int) -> CodebaseFinding:
        error = self.shell_syntax_checker(body)
        if error is None:
            return CodebaseFinding(
                check_id="shell_snippet_syntax",
                decision=CodebaseDecision.PASS,
                message="Shell snippet syntax check passed",
                line=line,
            )
        return CodebaseFinding(
            check_id="shell_snippet_syntax",
            decision=CodebaseDecision.REJECT,
            message=f"Shell snippet syntax error: {error}",
            line=line,
        )

    def _check_imports(self, tree: ast.AST, base_line: int) -> list[CodebaseFinding]:
        findings: list[CodebaseFinding] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    findings.append(self._check_module(alias.name, base_line + node.lineno - 1))
            elif isinstance(node, ast.ImportFrom) and node.module:
                findings.append(self._check_module(node.module, base_line + node.lineno - 1))
                module_path = _module_to_path(node.module, self.repo_root)
                if module_path is None or not module_path.exists():
                    continue
                exported = _python_top_level_names(module_path)
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    if alias.name not in exported:
                        findings.append(
                            CodebaseFinding(
                                check_id="python_import_attribute_missing",
                                decision=CodebaseDecision.HOLD,
                                message=(
                                    f"Imported name {alias.name!r} not found in {node.module!r}"
                                ),
                                value=f"{node.module}.{alias.name}",
                                line=base_line + node.lineno - 1,
                            )
                        )
        return findings

    def _check_module(self, module: str, line: int) -> CodebaseFinding:
        module_path = _module_to_path(module, self.repo_root)
        if module_path is not None and module_path.exists():
            return CodebaseFinding(
                check_id="python_import_module_exists",
                decision=CodebaseDecision.PASS,
                message=f"Import module resolves locally: {module}",
                value=module,
                line=line,
                evidence_refs=(str(module_path),),
            )
        return CodebaseFinding(
            check_id="python_import_module_missing",
            decision=CodebaseDecision.HOLD,
            message=f"Import module does not resolve locally: {module}",
            value=module,
            line=line,
        )

    def _check_numeric_claims(self, claims: Sequence[NumericClaim]) -> list[CodebaseFinding]:
        findings: list[CodebaseFinding] = []
        for claim in claims:
            expected = _lookup_numeric_expectation(claim, self.numeric_expectations)
            if expected is None:
                findings.append(
                    CodebaseFinding(
                        check_id="numeric_claim_unverified",
                        decision=CodebaseDecision.HOLD,
                        message=f"Numeric claim lacks deterministic expectation: {claim.text}",
                        value=claim.text,
                        line=claim.line,
                    )
                )
                continue
            if _normalize_number(str(expected)) == _normalize_number(claim.value):
                findings.append(
                    CodebaseFinding(
                        check_id="numeric_claim_verified",
                        decision=CodebaseDecision.PASS,
                        message=f"Numeric claim verified: {claim.text}",
                        value=claim.text,
                        line=claim.line,
                    )
                )
            else:
                findings.append(
                    CodebaseFinding(
                        check_id="numeric_claim_mismatch",
                        decision=CodebaseDecision.REJECT,
                        message=(
                            f"Numeric claim {claim.text!r} does not match expectation {expected!r}"
                        ),
                        value=claim.text,
                        line=claim.line,
                    )
                )
        return findings

    def _check_currentness_claims(
        self,
        claims: Sequence[CurrentnessClaim],
    ) -> list[CodebaseFinding]:
        findings: list[CodebaseFinding] = []
        for claim in claims:
            if self.currentness_evidence_refs:
                findings.append(
                    CodebaseFinding(
                        check_id="currentness_claim_evidence_present",
                        decision=CodebaseDecision.PASS,
                        message=f"Currentness claim has evidence refs: {claim.text}",
                        value=claim.text,
                        line=claim.line,
                        evidence_refs=self.currentness_evidence_refs,
                    )
                )
            else:
                findings.append(
                    CodebaseFinding(
                        check_id="currentness_claim_missing_evidence",
                        decision=CodebaseDecision.HOLD,
                        message=f"Currentness claim needs evidence refs: {claim.text}",
                        value=claim.text,
                        line=claim.line,
                    )
                )
        return findings


def _extract_path_refs(text: str) -> list[tuple[str, int]]:
    refs: list[tuple[str, int]] = []
    for match in _BACKTICK_RE.finditer(text):
        candidate = match.group(1).strip()
        if _PATH_RE.fullmatch(candidate):
            refs.append((candidate, match.start(1)))
    for match in _MARKDOWN_LINK_RE.finditer(text):
        candidate = match.group(1).strip()
        if _PATH_RE.fullmatch(candidate):
            refs.append((candidate, match.start(1)))
    for match in _PATH_RE.finditer(text):
        refs.append((match.group("path"), match.start("path")))
    return refs


def _resolve_repo_path(ref: str, repo_root: Path) -> Path | None:
    ref_path = Path(ref)
    candidate = ref_path if ref_path.is_absolute() else repo_root / ref_path
    try:
        resolved = candidate.resolve()
        resolved.relative_to(repo_root)
    except (OSError, ValueError):
        return None
    return resolved


def _module_to_path(module: str, repo_root: Path) -> Path | None:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*", module):
        return None
    parts = module.split(".")
    module_path = repo_root.joinpath(*parts).with_suffix(".py")
    package_path = repo_root.joinpath(*parts, "__init__.py")
    if module_path.exists():
        return module_path
    if package_path.exists():
        return package_path
    return module_path


def _python_top_level_names(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return set()
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".", 1)[0])
    return names


def _extract_numeric_claims(text: str) -> list[NumericClaim]:
    claims: list[NumericClaim] = []
    for match in _NUMBER_RE.finditer(text):
        value = match.group("value")
        subject = _clean_claim_text(match.group("subject"))
        if not subject or _looks_like_date_context(text, match.start()):
            continue
        claim_text = f"{value} {subject}"
        claims.append(
            NumericClaim(
                text=claim_text,
                value=value,
                subject=subject,
                line=_line_for_offset(text, match.start()),
            )
        )
    return claims


def _extract_currentness_claims(text: str) -> list[CurrentnessClaim]:
    claims: list[CurrentnessClaim] = []
    for start, sentence in _sentences_with_offsets(text):
        match = _CURRENTNESS_RE.search(sentence)
        if match is None:
            continue
        claims.append(
            CurrentnessClaim(
                text=sentence.strip(),
                keyword=match.group(1).lower(),
                line=_line_for_offset(text, start + match.start()),
            )
        )
    return claims


def _sentences_with_offsets(text: str) -> list[tuple[int, str]]:
    sentences: list[tuple[int, str]] = []
    start = 0
    for match in re.finditer(r"(?<=[.!?])\s+|\n+", text):
        sentence = text[start : match.start()].strip()
        if sentence:
            sentences.append((start, sentence))
        start = match.end()
    tail = text[start:].strip()
    if tail:
        sentences.append((start, tail))
    return sentences


def _lookup_numeric_expectation(
    claim: NumericClaim,
    expectations: Mapping[str, object],
) -> object | None:
    for key in (claim.text, claim.subject, _normalize_claim_key(claim.text)):
        if key in expectations:
            return expectations[key]
    return None


def _normalize_claim_key(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _normalize_number(value: str) -> str:
    return value.replace(",", "").rstrip("+")


def _clean_claim_text(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value).strip(" .,:;)")
    return cleaned


def _looks_like_date_context(text: str, offset: int) -> bool:
    window = text[max(0, offset - 12) : offset + 16].lower()
    return bool(re.search(r"\b20\d{2}-\d{2}-\d{2}\b|\b20\d{2}\b", window))


def _code_spans(text: str) -> list[tuple[int, int]]:
    return [(match.start(), match.end()) for match in _CODE_FENCE_RE.finditer(text)]


def _offset_in_spans(offset: int, spans: Sequence[tuple[int, int]]) -> bool:
    return any(start <= offset < end for start, end in spans)


def _strip_code_fences(text: str) -> str:
    return _CODE_FENCE_RE.sub("", text)


def _line_for_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _aggregate_decision(findings: Sequence[CodebaseFinding]) -> CodebaseDecision:
    if any(finding.decision == CodebaseDecision.REJECT for finding in findings):
        return CodebaseDecision.REJECT
    if any(finding.decision == CodebaseDecision.HOLD for finding in findings):
        return CodebaseDecision.HOLD
    return CodebaseDecision.PASS


def _default_shell_syntax_checker(body: str) -> str | None:
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".sh") as tmp:
            tmp.write(body)
            tmp.flush()
            result = subprocess.run(
                ["bash", "-n", tmp.name],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"shell_syntax_checker_unavailable: {type(exc).__name__}"
    if result.returncode == 0:
        return None
    return result.stderr.strip() or result.stdout.strip() or "bash -n failed"


__all__ = [
    "CodebaseConsistencyVerifier",
    "CodebaseDecision",
    "CodebaseFinding",
    "CodebaseVerificationReport",
    "CurrentnessClaim",
    "NumericClaim",
    "ShellSyntaxChecker",
    "verify_publication_codebase",
]
