from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "verify-weblog-producer-deploy.py"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("verify_weblog_producer_deploy", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def deploy_module(monkeypatch: pytest.MonkeyPatch) -> Any:
    module = _load_module()
    monkeypatch.setattr(module, "check_service_running", lambda: True)
    monkeypatch.setattr(module, "publish_test_post", lambda: True)
    monkeypatch.setattr(
        module,
        "find_weblog_event",
        lambda after_ts: {
            "event_id": "rvpe:omg_weblog:deploy-verify-weblog-producer",
            "event_type": "omg.weblog",
            "state_kind": "weblog.entry",
            "salience": 1.0,
        },
    )
    monkeypatch.setattr(
        module,
        "wait_for_event",
        lambda after_ts: {
            "event_id": "rvpe:omg_weblog:deploy-verify-weblog-producer",
            "event_type": "omg.weblog",
            "state_kind": "weblog.entry",
            "salience": 1.0,
        },
    )
    monkeypatch.setattr(
        module,
        "check_social_fanout",
        lambda event_id: {"mastodon": True, "bluesky": True},
    )
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    return module


def test_default_is_check_only_and_does_not_mutate(
    deploy_module: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    published = False
    deleted = False
    checked_service = False

    def _publish_test_post() -> bool:
        nonlocal published
        published = True
        return True

    def _delete_test_post() -> bool:
        nonlocal deleted
        deleted = True
        return True

    def _check_service_running() -> bool:
        nonlocal checked_service
        checked_service = True
        return True

    monkeypatch.setattr(deploy_module, "publish_test_post", _publish_test_post)
    monkeypatch.setattr(deploy_module, "delete_test_post", _delete_test_post)
    monkeypatch.setattr(deploy_module, "check_service_running", _check_service_running)

    assert deploy_module.main([]) == 0
    assert published is False
    assert deleted is False
    assert checked_service is False


def test_live_egress_cleanup_runs_by_default(
    deploy_module: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    deleted = False

    def _delete_test_post() -> bool:
        nonlocal deleted
        deleted = True
        return True

    monkeypatch.setattr(deploy_module, "delete_test_post", _delete_test_post)

    assert deploy_module.main(["--live-egress"]) == 0
    assert deleted is True


def test_no_cleanup_opt_out_leaves_test_post(
    deploy_module: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    deleted = False

    def _delete_test_post() -> bool:
        nonlocal deleted
        deleted = True
        return True

    monkeypatch.setattr(deploy_module, "delete_test_post", _delete_test_post)

    assert deploy_module.main(["--live-egress", "--no-cleanup"]) == 0
    assert deleted is False


def test_leave_live_post_override_leaves_test_post(
    deploy_module: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    deleted = False

    def _delete_test_post() -> bool:
        nonlocal deleted
        deleted = True
        return True

    monkeypatch.setattr(deploy_module, "delete_test_post", _delete_test_post)

    assert deploy_module.main(["--live-egress", "--leave-live-post"]) == 0
    assert deleted is False


def test_find_weblog_event_rejects_stale_live_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_module()
    events = tmp_path / "events.jsonl"
    events.write_text(
        "\n".join(
            json.dumps(event)
            for event in (
                {
                    "event_id": "rvpe:omg_weblog:deploy-verify-weblog-producer:old",
                    "event_type": "omg.weblog",
                    "provenance": {"generated_at": "2026-05-12T11:59:59Z"},
                },
                {
                    "event_id": "rvpe:omg_weblog:deploy-verify-weblog-producer:new",
                    "event_type": "omg.weblog",
                    "provenance": {"generated_at": "2026-05-12T12:00:01Z"},
                },
            )
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "PUBLIC_EVENT_PATH", events)
    after_ts = datetime(2026, 5, 12, 12, 0, 0, tzinfo=UTC).timestamp()

    found = module.find_weblog_event(after_ts)

    assert found is not None
    assert found["event_id"] == "rvpe:omg_weblog:deploy-verify-weblog-producer:new"


def test_check_social_fanout_reads_schema_v2_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_module()
    mastodon = tmp_path / "mastodon.json"
    bluesky = tmp_path / "bluesky.json"
    mastodon.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "event_ids": ["event-1"],
                "posts": [
                    {
                        "event_id": "event-1",
                        "event_public_url": "https://hapax.weblog.lol/post",
                        "public_url": "https://mastodon.test/@hapax/1",
                        "result": "ok",
                        "text": "Hapax weblog. https://hapax.weblog.lol/post",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    bluesky.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "event_ids": [],
                "posts": [
                    {
                        "event_id": "event-1",
                        "event_public_url": "https://hapax.weblog.lol/post",
                        "result": "ok",
                        "text": "Hapax weblog. https://hapax.weblog.lol/post",
                        "uri": "at://did:plc:example/app.bsky.feed.post/1",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "MASTODON_IDS_PATH", mastodon)
    monkeypatch.setattr(module, "BLUESKY_IDS_PATH", bluesky)

    assert module.check_social_fanout("event-1") == {
        "mastodon": True,
        "bluesky": True,
    }


def test_check_social_fanout_schema_v2_event_id_without_receipt_is_not_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_module()
    mastodon = tmp_path / "mastodon.json"
    bluesky = tmp_path / "bluesky.json"
    mastodon.write_text(
        '{"schema_version": 2, "event_ids": ["event-1"], "posts": []}',
        encoding="utf-8",
    )
    bluesky.write_text(
        '{"schema_version": 2, "event_ids": ["event-1"], "posts": [{"event_id": "event-1"}]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "MASTODON_IDS_PATH", mastodon)
    monkeypatch.setattr(module, "BLUESKY_IDS_PATH", bluesky)

    assert module.check_social_fanout("event-1") == {
        "mastodon": False,
        "bluesky": False,
    }


def test_check_only_fails_when_social_fanout_missing(
    deploy_module: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(deploy_module, "check_social_fanout", lambda event_id: {})

    assert deploy_module.main([]) == 1


def test_live_egress_fails_when_social_fanout_missing_and_cleans_up(
    deploy_module: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    deleted = False

    def _delete_test_post() -> bool:
        nonlocal deleted
        deleted = True
        return True

    monkeypatch.setattr(deploy_module, "check_social_fanout", lambda event_id: {})
    monkeypatch.setattr(deploy_module, "delete_test_post", _delete_test_post)

    assert deploy_module.main(["--live-egress"]) == 1
    assert deleted is True
