"""Tests for ``agents.mail_monitor.watch``."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from agents.mail_monitor import watch


def _service_with_watch(response: dict) -> mock.Mock:
    service = mock.Mock()
    service.users.return_value.watch.return_value.execute.return_value = response
    return service


# ── call_watch body shape (§5.2 invariant) ────────────────────────────


def test_call_watch_body_includes_topic_and_label_filter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(watch, "WATCH_STATE_PATH", tmp_path / "watch.json")
    service = _service_with_watch({"historyId": "12345", "expiration": "9999999999000"})

    response = watch.call_watch(
        service,
        topic_path="projects/my-project/topics/hapax-mail-monitor",
        label_ids=["L_v", "L_s", "L_o", "L_d"],
    )

    assert response["historyId"] == "12345"
    body = service.users.return_value.watch.call_args.kwargs["body"]
    assert body["topicName"] == "projects/my-project/topics/hapax-mail-monitor"
    assert body["labelIds"] == ["L_v", "L_s", "L_o", "L_d"]
    assert body["labelFilterAction"] == "INCLUDE"


def test_call_watch_label_filter_action_constant_is_include() -> None:
    """Spec §5.2 invariant — pinned at module-load level."""
    assert watch.WATCH_LABEL_FILTER_ACTION == "INCLUDE"


def test_call_watch_raises_when_label_ids_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(watch, "WATCH_STATE_PATH", tmp_path / "watch.json")
    service = _service_with_watch({"historyId": "1", "expiration": "1"})

    with pytest.raises(watch.WatchError, match="empty"):
        watch.call_watch(
            service,
            topic_path="projects/my-project/topics/hapax-mail-monitor",
            label_ids=[],
        )


# ── persistence ───────────────────────────────────────────────────────


def test_call_watch_persists_response_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = tmp_path / "watch.json"
    monkeypatch.setattr(watch, "WATCH_STATE_PATH", state_path)
    service = _service_with_watch({"historyId": "abc", "expiration": "1234567890000"})

    watch.call_watch(
        service,
        topic_path="projects/my-project/topics/hapax-mail-monitor",
        label_ids=["L_v"],
    )

    payload = json.loads(state_path.read_text())
    assert payload == {"historyId": "abc", "expiration": "1234567890000"}
    # Tmp file should be cleaned up after rename.
    assert not (tmp_path / "watch.tmp").exists()


def test_call_watch_creates_parent_dir_if_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = tmp_path / "nested" / "deep" / "watch.json"
    monkeypatch.setattr(watch, "WATCH_STATE_PATH", state_path)
    service = _service_with_watch({"historyId": "1", "expiration": "1"})

    watch.call_watch(
        service,
        topic_path="projects/p/topics/hapax-mail-monitor",
        label_ids=["L"],
    )

    assert state_path.exists()


# ── load_watch_state ──────────────────────────────────────────────────


def test_load_watch_state_returns_none_when_file_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(watch, "WATCH_STATE_PATH", tmp_path / "missing.json")
    assert watch.load_watch_state() is None


def test_load_watch_state_returns_dict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_path = tmp_path / "watch.json"
    state_path.write_text('{"historyId": "x", "expiration": "12"}')
    monkeypatch.setattr(watch, "WATCH_STATE_PATH", state_path)
    assert watch.load_watch_state() == {"historyId": "x", "expiration": "12"}


def test_load_watch_state_returns_none_on_corrupted_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = tmp_path / "watch.json"
    state_path.write_text("{not json}")
    monkeypatch.setattr(watch, "WATCH_STATE_PATH", state_path)
    assert watch.load_watch_state() is None


# ── watch_age_s ───────────────────────────────────────────────────────


def test_watch_age_s_returns_none_when_no_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(watch, "WATCH_STATE_PATH", tmp_path / "watch.json")
    assert watch.watch_age_s() is None


def test_watch_age_s_computed_from_expiration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = tmp_path / "watch.json"
    # Expiration = now + 7 days. Age = 0.
    seven_days_s = 7 * 24 * 3600.0
    now_s = 1_700_000_000.0
    expiration_ms = int((now_s + seven_days_s) * 1000)
    state_path.write_text(json.dumps({"historyId": "x", "expiration": str(expiration_ms)}))
    monkeypatch.setattr(watch, "WATCH_STATE_PATH", state_path)

    age = watch.watch_age_s(now=now_s)
    assert age is not None
    assert abs(age) < 1.0


def test_watch_age_s_returns_none_on_missing_expiration_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = tmp_path / "watch.json"
    state_path.write_text('{"historyId": "x"}')
    monkeypatch.setattr(watch, "WATCH_STATE_PATH", state_path)
    assert watch.watch_age_s() is None
