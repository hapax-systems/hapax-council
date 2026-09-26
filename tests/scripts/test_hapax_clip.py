"""Red-first pins for hapax-clip formatting, receipts, and route refusal."""

from __future__ import annotations

import importlib.util
import json
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


def test_receipt_records_the_digest_and_not_the_content(tmp_path: Path) -> None:
    clip = load()
    path = tmp_path / "receipts.jsonl"
    secret = b"super-secret-payload"
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
    text = path.read_text()
    record = json.loads(text)
    assert record["sha256"] == clip.sha256_hex(secret)
    assert record["bytes"] == len(secret)
    assert record["target"] == "steamdeck"
    assert secret.decode() not in text
    assert "content" not in record
