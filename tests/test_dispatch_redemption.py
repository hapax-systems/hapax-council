import json
import os
import socket
import stat
import threading
import time
from pathlib import Path

import pytest

from shared.governance.dispatch_redemption import (
    DispatchLaunchRedemptionAuthority,
    DispatchLaunchRedemptionServer,
    LaunchMintRequest,
    LaunchRedemptionContext,
    LaunchRedemptionRequest,
    dispatch_launch_redemption_socket,
    mint_launch_via_socket,
    parse_redemption_response,
    redeem_launch_via_socket,
    redemption_event_payload,
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
    assert "token" not in payload


def test_purge_expired_drops_dead_grants_without_changing_outcomes():
    now = [1000.0]
    authority = DispatchLaunchRedemptionAuthority(now=lambda: now[0])
    consumed = authority.mint(_context(), ttl_s=60)
    expired = authority.mint(_context(), ttl_s=10)
    live = authority.mint(_context(), ttl_s=600)
    assert authority.redeem(_request(consumed.token)).ok is True

    now[0] = 1030.0
    purged = authority.purge_expired()

    assert purged == 2
    # Purge maps replay/expiry to "unknown_token" — still fails closed.
    assert authority.redeem(_request(consumed.token)).reason == "unknown_token"
    assert authority.redeem(_request(expired.token)).reason == "unknown_token"
    live_response = authority.redeem(_request(live.token))
    assert live_response.ok is True
    assert authority.purge_expired() == 1


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
    payload = redemption_event_payload(events[0])
    assert payload["peer_pid"] == os.getpid()
    assert payload["peer_uid"] == os.getuid()
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
