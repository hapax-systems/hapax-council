"""Source-only policy fixtures. No admitted production SESSION port is constructed."""

from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import json
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field

from shared.relay_mq import ensure_schema, inspect_message, send_message
from shared.relay_mq_envelope import Envelope

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/hapax-seat-appserver-continuity"
NOW = datetime(2026, 10, 2, tzinfo=UTC)
ControlId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,255}$")]


# Faithful value fixtures from the jointly issued owner API. These are deliberately
# test-local; production imports/wiring require the independently accepted owner.
class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Identity(StrictModel):
    seat_id: ControlId = "seat"
    task_id: ControlId = "seat-task"
    claim_session_id: ControlId = "claim-session"
    claim_epoch: int = Field(default=1, gt=0, strict=True)
    runtime_id: ControlId = "runtime"
    native_version: ControlId = "fixture-version"
    thread_id: ControlId = "thread"


class Request(StrictModel):
    actor_id: ControlId
    identity: Identity
    operation: Literal["observe", "start_turn", "steer", "interrupt"]
    expected_turn_id: ControlId | None
    item_id: ControlId
    attempt_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    text: str = Field(default="", max_length=16384, repr=False, exclude=True)


class Result(StrictModel):
    op: Literal["coordinator_control"] = "coordinator_control"
    observed_at: datetime = NOW
    actor_id: ControlId
    identity: Identity
    operation: Literal["observe", "start_turn", "steer", "interrupt"]
    expected_turn_id: ControlId | None
    item_id: ControlId
    attempt_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome: Literal["attempted", "acknowledged", "refused", "uncertain"]
    reason: ControlId
    turn_id: ControlId | None = None


class Observation(StrictModel):
    identity: Identity = Identity()
    observed_at: datetime = NOW
    kind: Literal["initialized", "thread", "turn", "item", "unsupported"]
    turn_id: ControlId | None = None
    item_id: ControlId | None = None
    state: ControlId


def digest(request):
    value = request.model_dump(mode="json")
    value["text_sha256"] = hashlib.sha256(request.text.encode()).hexdigest()
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class FakePort:
    def __init__(self, clock):
        self.clock = clock
        self.calls = []
        self.outcome = "acknowledged"
        self.change = {}
        self.error = None

    def control(self, request):
        self.calls.append(request)
        if self.error:
            raise self.error
        return Result(
            **{
                **request.model_dump(mode="json"),
                "request_sha256": digest(request),
                "outcome": self.outcome,
                "reason": "fixture",
                "turn_id": "new-turn",
                "observed_at": self.clock[0],
                **self.change,
            }
        )


@pytest.fixture
def policy_module():
    loader = importlib.machinery.SourceFileLoader("seat_continuity", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    assert Path(module.__file__).resolve() == SCRIPT
    return module


@pytest.fixture
def rig(policy_module, tmp_path, monkeypatch):
    # Fixture HOME only: never replace the worker's real HOME or authentication.
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    db = tmp_path / "messages.db"
    ensure_schema(db)
    clock = [NOW]
    port = FakePort(clock)
    mq = policy_module.MQObligations(db)

    def build():
        return policy_module.SeatContinuity(
            identity=Identity(),
            actor_id="policy",
            recipients=("seat", "current-alias"),
            mq=mq,
            port=port,
            request_type=Request,
            clock=lambda: clock[0],
        )

    return policy_module, db, clock, port, build


def arrival(db, *, item="mail", recipient="seat", at=NOW):
    send_message(
        db,
        Envelope(
            message_id=item,
            sender="sender",
            message_type="advisory",
            subject="Duty",
            recipients_spec=recipient,
            payload="private duty body",
            created_at=at,
        ),
    )


def event(policy, state="completed", turn="old-turn", at=NOW, **kw):
    policy.observe(Observation(kind="turn", state=state, turn_id=turn, observed_at=at, **kw))


def record(db, item="mail", recipient="seat"):
    rows = inspect_message(db, item).recipients
    row = next(r for r in rows if r["recipient"] == recipient)
    return json.loads(row["reason"])["seat_continuity"]


def evidence(module, *, at=NOW, **kw):
    return module.UseEvidence(
        **{
            "identity": Identity(),
            "item_id": "mail",
            "attempt_id": "",
            "turn_id": "new-turn",
            "arrival_at": NOW,
            "payload_sha256": hashlib.sha256(b"private duty body").hexdigest(),
            "read_at": at,
            "disposition": "hold",
            "disposition_at": at,
            "checkpoint_ref": "sha256:" + "a" * 64,
            "checkpoint_at": at,
            **kw,
        }
    )


@pytest.mark.parametrize("order", ["pending", "after", "running", "collector-gap"])
def test_completion_arrival_orders_wake_once_and_require_use(rig, order):
    module, db, clock, port, build = rig
    p = build()
    if order in ("pending", "running", "collector-gap"):
        arrival(db)
        if order == "running":
            event(p, "inProgress")
            p.reconcile()
            assert not port.calls
    event(p)
    if order == "after":
        arrival(db)
    p.reconcile()
    p.reconcile()
    event(p)  # duplicate completion must not overwrite the acknowledged new turn
    p.reconcile()
    assert len(port.calls) == 1
    r = port.calls[0]
    assert r.operation == "start_turn" and r.expected_turn_id == "old-turn"
    assert r.identity == Identity() and r.item_id == "mail"
    assert "private duty body" not in r.text
    assert not p.healthy("mail")
    event(p, "inProgress", "new-turn")
    p.record_use(evidence(module, attempt_id=r.attempt_id))
    assert p.healthy("mail")
    assert record(db)["status"] == "complete"


@pytest.mark.parametrize("seconds, healthy", [(599, True), (600, True), (601, False)])
def test_deadline_inclusive_and_late_evidence_never_repairs_it(rig, seconds, healthy):
    module, db, clock, port, build = rig
    p = build()
    arrival(db)
    event(p)
    p.reconcile()
    event(p, "inProgress", "new-turn")
    clock[0] += timedelta(seconds=seconds)
    p.record_use(evidence(module, at=clock[0], attempt_id=port.calls[0].attempt_id))
    assert p.healthy("mail") is healthy
    if not healthy:
        assert record(db)["reason"] == "deadline_missed"


@pytest.mark.parametrize("outcome", ["attempted", "uncertain", "refused", "exception", "crash"])
def test_uncertainty_and_crash_restart_never_replays(rig, outcome):
    _, db, _, port, build = rig
    arrival(db)
    p = build()
    event(p)
    if outcome in ("exception", "crash"):
        port.error = TimeoutError() if outcome == "exception" else KeyboardInterrupt()
    else:
        port.outcome = outcome
    if outcome == "crash":
        with pytest.raises(KeyboardInterrupt):
            p.reconcile()
    else:
        p.reconcile()
    p = build()
    event(p)
    p.reconcile()
    assert len(port.calls) == 1
    assert not p.healthy("mail")
    assert record(db)["status"] == "held"


@pytest.mark.parametrize("state", ["paused", "yield", "quota_wall", "revoked", "failed"])
def test_owner_holds_retain_addressed_obligations(rig, state):
    _, db, _, port, build = rig
    arrival(db)
    p = build()
    event(p)
    event(p, state)
    p.reconcile()
    assert not port.calls
    assert record(db)["status"] == "held"


def test_mark_read_and_ack_without_read_coverage_are_insufficient(rig):
    _, db, _, port, build = rig
    arrival(db)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE recipients SET state='read'")
    p = build()
    event(p)
    p.reconcile()
    assert len(port.calls) == 1
    event(p, "inProgress", "new-turn")
    assert not p.healthy("mail")


@pytest.mark.parametrize(
    "change",
    [
        {"actor_id": "wrong"},
        {"identity": Identity(claim_epoch=2)},
        {"operation": "steer"},
        {"item_id": "different"},
        {"attempt_id": "b" * 64},
        {"expected_turn_id": "stale"},
        {"request_sha256": "b" * 64},
        {"turn_id": "old-turn"},
        {"turn_id": None},
        {"observed_at": NOW - timedelta(seconds=1)},
        {"observed_at": NOW + timedelta(seconds=1)},
    ],
)
def test_uncorrelated_or_non_new_ack_is_held(rig, change):
    _, db, _, port, build = rig
    arrival(db)
    port.change = change
    p = build()
    event(p)
    p.reconcile()
    assert record(db)["status"] == "held"
    assert not p.healthy("mail")


@pytest.mark.parametrize(
    "field,value",
    [
        ("seat_id", "predecessor"),
        ("task_id", "wrong-task"),
        ("claim_session_id", "wrong-sid"),
        ("claim_epoch", 2),
        ("thread_id", "wrong-thread"),
        ("runtime_id", "wrong-runtime"),
        ("native_version", "wrong-version"),
    ],
)
def test_owner_identity_mismatch_cannot_free_a_turn(rig, field, value):
    _, db, _, port, build = rig
    arrival(db)
    p = build()
    event(p, identity=Identity(**{field: value}))
    p.reconcile()
    assert not port.calls
    assert record(db)["reason"] == "identity_changed"


@pytest.mark.parametrize(
    "change",
    [
        {"identity": Identity(claim_epoch=2)},
        {"attempt_id": "c" * 64},
        {"turn_id": "old-turn"},
        {"arrival_at": NOW + timedelta(seconds=1)},
        {"payload_sha256": "c" * 64},
        {"read_at": None},
        {"disposition": None},
        {"disposition_at": None},
        {"checkpoint_ref": None},
        {"checkpoint_at": None},
        {"checkpoint_ref": "self-report"},
        {"disposition": "done"},
        {"read_at": NOW - timedelta(seconds=1)},
        {"checkpoint_at": NOW + timedelta(seconds=1)},
    ],
)
def test_incomplete_wrong_or_time_inconsistent_use_is_not_success(rig, change):
    module, db, _, port, build = rig
    arrival(db)
    p = build()
    event(p)
    p.reconcile()
    event(p, "inProgress", "new-turn")
    args = {"attempt_id": port.calls[0].attempt_id, **change}
    p.record_use(evidence(module, **args))
    assert record(db)["status"] == "held"
    assert not p.healthy("mail")


def test_new_turn_observation_is_required_even_with_full_use(rig):
    module, db, _, port, build = rig
    arrival(db)
    p = build()
    event(p)
    p.reconcile()
    p.record_use(evidence(module, attempt_id=port.calls[0].attempt_id))
    assert record(db)["reason"] == "use_binding_mismatch"


def test_wrong_recipient_and_processed_items_are_untouched(rig):
    _, db, _, port, build = rig
    arrival(db, recipient="predecessor")
    arrival(db, item="done")
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE recipients SET state='processed' WHERE message_id='done'")
    before = [inspect_message(db, item).recipients for item in ("mail", "done")]
    p = build()
    event(p)
    p.reconcile()
    assert not port.calls
    assert [inspect_message(db, item).recipients for item in ("mail", "done")] == before


def test_current_alias_and_restart_after_success_do_not_duplicate(rig):
    module, db, _, port, build = rig
    arrival(db, recipient="current-alias")
    p = build()
    event(p)
    p.reconcile()
    event(p, "inProgress", "new-turn")
    p.record_use(evidence(module, attempt_id=port.calls[0].attempt_id))
    p = build()
    event(p)
    p.reconcile()
    assert p.healthy("mail")
    assert len(port.calls) == 1


def test_two_collectors_and_two_arrivals_cannot_use_one_completion_twice(rig):
    _, db, _, port, build = rig
    arrival(db)
    arrival(db, item="mail2")
    p, q = build(), build()
    event(p)
    event(q)
    p.reconcile()
    q.reconcile()
    assert len(port.calls) == 1
    assert record(db, "mail2")["status"] == "pending"


def test_arrival_after_empty_completion_tick_is_reconciled(rig):
    _, db, _, port, build = rig
    p = build()
    event(p)
    p.reconcile()
    assert not port.calls
    arrival(db)
    p.reconcile()
    assert len(port.calls) == 1


def test_missing_port_unsupported_observation_and_late_ack_are_held(rig):
    _, db, clock, port, build = rig
    arrival(db)
    p = build()
    p.port = None
    event(p)
    p.reconcile()
    assert record(db)["reason"] == "unsupported_seam"
    assert not port.calls
    # A different item must retain unsupported owner observations too.
    arrival(db, item="unsupported")
    p.port = port
    p.observe(Observation(kind="unsupported", state="native_notification"))
    p.reconcile()
    assert record(db, "unsupported")["reason"] == "unsupported_observation"
    arrival(db, item="late")
    event(p)
    original = port.control

    def slow(request):
        clock[0] += timedelta(seconds=601)
        return original(request)

    port.control = slow
    p.reconcile()
    assert record(db, "late")["reason"] == "deadline_missed"


def test_duplicate_start_and_use_do_not_move_observed_effect_time(rig):
    module, db, clock, port, build = rig
    arrival(db)
    p = build()
    event(p)
    p.reconcile()
    event(p, "inProgress", "new-turn")
    clock[0] += timedelta(seconds=1)
    event(p, "inProgress", "new-turn", at=clock[0])
    proof = evidence(module, attempt_id=port.calls[0].attempt_id)
    p.record_use(proof)
    assert p.healthy("mail")
    before = record(db)
    p.record_use(proof)
    assert record(db) == before


def test_owner_revocation_after_ack_cannot_be_called_healthy(rig):
    module, db, _, port, build = rig
    arrival(db)
    p = build()
    event(p)
    p.reconcile()
    event(p, "inProgress", "new-turn")
    event(p, "revoked", "new-turn")
    p.record_use(evidence(module, attempt_id=port.calls[0].attempt_id))
    assert not p.healthy("mail")


def test_store_failure_before_intent_prevents_control(rig):
    _, db, _, port, build = rig
    arrival(db)
    p = build()
    event(p)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TRIGGER fail_write BEFORE UPDATE ON recipients "
            "BEGIN SELECT RAISE(ABORT, 'fixture disk failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        p.reconcile()
    assert not port.calls


def test_lost_final_receipt_retains_durable_intent(rig):
    _, db, _, port, build = rig
    arrival(db)
    p = build()
    event(p)
    original = port.control

    def lose_final(request):
        with sqlite3.connect(db) as conn:
            conn.execute(
                "CREATE TRIGGER fail_write BEFORE UPDATE ON recipients "
                "BEGIN SELECT RAISE(ABORT, 'fixture disk failure'); END"
            )
        return original(request)

    port.control = lose_final
    with pytest.raises(sqlite3.IntegrityError):
        p.reconcile()
    assert record(db)["status"] == "attempted"
    with sqlite3.connect(db) as conn:
        conn.execute("DROP TRIGGER fail_write")
    q = build()
    event(q)
    q.reconcile()
    assert len(port.calls) == 1
    assert record(db)["reason"] == "restart_unresolved"


def test_mq_ack_cannot_erase_reservation_or_cause_restart_replay(rig):
    from shared.relay_mq import ack_message

    _, db, _, port, build = rig
    arrival(db)
    p = build()
    event(p)
    p.reconcile()
    assert ack_message(db, "mail", "seat", "read")
    assert inspect_message(db, "mail").recipients[0]["reason"] is None
    q = build()
    event(q)
    q.reconcile()
    assert len(port.calls) == 1
    assert record(db)["status"] == "held"


def test_multiple_current_aliases_are_one_obligation(rig):
    module, db, _, port, build = rig
    arrival(db, recipient="seat,current-alias")
    p = build()
    event(p)
    p.reconcile()
    event(p, "inProgress", "new-turn")
    p.record_use(evidence(module, attempt_id=port.calls[0].attempt_id))
    assert p.healthy("mail")
    event(p, "completed", "new-turn")
    p.reconcile()
    assert len(port.calls) == 1


def test_source_template_is_inert_and_policy_has_no_native_or_dispatch_path():
    import ast

    tree = ast.parse(SCRIPT.read_text())
    imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert "shared.codex_session_transport" not in imports
    assert "shared.execution_admission" not in imports
    calls = [
        n.func.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    ]
    assert not set(calls) & {"CodexSessionTransport", "NativePeer", "AuthenticatedSessionActor"}
    unit = (ROOT / "systemd/units/hapax-seat-appserver-continuity.service").read_text()
    assert "RefuseManualStart=yes" in unit and "[Install]" not in unit
    assert "Restart=no" in unit
