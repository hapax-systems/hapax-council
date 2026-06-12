#!/usr/bin/env python3
import json
import subprocess

GUARD = "/data/cache/hapax/scratch/cd-guard/hooks/scripts/unguarded_cd_guard.py"


def run(cmd):
    payload = json.dumps({"tool_input": {"command": cmd}})
    p = subprocess.run(["python3", GUARD], input=payload, capture_output=True, text=True)
    return p.returncode


payloads = [
    # newline-delimited multi-line scripts (the realistic shape)
    ("if [ -d build ]; then\n  cd build\nfi\nmake", "block"),
    ('for d in */; do\n  cd "$d"\n  ./build.sh\ndone', "block"),
    ('if [ -n "$DIR" ]; then\n  cd "$DIR"\n  git add -A && git commit -m wip\nfi', "block"),
    # elif body
    ("if false; then :; elif true; then cd /nonexistent; fi; make", "block"),
    # case with newlines
    ('case "$1" in\n  build) cd build; make ;;\nesac', "block"),
    # nested: cd in then inside a loop
    ("for d in a b; do\n  if true; then cd $d; fi\n  ./run.sh\ndone", "block"),
    # until loop
    ("until false; do cd /nonexistent; echo y; done", "block"),
    # the original incident shape, wrapped in then
    ("if true; then cd /tmp/x && git add -A; git commit -m y; fi", "block"),
]

for cmd, expected in payloads:
    rc = run(cmd)
    observed = "block" if rc == 2 else ("allow" if rc == 0 else f"err{rc}")
    flag = "  <<< FAIL-OPEN" if (expected == "block" and observed == "allow") else ""
    print(f"[exp={expected} obs={observed}]{flag}  {cmd!r}")
