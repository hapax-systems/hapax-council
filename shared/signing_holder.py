"""Signing holder: signs witness receipts only for the system witness-rota unit.

The public-gate authority key signs witness receipts (the existing dossier shape). Lanes all run
as one uid, so a key they can read, or a holder that signs for any caller, cannot tell a witness
from an author. This holder runs as a socket-activated system service (``DynamicUser=``, the key
from ``LoadCredentialEncrypted=``). It admits a caller only when the caller's cgroup is the
**system** unit ``hapax-witness-rota@<instance>.service``, which a non-escalating lane cannot
create or attach to (``kernel.yama.ptrace_scope`` 1).

Admission reads the peer's pidfd from the socket itself (``SO_PEERPIDFD``), so there is no window
between learning a pid and opening a pidfd. It reads that pid's cgroup, and then requires the
pidfd to still be alive: a peer that exited meanwhile, whose pid another process may now hold,
is refused.

Bound: lanes are in the ``docker`` and ``wheel`` groups, so any lane is root-equivalent until O5.
Until then this holds against non-escalating lanes only. Installing the units and the key is O3.
"""

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
    """True only for a system-slice instance of the witness-rota template unit."""
    return _ROTA_CGROUP.fullmatch(path) is not None


def cgroup_of(pid: int, *, proc_root: Path = Path("/proc")) -> str:
    """The pid's cgroup v2 path, or "" when there is no unified-hierarchy line."""
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
    """Admit the connected peer only if it is a live process in the system witness-rota unit."""
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
    """The request, or None when it exceeds the limit.

    It reads to EOF (discarding past the limit, up to a hard cap) so that closing never resets
    the caller before it reads the reply.
    """
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
    """Answer one connection: a signature line when admitted, else a refusal line."""
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
    signature = public_gate_authority_signature(payload, secret)
    log(f"signed: sha256 {hashlib.sha256(request).hexdigest()} for {admission.cgroup}")
    _reply(conn, signature)
    return 0


def load_secret(env: Mapping[str, str]) -> str | None:
    """The key from the unit's credentials directory only, never from the environment."""
    directory = env.get("CREDENTIALS_DIRECTORY")
    if not directory:
        return None
    try:
        secret = (Path(directory) / CREDENTIAL_NAME).read_text().strip()
    except FileNotFoundError:
        return None
    return secret or None


def request_signature(payload: Mapping[str, Any], socket_path: Path = SOCKET_PATH) -> str:
    """Ask the holder to sign; raise SigningRefused with its reason otherwise."""
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
