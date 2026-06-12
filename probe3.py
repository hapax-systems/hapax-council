#!/usr/bin/env python3
import json
import subprocess

GUARD = "/data/cache/hapax/scratch/cd-guard/hooks/scripts/unguarded_cd_guard.py"


def run(cmd):
    payload = json.dumps({"tool_input": {"command": cmd}})
    p = subprocess.run(["python3", GUARD], input=payload, capture_output=True, text=True)
    return p.returncode


# high-realism operator/agent one-liners; all UNSAFE per contract (failed cd -> later cmd wrong dir)
payloads = [
    "if [ -d build ]; then cd build; make; fi",
    "if [ -d build ]; then cd build; fi; make",
    'while read -r d; do cd "$d"; git pull; done',
    'for d in */; do cd "$d"; ./build.sh; done',
    'case "$1" in build) cd build; make ;; esac',
    "if true; then cd /tmp/x; git add -A && git commit -m y; fi",
    "for r in repo1 repo2; do cd $r; git fetch; done",
    "test -d build && cd build; make",  # &&-then-; ... control: cd is first word here
]

for cmd in payloads:
    rc = run(cmd)
    observed = "block" if rc == 2 else ("allow" if rc == 0 else f"err{rc}")
    flag = "  <<< FAIL-OPEN" if observed == "allow" else ""
    print(f"[obs={observed}]{flag}  {cmd!r}")
