"""Tests for cc-hygiene ntfy dispatcher (PR5 surface A).

Per project convention, no shared conftest fixtures — each test builds its
own throttle file under ``tmp_path``. ``shared.notify.send_notification``
is replaced by an in-test sender adapter; we never hit the network.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# Make the script-side package importable.
_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from cc_hygiene.models import HygieneEvent  # noqa: E402
from cc_hygiene.ntfy import (  # noqa: E402
    NTFY_TOPIC,
    ORPHAN_PR_NTFY_AGE_HOURS,
    RELAY_STALE_NTFY_AGE_MIN,
    THROTTLE_MIN,
    dispatch_alerts,
    is_high_severity,
)

# ----------------------------------------------------------------------------
# helpers / sender stub
# ----------------------------------------------------------------------------


class _RecordingSender:
    """Replacement for ``shared.notify.send_notification`` capturing all calls."""

    def __init__(self, *, return_value: bool = True) -> None:
        self.calls: list[dict[str, Any]] = []
        self.return_value = return_value

    def __call__(
        self,
        title: str,
        message: str,
        *,
        priority: str = "default",
        tags: list[str] | None = None,
        topic: str | None = None,
        click_url: str | None = None,
    ) -> bool:
        self.calls.append(
            {
                "title": title,
                "message": message,
                "priority": priority,
                "tags": tags,
                "topic": topic,
                "click_url": click_url,
            }
        )
        return self.return_value


def _now() -> datetime:
    return datetime(2026, 4, 26, 12, 0, 0, tzinfo=UTC)


# ----------------------------------------------------------------------------
# severity gating
# ----------------------------------------------------------------------------


def test_violation_severity_is_high() -> None:
    """Any ``severity == 'violation'`` event triggers an alert (e.g. duplicate-claim)."""
    e = HygieneEvent(
        timestamp=_now(),
        check_id="duplicate_claim",
        severity="violation",
        task_id="cc-task-X",
        session=None,
        message="duplicate",
    )
    assert is_high_severity(e)


def test_ghost_claimed_violation_is_high() -> None:
    e = HygieneEvent(
        timestamp=_now(),
        check_id="ghost_claimed",
        severity="violation",
        task_id="cc-task-Y",
        message="ghost",
    )
    assert is_high_severity(e)


def test_warning_severity_alone_is_not_high() -> None:
    """Generic ``warning`` events do NOT escalate to ntfy (steady-state)."""
    e = HygieneEvent(
        timestamp=_now(),
        check_id="wip_limit",
        severity="warning",
        session="alpha",
        message="wip",
    )
    assert not is_high_severity(e)


def test_orphan_pr_below_age_threshold_skipped() -> None:
    now = _now()
    created = (now - timedelta(hours=2)).replace(microsecond=0).isoformat()
    e = HygieneEvent(
        timestamp=now,
        check_id="orphan_pr",
        severity="warning",
        message="pr orphan",
        metadata={"createdAt": created.replace("+00:00", "Z")},
    )
    assert not is_high_severity(e)


def test_orphan_pr_at_age_threshold_alerts() -> None:
    now = _now()
    created = now - timedelta(hours=ORPHAN_PR_NTFY_AGE_HOURS, minutes=1)
    e = HygieneEvent(
        timestamp=now,
        check_id="orphan_pr",
        severity="warning",
        message="pr orphan",
        metadata={"createdAt": created.isoformat().replace("+00:00", "Z")},
    )
    assert is_high_severity(e)


def test_orphan_pr_missing_metadata_skipped() -> None:
    e = HygieneEvent(
        timestamp=_now(),
        check_id="orphan_pr",
        severity="warning",
        message="pr orphan",
        metadata={},
    )
    assert not is_high_severity(e)


def test_relay_stale_below_60min_skipped() -> None:
    e = HygieneEvent(
        timestamp=_now(),
        check_id="relay_yaml_stale",
        severity="warning",
        session="beta",
        message="stale",
        metadata={"age_minutes": "45", "role": "beta"},
    )
    assert not is_high_severity(e)


def test_relay_stale_at_60min_alerts() -> None:
    e = HygieneEvent(
        timestamp=_now(),
        check_id="relay_yaml_stale",
        severity="warning",
        session="beta",
        message="stale",
        metadata={"age_minutes": str(RELAY_STALE_NTFY_AGE_MIN), "role": "beta"},
    )
    assert is_high_severity(e)


# ----------------------------------------------------------------------------
# dispatch_alerts: send + skip semantics
# ----------------------------------------------------------------------------


def test_dispatch_sends_for_violation_event(tmp_path: Path) -> None:
    sender = _RecordingSender()
    throttle = tmp_path / "throttle.json"
    e = HygieneEvent(
        timestamp=_now(),
        check_id="duplicate_claim",
        severity="violation",
        task_id="cc-task-DUPE",
        message="claimed twice",
        metadata={"sessions": "alpha,beta", "window_minutes": "5"},
    )
    results = dispatch_alerts([e], throttle_path=throttle, sender=sender, now=_now())
    assert len(results) == 1
    assert results[0].sent
    assert results[0].reason == "sent"
    assert len(sender.calls) == 1
    call = sender.calls[0]
    assert "duplicate_claim" in call["title"]
    assert "cc-task-DUPE" in call["message"]
    assert call["topic"] == NTFY_TOPIC
    assert call["priority"] == "high"
    assert call["click_url"] is not None
    assert "obsidian://open" in call["click_url"]


def test_dispatch_skips_sub_threshold_event(tmp_path: Path) -> None:
    sender = _RecordingSender()
    throttle = tmp_path / "throttle.json"
    e = HygieneEvent(
        timestamp=_now(),
        check_id="offered_stale",
        severity="info",
        task_id="cc-old",
        message="old offer",
    )
    results = dispatch_alerts([e], throttle_path=throttle, sender=sender, now=_now())
    assert len(results) == 1
    assert not results[0].sent
    assert results[0].reason == "sub-threshold"
    assert sender.calls == []


# ----------------------------------------------------------------------------
# throttle: 1 alert per topic-class per 5 min
# ----------------------------------------------------------------------------


def test_throttle_blocks_second_alert_within_window(tmp_path: Path) -> None:
    sender = _RecordingSender()
    throttle = tmp_path / "throttle.json"
    e1 = HygieneEvent(
        timestamp=_now(),
        check_id="duplicate_claim",
        severity="violation",
        task_id="cc-A",
        message="dup",
    )
    e2 = HygieneEvent(
        timestamp=_now(),
        check_id="duplicate_claim",
        severity="violation",
        task_id="cc-B",
        message="dup",
    )

    # First sweep: e1 sent.
    r1 = dispatch_alerts([e1], throttle_path=throttle, sender=sender, now=_now())
    assert r1[0].sent

    # Second sweep within 5min: e2 throttled (same check_id topic-class).
    r2 = dispatch_alerts(
        [e2],
        throttle_path=throttle,
        sender=sender,
        now=_now() + timedelta(minutes=THROTTLE_MIN - 1),
    )
    assert not r2[0].sent
    assert r2[0].reason == "throttled"
    assert len(sender.calls) == 1


def test_throttle_releases_after_window(tmp_path: Path) -> None:
    sender = _RecordingSender()
    throttle = tmp_path / "throttle.json"
    e = HygieneEvent(
        timestamp=_now(),
        check_id="duplicate_claim",
        severity="violation",
        task_id="cc-A",
        message="dup",
    )
    dispatch_alerts([e], throttle_path=throttle, sender=sender, now=_now())
    assert len(sender.calls) == 1

    # After the window, the same topic-class can fire again.
    later = _now() + timedelta(minutes=THROTTLE_MIN + 1)
    e_later = HygieneEvent(
        timestamp=later,
        check_id="duplicate_claim",
        severity="violation",
        task_id="cc-A",
        message="dup",
    )
    dispatch_alerts([e_later], throttle_path=throttle, sender=sender, now=later)
    assert len(sender.calls) == 2


def test_throttle_per_topic_class_independent(tmp_path: Path) -> None:
    """Different ``check_id`` events do not share a throttle bucket."""
    sender = _RecordingSender()
    throttle = tmp_path / "throttle.json"
    now = _now()
    age_iso = (
        (now - timedelta(hours=ORPHAN_PR_NTFY_AGE_HOURS + 1)).isoformat().replace("+00:00", "Z")
    )
    events = [
        HygieneEvent(
            timestamp=now,
            check_id="duplicate_claim",
            severity="violation",
            task_id="cc-DUP",
            message="dup",
        ),
        HygieneEvent(
            timestamp=now,
            check_id="orphan_pr",
            severity="warning",
            message="pr orphan",
            metadata={"createdAt": age_iso, "pr": "1234"},
        ),
    ]
    dispatch_alerts(events, throttle_path=throttle, sender=sender, now=now)
    # Both alerts fire — independent throttle buckets.
    assert len(sender.calls) == 2
    titles = sorted(call["title"] for call in sender.calls)
    assert any("duplicate_claim" in t for t in titles)
    assert any("orphan_pr" in t for t in titles)


def test_throttle_state_persists_atomically(tmp_path: Path) -> None:
    sender = _RecordingSender()
    throttle = tmp_path / "throttle.json"
    e = HygieneEvent(
        timestamp=_now(),
        check_id="duplicate_claim",
        severity="violation",
        task_id="cc-A",
        message="dup",
    )
    dispatch_alerts([e], throttle_path=throttle, sender=sender, now=_now())
    assert throttle.exists()
    payload = json.loads(throttle.read_text(encoding="utf-8"))
    assert any("duplicate_claim" in k for k in payload)


# ----------------------------------------------------------------------------
# killswitch
# ----------------------------------------------------------------------------


def test_killswitch_skips_all(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("HAPAX_CC_HYGIENE_OFF", "1")
    sender = _RecordingSender()
    throttle = tmp_path / "throttle.json"
    e = HygieneEvent(
        timestamp=_now(),
        check_id="duplicate_claim",
        severity="violation",
        task_id="cc-A",
        message="dup",
    )
    results = dispatch_alerts([e], throttle_path=throttle, sender=sender, now=_now())
    assert results == []
    assert sender.calls == []
    assert not throttle.exists()


# ----------------------------------------------------------------------------
# resilience
# ----------------------------------------------------------------------------


def test_send_failure_does_not_crash(tmp_path: Path) -> None:
    def _boom(*_: Any, **__: Any) -> bool:
        raise RuntimeError("ntfy down")

    throttle = tmp_path / "throttle.json"
    e = HygieneEvent(
        timestamp=_now(),
        check_id="duplicate_claim",
        severity="violation",
        task_id="cc-A",
        message="dup",
    )
    results = dispatch_alerts([e], throttle_path=throttle, sender=_boom, now=_now())
    assert len(results) == 1
    assert not results[0].sent
    assert results[0].reason == "send-error"
    # On send-error the throttle is NOT updated (so a retry next sweep is allowed).
    assert not throttle.exists()


def test_corrupt_throttle_file_recovers(tmp_path: Path) -> None:
    sender = _RecordingSender()
    throttle = tmp_path / "throttle.json"
    throttle.write_text("not-json-at-all", encoding="utf-8")
    e = HygieneEvent(
        timestamp=_now(),
        check_id="duplicate_claim",
        severity="violation",
        task_id="cc-A",
        message="dup",
    )
    results = dispatch_alerts([e], throttle_path=throttle, sender=sender, now=_now())
    assert results[0].sent
    payload = json.loads(throttle.read_text(encoding="utf-8"))
    assert any("duplicate_claim" in k for k in payload)


# ----------------------------------------------------------------------------
# message format
# ----------------------------------------------------------------------------


def test_alert_body_is_terse(tmp_path: Path) -> None:
    sender = _RecordingSender()
    throttle = tmp_path / "throttle.json"
    e = HygieneEvent(
        timestamp=_now(),
        check_id="duplicate_claim",
        severity="violation",
        task_id="cc-task-MULTI",
        session="alpha",
        message="claimed simultaneously by sessions ['alpha', 'beta'] within 5min",
    )
    dispatch_alerts([e], throttle_path=throttle, sender=sender, now=_now())
    body = sender.calls[0]["message"]
    title = sender.calls[0]["title"]
    assert body.startswith("[VIOLATION] duplicate_claim cc-task-MULTI")
    assert title == "[VIOLATION] duplicate_claim"


def test_alert_uses_obsidian_deeplink_when_task_id_present(tmp_path: Path) -> None:
    sender = _RecordingSender()
    throttle = tmp_path / "throttle.json"
    e = HygieneEvent(
        timestamp=_now(),
        check_id="duplicate_claim",
        severity="violation",
        task_id="cc-some-task",
        message="dup",
    )
    dispatch_alerts([e], throttle_path=throttle, sender=sender, now=_now())
    click = sender.calls[0]["click_url"]
    assert click is not None
    assert "obsidian://open" in click
    assert "cc-some-task" in click


def test_alert_no_click_url_without_task_id(tmp_path: Path) -> None:
    sender = _RecordingSender()
    throttle = tmp_path / "throttle.json"
    e = HygieneEvent(
        timestamp=_now(),
        check_id="duplicate_claim",
        severity="violation",
        task_id=None,
        message="dup",
    )
    dispatch_alerts([e], throttle_path=throttle, sender=sender, now=_now())
    assert sender.calls[0]["click_url"] is None
