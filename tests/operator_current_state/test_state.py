from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from agents.operator_current_state.state import (
    OperatorCurrentStateItem,
    SourceStatus,
    parse_timestamp,
)


def _ts() -> datetime:
    return datetime(2026, 5, 13, 14, 0, tzinfo=UTC)


def test_item_rejects_operator_required_watch() -> None:
    with pytest.raises(ValidationError):
        OperatorCurrentStateItem(
            **{
                "id": "x",
                "class": "watch",
                "summary": "bad",
                "operator_required": True,
                "stale_after": _ts() + timedelta(minutes=15),
                "source_ref": "test",
                "evidence_ref": "test",
                "predicate_family": "methodology",
                "predicate_value": "active",
            }
        )


def test_source_status_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        SourceStatus(
            path="x",
            required=True,
            authority="derived",
            predicate_value="fresh",
            evaluated_at=_ts(),
            stale_after=_ts() + timedelta(minutes=5),
            extra_field=True,
        )


def test_parse_timestamp_accepts_z_suffix() -> None:
    parsed = parse_timestamp("2026-05-13T14:00:00Z")
    assert parsed == _ts()
