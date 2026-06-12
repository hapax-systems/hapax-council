#!/usr/bin/env python3
import json
import subprocess

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


cases = [
    # coarse pipeline flag: any | in and-or list disables cd analysis for whole list
    ("pipe-after-&&", "cd /nonexistent_xyz && echo hi | cat; echo WRONG"),
    ("pipe-after-&& git", "cd /nonexistent_xyz && git log | head; rm -f tmpfile"),
    ("pipe-after-&& nl", "cd /nonexistent_xyz && echo hi | cat\necho WRONG"),
    ("ctrl no-pipe(block)", "cd /nonexistent_xyz && echo hi; echo WRONG"),
    # quoted / escaped / prefixed cd command word
    ("backslash-cd", "\\cd /nonexistent_xyz; echo WRONG"),
    ("squote-cd", "'cd' /nonexistent_xyz; echo WRONG"),
    ("dquote-cd", '"cd" /nonexistent_xyz; echo WRONG'),
    ("concat-cd", 'c"d" /nonexistent_xyz; echo WRONG'),
    ("command-cd", "command cd /nonexistent_xyz; echo WRONG"),
    ("time-cd", "time cd /nonexistent_xyz; echo WRONG"),
    # case pattern body
    ("case-pat", 'case "$1" in build) cd build; make ;; esac'),
    # keyword-glued single line
    ("then-glued", "if [ -d build ]; then cd build; fi; make"),
    ("do-glued", 'for d in */; do cd "$d"; ./build.sh; done'),
]
for name, cmd in cases:
    print(f"[{analyze(cmd):6}] {name:20} {cmd!r}")
