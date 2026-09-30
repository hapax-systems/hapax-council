"""Clipboard authority, literal-text, privacy and bounded transport regressions."""

import base64
import json
import os
import socket
import struct
import sys
import time
import uuid
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import hapax_clip as clip

ENDPOINT = str(uuid.uuid4())
EPOCH = str(uuid.uuid4())
PAYLOAD = "λ 🔒\r\n' \" ` $(touch /tmp/never) ;\n".encode()
HOST_KEY = (
    "ssh-ed25519 "
    + base64.b64encode(b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00 " + bytes(32)).decode()
)


def endpoint():
    return dict(
        platform="wayland",
        host="100.64.0.1",  # pragma: allowlist secret -- synthetic routing fixture
        user="operator",
        host_key=HOST_KEY,
        endpoint=ENDPOINT,
        principal=str(os.getuid()),
    )


def request(data=PAYLOAD):
    return dict(
        v=1,
        id=str(uuid.uuid4()),
        op="set",
        endpoint=ENDPOINT,
        session="4",
        epoch=EPOCH,
        bytes=len(data),
        sha256=clip.digest(data),
        data=base64.b64encode(data).decode(),
    )


def ack(q):
    return {k: q[k] for k in ("v", "id", "endpoint", "session", "epoch", "bytes", "sha256")} | {
        "principal": str(os.getuid()),
        "history_excluded": True,
    }


@pytest.mark.parametrize("data", [PAYLOAD, b"", b"a\r\nb\nc\r", b"a" * clip.MAX_TEXT])
def test_literal_default_and_protocol_exact(data):
    assert clip.render(data) == data
    assert (
        clip.validate_request(clip.decode_json(clip.encode_json(request(data))), ENDPOINT) == data
    )


@pytest.mark.parametrize("data", [b"\xff", b"a\x00b", b"a" * (clip.MAX_TEXT + 1), b"\xed\xa0\x80"])
def test_unrepresentable_or_oversized_text_refused(data):
    with pytest.raises(clip.ClipError):
        clip.render(data)


@pytest.mark.parametrize(
    "change",
    [
        dict(v=True),
        dict(v=2),
        dict(id="bad"),
        dict(epoch="bad"),
        dict(op="exec"),
        dict(endpoint=str(uuid.uuid4())),
        dict(session="-oProxyCommand=x"),
        dict(bytes=True),
        dict(bytes=-1),
        dict(bytes=999),
        dict(sha256="bad"),
        dict(data="%%%"),
        dict(data="YWJj\n"),
        dict(extra="ignored"),
    ],
)
def test_protocol_refuses_malformed_identity_or_integrity(change):
    with pytest.raises(clip.ClipError):
        clip.validate_request(request() | change, ENDPOINT)


@pytest.mark.parametrize("raw", [b'{"v":1,"v":1}', b"[]", b"null", b"\xff", b"{", b"a" * 1500001])
def test_json_refuses_duplicates_nonobjects_or_oversize(raw):
    with pytest.raises(clip.ClipError):
        clip.decode_json(raw)


@pytest.mark.parametrize(
    "change",
    [
        dict(id=str(uuid.uuid4())),
        dict(endpoint=str(uuid.uuid4())),
        dict(principal="other"),
        dict(session="5"),
        dict(epoch=str(uuid.uuid4())),
        dict(bytes=0),
        dict(sha256="bad"),
        dict(history_excluded=False),
        dict(extra="unsafe"),
    ],
)
def test_ack_bound_to_enrollment_session_nonce_and_actual_bytes(change):
    q = request()
    good = ack(q)
    clip.validate_ack(good, q, endpoint(), good)
    with pytest.raises(clip.ClipError):
        clip.validate_ack(good | change, q, endpoint(), good)


def test_describe_is_not_a_write():
    q = dict(v=1, id=str(uuid.uuid4()), op="describe", endpoint=ENDPOINT)
    assert clip.validate_request(q, ENDPOINT) is None


@pytest.mark.parametrize(
    "change",
    [
        dict(host="-oProxyCommand=x"),
        dict(host="a;touch /tmp/x"),
        dict(host="a b"),
        dict(user="-root"),
        dict(user="x;bad"),
        dict(principal="no"),
        dict(endpoint="not-enrolled"),
        dict(platform="kdeconnect"),
        dict(host_key="ssh-rsa AAAA"),
        dict(identity_file="relative"),
        dict(extra=True),
    ],
)
def test_enrollment_rejects_option_shell_injection_or_unsupported_binding(tmp_path, change):
    path = tmp_path / "enrollment.json"
    path.write_text(json.dumps(dict(v=1, endpoints={"client": endpoint() | change})))
    path.chmod(384)
    with pytest.raises((clip.ClipError, OSError)):
        clip.load_endpoints(path)


def test_route_uses_pinned_key_and_fixed_commands_no_payload_argv(tmp_path):
    for platform in ("wayland", "windows"):
        argv = clip.ssh_argv(endpoint() | {"platform": platform}, tmp_path / "pin")
        joined = " ".join(argv)
        assert "StrictHostKeyChecking=yes" in joined
        assert "GlobalKnownHostsFile=/dev/null" in joined
        assert "HostKeyAlias=hapax-clip-" + ENDPOINT in joined
        assert PAYLOAD.decode() not in joined
        assert base64.b64encode(PAYLOAD).decode() not in joined
        assert "ForwardAgent=no" in joined


def test_delivery_checks_two_independent_request_ids_and_transports_only_stdin(monkeypatch):
    seen = []

    def run(argv, raw):
        q = clip.decode_json(raw[4:])
        seen.append((argv, q))
        reply = dict(
            v=1, id=q["id"], endpoint=ENDPOINT, session="4", epoch=EPOCH, principal=str(os.getuid())
        )
        if q["op"] == "set":
            assert clip.validate_request(q, ENDPOINT) == PAYLOAD
            reply.update(bytes=len(PAYLOAD), sha256=clip.digest(PAYLOAD), history_excluded=True)
        return clip.encode_json(reply)

    monkeypatch.setattr(clip, "bounded_run", run)
    assert clip.deliver(endpoint(), PAYLOAD)["sha256"] == clip.digest(PAYLOAD)
    assert [q["op"] for _, q in seen] == ["describe", "set"]
    assert seen[0][1]["id"] != seen[1][1]["id"]
    assert all((PAYLOAD.decode() not in " ".join(argv) for argv, _ in seen))


def test_receipt_private_and_contains_no_payload(tmp_path):
    path = tmp_path / "private" / "receipt.jsonl"
    record = {k: v for k, v in ack(request()).items() if k != "data"}
    clip.receipt(path, record)
    assert json.loads(path.read_text()) == record
    assert PAYLOAD not in path.read_bytes()
    assert path.stat().st_mode & 511 == 384
    assert path.parent.stat().st_mode & 511 == 448


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "public"])
def test_unsafe_receipt_file_refused(tmp_path, kind):
    directory = tmp_path / "private"
    directory.mkdir(mode=448)
    target = directory / "other"
    target.write_bytes(b"untouched")
    target.chmod(384)
    path = directory / "receipt"
    if kind == "symlink":
        path.symlink_to(target)
    elif kind == "hardlink":
        os.link(target, path)
    else:
        path.write_bytes(b"untouched")
        path.chmod(420)
    with pytest.raises((clip.ClipError, OSError)):
        clip.receipt(path, {"v": 1})
    assert target.read_bytes() == b"untouched"


def test_private_enrollment_symlink_refused(tmp_path):
    target = tmp_path / "target"
    target.write_text("{}")
    target.chmod(384)
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(OSError):
        clip.read_private(link)


def test_bounded_transport_roundtrip_and_no_stderr_leak():
    program = 'import sys; d=sys.stdin.buffer.read(); sys.stderr.write("secret"); sys.stdout.buffer.write(d)'
    assert clip.bounded_run([sys.executable, "-c", program], PAYLOAD, maximum=1000) == PAYLOAD


@pytest.mark.parametrize(
    "program,data,maximum",
    [
        ("import time; time.sleep(3)", b"a" * clip.MAX_REQUEST, 100),
        ('import sys; sys.stdout.buffer.write(b"a"*1000000)', b"", 100),
        ('import sys; sys.stderr.write("secret"); sys.exit(1)', b"", 100),
    ],
    ids=["blocked-stdin", "overflow", "error"],
)
def test_transport_timeout_overflow_failure_bounded_without_payload_error(program, data, maximum):
    before = time.monotonic()
    with pytest.raises(clip.ClipError) as error:
        clip.bounded_run([sys.executable, "-c", program], data, maximum=maximum, timeout=0.15)
    assert time.monotonic() - before < 1.5
    assert "secret" not in str(error.value)


def test_framed_ipc_truncation_and_oversize_refused():
    for raw in (struct.pack("!I", 10000000), struct.pack("!I", 9) + b"a"):
        a, b = socket.socketpair()
        with a, b:
            a.settimeout(0.1)
            b.sendall(raw)
            b.shutdown(socket.SHUT_WR)
            with pytest.raises(clip.ClipError):
                clip.read_frame(a, 100)


def test_framed_ipc_roundtrip():
    a, b = socket.socketpair()
    with a, b:
        clip.send_frame(a, PAYLOAD)
        assert clip.read_frame(b, 1000) == PAYLOAD


def test_cli_failures_do_not_print_payload_or_encoding(tmp_path, capsys):
    path = tmp_path / "input"
    path.write_bytes(PAYLOAD)
    assert clip.main(["unknown", str(path), "--config", str(tmp_path / "missing")]) == 1
    result = capsys.readouterr()
    assert "Next action:" in result.err and (not result.out)
    assert (
        PAYLOAD.decode() not in result.err and base64.b64encode(PAYLOAD).decode() not in result.err
    )


def test_explicit_wrapping_never_adds_preview():
    shell = clip.render(PAYLOAD, "shell")
    pwsh = clip.render(PAYLOAD, "pwsh")
    assert PAYLOAD not in shell and PAYLOAD not in pwsh
    assert base64.b64decode(shell.decode().split("'")[3]) == PAYLOAD
    assert base64.b64decode(pwsh.split()[-1]).decode("utf-16le").encode() == PAYLOAD


def test_framed_stdin_finishes_without_waiting_for_eof():
    import io

    raw = clip.encode_json({"op": "describe"})
    handle = io.BytesIO(clip.encode_frame(raw) + b"untouched-after-frame")
    assert clip.read_input_frame(handle) == raw
    assert handle.read() == b"untouched-after-frame"
    for broken in (b"\x00", struct.pack("!I", clip.MAX_REQUEST + 1), struct.pack("!I", 10) + b"{}"):
        with pytest.raises(clip.ClipError):
            clip.read_input_frame(io.BytesIO(broken))


@pytest.mark.parametrize("change", [{"v": True}, {"bytes": True}, {"bytes": 1.0}])
def test_ack_rejects_boolean_or_float_protocol_integers(change):
    q = request(b"x")
    with pytest.raises(clip.ClipError):
        clip.validate_ack(ack(q) | change, q, endpoint())


def test_successful_cli_receipt_omits_payload_and_content_fingerprint(
    tmp_path, monkeypatch, capsys
):
    source = tmp_path / "input"
    source.write_bytes(PAYLOAD)
    output = tmp_path / "private" / "receipt.jsonl"
    monkeypatch.setattr(clip, "load_endpoints", lambda path: {"client": endpoint()})

    def deliver(item, data):
        return ack(request(data))

    monkeypatch.setattr(clip, "deliver", deliver)
    assert clip.main(["client", str(source), "--receipt", str(output)]) == 0
    public = capsys.readouterr().out
    assert "sha256" not in public and clip.digest(PAYLOAD) not in public
    assert PAYLOAD.decode() not in public and base64.b64encode(PAYLOAD).decode() not in public
    assert "sha256" not in output.read_text()


def test_launcher_symlink_resolves_accepted_source_not_local_copy(tmp_path):
    import subprocess

    launcher = tmp_path / "hapax-clip"
    launcher.symlink_to(SCRIPTS / "hapax-clip")
    result = subprocess.run([str(launcher), "--help"], capture_output=True, timeout=5)
    assert result.returncode == 0 and b"Exact enrolled name" in result.stdout
    assert not (tmp_path / "hapax_clip.py").exists()


@pytest.fixture
def actual_clipboard_predecessor():
    import subprocess
    import types

    commit = "2c94fef2741ef9e0f0fca7b45f08eb3f4b20986a"  # pragma: allowlist secret -- public predecessor Git commit
    result = subprocess.run(
        ["git", "show", commit + ":scripts/hapax_clip.py"],
        cwd=SCRIPTS.parent,
        capture_output=True,
        timeout=5,
    )
    if result.returncode:
        pytest.skip("Actual PR4796 Git object absent; fetch predecessor history to reproduce")
    module = types.ModuleType("actual_clipboard_predecessor")
    sys.modules[module.__name__] = module
    try:
        exec(compile(result.stdout, "git:" + commit, "exec"), module.__dict__)
        yield module
    finally:
        sys.modules.pop(module.__name__, None)


def test_actual_predecessor_changed_mixed_newlines(actual_clipboard_predecessor):
    old = actual_clipboard_predecessor
    assert old.render(PAYLOAD, "raw", b"\n").encode() != PAYLOAD
    assert clip.render(PAYLOAD) == PAYLOAD


def test_actual_predecessor_default_wrapped_and_disclosed_input(
    actual_clipboard_predecessor, tmp_path, monkeypatch, capsys
):
    old = actual_clipboard_predecessor
    source = tmp_path / "nonsecret-fixture"
    source.write_bytes(PAYLOAD)
    captured = []
    monkeypatch.setattr(
        old, "resolve_route", lambda *args: old.Route("kdeconnect", "local", "fixture")
    )
    monkeypatch.setattr(old, "deliver", lambda route, text: captured.append(text.encode()))
    assert old.main(["fixture", str(source), "--receipt", str(tmp_path / "old.jsonl")]) == 0
    public = capsys.readouterr().out
    assert captured != [PAYLOAD]
    assert clip.digest(PAYLOAD) in public
    assert base64.b64encode(PAYLOAD).decode() in public
    assert clip.render(PAYLOAD) == PAYLOAD


def test_actual_predecessor_receipt_followed_symlink(actual_clipboard_predecessor, tmp_path):
    old = actual_clipboard_predecessor
    target = tmp_path / "owned-fixture"
    target.write_bytes(b"unchanged")
    target.chmod(0o600)
    link = tmp_path / "receipt"
    link.symlink_to(target)
    old.append_receipt(
        link,
        when="fixture",
        target="fixture",
        route="fixture",
        mode="raw",
        digest=clip.digest(PAYLOAD),
        nbytes=len(PAYLOAD),
        content=PAYLOAD,
    )
    assert target.read_bytes() != b"unchanged"
    target.write_bytes(b"unchanged")
    with pytest.raises((clip.ClipError, OSError)):
        clip.receipt(link, {"v": 1})
    assert target.read_bytes() == b"unchanged"


def test_named_pipe_receipt_refused_without_blocking(tmp_path):
    import subprocess

    path = tmp_path / "receipt-fifo"
    os.mkfifo(path, 0o600)
    program = """import sys
from pathlib import Path
import hapax_clip as clip
try:
    clip.receipt(Path(sys.argv[1]), {"v": 1})
except (clip.ClipError, OSError):
    raise SystemExit(0)
raise SystemExit(1)
"""
    child = subprocess.Popen(
        [sys.executable, "-c", program, str(path)],
        env=dict(os.environ, PYTHONPATH=str(SCRIPTS)),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert child.wait(timeout=1) == 0
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=1)
