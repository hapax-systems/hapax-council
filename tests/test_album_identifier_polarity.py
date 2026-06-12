"""Polarity pin for scripts/album-identifier.py (W4-ALBUM-POLARITY-STORM).

The audit-w4 finding: the routine no-album state (nothing on the deck,
or the last identification cleared) took
``raise ValueError("No album currently identified")`` INSIDE the
PNG-save ``try``, where the blanket ``except Exception:
log.exception("Album cover save failed")`` converted the EXPECTED idle
state into a full ERROR+traceback on every poll tick — ~129 ERR/h,
~776 in 6h (anchor class obse-2: inverted polarity, expected state
logged as failure). Alert fatigue from this storm buries real failures.

The fix gates the save on ``_current_album`` BEFORE the try and logs
one INFO per *transition* into the no-album state (``_no_album_logged``
latch). ``log.exception`` is reserved for real save failures.

These are source-structure pins (the 1,100-line script's poll loop is
not importable-and-runnable at CI time without PipeWire/Pi hardware);
the live-rate recheck lives in the task's findings.json:
``journalctl --user -u album-identifier.service --since "-1h"
| grep -c "No album currently identified"`` -> expect < 10/h.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "album-identifier.py"


def _source() -> str:
    return SCRIPT.read_text()


class TestNoAlbumPolarityFixed:
    def test_no_album_state_is_not_raised_as_exception(self) -> None:
        """The inverted-polarity pattern must stay dead: the routine
        no-album state may never re-enter the save-try as a raise that
        the blanket except converts to ERROR+traceback."""
        assert 'raise ValueError("No album currently identified")' not in _source(), (
            "scripts/album-identifier.py reintroduced the no-album raise "
            "inside the PNG-save try — the W4-ALBUM-POLARITY-STORM pattern "
            "(~129 ERR/h of expected-state tracebacks). Gate on "
            "_current_album BEFORE the try instead."
        )

    def test_transition_latch_exists(self) -> None:
        """The no-album state logs once per transition (INFO), not per
        tick — the latch variable is the mechanism."""
        src = _source()
        assert "_no_album_logged" in src, (
            "transition latch _no_album_logged removed; without it the "
            "no-album INFO either spams every tick or disappears entirely"
        )

    def test_no_album_logging_is_info_not_error(self) -> None:
        """Whatever message announces the no-album state must go through
        log.info — never log.error/log.exception."""
        src = _source()
        for match in re.finditer(r"log\.(\w+)\([^)]*[Nn]o album currently identified", src):
            assert match.group(1) == "info", (
                f"no-album state logged via log.{match.group(1)}; the whole "
                f"point of W4-ALBUM-POLARITY-STORM is that this is an "
                f"expected state — INFO on transition only"
            )
