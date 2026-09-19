#!/usr/bin/env python3
"""Mutation-check HAN sending in isolated copies with loopback SMTP only."""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/han_mail_send.py"
# Replace the named if-condition with False, keeping the actual behavior tests.
GUARDS = [
    ("tty", "not sys.stdin.isatty()", "test_no_tty_refuses"),
    ("agent-session", "any(os.environ.get(name)", "test_agent_even_with_tty_refuses"),
    ("h0-binding", "candidate.h0 != receipt", "test_gate_round_trip_and_every_outside_slot_byte"),
    ("unfilled-slot", "SLOT in filled", "test_unfilled_slot_refuses"),
    ("placeholder", "len(labels) < 2", "test_placeholder_recipient_refuses"),
    (
        "receive-installed",
        'values.get("LoadState")',
        "test_receive_preconditions_independently_refuse",
    ),
    ("receive-timer", 'unit.endswith(".timer")', "test_receive_preconditions_independently_refuse"),
    (
        "receive-service",
        'unit.endswith(".service")',
        "test_receive_preconditions_independently_refuse",
    ),
    ("notification-test", "not passed", "test_receive_preconditions_independently_refuse"),
    ("dkim", "len(records) != 1", "test_dns_preconditions_independently_refuse"),
    ("spf", "include not in terms", "test_dns_preconditions_independently_refuse"),
    ("dmarc", "len(dmarc) != 1", "test_dns_preconditions_independently_refuse"),
]


def without_guard(source: str, prefix: str) -> str:
    tree = ast.parse(source)
    matches = [
        node.test
        for node in ast.walk(tree)
        if isinstance(node, ast.If) and ast.get_source_segment(source, node.test).startswith(prefix)
    ]
    assert len(matches) == 1, f"guard anchor changed: {prefix}"
    expression = ast.get_source_segment(source, matches[0])
    return source.replace(expression, "False", 1)


def main() -> int:
    source = SOURCE.read_text()
    variants = [(name, test, without_guard(source, prefix)) for name, prefix, test in GUARDS]
    variants.extend(
        [
            (
                "single-use",
                "test_local_smtp_acceptance_and_single_use",
                source.replace(
                    "os.link(temporary, path, follow_symlinks=False)", "os.replace(temporary, path)"
                ),
            ),
            (
                "honest-ambiguity",
                "test_ambiguous_smtp_no_retry",
                source.replace(
                    '"ambiguous" if started else "pre_send_failed"', '"pre_send_failed"'
                ),
            ),
        ]
    )
    with tempfile.TemporaryDirectory(prefix="han-mail-send-mutations-") as temporary:
        root = Path(temporary)
        (root / "scripts").mkdir()
        (root / "scripts/__init__.py").touch()
        (root / "tests").mkdir()
        shutil.copyfile(ROOT / "tests/test_han_mail_send.py", root / "tests/test_han_mail_send.py")
        for name, test, mutant in variants:
            assert mutant != source, f"mutation anchor changed: {name}"
            compile(mutant, name, "exec")
            (root / "scripts/han_mail_send.py").write_text(mutant)
            shutil.rmtree(root / "scripts/__pycache__", ignore_errors=True)
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "--tb=short",
                    f"--confcutdir={root}",
                    f"tests/test_han_mail_send.py::{test}",
                ],
                cwd=root,
                env={**os.environ, "PYTHONPATH": str(root)},
                capture_output=True,
                text=True,
                timeout=45,
            )
            killed = (
                result.returncode == 1
                and f"FAILED tests/test_han_mail_send.py::{test}" in result.stdout
            )
            print(f"{name}: {'KILLED' if killed else 'SURVIVED/ERROR'}", flush=True)
            if not killed:
                print(result.stdout + result.stderr)
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
