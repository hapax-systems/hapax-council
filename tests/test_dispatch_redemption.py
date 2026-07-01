import socket
import stat
import threading
import time
from pathlib import Path

from shared.governance.dispatch_redemption import (
    DispatchLaunchRedemptionAuthority,
    DispatchLaunchRedemptionServer,
    LaunchRedemptionContext,
    LaunchRedemptionRequest,
    dispatch_launch_redemption_socket,
    handle_redemption_bytes,
    handle_redemption_payload,
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


def test_fixed_socket_path_ignores_caller_env(monkeypatch):
    monkeypatch.setenv("HAPAX_METHODOLOGY_DISPATCH_REDEEM_SOCKET", "/tmp/fake.sock")
    assert dispatch_launch_redemption_socket() == Path("/run/hapax/coord/dispatch-redemption.sock")
    assert str(dispatch_launch_redemption_socket()) != "/tmp/fake.sock"
    assert "/run/user/" not in str(dispatch_launch_redemption_socket())


def test_mint_and_redeem_once():
    now = [1000.0]
    authority = DispatchLaunchRedemptionAuthority(now=lambda: now[0])
    grant = authority.mint(_context(), ttl_s=60)

    first = authority.redeem(_request(grant.token))
    assert first.ok is True
    assert first.reason == "redeemed"
    assert first.dispatch_message_id == "019f-test"
    assert first.route_decision_ref == "route-decision:test"

    second = authority.redeem(_request(grant.token))
    assert second.ok is False
    assert second.reason == "already_consumed"


def test_events_record_token_free_mint_and_redeem():
    now = [1000.0]
    authority = DispatchLaunchRedemptionAuthority(now=lambda: now[0])
    grant = authority.mint(_context(), ttl_s=60)
    now[0] = 1001.0

    authority.redeem(_request(grant.token))
    events = authority.events()

    assert [event.event_type for event in events] == ["grant_minted", "grant_redeemed"]
    assert [event.grant_id for event in events] == [grant.grant_id, grant.grant_id]
    assert events[0].task_id == "task-1"
    assert events[0].dispatch_message_id == "019f-test"
    assert grant.token not in repr(events)

    event_payload = redemption_event_payload(events[0])
    assert event_payload["schema"] == "hapax.dispatch_launch_redemption_event.v1"
    assert event_payload["event_type"] == "grant_minted"
    assert event_payload["grant_id"] == grant.grant_id
    assert "token" not in event_payload


def test_random_token_fails():
    authority = DispatchLaunchRedemptionAuthority(now=lambda: 1000.0)
    authority.mint(_context(), ttl_s=60)

    response = authority.redeem(_request("not-the-token"))
    assert response.ok is False
    assert response.reason == "unknown_token"
    assert authority.events()[-1].event_type == "grant_refused"
    assert authority.events()[-1].reason == "unknown_token"


def test_expired_token_fails():
    now = [1000.0]
    authority = DispatchLaunchRedemptionAuthority(now=lambda: now[0])
    grant = authority.mint(_context(), ttl_s=10)
    now[0] = 1011.0

    response = authority.redeem(_request(grant.token))
    assert response.ok is False
    assert response.reason == "expired_token"


def test_context_mismatch_fails():
    authority = DispatchLaunchRedemptionAuthority(now=lambda: 1000.0)
    grant = authority.mint(_context(), ttl_s=60)

    response = authority.redeem(_request(grant.token, _context(worktree="/tmp/other")))
    assert response.ok is False
    assert response.reason == "context_mismatch"


def test_policy_check_can_refuse_at_redemption_time():
    seen_contexts = []

    def refuse(context: LaunchRedemptionContext) -> str:
        seen_contexts.append(context)
        return "route_no_longer_launch"

    authority = DispatchLaunchRedemptionAuthority(now=lambda: 1000.0, policy_check=refuse)
    grant = authority.mint(_context(), ttl_s=60)

    response = authority.redeem(_request(grant.token))
    retry = authority.redeem(_request(grant.token))

    assert response.ok is False
    assert response.reason == "policy_refused:route_no_longer_launch"
    assert response.dispatch_message_id == "019f-test"
    assert response.route_decision_ref == "route-decision:test"
    assert retry.reason == "policy_refused:route_no_longer_launch"
    assert seen_contexts == [_context().normalized(), _context().normalized()]
    assert authority.events()[-1].event_type == "grant_refused"
    assert authority.events()[-1].reason == "policy_refused:route_no_longer_launch"


def test_context_normalization_allows_lane_case_and_resolved_worktree(tmp_path):
    worktree = tmp_path / "wt"
    worktree.mkdir()
    authority = DispatchLaunchRedemptionAuthority(now=lambda: 1000.0)
    grant = authority.mint(_context(lane="CX_Test", worktree=str(worktree)), ttl_s=60)

    response = authority.redeem(
        _request(grant.token, _context(lane="cx-test", worktree=str(worktree)))
    )
    assert response.ok is True


def test_missing_required_context_refused_at_mint():
    authority = DispatchLaunchRedemptionAuthority(now=lambda: 1000.0)
    try:
        authority.mint(_context(dispatch_message_id=""), ttl_s=60)
    except ValueError as exc:
        assert "dispatch_message_id" in str(exc)
    else:
        raise AssertionError("expected missing context to fail")


def test_handle_redemption_payload_returns_explicit_invalid_request():
    authority = DispatchLaunchRedemptionAuthority(now=lambda: 1000.0)

    response = parse_redemption_response(handle_redemption_payload(authority, {"schema": "bad"}))

    assert response.ok is False
    assert response.reason.startswith("invalid_request:")


def test_handle_redemption_bytes_returns_explicit_invalid_request():
    authority = DispatchLaunchRedemptionAuthority(now=lambda: 1000.0)

    response = parse_redemption_response(handle_redemption_bytes(authority, b"{not-json"))

    assert response.ok is False
    assert response.reason.startswith("invalid_request:")


def test_handle_redemption_payload_redeems_valid_request():
    authority = DispatchLaunchRedemptionAuthority(now=lambda: 1000.0)
    grant = authority.mint(_context(), ttl_s=60)

    response = parse_redemption_response(
        handle_redemption_payload(authority, redemption_request_payload(_request(grant.token)))
    )

    assert response.ok is True
    assert response.reason == "redeemed"


def test_socket_redemption_roundtrip(tmp_path):
    now = [1000.0]
    authority = DispatchLaunchRedemptionAuthority(now=lambda: now[0])
    grant = authority.mint(_context(), ttl_s=60)
    socket_path = tmp_path / "dispatch-redemption.sock"
    server = DispatchLaunchRedemptionServer(authority, socket_path=socket_path)

    thread = threading.Thread(target=server.serve_once)
    thread.start()

    response = _redeem_with_retry(_request(grant.token), socket_path)
    thread.join(timeout=5)

    assert response.ok is True
    assert response.reason == "redeemed"
    assert response.dispatch_message_id == "019f-test"


def test_server_sets_governor_runtime_modes(tmp_path):
    authority = DispatchLaunchRedemptionAuthority(now=lambda: 1000.0)
    socket_path = tmp_path / "coord" / "dispatch-redemption.sock"
    server = DispatchLaunchRedemptionServer(authority, socket_path=socket_path)

    thread = threading.Thread(target=server.serve_once, kwargs={"timeout_s": 5.0})
    thread.start()
    raw = _send_raw_with_retry(b"{not-json\n", socket_path)
    thread.join(timeout=5)

    assert parse_redemption_response(raw).reason.startswith("invalid_request:")
    assert stat.S_IMODE(socket_path.parent.stat().st_mode) == 0o750
    assert stat.S_IMODE(socket_path.stat().st_mode) == 0o660


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


def test_socket_malformed_request_gets_invalid_request_response(tmp_path):
    authority = DispatchLaunchRedemptionAuthority(now=lambda: 1000.0)
    socket_path = tmp_path / "dispatch-redemption.sock"
    server = DispatchLaunchRedemptionServer(authority, socket_path=socket_path)

    thread = threading.Thread(target=server.serve_once)
    thread.start()
    raw = _send_raw_with_retry(b"{not-json\n", socket_path)
    thread.join(timeout=5)
    response = parse_redemption_response(raw)

    assert response.ok is False
    assert response.reason.startswith("invalid_request:")


def test_server_refuses_to_replace_non_socket_path(tmp_path):
    authority = DispatchLaunchRedemptionAuthority(now=lambda: 1000.0)
    socket_path = tmp_path / "dispatch-redemption.sock"
    socket_path.write_text("not a socket", encoding="utf-8")
    server = DispatchLaunchRedemptionServer(authority, socket_path=socket_path)

    try:
        server.serve_once(timeout_s=0.01)
    except FileExistsError as exc:
        assert "refusing to replace non-socket path" in str(exc)
    else:
        raise AssertionError("expected non-socket path refusal")


def test_server_unlinks_stale_socket_path(tmp_path):
    authority = DispatchLaunchRedemptionAuthority(now=lambda: 1000.0)
    grant = authority.mint(_context(), ttl_s=60)
    socket_path = tmp_path / "dispatch-redemption.sock"
    stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    stale.bind(str(socket_path))
    stale.close()
    assert stat.S_ISSOCK(socket_path.stat().st_mode)
    server = DispatchLaunchRedemptionServer(authority, socket_path=socket_path)

    thread = threading.Thread(target=server.serve_once)
    thread.start()
    response = _redeem_with_retry(_request(grant.token), socket_path)
    thread.join(timeout=5)

    assert response.ok is True


def test_server_refuses_active_socket_path(tmp_path):
    authority = DispatchLaunchRedemptionAuthority(now=lambda: 1000.0)
    socket_path = tmp_path / "dispatch-redemption.sock"
    active = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    active.bind(str(socket_path))
    active.listen(1)
    server = DispatchLaunchRedemptionServer(authority, socket_path=socket_path)

    try:
        try:
            server.serve_once(timeout_s=0.01)
        except OSError as exc:
            assert "redemption socket already active" in str(exc)
        else:
            raise AssertionError("expected active socket refusal")
    finally:
        active.close()
        socket_path.unlink(missing_ok=True)


def _redeem_with_retry(request: LaunchRedemptionRequest, path, *, timeout_s: float = 5.0):
    deadline = time.monotonic() + timeout_s
    last_response = None
    while time.monotonic() < deadline:
        last_response = redeem_launch_via_socket(request, socket_path=path, timeout_s=0.2)
        if last_response.ok or not last_response.reason.startswith("socket_unavailable:"):
            return last_response
        time.sleep(0.01)
    raise AssertionError(f"redemption socket did not become ready: {path}: {last_response}")


def _send_raw_with_retry(data: bytes, path, *, timeout_s: float = 5.0):
    import json

    deadline = time.monotonic() + timeout_s
    last_error = None
    while time.monotonic() < deadline:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(0.2)
                client.connect(str(path))
                client.sendall(data)
                raw = b""
                while not raw.endswith(b"\n"):
                    chunk = client.recv(4096)
                    if not chunk:
                        break
                    raw += chunk
            return json.loads(raw.decode("utf-8"))
        except OSError as exc:
            last_error = exc
            time.sleep(0.01)
    raise AssertionError(f"redemption socket did not accept raw request: {path}: {last_error}")


def _serve_raw_response(path, payload) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(path))
        server.listen(1)
        conn, _addr = server.accept()
        with conn:
            while True:
                chunk = conn.recv(4096)
                if not chunk or b"\n" in chunk:
                    break
            conn.sendall(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
            )
