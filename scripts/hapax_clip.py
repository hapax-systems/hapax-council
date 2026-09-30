#!/usr/bin/env python3
"""Deliver literal text to explicitly enrolled, active operator desktops.

Existing operator SSH authority is not an execution lease for untrusted jobs.
Payloads travel on stdin and framed local IPC only; receipts contain metadata.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import selectors
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

MAX_TEXT = 1048576
MAX_REQUEST = 1500000
MAX_REPLY = 8192
TIMEOUT = 12
VERSION = 1
SAFE_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}\Z")
SAFE_HOST = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,253}\Z")
SID = re.compile(r"S-1-[0-9]+(?:-[0-9]+)+\Z")


class ClipError(Exception):
    """Safe error text never interpolates payload or subprocess output."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def text_bytes(data: bytes) -> bytes:
    if len(data) > MAX_TEXT:
        raise ClipError("Text exceeds the 1 MiB limit.")
    try:
        data.decode("utf-8", "strict")
    except UnicodeError:
        raise ClipError("Text must be valid UTF-8.") from None
    if b"\0" in data:
        raise ClipError("NUL cannot round-trip through native text clipboards.")
    return data


def render(data: bytes, mode: str = "raw") -> bytes:
    text_bytes(data)
    if mode == "raw":
        return data
    # Explicit formatting puts a command on the clipboard; it never executes it.
    if mode == "shell":
        encoded = base64.b64encode(data).decode("ascii")
        result = f"printf '%s' '{encoded}' | base64 -d | bash\n".encode()
    elif mode == "pwsh":
        encoded = base64.b64encode(data.decode().encode("utf-16le")).decode("ascii")
        result = f"powershell -NoProfile -EncodedCommand {encoded}\n".encode()
    else:
        raise ClipError("Unknown formatting mode.")
    return text_bytes(result)


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ClipError("Duplicate protocol field.")
        result[key] = value
    return result


def decode_json(raw: bytes, maximum: int = MAX_REQUEST) -> dict:
    if len(raw) > maximum:
        raise ClipError("Protocol frame exceeds its limit.")
    try:
        result = json.loads(raw, object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError):
        raise ClipError("Malformed protocol frame.") from None
    if not isinstance(result, dict):
        raise ClipError("Protocol frame must be an object.")
    return result


def encode_json(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("ascii")


def encode_frame(raw: bytes) -> bytes:
    if len(raw) > MAX_REQUEST:
        raise ClipError("Protocol frame exceeds its limit.")
    return struct.pack("!I", len(raw)) + raw


def read_input_frame(handle) -> bytes:
    header = handle.read(4)
    if len(header) != 4:
        raise ClipError("Protocol frame header is incomplete.")
    size = struct.unpack("!I", header)[0]
    if size > MAX_REQUEST:
        raise ClipError("Protocol frame exceeds its limit.")
    raw = handle.read(size)
    if len(raw) != size:
        raise ClipError("Protocol frame is incomplete.")
    return raw


def valid_uuid(value: object) -> bool:
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def validate_request(request: dict, endpoint: str) -> bytes | None:
    fields = {"v", "id", "op", "endpoint"}
    if request.get("op") == "set":
        fields |= {"session", "epoch", "data", "bytes", "sha256"}
    if set(request) != fields or type(request.get("v")) is not int:
        raise ClipError("Unexpected protocol fields.")
    if request["v"] != VERSION or not valid_uuid(request["id"]):
        raise ClipError("Unsupported protocol identity.")
    if request["endpoint"] != endpoint:
        raise ClipError("Endpoint enrollment does not match.")
    if request["op"] == "describe":
        return None
    if request["op"] != "set" or not valid_uuid(request.get("epoch")):
        raise ClipError("Unsupported clipboard operation.")
    if not isinstance(request["session"], str) or not SAFE_NAME.fullmatch(request["session"]):
        raise ClipError("Invalid desktop session binding.")
    if type(request["bytes"]) is not int or not 0 <= request["bytes"] <= MAX_TEXT:
        raise ClipError("Invalid text size.")
    try:
        if not isinstance(request["data"], str) or len(request["data"]) > 1398104:
            raise ValueError
        data = base64.b64decode(request["data"], validate=True)
    except (ValueError, UnicodeError):
        raise ClipError("Invalid text encoding.") from None
    text_bytes(data)
    if request["bytes"] != len(data) or request["sha256"] != digest(data):
        raise ClipError("Text integrity does not match.")
    return data


def private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ClipError("Private directory ownership or permissions are unsafe.")


def read_private(path: Path, maximum: int = MAX_REQUEST) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ClipError("Private file ownership or permissions are unsafe.")
        return handle.read(maximum + 1)


def receipt(path: Path, record: dict) -> None:
    private_directory(path.parent)
    fd = os.open(
        path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600
    )
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
            or info.st_nlink != 1
        ):
            raise ClipError("Receipt file ownership or permissions are unsafe.")
        os.write(fd, encode_json(record) + b"\n")
    finally:
        os.close(fd)


def bounded_run(
    argv: list[str], data: bytes = b"", *, maximum: int = MAX_REPLY, timeout: float = TIMEOUT
) -> bytes:
    """Bound output and time, including a blocked stdin writer."""
    process = subprocess.Popen(
        argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )
    output = bytearray()
    deadline = time.monotonic() + timeout
    try:
        assert process.stdin is not None and process.stdout is not None
        with selectors.DefaultSelector() as selector:
            for stream in (process.stdin, process.stdout):
                os.set_blocking(stream.fileno(), False)
            selector.register(process.stdout, selectors.EVENT_READ, "out")
            remaining = memoryview(data)
            if remaining:
                selector.register(process.stdin, selectors.EVENT_WRITE, "in")
            else:
                process.stdin.close()
            while selector.get_map():
                left = deadline - time.monotonic()
                if left <= 0:
                    raise ClipError("Clipboard transport timed out.")
                for key, _event in selector.select(left):
                    if key.data == "in":
                        try:
                            count = os.write(key.fd, remaining[:65536])
                        except BrokenPipeError:
                            raise ClipError("Clipboard transport closed its input.") from None
                        remaining = remaining[count:]
                        if not remaining:
                            selector.unregister(key.fileobj)
                            process.stdin.close()
                    else:
                        chunk = os.read(key.fd, min(65536, maximum + 1 - len(output)))
                        if not chunk:
                            selector.unregister(key.fileobj)
                        output.extend(chunk)
                        if len(output) > maximum:
                            raise ClipError("Clipboard transport exceeded its output limit.")
        process.wait(timeout=max(0.001, deadline - time.monotonic()))
        if process.returncode:
            raise ClipError("Clipboard transport refused the request.")
        return bytes(output)
    except subprocess.TimeoutExpired:
        raise ClipError("Clipboard transport timed out.") from None
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        for stream in (process.stdin, process.stdout):
            if stream is not None:
                stream.close()


def read_frame(stream: socket.socket, maximum: int) -> bytes:
    deadline = time.monotonic() + (stream.gettimeout() or TIMEOUT)

    def exact(size: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < size:
            left = deadline - time.monotonic()
            if left <= 0:
                raise ClipError("Clipboard IPC timed out.")
            stream.settimeout(left)
            chunk = stream.recv(size - len(chunks))
            if not chunk:
                raise ClipError("Clipboard IPC ended before its frame.")
            chunks.extend(chunk)
        return bytes(chunks)

    size = struct.unpack("!I", exact(4))[0]
    if size > maximum:
        raise ClipError("Clipboard IPC frame exceeds its limit.")
    return exact(size)


def send_frame(stream: socket.socket, raw: bytes) -> None:
    stream.sendall(struct.pack("!I", len(raw)) + raw)


def socket_path() -> Path:
    return Path(f"/run/user/{os.getuid()}/hapax-clipboard/endpoint.sock")


def local_receive(raw: bytes) -> bytes:
    path = socket_path()
    private_directory(path.parent)
    info = path.lstat()
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ClipError("Desktop endpoint socket is unsafe.")
    with socket.socket(socket.AF_UNIX) as stream:
        stream.settimeout(TIMEOUT)
        stream.connect(str(path))
        send_frame(stream, raw)
        return read_frame(stream, MAX_REPLY)


def load_endpoints(path: Path) -> dict:
    config = decode_json(read_private(path))
    if set(config) != {"v", "endpoints"} or type(config["v"]) is not int or config["v"] != VERSION:
        raise ClipError("Invalid endpoint enrollment file.")
    if not isinstance(config["endpoints"], dict):
        raise ClipError("Invalid endpoint enrollment entries.")
    for name, item in config["endpoints"].items():
        if not SAFE_NAME.fullmatch(name) or not isinstance(item, dict):
            raise ClipError("Invalid endpoint enrollment name.")
        fields = {"platform", "host", "user", "host_key", "endpoint", "principal"}
        if set(item) not in (fields, fields | {"identity_file"}):
            raise ClipError("Invalid endpoint enrollment fields.")
        if item["platform"] not in ("wayland", "windows"):
            raise ClipError("Unsupported enrolled platform.")
        if not isinstance(item["host"], str) or not SAFE_HOST.fullmatch(item["host"]):
            raise ClipError("Invalid enrolled SSH host.")
        if not isinstance(item["user"], str) or not SAFE_NAME.fullmatch(item["user"]):
            raise ClipError("Invalid enrolled SSH user.")
        if not valid_uuid(item["endpoint"]):
            raise ClipError("Invalid enrolled endpoint identity.")
        try:
            algorithm, encoded = item["host_key"].split()
            if algorithm != "ssh-ed25519" or len(base64.b64decode(encoded, validate=True)) != 51:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise ClipError("Invalid enrolled public host key.") from None
        principal = item["principal"]
        if not isinstance(principal, str) or not (
            principal.isdecimal() if item["platform"] == "wayland" else SID.fullmatch(principal)
        ):
            raise ClipError("Invalid enrolled desktop principal.")
        if "identity_file" in item:
            identity = item["identity_file"]
            if not isinstance(identity, str) or not Path(identity).is_absolute():
                raise ClipError("SSH identity binding must be an absolute path.")
            read_private(Path(identity), maximum=16384)
    return config["endpoints"]


def ssh_argv(endpoint: dict, known_hosts: Path) -> list[str]:
    result = [
        "ssh",
        "-F",
        "/dev/null",
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "ConnectTimeout=6",
        "-o",
        "ServerAliveInterval=3",
        "-o",
        "ServerAliveCountMax=2",
        "-o",
        "ClearAllForwardings=yes",
        "-o",
        "ForwardAgent=no",
        "-o",
        "ForwardX11=no",
        "-o",
        "ControlMaster=no",
        "-o",
        "GlobalKnownHostsFile=/dev/null",
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        "-o",
        f"HostKeyAlias=hapax-clip-{endpoint['endpoint']}",
        "-o",
        "HostKeyAlgorithms=ssh-ed25519",
    ]
    if "identity_file" in endpoint:
        result += ["-o", "IdentitiesOnly=yes", "-i", endpoint["identity_file"]]
    result += ["-l", endpoint["user"], endpoint["host"]]
    if endpoint["platform"] == "wayland":
        result += ["~/.local/bin/hapax-clip --receive"]
    else:
        # Native stdin reader avoids PowerShell host input prefetch/serialization.
        result += [
            'cmd.exe /d /s /c ""%LOCALAPPDATA%\\Hapax\\Clipboard\\current\\hapax-clip-windows.exe" --client"'
        ]
    return result


def validate_ack(reply: dict, request: dict, endpoint: dict, described: dict | None = None) -> None:
    fields = {"v", "id", "endpoint", "session", "epoch", "principal"}
    if request["op"] == "set":
        fields |= {"bytes", "sha256", "history_excluded"}
    if set(reply) != fields or type(reply.get("v")) is not int or reply.get("v") != VERSION:
        raise ClipError("Destination did not acknowledge the operation.")
    if any(reply.get(k) != request[k] for k in ("id", "endpoint")):
        raise ClipError("Destination acknowledgement identity does not match.")
    if reply["principal"] != endpoint["principal"] or not valid_uuid(reply["epoch"]):
        raise ClipError("Destination desktop principal does not match enrollment.")
    if not isinstance(reply["session"], str) or not SAFE_NAME.fullmatch(reply["session"]):
        raise ClipError("Destination desktop session is invalid.")
    if described is not None:
        if any(reply[k] != described[k] for k in ("session", "epoch", "principal")):
            raise ClipError("Destination desktop changed during delivery.")
    if request["op"] == "set":
        if type(reply["bytes"]) is not int:
            raise ClipError("Destination clipboard readback size is invalid.")
        if any(reply[k] != request[k] for k in ("bytes", "sha256")):
            raise ClipError("Destination clipboard readback did not match.")
        if reply["history_excluded"] is not True:
            raise ClipError("Destination did not exclude native clipboard history.")


def deliver(endpoint: dict, data: bytes) -> dict:
    with tempfile.TemporaryDirectory(prefix="hapax-clip-pin-") as directory:
        known = Path(directory) / "known_hosts"
        known.write_text(f"hapax-clip-{endpoint['endpoint']} {endpoint['host_key']}\n")
        known.chmod(0o600)
        argv = ssh_argv(endpoint, known)
        request = {
            "v": VERSION,
            "id": str(uuid.uuid4()),
            "op": "describe",
            "endpoint": endpoint["endpoint"],
        }
        described = decode_json(bounded_run(argv, encode_frame(encode_json(request))), MAX_REPLY)
        validate_ack(described, request, endpoint)
        request = {
            "v": VERSION,
            "id": str(uuid.uuid4()),
            "op": "set",
            "endpoint": endpoint["endpoint"],
            "session": described["session"],
            "epoch": described["epoch"],
            "bytes": len(data),
            "sha256": digest(data),
            "data": base64.b64encode(data).decode("ascii"),
        }
        reply = decode_json(bounded_run(argv, encode_frame(encode_json(request))), MAX_REPLY)
        validate_ack(reply, request, endpoint, described)
        return reply


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?", help="Exact enrolled name; no auto-current guess")
    parser.add_argument("file", nargs="?", default="-", help="UTF-8 file or bounded stdin (-)")
    parser.add_argument(
        "--config", type=Path, default=Path.home() / ".config/hapax/clipboard-endpoints.json"
    )
    modes = parser.add_mutually_exclusive_group()
    for mode in ("raw", "shell", "pwsh"):
        modes.add_argument("--" + mode, action="store_const", const=mode, dest="mode")
    parser.set_defaults(mode="raw")
    parser.add_argument("--receipt", type=Path, help="Optional private metadata-only JSONL")
    parser.add_argument("--receive", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.receive:
            if args.target or args.receipt or args.mode != "raw":
                raise ClipError("Receiver arguments are invalid.")
            raw = read_input_frame(sys.stdin.buffer)
            decode_json(raw)
            sys.stdout.buffer.write(local_receive(raw) + b"\n")
            return 0
        if not args.target:
            raise ClipError("Name an explicitly enrolled desktop target.")
        if args.file == "-":
            data = sys.stdin.buffer.read(MAX_TEXT + 1)
        else:
            with Path(args.file).open("rb") as handle:
                data = handle.read(MAX_TEXT + 1)
        data = render(data, args.mode)
        endpoints = load_endpoints(args.config)
        if args.target not in endpoints:
            raise ClipError("No exact endpoint enrollment exists for this target.")
        reply = deliver(endpoints[args.target], data)
        record = {
            "time": datetime.now(UTC).isoformat(),
            "target": args.target,
            "mode": args.mode,
            "delivery": "acknowledged",
            # Payload digests are checked in memory, not kept in transcripts or
            # receipts where a low-entropy secret could be guessed offline.
            **{key: value for key, value in reply.items() if key != "sha256"},
        }
        if args.receipt:
            try:
                receipt(args.receipt, record)
            except (ClipError, OSError):
                print(encode_json(record).decode())
                print(
                    "Clipboard delivery was acknowledged, but its metadata receipt "
                    "could not be saved. Next action: repair the private receipt path; "
                    "retain this acknowledgement without repeating the clipboard write.",
                    file=sys.stderr,
                )
                return 2
        print(encode_json(record).decode())
        return 0
    except (ClipError, OSError, TimeoutError, ValueError, TypeError):
        print(
            "Clipboard delivery failed. Next action: check enrollment, active unlocked "
            "desktop endpoint and bounded UTF-8 input; retry explicitly.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
