"""Red-first pins for hapax-clip formatting, receipts, and route refusal."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MODULE = REPO / "scripts" / "hapax_clip.py"


def load():
    spec = importlib.util.spec_from_file_location("hapax_clip", MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PAYLOAD = b"cat <<'EOF'\necho \"quoted 'mix'\"\nEOF\n"


def test_shell_round_trip_is_byte_exact() -> None:
    clip = load()
    pasted = clip.format_shell(PAYLOAD)
    assert pasted.count("\n") >= 1
    command = [line for line in pasted.splitlines() if line.startswith("echo ")][0]
    encoded = command.split()[1]
    assert clip.shell_round_trip(encoded) == PAYLOAD
    assert "sha256=" in pasted.splitlines()[0]


def test_crlf_normalises_to_lf_and_back() -> None:
    clip = load()
    mixed = b"one\r\ntwo\nthree\r"
    assert clip.normalise_newlines(mixed, b"\n") == b"one\ntwo\nthree\n"
    assert clip.normalise_newlines(mixed, b"\r\n") == b"one\r\ntwo\r\nthree\r\n"


def test_pwsh_encoded_command_round_trips() -> None:
    clip = load()
    pasted = clip.format_pwsh(PAYLOAD)
    command = [line for line in pasted.splitlines() if "EncodedCommand" in line][0]
    encoded = command.split()[-1]
    assert clip.pwsh_round_trip(encoded) == PAYLOAD
    assert command.startswith("powershell -NoProfile -EncodedCommand ")


def test_resolver_refuses_with_a_next_action() -> None:
    clip = load()
    try:
        clip.resolve_route("missing-host", probes=[lambda _target: None])
    except clip.RouteUnavailable as exc:
        assert "Next action:" in str(exc)
    else:
        raise AssertionError("resolver returned a route")


def _record(tmp_path: Path, secret: bytes) -> dict:
    clip = load()
    path = tmp_path / "receipts.jsonl"
    clip.append_receipt(
        path,
        when="2026-09-26T00:00:00Z",
        target="steamdeck",
        route="kdeconnect",
        mode="shell",
        digest=clip.sha256_hex(secret),
        nbytes=len(secret),
        content=secret,
    )
    record = json.loads(path.read_text())
    assert set(record) == {"time", "target", "route", "mode", "sha256", "bytes"}
    assert all(value != secret.decode("utf-8", "replace") for value in record.values())
    return record


def test_receipt_records_the_digest_and_not_the_content(tmp_path: Path) -> None:
    clip = load()
    record = _record(tmp_path, b"super-secret-payload")
    assert record["sha256"] == clip.sha256_hex(b"super-secret-payload")
    assert record["bytes"] == len(b"super-secret-payload")
    assert record["target"] == "steamdeck"


def test_receipt_accepts_a_short_payload(tmp_path: Path) -> None:
    for secret in (b"e", b"true", b"ab"):
        _record(tmp_path / secret.decode(), secret)


LISTING = (
    "- steamdeck: abcdef0123456789 on 192.168.68.94 via LAN (paired and reachable)\n"
    "- bazzite: bbbbbbbbbbbbbbbb on  via  (paired)\n"
)


def _completed(
    argv: list[str], text: str | None = None, code: int = 0, stdout: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(argv, code, stdout, "share failed")


def test_kde_probe_uses_a_paired_reachable_device() -> None:
    clip = load()

    def run(argv: list[str], text: str | None = None) -> subprocess.CompletedProcess[str]:
        return _completed(argv, text, stdout=LISTING)

    route = clip.kde_probe("steamdeck", hosts=("podium",), run=run)
    assert route is not None
    assert route.kind == "kdeconnect"
    assert route.via == "podium"
    assert clip.kde_probe("bazzite", hosts=("podium",), run=run) is None


def test_push_kde_failure_names_the_next_action() -> None:
    clip = load()
    route = clip.Route("kdeconnect", "podium", "steamdeck abcdef0123456789")

    def run(argv: list[str], text: str | None = None) -> subprocess.CompletedProcess[str]:
        return _completed(argv, text, code=1)

    try:
        clip.push_kde(route, "payload", run=run)
    except clip.RouteUnavailable as exc:
        assert "Next action:" in str(exc)
    else:
        raise AssertionError("share failure returned")


def test_linux_probe_and_push_failure() -> None:
    clip = load()

    def present(argv: list[str], text: str | None = None) -> subprocess.CompletedProcess[str]:
        return _completed(argv, text, code=0)

    def missing(argv: list[str], text: str | None = None) -> subprocess.CompletedProcess[str]:
        return _completed(argv, text, code=1)

    route = clip.linux_probe("hapax-podium.local", run=present)
    assert route is not None and route.kind == "linux-clipboard"
    assert clip.linux_probe("hapax-podium.local", run=missing) is None
    try:
        clip.push_linux(route, "payload", run=missing)
    except clip.RouteUnavailable as exc:
        assert "Next action:" in str(exc)
    else:
        raise AssertionError("clipboard failure returned")
