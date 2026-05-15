"""End-to-end deployment tests for the weblog publish public event producer.

Verifies:
- systemd unit is active and healthy
- state file tracks seen RSS items
- /dev/shm/hapax-public-events/events.jsonl contains valid RVPE rows
- producer run_once emits correct ResearchVehiclePublicEvent against live RSS
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from agents.weblog_publish_public_event_producer import (
    WeblogPublishPublicEventProducer,
)

LIVE_EVENTS_PATH = Path("/dev/shm/hapax-public-events/events.jsonl")
STATE_PATH = Path.home() / ".cache/hapax/weblog-publish-public-event-state.json"
UNIT_NAME = "hapax-weblog-publish-public-event-producer.service"

REQUIRED_EVENT_FIELDS = {
    "schema_version",
    "event_id",
    "event_type",
    "occurred_at",
    "source",
    "salience",
    "state_kind",
    "rights_class",
    "privacy_class",
    "provenance",
    "surface_policy",
}


def _systemctl_is_active() -> bool:
    result = subprocess.run(
        ["systemctl", "--user", "is-active", UNIT_NAME],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    return result.stdout.strip() == "active"


requires_live_deployment = pytest.mark.skipif(
    not _systemctl_is_active(),
    reason=f"{UNIT_NAME} is not active; live deployment verification requires the host unit",
)

requires_live_rss = pytest.mark.skipif(
    os.environ.get("HAPAX_WEBLOG_PUBLISH_LIVE_RSS_TESTS") != "1",
    reason="live weblog RSS verification requires HAPAX_WEBLOG_PUBLISH_LIVE_RSS_TESTS=1",
)


@requires_live_deployment
class TestSystemdUnit:
    def test_unit_is_active(self) -> None:
        assert _systemctl_is_active(), f"{UNIT_NAME} is not active"

    def test_unit_has_correct_type(self) -> None:
        result = subprocess.run(
            ["systemctl", "--user", "show", UNIT_NAME, "--property=Type"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        assert "Type=simple" in result.stdout


@requires_live_deployment
class TestStateFile:
    def test_state_file_exists(self) -> None:
        assert STATE_PATH.exists(), f"State file missing: {STATE_PATH}"

    def test_state_file_has_seen_items(self) -> None:
        payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        assert "seen_item_ids" in payload
        assert isinstance(payload["seen_item_ids"], list)
        assert len(payload["seen_item_ids"]) > 0

    def test_state_file_has_schema_version(self) -> None:
        payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        assert payload.get("schema_version") == 1


@requires_live_deployment
class TestLiveEventsJSONL:
    def test_events_file_exists(self) -> None:
        assert LIVE_EVENTS_PATH.exists(), f"Events JSONL missing: {LIVE_EVENTS_PATH}"

    def test_events_are_valid_json(self) -> None:
        for line in LIVE_EVENTS_PATH.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            assert isinstance(event, dict)

    def test_events_have_required_fields(self) -> None:
        lines = LIVE_EVENTS_PATH.read_text(encoding="utf-8").splitlines()
        assert len(lines) > 0, "No events written yet"
        for line in lines:
            if not line.strip():
                continue
            event = json.loads(line)
            missing = REQUIRED_EVENT_FIELDS - set(event.keys())
            assert not missing, f"Event {event.get('event_id', '?')} missing fields: {missing}"

    def test_events_have_omg_weblog_type(self) -> None:
        found_weblog_event = False
        for line in LIVE_EVENTS_PATH.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if event["event_type"] == "omg.weblog":
                found_weblog_event = True
        assert found_weblog_event, "No omg.weblog events found on the shared public-events bus"

    def test_events_have_valid_surface_policy(self) -> None:
        for line in LIVE_EVENTS_PATH.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            sp = event["surface_policy"]
            assert isinstance(sp["allowed_surfaces"], list)
            assert isinstance(sp["denied_surfaces"], list)
            assert sp["requires_provenance"] is True


@requires_live_rss
class TestProducerRunOnce:
    def test_run_once_against_live_rss(self, tmp_path: Path) -> None:
        public = tmp_path / "events.jsonl"
        state = tmp_path / "state.json"
        producer = WeblogPublishPublicEventProducer(
            public_event_path=public,
            state_path=state,
            emit_existing_on_first_run=True,
        )
        written = producer.run_once()
        assert written > 0, "Expected at least one event from live RSS"
        events = [json.loads(line) for line in public.read_text(encoding="utf-8").splitlines()]
        assert all(e["event_type"] == "omg.weblog" for e in events)
        assert all(e["schema_version"] == 1 for e in events)
        assert all(
            e["source"]["producer"] == "agents.weblog_publish_public_event_producer" for e in events
        )

    def test_run_once_events_have_public_urls(self, tmp_path: Path) -> None:
        public = tmp_path / "events.jsonl"
        state = tmp_path / "state.json"
        producer = WeblogPublishPublicEventProducer(
            public_event_path=public,
            state_path=state,
            emit_existing_on_first_run=True,
        )
        producer.run_once()
        events = [json.loads(line) for line in public.read_text(encoding="utf-8").splitlines()]
        with_urls = [e for e in events if e.get("public_url")]
        assert len(with_urls) > 0, "Expected at least one event with a public_url"
        for event in with_urls:
            assert event["public_url"].startswith("https://hapax.weblog.lol/")

    @pytest.mark.parametrize("surface", ["mastodon", "bluesky", "arena", "archive"])
    def test_events_allow_social_fanout_surfaces(self, tmp_path: Path, surface: str) -> None:
        public = tmp_path / "events.jsonl"
        state = tmp_path / "state.json"
        producer = WeblogPublishPublicEventProducer(
            public_event_path=public,
            state_path=state,
            emit_existing_on_first_run=True,
        )
        producer.run_once()
        events = [json.loads(line) for line in public.read_text(encoding="utf-8").splitlines()]
        with_urls = [e for e in events if e.get("public_url")]
        assert any(surface in e["surface_policy"]["allowed_surfaces"] for e in with_urls), (
            f"{surface} not in allowed_surfaces for any event with a public_url"
        )
