"""The research-desk ledger is the capability's receipt surface; these pin its shape.

Two properties are load-bearing: a row can only be built from the named fields (so
the bearer credential has no route into the file), and a write that fails is a
raised error rather than a silent drop (so a receipt id handed to an external agent
always has a row behind it).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared import research_desk_ledger as ledger


def test_record_is_a_closed_schema() -> None:
    record = ledger.build_record(
        tool="deliver_result",
        outcome="ok",
        caller_ip="127.0.0.1",
        request_id="req-1",
        bytes_in=10,
        bytes_out=20,
        receipt_id="rd-1",
    )
    assert set(record) == {
        "ledger_schema",
        "at",
        "tool",
        "outcome",
        "request_id",
        "receipt_id",
        "result_count",
        "bytes_in",
        "bytes_out",
        "reason_code",
        "caller_ip",
    }
    assert record["ledger_schema"] == ledger.LEDGER_SCHEMA


def test_record_builder_has_no_passthrough_for_arbitrary_fields() -> None:
    """There is no ``**extra``; a credential cannot arrive by being handed in."""
    with pytest.raises(TypeError):
        ledger.build_record(  # type: ignore[call-arg]
            tool="fetch_request",
            outcome="ok",
            caller_ip=None,
            authorization="Bearer super-secret",
        )


@pytest.mark.parametrize("tool", ["", "search", "list_open_requests", "deliver"])
def test_unknown_tool_is_a_loud_failure(tool: str) -> None:
    with pytest.raises(ValueError, match="unknown research-desk tool"):
        ledger.build_record(tool=tool, outcome="ok", caller_ip=None)


@pytest.mark.parametrize("outcome", ["", "success", "fail"])
def test_unknown_outcome_is_a_loud_failure(outcome: str) -> None:
    with pytest.raises(ValueError, match="unknown outcome"):
        ledger.build_record(tool="fetch_request", outcome=outcome, caller_ip=None)


def test_append_and_read_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    for index in range(3):
        ledger.append(
            ledger.build_record(
                tool="fetch_request",
                outcome="ok",
                caller_ip="10.0.0.1",
                request_id=f"req-{index}",
            ),
            path=path,
        )
    rows = ledger.read_records(path)
    assert [row["request_id"] for row in rows] == ["req-0", "req-1", "req-2"]
    assert all(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())


def test_read_of_an_absent_ledger_is_empty(tmp_path: Path) -> None:
    assert ledger.read_records(tmp_path / "nothing.jsonl") == []


def test_append_raises_rather_than_dropping_a_receipt(tmp_path: Path) -> None:
    """Unwritable ledger => the call fails. A receipt with no row behind it is a lie."""
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    blocked.chmod(0o500)
    try:
        with pytest.raises(OSError):
            ledger.append(
                ledger.build_record(tool="deliver_result", outcome="ok", caller_ip=None),
                path=blocked / "ledger.jsonl",
            )
    finally:
        blocked.chmod(0o700)


def test_ledger_path_honours_the_environment_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAPAX_RESEARCH_DESK_LEDGER", "/tmp/desk-ledger.jsonl")
    assert ledger.ledger_path_from_env() == Path("/tmp/desk-ledger.jsonl")
    monkeypatch.setenv("HAPAX_RESEARCH_DESK_LEDGER", "  ")
    assert ledger.ledger_path_from_env() == ledger.DEFAULT_LEDGER_PATH
