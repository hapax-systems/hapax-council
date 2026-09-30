#!/usr/bin/env python3
"""Per-user Wayland clipboard endpoint; no TCP, root daemon, history or payload log."""

from __future__ import annotations

import ctypes
import os
import shutil
import socket
import stat
import struct
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from hapax_clip import (
    MAX_REPLY,
    MAX_REQUEST,
    MAX_TEXT,
    ClipError,
    bounded_run,
    decode_json,
    digest,
    encode_json,
    private_directory,
    read_frame,
    read_private,
    send_frame,
    socket_path,
    valid_uuid,
    validate_request,
)

PASSWORD_HINT = "x-kde-passwordManagerHint"  # pragma: allowlist secret -- public native MIME format


def memory_fd() -> int:
    # Some managed Python builds omit os.memfd_create despite a capable kernel.
    if hasattr(os, "memfd_create"):
        return os.memfd_create("hapax-clip-input", 1)
    try:
        create = ctypes.CDLL(None, use_errno=True).memfd_create
    except AttributeError:
        raise ClipError("The platform lacks anonymous RAM descriptors; no disk fallback.") from None
    create.argtypes = [ctypes.c_char_p, ctypes.c_uint]
    create.restype = ctypes.c_int
    fd = create(b"hapax-clip-input", 1)  # MFD_CLOEXEC
    if fd < 0:
        raise ClipError("The kernel refused an anonymous RAM descriptor.")
    return fd


def active_session(uid: int) -> str:
    """Resolve one actual unlocked local Wayland session, never a first socket."""
    deadline = time.monotonic() + 3

    def remaining():
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise ClipError("Desktop session inspection expired.")
        return seconds

    listing = bounded_run(["loginctl", "list-sessions", "--no-legend"], timeout=remaining())
    found = []
    for line in listing.decode("utf-8", "strict").splitlines():
        session = line.split()[0]
        raw = bounded_run(
            [
                "loginctl",
                "show-session",
                session,
                "-p",
                "User",
                "-p",
                "Type",
                "-p",
                "Active",
                "-p",
                "LockedHint",
                "-p",
                "Remote",
                "-p",
                "Class",
                "-p",
                "Desktop",
            ],
            timeout=remaining(),
        )
        properties = dict(line.split("=", 1) for line in raw.decode().splitlines() if "=" in line)
        if properties.get("User") == str(uid) and properties.get("Type") == "wayland":
            # An active but locked session is not silently replaced by another route.
            if properties.get("Active") == "yes":
                if (
                    properties.get("LockedHint") != "no"
                    or properties.get("Remote") != "no"
                    or properties.get("Class") != "user"
                    or properties.get("Desktop") != "KDE"
                ):
                    raise ClipError("The graphical desktop is locked or unavailable.")
                found.append(session)
    if len(found) != 1:
        raise ClipError("No unique active unlocked Wayland desktop exists.")
    return found[0]


def verify_wayland_environment(uid: int) -> None:
    runtime = Path(f"/run/user/{uid}")
    if os.environ.get("XDG_RUNTIME_DIR") != str(runtime):
        raise ClipError("Runtime directory is not bound to the desktop user.")
    name = os.environ.get("WAYLAND_DISPLAY", "")
    if not name or Path(name).name != name or name in (".", ".."):
        raise ClipError("An explicit graphical Wayland display binding is required.")
    info = runtime.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or info.st_mode & 0o077:
        raise ClipError("The desktop runtime directory is not private.")
    info = (runtime / name).lstat()
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != uid:
        raise ClipError("The compositor socket is not owned by the desktop user.")


def peer_is_owner(stream: socket.socket, uid: int) -> bool:
    _pid, peer_uid, _gid = struct.unpack(
        "3i", stream.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
    )
    return peer_uid == uid


def require_tmpfs(path: Path, timeout: float = 1) -> None:
    if (
        bounded_run(
            ["findmnt", "-n", "-o", "FSTYPE", "--target", str(path)], timeout=timeout
        ).strip()
        != b"tmpfs"
    ):
        raise ClipError("Clipboard staging requires verified private tmpfs; no disk fallback.")


class NativeProvider:
    """Own one foreground data-control provider, with only unlinked RAM staging."""

    def __init__(self, directory: Path):
        private_directory(directory)
        require_tmpfs(directory)
        if b"--sensitive" not in bounded_run(["wl-copy", "--help"], timeout=2):
            raise ClipError("The native provider lacks sensitive clipboard support.")
        self.directory = directory
        self.owner = None

    def stop(self) -> None:
        if self.owner is not None:
            if self.owner.poll() is None:
                self.owner.terminate()
            try:
                self.owner.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.owner.kill()
                self.owner.wait(timeout=1)
            self.owner = None

    def write(self, data: bytes, deadline: float) -> bytes:
        def remaining():
            seconds = deadline - time.monotonic()
            if seconds <= 0:
                raise ClipError("Pending desktop write expired.")
            return min(seconds, 2)

        require_tmpfs(self.directory, remaining())
        staging = Path(tempfile.mkdtemp(prefix="provider-", dir=self.directory))
        old_owner = self.owner
        child = None
        fd = -1
        try:
            fd = memory_fd()
            at = 0
            while at < len(data):
                at += os.write(fd, data[at:])
            os.lseek(fd, 0, os.SEEK_SET)
            remaining()
            child = subprocess.Popen(
                ["wl-copy", "--foreground", "--sensitive", "--type", "text/plain;charset=utf-8"],
                stdin=fd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=dict(os.environ, TMPDIR=str(staging)),
            )
            self.owner = child
            while True:
                if child.poll() is not None:
                    raise ClipError("The native clipboard owner exited.")
                try:
                    observed = bounded_run(
                        ["wl-paste", "--no-newline", "--type", "text/plain;charset=utf-8"],
                        maximum=MAX_TEXT + 1,
                        timeout=remaining(),
                    )
                    hint = bounded_run(
                        ["wl-paste", "--no-newline", "--type", PASSWORD_HINT], timeout=remaining()
                    )
                except ClipError:
                    remaining()
                    time.sleep(0.02)
                    continue
                if (
                    observed == data
                    and hint == b"secret"  # pragma: allowlist secret -- native KDE history hint
                    and child.poll() is None
                ):
                    if any(staging.iterdir()):
                        raise ClipError("Native RAM staging was not unlinked before receipt.")
                    return observed
                remaining()
                time.sleep(0.02)
        except BaseException:
            if child is not None:
                self.stop()
            raise
        finally:
            if fd >= 0:
                os.close(fd)
            shutil.rmtree(staging)
            if child is not None and old_owner is not None and old_owner is not child:
                if old_owner.poll() is None:
                    old_owner.terminate()
                try:
                    old_owner.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    old_owner.kill()
                    old_owner.wait(timeout=1)


def peer_connected(stream: socket.socket) -> bool:
    timeout = stream.gettimeout()
    stream.setblocking(False)
    try:
        # The producer waits for the reply. EOF or extra input is not that state.
        stream.recv(1, socket.MSG_PEEK | socket.MSG_DONTWAIT)
        return False
    except BlockingIOError:
        return True
    except OSError:
        return False
    finally:
        stream.settimeout(timeout)


class Endpoint:
    def __init__(self, endpoint: str, session: str, provider):
        self.endpoint = endpoint
        self.session = session
        self.epoch = str(uuid.uuid4())
        self.uid = os.getuid()
        self.provider = provider

    def current(self) -> None:
        verify_wayland_environment(self.uid)
        if active_session(self.uid) != self.session:
            raise ClipError("The endpoint's desktop session is stale.")

    def handle(self, request: dict, connected=lambda: True) -> dict:
        deadline = time.monotonic() + 5
        data = validate_request(request, self.endpoint)
        self.current()
        reply = {
            "v": 1,
            "id": request["id"],
            "endpoint": self.endpoint,
            "session": self.session,
            "epoch": self.epoch,
            "principal": str(self.uid),
        }
        if data is None:
            return reply
        if request["session"] != self.session or request["epoch"] != self.epoch:
            raise ClipError("Desktop session or endpoint epoch has changed.")
        self.current()
        if time.monotonic() >= deadline or not connected():
            raise ClipError("The pending clipboard producer expired or disconnected.")
        observed = self.provider.write(data, deadline)
        self.current()
        if (
            time.monotonic() >= deadline
            or observed != data
            or self.provider.owner.poll() is not None
        ):
            raise ClipError("Native clipboard changed or history exclusion did not match.")
        reply.update(bytes=len(data), sha256=digest(observed), history_excluded=True)
        return reply

    def serve(self, listener: socket.socket) -> None:
        # One connection/effect at a time. No queue of stale payloads.
        while True:
            stream, _address = listener.accept()
            with stream:
                stream.settimeout(8)
                try:
                    if not peer_is_owner(stream, self.uid):
                        raise ClipError("IPC peer is not the enrolled desktop user.")
                    request = decode_json(read_frame(stream, MAX_REQUEST))
                    reply = encode_json(self.handle(request, lambda: peer_connected(stream)))
                except (ClipError, OSError, ValueError, UnicodeError):
                    reply = b'{"error":"clipboard_request_refused"}'
                finally:
                    # Do not retain the last base64 payload while awaiting another peer.
                    request = None
                if len(reply) <= MAX_REPLY:
                    try:
                        send_frame(stream, reply)
                    except OSError:
                        pass


def main() -> int:
    os.umask(0o077)
    uid = os.getuid()
    verify_wayland_environment(uid)
    session = active_session(uid)
    config = decode_json(read_private(Path.home() / ".config/hapax/clipboard-endpoint.json"))
    if (
        set(config) != {"v", "endpoint", "principal"}
        or type(config["v"]) is not int
        or config["v"] != 1
    ):
        raise ClipError("Invalid local endpoint enrollment.")
    if not valid_uuid(config["endpoint"]) or config["principal"] != str(uid):
        raise ClipError("Local endpoint principal does not match.")
    path = socket_path()
    private_directory(path.parent)
    # Refuse an existing owner rather than stealing a live or stale socket.
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind(str(path))
        path.chmod(0o600)
        listener.listen(1)
        provider = NativeProvider(path.parent / "providers")
        endpoint = Endpoint(config["endpoint"], session, provider)
        try:
            endpoint.serve(listener)
        finally:
            provider.stop()
            path.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ClipError, OSError):
        raise SystemExit(
            "Desktop endpoint unavailable. Next action: check its private enrollment, "
            "active unlocked Wayland session and compositor environment."
        ) from None
