"""Regression: a fail-open S2 composability gate must NOT masquerade as a clean accept.

Eval-plane honesty (audit 2026-06-19): the S2 gate fail-opens (errored=True,
accept=True) on a degraded LLM call; the ledger previously recorded accepted=True,
indistinguishable from a real verified pass. These tests pin the honest record.
"""

import json

from agents.hapax_daimonion.daily_segment_prep import (
    COUNCIL_DECISIONS_LEDGER_FILENAME,
    _append_s2_composability_ledger,
)


def _rows(prep_dir):
    text = (prep_dir / COUNCIL_DECISIONS_LEDGER_FILENAME).read_text()
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def test_real_accept_records_clean_pass(tmp_path):
    _append_s2_composability_ledger(
        tmp_path,
        programme_id="p1",
        role="rant",
        topic="t",
        segment_beats=[],
        accepted=True,
        reason="",
        errored=False,
    )
    gate = _rows(tmp_path)[-1]["producer_gate"]
    assert gate["accepted"] is True
    assert gate["errored"] is False
    assert gate["fail_open"] is False


def test_fail_open_not_recorded_as_clean_accept(tmp_path):
    """errored=True + accepted=True (fail-open) -> recorded accepted=False, errored=True."""
    _append_s2_composability_ledger(
        tmp_path,
        programme_id="p1",
        role="rant",
        topic="t",
        segment_beats=[],
        accepted=True,
        reason="gate truncated",
        errored=True,
    )
    row = _rows(tmp_path)[-1]
    assert row["producer_gate"]["accepted"] is False
    assert row["producer_gate"]["errored"] is True
    assert row["producer_gate"]["fail_open"] is True
    assert row["terminal_status"] == "s2_gate_errored"
    assert row["terminal"] is True


def test_real_reject_recorded(tmp_path):
    _append_s2_composability_ledger(
        tmp_path,
        programme_id="p1",
        role="tier_list",
        topic="t",
        segment_beats=[],
        accepted=False,
        reason="parallel list",
        errored=False,
    )
    row = _rows(tmp_path)[-1]
    assert row["producer_gate"]["accepted"] is False
    assert row["terminal_status"] == "no_candidate"
    assert row["terminal_reason"] == "uncomposable_topic_type"
