#!/usr/bin/env python3
"""Prove mail safety and attention-budget tests reject deliberate defects."""

import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts/han_mail_pull.py"
MUTATIONS = [
    (
        "delete-before-durable-store",
        "test_delete_only_after_durable_verified_local_copy",
        "    store_item(root, key, raw, metadata)\n",
        "    kv.delete_value(key)\n    store_item(root, key, raw, metadata)\n",
    ),
    (
        "duplicate-notification-on-repull",
        "test_idempotent_repull",
        '        if item.get("notified"):\n',
        "        if False:\n",
    ),
    (
        "body-in-notification",
        "test_body_never_in_notification",
        "    if notify(title, message, priority=",
        '    message += (root / f"{first_path.stem}.eml").read_text()\n'
        "    if notify(title, message, priority=",
    ),
    (
        "body-in-push",
        "test_body_never_in_push",
        "    if notify(title, message, priority=",
        '    message += (root / f"{first_path.stem}.eml").read_text()\n'
        "    if notify(title, message, priority=",
    ),
    (
        "one-push-per-item",
        "test_coalesces_one_push_per_poll",
        '    if notify(title, message, priority="high", tags=["mail"], technical=False):\n',
        '    if any([notify(title, message, priority="high", tags=["mail"], technical=False)\n'
        "            for _ in pending]):\n",
    ),
]


def main() -> int:
    original = SOURCE.read_text()
    with tempfile.TemporaryDirectory(prefix="han-mail-mutations-") as temp:
        for name, test, before, after in MUTATIONS:
            assert original.count(before) == 1, f"mutation anchor changed: {name}"
            target = Path(temp) / f"{name}.py"
            target.write_text(original.replace(before, after))
            result = subprocess.run(
                [
                    "uv",
                    "run",
                    "--no-sync",
                    "pytest",
                    f"tests/test_han_mail_pull.py::{test}",
                    "-q",
                    "--tb=short",
                ],
                cwd=ROOT,
                env={**os.environ, "HAN_MAIL_PULL_UNDER_TEST": str(target)},
                text=True,
                capture_output=True,
            )
            killed = (
                result.returncode == 1
                and "1 failed" in result.stdout
                and f"FAILED tests/test_han_mail_pull.py::{test}" in result.stdout
            )
            print(f"{name}: {'KILLED' if killed else 'FAILED TO KILL'}")
            if not killed:
                print(result.stdout)
                print(result.stderr)
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
