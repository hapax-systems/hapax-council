"""Offline terminal fixture, not Codex: record real tmux input and submit on CR.

Models only the reported composer boundary. It requests modifyOtherKeys, never
runs captured text, contacts a provider, or launches a model. Native Codex and
installed-lane acceptance remain separate observations.
"""

import json
import os
import re
import sys
import tty
from pathlib import Path

root = Path(sys.argv[1])
mode = sys.argv[2]
extended = sys.argv[3] == "extended"
tty.setraw(sys.stdin.fileno())
if extended:
    sys.stdout.write("\x1b[>4;2m")
composer = ""
working = False
returns = 0
pending = b""


def draw():
    sys.stdout.write("\x1b[2J\x1b[H" + ("Working (fixture)" if working else "Idle (fixture)"))
    sys.stdout.write("\r\n\u203a " + composer)
    sys.stdout.flush()


draw()
while True:
    chunk = os.read(sys.stdin.fileno(), 4096)
    if not chunk:
        break
    with (root / "wire.bin").open("ab") as stream:
        stream.write(chunk)
    pending += chunk
    while pending:
        if pending.startswith(b"\x1b"):
            match = re.match(rb"\x1b\[[0-9;]*[a-zA-Z~]", pending)
            if match is None:
                break
            pending = pending[match.end() :]
            continue
        char, pending = pending[:1], pending[1:]
        if char == b"\r":
            returns += 1
            if mode == "never-submit" or (mode == "drop-first" and returns == 1):
                continue
            if composer:
                (root / "submitted.json").write_text(json.dumps(composer))
                composer = ""
                working = True
                if mode != "no-ack":
                    (root / "ack").write_text("fixture-token\n")
        elif char == b"\x15":
            composer = ""
        else:
            composer += char.decode("ascii")
    draw()
