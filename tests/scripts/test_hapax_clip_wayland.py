"""Native desktop-session and IPC peer authority, with real kernel peer and disconnect checks."""

import os
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import hapax_clip_wayland as wayland
from hapax_clip import ClipError


def mock_sessions(monkeypatch, sessions):

    def run(argv, **kwargs):
        if argv[1] == "list-sessions":
            return "".join(f"{name} {os.getuid()} operator seat0\n" for name in sessions).encode()
        p = dict(
            User=str(os.getuid()),
            Type="wayland",
            Active="yes",
            LockedHint="no",
            Remote="no",
            Class="user",
            Desktop="KDE",
        )
        p.update(sessions[argv[2]])
        return "".join((f"{k}={v}\n" for k, v in p.items())).encode()

    monkeypatch.setattr(wayland, "bounded_run", run)


def test_one_real_session(monkeypatch):
    mock_sessions(monkeypatch, {"4": {}})
    assert wayland.active_session(os.getuid()) == "4"


@pytest.mark.parametrize(
    "sessions",
    [
        {},
        {"4": {}, "5": {}},
        {"4": {"LockedHint": "yes"}},
        {"4": {"LockedHint": ""}},
        {"4": {"User": "other"}},
        {"4": {"Active": "no"}},
        {"4": {"Type": "tty"}},
        {"4": {"Remote": "yes"}},
        {"4": {"Class": "greeter"}},
    ],
)
def test_ambiguous_locked_unknown_or_foreign_session_refused(monkeypatch, sessions):
    mock_sessions(monkeypatch, sessions)
    with pytest.raises(ClipError):
        wayland.active_session(os.getuid())


def test_native_peer_uid_not_a_claim_in_request():
    a, b = socket.socketpair()
    with a, b:
        assert wayland.peer_is_owner(a, os.getuid())
        assert not wayland.peer_is_owner(a, os.getuid() + 1)


def test_stale_endpoint_session_refused(monkeypatch):
    endpoint = wayland.Endpoint("id", "4", None)
    monkeypatch.setattr(wayland, "verify_wayland_environment", lambda uid: None)
    monkeypatch.setattr(wayland, "active_session", lambda uid: "5")
    with pytest.raises(ClipError):
        endpoint.current()


def test_no_guessed_wayland_socket(monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    with pytest.raises(ClipError):
        wayland.verify_wayland_environment(os.getuid())
    monkeypatch.setenv("WAYLAND_DISPLAY", "../../another-socket")
    with pytest.raises(ClipError):
        wayland.verify_wayland_environment(os.getuid())


def native_case(monkeypatch):
    import base64
    import types
    import uuid

    from hapax_clip import digest

    data = b"own literal\r\nprobe"
    calls = []
    provider = types.SimpleNamespace(owner=types.SimpleNamespace(poll=lambda: None))

    def write(value, deadline):
        calls.append(value)
        return value

    provider.write = write
    endpoint = wayland.Endpoint(str(uuid.uuid4()), "4", provider)
    monkeypatch.setattr(endpoint, "current", lambda: None)
    q = dict(
        v=1,
        id=str(uuid.uuid4()),
        op="set",
        endpoint=endpoint.endpoint,
        session="4",
        epoch=endpoint.epoch,
        bytes=len(data),
        sha256=digest(data),
        data=base64.b64encode(data).decode(),
    )
    return endpoint, q, calls


def test_native_ack_requires_observed_bytes_and_live_owner(monkeypatch):
    endpoint, q, calls = native_case(monkeypatch)
    assert endpoint.handle(q)["history_excluded"] is True and len(calls) == 1
    endpoint.provider.owner.poll = lambda: 0
    with pytest.raises(ClipError):
        endpoint.handle(q)


@pytest.mark.parametrize(
    "change", [{"session": "5"}, {"epoch": "00000000-0000-0000-0000-000000000000"}]
)
def test_stale_request_has_no_native_effect(monkeypatch, change):
    endpoint, q, calls = native_case(monkeypatch)
    with pytest.raises(ClipError):
        endpoint.handle(q | change)
    assert calls == []


def test_disconnected_producer_has_no_native_effect(monkeypatch):
    endpoint, q, calls = native_case(monkeypatch)
    with pytest.raises(ClipError):
        endpoint.handle(q, lambda: False)
    assert calls == []


def test_expired_producer_has_no_native_effect(monkeypatch):
    endpoint, q, calls = native_case(monkeypatch)
    ticks = iter([0, 6])
    monkeypatch.setattr(wayland.time, "monotonic", lambda: next(ticks))
    with pytest.raises(ClipError):
        endpoint.handle(q)
    assert calls == []


def test_real_peer_connection_check_is_nonblocking_and_preserves_timeout():
    a, b = socket.socketpair()
    with a, b:
        a.settimeout(8)
        assert wayland.peer_connected(a) and a.gettimeout() == 8
        b.send(b"unexpected")
        assert not wayland.peer_connected(a) and a.recv(10) == b"unexpected"
        b.close()
        assert not wayland.peer_connected(a)


def test_other_desktop_has_no_claimed_kde_history_exclusion(monkeypatch):
    mock_sessions(monkeypatch, {"4": {"Desktop": "GNOME"}})
    with pytest.raises(ClipError):
        wayland.active_session(os.getuid())


def test_session_inspection_has_one_total_deadline(monkeypatch):
    mock_sessions(monkeypatch, {"4": {}})
    ticks = iter([0, 0, 4])
    monkeypatch.setattr(wayland.time, "monotonic", lambda: next(ticks))
    with pytest.raises(ClipError):
        wayland.active_session(os.getuid())


@pytest.mark.parametrize("filesystem", [b"ext4\n", b"btrfs\n", b"", b"tmpfs\next4\n"])
def test_disk_or_ambiguous_staging_refused(monkeypatch, tmp_path, filesystem):
    monkeypatch.setattr(wayland, "bounded_run", lambda *args, **kwargs: filesystem)
    with pytest.raises(ClipError):
        wayland.NativeProvider(tmp_path / "runtime")


def native_provider(monkeypatch, tmp_path, hint=b"secret"):
    observed = {}

    class Child:
        exited = False

        def poll(self):
            return 0 if self.exited else None

        def terminate(self):
            self.exited = True

        def kill(self):
            self.exited = True

        def wait(self, timeout):
            return 0

    child = Child()

    def launch(argv, **kwargs):
        assert argv == [
            "wl-copy",
            "--foreground",
            "--sensitive",
            "--type",
            "text/plain;charset=utf-8",
        ]
        assert (
            kwargs["stdout"] == wayland.subprocess.DEVNULL
            and kwargs["stderr"] == wayland.subprocess.DEVNULL
        )
        assert not Path(kwargs["env"]["TMPDIR"]).stat().st_mode & 0o077
        observed["data"] = os.read(kwargs["stdin"], 1048577)
        observed["argv"] = argv
        return child

    def run(argv, **kwargs):
        if argv[0] == "findmnt":
            return b"tmpfs\n"
        if argv[0] == "wl-copy":
            return b"--sensitive"
        if argv[-1] == "text/plain;charset=utf-8":
            return observed["data"]
        return hint

    monkeypatch.setattr(wayland.subprocess, "Popen", launch)
    monkeypatch.setattr(wayland, "bounded_run", run)
    provider = wayland.NativeProvider(tmp_path / "runtime")
    return provider, child, observed


def test_provider_uses_memory_fd_and_private_ram_staging_without_payload_argv(
    monkeypatch, tmp_path
):
    import time

    provider, child, observed = native_provider(monkeypatch, tmp_path)
    data = b"literal quotes ' ; \r\n" * 1000
    assert provider.write(data, time.monotonic() + 2) == data
    assert observed["data"] == data and data.decode() not in str(observed["argv"])
    assert list(provider.directory.iterdir()) == [] and child.poll() is None
    provider.stop()
    assert child.exited


def test_failed_sensitive_hint_stops_only_owned_provider_and_removes_ram_staging(
    monkeypatch, tmp_path
):
    import time

    provider, child, _ = native_provider(monkeypatch, tmp_path, b"public")
    with pytest.raises(ClipError):
        provider.write(b"own probe", time.monotonic() + 0.03)
    assert child.exited and list(provider.directory.iterdir()) == []
