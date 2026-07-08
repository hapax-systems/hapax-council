import hashlib
import json
import os
import socket
import stat
import subprocess
import threading
import time
from pathlib import Path

import pytest

import shared.governance.dispatch_redemption as redemption
from shared.governance.dispatch_redemption import (
    DispatchLaunchRedemptionAuthority,
    DispatchLaunchRedemptionServer,
    LaunchMintRequest,
    LaunchPeerCredentials,
    LaunchRedemptionContext,
    LaunchRedemptionRequest,
    dispatch_launch_redemption_socket,
    handle_authority_bytes,
    mint_launch_via_socket,
    mint_request_payload,
    parse_mint_request,
    parse_mint_response,
    parse_redemption_response,
    redeem_launch_via_socket,
    redemption_event_payload,
    redemption_request_payload,
)


def _context(**overrides) -> LaunchRedemptionContext:
    values = {
        "task_id": "task-1",
        "lane": "cx-test",
        "platform": "codex",
        "mode": "headless",
        "profile": "full",
        "worktree": "/tmp/hapax-worktree",
        "purpose": "external_launch",
        "dispatch_message_id": "019f-test",
        "route_decision_ref": "route-decision:test",
        "authority_case": "CASE-CAPACITY-ROUTING-001",
        "parent_spec": "/tmp/spec.md",
    }
    values.update(overrides)
    return LaunchRedemptionContext(**values)


def _request(token: str, context: LaunchRedemptionContext | None = None) -> LaunchRedemptionRequest:
    return LaunchRedemptionRequest(
        token=token,
        context=context or _context(),
        wrapper="hapax-codex-headless",
        wrapper_pid=123,
        observed_at=1001.0,
    )


def _mint_request(
    context: LaunchRedemptionContext | None = None,
    *,
    requester_pid: int | None = None,
) -> LaunchMintRequest:
    return LaunchMintRequest(
        context=context or _context(),
        requester="hapax-methodology-dispatch",
        requester_pid=requester_pid or os.getpid(),
        ttl_s=60.0,
        observed_at=1001.0,
    )


def test_fixed_socket_path_is_not_caller_env_selected(monkeypatch):
    monkeypatch.setenv("HAPAX_METHODOLOGY_DISPATCH_REDEEM_SOCKET", "/tmp/fake.sock")

    assert dispatch_launch_redemption_socket() == Path("/run/hapax/coord/dispatch-redemption.sock")
    assert str(dispatch_launch_redemption_socket()) != "/tmp/fake.sock"
    assert "/run/user/" not in str(dispatch_launch_redemption_socket())


def test_module_boundary_disclaims_same_uid_nonforgeability():
    assert redemption.__doc__ is not None
    assert "does not claim user authentication" in redemption.__doc__
    assert "same-UID non-forgeability" in redemption.__doc__


def test_mint_redeems_once_and_records_token_free_events():
    now = [1000.0]
    authority = DispatchLaunchRedemptionAuthority(now=lambda: now[0])
    grant = authority.mint(_context(), ttl_s=60)
    now[0] = 1001.0

    first = authority.redeem(_request(grant.token))
    second = authority.redeem(_request(grant.token))

    assert first.ok is True
    assert first.reason == "redeemed"
    assert first.dispatch_message_id == "019f-test"
    assert second.ok is False
    assert second.reason == "already_consumed"
    events = authority.events()
    assert [event.event_type for event in events] == [
        "grant_minted",
        "grant_redeemed",
        "grant_refused",
    ]
    assert grant.token not in repr(events)
    payload = redemption_event_payload(events[0])
    assert payload["schema"] == "hapax.dispatch_launch_redemption_event.v1"
    assert payload["authority_case"] == "CASE-CAPACITY-ROUTING-001"
    assert payload["parent_spec"] == "/tmp/spec.md"
    assert "token" not in payload


def test_purge_expired_drops_dead_grants_without_changing_outcomes():
    now = [1000.0]
    authority = DispatchLaunchRedemptionAuthority(now=lambda: now[0])
    consumed_context = _context(dispatch_message_id="019f-consumed")
    expired_context = _context(dispatch_message_id="019f-expired")
    live_context = _context(dispatch_message_id="019f-live")
    consumed = authority.mint(consumed_context, ttl_s=60)
    expired = authority.mint(expired_context, ttl_s=10)
    live = authority.mint(live_context, ttl_s=600)
    assert authority.redeem(_request(consumed.token, consumed_context)).ok is True

    now[0] = 1030.0
    purged = authority.purge_expired()

    assert purged == 2
    # Purge maps replay/expiry to "unknown_token" — still fails closed.
    assert authority.redeem(_request(consumed.token, consumed_context)).reason == "unknown_token"
    assert authority.redeem(_request(expired.token, expired_context)).reason == "unknown_token"
    live_response = authority.redeem(_request(live.token, live_context))
    assert live_response.ok is True
    assert authority.purge_expired() == 1


def test_mint_refuses_duplicate_active_context_without_issuing_second_token():
    now = [1000.0]
    authority = DispatchLaunchRedemptionAuthority(now=lambda: now[0])
    first = authority.mint(_context(), ttl_s=60)

    with pytest.raises(redemption.LaunchMintRefusedError) as excinfo:
        authority.mint(_context(), ttl_s=60)

    assert str(excinfo.value) == "duplicate_active_context"
    events = authority.events()
    assert [event.event_type for event in events] == ["grant_minted", "mint_refused"]
    assert events[1].grant_id == first.grant_id
    assert events[1].reason == "duplicate_active_context"


def test_redeem_refuses_context_mismatch_and_policy_drift():
    authority = DispatchLaunchRedemptionAuthority(now=lambda: 1000.0)
    grant = authority.mint(_context(), ttl_s=60)

    mismatch = authority.redeem(_request(grant.token, _context(worktree="/tmp/other")))

    assert mismatch.ok is False
    assert mismatch.reason == "context_mismatch"

    drift_authority = DispatchLaunchRedemptionAuthority(
        now=lambda: 1000.0, policy_check=lambda _context: "route_no_longer_launch"
    )
    drift_grant = drift_authority.mint(_context(), ttl_s=60)

    drift = drift_authority.redeem(_request(drift_grant.token))

    assert drift.ok is False
    assert drift.reason == "policy_refused:route_no_longer_launch"
    assert drift.dispatch_message_id == "019f-test"


def test_unknown_token_refusal_preserves_presented_context():
    authority = DispatchLaunchRedemptionAuthority(now=lambda: 1000.0)

    response = authority.redeem(_request("not-a-live-token"))

    assert response.ok is False
    assert response.reason == "unknown_token"
    events = authority.events()
    assert [event.event_type for event in events] == ["grant_refused"]
    assert events[0].reason == "unknown_token"
    assert events[0].task_id == "task-1"
    assert events[0].lane == "cx-test"
    assert events[0].dispatch_message_id == "019f-test"
    assert events[0].route_decision_ref == "route-decision:test"


def test_socket_redemption_roundtrip_sets_governor_modes(tmp_path):
    authority = DispatchLaunchRedemptionAuthority(now=lambda: 1000.0)
    grant = authority.mint(_context(), ttl_s=60)
    socket_path = tmp_path / "coord" / "dispatch-redemption.sock"
    server = DispatchLaunchRedemptionServer(authority, socket_path=socket_path)

    thread = threading.Thread(target=server.serve_once, kwargs={"timeout_s": 5.0})
    thread.start()
    response = _redeem_with_retry(_request(grant.token), socket_path)
    thread.join(timeout=5)

    assert response.ok is True
    assert response.reason == "redeemed"
    assert stat.S_IMODE(socket_path.parent.stat().st_mode) == 0o750
    assert stat.S_IMODE(socket_path.stat().st_mode) == 0o660


@pytest.mark.skipif(not hasattr(socket, "SO_PEERCRED"), reason="SO_PEERCRED is Linux-only")
def test_socket_mint_and_redeem_roundtrip_records_peer_metadata(tmp_path):
    authority = DispatchLaunchRedemptionAuthority(now=lambda: 1000.0)
    socket_path = tmp_path / "coord" / "dispatch-redemption.sock"
    server = DispatchLaunchRedemptionServer(authority, socket_path=socket_path)

    mint_thread = threading.Thread(target=server.serve_once, kwargs={"timeout_s": 5.0})
    mint_thread.start()
    mint_response = _mint_with_retry(_mint_request(), socket_path)
    mint_thread.join(timeout=5)

    assert mint_response.ok is True
    assert mint_response.reason == "minted"
    assert mint_response.token

    redeem_thread = threading.Thread(target=server.serve_once, kwargs={"timeout_s": 5.0})
    redeem_thread.start()
    redeem_response = _redeem_with_retry(_request(mint_response.token), socket_path)
    redeem_thread.join(timeout=5)

    assert redeem_response.ok is True
    events = authority.events()
    assert [event.event_type for event in events] == ["grant_minted", "grant_redeemed"]
    assert events[0].peer_pid == os.getpid()
    assert events[0].peer_uid == os.getuid()
    assert events[0].requester == "hapax-methodology-dispatch"
    assert events[0].requester_pid == os.getpid()
    assert events[1].wrapper == "hapax-codex-headless"
    assert events[1].wrapper_pid == 123
    payload = redemption_event_payload(events[0])
    assert payload["peer_pid"] == os.getpid()
    assert payload["peer_uid"] == os.getuid()
    assert payload["requester"] == "hapax-methodology-dispatch"
    assert payload["requester_pid"] == os.getpid()
    assert payload["authority_case"] == "CASE-CAPACITY-ROUTING-001"
    assert payload["parent_spec"] == "/tmp/spec.md"
    assert mint_response.token not in repr(payload)


@pytest.mark.skipif(not hasattr(socket, "SO_PEERCRED"), reason="SO_PEERCRED is Linux-only")
def test_socket_mint_refuses_requester_pid_that_is_not_peer(tmp_path):
    authority = DispatchLaunchRedemptionAuthority(now=lambda: 1000.0)
    socket_path = tmp_path / "coord" / "dispatch-redemption.sock"
    server = DispatchLaunchRedemptionServer(authority, socket_path=socket_path)

    thread = threading.Thread(target=server.serve_once, kwargs={"timeout_s": 5.0})
    thread.start()
    response = _mint_with_retry(_mint_request(requester_pid=os.getpid() + 100_000), socket_path)
    thread.join(timeout=5)

    assert response.ok is False
    assert response.reason.startswith("peer_pid_mismatch:")
    events = authority.events()
    assert [event.event_type for event in events] == ["mint_refused"]
    assert events[0].reason.startswith("peer_pid_mismatch:")
    assert events[0].peer_pid == os.getpid()


def test_authority_records_wire_refusal_for_malformed_json():
    authority = DispatchLaunchRedemptionAuthority(now=lambda: 1000.0)

    response_payload = handle_authority_bytes(
        authority,
        b"{",
        peer=LaunchPeerCredentials(pid=123, uid=456, gid=789),
    )
    response = parse_redemption_response(response_payload)

    assert response.ok is False
    assert response.reason == "invalid_request:JSONDecodeError"
    events = authority.events()
    assert [event.event_type for event in events] == ["wire_refused"]
    assert events[0].reason == "invalid_request:JSONDecodeError"
    assert events[0].task_id is None
    assert events[0].peer_pid == 123
    assert events[0].peer_uid == 456
    assert events[0].peer_gid == 789


def test_authority_records_wire_refusal_for_unsupported_schema():
    authority = DispatchLaunchRedemptionAuthority(now=lambda: 1000.0)

    # A genuinely-unknown schema (NOT the read-only probe schema, which is now a
    # legitimate no-record witness — see test_probe_schema_is_read_only_*).
    response_payload = handle_authority_bytes(
        authority,
        json.dumps({"schema": "hapax.dispatch_launch_bogus.v1"}).encode() + b"\n",
    )
    response = parse_redemption_response(response_payload)

    assert response.ok is False
    assert response.reason == "invalid_request:unsupported_schema"
    events = authority.events()
    assert [event.event_type for event in events] == ["wire_refused"]
    assert events[0].reason == "invalid_request:unsupported_schema"
    assert events[0].task_id is None


def test_authority_records_wire_refusal_for_malformed_mint_payload():
    authority = DispatchLaunchRedemptionAuthority(now=lambda: 1000.0)

    response_payload = handle_authority_bytes(
        authority,
        json.dumps({"schema": "hapax.dispatch_launch_mint.v1"}).encode() + b"\n",
    )
    response = parse_mint_response(response_payload)

    assert response.ok is False
    assert response.reason == "invalid_request:ValueError"
    events = authority.events()
    assert [event.event_type for event in events] == ["wire_refused"]
    assert events[0].reason == "invalid_request:ValueError"
    assert events[0].requester is None


def test_mint_fails_closed_when_event_sink_fails():
    def failing_sink(_event):
        raise RuntimeError("ledger down")

    authority = DispatchLaunchRedemptionAuthority(
        now=lambda: 1000.0,
        event_sink=failing_sink,
    )

    response_payload = handle_authority_bytes(
        authority,
        _encoded_mint_request(_mint_request()),
        peer=LaunchPeerCredentials(pid=os.getpid(), uid=os.getuid(), gid=os.getgid()),
    )
    response = parse_mint_response(response_payload)

    assert response.ok is False
    assert response.reason == "evidence_write_failed"
    assert response.token is None
    assert authority.events() == ()


def test_mint_peer_refusal_fails_closed_when_event_sink_fails():
    def failing_sink(_event):
        raise RuntimeError("ledger down")

    authority = DispatchLaunchRedemptionAuthority(
        now=lambda: 1000.0,
        event_sink=failing_sink,
    )

    response_payload = handle_authority_bytes(
        authority,
        _encoded_mint_request(_mint_request()),
        peer=LaunchPeerCredentials(pid=os.getpid(), uid=os.getuid() + 1, gid=os.getgid()),
        require_mint_peer=True,
    )
    response = parse_mint_response(response_payload)

    assert response.ok is False
    assert response.reason == "evidence_write_failed"
    assert authority.events() == ()


def test_mint_invalid_context_records_refusal_without_issuing_token():
    authority = DispatchLaunchRedemptionAuthority(now=lambda: 1000.0)

    response_payload = handle_authority_bytes(
        authority,
        _encoded_mint_request(_mint_request(_context(task_id=" "))),
        peer=LaunchPeerCredentials(pid=os.getpid(), uid=os.getuid(), gid=os.getgid()),
    )
    response = parse_mint_response(response_payload)

    assert response.ok is False
    assert response.reason == "invalid_context:ValueError"
    assert response.token is None
    events = authority.events()
    assert [event.event_type for event in events] == ["mint_refused"]
    assert events[0].reason == "invalid_context:ValueError"
    assert events[0].task_id == ""
    assert events[0].lane == "cx-test"
    assert events[0].platform == "codex"
    assert events[0].dispatch_message_id == "019f-test"
    assert events[0].authority_case == "CASE-CAPACITY-ROUTING-001"


def test_mint_refusal_logging_falls_back_when_context_normalization_fails():
    authority = DispatchLaunchRedemptionAuthority(now=lambda: 1000.0)

    authority.record_mint_refusal(
        _context(worktree=object()),
        reason="invalid_context:TypeError",
    )

    events = authority.events()
    assert [event.event_type for event in events] == ["mint_refused"]
    assert events[0].reason == "invalid_context:TypeError"
    assert events[0].task_id is None


def test_mint_invalid_context_fails_closed_when_event_sink_fails():
    def failing_sink(_event):
        raise RuntimeError("ledger down")

    authority = DispatchLaunchRedemptionAuthority(
        now=lambda: 1000.0,
        event_sink=failing_sink,
    )

    response_payload = handle_authority_bytes(
        authority,
        _encoded_mint_request(_mint_request(_context(task_id=" "))),
    )
    response = parse_mint_response(response_payload)

    assert response.ok is False
    assert response.reason == "evidence_write_failed"
    assert response.token is None
    assert authority.events() == ()


def test_redeem_fails_closed_and_rolls_back_when_event_sink_fails_once():
    fail_redeem = True

    def flaky_sink(event):
        nonlocal fail_redeem
        if fail_redeem and event.event_type == "grant_redeemed":
            fail_redeem = False
            raise RuntimeError("ledger down")

    authority = DispatchLaunchRedemptionAuthority(
        now=lambda: 1000.0,
        event_sink=flaky_sink,
    )
    grant = authority.mint(_context(), ttl_s=60)

    failed_payload = handle_authority_bytes(
        authority,
        _encoded_redemption_request(_request(grant.token)),
    )
    failed = parse_redemption_response(failed_payload)
    retried_payload = handle_authority_bytes(
        authority,
        _encoded_redemption_request(_request(grant.token)),
    )
    retried = parse_redemption_response(retried_payload)

    assert failed.ok is False
    assert failed.reason == "evidence_write_failed"
    assert retried.ok is True
    assert retried.reason == "redeemed"
    assert [event.event_type for event in authority.events()] == ["grant_minted", "grant_redeemed"]


def test_redeem_refusal_fails_closed_when_event_sink_fails():
    def failing_refusal_sink(event):
        if event.event_type == "grant_refused":
            raise RuntimeError("ledger down")

    authority = DispatchLaunchRedemptionAuthority(
        now=lambda: 1000.0,
        event_sink=failing_refusal_sink,
    )
    grant = authority.mint(_context(), ttl_s=60)
    first = parse_redemption_response(
        handle_authority_bytes(authority, _encoded_redemption_request(_request(grant.token)))
    )
    refused = parse_redemption_response(
        handle_authority_bytes(authority, _encoded_redemption_request(_request(grant.token)))
    )

    assert first.ok is True
    assert refused.ok is False
    assert refused.reason == "evidence_write_failed"
    assert [event.event_type for event in authority.events()] == ["grant_minted", "grant_redeemed"]


def test_authority_socket_mint_fails_closed_when_peer_credentials_unavailable():
    authority = DispatchLaunchRedemptionAuthority(now=lambda: 1000.0)

    response_payload = handle_authority_bytes(
        authority,
        _encoded_mint_request(_mint_request()),
        require_mint_peer=True,
    )
    response = parse_mint_response(response_payload)

    assert response.ok is False
    assert response.reason == "peer_unavailable"
    events = authority.events()
    assert [event.event_type for event in events] == ["mint_refused"]
    assert events[0].reason == "peer_unavailable"
    assert events[0].requester == "hapax-methodology-dispatch"


def test_authority_socket_mint_refuses_peer_uid_mismatch():
    authority = DispatchLaunchRedemptionAuthority(now=lambda: 1000.0)

    response_payload = handle_authority_bytes(
        authority,
        _encoded_mint_request(_mint_request()),
        peer=LaunchPeerCredentials(pid=os.getpid(), uid=os.getuid() + 1, gid=os.getgid()),
        require_mint_peer=True,
    )
    response = parse_mint_response(response_payload)

    assert response.ok is False
    assert response.reason == f"peer_uid_mismatch:{os.getuid() + 1}"
    events = authority.events()
    assert [event.event_type for event in events] == ["mint_refused"]
    assert events[0].peer_uid == os.getuid() + 1
    assert events[0].requester_pid == os.getpid()


def test_authority_socket_mint_refuses_unwitnessed_requester_process():
    authority = DispatchLaunchRedemptionAuthority(now=lambda: 1000.0)

    response_payload = handle_authority_bytes(
        authority,
        _encoded_mint_request(_mint_request()),
        peer=LaunchPeerCredentials(pid=os.getpid(), uid=os.getuid(), gid=os.getgid()),
        require_mint_peer=True,
        require_mint_requester_process=True,
    )
    response = parse_mint_response(response_payload)

    assert response.ok is False
    assert response.reason == "peer_requester_mismatch:hapax-methodology-dispatch"
    events = authority.events()
    assert [event.event_type for event in events] == ["mint_refused"]
    assert events[0].reason == "peer_requester_mismatch:hapax-methodology-dispatch"
    assert events[0].peer_pid == os.getpid()


@pytest.mark.skipif(not Path("/usr/bin/python3").exists(), reason="requires trusted system python")
def test_authority_socket_mint_accepts_allowed_dispatcher_path_process(tmp_path, monkeypatch):
    authority = DispatchLaunchRedemptionAuthority(now=lambda: 1000.0)
    socket_path = tmp_path / "coord" / "dispatch-redemption.sock"
    server = DispatchLaunchRedemptionServer(
        authority,
        socket_path=socket_path,
        require_mint_requester_process=True,
    )
    dispatcher = tmp_path / "scripts" / "hapax-methodology-dispatch"
    dispatcher.parent.mkdir()
    worktree = tmp_path / "reins"
    worktree.mkdir()
    dispatcher.write_text(
        "import json\n"
        "import os\n"
        "import sys\n"
        "import time\n"
        "from pathlib import Path\n"
        f"sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r})\n"
        "from shared.governance.dispatch_redemption import ("
        "LaunchMintRequest, LaunchRedemptionContext, mint_launch_via_socket)\n"
        "socket_path = Path(sys.argv[1])\n"
        "worktree = Path(sys.argv[2])\n"
        "context = LaunchRedemptionContext("
        "task_id='task-1', lane='cx-test', platform='codex', mode='headless', "
        "profile='full', worktree=str(worktree), purpose='external_launch', "
        "dispatch_message_id='019f-test', route_decision_ref='route-decision:test', "
        "authority_case='CASE-CAPACITY-ROUTING-001')\n"
        "response = mint_launch_via_socket("
        "LaunchMintRequest(context=context, requester='hapax-methodology-dispatch', "
        "requester_pid=os.getpid(), ttl_s=60.0, observed_at=time.time()), "
        "socket_path=socket_path, timeout_s=2.0)\n"
        "print(json.dumps({'ok': response.ok, 'reason': response.reason}))\n"
        "raise SystemExit(0 if response.ok else 1)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "HAPAX_DISPATCH_REDEMPTION_ALLOWED_REQUESTER_PATHS",
        str(dispatcher),
    )

    thread = threading.Thread(target=server.serve_once, kwargs={"timeout_s": 5.0})
    thread.start()
    result = _run_dispatcher_mint_with_retry(dispatcher, socket_path, worktree)
    thread.join(timeout=5)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["reason"] == "minted"
    events = authority.events()
    assert [event.event_type for event in events] == ["grant_minted"]
    assert events[0].requester == "hapax-methodology-dispatch"


@pytest.mark.skipif(not Path("/usr/bin/python3").exists(), reason="requires trusted system python")
def test_authority_socket_mint_rejects_native_loader_injection(tmp_path, monkeypatch):
    authority = DispatchLaunchRedemptionAuthority(now=lambda: 1000.0)
    socket_path = tmp_path / "coord" / "dispatch-redemption.sock"
    server = DispatchLaunchRedemptionServer(
        authority,
        socket_path=socket_path,
        require_mint_requester_process=True,
    )
    dispatcher = tmp_path / "scripts" / "hapax-methodology-dispatch"
    dispatcher.parent.mkdir()
    worktree = tmp_path / "reins"
    worktree.mkdir()
    dispatcher.write_text(
        "import json\n"
        "import os\n"
        "import sys\n"
        "import time\n"
        "from pathlib import Path\n"
        f"sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r})\n"
        "from shared.governance.dispatch_redemption import ("
        "LaunchMintRequest, LaunchRedemptionContext, mint_launch_via_socket)\n"
        "socket_path = Path(sys.argv[1])\n"
        "worktree = Path(sys.argv[2])\n"
        "context = LaunchRedemptionContext("
        "task_id='task-1', lane='cx-test', platform='codex', mode='headless', "
        "profile='full', worktree=str(worktree), purpose='external_launch', "
        "dispatch_message_id='019f-test', route_decision_ref='route-decision:test', "
        "authority_case='CASE-CAPACITY-ROUTING-001')\n"
        "response = mint_launch_via_socket("
        "LaunchMintRequest(context=context, requester='hapax-methodology-dispatch', "
        "requester_pid=os.getpid(), ttl_s=60.0, observed_at=time.time()), "
        "socket_path=socket_path, timeout_s=2.0)\n"
        "print(json.dumps({'ok': response.ok, 'reason': response.reason}))\n"
        "raise SystemExit(0 if response.ok else 1)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "HAPAX_DISPATCH_REDEMPTION_ALLOWED_REQUESTER_PATHS",
        str(dispatcher),
    )

    thread = threading.Thread(target=server.serve_once, kwargs={"timeout_s": 5.0})
    thread.start()
    result = _run_dispatcher_mint_with_retry(
        dispatcher,
        socket_path,
        worktree,
        extra_env={"LD_PRELOAD": str(tmp_path / "attacker.so")},
    )
    thread.join(timeout=5)

    assert result.returncode == 1
    assert json.loads(result.stdout)["reason"] == "peer_requester_native_env:LD_PRELOAD"
    events = authority.events()
    assert [event.event_type for event in events] == ["mint_refused"]
    assert events[0].reason == "peer_requester_native_env:LD_PRELOAD"


@pytest.mark.skipif(
    not (Path("/usr/bin/python3").exists() and hasattr(socket, "SCM_CREDENTIALS")),
    reason="requires trusted system python and Unix per-message credentials",
)
def test_authority_socket_mint_rejects_forked_sender_claiming_parent_pid(tmp_path, monkeypatch):
    # This covers the enforceable kernel-credential predicate only: the process
    # that sends the mint bytes must match requester_pid. It intentionally does
    # not claim to close the same-UID parent-send-then-exec TOCTOU; that residual
    # is documented as witnessability, not non-forgeability.
    authority = DispatchLaunchRedemptionAuthority(now=lambda: 1000.0)
    socket_path = tmp_path / "coord" / "dispatch-redemption.sock"
    server = DispatchLaunchRedemptionServer(
        authority,
        socket_path=socket_path,
        require_mint_requester_process=True,
    )
    dispatcher = tmp_path / "scripts" / "hapax-methodology-dispatch"
    dispatcher.parent.mkdir()
    worktree = tmp_path / "reins"
    worktree.mkdir()
    dispatcher.write_text(
        "import json\n"
        "import os\n"
        "import socket\n"
        "import sys\n"
        "import time\n"
        "from pathlib import Path\n"
        f"sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r})\n"
        "from shared.governance.dispatch_redemption import ("
        "LaunchMintRequest, LaunchRedemptionContext, mint_request_payload)\n"
        "if len(sys.argv) > 1 and sys.argv[1] == '--trusted-sleep':\n"
        "    time.sleep(2.0)\n"
        "    raise SystemExit(0)\n"
        "socket_path = Path(sys.argv[1])\n"
        "worktree = Path(sys.argv[2])\n"
        "client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
        "client.connect(str(socket_path))\n"
        "original_pid = os.getpid()\n"
        "child = os.fork()\n"
        "if child == 0:\n"
        "    time.sleep(0.25)\n"
        "    context = LaunchRedemptionContext("
        "task_id='task-1', lane='cx-test', platform='codex', mode='headless', "
        "profile='full', worktree=str(worktree), purpose='external_launch', "
        "dispatch_message_id='019f-test', route_decision_ref='route-decision:test', "
        "authority_case='CASE-CAPACITY-ROUTING-001')\n"
        "    payload = mint_request_payload(LaunchMintRequest("
        "context=context, requester='hapax-methodology-dispatch', "
        "requester_pid=original_pid, ttl_s=60.0, observed_at=time.time()))\n"
        "    client.sendall(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode() + b'\\n')\n"
        "    print(client.recv(65536).decode(), flush=True)\n"
        "    os._exit(0)\n"
        "os.execv('/usr/bin/python3', ['/usr/bin/python3', '-I', __file__, '--trusted-sleep'])\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "HAPAX_DISPATCH_REDEMPTION_ALLOWED_REQUESTER_PATHS",
        str(dispatcher),
    )

    thread = threading.Thread(target=server.serve_once, kwargs={"timeout_s": 5.0})
    thread.start()
    proc = subprocess.Popen(
        ["/usr/bin/python3", "-I", str(dispatcher), str(socket_path), str(worktree)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    thread.join(timeout=5)
    if proc.poll() is None:
        proc.terminate()
    stdout, stderr = proc.communicate(timeout=5)

    assert stderr == ""
    payload = json.loads(stdout)
    assert payload["ok"] is False
    assert str(payload["reason"]).startswith("peer_pid_mismatch:")
    events = authority.events()
    assert [event.event_type for event in events] == ["mint_refused"]
    assert events[0].reason.startswith("peer_pid_mismatch:")
    assert events[0].peer_pid != events[0].requester_pid


@pytest.mark.skipif(not Path("/usr/bin/python3").exists(), reason="requires trusted system python")
def test_requester_path_witness_rejects_argv_shape_forgery(tmp_path):
    dispatcher = tmp_path / "scripts" / "hapax-methodology-dispatch"
    dispatcher.parent.mkdir()
    dispatcher.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    expected_paths = frozenset({dispatcher.resolve()})
    trusted_python = Path("/usr/bin/python3").resolve()

    assert (
        redemption._trusted_python_process_script_path(
            trusted_python,
            (str(trusted_python), "-I", str(dispatcher), "--task", "task-1"),
            expected_paths,
        )
        == dispatcher.resolve()
    )
    assert (
        redemption._trusted_python_process_script_path(
            trusted_python,
            (str(trusted_python), "-c", "print('forged')", str(dispatcher)),
            expected_paths,
        )
        is None
    )
    assert (
        redemption._trusted_python_process_script_path(
            trusted_python,
            (str(trusted_python), str(dispatcher), "--task", "task-1"),
            expected_paths,
        )
        is None
    )
    assert (
        redemption._trusted_python_process_script_path(
            Path("/bin/true"),
            (str(trusted_python), "-I", str(dispatcher), "--task", "task-1"),
            expected_paths,
        )
        is None
    )


def test_requester_path_witness_rejects_digest_drift(tmp_path, monkeypatch):
    dispatcher = tmp_path / "hapax-methodology-dispatch"
    dispatcher.write_text("#!/usr/bin/env python3\nprint('changed')\n", encoding="utf-8")
    observed_digest = hashlib.sha256(dispatcher.read_bytes()).hexdigest()

    monkeypatch.setenv("HAPAX_DISPATCH_REDEMPTION_ALLOWED_REQUESTER_SHA256", "0" * 64)

    refusal = redemption._requester_script_digest_refusal(dispatcher)

    assert observed_digest != "0" * 64
    assert refusal == f"peer_requester_digest_mismatch:{dispatcher}"


def test_native_mapping_witness_rejects_user_writable_code(tmp_path):
    mapped = tmp_path / "attacker.so"
    mapped.write_bytes(b"not a real shared object")
    mapped.chmod(0o775)

    refusal = redemption._mapped_executable_refusal(mapped)

    assert refusal is not None
    assert refusal.startswith("peer_requester_native_mapping_")


def test_socket_redemption_fails_closed_when_authority_absent(tmp_path):
    response = redeem_launch_via_socket(_request("anything"), socket_path=tmp_path / "missing.sock")

    assert response.ok is False
    assert response.reason.startswith("socket_unavailable:")


def test_socket_success_response_must_echo_binding_refs(tmp_path):
    socket_path = tmp_path / "dispatch-redemption.sock"
    raw_response = {
        "schema": "hapax.dispatch_launch_redeem_response.v1",
        "ok": True,
        "reason": "redeemed",
        "grant_id": "grant-1",
        "consumed_at": 1002.0,
        "dispatch_message_id": "other-message",
        "route_decision_ref": "route-decision:test",
    }
    thread = threading.Thread(target=_serve_raw_response, args=(socket_path, raw_response))
    thread.start()

    response = _redeem_with_retry(_request("anything"), socket_path)
    thread.join(timeout=5)

    assert response.ok is False
    assert response.reason == "invalid_response:dispatch_message_id_mismatch"


def _redeem_with_retry(request: LaunchRedemptionRequest, socket_path: Path):
    last = None
    for _ in range(100):
        response = redeem_launch_via_socket(request, socket_path=socket_path, timeout_s=0.2)
        if not response.reason.startswith("socket_unavailable:"):
            return response
        last = response
        time.sleep(0.01)
    assert last is not None
    return last


def _mint_with_retry(request: LaunchMintRequest, socket_path: Path):
    last = None
    for _ in range(100):
        response = mint_launch_via_socket(request, socket_path=socket_path, timeout_s=0.2)
        if not response.reason.startswith("socket_unavailable:"):
            return response
        last = response
        time.sleep(0.01)
    assert last is not None
    return last


def _run_dispatcher_mint_with_retry(
    dispatcher: Path,
    socket_path: Path,
    worktree: Path,
    *,
    extra_env: dict[str, str] | None = None,
):
    last = None
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    for _ in range(100):
        result = subprocess.run(
            ["/usr/bin/python3", "-I", str(dispatcher), str(socket_path), str(worktree)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            env=env,
        )
        if "socket_unavailable:" not in result.stdout:
            return result
        last = result
        time.sleep(0.01)
    assert last is not None
    return last


def _encoded_mint_request(request: LaunchMintRequest) -> bytes:
    return (
        json.dumps(mint_request_payload(request), sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        + b"\n"
    )


def _encoded_redemption_request(request: LaunchRedemptionRequest) -> bytes:
    return (
        json.dumps(
            redemption_request_payload(request),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def _serve_raw_response(socket_path: Path, raw_response: dict[str, object]) -> None:
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(socket_path))
        server.listen(1)
        conn, _addr = server.accept()
        with conn:
            conn.recv(65536)
            body = json.dumps(raw_response, sort_keys=True, separators=(",", ":")) + "\n"
            conn.sendall(body.encode("utf-8"))


def test_parse_bad_response_schema_raises():
    try:
        parse_redemption_response({"schema": "bad"})
    except ValueError as exc:
        assert "unsupported dispatch launch redemption response schema" in str(exc)
    else:
        raise AssertionError("bad response schema should fail")


def test_parse_responses_reject_non_bool_ok_fields():
    with pytest.raises(ValueError, match="redemption response ok must be boolean"):
        parse_redemption_response(
            {
                "schema": "hapax.dispatch_launch_redeem_response.v1",
                "ok": "false",
                "reason": "malformed",
            }
        )
    with pytest.raises(ValueError, match="mint response ok must be boolean"):
        parse_mint_response(
            {
                "schema": "hapax.dispatch_launch_mint_response.v1",
                "ok": "false",
                "reason": "malformed",
            }
        )


@pytest.mark.parametrize("bad_ttl", [float("nan"), float("inf"), float("-inf")])
def test_parse_mint_request_rejects_non_finite_ttl(bad_ttl):
    # A NaN/Inf ttl passes float() and the <= 0 check (NaN comparisons are false),
    # which would leave a grant that never expires or purges. Must fail closed.
    payload = mint_request_payload(_mint_request())
    payload["ttl_s"] = bad_ttl
    with pytest.raises(ValueError, match="ttl_s must be a finite positive number"):
        parse_mint_request(payload)


def test_parse_mint_request_rejects_non_finite_observed_at():
    payload = mint_request_payload(_mint_request())
    payload["observed_at"] = float("inf")
    with pytest.raises(ValueError, match="observed_at must be a finite number"):
        parse_mint_request(payload)


def test_probe_schema_is_read_only_and_records_no_wire_refusal():
    # A --receipt health probe must be an idempotent read-only witness: it must
    # NOT manufacture durable refusal evidence in the token-free ledger.
    authority = DispatchLaunchRedemptionAuthority(now=lambda: 1000.0)
    before = len(authority.events())
    response = handle_authority_bytes(
        authority, json.dumps({"schema": "hapax.dispatch_launch_probe.v1"}).encode("utf-8")
    )
    assert response == {
        "schema": "hapax.dispatch_launch_probe_response.v1",
        "ok": True,
        "reason": "probe_witnessed",
    }
    assert len(authority.events()) == before  # no grant_refused / wire refusal recorded

    # A genuinely unknown schema still refuses AND records (the probe is the only exemption).
    unsupported = handle_authority_bytes(
        authority, json.dumps({"schema": "hapax.bogus.v1"}).encode("utf-8")
    )
    assert unsupported["ok"] is False
    assert unsupported["reason"] == "invalid_request:unsupported_schema"
    assert len(authority.events()) > before
