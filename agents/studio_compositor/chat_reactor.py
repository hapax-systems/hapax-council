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

import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

from .graph_mutation_bus import write_graph_mutation
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


# ── LRR Phase 9 §3.3 — research-aware chat reactor ──────────────────────────
#
# Two tunables that differ between default and research-mode windows:
#
# * ``cooldown_seconds`` — default 30s (ambient feel); research-mode 90s
#   (deliberate rhythm so a preset hit is held long enough to correlate
#   with a research-activity segment).
# * ``require_trigger_prefix`` — default None (any preset keyword
#   matches); research-mode ``"!fx"`` (viewers must prepend ``!fx`` to
#   request a switch, matching the explicit-syntax convention the
#   research window deliberately teaches).
#
# The A/B window drill (docs/drills/2026-04-17-audience-engagement-ab.md)
# consumes these — window A runs ``DEFAULT``, window B runs
# ``RESEARCH_MODE``, and the compositor's Stream Moments collector
# captures reaction deltas across the two windows.


@dataclass(frozen=True)
class ReactorSensitivity:
    cooldown_seconds: float
    require_trigger_prefix: str | None = None


DEFAULT_SENSITIVITY: ReactorSensitivity = ReactorSensitivity(cooldown_seconds=COOLDOWN_SECONDS)
RESEARCH_MODE_SENSITIVITY: ReactorSensitivity = ReactorSensitivity(
    cooldown_seconds=90.0, require_trigger_prefix="!fx"
)


def resolve_sensitivity_for_working_mode(working_mode: str | None = None) -> ReactorSensitivity:
    """Pick a sensitivity profile based on the operator's working mode.

    ``research`` mode → research-mode sensitivity; anything else (``rnd``
    or unset) → default. The injectable string parameter lets tests
    exercise the mapping without touching the working-mode file.
    """
    if working_mode is None:
        try:
            from shared.working_mode import get_working_mode

            working_mode = get_working_mode().value
        except Exception:  # pragma: no cover — fallback only
            working_mode = ""
    return RESEARCH_MODE_SENSITIVITY if working_mode == "research" else DEFAULT_SENSITIVITY


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
        cooldown: float | None = None,
        sensitivity: ReactorSensitivity | None = None,
    ) -> None:
        self._preset_dir = preset_dir or PRESET_DIR
        self._mutation_file = mutation_file or MUTATION_FILE
        # Back-compat: ``cooldown=`` kwarg overrides the sensitivity's
        # cooldown while preserving whatever trigger-prefix the
        # sensitivity specified. Tests that mutate ``_cooldown``
        # directly after construction continue to work.
        base = sensitivity or DEFAULT_SENSITIVITY
        self._cooldown: float = cooldown if cooldown is not None else base.cooldown_seconds
        self._trigger_prefix: str | None = base.require_trigger_prefix
        self._last_switch_monotonic: float = 0.0
        self._build_keyword_index()

    @property
    def sensitivity(self) -> ReactorSensitivity:
        return ReactorSensitivity(
            cooldown_seconds=self._cooldown,
            require_trigger_prefix=self._trigger_prefix,
        )

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

        If ``sensitivity.require_trigger_prefix`` is set, the message
        must begin with that prefix (case-insensitive) for the keyword
        scan to run; otherwise the match is ambient (any preset name
        anywhere in the message).
        """
        if not message_text or self._match_regex is None:
            return None
        prefix = self._trigger_prefix
        if prefix:
            stripped = message_text.lstrip()
            if not stripped.lower().startswith(prefix.lower()):
                return None
            # Scan only the tail after the prefix — avoids prefix matching
            # itself if a preset happens to share the prefix string.
            scan_from = stripped[len(prefix) :]
        else:
            scan_from = message_text
        m = self._match_regex.search(scan_from)
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
            write_graph_mutation(graph, path=self._mutation_file)
        except OSError:
            log.warning("Chat reactor: failed to write mutation for %s", preset_name)
            return None

        self._last_switch_monotonic = now
        # Deliberately logs ONLY the preset name — no author, no message
        # content, no recent chat snippet. Axiom: interpersonal_transparency.
        log.info("Chat preset switch: %s", preset_name)
        return preset_name
