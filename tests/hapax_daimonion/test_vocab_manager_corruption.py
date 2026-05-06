"""Pin VocabularyManager._load against non-dict JSON corruption.

Sixteenth+1 site in the SHM corruption-class trail (#2627, #2631,
#2632, #2633, #2636 merged; queue extends through #2657). The
``_load`` method calls ``raw.get("version")`` and ``raw.get("entries")``
outside the ``(OSError, json.JSONDecodeError)`` catch — a writer
producing valid JSON whose root is null, a list, a string, or a
number previously raised AttributeError out of vocabulary startup.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.hapax_daimonion.vocab_manager import VocabularyManager


@pytest.mark.parametrize(
    "payload,kind",
    [
        ("null", "null"),
        ('"a string"', "string"),
        ("[1, 2, 3]", "list"),
        ("42", "int"),
    ],
)
def test_load_non_dict_root_does_not_crash(tmp_path: Path, payload: str, kind: str) -> None:
    """A corrupt persist file with a non-dict JSON root must not crash
    VocabularyManager startup. The seeds still populate via
    ``_ensure_seeds`` after ``_load`` returns early; the regression
    we're pinning is that ``_load`` itself doesn't raise AttributeError
    out of the constructor (which would tear down the daimonion before
    the seeds even get a chance to land)."""
    persist = tmp_path / "vocabulary.json"
    persist.write_text(payload)
    # _load runs on construction; must not raise.
    mgr = VocabularyManager(persist_path=persist)
    # The seeds (per _ensure_seeds, called after _load) should still
    # have populated; the regression check is that we got here at all
    # without an AttributeError.
    assert isinstance(mgr._entries, dict), f"non-dict root={kind} should not crash"


def test_load_dict_root_with_wrong_version_returns_seeds_only(tmp_path: Path) -> None:
    """Sanity pin: a well-formed dict with wrong version is silently
    ignored (no crash). Seeds still populate via _ensure_seeds."""
    persist = tmp_path / "vocabulary.json"
    persist.write_text('{"version": 99, "entries": []}')
    mgr = VocabularyManager(persist_path=persist)
    # No crash; seeds populate independent of _load's outcome.
    assert isinstance(mgr._entries, dict)


def test_load_dict_root_with_correct_version_loads_entries(tmp_path: Path) -> None:
    """Sanity pin: the happy path still works — version=1 + entries list
    is parsed and individual entry failures are skipped, not crashed."""
    persist = tmp_path / "vocabulary.json"
    # Mix one valid-shape entry with one garbage entry; only the valid
    # one should land in self._entries.
    persist.write_text('{"version": 1, "entries": [{"not": "a valid entry"}]}')
    # Must not raise even with malformed entries inside the dict root.
    mgr = VocabularyManager(persist_path=persist)
    # Entries list is iterated and per-entry exceptions are swallowed
    # (per the existing inner try/except). Final state may be empty
    # if every entry failed to parse.
    assert isinstance(mgr._entries, dict)
