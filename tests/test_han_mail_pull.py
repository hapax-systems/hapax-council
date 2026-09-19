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
