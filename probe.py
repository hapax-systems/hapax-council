#!/usr/bin/env python3
import json
import subprocess

GUARD = "/data/cache/hapax/scratch/cd-guard/hooks/scripts/unguarded_cd_guard.py"


def run(cmd):
    payload = json.dumps({"tool_input": {"command": cmd}})
    p = subprocess.run(["python3", GUARD], input=payload, capture_output=True, text=True)
    return p.returncode, p.stderr.strip()


payloads = [
    # control-flow keyword wrappers (cd in then/do/else bodies, NOT condition)
    ("if true; then cd /nonexistent; fi; echo after", "block"),
    ("if [ -d build ]; then cd build; fi; make", "block"),
    ("if true; then cd /nonexistent; git add -A && git commit -m x; fi", "block"),
    ("for d in a b c; do cd $d; done; echo after", "block"),
    ('for d in */; do cd "$d"; ./build.sh; done', "block"),
    ("while true; do cd /nonexistent; echo y; done", "block"),
    ("case $x in build) cd build;; esac; make", "block"),
    ("if true; then cd /nonexistent; else echo no; fi; echo after", "block"),
    # prefix words
    ("time cd /nonexistent; echo after", "block"),
    ("! cd /nonexistent; echo after", "block"),
    ("eval cd /nonexistent; echo after", "block"),
    ("command cd /nonexistent; echo after", "block"),
    ("nice cd /nonexistent; echo after", "block"),
    # controls — sanity: these SHOULD block already (no keyword hiding)
    ("cd /nonexistent; echo after", "block"),
    ("cd /nonexistent && a; b", "block"),
    ("cd /nonexistent || true; b", "block"),
    # safe forms — should allow
    ("cd /nonexistent && make", "allow"),
    ("cd /nonexistent || exit 1; make", "allow"),
    ("set -e; cd /nonexistent; make", "allow"),
    ("cd /nonexistent", "allow"),
    ("(cd /nonexistent); b", "allow"),
    # guarded if forms (cd is the condition) — should allow per contract
    ("if cd /nonexistent; then make; fi", "allow"),
]

for cmd, expected in payloads:
    rc, err = run(cmd)
    observed = "block" if rc == 2 else ("allow" if rc == 0 else f"error({rc})")
    flag = ""
    if expected == "block" and observed == "allow":
        flag = "  <<< FAIL-OPEN"
    elif expected == "allow" and observed == "block":
        flag = "  <<< FALSE-POSITIVE"
    elif observed.startswith("error"):
        flag = "  <<< CRASH"
    print(f"[exp={expected:5} obs={observed:6}]{flag}  {cmd}")
