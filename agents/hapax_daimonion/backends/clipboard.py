"""Clipboard intent classification backend.

Observes clipboard changes via wl-paste and classifies content type as an
intent signal. Classification is rule-based (no LLM). The classification
label is stored as a perception Behavior; clipboard content itself is
NEVER written to disk or sent to any LLM (privacy constraint).

Provides:
  - clipboard_intent: str ("url", "error", "code", "person", "text", "empty")
  - clipboard_changed: bool (True on the tick when clipboard changes)
"""

from __future__ import annotations

import logging
import re
import subprocess
import time

from agents.hapax_daimonion.perception import PerceptionTier
from agents.hapax_daimonion.primitives import Behavior

log = logging.getLogger(__name__)

# ── Classification patterns ──────────────────────────────────────────────────

_URL_RE = re.compile(r"https?://")
_ERROR_RE = re.compile(
    r"Error|Exception|Traceback|at\s+\S+\(|FAILED|panic:|fatal:",
    re.IGNORECASE,
)
_CODE_HEURISTICS = re.compile(
    r"[{}\[\]();]|^\s{2,}(def |class |fn |func |import |from |const |let |var )",
    re.MULTILINE,
)


def classify_clipboard(text: str) -> str:
    """Classify clipboard content into an intent category.

    Returns one of: "url", "error", "code", "text", "empty".
    Content is examined but never stored.
    """
    if not text or not text.strip():
        return "empty"
    if _URL_RE.search(text):
        return "url"
    if _ERROR_RE.search(text):
        return "error"
    if _CODE_HEURISTICS.search(text):
        return "code"
    return "text"


def _read_clipboard() -> str | None:
    """Read current Wayland clipboard via wl-paste. Returns None on failure."""
    try:
        result = subprocess.run(
            ["wl-paste", "--no-newline"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


class ClipboardIntentBackend:
    """Classifies clipboard content changes as intent signals."""

    def __init__(self) -> None:
        self._b_intent: Behavior[str] = Behavior("empty")
        self._b_changed: Behavior[bool] = Behavior(False)
        self._last_hash: int = 0

    @property
    def name(self) -> str:
        return "clipboard_intent"

    @property
    def provides(self) -> frozenset[str]:
        return frozenset({"clipboard_intent", "clipboard_changed"})

    @property
    def tier(self) -> PerceptionTier:
        return PerceptionTier.SLOW  # polls every slow tick (~12s)

    def available(self) -> bool:
        try:
            result = subprocess.run(
                ["wl-paste", "--version"],
                capture_output=True,
                timeout=2,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        now = time.monotonic()
        content = _read_clipboard()
        if content is None:
            self._b_changed.update(False, now)
            behaviors["clipboard_intent"] = self._b_intent
            behaviors["clipboard_changed"] = self._b_changed
            return

        content_hash = hash(content)
        changed = content_hash != self._last_hash

        if changed:
            self._last_hash = content_hash
            intent = classify_clipboard(content)
            self._b_intent.update(intent, now)
            log.debug("Clipboard intent: %s (changed)", intent)

        self._b_changed.update(changed, now)
        behaviors["clipboard_intent"] = self._b_intent
        behaviors["clipboard_changed"] = self._b_changed

    def start(self) -> None:
        log.info("Clipboard intent backend started")

    def stop(self) -> None:
        log.info("Clipboard intent backend stopped")
