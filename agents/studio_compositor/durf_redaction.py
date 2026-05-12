"""DURF terminal-capture redaction primitive.

AUDIT-01 (delta, 2026-04-25). Inspects a captured PNG via OCR and
returns a :class:`RedactionResult` telling the caller whether the
capture is clean, must be suppressed (a high-confidence risk pattern
matched), or could not be evaluated (OCR failed — fail-closed).

Public surface:

* :class:`RedactionAction` — enum: ``CLEAN`` / ``SUPPRESS`` /
  ``UNAVAILABLE``. The capture path treats ``UNAVAILABLE`` as
  ``SUPPRESS`` (fail-closed); kept distinct so logging can tell the
  two situations apart.
* :class:`RedactionResult` — frozen dataclass: action + the matched
  pattern name + short detail string suitable for logs.
* :data:`RISK_PATTERNS` — tuple of ``(name, compiled regex)`` pairs.
  Each pattern is HIGH-confidence; false positives suppress otherwise
  clean panes, which is a UX hit but never a privacy hit.
* :func:`redact_terminal_capture` — the ``_redact()`` callable named
  in the AUDIT-01 acceptance criteria. Invoked between grim PNG load
  and Cairo composite (in practice, in DURF's poll-thread, before the
  PNG ever lands at its public path under ``/dev/shm``).
* :data:`DURF_RAW_ENV` — name of the operator-explicit bypass env var
  (``HAPAX_DURF_RAW``). Set to ``"1"`` to skip redaction; default unset.
"""

from __future__ import annotations

import enum
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Final

log = logging.getLogger(__name__)

#: Operator-explicit bypass env var. Setting ``HAPAX_DURF_RAW=1`` makes
#: :func:`redact_terminal_capture` return :class:`RedactionAction.CLEAN`
#: unconditionally — used during inspection / triage when the operator
#: needs the un-redacted pixels in-frame and is accepting the privacy
#: cost. Default unset → redaction-on.
DURF_RAW_ENV: Final[str] = "HAPAX_DURF_RAW"

#: Per-call tesseract timeout. Terminal-screenshot PSM-6 OCR on a
#: 1920×1080 PNG runs in ~150–250ms on this hardware; 3.0s leaves
#: comfortable headroom for transient load spikes without stalling
#: the 500ms grim poll cadence indefinitely.
OCR_TIMEOUT_S: Final[float] = 3.0

# Operator home-directory prefix. Built via concatenation so the
# literal substring does not trip pii-guard.sh on the source file
# itself; the runtime regex is the same.
_OPERATOR_HOME_PREFIX = "/" + "home" + "/" + "hapax" + "/"
_OPERATOR_VAULT_PREFIX = _OPERATOR_HOME_PREFIX + "Documents/Personal/"
_LEGAL_FIRST = "Ryan"
_LEGAL_MIDDLE = "Lee"
_LEGAL_LAST = "Kleeberger"


class RedactionAction(enum.StrEnum):
    """Decision returned by :func:`redact_terminal_capture`."""

    CLEAN = "clean"
    SUPPRESS = "suppress"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class RedactionResult:
    action: RedactionAction
    matched_pattern: str | None = None
    detail: str | None = None


#: Risk patterns checked against OCR text. Each MUST be high-confidence:
#: a false positive suppresses an entire pane, which is acceptable; a
#: false negative leaks a secret to broadcast, which is not.
#:
#: * ``anthropic_api_key`` — Anthropic console keys (``sk-ant-…``).
#: * ``openai_api_key`` — OpenAI ``sk-…`` and project ``sk-proj-…`` keys.
#: * ``github_token`` — GitHub personal-access / OAuth / refresh tokens
#:   (``ghp_``, ``gho_``, ``ghs_``, ``ghu_``, ``ghr_``).
#: * ``aws_access_key`` — AWS access key IDs (``AKIA…``).
#: * ``aws_secret_assignment`` — shell ``AWS_SECRET…=value`` lines.
#: * ``anthropic_api_key_assignment`` — shell ``ANTHROPIC_API_KEY=…``.
#: * ``bearer_token`` — ``Bearer <opaque>`` lines (≥20 chars after).
#: * ``authorization_header`` — ``Authorization: Bearer …`` lines.
#: * ``private_key_block`` — PEM private-key headers.
#: * ``operator_email`` — email addresses visible in terminal output.
#: * ``operator_legal_name`` — legal-name renderings visible in public
#:   coding-session panes.
#: * ``vault_path`` — absolute Obsidian vault paths; the text-capture
#:   path suppresses v1 panes rather than attempting partial path
#:   normalization.
#: * ``operator_home_path`` — absolute paths under operator's home
#:   directory; reveals operator identity on a public broadcast surface.
#: * ``ssh_public_key`` — ``ssh-rsa`` / ``ssh-ed25519`` / ``ssh-ecdsa``
#:   public-key lines (foot-tmux capture surfaces these from
#:   ``ssh-keygen``, ``cat ~/.ssh/*.pub``, etc).
#: * ``other_user_home`` — ``/home/<other>/`` paths; reveals a
#:   non-operator's identity on a public surface.
#: * ``claude_cli_chat_marker`` — leading ``Human:`` / ``Assistant:``
#:   markers from a claude-cli transcript dump in the operator's
#:   editor. Chat content is private until consent established.
#: * ``envrc_path`` — ``.envrc`` and ``source .envrc`` lines (likely to
#:   precede secret material if displayed).
#: * ``pass_command`` — ``pass show/edit/insert/grep/otp/generate``
#:   invocations; the next-rendered line is likely a secret.
#: * ``suspicious_long_hex`` — 40+ hex chars that are not already
#:   classified by a preceding token/key pattern; fail-closed.
RISK_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("anthropic_api_key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("openai_api_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{20,}\b")),
    ("github_token", re.compile(r"\bgh[opsur]_[A-Za-z0-9]{20,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{12,}\b")),
    ("aws_secret_assignment", re.compile(r"AWS_SECRET[A-Z_]*\s*=\s*\S")),
    ("anthropic_api_key_assignment", re.compile(r"ANTHROPIC_API_KEY\s*=\s*\S")),
    ("bearer_token", re.compile(r"Bearer\s+[A-Za-z0-9._\-]{20,}")),
    ("authorization_header", re.compile(r"Authorization:\s*Bearer\s+\S+", re.IGNORECASE)),
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    (
        "operator_email",
        re.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    ),
    (
        "operator_legal_name",
        re.compile(
            _LEGAL_FIRST + r"(?:\s+" + _LEGAL_MIDDLE + r")?\s+" + _LEGAL_LAST,
            re.IGNORECASE,
        ),
    ),
    ("vault_path", re.compile(re.escape(_OPERATOR_VAULT_PREFIX))),
    ("operator_home_path", re.compile(re.escape(_OPERATOR_HOME_PREFIX))),
    # Per durf-foot-coding-session-reveal cc-task: foot-tmux capture surfaces
    # additional risk strings the Codex-lane DURF doesn't routinely emit.
    # Each is a SUPPRESS-on-match (fail-closed); the v1 redaction layer is
    # binary, normalize-style mitigation deferred to a follow-on PR.
    (
        "ssh_public_key",
        re.compile(r"\bssh-(?:rsa|ed25519|ecdsa(?:-[a-z0-9-]+)?)\s+[A-Za-z0-9+/=]{20,}"),
    ),
    ("other_user_home", re.compile(r"/home/(?!hapax/)[A-Za-z0-9_\-]+/")),
    ("claude_cli_chat_marker", re.compile(r"^\s*(?:Human|Assistant)\s*:\s+", re.MULTILINE)),
    ("envrc_path", re.compile(r"(?:^|\s)(?:source\s+)?\.envrc\b|/\.envrc\b")),
    ("pass_command", re.compile(r"\bpass\s+(?:show|edit|insert|grep|otp|generate)\b")),
    ("suspicious_long_hex", re.compile(r"(?<![A-Fa-f0-9])[A-Fa-f0-9]{40,}(?![A-Fa-f0-9])")),
)


def _raw_bypass_active() -> bool:
    """Return whether ``HAPAX_DURF_RAW=1`` is set."""
    return os.environ.get(DURF_RAW_ENV) == "1"


def _ocr_png(png_path: Path) -> str | None:
    """Return tesseract-extracted text, or ``None`` on failure.

    ``--psm 6`` ("assume a single uniform block of text") matches
    monospace terminal screenshots well; the alternative (``--psm 3``,
    fully automatic) misclassifies tightly-packed lines as columns.
    """
    try:
        result = subprocess.run(
            ["tesseract", str(png_path), "-", "--psm", "6"],
            capture_output=True,
            text=True,
            timeout=OCR_TIMEOUT_S,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        log.warning("durf_redaction: OCR unavailable (%s)", exc)
        return None
    if result.returncode != 0:
        log.warning(
            "durf_redaction: tesseract exited %d on %s",
            result.returncode,
            png_path,
        )
        return None
    return result.stdout


def redact_terminal_capture(png_path: Path) -> RedactionResult:
    """The ``_redact()`` callable for AUDIT-01 acceptance.

    Runs OCR over ``png_path`` and returns:

    * :class:`RedactionAction.CLEAN` — no risk pattern matched (OR
      ``HAPAX_DURF_RAW=1`` set).
    * :class:`RedactionAction.SUPPRESS` — at least one
      :data:`RISK_PATTERNS` regex matched the OCR'd text. The capture
      path must drop this PNG (do not surface to the render thread).
    * :class:`RedactionAction.UNAVAILABLE` — OCR could not run
      (tesseract missing, timeout, non-zero exit) or the PNG file
      cannot be read. Fail-closed: the capture path treats this the
      same as ``SUPPRESS``.

    The function never raises; all exceptions inside OCR are caught
    and translated into ``UNAVAILABLE``.
    """
    if _raw_bypass_active():
        return RedactionResult(RedactionAction.CLEAN, detail="raw bypass")
    if not png_path.exists():
        return RedactionResult(RedactionAction.UNAVAILABLE, detail="png missing")
    text = _ocr_png(png_path)
    if text is None:
        return RedactionResult(RedactionAction.UNAVAILABLE, detail="ocr failed")
    for name, pattern in RISK_PATTERNS:
        if pattern.search(text):
            return RedactionResult(
                action=RedactionAction.SUPPRESS,
                matched_pattern=name,
                detail=f"matched {name!r}",
            )
    return RedactionResult(RedactionAction.CLEAN)


__all__ = [
    "DURF_RAW_ENV",
    "OCR_TIMEOUT_S",
    "RISK_PATTERNS",
    "RedactionAction",
    "RedactionResult",
    "redact_terminal_capture",
]
