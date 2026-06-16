"""The seg-prep ledger writers append under flock and preserve exact byte format.

A manual ``batch_prep_segments.sh`` / smoke run hitting the same shared date dir
concurrently with the 04:00 oneshot would tear NDJSON lines (rows exceed
``PIPE_BUF``, so raw ``O_APPEND`` is not atomic). Routing the three prep writers
through ``shared.jsonl_append`` (flock-on-sidecar + single ``os.write``) closes
that vector. These tests pin: (1) the write goes through the helper (the ``.lock``
sidecar exists), (2) the bytes are unchanged (canonical ``sort_keys=True``), and
(3) each writer's prior fail-mode is preserved — council-decisions FAIL-OPEN,
candidate-ledger + prep-diagnostic FAIL-LOUD.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.hapax_daimonion import daily_segment_prep as prep


def _is_canonical_line(line: str) -> bool:
    """The line is byte-identical to json.dumps(parsed, sort_keys=True)."""
    return line == json.dumps(json.loads(line), sort_keys=True)


def test_council_decisions_append_uses_flock_and_canonical_bytes(tmp_path: Path) -> None:
    prep._append_council_decisions_ledger(
        tmp_path,
        "prog-1",
        {"coherence": {"mean_score": 4.0, "criterion": 3.0}},
        terminal_status="released",
    )
    ledger = tmp_path / prep.COUNCIL_DECISIONS_LEDGER_FILENAME
    # the flock sidecar proves the write went through shared.jsonl_append
    assert ledger.with_name(ledger.name + ".lock").exists()
    lines = ledger.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["terminal_status"] == "released"
    assert row["council_decisions"]["coherence"]["criterion"] == 3.0
    assert _is_canonical_line(lines[0])


def test_candidate_ledger_append_uses_flock_and_canonical_bytes(tmp_path: Path) -> None:
    prep._append_candidate_ledger(
        tmp_path,
        {"programme_id": "p", "artifact_sha256": "deadbeef"},
        tmp_path / "artifact.json",
    )
    ledger = tmp_path / prep.CANDIDATE_LEDGER
    assert ledger.with_name(ledger.name + ".lock").exists()
    lines = ledger.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["programme_id"] == "p"
    assert _is_canonical_line(lines[0])


def test_prep_diagnostic_append_uses_flock_and_canonical_bytes(tmp_path: Path) -> None:
    prep._write_prep_diagnostic_outcome(
        tmp_path,
        prep_session=None,
        programme_id="prog-1",
        terminal_status="no_candidate",
        terminal_reason="test_reason",
        not_loadable_reason="",
    )
    ledger = tmp_path / prep.PREP_DIAGNOSTIC_LEDGER_FILENAME
    assert ledger.with_name(ledger.name + ".lock").exists()
    lines = ledger.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["terminal_status"] == "no_candidate"
    assert _is_canonical_line(lines[0])


def test_writers_create_missing_parent_dir(tmp_path: Path) -> None:
    """The explicit mkdir was removed; append_jsonl must create the (date) dir.
    Append into a NON-existent prep dir and confirm the ledger is materialised."""
    prep_dir = tmp_path / "does-not-exist-yet" / "2026-06-16"
    assert not prep_dir.exists()
    prep._append_council_decisions_ledger(
        prep_dir,
        "prog-1",
        {"coherence": {"mean_score": 4.0, "criterion": 3.0}},
        terminal_status="released",
    )
    ledger = prep_dir / prep.COUNCIL_DECISIONS_LEDGER_FILENAME
    assert ledger.is_file()
    assert json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])["terminal_status"] == (
        "released"
    )


def test_fail_modes_preserved_per_writer(tmp_path: Path) -> None:
    """Force a REAL append failure and assert the actual outcome — not a mock. Each
    LEDGER PATH is pre-created as a DIRECTORY, so the helper's data-fd open raises
    IsADirectoryError (an OSError) at the append step itself — isolating each
    writer's append fail-mode from any upstream work (e.g. the diagnostic dossier
    write, which uses the real prep dir and succeeds first). council-decisions
    stays FAIL-OPEN (swallows, no exception escapes); candidate-ledger and
    prep-diagnostic stay FAIL-LOUD (the OSError propagates)."""
    (tmp_path / prep.COUNCIL_DECISIONS_LEDGER_FILENAME).mkdir()
    (tmp_path / prep.CANDIDATE_LEDGER).mkdir()
    (tmp_path / prep.PREP_DIAGNOSTIC_LEDGER_FILENAME).mkdir()

    # FAIL-OPEN: the council writer must NOT raise (try/except + log.debug).
    prep._append_council_decisions_ledger(
        tmp_path,
        "p",
        {"coherence": {"mean_score": 4.0, "criterion": 3.0}},
        terminal_status="released",
    )

    # FAIL-LOUD: the candidate + diagnostic writers must propagate the error.
    with pytest.raises(OSError):
        prep._append_candidate_ledger(tmp_path, {"programme_id": "p"}, tmp_path / "a.json")

    with pytest.raises(OSError):
        prep._write_prep_diagnostic_outcome(
            tmp_path,
            prep_session=None,
            programme_id="p",
            terminal_status="no_candidate",
            terminal_reason="r",
            not_loadable_reason="",
        )
