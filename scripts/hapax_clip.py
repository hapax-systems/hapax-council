#!/usr/bin/env python3
"""Push a paste-safe payload to a tailnet clipboard.

Prior art, measured 2026-09-26:
- KDE Connect: podium is paired with steamdeck (f104689c…) and bazzite
  (ae9fd60e…). Appendix's kdeconnect daemon did not start. Talus SSH from
  appendix was refused, and from podium the host key check failed, so the
  talus Store-app CLI was not exercised.
- hapax-*-send delivers instructions into a lane session. It is not a
  clipboard.
- Fleet hosts are named in frame/FLEET-INVENTORY-vram-and-appliances.md.
  Windows Set-Clipboard on hapax-dextra round-trips inside the SSH
  session and was not shown to reach the desktop. The proven Windows
  path is KDE Connect share-text from podium to WIN-C2ANEVBHN6Q, which
  is paired and reachable. That is the same device route as steamdeck.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

NEXT_ACTION = (
    "Next action: name a paired reachable KDE Connect device, or a Linux "
    "tailnet host whose graphical session has wl-copy or xclip. Windows "
    "clipboard from non-interactive SSH is unsupported: Set-Clipboard on "
    "hapax-dextra stays inside the SSH session and was not shown to reach "
    "the desktop."
)

_DEVICE_LINE = re.compile(r"^- (?P<name>.+): (?P<id>[0-9a-f]+) on .* \((?P<state>.*)\)\s*$")


class RouteUnavailable(Exception):
    """No clipboard route exists for this target."""


@dataclass(frozen=True)
class Route:
    kind: str
    via: str
    detail: str

    def label(self) -> str:
        return f"{self.kind} via {self.via} ({self.detail})"


def sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def summary_line(payload: bytes) -> str:
    text = payload.decode("utf-8", "replace")
    first = next((line.strip() for line in text.splitlines() if line.strip()), "empty")
    collapsed = " ".join(first.split())
    if len(collapsed) > 72:
        return collapsed[:69] + "..."
    return collapsed


def format_shell(payload: bytes) -> str:
    encoded = base64.b64encode(payload).decode("ascii")
    comment = (
        f"# hapax-clip sha256={sha256_hex(payload)} bytes={len(payload)} {summary_line(payload)}"
    )
    return f"{comment}\necho {encoded} | base64 -d | bash\n"


def shell_round_trip(encoded: str) -> bytes:
    return base64.b64decode(encoded)


def format_pwsh(payload: bytes) -> str:
    script = payload.decode("utf-8")
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    comment = (
        f"# hapax-clip sha256={sha256_hex(payload)} bytes={len(payload)} {summary_line(payload)}"
    )
    return f"{comment}\npowershell -NoProfile -EncodedCommand {encoded}\n"


def pwsh_round_trip(encoded: str) -> bytes:
    return base64.b64decode(encoded).decode("utf-16le").encode("utf-8")


def normalise_newlines(payload: bytes, newline: bytes) -> bytes:
    unix = payload.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    if newline == b"\n":
        return unix
    if newline != b"\r\n":
        raise ValueError("newline must be LF or CRLF")
    return unix.replace(b"\n", b"\r\n")


def resolve_route(target: str, probes: list[Callable[[str], Route | None]]) -> Route:
    for probe in probes:
        found = probe(target)
        if found is not None:
            return found
    raise RouteUnavailable(NEXT_ACTION)


def append_receipt(
    path: Path,
    *,
    when: str,
    target: str,
    route: str,
    mode: str,
    digest: str,
    nbytes: int,
    content: bytes,
) -> None:
    record = {
        "time": when,
        "target": target,
        "route": route,
        "mode": mode,
        "sha256": digest,
        "bytes": nbytes,
    }
    # `content` is intentionally unused. The receipt is only the fields above.
    del content
    line = json.dumps(record, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)


def parse_kde_devices(listing: str) -> list[dict[str, str | bool]]:
    devices: list[dict[str, str | bool]] = []
    for raw in listing.splitlines():
        match = _DEVICE_LINE.match(raw.strip())
        if match is None:
            continue
        state = match.group("state")
        devices.append(
            {
                "name": match.group("name"),
                "id": match.group("id"),
                "paired": "paired" in state,
                "reachable": "reachable" in state,
            }
        )
    return devices


def match_device(target: str, device: dict[str, str | bool]) -> bool:
    wanted = target.casefold()
    name = str(device["name"]).casefold()
    ident = str(device["id"]).casefold()
    return wanted in (name, ident) or ident.startswith(wanted)


def render(payload: bytes, mode: str, newline: bytes) -> str:
    if mode == "raw":
        return normalise_newlines(payload, newline).decode("utf-8")
    if mode == "pwsh":
        return format_pwsh(payload)
    if mode == "shell":
        return format_shell(payload)
    raise ValueError(f"unknown mode {mode}")


def preview(payload: bytes, *, target: str, route: str, mode: str, pasted: str) -> str:
    shown = "\n".join(payload.decode("utf-8", "replace").splitlines()[:12])
    return (
        f"target: {target}\n"
        f"route: {route}\n"
        f"mode: {mode}\n"
        f"sha256: {sha256_hex(payload)}\n"
        f"bytes: {len(payload)}\n"
        f"preview:\n{shown}\n"
        f"---\n{pasted}"
    )


def _run(argv: list[str], text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        input=text,
        text=True,
        capture_output=True,
        check=False,
    )


def list_kde(host: str, run: Callable[..., subprocess.CompletedProcess[str]] = _run) -> str:
    if host == "local":
        result = run(["kdeconnect-cli", "-l"])
    else:
        result = run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", host, "kdeconnect-cli", "-l"]
        )
    if result.returncode != 0:
        return ""
    return result.stdout


def kde_probe(
    target: str,
    hosts: tuple[str, ...] = ("hapax-podium.local", "local"),
    run: Callable[..., subprocess.CompletedProcess[str]] = _run,
) -> Route | None:
    for host in hosts:
        for device in parse_kde_devices(list_kde(host, run)):
            if not device["paired"] or not device["reachable"]:
                continue
            if match_device(target, device):
                return Route("kdeconnect", host, f"{device['name']} {device['id']}")
    return None


def push_kde(
    route: Route,
    pasted: str,
    run: Callable[..., subprocess.CompletedProcess[str]] = _run,
) -> None:
    device_id = str(route.detail).split()[-1]
    command = ["kdeconnect-cli", "-d", device_id, "--share-text", pasted]
    if route.via != "local":
        command = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", route.via, *command]
    result = run(command)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RouteUnavailable(
            "Next action: the KDE Connect share failed. Confirm the device is "
            f"reachable and rerun. {detail}"
        )


def linux_probe(
    target: str, run: Callable[..., subprocess.CompletedProcess[str]] = _run
) -> Route | None:
    if " " in target or not target:
        return None
    probe = run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=8",
            target,
            "command -v wl-copy >/dev/null || command -v xclip >/dev/null",
        ]
    )
    if probe.returncode != 0:
        return None
    return Route("linux-clipboard", target, "ssh graphical clipboard")


def push_linux(
    route: Route,
    pasted: str,
    run: Callable[..., subprocess.CompletedProcess[str]] = _run,
) -> None:
    remote = (
        "runtime=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}; "
        'export XDG_RUNTIME_DIR="$runtime"; '
        'sock=$(find "$runtime" -maxdepth 1 -name "wayland-*" -type s 2>/dev/null | head -1); '
        'if [ -n "$sock" ]; then export WAYLAND_DISPLAY=$(basename "$sock"); '
        "else export WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-wayland-0}; fi; "
        "if command -v wl-copy >/dev/null; then wl-copy; "
        "else xclip -selection clipboard; fi"
    )
    result = run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", route.via, remote],
        text=pasted,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RouteUnavailable(
            "Next action: the Linux clipboard command failed. Confirm a graphical "
            f"session on {route.via} and rerun. {detail}"
        )


def deliver(route: Route, pasted: str) -> None:
    if route.kind == "kdeconnect":
        push_kde(route, pasted)
        return
    if route.kind == "linux-clipboard":
        push_linux(route, pasted)
        return
    raise RouteUnavailable(NEXT_ACTION)


def newline_for(mode: str, route: Route) -> bytes:
    if mode != "raw":
        return b"\n"
    if route.kind == "kdeconnect" and "win" in route.detail.casefold():
        return b"\r\n"
    return b"\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hapax-clip",
        description=(
            "Push a paste-safe payload. Route (a) is KDE Connect share-text. "
            "Route (b), SSH into a graphical session (wl-copy or xclip), is "
            "not live-proven: it ships fail-closed and refuses with a next "
            "action when no compositor socket exists."
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--shell", action="store_true", help="paste-safe POSIX line (default)")
    mode.add_argument("--pwsh", action="store_true", help="PowerShell EncodedCommand")
    mode.add_argument("--raw", action="store_true", help="verbatim text, newlines normalised")
    parser.add_argument(
        "--receipt", type=Path, default=Path.home() / ".cache/hapax/hapax-clip.jsonl"
    )
    parser.add_argument("target")
    parser.add_argument("file", nargs="?", default="-")
    args = parser.parse_args(argv)
    chosen = "pwsh" if args.pwsh else "raw" if args.raw else "shell"
    if args.file == "-":
        payload = sys.stdin.buffer.read()
    else:
        try:
            payload = Path(args.file).read_bytes()
        except OSError as exc:
            print(
                "Next action: pass a readable file, or '-' to read stdin. "
                f"Could not read {args.file}: {exc}",
                file=sys.stderr,
            )
            return 1
    try:
        route = resolve_route(args.target, [kde_probe, linux_probe])
    except RouteUnavailable as exc:
        print(exc, file=sys.stderr)
        return 1
    pasted = render(payload, chosen, newline_for(chosen, route))
    print(preview(payload, target=args.target, route=route.label(), mode=chosen, pasted=pasted))
    try:
        deliver(route, pasted)
    except RouteUnavailable as exc:
        print(exc, file=sys.stderr)
        return 1
    append_receipt(
        args.receipt,
        when=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        target=args.target,
        route=route.label(),
        mode=chosen,
        digest=sha256_hex(payload),
        nbytes=len(payload),
        content=payload,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
