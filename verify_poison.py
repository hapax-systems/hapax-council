#!/usr/bin/env python3
"""For each payload: run under bash from START (exists), targeting MISSING dir.
A trailing `pwd` marks where the later statement ran. If it prints START, the
failed cd poisoned the scope (later cmd ran in WRONG dir)."""

import json
import os
import subprocess
import tempfile

base = tempfile.mkdtemp(prefix="cdguard_")
START = os.path.join(base, "start")
os.makedirs(START)
MISS = os.path.join(base, "missing_nope")  # intentionally NOT created
GUARD = "/data/cache/hapax/scratch/cd-guard/hooks/scripts/unguarded_cd_guard.py"


def analyze(cmd):
    p = subprocess.run(
        ["python3", GUARD],
        input=json.dumps({"tool_input": {"command": cmd}}),
        capture_output=True,
        text=True,
    )
    return (
        "block" if p.returncode == 2 else ("allow" if p.returncode == 0 else f"err{p.returncode}")
    )


def run_bash(cmd):
    p = subprocess.run(
        ["bash", "-c", cmd],
        cwd=START,
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": os.environ["PATH"]},
    )
    return p.stdout.strip(), p.stderr.strip()


# Each payload ends in a marker that prints pwd; cd target = MISS (missing).
# %M = missing dir.
cases = [
    ("pipe-after-&&", f"cd {MISS} && echo hi | cat; pwd"),
    ("pipe-&& git", f"cd {MISS} && echo log | head; pwd"),
    ("backslash-cd", f"\\cd {MISS}; pwd"),
    ("squote-cd", f"'cd' {MISS}; pwd"),
    ("dquote-cd", f'"cd" {MISS}; pwd'),
    ("concat-cd", f'c"d" {MISS}; pwd'),
    ("command-cd", f"command cd {MISS}; pwd"),
    ("time-cd", f"time cd {MISS}; pwd"),
    ("case-pat", f'set -- build; case "$1" in build) cd {MISS}; pwd ;; esac'),
    ("then-glued", f"if true; then cd {MISS}; fi; pwd"),
    ("do-glued", f"for d in x; do cd {MISS}; pwd; done"),
    # control: no-pipe version that analyzer blocks (sanity that it poisons too)
    ("ctrl-no-pipe", f"cd {MISS} && echo hi; pwd"),
]
print(f"START={START}")
print(f"MISS ={MISS} (exists? {os.path.exists(MISS)})\n")
for name, cmd in cases:
    verdict = analyze(cmd)
    out, err = run_bash(cmd)
    poisoned = out == START  # later pwd ran in original/wrong dir
    tag = "POISON" if poisoned else "safe  "
    fo = "  <<< FAIL-OPEN" if (poisoned and verdict == "allow") else ""
    print(f"[analyzer={verdict:6} bash={tag}]{fo}  {name}: pwd_out={out!r}")
