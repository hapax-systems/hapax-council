"""Self-authored foreign-data fixtures only; never use the production quarantine."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path

import httpx
import pytest

SOURCE = Path(__file__).resolve().parents[1] / "scripts/han_mail_pull.py"
spec = importlib.util.spec_from_file_location(
    "han_mail_pull_test_target", os.environ.get("HAN_MAIL_PULL_UNDER_TEST", SOURCE)
)
pull = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pull)

BODY = b"FOREIGN_BODY_SENTINEL_DO_NOT_SURFACE\r\nSubject: forged body subject\r\n"
RAW = (
    b"From: fixture@example.invalid\r\nSubject: =?utf-8?q?Self-authored_=E2=9C=93?=\r\n\r\n" + BODY
)
KEY = hashlib.sha256(RAW).hexdigest()
METADATA = {
    "schema": 1,
    "sender": "fixture@example.invalid",
    "recipient": "hrl-han@hapaxresearch.com",
    "received_at": "2026-09-19T09:00:00Z",
    "size": len(RAW),
    "auth": {"spf": "pass", "dkim": "none", "dmarc": "none", "source": "unverified_header"},
}
NOW = 1789808400.0


class FakeKV:
    def __init__(self):
        self.raw = RAW
        self.metadata = METADATA.copy()
        self.gets = []
        self.deletes = []
        self.lists = []
        self.entries = [{"name": KEY, "metadata": self.metadata}, {"name": "rate:day:fixture"}]
        self.on_delete = lambda _: None

    def list_keys(self, cursor):
        self.lists.append(cursor)
        return self.entries, ""

    def get_value(self, key):
        self.gets.append(key)
        return self.raw

    def delete_value(self, key):
        self.on_delete(key)
        self.deletes.append(key)
        # Keep the stale list/value for deliberate idempotency/re-pull coverage.


@pytest.fixture
def root(tmp_path):
    directory = tmp_path / "quarantine"
    pull.private_directory(directory)
    return directory


@pytest.fixture
def notices():
    calls = []

    def notify(*args, **kwargs):
        calls.append((args, kwargs))
        return True

    return calls, notify


@pytest.fixture
def channels(monkeypatch):
    from shared import notify

    state = {"status": 200, "desktop_result": False, "pushes": [], "desktops": []}
    real_client = httpx.Client
    monkeypatch.delenv("NTFY_BASE_URL", raising=False)

    def handler(request):
        state["pushes"].append(request)
        if "on_push" in state:
            state["on_push"]()
        if state["status"] == "timeout":
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        if state["status"] == "connection":
            raise httpx.ConnectError("synthetic outage", request=request)
        return httpx.Response(state["status"], headers={"Location": "https://example.invalid/"})

    def client(**kwargs):
        assert kwargs == {"timeout": 10, "follow_redirects": False, "trust_env": False}
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    def desktop(*args, **kwargs):
        state["desktops"].append((args, kwargs))
        if state["desktop_result"] == "exception":
            raise RuntimeError("synthetic desktop failure")
        return state["desktop_result"]

    monkeypatch.setattr(pull.httpx, "Client", client)
    monkeypatch.setattr(notify, "send_notification", desktop)
    return state


def pending_batch(root):
    """One durable retry plus two newly arrived, self-authored messages."""
    kv = FakeKV()
    kv.entries = []
    raw_by_key = {}
    for index in range(3):
        raw = RAW.replace(b"Self-authored_", f"Self-authored_{index}_".encode())
        key = hashlib.sha256(raw).hexdigest()
        metadata = {**METADATA, "size": len(raw), "sender": f"fixture{index}@example.invalid"}
        raw_by_key[key] = raw
        if index == 0:
            pull.store_item(root, key, raw, metadata)
        else:
            kv.entries.append({"name": key, "metadata": metadata})
    kv.get_value = raw_by_key.__getitem__
    return kv, sorted(raw_by_key)


def test_coalesces_one_push_per_poll(root, channels):
    kv, keys = pending_batch(root)

    def check_durable_attempts():
        for key in keys:
            item = pull.read_json(root / f"{key}.json")
            assert not item["notified"]
            assert item["notification_attempts"] == 1

    channels["on_push"] = check_durable_attempts
    assert pull.run_once(kv, root, pull.send_mail_notification, lambda: NOW) == {
        "pulled": 2,
        "notified": 3,
    }
    assert len(channels["pushes"]) == 1
    payload = json.loads(channels["pushes"][0].content)
    assert "3 pending foreign item(s)" in payload["title"]
    first = pull.read_json(root / f"{keys[0]}.json")
    assert f"Sender: {first['sender']}" in payload["message"]
    assert f"Subject: {first['subject']}" in payload["message"]
    for key in keys:
        item = pull.read_json(root / f"{key}.json")
        assert item["notified"]
        if key != keys[0]:
            assert item["sender"] not in payload["message"]
            assert item["subject"] not in payload["message"]
    assert not channels["desktops"]
    kv.entries = []
    assert pull.run_once(kv, root, pull.send_mail_notification, lambda: NOW + 300) == {
        "pulled": 0,
        "notified": 0,
    }
    assert len(channels["pushes"]) == 1


def test_body_never_in_push(root, channels):
    pull.run_once(FakeKV(), root, pull.send_mail_notification, lambda: NOW)
    assert len(channels["pushes"]) == 1
    request = channels["pushes"][0]
    assert request.method == "POST"
    assert str(request.url) == "http://100.85.131.41:8090/"
    wire = str(request.url) + str(request.headers) + request.content.decode()
    assert "FOREIGN_BODY_SENTINEL" not in wire
    assert "forged body subject" not in wire
    assert json.loads(request.content) == {
        "topic": "hapax-han-mail",
        "title": f"HAN mail — 1 pending foreign item(s) [{KEY[:12]}]",
        "message": (
            "Sender: fixture@example.invalid\nSubject: Self-authored ✓\n"
            "Auth: unverified (header observations only); SPF=pass, DKIM=none, DMARC=none\n"
            "Received: 2026-09-19T09:00:00Z"
        ),
        "priority": 4,
        "tags": ["mail"],
    }


@pytest.mark.parametrize(
    ("status", "desktop_result", "accepted"),
    [
        (200, False, True),
        (201, False, True),
        (204, False, True),
        (299, False, True),
        (199, False, False),
        (300, False, False),
        (302, False, False),
        (403, False, False),
        (429, False, False),
        (500, False, False),
        (503, True, True),
        (503, "exception", False),
        ("timeout", False, False),
        ("timeout", True, True),
        ("connection", False, False),
        ("connection", True, True),
    ],
)
def test_notified_requires_channel_acceptance(root, channels, status, desktop_result, accepted):
    channels.update(status=status, desktop_result=desktop_result)
    result = pull.run_once(FakeKV(), root, pull.send_mail_notification, lambda: NOW)
    assert result["notified"] == int(accepted)
    assert pull.read_json(root / f"{KEY}.json")["notified"] is accepted
    assert len(channels["pushes"]) == 1
    if isinstance(status, int) and 200 <= status < 300:
        assert not channels["desktops"]
    else:
        assert len(channels["desktops"]) == 1
        assert channels["desktops"][0][1] == {
            "priority": "high",
            "tags": ["mail"],
            "technical": False,
        }


def test_failed_batch_retries_once_next_poll_after_remote_deletion(root, channels):
    kv, keys = pending_batch(root)
    channels["status"] = 503
    assert pull.run_once(kv, root, pull.send_mail_notification, lambda: NOW)["notified"] == 0
    assert len(kv.deletes) == 2
    before = {key: pull.read_json(root / f"{key}.json") for key in keys}
    assert all(not item["notified"] for item in before.values())
    assert len(channels["pushes"]) == len(channels["desktops"]) == 1
    kv.entries = []
    channels["status"] = 200
    assert pull.run_once(kv, root, pull.send_mail_notification, lambda: NOW + 300) == {
        "pulled": 0,
        "notified": 3,
    }
    assert len(channels["pushes"]) == 2
    titles = [json.loads(request.content)["title"] for request in channels["pushes"]]
    assert titles[0] != titles[1]  # desktop dedup cannot settle a failed attempt
    for key in keys:
        assert pull.read_json(root / f"{key}.json") == {
            **before[key],
            "notified": True,
            "notification_attempts": 2,
        }


def test_main_uses_ntfy_and_configured_base_url(root, channels, monkeypatch, capsys):
    monkeypatch.setenv("NTFY_BASE_URL", "http://ntfy.test:8090/")
    monkeypatch.setattr(pull, "QUARANTINE", root)
    monkeypatch.setattr(pull, "CloudflareKV", lambda _namespace: FakeKV())
    assert pull.main() == 0
    assert json.loads(capsys.readouterr().out) == {"pulled": 1, "notified": 1}
    assert len(channels["pushes"]) == 1
    assert str(channels["pushes"][0].url) == "http://ntfy.test:8090/"


def test_idempotent_repull(root, notices):
    kv = FakeKV()
    calls, notify = notices
    pull.run_once(kv, root, notify, lambda: NOW)
    before = (root / f"{KEY}.json").read_bytes()
    pull.run_once(kv, root, notify, lambda: NOW + 300)
    assert kv.gets == [KEY, KEY]
    assert kv.deletes == [KEY, KEY]
    assert len(calls) == 1
    assert (root / f"{KEY}.eml").read_bytes() == RAW
    assert (root / f"{KEY}.json").read_bytes() == before
    assert len(list(root.glob("*.eml"))) == 1


def test_body_never_in_notification(root, notices):
    calls, notify = notices
    pull.run_once(FakeKV(), root, notify, lambda: NOW)
    assert len(calls) == 1
    text = json.dumps(calls)
    assert "FOREIGN_BODY_SENTINEL" not in text
    assert "forged body subject" not in text
    assert "Self-authored" in text
    assert "fixture@example.invalid" in text
    assert "unverified" in text
    assert "2026-09-19T09:00:00Z" in text
    assert calls[0][1] == {"priority": "high", "tags": ["mail"], "technical": False}
    item = json.loads((root / f"{KEY}.json").read_bytes())
    assert item["type"] == "han.mail.foreign-data"
    assert "FOREIGN_BODY_SENTINEL" not in json.dumps(item)
    assert item["subject"] == "Self-authored ✓"


def test_delete_only_after_durable_verified_local_copy(root, notices, monkeypatch):
    events = []
    real_fsync = pull.os.fsync
    real_verify = pull.verify_local

    def fsync(fd):
        events.append(("fsync", os.readlink(f"/proc/self/fd/{fd}")))
        real_fsync(fd)

    def verify(path, key, size):
        real_verify(path, key, size)
        events.append(("verified", str(path)))

    monkeypatch.setattr(pull.os, "fsync", fsync)
    monkeypatch.setattr(pull, "verify_local", verify)
    kv = FakeKV()

    def on_delete(key):
        assert (root / f"{key}.eml").read_bytes() == RAW
        item = json.loads((root / f"{key}.json").read_bytes())
        assert item["sha256"] == key
        assert ("verified", str(root / f"{key}.eml")) in events
        assert events[-2][0] == "fsync"  # delete budget file fsync
        assert events[-1] == ("fsync", str(root))  # budget rename durable too
        assert sum(1 for e in events if e == ("fsync", str(root))) >= 5

    kv.on_delete = on_delete
    pull.run_once(kv, root, notices[1], lambda: NOW)
    assert kv.deletes == [KEY]


def test_crash_between_local_write_and_delete_repulls(root, notices):
    kv = FakeKV()

    def crash(_):
        raise SystemExit("simulated process loss")

    kv.on_delete = crash
    with pytest.raises(SystemExit):
        pull.run_once(kv, root, notices[1], lambda: NOW)
    assert (root / f"{KEY}.eml").read_bytes() == RAW
    assert (root / f"{KEY}.json").exists()
    assert not kv.deletes
    assert not notices[0]
    kv.on_delete = lambda _: None
    pull.run_once(kv, root, notices[1], lambda: NOW + 300)
    assert kv.gets == [KEY, KEY]
    assert kv.deletes == [KEY]
    assert len(notices[0]) == 1


@pytest.mark.parametrize("failure", ["raw_fsync", "metadata", "hash", "size"])
def test_storage_failures_never_delete(root, notices, monkeypatch, failure):
    kv = FakeKV()
    if failure == "raw_fsync":
        real_atomic = pull.atomic_write

        def fail_raw(path, value):
            if path.suffix == ".eml":
                raise OSError("simulated disk failure")
            return real_atomic(path, value)

        monkeypatch.setattr(pull, "atomic_write", fail_raw)
    elif failure == "metadata":
        real_write = pull.write_json

        def fail_metadata(path, value):
            if path.stem == KEY:
                raise OSError("simulated metadata failure")
            return real_write(path, value)

        monkeypatch.setattr(pull, "write_json", fail_metadata)
    elif failure == "hash":
        kv.raw = b"altered self-authored bytes"
    else:
        kv.metadata["size"] += 1
    with pytest.raises((pull.IntakeError, OSError)):
        pull.run_once(kv, root, notices[1], lambda: NOW)
    assert not kv.deletes
    assert not notices[0]


def test_corrupt_existing_copy_prevents_delete(root, notices):
    (root / f"{KEY}.eml").write_bytes(b"synthetic local corruption")
    kv = FakeKV()
    with pytest.raises(pull.IntakeError):
        pull.run_once(kv, root, notices[1], lambda: NOW)
    assert not kv.deletes


def test_notification_failure_retries_after_remote_disappears(root):
    kv = FakeKV()
    calls = []

    def notify(title, *_args, **_kwargs):
        calls.append(title)
        return len(calls) > 1

    pull.run_once(kv, root, notify, lambda: NOW)
    assert not json.loads((root / f"{KEY}.json").read_bytes())["notified"]
    kv.entries = []
    pull.run_once(kv, root, notify, lambda: NOW + 300)
    assert len(calls) == 2
    assert calls[0] != calls[1]  # avoid shared.notify's prior failed-attempt dedup
    assert json.loads((root / f"{KEY}.json").read_bytes())["notified"]


def test_five_minute_spacing_persists_across_invocations(root, notices):
    kv = FakeKV()
    kv.entries = []
    for offset in (0, 1, 299, 300):
        pull.run_once(kv, root, notices[1], lambda: NOW + offset)
    assert len(kv.lists) == 2


def test_quota_reservation_survives_failure_and_limits_each_day(root):
    budget = pull.Budget(root, lambda: NOW)
    for _ in range(500):
        assert budget.reserve("deletes")
    assert not pull.Budget(root, lambda: NOW).reserve("deletes")
    assert not pull.Budget(root, lambda: NOW - 86400).reserve("deletes")
    assert pull.Budget(root, lambda: NOW + 86400).reserve("deletes")


def test_lists_daily_bound_and_no_immediate_pagination(root, notices):
    budget = pull.Budget(root, lambda: NOW)
    budget.state = {"day": "2026-09-19", "lists": 288, "last_list": NOW - 300}
    pull.write_json(budget.path, budget.state)
    assert not budget.reserve("lists")
    kv = FakeKV()
    kv.entries = []
    pull.run_once(kv, root, notices[1], lambda: NOW)
    assert not kv.lists


def test_metadata_cannot_choose_local_path(root, notices):
    kv = FakeKV()
    kv.entries = [{"name": "../../outside", "metadata": METADATA}]
    pull.run_once(kv, root, notices[1], lambda: NOW)
    assert not kv.gets


def test_headerless_body_is_not_a_subject():
    assert pull.subject_only(BODY) == "(subject unavailable)"


def test_cursor_advances_on_next_poll_only(root, notices):
    kv = FakeKV()

    def page(cursor):
        kv.lists.append(cursor)
        return [], "second-page" if not cursor else ""

    kv.list_keys = page
    pull.run_once(kv, root, notices[1], lambda: NOW)
    assert kv.lists == [""]
    pull.run_once(kv, root, notices[1], lambda: NOW + 299)
    assert kv.lists == [""]
    pull.run_once(kv, root, notices[1], lambda: NOW + 300)
    assert kv.lists == ["", "second-page"]


def test_cloudflare_transport_preserves_binary_and_refuses_oversize():
    kv = pull.CloudflareKV.__new__(pull.CloudflareKV)
    kv.base = "/accounts/fixture/storage/kv/namespaces/fixture"
    data = RAW
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, content=data)

    kv.client = httpx.Client(
        base_url="https://api.cloudflare.com/client/v4", transport=httpx.MockTransport(handler)
    )
    assert kv.get_value(KEY) == RAW
    data = b"x" * (pull.MAX_BYTES + 1)
    with pytest.raises(pull.IntakeError, match="exceeds"):
        kv.get_value(KEY)
    assert all(request.method == "GET" for request in requests)


def test_cloudflare_paid_workers_subscription_stops_before_kv(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        pull.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="self-authored-fixture-value"),
    )
    paths = []

    def request(_self, method, path):
        paths.append((method, path))
        return {"result": [{"rate_plan": {"id": "workers_paid"}}]}

    monkeypatch.setattr(pull.CloudflareKV, "_json", request)
    with pytest.raises(pull.IntakeError, match="STOP: Workers subscription"):
        pull.CloudflareKV("fixture-namespace")
    assert len(paths) == 1
    assert paths[0][1].endswith("/subscriptions")
