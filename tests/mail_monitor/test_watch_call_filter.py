"""Spec §5.2 / cc-task-005 invariant: ``users.watch()`` is never invoked
without ``labelFilterAction=INCLUDE`` and a non-empty ``labelIds``
list.

This is a CI-gate test — a regression here turns the daemon into a
full-mailbox reader. Failing this test should block merge.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from agents.mail_monitor import watch


def test_watch_call_always_uses_include_filter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(watch, "WATCH_STATE_PATH", tmp_path / "watch.json")
    captured_bodies: list[dict] = []

    def _capture(*args: object, **kwargs: object) -> mock.Mock:
        captured_bodies.append(kwargs["body"])
        execute = mock.Mock()
        execute.execute.return_value = {"historyId": "x", "expiration": "1"}
        return execute

    service = mock.Mock()
    service.users.return_value.watch = _capture

    for label_set in (
        ["L_v", "L_s", "L_o", "L_d"],
        ["L_v"],
        ["L_v", "L_d"],
    ):
        watch.call_watch(
            service,
            topic_path="projects/p/topics/hapax-mail-monitor",
            label_ids=label_set,
        )

    assert len(captured_bodies) == 3
    for body in captured_bodies:
        assert body["labelFilterAction"] == "INCLUDE", (
            "watch() invoked WITHOUT INCLUDE filter — spec §5.2 invariant. "
            "Daemon would observe non-Hapax mail. Hard-stop."
        )
        assert body["labelIds"], "watch() invoked with empty labelIds — spec §5.2 invariant."


def test_watch_call_refuses_empty_label_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(watch, "WATCH_STATE_PATH", tmp_path / "watch.json")
    service = mock.Mock()
    service.users.return_value.watch.return_value.execute.return_value = {
        "historyId": "x",
        "expiration": "1",
    }

    with pytest.raises(watch.WatchError):
        watch.call_watch(
            service,
            topic_path="projects/p/topics/hapax-mail-monitor",
            label_ids=[],
        )

    # Crucially: the empty-label_ids case must NOT have called watch().
    service.users.return_value.watch.assert_not_called()
