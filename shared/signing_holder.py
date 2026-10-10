"""Sign for admitted witness-rota peers."""

from __future__ import annotations

import hashlib
import json
import os
import re
import select
import socket
import struct
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shared.public_gate_receipts import public_gate_authority_signature

SO_PEERPIDFD = getattr(socket, "SO_PEERPIDFD", 77)
CREDENTIAL_NAME = "hapax-public-gate-authority-hmac-key"
SOCKET_PATH = Path("/run/hapax-signing-holder.sock")
MAX_REQUEST_BYTES = 1 << 20
_ROTA_CGROUP = re.compile(
    r"/system\.slice/system-hapax\\x2dwitness\\x2drota\.slice/hapax-witness-rota@[^/]+\.service"
)


class SigningRefused(RuntimeError):
    pass


@dataclass(frozen=True)
class Admission:
    ok: bool
    reason: str
    cgroup: str = ""


def cgroup_admitted(path: str) -> bool:
    return _ROTA_CGROUP.fullmatch(path) is not None


def cgroup_of(pid: int, *, proc_root: Path = Path("/proc")) -> str:
    for line in (proc_root / str(pid) / "cgroup").read_text().splitlines():
        if line.startswith("0::"):
            return line[3:]
    return ""


def _pid_of(pidfd: int) -> int:
    for line in Path(f"/proc/self/fdinfo/{pidfd}").read_text().splitlines():
        if line.startswith("Pid:"):
            return int(line.split()[1])
    raise OSError("pidfd has no Pid line")


def _exited(pidfd: int) -> bool:
    poller = select.poll()
    poller.register(pidfd, select.POLLIN)
    return bool(poller.poll(0))


def admit(sock: socket.socket, *, read_cgroup: Callable[[int], str] | None = None) -> Admission:
    read_cgroup = read_cgroup or cgroup_of
    try:
        raw = sock.getsockopt(socket.SOL_SOCKET, SO_PEERPIDFD, struct.calcsize("i"))
        pidfd = struct.unpack("i", raw)[0]
    except OSError as exc:
        return Admission(False, f"no peer pidfd ({exc.strerror}); only local stream callers")
    try:
        pid = _pid_of(pidfd)
        cgroup = read_cgroup(pid)
        if _exited(pidfd):
            return Admission(False, f"peer {pid} exited during admission", cgroup)
    except OSError as exc:
        return Admission(False, f"peer cannot be read ({exc.strerror})")
    finally:
        os.close(pidfd)
    if not cgroup_admitted(cgroup):
        return Admission(
            False, f"caller cgroup {cgroup or '(none)'} is not the witness rota unit", cgroup
        )
    return Admission(True, "admitted", cgroup)


def _read_request(conn: socket.socket) -> bytes | None:
    """Read through EOF before refusing overflow."""
    chunks: list[bytes] = []
    size = 0
    while size <= 16 * MAX_REQUEST_BYTES and (chunk := conn.recv(65536)):
        size += len(chunk)
        if size <= MAX_REQUEST_BYTES:
            chunks.append(chunk)
    return b"".join(chunks) if size <= MAX_REQUEST_BYTES else None


def _json_mapping(request: bytes) -> Mapping[str, Any] | None:
    try:
        payload = json.loads(request)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, Mapping) else None


def _reply(conn: socket.socket, line: str) -> None:
    conn.sendall((line + "\n").encode())
    conn.shutdown(socket.SHUT_WR)


def serve(
    conn: socket.socket,
    secret: str,
    *,
    admit_fn: Callable[[socket.socket], Admission] | None = None,
    log: Callable[[str], None] | None = None,
) -> int:
    admit_fn = admit_fn or admit
    log = log or (lambda line: print(line, file=sys.stderr))
    admission = admit_fn(conn)
    request = _read_request(conn)
    if not admission.ok:
        log(f"refused: {admission.reason}")
        _reply(conn, f"refused: {admission.reason}")
        return 1
    payload = _json_mapping(request) if request is not None else None
    if request is None or payload is None:
        log(f"refused: request from {admission.cgroup} is not a JSON mapping within the size limit")
        _reply(conn, "refused: the request must be one JSON mapping of at most 1 MiB")
        return 1
    refreshed = admit_fn(conn)
    if not refreshed.ok:
        log(f"refused: {refreshed.reason}")
        _reply(conn, f"refused: {refreshed.reason}")
        return 1
    signature = public_gate_authority_signature(payload, secret)
    log(f"signed: sha256 {hashlib.sha256(request).hexdigest()} for {refreshed.cgroup}")
    _reply(conn, signature)
    return 0


def load_secret(env: Mapping[str, str]) -> str | None:
    directory = env.get("CREDENTIALS_DIRECTORY")
    if not directory:
        return None
    try:
        secret = (Path(directory) / CREDENTIAL_NAME).read_text().strip()
    except FileNotFoundError:
        return None
    return secret or None


def request_signature(payload: Mapping[str, Any], socket_path: Path = SOCKET_PATH) -> str:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(30)
        sock.connect(str(socket_path))
        sock.sendall(json.dumps(payload).encode())
        sock.shutdown(socket.SHUT_WR)
        chunks: list[bytes] = []
        while chunk := sock.recv(65536):
            chunks.append(chunk)
    line = b"".join(chunks).decode().strip()
    if not line.startswith("hmac-sha256:"):
        raise SigningRefused(line or "the holder closed without answering")
    return line


def main(conn: socket.socket | None = None, env: Mapping[str, str] | None = None) -> int:
    conn = conn or socket.socket(fileno=0)
    secret = load_secret(os.environ if env is None else env)
    if secret is None:
        reason = f"the holder has no {CREDENTIAL_NAME} credential; next action: O3 installs it"
        print(f"refused: {reason}", file=sys.stderr)
        _reply(conn, f"refused: {reason}")
        return 1
    return serve(conn, secret)
