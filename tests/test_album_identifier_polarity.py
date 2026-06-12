"""Polarity pin for scripts/album-identifier.py (W4-ALBUM-POLARITY-STORM).

The audit-w4 finding: the routine no-album state (nothing on the deck,
or the last identification cleared) took
``raise ValueError("No album currently identified")`` INSIDE the
PNG-save ``try``, where the blanket ``except Exception:
log.exception("Album cover save failed")`` converted the EXPECTED idle
state into a full ERROR+traceback on every poll tick — ~129 ERR/h,
~776 in 6h (anchor class obse-2: inverted polarity, expected state
logged as failure). Alert fatigue from this storm buries real failures.

The fix routes the save decision through ``_album_cover_save_allowed()``
— gate BEFORE the try, one INFO per *transition* into the no-album state
(``_no_album_logged`` latch). ``log.exception`` is reserved for real
save failures.

The behavioral tests below exercise the REAL helper (the module is
import-safe; only ``main()`` touches PipeWire/Pi hardware). The
source-structure pins stay as a second line against the storm pattern
re-entering via a different path. Live-rate recheck in findings.json:
``journalctl --user -u album-identifier.service --since "-1h"
| grep -c "No album currently identified"`` -> expect < 10/h.
"""

from __future__ import annotations

import importlib.util
import logging
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "album-identifier.py"


@pytest.fixture(scope="module")
def album_module():
    spec = importlib.util.spec_from_file_location("album_identifier", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(REPO_ROOT))
    try:
        spec.loader.exec_module(mod)
    finally:
        if str(REPO_ROOT) in sys.path:
            sys.path.remove(str(REPO_ROOT))
    return mod


@pytest.fixture()
def fresh_state(album_module):
    """Reset the gate's module globals between tests."""
    album_module._current_album = {}
    album_module._no_album_logged = False
    return album_module


def _no_album_infos(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if "No album currently identified" in r.getMessage()]


class TestCoverSaveGateBehavior:
    """Drive the real gate through the storm scenario: many consecutive
    no-album ticks must produce exactly ONE INFO and zero ERRORs."""

    def test_no_album_ticks_log_info_exactly_once(self, fresh_state, caplog) -> None:
        mod = fresh_state
        mod._current_album = None
        with caplog.at_level(logging.DEBUG, logger="album-identifier"):
            decisions = [mod._album_cover_save_allowed() for _ in range(50)]
        assert decisions == [False] * 50
        infos = _no_album_infos(caplog)
        assert len(infos) == 1, (
            f"{len(infos)} no-album log lines over 50 idle ticks — the storm "
            f"is back (was ~129/h before the latch)"
        )
        assert infos[0].levelno == logging.INFO
        assert not [r for r in caplog.records if r.levelno >= logging.ERROR], (
            "no-album idle state produced ERROR records — inverted polarity"
        )

    def test_album_present_allows_save_and_rearms_latch(self, fresh_state, caplog) -> None:
        mod = fresh_state
        mod._current_album = None
        with caplog.at_level(logging.DEBUG, logger="album-identifier"):
            assert mod._album_cover_save_allowed() is False
            mod._current_album = {"artist": "Coil", "title": "Musick"}
            assert mod._album_cover_save_allowed() is True
            # transition back into no-album: latch re-armed -> one NEW info
            mod._current_album = None
            assert mod._album_cover_save_allowed() is False
        assert len(_no_album_infos(caplog)) == 2

    def test_initial_empty_dict_state_still_saves(self, fresh_state) -> None:
        """Boot state is {} (no identification yet, but not the cleared
        None state) — the gate must keep the historical behavior of
        refreshing the cover PNG every poll."""
        mod = fresh_state
        mod._current_album = {}
        assert mod._album_cover_save_allowed() is True


UNIT_FILE = REPO_ROOT / "systemd" / "units" / "album-identifier.service"
RELEASE_ROOT = "%h/.cache/hapax/source-activation/worktree"


class TestReleaseRootContract:
    """The versioned unit runs from the source-activation release root,
    never the mutable main clone (review round 2, PR #4106: the root
    migration itself needs a pin or it can silently regress while the
    'release-root' claim still looks tested)."""

    def test_exec_paths_use_release_root(self) -> None:
        text = UNIT_FILE.read_text()
        for directive in ("ExecStart=", "WorkingDirectory="):
            line = next(
                line for line in text.splitlines() if line.startswith(directive)
            )
            assert RELEASE_ROOT in line, (
                f"{directive} does not point at the release root: {line!r}. "
                f"Running from a mutable checkout lets live behavior drift "
                f"with un-activated local edits (audit-w1 #4090 class)."
            )
        assert "%h/projects/hapax-council" not in text, (
            "unit references the mutable main clone — release-root regression"
        )

    def test_runtime_source_check_guards_start(self) -> None:
        text = UNIT_FILE.read_text()
        assert (
            "ExecStartPre=" in text
            and "hapax-compositor-runtime-source-check" in text
            and "--require-file scripts/album-identifier.py" in text
        ), (
            "ExecStartPre runtime-source-check missing — the unit could "
            "start against a release root that lacks the script"
        )


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
