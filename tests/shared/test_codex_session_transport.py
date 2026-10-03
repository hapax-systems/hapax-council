"""Fake native peer only: no provider, native launcher or incumbent connection."""

import json
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256

import pytest

from shared.codex_session_transport import CodexSessionTransport
from shared.platform_session_contract import CoordinatorControlRequest, CoordinatorIdentity


class Peer:
    def __init__(self):
        self.writes = []
        self.incoming = deque()
        self.alive = True
        self.lose_reply = False
        self.transform = lambda message: message
        self.turn_number = 0

    def write(self, data, timeout):
        msg = json.loads(data)
        self.writes.append(msg)
        method = msg["method"]
        if method == "initialized":
            return
        if self.lose_reply and method.startswith("turn/"):
            return
        if method == "turn/start":
            self.turn_number += 1
        result = {
            "initialize": {
                "userAgent": "reins/1",
                "platformFamily": "unix",
                "platformOs": "linux",
                "codexHome": "/private/fake",
            },
            "thread/read": {"thread": {"id": "thread-1", "status": {"type": "idle"}, "turns": []}},
            "turn/start": {"turn": {"id": f"turn-{self.turn_number}", "status": "inProgress"}},
            "turn/steer": {"turnId": f"turn-{self.turn_number}"},
            "turn/interrupt": {},
        }[method]
        self.incoming.append(
            json.dumps(self.transform({"id": msg["id"], "result": result})).encode() + b"\n"
        )

    def read(self, limit, timeout):
        if not self.incoming:
            raise TimeoutError
        return self.incoming.popleft()


@pytest.fixture
def identity():
    return CoordinatorIdentity(
        seat_id="seat",
        task_id="task-20261002",
        claim_session_id="claim-1",
        claim_epoch=1,
        runtime_id="runtime-1",
        native_version="0.158.0",
        thread_id="thread-1",
    )


def request(identity, **changes):
    return CoordinatorControlRequest(
        **dict(
            actor_id="principal",
            identity=identity,
            operation="start_turn",
            expected_turn_id=None,
            item_id="message-1",
            attempt_id=sha256(b"attempt-1").hexdigest(),
            text="private body",
        )
        | changes
    )


def control(transport, identity, **changes):
    return transport._control(request(identity, **changes), before_write=lambda: None)


def ready(transport, identity):
    result = control(transport, identity, operation="observe", text="")
    assert result.outcome == "acknowledged"
    transport.observations()


def test_wrong_binding_and_expected_turn_never_write(tmp_path, identity):
    peer = Peer()
    with CodexSessionTransport(
        identity, peer, tmp_path / "session-send-receipts.jsonl"
    ) as transport:
        bad = identity.model_copy(update={"thread_id": "wrong"})
        result = control(transport, bad)
        assert result.outcome == "refused"
        assert peer.writes == []
        ready(transport, identity)
        before = list(peer.writes)
        result = control(transport, identity, expected_turn_id="stale")
        assert result.outcome == "refused"
        assert peer.writes == before


def test_uncertain_send_is_durable_and_never_replayed_on_restart(tmp_path, identity):
    path = tmp_path / "session-send-receipts.jsonl"
    peer = Peer()
    peer.lose_reply = True
    with CodexSessionTransport(identity, peer, path) as transport:
        ready(transport, identity)
        result = control(transport, identity)
        assert result.outcome == "uncertain"
    again = Peer()
    with CodexSessionTransport(identity, again, path) as transport:
        assert control(transport, identity).outcome == "uncertain"
        assert again.writes == []
    assert "private body" not in path.read_text()


def notice(peer, method, **params):
    peer.incoming.append(
        json.dumps({"method": method, "params": {"threadId": "thread-1", **params}}).encode()
        + b"\n"
    )


def test_correlated_turn_control_and_completion(tmp_path, identity):
    peer = Peer()
    with CodexSessionTransport(identity, peer, tmp_path / "bus") as transport:
        assert control(transport, identity).reason == "observe_required"
        assert peer.writes == []
        ready(transport, identity)
        assert [x["method"] for x in peer.writes] == ["initialize", "initialized", "thread/read"]
        start = control(transport, identity)
        assert (start.outcome, start.turn_id) == ("acknowledged", "turn-1")
        for operation, text in (("steer", "direction"), ("interrupt", "")):
            result = control(
                transport,
                identity,
                operation=operation,
                text=text,
                expected_turn_id="turn-1",
                item_id=operation,
                attempt_id=sha256(operation.encode()).hexdigest(),
            )
            assert result.outcome == "acknowledged"
        assert peer.writes[-2]["params"]["expectedTurnId"] == "turn-1"
        assert peer.writes[-1]["params"]["turnId"] == "turn-1"
        notice(peer, "turn/completed", turn={"id": "turn-1", "status": "interrupted"})
        transport.poll()
        assert transport.observations()[-1].state == "interrupted"


def test_single_writer_and_concurrent_duplicate_requests(tmp_path, identity):
    path = tmp_path / "bus"
    peer = Peer()
    with CodexSessionTransport(identity, peer, path) as transport:
        with pytest.raises(BlockingIOError):
            CodexSessionTransport(identity, Peer(), path)
        ready(transport, identity)
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(
                workers.map(
                    lambda _: control(transport, identity),
                    range(2),
                )
            )
        assert results[0] == results[1]
        assert sum(w["method"] == "turn/start" for w in peer.writes) == 1
        changed = request(identity, text="changed body")
        assert transport._control(changed, before_write=lambda: None).reason == "attempt_reused"
    assert peer.alive
    again = Peer()
    with CodexSessionTransport(identity, again, path) as restarted:
        assert control(restarted, identity) == results[0]
        assert again.writes == []


@pytest.mark.parametrize("bad", ["correlation", "thread", "version", "turn_reply"])
def test_mismatched_native_evidence_never_acknowledges(tmp_path, identity, bad):
    peer = Peer()
    if bad == "version":
        identity = identity.model_copy(update={"native_version": "unknown"})
    with CodexSessionTransport(identity, peer, tmp_path / "bus") as transport:
        if bad == "thread":

            def transform(msg):
                if "thread" in msg["result"]:
                    msg["result"]["thread"]["id"] = "other-thread"
                return msg

            peer.transform = transform
        elif bad == "correlation":
            peer.transform = lambda msg: dict(msg, id="unknown-reply")
        if bad != "turn_reply":
            result = control(transport, identity, operation="observe", text="")
            assert result.outcome == "refused"
            assert not any(w["method"].startswith("turn/") for w in peer.writes)
        else:
            ready(transport, identity)
            control(transport, identity)
            peer.transform = lambda msg: dict(msg, result={"turnId": "wrong-turn"})
            result = control(
                transport,
                identity,
                operation="steer",
                expected_turn_id="turn-1",
                item_id="steer",
                attempt_id="b" * 64,
            )
            assert result.outcome == "uncertain"


def test_write_ahead_failure_prevents_send_and_final_failure_survives_restart(
    tmp_path, identity, monkeypatch
):
    path = tmp_path / "bus"
    peer = Peer()
    with CodexSessionTransport(identity, peer, path) as transport:
        ready(transport, identity)
        before = list(peer.writes)
        real_record = transport._record

        def fail(receipt, before_write):
            raise OSError("fixture disk full")

        monkeypatch.setattr(transport, "_record", fail)
        with pytest.raises(OSError):
            control(transport, identity)
        assert peer.writes == before

        def fail_final(receipt, before_write):
            if receipt.outcome != "attempted":
                raise OSError("fixture disk full")
            return real_record(receipt, before_write)

        monkeypatch.setattr(transport, "_record", fail_final)
        with pytest.raises(OSError):
            control(transport, identity)
    with CodexSessionTransport(identity, Peer(), path) as restarted:
        assert control(restarted, identity).outcome == "uncertain"


def test_unsupported_item_is_typed_and_payload_not_retained(tmp_path, identity):
    peer = Peer()
    with CodexSessionTransport(identity, peer, tmp_path / "bus") as transport:
        ready(transport, identity)
        control(transport, identity)
        notice(
            peer,
            "item/started",
            turnId="turn-1",
            item={"id": "item-2", "type": "futureSecretTool", "body": "secret"},
        )
        transport.poll()
        event = transport.observations()[0]
        assert (event.kind, event.item_id) == ("unsupported", "item-2")
        assert "secret" not in event.model_dump_json()


@pytest.mark.parametrize("fault", ["frame", "queue", "history", "payload", "disconnect"])
def test_bounds_and_disconnect_fail_closed(tmp_path, identity, monkeypatch, fault):
    import shared.codex_session_transport as module

    peer = Peer()
    path = tmp_path / "bus"
    if fault == "history":
        path.write_bytes(b"x" * (module.MAX_HISTORY + 1))
        with CodexSessionTransport(identity, peer, path) as transport:
            with pytest.raises(ValueError, match="bound"):
                control(transport, identity)
        assert peer.writes == []
        return
    with CodexSessionTransport(identity, peer, path) as transport:
        ready(transport, identity)
        if fault == "payload":
            monkeypatch.setattr(module, "MAX_FRAME", 128)
            before = list(peer.writes)
            assert control(transport, identity, text="x" * 256).outcome == "uncertain"
            assert peer.writes == before
        elif fault == "disconnect":
            peer.incoming.append(b"")
            assert control(transport, identity).outcome == "uncertain"
        else:
            if fault == "frame":
                peer.incoming.append(b"x" * (module.MAX_FRAME + 1))
            else:
                monkeypatch.setattr(module, "MAX_OBSERVATIONS", 1)
                notice(peer, "future/event")
                transport.poll()
                notice(peer, "future/event")
            with pytest.raises(ValueError):
                transport.poll()
            assert control(transport, identity).outcome == "refused"


@pytest.mark.parametrize("arrival", ["pending_at_completion", "immediately_after_completion"])
def test_fake_mq_consumer_completion_arrival_races(tmp_path, identity, arrival):
    """Consumer fixture only: no production MQ reader or disposition policy."""
    peer = Peer()
    with CodexSessionTransport(identity, peer, tmp_path / "bus") as transport:
        ready(transport, identity)
        control(transport, identity)
        pending = []
        completed = False
        results = []

        def drain():
            if completed and pending:
                item = pending.pop(0)
                results.append(
                    control(
                        transport,
                        identity,
                        item_id=item,
                        expected_turn_id="turn-1",
                        attempt_id=sha256(item.encode()).hexdigest(),
                    )
                )

        if arrival == "pending_at_completion":
            pending.append("addressed-2")
            drain()
        notice(peer, "turn/completed", turn={"id": "turn-1", "status": "completed"})
        transport.poll()
        completed = any(
            e.kind == "turn" and e.state == "completed" for e in transport.observations()
        )
        if arrival == "immediately_after_completion":
            pending.append("addressed-2")
        drain()
        pending.append("addressed-2")  # duplicated arrival/cursor restart
        drain()
        assert results[0] == results[1]
        assert sum(w["method"] == "turn/start" for w in peer.writes) == 2


@pytest.mark.parametrize("boundary", ["entry", "replay", "attempted", "acknowledged"])
def test_expired_admission_cannot_read_replay_or_write_receipt(
    tmp_path, identity, monkeypatch, boundary
):
    peer = Peer()
    path = tmp_path / "bus"
    with CodexSessionTransport(identity, peer, path) as transport:
        ready(transport, identity)
        if boundary == "replay":
            control(transport, identity)
        before = path.read_bytes() if path.exists() else None
        writes = list(peer.writes)

        expired = boundary in {"entry", "replay"}
        real_result = transport._result

        def prepare_result(*args):
            nonlocal expired
            result = real_result(*args)
            expired |= result.outcome == boundary
            return result

        monkeypatch.setattr(transport, "_result", prepare_result)

        def check():
            if expired:
                raise PermissionError("fixture admission expired")

        with pytest.raises(PermissionError, match="expired"):
            transport._control(request(identity), before_write=check)
        if boundary == "acknowledged":
            assert [json.loads(line)["outcome"] for line in path.read_bytes().splitlines()] == [
                "attempted"
            ]
            assert peer.writes[len(writes) :][0]["method"] == "turn/start"
        else:
            assert (path.read_bytes() if path.exists() else None) == before
            assert peer.writes == writes


def test_restart_reads_history_only_after_current_admission(tmp_path, identity):
    path = tmp_path / "bus"
    path.write_bytes(b"not a complete receipt")
    peer = Peer()
    with CodexSessionTransport(identity, peer, path) as transport:

        def deny():
            raise PermissionError("no current SESSION permission")

        with pytest.raises(PermissionError):
            transport._control(request(identity), before_write=deny)
    assert peer.writes == [] and path.read_bytes() == b"not a complete receipt"


def test_actual_failed_receipt_fsync_latches_writer(tmp_path, identity, monkeypatch):
    import shared.codex_session_transport as module

    peer = Peer()
    with CodexSessionTransport(identity, peer, tmp_path / "bus") as transport:
        ready(transport, identity)
        before = list(peer.writes)
        original = module.os.fsync

        def fail(fd):
            raise OSError("fixture fsync failed")

        monkeypatch.setattr(module.os, "fsync", fail)
        with pytest.raises(OSError):
            control(transport, identity)
        monkeypatch.setattr(module.os, "fsync", original)
        assert (
            control(transport, identity, item_id="other", attempt_id="e" * 64).outcome == "refused"
        )
        assert peer.writes == before
