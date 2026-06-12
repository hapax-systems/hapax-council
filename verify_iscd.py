#!/usr/bin/env python3
"""Disambiguate: is the obfuscated word REALLY cd? Run `<WORD> <EXISTING>; pwd`
from START. If pwd==DEST the word performed a real chdir (it IS cd). If
pwd==START it was a no-op / command-not-found (NOT cd)."""

import os
import subprocess
import tempfile

base = tempfile.mkdtemp(prefix="cdguard_iscd_")
START = os.path.join(base, "start")
os.makedirs(START)
DEST = os.path.join(base, "dest")
os.makedirs(DEST)  # EXISTS


def run_bash(cmd):
    p = subprocess.run(["bash", "-c", cmd], cwd=START, capture_output=True, text=True)
    return p.stdout.strip(), p.stderr.strip()


cases = [
    ("backslash-cd", f"\\cd {DEST}; pwd"),
    ("squote-cd", f"'cd' {DEST}; pwd"),
    ("dquote-cd", f'"cd" {DEST}; pwd'),
    ("concat-cd", f'c"d" {DEST}; pwd'),
    ("command-cd", f"command cd {DEST}; pwd"),
    ("time-cd", f"time cd {DEST}; pwd"),
    ("plain-cd", f"cd {DEST}; pwd"),  # control: definitely cd
]
print(f"START={START}\nDEST ={DEST}\n")
for name, cmd in cases:
    out, err = run_bash(cmd)
    is_cd = out == DEST
    print(f"[is_cd={is_cd!s:5}] {name:14} pwd={out!r}  err={err!r}")
