"""Transcript-grade secret + PII scrubber for the Continuity Substrate (CS).

WHY THIS IS A DISTINCT MODULE (do not "just reuse" the HKP redactor):
The HKP redaction set (``hkp_research_viewer`` / ``hkp_prompt_context``) is a
*structured-field* redactor built for cc-task / spec frontmatter — its
assignment rule anchors on ``=`` and its bearer rule on the literal ``Bearer``.
Pointed at a *raw session transcript* it leaks the shapes that actually occur
there: bare ``sk-ant-*`` keys, bare ``ghp_/ghs_`` PATs, bare env-secret VALUES,
the operator's spoken password (no token shape at all), JSON-value secrets
(``"k":"v"`` — no ``=``), and bluesky app-passwords. This module is the
transcript-grade scrubber the CS distillation pipeline runs as **stage 0**,
before any distillation or storage.

CONTRACT (per REQ-20260621-continuity-transcript-scrubber):
- :func:`scrub` removes secrets/PII and returns the scrubbed text + a per-category
  redaction tally.
- :func:`assert_clean` is the FAIL-CLOSED gate: it re-scans text with the full
  detector set and raises :class:`ResidualSecretError` on ANY residual. The CS
  caller treats that as DROP-THE-BUNDLE (never drop-the-field, never persist).
- The live-env-value denylist (exact match against the real secret VALUES in
  ``/run/user/1000/hapax-secrets.env``) is the strongest signal — it catches a
  bare echo of a real secret that matches no generic pattern. Those values are
  read in-process to build a match set and are never persisted.

This module performs NO authority action and writes nothing. It is pure text in,
scrubbed text out — support for the non-authorizing CS/HKP boundary.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Default materialised-secrets env file (hapax-secrets.service writes it from `pass`).
DEFAULT_SECRETS_ENV = Path("/run/user/1000/hapax-secrets.env")

#: Minimum length for an env VALUE to enter the exact-match denylist. Short values
#: (e.g. "1", "true", a port) would cause rampant false positives.
MIN_DENYLIST_VALUE_LEN = 8

#: Entropy detector thresholds (conservative — secrets, not git SHAs or slugs).
_ENTROPY_MIN_LEN = 32
_ENTROPY_MIN_BITS = 4.0

REDACTION = "[REDACTED:{cat}]"


@dataclass(frozen=True)
class ScrubResult:
    """Outcome of a scrub pass."""

    text: str
    redactions: int
    categories: dict[str, int] = field(default_factory=dict)


class ResidualSecretError(RuntimeError):
    """Raised by :func:`assert_clean` when residual secret/PII material is found.

    Carries the per-category tally so the caller can log WHAT class leaked
    (never the value) before dropping the bundle.
    """

    def __init__(self, categories: dict[str, int]) -> None:
        self.categories = categories
        summary = ", ".join(f"{k}={v}" for k, v in sorted(categories.items()))
        super().__init__(
            f"residual secret/PII material after scrub ({summary}); "
            "drop-the-bundle (fail-closed) — never persist or serve"
        )


# --------------------------------------------------------------------------- #
# Generic secret patterns (transcript-shaped: bare tokens, JSON values, prose) #
# --------------------------------------------------------------------------- #

# Order matters only for tally clarity; replacement is span-based so overlaps are
# resolved by widest-first selection in _detect.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Anthropic / OpenAI style keys (bare — no assignment needed).
    ("provider_token", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{16,}")),
    ("provider_token", re.compile(r"\bsk-[A-Za-z0-9]{20,}")),
    # GitHub PATs / tokens (bare).
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}")),
    # Slack tokens.
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    # GitLab PAT.
    ("gitlab_token", re.compile(r"\bglpat-[A-Za-z0-9_-]{16,}")),
    # AWS access key id.
    ("aws_key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    # Google API key.
    ("google_key", re.compile(r"\bAIza[A-Za-z0-9_-]{30,}")),
    # JWT (three base64url segments).
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    # PEM private key blocks (multi-line).
    (
        "private_key",
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----.*?"
            r"-----END (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----",
            re.DOTALL,
        ),
    ),
    # bluesky app-password form: xxxx-xxxx-xxxx-xxxx (4 groups of 4 lowercase/digits).
    ("app_password", re.compile(r"\b[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}\b")),
    # HTTP Authorization headers (Bearer / Basic).
    ("authorization", re.compile(r"(?i)\bauthorization\s*:\s*(?:bearer|basic)\s+\S+")),
    # Spoken / written password disclosure ("password is X", "passphrase: X").
    (
        "spoken_secret",
        re.compile(r"(?i)\b(?:pass(?:word|phrase)|api\s*key|secret)\b[^\S\n]{0,4}(?:is|:|=)\s*\S+"),
    ),
)

# Assignment forms: KEY=value / "KEY":"value" / KEY: value where KEY looks secret-ish.
_SECRET_KEY = (
    r"(?:[A-Za-z0-9_]*"
    r"(?:secret|token|passwd|password|api[_-]?key|apikey|access[_-]?key|"
    r"private[_-]?key|client[_-]?secret|auth|credential|bearer|session[_-]?key)"
    r"[A-Za-z0-9_]*)"
)
_PRIVATE_TEXT_KEY = re.compile(
    r"(?i)(?:^|[_-])(?:text|utterance|transcript|message|content|prompt|response)(?:$|[_-])"
)
_ASSIGNMENT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("secret_assignment", re.compile(rf'(?i)"{_SECRET_KEY}"\s*:\s*"[^"]+"')),
    ("secret_assignment", re.compile(rf"(?i)\b{_SECRET_KEY}\s*[:=]\s*\S+")),
)

# Operator PII (reuses .gitleaks.toml intent — name / location / home path).
_PII_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("operator_pii", re.compile(r"(?i)Ryan\s+Kleeberger")),
    ("operator_pii", re.compile(r"Minneapolis[- ]St\.?\s*Paul")),
)


@dataclass(frozen=True)
class _Match:
    start: int
    end: int
    category: str


def _shannon_bits(s: str) -> float:
    if not s:
        return 0.0
    counts: dict[str, int] = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _entropy_matches(text: str) -> list[_Match]:
    """Conservative high-entropy fallback.

    Flags long base64-ish tokens that are NOT pure hex (git SHAs / sha256 are
    excluded so SOURCE pointers survive) and NOT pure decimal.
    """
    matches: list[_Match] = []
    # Exclude '=' from the inner class (only allow it as trailing base64 padding)
    # so the detector does not glue an assignment operator onto its token and
    # mask a more specific detector (e.g. KEY=ghp_... must stay a github_token).
    for m in re.finditer(rf"[A-Za-z0-9+/_-]{{{_ENTROPY_MIN_LEN},}}={{0,2}}", text):
        tok = m.group(0)
        if re.fullmatch(r"[0-9a-fA-F]+", tok):  # git SHA / hex digest → keep (pointer)
            continue
        if tok.isdigit():
            continue
        if not (any(c.islower() for c in tok) and any(c.isupper() or c.isdigit() for c in tok)):
            continue
        if _shannon_bits(tok) >= _ENTROPY_MIN_BITS:
            matches.append(_Match(m.start(), m.end(), "high_entropy"))
    return matches


def load_secret_values(env_path: Path = DEFAULT_SECRETS_ENV) -> set[str]:
    """Read secret VALUES from the materialised env file for exact-match scrubbing.

    Missing/unreadable file is non-fatal (the generic detectors still run); the
    caller's :func:`assert_clean` remains the fail-closed backstop. Values shorter
    than :data:`MIN_DENYLIST_VALUE_LEN` are skipped to avoid false positives.
    """
    values: set[str] = set()
    try:
        raw = env_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return values
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        _, _, val = line.partition("=")
        val = val.strip().strip('"').strip("'")
        if len(val) >= MIN_DENYLIST_VALUE_LEN:
            values.add(val)
    return values


def load_secret_var_names(env_path: Path = DEFAULT_SECRETS_ENV) -> set[str]:
    """Read the env VAR NAMES so ``NAME=...`` / ``"NAME":"..."`` echoes are caught."""
    names: set[str] = set()
    try:
        raw = env_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return names
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, _ = line.partition("=")
        key = key.strip()
        if key:
            names.add(key)
    return names


def _detect(
    text: str,
    *,
    secret_values: tuple[str, ...] | set[str],
    var_names: tuple[str, ...] | set[str],
    redact_pii: bool = True,
) -> list[_Match]:
    matches: list[_Match] = []

    # Exact live-value denylist (strongest signal).
    for val in secret_values:
        start = 0
        while True:
            idx = text.find(val, start)
            if idx < 0:
                break
            matches.append(_Match(idx, idx + len(val), "known_secret"))
            start = idx + len(val)

    # Env VAR NAME = value / "VAR": "value" echoes.
    for name in var_names:
        if not name:
            continue
        esc = re.escape(name)
        for pat in (
            re.compile(rf'"{esc}"\s*:\s*"[^"]+"'),
            re.compile(rf"\b{esc}\s*[:=]\s*\S+"),
        ):
            for m in pat.finditer(text):
                matches.append(_Match(m.start(), m.end(), "known_secret"))

    pattern_groups = [_PATTERNS, _ASSIGNMENT_PATTERNS]
    if redact_pii:
        pattern_groups.append(_PII_PATTERNS)
    for group in pattern_groups:
        for category, pat in group:
            for m in pat.finditer(text):
                matches.append(_Match(m.start(), m.end(), category))

    matches.extend(_entropy_matches(text))
    return matches


def _resolve_overlaps(matches: list[_Match]) -> list[_Match]:
    """Merge overlapping/touching matches into UNION spans (fail-closed).

    Sorting by ``(start, end)``, any match that reaches into the running span
    EXTENDS it to the union end rather than being dropped. This closes the leak
    where a later, crossing match (one that starts inside a kept match but ends
    beyond it) was discarded, leaving its tail — part of a secret — in the clear.
    No byte flagged by any detector can survive.
    """
    if not matches:
        return []
    ordered = sorted(matches, key=lambda m: (m.start, m.end))
    merged: list[_Match] = [ordered[0]]
    for m in ordered[1:]:
        last = merged[-1]
        if m.start <= last.end:
            if m.end > last.end:
                # Extend to the union end; the match that reaches furthest carries
                # the merged span's (informational) category label.
                merged[-1] = _Match(last.start, m.end, m.category)
            # else: m is fully contained in the running span — already redacted.
        else:
            merged.append(m)
    return merged


def scrub(
    text: str,
    *,
    secret_env_path: Path = DEFAULT_SECRETS_ENV,
    extra_secret_values: tuple[str, ...] = (),
    redact_pii: bool = True,
) -> ScrubResult:
    """Scrub secrets + PII from ``text``; return scrubbed text and a per-category tally."""
    secret_values = set(load_secret_values(secret_env_path)) | set(extra_secret_values)
    var_names = load_secret_var_names(secret_env_path)

    matches = _detect(text, secret_values=secret_values, var_names=var_names, redact_pii=redact_pii)
    kept = _resolve_overlaps(matches)

    categories: dict[str, int] = {}
    out: list[str] = []
    cursor = 0
    for m in kept:
        out.append(text[cursor : m.start])
        out.append(REDACTION.format(cat=m.category))
        categories[m.category] = categories.get(m.category, 0) + 1
        cursor = m.end
    out.append(text[cursor:])
    return ScrubResult(text="".join(out), redactions=len(kept), categories=categories)


def assert_clean(
    text: str,
    *,
    secret_env_path: Path = DEFAULT_SECRETS_ENV,
    extra_secret_values: tuple[str, ...] = (),
    redact_pii: bool = True,
) -> None:
    """FAIL-CLOSED gate: raise :class:`ResidualSecretError` if ANY residual is found.

    Run on the final to-be-persisted / to-be-served bundle text. On raise, the CS
    caller drops the whole bundle and falls back to naked compaction.
    """
    secret_values = set(load_secret_values(secret_env_path)) | set(extra_secret_values)
    var_names = load_secret_var_names(secret_env_path)
    matches = _detect(text, secret_values=secret_values, var_names=var_names, redact_pii=redact_pii)
    if matches:
        categories: dict[str, int] = {}
        for m in matches:
            categories[m.category] = categories.get(m.category, 0) + 1
        raise ResidualSecretError(categories)


def _sensitive_key_context(key: str) -> bool:
    return bool(_ASSIGNMENT_PATTERNS[1][1].fullmatch(f"{key}: placeholder"))


def _private_text_key_context(key: str) -> bool:
    lowered = key.lower()
    if lowered.endswith(("_hash", "_id", "_ids", "_ref", "_refs")):
        return False
    return bool(_PRIVATE_TEXT_KEY.search(key))


def _child_key_context(parent: str | None, key: str) -> str:
    if _sensitive_key_context(key) or _private_text_key_context(key):
        return key
    if parent is not None and (_sensitive_key_context(parent) or _private_text_key_context(parent)):
        return parent
    return key


def scrub_structured_value(value: Any, *, key_context: str | None = None) -> Any:
    """Scrub JSON-like values while preserving key context for assignment detectors.

    Scalar :func:`scrub` calls cannot see that ``{"api_key": "hunter2"}`` is a
    secret assignment because the key and value are separated by structured
    serialization. This helper recurses through dict/list payloads and uses the
    current field name as detector context before durable persistence.
    """

    if isinstance(value, dict):
        return {
            str(k): scrub_structured_value(v, key_context=_child_key_context(key_context, str(k)))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [scrub_structured_value(v, key_context=key_context) for v in value]
    if isinstance(value, str):
        if key_context and _private_text_key_context(key_context) and value:
            return "[REDACTED:private_text]"

        cleaned = scrub(value).text
        assert_clean(cleaned)

        if key_context and _sensitive_key_context(key_context):
            contextual = scrub(f"{key_context}: {value}")
            if contextual.redactions:
                return "[REDACTED:secret_assignment]"
        return cleaned
    return value
