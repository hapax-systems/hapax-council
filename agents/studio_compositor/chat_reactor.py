"""Chat-reactive preset switching.

Viewers can request an effect preset by typing its name in the live
chat. A4's stream-overlay shows the current preset in the bottom-right
of the frame, so viewers can see what they're switching away from and
what names are valid — a complete feedback loop with no explicit
command syntax.

A5 (Stream A handoff 2026-04-12). Integrated into ``chat-monitor.py``
via :meth:`PresetReactor.process_message`. Pure stateless keyword
match + a single-slot cooldown timer; no per-author memory, no chat
persistence. Consent-safe: we never store the message, author, or any
derived text beyond the one-shot match.

Pattern: preset names are stripped of their ``_preset`` suffix for
matching ("halftone_preset" matches the bare word "halftone"), and the
match is a word-boundary regex so "neonight" never triggers "neon".
Each match writes the full preset graph JSON to the compositor's
``graph-mutation.json`` mutation bus, identical to the manual chain
builder and ``random_mode``.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

from .random_mode import (
    MUTATION_FILE,
    PRESET_DIR,
    get_preset_names,
    load_preset_graph,
)

log = logging.getLogger(__name__)

SHM_DIR = Path("/dev/shm/hapax-compositor")
FX_CURRENT_FILE = SHM_DIR / "fx-current.txt"

COOLDOWN_SECONDS = 30.0
"""Minimum seconds between chat-triggered switches.

Prevents rapid thrash when multiple viewers spam the same or different
preset names. 30s is intentionally slower than the ~5–10s random_mode
cycling, so a chat-triggered switch actually gets held for a meaningful
window before random_mode or the next chat hit can replace it.
"""


def _keyword_for(preset_name: str) -> str:
    """Strip common suffixes so 'halftone_preset' matches 'halftone'."""
    for suffix in ("_preset", "_fx"):
        if preset_name.endswith(suffix):
            return preset_name[: -len(suffix)]
    return preset_name


def _read_current_preset() -> str:
    try:
        return FX_CURRENT_FILE.read_text().strip()
    except OSError:
        return ""


class PresetReactor:
    """Match chat messages against preset keywords and drive switches.

    Construct once per chat-monitor process. All state (preset list,
    keyword index, last-switch timestamp) lives on the instance. A
    fresh reactor after restart simply loses its cooldown — switches
    resume immediately, which is the desired behavior.
    """

    def __init__(
        self,
        preset_dir: Path | None = None,
        mutation_file: Path | None = None,
        cooldown: float = COOLDOWN_SECONDS,
    ) -> None:
        self._preset_dir = preset_dir or PRESET_DIR
        self._mutation_file = mutation_file or MUTATION_FILE
        self._cooldown = cooldown
        self._last_switch_monotonic: float = 0.0
        self._build_keyword_index()

    def _build_keyword_index(self) -> None:
        """Build a ``keyword -> preset_name`` map from the preset directory.

        Matches are case-insensitive; shorter keywords win when multiple
        presets would match (e.g. ``neon`` > ``neon_variant`` on a bare
        "neon" token). Longest-match first so "datamosh_heavy" wins over
        "datamosh" when the chat message has the more specific variant.
        """
        names = (
            get_preset_names()
            if self._preset_dir is PRESET_DIR
            else [
                p.stem
                for p in sorted(self._preset_dir.glob("*.json"))
                if not p.stem.startswith("_")
                and p.stem not in ("clean", "echo", "reverie_vocabulary")
            ]
        )
        index: dict[str, str] = {}
        for preset_name in names:
            key = _keyword_for(preset_name).lower()
            if key and key not in index:
                index[key] = preset_name
        self._keyword_index = index
        self._match_regex = self._compile_regex(list(index.keys()))
        log.debug("PresetReactor indexed %d presets", len(index))

    @staticmethod
    def _compile_regex(keywords: list[str]) -> re.Pattern[str] | None:
        if not keywords:
            return None
        # Longest first so word-boundary alternation prefers specific variants.
        alternation = "|".join(re.escape(k) for k in sorted(keywords, key=len, reverse=True))
        return re.compile(rf"\b({alternation})\b", re.IGNORECASE)

    def match(self, message_text: str) -> str | None:
        """Return the preset name a message requests, or ``None``.

        Stateless — no cooldown check, no current-preset comparison. The
        caller decides whether to act on the match. Split out so tests
        can exercise the pattern matching independently of file I/O.
        """
        if not message_text or self._match_regex is None:
            return None
        m = self._match_regex.search(message_text)
        if not m:
            return None
        key = m.group(1).lower()
        return self._keyword_index.get(key)

    def process_message(self, message_text: str) -> str | None:
        """Match + cooldown + no-op guard + write mutation. Returns applied preset or None.

        This is the single call site from chat-monitor — one line in
        ``_process_message`` after tokenization. Returns the preset
        name iff a switch was actually written to the mutation bus,
        else None. Any decision (no match, cooldown, no-op, failure)
        returns None silently — chat-monitor doesn't need to know the
        reason, only whether something happened.
        """
        preset_name = self.match(message_text)
        if preset_name is None:
            return None

        now = time.monotonic()
        if now - self._last_switch_monotonic < self._cooldown:
            return None

        if _read_current_preset() == preset_name:
            # Already on it — don't double-apply, don't reset the cooldown
            # (otherwise chat spam on the active preset permanently locks
            # out other switches).
            return None

        graph = load_preset_graph(preset_name)
        if graph is None:
            log.warning("Chat reactor: preset %s not loadable", preset_name)
            return None

        try:
            self._mutation_file.parent.mkdir(parents=True, exist_ok=True)
            self._mutation_file.write_text(json.dumps(graph))
        except OSError:
            log.warning("Chat reactor: failed to write mutation for %s", preset_name)
            return None

        self._last_switch_monotonic = now
        # Deliberately logs ONLY the preset name — no author, no message
        # content, no recent chat snippet. Axiom: interpersonal_transparency.
        log.info("Chat preset switch: %s", preset_name)
        return preset_name
