"""The signing holder signs only for the system witness-rota unit.

A refused caller gets no signature, every act is logged without the key, and failure narrows.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from shared import signing_holder as holder
from shared.public_gate_receipts import public_gate_authority_signature
from shared.signing_holder import (
    CREDENTIAL_NAME,
    Admission,
    SigningRefused,
    admit,
    cgroup_admitted,
    cgroup_of,
    load_secret,
    request_signature,
    serve,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ROTA = "/system.slice/system-hapax\\x2dwitness\\x2drota.slice/hapax-witness-rota@r1.service"
SECRET = "test-secret-not-a-real-key"
PAYLOAD = {"dossier_schema": 1, "task_id": "witness-abc", "review_team_verdict": "quorum-accept"}
ADMITTED = Admission(True, "admitted", ROTA)
REFUSED = Admission(
    False, "caller cgroup /user.slice/x is not the witness rota unit", "/user.slice/x"
)
BLOCKING_CLIENT = (
    "import socket, sys; s = socket.socket(socket.AF_UNIX); s.connect(sys.argv[1]); s.recv(1)"
)


# --- which cgroups are admitted ---


def test_the_system_rota_unit_is_admitted() -> None:
    assert cgroup_admitted(ROTA)


@pytest.mark.parametrize(
    "path",
    [
        "/user.slice/user-1000.slice/user@1000.service/app.slice/hapax-witness-rota@r1.service",
        "/user.slice/user-1000.slice/user@1000.service/system.slice/"
        "system-hapax\\x2dwitness\\x2drota.slice/hapax-witness-rota@r1.service",
    ],
)
def test_a_user_slice_unit_with_the_rota_name_is_refused(path: str) -> None:
    assert not cgroup_admitted(path)


@pytest.mark.parametrize(
    "path",
    [
        "/system.slice/sshd.service",
        f"{ROTA}/child",
        "/system.slice/hapax-witness-rota.service",
        "/system.slice/system-hapax\\x2dwitness\\x2drota.slice/hapax-witness-rota-x@r1.service",
        "",
    ],
)
def test_other_cgroups_are_refused(path: str) -> None:
    assert not cgroup_admitted(path)


def test_the_cgroup_is_read_from_the_unified_hierarchy_line(tmp_path: Path) -> None:
    (tmp_path / "42").mkdir()
    (tmp_path / "42" / "cgroup").write_text(f"12:cpu,cpuacct:/elsewhere\n0::{ROTA}\n")
    assert cgroup_of(42, proc_root=tmp_path) == ROTA


def test_a_cgroup_file_without_a_unified_line_reads_empty(tmp_path: Path) -> None:
    (tmp_path / "42").mkdir()
    (tmp_path / "42" / "cgroup").write_text(f"12:cpu:{ROTA}\n")
    assert cgroup_of(42, proc_root=tmp_path) == ""


# --- admission uses the peer's pidfd from the socket itself ---


@pytest.fixture
def listener(tmp_path: Path):
    path = tmp_path / "h.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    server.listen(1)
    server.settimeout(10)
    yield server, path
    server.close()


def _connect_child(server: socket.socket, path: Path) -> tuple[socket.socket, subprocess.Popen]:
    child = subprocess.Popen([sys.executable, "-c", BLOCKING_CLIENT, str(path)])
    conn, _ = server.accept()
    return conn, child


def test_a_uid_1000_caller_outside_the_rota_unit_is_refused() -> None:
    a, b = socket.socketpair()
    with a, b:
        result = admit(a)
    assert not result.ok
    assert result.cgroup == cgroup_of(os.getpid())
    assert result.cgroup in result.reason


def test_a_live_peer_in_the_rota_unit_is_admitted() -> None:
    a, b = socket.socketpair()
    with a, b:
        assert admit(a, read_cgroup=lambda pid: ROTA).ok


def test_the_cgroup_read_is_the_connecting_peers(listener) -> None:
    server, path = listener
    conn, child = _connect_child(server, path)
    seen: list[int] = []
    with conn:
        admit(conn, read_cgroup=lambda pid: seen.append(pid) or ROTA)
        conn.sendall(b"x")
    child.wait(timeout=10)
    assert seen == [child.pid]


def test_a_pid_reused_by_the_rota_unit_is_refused(listener) -> None:
    server, path = listener
    conn, child = _connect_child(server, path)

    def peer_dies_and_its_pid_is_reused(pid: int) -> str:
        conn.sendall(b"x")
        child.wait(timeout=10)
        return ROTA

    with conn:
        result = admit(conn, read_cgroup=peer_dies_and_its_pid_is_reused)
    assert not result.ok


def test_a_socket_without_a_peer_pidfd_is_refused() -> None:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as unconnected:
        assert not admit(unconnected, read_cgroup=lambda pid: ROTA).ok


# --- the service: sign only when admitted, log every act, never the key ---


def exchange(
    request: bytes,
    admission: Admission,
    *,
    log: list[str] | None = None,
) -> tuple[int, str]:
    a, b = socket.socketpair()
    received: list[bytes] = []

    def client() -> None:
        try:
            b.sendall(request)
            b.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        chunks = []
        while chunk := b.recv(65536):
            chunks.append(chunk)
        received.append(b"".join(chunks))

    thread = threading.Thread(target=client, daemon=True)
    thread.start()
    with a:
        rc = serve(
            a, SECRET, admit_fn=lambda s: admission, log=(log if log is not None else []).append
        )
    thread.join(timeout=10)
    b.close()
    return rc, received[0].decode() if received else ""


def test_an_admitted_request_gets_the_resolvers_signature() -> None:
    rc, response = exchange(json.dumps(PAYLOAD).encode(), ADMITTED)
    assert rc == 0
    assert response == public_gate_authority_signature(PAYLOAD, SECRET) + "\n"


def test_a_refused_caller_gets_no_signature() -> None:
    rc, response = exchange(json.dumps(PAYLOAD).encode(), REFUSED)
    assert rc != 0
    assert response.startswith("refused:") and "hmac-sha256:" not in response


def test_an_oversized_request_is_refused() -> None:
    big = json.dumps({"x": "a" * (1 << 20)}).encode()
    rc, response = exchange(big, ADMITTED)
    assert rc != 0 and response.startswith("refused:")


@pytest.mark.parametrize("request_bytes", [b"[1, 2]", b"not json", b"\xff\xfe"])
def test_a_request_that_is_not_a_json_mapping_is_refused(request_bytes: bytes) -> None:
    rc, response = exchange(request_bytes, ADMITTED)
    assert rc != 0 and response.startswith("refused:")


def test_each_signing_act_is_logged_without_the_key() -> None:
    lines: list[str] = []
    request = json.dumps(PAYLOAD).encode()
    exchange(request, ADMITTED, log=lines)
    assert len(lines) == 1
    assert ROTA in lines[0] and hashlib.sha256(request).hexdigest() in lines[0]
    assert SECRET not in lines[0]


def test_each_refusal_is_logged() -> None:
    lines: list[str] = []
    exchange(json.dumps(PAYLOAD).encode(), REFUSED, log=lines)
    assert len(lines) == 1 and lines[0].startswith("refused")


# --- the key comes only from the unit's credential ---


def test_the_key_is_read_from_the_units_credentials_directory(tmp_path: Path) -> None:
    (tmp_path / CREDENTIAL_NAME).write_text(SECRET + "\n")
    assert load_secret({"CREDENTIALS_DIRECTORY": str(tmp_path)}) == SECRET


def test_a_missing_credential_loads_nothing(tmp_path: Path) -> None:
    assert load_secret({"CREDENTIALS_DIRECTORY": str(tmp_path)}) is None
    assert load_secret({}) is None


def test_the_environment_key_is_never_used() -> None:
    assert load_secret({"HAPAX_PUBLIC_GATE_AUTHORITY_HMAC_KEY": SECRET}) is None


def test_main_refuses_this_process_with_real_admission(tmp_path: Path) -> None:
    (tmp_path / CREDENTIAL_NAME).write_text(SECRET)
    a, b = socket.socketpair()
    with a, b:
        b.sendall(json.dumps(PAYLOAD).encode())
        b.shutdown(socket.SHUT_WR)
        rc = holder.main(conn=a, env={"CREDENTIALS_DIRECTORY": str(tmp_path)})
        a.shutdown(socket.SHUT_WR)
        response = b.recv(65536).decode()
    assert rc != 0 and response.startswith("refused:")


def test_main_without_a_credential_refuses_and_names_the_next_action() -> None:
    a, b = socket.socketpair()
    with a, b:
        b.shutdown(socket.SHUT_WR)
        rc = holder.main(conn=a, env={})
        a.shutdown(socket.SHUT_WR)
        response = b.recv(65536).decode()
    assert rc != 0 and response.startswith("refused:") and "next action:" in response


# --- the client ---


def _serve_once(server: socket.socket, admission: Admission) -> threading.Thread:
    def run() -> None:
        try:
            conn, _ = server.accept()
        except OSError:
            return
        with conn:
            serve(conn, SECRET, admit_fn=lambda s: admission, log=lambda line: None)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def test_the_client_gets_the_signature_from_the_holder(listener) -> None:
    server, path = listener
    thread = _serve_once(server, ADMITTED)
    assert request_signature(PAYLOAD, path) == public_gate_authority_signature(PAYLOAD, SECRET)
    thread.join(timeout=10)


def test_the_client_raises_when_refused(listener) -> None:
    server, path = listener
    thread = _serve_once(server, REFUSED)
    with pytest.raises(SigningRefused):
        request_signature(PAYLOAD, path)
    thread.join(timeout=10)


# --- packaging: system-scoped, socket-activated, credential-only ---

SOCKET_UNIT = REPO_ROOT / "systemd/units/hapax-signing-holder.socket"
SERVICE_UNIT = REPO_ROOT / "systemd/units/hapax-signing-holder@.service"
ENTRY = REPO_ROOT / "scripts/hapax-signing-holder"


def test_the_holder_units_are_system_scoped_and_socket_activated() -> None:
    sock, service = SOCKET_UNIT.read_text(), SERVICE_UNIT.read_text()
    assert "# Hapax-Install-Scope: system" in sock and "# Hapax-Install-Scope: system" in service
    assert "ListenStream=/run/hapax-signing-holder.sock" in sock
    assert "Accept=yes" in sock
    for line in (
        "DynamicUser=yes",
        f"LoadCredentialEncrypted={CREDENTIAL_NAME}",
        "StandardInput=socket",
        "ExecStart=/usr/local/sbin/hapax-signing-holder",
    ):
        assert line in service, line
    assert "ProtectProc=invisible" not in service
    assert "HAPAX_PUBLIC_GATE_AUTHORITY_HMAC_KEY" not in service


def test_the_entry_script_imports_only_the_installed_library() -> None:
    lines = ENTRY.read_text().splitlines()
    assert lines[0] == "#!/usr/bin/python3 -I"
    text = "\n".join(lines)
    assert 'sys.path.insert(0, "/usr/local/lib/hapax/signing-holder")' in text
    assert "from shared.signing_holder import main" in text
