"""Single managed writer for native Codex control, without process lifecycle ownership.

The owner supplies a connected NativePeer and the existing SESSION receipt bus.
This library owns no process or credentials. Only the SESSION adapter calls
_control; it is not an isolation boundary against code in the writer process.
Protocol basis: 0.158.0 schemas; https://learn.chatgpt.com/docs/app-server.
"""

from __future__ import annotations

import fcntl
import json
import os
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from shared.jsonl_append import lock_path_for
from shared.platform_session_contract import (
    CoordinatorControlRequest,
    CoordinatorControlResult,
    CoordinatorIdentity,
    CoordinatorObservation,
    request_digest,
)

MAX_FRAME = 65536
MAX_HISTORY = 8 * 1024 * 1024
MAX_OBSERVATIONS = 128


class NativeRefused(ValueError):
    """A correlated native error reply; private error text is not retained."""


class NativePeer(Protocol):
    def write(self, data: bytes, timeout: float) -> None: ...

    def read(self, limit: int, timeout: float) -> bytes: ...


class CodexSessionTransport:
    """Bounded serialized control engine; only a correlated reply acknowledges.

    Reuse the existing SESSION receipt bus. An attempted record is fsynced before
    writing native bytes; restart preserves unresolved attempts as uncertain. No
    automatic reconciliation or replay is implemented. One lifetime lock per bus
    excludes competing managed writers on the binding's local filesystem. Runtime
    commissioning must separately prove no incumbent outside that binding exists.
    """

    def __init__(self, identity: CoordinatorIdentity, peer: NativePeer, receipts_path: Path):
        self.identity, self.peer, self.path = identity, peer, Path(receipts_path)
        self._mutex = threading.RLock()
        self._buffer = b""
        self._events: deque[CoordinatorObservation] = deque()
        self._history: dict[str, CoordinatorControlResult] = {}
        self._history_loaded = False
        self._ready = False
        self._closed = False
        self._broken = False
        self._turn: str | None = None
        self._active = False
        self._serial = 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._writer = os.open(
            str(self.path) + ".coordinator-writer.lock", os.O_CREAT | os.O_RDWR, 0o600
        )
        try:
            fcntl.flock(self._writer, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            os.close(self._writer)
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self) -> None:
        """Writer owner shutdown only. Borrowed runtime descriptors remain alive."""
        with self._mutex:
            if not self._closed:
                self._closed = True
                os.close(self._writer)

    def _load_history(self) -> None:
        if not self.path.exists():
            return
        with self.path.open("rb") as stream:
            raw = stream.read(MAX_HISTORY + 1)
        if len(raw) > MAX_HISTORY or (raw and not raw.endswith(b"\n")):
            raise ValueError("receipt history incomplete or over bound; reconcile before reconnect")
        for line in raw.splitlines():
            record = json.loads(line)
            if record.get("op") != "coordinator_control":
                continue
            receipt = CoordinatorControlResult.model_validate(record)
            if receipt.identity.seat_id == self.identity.seat_id:
                self._history[receipt.attempt_id] = receipt

    def _record(self, receipt: CoordinatorControlResult, before_write) -> CoordinatorControlResult:
        try:
            return self._append_record(receipt, before_write)
        except OSError:
            # A partial write/fsync failure may have spent the attempt. The same
            # writer must not append a different request past damaged evidence.
            self._broken = True
            raise

    def _append_record(
        self, receipt: CoordinatorControlResult, before_write
    ) -> CoordinatorControlResult:
        # Same SESSION bus and lock convention, with full-write/fsync required at
        # this non-idempotent boundary. The advisory append helper does not fsync.
        data = (receipt.model_dump_json() + "\n").encode()
        with lock_path_for(self.path).open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            before_write()  # Revalidate after waiting for other SESSION bus appenders.
            with self.path.open("ab", buffering=0) as stream:
                if stream.tell() + len(data) > MAX_HISTORY:
                    raise OSError("receipt history bound; reconcile before sending")
                if stream.write(data) != len(data):
                    raise OSError("short receipt write")
                os.fsync(stream.fileno())
            parent = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
        self._history[receipt.attempt_id] = receipt
        return receipt

    def _result(self, request, outcome, reason, turn_id=None):
        return CoordinatorControlResult(
            **request.model_dump(mode="json"),
            request_sha256=request_digest(request),
            outcome=outcome,
            reason=reason,
            turn_id=turn_id,
        )

    def _event(self, kind, state, turn_id=None, item_id=None):
        if len(self._events) >= MAX_OBSERVATIONS:
            raise ValueError("observation queue full")
        self._events.append(
            CoordinatorObservation(
                identity=self.identity,
                kind=kind,
                state=state,
                turn_id=turn_id,
                item_id=item_id,
            )
        )

    def observations(self) -> tuple[CoordinatorObservation, ...]:
        with self._mutex:
            events = tuple(self._events)
            self._events.clear()
            return events

    def _send(self, message, before_write, timeout):
        data = (json.dumps(message, separators=(",", ":")) + "\n").encode()
        if len(data) > MAX_FRAME:
            raise ValueError("native payload too large")
        before_write()  # actual current admission at every native write
        self.peer.write(data, timeout)

    def _receive(self, timeout):
        deadline = time.monotonic() + timeout
        while b"\n" not in self._buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            data = self.peer.read(MAX_FRAME + 1 - len(self._buffer), remaining)
            if not data:
                raise EOFError
            self._buffer += data
            if len(self._buffer) > MAX_FRAME:
                raise ValueError("native frame too large")
        line, self._buffer = self._buffer.split(b"\n", 1)
        message = json.loads(line)
        if not isinstance(message, dict):
            raise ValueError("native object required")
        return message

    def _notification(self, message):
        params = message.get("params", {})
        method = message.get("method")
        if params.get("threadId") != self.identity.thread_id:
            raise ValueError("uncorrelated native observation")
        if "id" in message:
            self._event("unsupported", "server_request")
            self._broken = True  # never auto-approve or silently drop a native decision
        elif method in ("turn/started", "turn/completed"):
            turn = params["turn"]
            turn_id = turn["id"]
            allowed = (
                {"inProgress"}
                if method == "turn/started"
                else {"completed", "failed", "interrupted"}
            )
            if turn["status"] not in allowed:
                raise ValueError("invalid native turn state")
            if method == "turn/completed" and turn_id != self._turn:
                raise ValueError("wrong completed turn")
            if method == "turn/started" and self._active and turn_id != self._turn:
                raise ValueError("competing native turn")
            self._event("turn", turn["status"], turn_id)
            self._turn, self._active = turn_id, method == "turn/started"
        elif method in ("item/started", "item/completed"):
            if params.get("turnId") != self._turn:
                raise ValueError("wrong item turn")
            item = params["item"]
            known = item.get("type") in {
                "userMessage",
                "agentMessage",
                "commandExecution",
                "fileChange",
                "mcpToolCall",
                "reasoning",
            }
            self._event(
                "item" if known else "unsupported",
                "started" if method.endswith("started") else "completed",
                self._turn,
                item["id"],
            )
        else:
            self._event("unsupported", "native_notification", self._turn)

    def poll(self, timeout: float = 0.01) -> None:
        """The managed writer calls this after completion, independently of clients."""
        with self._mutex:
            if self._closed or self._broken:
                raise ValueError("writer unavailable; reconcile connection")
            try:
                self._notification(self._receive(timeout))
            except TimeoutError:
                return
            except Exception:
                self._broken = True
                raise

    def _rpc(self, method, params, before_write, timeout):
        self._serial += 1
        correlation = f"control-{self._serial}"
        self._send({"id": correlation, "method": method, "params": params}, before_write, timeout)
        deadline = time.monotonic() + timeout
        while True:
            message = self._receive(max(0, deadline - time.monotonic()))
            if "method" in message:
                self._notification(message)
                continue
            if message.get("id") != correlation:
                raise ValueError("wrong reply correlation")
            if "error" in message:
                raise NativeRefused("native refused request")
            return message["result"]

    def _initialize(self, before_write, timeout):
        if self.identity.native_version != "0.158.0":
            raise ValueError("unsupported schema binding")
        result = self._rpc(
            "initialize", {"clientInfo": {"name": "reins", "version": "1"}}, before_write, timeout
        )
        # userAgent identifies the client upstream; it is NOT native version
        # evidence. native_version is the commissioning owner's binary binding.
        if not all(
            isinstance(result.get(key), str) and result[key]
            for key in ("userAgent", "platformFamily", "platformOs", "codexHome")
        ):
            raise ValueError("malformed initialization")
        self._event("initialized", "observed")
        self._send({"method": "initialized", "params": {}}, before_write, timeout)
        result = self._rpc(
            "thread/read",
            {"threadId": self.identity.thread_id, "includeTurns": True},
            before_write,
            timeout,
        )
        thread = result["thread"]
        if thread["id"] != self.identity.thread_id or thread["status"]["type"] not in {
            "idle",
            "active",
        }:
            raise ValueError("managed thread unavailable")
        turns = thread["turns"]
        self._turn = turns[-1]["id"] if turns else None
        self._active = thread["status"]["type"] == "active"
        if self._active and not self._turn:
            raise ValueError("active turn missing")
        self._event("thread", thread["status"]["type"], self._turn)
        self._ready = True

    def _control(
        self,
        request: CoordinatorControlRequest,
        *,
        before_write: Callable[[], None],
        timeout: float = 2.0,
    ) -> CoordinatorControlResult:
        """Internal adapter port. No caller boolean or worker LAUNCH decision."""
        with self._mutex:
            before_write()  # Admission can expire while waiting for the managed writer.
            if request.identity != self.identity:
                return self._result(request, "refused", "identity_mismatch")
            if not self._history_loaded:
                self._load_history()
                self._history_loaded = True
            # The adapter checks authority before calling, including for replay reads.
            previous = self._history.get(request.attempt_id)
            if previous:
                if previous.request_sha256 != request_digest(request):
                    return self._result(request, "refused", "attempt_reused")
                return (
                    previous.model_copy(
                        update={"outcome": "uncertain", "reason": "reconcile_required"}
                    )
                    if previous.outcome == "attempted"
                    else previous
                )
            for receipt in self._history.values():
                if receipt.identity.thread_id == request.identity.thread_id:
                    if receipt.outcome in {"attempted", "uncertain"}:
                        return self._result(request, "refused", "reconcile_required")
                    if receipt.item_id == request.item_id:
                        return self._result(request, "refused", "item_already_attempted")
            if self._closed or self._broken:
                return self._result(request, "refused", "connection_unavailable")
            if (request.operation in {"interrupt", "observe"}) != (request.text == ""):
                return self._result(request, "refused", "unsupported_input")
            if request.operation == "observe":
                try:
                    if not self._ready:
                        self._initialize(before_write, timeout)
                    return self._result(request, "acknowledged", "native_observation", self._turn)
                except Exception:
                    self._broken = True
                    return self._result(request, "refused", "initialization_unavailable")
            if not self._ready:
                return self._result(request, "refused", "observe_required")
            if request.expected_turn_id != self._turn or self._active != (
                request.operation != "start_turn"
            ):
                return self._result(request, "refused", "stale_turn")
            params = {"threadId": self.identity.thread_id}
            if request.operation == "interrupt":
                params["turnId"] = self._turn
            else:
                params["input"] = [{"type": "text", "text": request.text}]
                params["clientUserMessageId"] = request.item_id
                if request.operation == "steer":
                    params["expectedTurnId"] = self._turn
            method = {
                "start_turn": "turn/start",
                "steer": "turn/steer",
                "interrupt": "turn/interrupt",
            }[request.operation]
            attempted = self._result(request, "attempted", "native_write_pending")
            self._record(attempted, before_write)  # failure denies any native control write
            try:
                result = self._rpc(method, params, before_write, timeout)
                if request.operation == "start_turn":
                    turn_id = result["turn"]["id"]
                    if turn_id == request.expected_turn_id:
                        raise ValueError("start returned predecessor turn")
                    if self._turn != request.expected_turn_id and self._turn != turn_id:
                        raise ValueError("turn reply mismatch")
                    if self._turn != turn_id:
                        self._turn, self._active = turn_id, True
                elif request.operation == "steer" and result.get("turnId") != self._turn:
                    raise ValueError("steer reply mismatch")
                receipt = self._result(request, "acknowledged", "native_reply", self._turn)
            except NativeRefused:
                receipt = self._result(request, "refused", "native_refused", self._turn)
            except Exception:
                self._broken = True
                receipt = self._result(request, "uncertain", "reconcile_required", self._turn)
            return self._record(receipt, before_write)
