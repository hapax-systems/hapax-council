from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import socket
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-coord-runtime-witness"
WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _init_source_repo(tmp_path: Path) -> tuple[Path, str]:
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    repo = tmp_path / "hapax-coord"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "coord-witness-test@example.test")
    _git(repo, "config", "user.name", "Coord Witness Test")
    (repo / "scripts").mkdir()
    (repo / "scripts/run-dev.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (repo / "README.md").write_text("# Hapax Coordination\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-u", "origin", "main")
    return repo, _git(repo, "rev-parse", "HEAD")


def _activation_worktree(source_repo: Path, sha: str, tmp_path: Path) -> Path:
    activation = tmp_path / "activation/worktree"
    activation.parent.mkdir()
    _git(source_repo, "worktree", "add", "--detach", str(activation), sha)
    (activation / ".deployed-sha").write_text(f"{sha}\n", encoding="utf-8")
    return activation


def _fake_systemctl(
    tmp_path: Path,
    activation: Path,
    *,
    working_directory: Path | None = None,
    exec_start: str | None = None,
    rc: int = 0,
    active_state: str = "active",
    sub_state: str = "running",
    result: str = "success",
) -> Path:
    working_directory = working_directory or activation
    exec_start = exec_start or (
        f"{{ path={activation}/scripts/run-dev.sh ; "
        f"argv[]={activation}/scripts/run-dev.sh --daemon ; ignore_errors=no }}"
    )
    fake = tmp_path / "systemctl"
    if rc:
        fake.write_text(
            f"#!/usr/bin/env bash\necho systemctl failed >&2\nexit {rc}\n",
            encoding="utf-8",
        )
        fake.chmod(0o755)
        return fake
    fake.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'if [ "${1:-}" = "--user" ] && [ "${2:-}" = "show" ]; then\n'
        "cat <<EOF\n"
        f"ActiveState={active_state}\n"
        f"SubState={sub_state}\n"
        f"Result={result}\n"
        "ExecMainStatus=0\n"
        "MainPID=123\n"
        "FragmentPath=/tmp/hapax-coord.service\n"
        "DropInPaths=\n"
        f"WorkingDirectory={working_directory}\n"
        f"ExecStart={exec_start}\n"
        "EOF\n"
        "exit 0\n"
        "fi\n"
        "exit 2\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return fake


def _fake_journalctl(tmp_path: Path, body: str, *, rc: int = 0) -> Path:
    fake = tmp_path / "journalctl"
    fake.write_text(
        f"#!/usr/bin/env bash\ncat <<'EOF'\n{body}\nEOF\nexit {rc}\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return fake


class _CoordHandler(BaseHTTPRequestHandler):
    body = b"<!doctype html><title>Hapax Coordination</title>"
    status = 200

    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name.
        self.send_response(self.status)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def _serve_coord_marker(body: bytes | None = None, status: int = 200) -> tuple[HTTPServer, str]:
    class Handler(_CoordHandler):
        pass

    if body is not None:
        Handler.body = body
    Handler.status = status
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, f"http://{host}:{port}/"


def _ws_text_frame(text: str) -> bytes:
    payload = text.encode("utf-8")
    header = bytearray([0x81])
    length = len(payload)
    if length < 126:
        header.append(length)
    elif length <= 0xFFFF:
        header.extend([126, (length >> 8) & 0xFF, length & 0xFF])
    else:
        header.append(127)
        header.extend(length.to_bytes(8, "big"))
    return bytes(header) + payload


def _read_ws_client_text(conn: socket.socket) -> str:
    first = conn.recv(2)
    if len(first) < 2:
        return ""
    length = first[1] & 0x7F
    if length == 126:
        length = int.from_bytes(conn.recv(2), "big")
    elif length == 127:
        length = int.from_bytes(conn.recv(8), "big")
    mask = conn.recv(4)
    payload = bytearray()
    while len(payload) < length:
        chunk = conn.recv(length - len(payload))
        if not chunk:
            break
        payload.extend(chunk)
    decoded = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    return decoded.decode("utf-8", errors="replace")


class _FakeWebSocketServer:
    def __init__(
        self,
        *,
        marker: bool = True,
        status: int = 101,
        path_challenge: bool = True,
        marker_before_challenge: bool = False,
        accept_override: bytes | None = None,
    ) -> None:
        self.marker = marker
        self.status = status
        self.path_challenge = path_challenge
        self.marker_before_challenge = marker_before_challenge
        self.accept_override = accept_override
        self.request_path = ""
        self.received_messages: list[str] = []
        self._sock = socket.socket()
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(1)
        self._sock.settimeout(5)
        host, port = self._sock.getsockname()
        self.url = f"ws://{host}:{port}/clog"
        self._thread = threading.Thread(target=self._serve_once, daemon=True)
        self._thread.start()

    def _serve_once(self) -> None:
        try:
            conn, _addr = self._sock.accept()
        except OSError:
            return
        with conn:
            conn.settimeout(5)
            request = b""
            while b"\r\n\r\n" not in request:
                chunk = conn.recv(1024)
                if not chunk:
                    return
                request += chunk
            request_text = request.decode("iso-8859-1", errors="replace")
            self.request_path = request_text.split(" ", 2)[1]
            key_match = re.search(r"^Sec-WebSocket-Key:\s*(.+)$", request_text, re.MULTILINE)
            if self.status != 101 or key_match is None:
                conn.sendall(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
                return
            accept = base64.b64encode(
                hashlib.sha1(f"{key_match.group(1).strip()}{WEBSOCKET_GUID}".encode()).digest()
            )
            accept = self.accept_override or accept
            conn.sendall(
                b"HTTP/1.1 101 Switching Protocols\r\n"
                b"Upgrade: websocket\r\n"
                b"Connection: Upgrade\r\n" + b"Sec-WebSocket-Accept: " + accept + b"\r\n\r\n"
            )
            if self.accept_override is not None:
                return
            conn.sendall(_ws_text_frame("clog['connection_id']='test-connection'"))
            if self.marker and self.marker_before_challenge:
                conn.sendall(_ws_text_frame("clog['document'].title='Hapax Coordination'"))
            if self.path_challenge:
                conn.sendall(
                    _ws_text_frame(
                        'ws.send ("7:"+eval("$(clog[\\x27location\\x27]).prop(\\x27pathname\\x27)"));'
                    )
                )
                self.received_messages.append(_read_ws_client_text(conn))
            if self.marker and not self.marker_before_challenge:
                conn.sendall(_ws_text_frame("clog['document'].title='Hapax Coordination'"))
            elif not self.marker:
                conn.sendall(_ws_text_frame("clog['document'].title='Other'"))

    def close(self) -> None:
        self._sock.close()
        self._thread.join(timeout=5)


def _run_witness(
    *,
    source_repo: Path,
    activation: Path,
    systemctl: Path,
    journalctl: Path,
    url: str = "http://127.0.0.1:1/",
    extra_args: list[str] | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "HAPAX_COORD_WITNESS_ACTIVATION_WORKTREE": str(activation),
        "HAPAX_COORD_WITNESS_SYSTEMCTL": str(systemctl),
        "HAPAX_COORD_WITNESS_JOURNALCTL": str(journalctl),
        "HAPAX_COORD_WITNESS_URL": url,
        **(extra_env or {"HAPAX_COORD_WITNESS_SOURCE_REPO": str(source_repo)}),
    }
    return subprocess.run(
        [str(SCRIPT), "--json", *(extra_args or [])],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_coord_runtime_witness_accepts_activation_receipt_render_and_journal(
    tmp_path: Path,
) -> None:
    source_repo, sha = _init_source_repo(tmp_path)
    activation = _activation_worktree(source_repo, sha, tmp_path)
    systemctl = _fake_systemctl(tmp_path, activation)
    journalctl = _fake_journalctl(tmp_path, "Listening on 127.0.0.1:8765.")
    server, url = _serve_coord_marker()
    ws_server = _FakeWebSocketServer()

    try:
        result = _run_witness(
            source_repo=source_repo,
            activation=activation,
            systemctl=systemctl,
            journalctl=journalctl,
            url=url,
            extra_args=["--websocket-url", ws_server.url],
        )
    finally:
        server.shutdown()
        ws_server.close()

    assert result.returncode == 0, result.stderr
    witness = json.loads(result.stdout)
    assert witness["ok"] is True
    assert witness["checks"]["activation"]["activation_head"] == sha
    assert witness["checks"]["activation"]["deployed_sha"] == sha
    assert witness["checks"]["activation"]["source_origin_main"] == sha
    assert witness["checks"]["activation"]["source_remote_main"] == sha
    assert witness["checks"]["http"]["status"] == 200
    assert witness["checks"]["websocket"]["status"] == 101
    assert witness["checks"]["websocket"]["path"] == "/clog"
    assert witness["checks"]["websocket"]["frames"]
    assert witness["checks"]["websocket"]["render_marker_seen"] is True
    assert witness["checks"]["websocket"]["path_challenge_seen"] is True
    assert witness["checks"]["websocket"]["path_reply_sent"] is True
    assert ws_server.received_messages == ["7:/"]
    assert witness["checks"]["journal"]["overflow_signature_matches"] == []


def test_coord_runtime_witness_fails_when_activation_lags_origin_main(tmp_path: Path) -> None:
    source_repo, sha_a = _init_source_repo(tmp_path)
    activation = _activation_worktree(source_repo, sha_a, tmp_path)
    (source_repo / "README.md").write_text("# Hapax Coordination\nnew\n", encoding="utf-8")
    _git(source_repo, "add", "README.md")
    _git(source_repo, "commit", "-m", "new main")
    _git(source_repo, "push", "origin", "main")
    _git(source_repo, "fetch", "origin", "+refs/heads/main:refs/remotes/origin/main")
    systemctl = _fake_systemctl(tmp_path, activation)
    journalctl = _fake_journalctl(tmp_path, "Listening on 127.0.0.1:8765.")

    result = _run_witness(
        source_repo=source_repo,
        activation=activation,
        systemctl=systemctl,
        journalctl=journalctl,
        extra_args=["--skip-http", "--skip-websocket"],
    )

    assert result.returncode == 1
    witness = json.loads(result.stdout)
    assert "activation_not_at_source_origin_main" in witness["failures"]


def test_coord_runtime_witness_fails_when_remote_main_advances_without_fetch(
    tmp_path: Path,
) -> None:
    source_repo, sha_a = _init_source_repo(tmp_path)
    activation = _activation_worktree(source_repo, sha_a, tmp_path)
    other = tmp_path / "other"
    origin_url = _git(source_repo, "remote", "get-url", "origin")
    _git(source_repo, "clone", origin_url, str(other))
    _git(other, "config", "user.email", "coord-witness-test@example.test")
    _git(other, "config", "user.name", "Coord Witness Test")
    (other / "README.md").write_text("# Hapax Coordination\nremote\n", encoding="utf-8")
    _git(other, "add", "README.md")
    _git(other, "commit", "-m", "remote main")
    _git(other, "push", "origin", "main")
    systemctl = _fake_systemctl(tmp_path, activation)
    journalctl = _fake_journalctl(tmp_path, "Listening on 127.0.0.1:8765.")

    result = _run_witness(
        source_repo=source_repo,
        activation=activation,
        systemctl=systemctl,
        journalctl=journalctl,
        extra_args=["--skip-http", "--skip-websocket"],
    )

    assert result.returncode == 1
    witness = json.loads(result.stdout)
    assert witness["checks"]["activation"]["source_origin_main"] == sha_a
    assert witness["checks"]["activation"]["source_remote_main"] != sha_a
    assert "activation_not_at_source_remote_main" in witness["failures"]


def test_coord_runtime_witness_honors_coord_deploy_repo_fallback(tmp_path: Path) -> None:
    source_repo, sha = _init_source_repo(tmp_path)
    activation = _activation_worktree(source_repo, sha, tmp_path)
    systemctl = _fake_systemctl(tmp_path, activation)
    journalctl = _fake_journalctl(tmp_path, "Listening on 127.0.0.1:8765.")

    result = _run_witness(
        source_repo=source_repo,
        activation=activation,
        systemctl=systemctl,
        journalctl=journalctl,
        extra_args=["--skip-http", "--skip-websocket"],
        extra_env={"HAPAX_COORD_DEPLOY_REPO": str(source_repo)},
    )

    assert result.returncode == 0, result.stderr
    witness = json.loads(result.stdout)
    assert witness["checks"]["activation"]["source_repo"] == str(source_repo)
    assert witness["checks"]["activation"]["source_origin_main"] == sha


def test_coord_runtime_witness_fails_on_wrong_unit_root(tmp_path: Path) -> None:
    source_repo, sha = _init_source_repo(tmp_path)
    activation = _activation_worktree(source_repo, sha, tmp_path)
    wrong_root = tmp_path / "mutable-hapax-coord"
    systemctl = _fake_systemctl(tmp_path, activation, working_directory=wrong_root)
    journalctl = _fake_journalctl(tmp_path, "Listening on 127.0.0.1:8765.")

    result = _run_witness(
        source_repo=source_repo,
        activation=activation,
        systemctl=systemctl,
        journalctl=journalctl,
        extra_args=["--skip-http", "--skip-websocket"],
    )

    assert result.returncode == 1
    witness = json.loads(result.stdout)
    assert any(
        failure.startswith("unit_wrong_working_directory:") for failure in witness["failures"]
    )


def test_coord_runtime_witness_fails_on_deployed_sha_mismatch(tmp_path: Path) -> None:
    source_repo, sha = _init_source_repo(tmp_path)
    activation = _activation_worktree(source_repo, sha, tmp_path)
    (activation / ".deployed-sha").write_text("0" * 40 + "\n", encoding="utf-8")
    systemctl = _fake_systemctl(tmp_path, activation)
    journalctl = _fake_journalctl(tmp_path, "Listening on 127.0.0.1:8765.")

    result = _run_witness(
        source_repo=source_repo,
        activation=activation,
        systemctl=systemctl,
        journalctl=journalctl,
        extra_args=["--skip-http", "--skip-websocket"],
    )

    assert result.returncode == 1
    witness = json.loads(result.stdout)
    assert "deployed_sha_mismatch" in witness["failures"]


def test_coord_runtime_witness_fails_when_activation_run_dev_is_missing(tmp_path: Path) -> None:
    source_repo, sha = _init_source_repo(tmp_path)
    activation = _activation_worktree(source_repo, sha, tmp_path)
    (activation / "scripts/run-dev.sh").unlink()
    systemctl = _fake_systemctl(tmp_path, activation)
    journalctl = _fake_journalctl(tmp_path, "Listening on 127.0.0.1:8765.")

    result = _run_witness(
        source_repo=source_repo,
        activation=activation,
        systemctl=systemctl,
        journalctl=journalctl,
        extra_args=["--skip-http", "--skip-websocket"],
    )

    assert result.returncode == 1
    witness = json.loads(result.stdout)
    assert any(failure.startswith("activation_run_dev_missing:") for failure in witness["failures"])


def test_coord_runtime_witness_fails_when_deployed_sha_receipt_is_missing(
    tmp_path: Path,
) -> None:
    source_repo, sha = _init_source_repo(tmp_path)
    activation = _activation_worktree(source_repo, sha, tmp_path)
    (activation / ".deployed-sha").unlink()
    systemctl = _fake_systemctl(tmp_path, activation)
    journalctl = _fake_journalctl(tmp_path, "Listening on 127.0.0.1:8765.")

    result = _run_witness(
        source_repo=source_repo,
        activation=activation,
        systemctl=systemctl,
        journalctl=journalctl,
        extra_args=["--skip-http", "--skip-websocket"],
    )

    assert result.returncode == 1
    witness = json.loads(result.stdout)
    assert any(
        failure.startswith("deployed_sha_receipt_missing:") for failure in witness["failures"]
    )


def test_coord_runtime_witness_fails_when_deployed_sha_receipt_is_empty(
    tmp_path: Path,
) -> None:
    source_repo, sha = _init_source_repo(tmp_path)
    activation = _activation_worktree(source_repo, sha, tmp_path)
    (activation / ".deployed-sha").write_text("\n", encoding="utf-8")
    systemctl = _fake_systemctl(tmp_path, activation)
    journalctl = _fake_journalctl(tmp_path, "Listening on 127.0.0.1:8765.")

    result = _run_witness(
        source_repo=source_repo,
        activation=activation,
        systemctl=systemctl,
        journalctl=journalctl,
        extra_args=["--skip-http", "--skip-websocket"],
    )

    assert result.returncode == 1
    witness = json.loads(result.stdout)
    assert witness["checks"]["activation"]["deployed_sha"] == ""
    assert "deployed_sha_receipt_empty" in witness["failures"]


def test_coord_runtime_witness_fails_on_dirty_activation_but_ignores_receipt(
    tmp_path: Path,
) -> None:
    source_repo, sha = _init_source_repo(tmp_path)
    activation = _activation_worktree(source_repo, sha, tmp_path)
    (activation / "untracked.txt").write_text("dirty\n", encoding="utf-8")
    systemctl = _fake_systemctl(tmp_path, activation)
    journalctl = _fake_journalctl(tmp_path, "Listening on 127.0.0.1:8765.")

    result = _run_witness(
        source_repo=source_repo,
        activation=activation,
        systemctl=systemctl,
        journalctl=journalctl,
        extra_args=["--skip-http", "--skip-websocket"],
    )

    assert result.returncode == 1
    witness = json.loads(result.stdout)
    assert "activation_worktree_dirty" in witness["failures"]
    assert witness["checks"]["activation"]["activation_dirty_entries"] == ["?? untracked.txt"]


def test_coord_runtime_witness_ignores_gitignored_runtime_artifacts(
    tmp_path: Path,
) -> None:
    source_repo, _sha = _init_source_repo(tmp_path)
    (source_repo / ".gitignore").write_text("cache/\n", encoding="utf-8")
    _git(source_repo, "add", ".gitignore")
    _git(source_repo, "commit", "-m", "ignore runtime cache")
    _git(source_repo, "push", "origin", "main")
    sha = _git(source_repo, "rev-parse", "HEAD")
    activation = _activation_worktree(source_repo, sha, tmp_path)
    (activation / "cache").mkdir()
    (activation / "cache/runtime.fasl").write_text("artifact\n", encoding="utf-8")
    systemctl = _fake_systemctl(tmp_path, activation)
    journalctl = _fake_journalctl(tmp_path, "Listening on 127.0.0.1:8765.")

    result = _run_witness(
        source_repo=source_repo,
        activation=activation,
        systemctl=systemctl,
        journalctl=journalctl,
        extra_args=["--skip-http", "--skip-websocket"],
    )

    assert result.returncode == 0, result.stderr
    witness = json.loads(result.stdout)
    assert witness["checks"]["activation"]["activation_dirty_entries"] == []


def test_coord_runtime_witness_accepts_http_marker_beyond_legacy_sample(
    tmp_path: Path,
) -> None:
    source_repo, sha = _init_source_repo(tmp_path)
    activation = _activation_worktree(source_repo, sha, tmp_path)
    systemctl = _fake_systemctl(tmp_path, activation)
    journalctl = _fake_journalctl(tmp_path, "Listening on 127.0.0.1:8765.")
    server, url = _serve_coord_marker(b"x" * 20_000 + b"Hapax Coordination")
    ws_server = _FakeWebSocketServer()

    try:
        result = _run_witness(
            source_repo=source_repo,
            activation=activation,
            systemctl=systemctl,
            journalctl=journalctl,
            url=url,
            extra_args=["--websocket-url", ws_server.url],
        )
    finally:
        server.shutdown()
        ws_server.close()

    assert result.returncode == 0, result.stderr
    witness = json.loads(result.stdout)
    assert witness["ok"] is True


def test_coord_runtime_witness_fails_on_http_non_200(tmp_path: Path) -> None:
    source_repo, sha = _init_source_repo(tmp_path)
    activation = _activation_worktree(source_repo, sha, tmp_path)
    systemctl = _fake_systemctl(tmp_path, activation)
    journalctl = _fake_journalctl(tmp_path, "Listening on 127.0.0.1:8765.")
    server, url = _serve_coord_marker(b"not found", status=503)
    ws_server = _FakeWebSocketServer()

    try:
        result = _run_witness(
            source_repo=source_repo,
            activation=activation,
            systemctl=systemctl,
            journalctl=journalctl,
            url=url,
            extra_args=["--websocket-url", ws_server.url],
        )
    finally:
        server.shutdown()
        ws_server.close()

    assert result.returncode == 1
    witness = json.loads(result.stdout)
    assert "http_status_not_200:503" in witness["failures"]


def test_coord_runtime_witness_fails_when_http_probe_fails(tmp_path: Path) -> None:
    source_repo, sha = _init_source_repo(tmp_path)
    activation = _activation_worktree(source_repo, sha, tmp_path)
    systemctl = _fake_systemctl(tmp_path, activation)
    journalctl = _fake_journalctl(tmp_path, "Listening on 127.0.0.1:8765.")

    result = _run_witness(
        source_repo=source_repo,
        activation=activation,
        systemctl=systemctl,
        journalctl=journalctl,
        url="http://127.0.0.1:1/",
        extra_args=["--skip-websocket"],
    )

    assert result.returncode == 1
    witness = json.loads(result.stdout)
    assert any(failure.startswith("http_probe_failed:") for failure in witness["failures"])


def test_coord_runtime_witness_fails_on_http_missing_marker(tmp_path: Path) -> None:
    source_repo, sha = _init_source_repo(tmp_path)
    activation = _activation_worktree(source_repo, sha, tmp_path)
    systemctl = _fake_systemctl(tmp_path, activation)
    journalctl = _fake_journalctl(tmp_path, "Listening on 127.0.0.1:8765.")
    server, url = _serve_coord_marker(b"plain boot shell")
    ws_server = _FakeWebSocketServer()

    try:
        result = _run_witness(
            source_repo=source_repo,
            activation=activation,
            systemctl=systemctl,
            journalctl=journalctl,
            url=url,
            extra_args=["--websocket-url", ws_server.url],
        )
    finally:
        server.shutdown()
        ws_server.close()

    assert result.returncode == 1
    witness = json.loads(result.stdout)
    assert "http_render_missing_coordination_marker" in witness["failures"]


def test_coord_runtime_witness_fails_on_websocket_missing_render_marker(tmp_path: Path) -> None:
    source_repo, sha = _init_source_repo(tmp_path)
    activation = _activation_worktree(source_repo, sha, tmp_path)
    systemctl = _fake_systemctl(tmp_path, activation)
    journalctl = _fake_journalctl(tmp_path, "Listening on 127.0.0.1:8765.")
    server, url = _serve_coord_marker()
    ws_server = _FakeWebSocketServer(marker=False)

    try:
        result = _run_witness(
            source_repo=source_repo,
            activation=activation,
            systemctl=systemctl,
            journalctl=journalctl,
            url=url,
            extra_args=["--websocket-url", ws_server.url],
        )
    finally:
        server.shutdown()
        ws_server.close()

    assert result.returncode == 1
    witness = json.loads(result.stdout)
    assert "websocket_render_missing_coordination_marker" in witness["failures"]


def test_coord_runtime_witness_fails_on_invalid_websocket_url(tmp_path: Path) -> None:
    source_repo, sha = _init_source_repo(tmp_path)
    activation = _activation_worktree(source_repo, sha, tmp_path)
    systemctl = _fake_systemctl(tmp_path, activation)
    journalctl = _fake_journalctl(tmp_path, "Listening on 127.0.0.1:8765.")

    result = _run_witness(
        source_repo=source_repo,
        activation=activation,
        systemctl=systemctl,
        journalctl=journalctl,
        extra_args=["--skip-http", "--websocket-url", "http://127.0.0.1:8765/clog"],
    )

    assert result.returncode == 1
    witness = json.loads(result.stdout)
    assert "websocket_url_invalid:http://127.0.0.1:8765/clog" in witness["failures"]


def test_coord_runtime_witness_fails_on_websocket_non_101(tmp_path: Path) -> None:
    source_repo, sha = _init_source_repo(tmp_path)
    activation = _activation_worktree(source_repo, sha, tmp_path)
    systemctl = _fake_systemctl(tmp_path, activation)
    journalctl = _fake_journalctl(tmp_path, "Listening on 127.0.0.1:8765.")
    ws_server = _FakeWebSocketServer(status=404)

    try:
        result = _run_witness(
            source_repo=source_repo,
            activation=activation,
            systemctl=systemctl,
            journalctl=journalctl,
            extra_args=["--skip-http", "--websocket-url", ws_server.url],
        )
    finally:
        ws_server.close()

    assert result.returncode == 1
    witness = json.loads(result.stdout)
    assert "websocket_status_not_101:404" in witness["failures"]


def test_coord_runtime_witness_fails_on_websocket_accept_mismatch(tmp_path: Path) -> None:
    source_repo, sha = _init_source_repo(tmp_path)
    activation = _activation_worktree(source_repo, sha, tmp_path)
    systemctl = _fake_systemctl(tmp_path, activation)
    journalctl = _fake_journalctl(tmp_path, "Listening on 127.0.0.1:8765.")
    ws_server = _FakeWebSocketServer(accept_override=b"mismatch")

    try:
        result = _run_witness(
            source_repo=source_repo,
            activation=activation,
            systemctl=systemctl,
            journalctl=journalctl,
            extra_args=["--skip-http", "--websocket-url", ws_server.url],
        )
    finally:
        ws_server.close()

    assert result.returncode == 1
    witness = json.loads(result.stdout)
    assert "websocket_accept_mismatch" in witness["failures"]


def test_coord_runtime_witness_fails_when_websocket_connection_is_refused(
    tmp_path: Path,
) -> None:
    source_repo, sha = _init_source_repo(tmp_path)
    activation = _activation_worktree(source_repo, sha, tmp_path)
    systemctl = _fake_systemctl(tmp_path, activation)
    journalctl = _fake_journalctl(tmp_path, "Listening on 127.0.0.1:8765.")
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    host, port = sock.getsockname()
    sock.close()

    result = _run_witness(
        source_repo=source_repo,
        activation=activation,
        systemctl=systemctl,
        journalctl=journalctl,
        extra_args=["--skip-http", "--websocket-url", f"ws://{host}:{port}/clog"],
    )

    assert result.returncode == 1
    witness = json.loads(result.stdout)
    assert any(failure.startswith("websocket_probe_failed:") for failure in witness["failures"])


def test_coord_runtime_witness_fails_when_websocket_skips_path_challenge(
    tmp_path: Path,
) -> None:
    source_repo, sha = _init_source_repo(tmp_path)
    activation = _activation_worktree(source_repo, sha, tmp_path)
    systemctl = _fake_systemctl(tmp_path, activation)
    journalctl = _fake_journalctl(tmp_path, "Listening on 127.0.0.1:8765.")
    server, url = _serve_coord_marker()
    ws_server = _FakeWebSocketServer(path_challenge=False)

    try:
        result = _run_witness(
            source_repo=source_repo,
            activation=activation,
            systemctl=systemctl,
            journalctl=journalctl,
            url=url,
            extra_args=["--websocket-url", ws_server.url],
        )
    finally:
        server.shutdown()
        ws_server.close()

    assert result.returncode == 1
    witness = json.loads(result.stdout)
    assert witness["checks"]["websocket"]["render_marker_seen"] is True
    assert witness["checks"]["websocket"]["path_challenge_seen"] is False
    assert "websocket_path_challenge_missing" in witness["failures"]


def test_coord_runtime_witness_answers_websocket_path_challenge_after_marker(
    tmp_path: Path,
) -> None:
    source_repo, sha = _init_source_repo(tmp_path)
    activation = _activation_worktree(source_repo, sha, tmp_path)
    systemctl = _fake_systemctl(tmp_path, activation)
    journalctl = _fake_journalctl(tmp_path, "Listening on 127.0.0.1:8765.")
    server, url = _serve_coord_marker()
    ws_server = _FakeWebSocketServer(marker_before_challenge=True)

    try:
        result = _run_witness(
            source_repo=source_repo,
            activation=activation,
            systemctl=systemctl,
            journalctl=journalctl,
            url=url,
            extra_args=["--websocket-url", ws_server.url],
        )
    finally:
        server.shutdown()
        ws_server.close()

    assert result.returncode == 0, result.stderr
    witness = json.loads(result.stdout)
    assert witness["checks"]["websocket"]["render_marker_seen"] is True
    assert witness["checks"]["websocket"]["path_challenge_seen"] is True
    assert witness["checks"]["websocket"]["path_reply_sent"] is True
    assert ws_server.received_messages == ["7:/"]


def test_coord_runtime_witness_fails_when_systemctl_show_fails(tmp_path: Path) -> None:
    source_repo, sha = _init_source_repo(tmp_path)
    activation = _activation_worktree(source_repo, sha, tmp_path)
    systemctl = _fake_systemctl(tmp_path, activation, rc=7)
    journalctl = _fake_journalctl(tmp_path, "Listening on 127.0.0.1:8765.")

    result = _run_witness(
        source_repo=source_repo,
        activation=activation,
        systemctl=systemctl,
        journalctl=journalctl,
        extra_args=["--skip-http", "--skip-websocket"],
    )

    assert result.returncode == 1
    witness = json.loads(result.stdout)
    assert any(failure.startswith("systemctl_show_failed:") for failure in witness["failures"])


def test_coord_runtime_witness_fails_when_unit_is_not_active_running_or_successful(
    tmp_path: Path,
) -> None:
    source_repo, sha = _init_source_repo(tmp_path)
    activation = _activation_worktree(source_repo, sha, tmp_path)
    systemctl = _fake_systemctl(
        tmp_path,
        activation,
        active_state="failed",
        sub_state="dead",
        result="exit-code",
    )
    journalctl = _fake_journalctl(tmp_path, "Listening on 127.0.0.1:8765.")

    result = _run_witness(
        source_repo=source_repo,
        activation=activation,
        systemctl=systemctl,
        journalctl=journalctl,
        extra_args=["--skip-http", "--skip-websocket"],
    )

    assert result.returncode == 1
    witness = json.loads(result.stdout)
    assert "unit_not_active:failed" in witness["failures"]
    assert "unit_not_running:dead" in witness["failures"]
    assert "unit_result_not_success:exit-code" in witness["failures"]


def test_coord_runtime_witness_fails_when_execstart_does_not_use_activation_run_dev(
    tmp_path: Path,
) -> None:
    source_repo, sha = _init_source_repo(tmp_path)
    activation = _activation_worktree(source_repo, sha, tmp_path)
    systemctl = _fake_systemctl(tmp_path, activation, exec_start="/tmp/other/run-dev.sh")
    journalctl = _fake_journalctl(tmp_path, "Listening on 127.0.0.1:8765.")

    result = _run_witness(
        source_repo=source_repo,
        activation=activation,
        systemctl=systemctl,
        journalctl=journalctl,
        extra_args=["--skip-http", "--skip-websocket"],
    )

    assert result.returncode == 1
    witness = json.loads(result.stdout)
    assert "unit_execstart_not_activation_run_dev" in witness["failures"]


def test_coord_runtime_witness_fails_when_execstart_wraps_activation_run_dev(
    tmp_path: Path,
) -> None:
    source_repo, sha = _init_source_repo(tmp_path)
    activation = _activation_worktree(source_repo, sha, tmp_path)
    mutable_run_dev = tmp_path / "mutable-hapax-coord/scripts/run-dev.sh"
    mutable_run_dev.parent.mkdir(parents=True)
    mutable_run_dev.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    exec_start = (
        f"{{ path={mutable_run_dev} ; "
        f"argv[]={mutable_run_dev} --forward {activation}/scripts/run-dev.sh ; "
        "ignore_errors=no }"
    )
    systemctl = _fake_systemctl(tmp_path, activation, exec_start=exec_start)
    journalctl = _fake_journalctl(tmp_path, "Listening on 127.0.0.1:8765.")

    result = _run_witness(
        source_repo=source_repo,
        activation=activation,
        systemctl=systemctl,
        journalctl=journalctl,
        extra_args=["--skip-http", "--skip-websocket"],
    )

    assert result.returncode == 1
    witness = json.loads(result.stdout)
    assert "unit_execstart_not_activation_run_dev" in witness["failures"]


def test_coord_runtime_witness_fails_when_journalctl_fails(tmp_path: Path) -> None:
    source_repo, sha = _init_source_repo(tmp_path)
    activation = _activation_worktree(source_repo, sha, tmp_path)
    systemctl = _fake_systemctl(tmp_path, activation)
    journalctl = _fake_journalctl(tmp_path, "journalctl failed", rc=9)

    result = _run_witness(
        source_repo=source_repo,
        activation=activation,
        systemctl=systemctl,
        journalctl=journalctl,
        extra_args=["--skip-http", "--skip-websocket"],
    )

    assert result.returncode == 1
    witness = json.loads(result.stdout)
    assert any(failure.startswith("journalctl_failed:") for failure in witness["failures"])


def test_coord_runtime_witness_fails_on_clog_overflow_signature(tmp_path: Path) -> None:
    source_repo, sha = _init_source_repo(tmp_path)
    activation = _activation_worktree(source_repo, sha, tmp_path)
    systemctl = _fake_systemctl(tmp_path, activation)
    journalctl = _fake_journalctl(
        tmp_path,
        "Unhandled error in handle-new-connection: value is not of type unsigned-byte",
    )

    result = _run_witness(
        source_repo=source_repo,
        activation=activation,
        systemctl=systemctl,
        journalctl=journalctl,
        extra_args=["--skip-http", "--skip-websocket"],
    )

    assert result.returncode == 1
    witness = json.loads(result.stdout)
    assert "clog_overflow_signature_seen" in witness["failures"]
