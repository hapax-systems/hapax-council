#!/usr/bin/env python3
"""Prove mail safety, attention-budget and release-path tests reject defects."""

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
RELEASE = "%h/.cache/hapax/source-activation/worktree"
DEV = "%h/projects/hapax-council"
UNIT_MUTATIONS = [
    (name, "test_service_uses_activated_release", before, after)
    for name, before, after in [
        ("dev-working-directory", f"WorkingDirectory={RELEASE}", f"WorkingDirectory={DEV}"),
        ("dev-interpreter", f"ExecStart={RELEASE}/.venv/", f"ExecStart={DEV}/.venv/"),
        ("dev-script", f"{RELEASE}/scripts/han_mail_pull.py", f"{DEV}/scripts/han_mail_pull.py"),
        ("dev-path", f"Environment=PATH={RELEASE}/", f"Environment=PATH={DEV}/"),
        ("dev-pythonpath", f"Environment=PYTHONPATH={RELEASE}", f"Environment=PYTHONPATH={DEV}"),
        (
            "dev-shadowed-environment",
            "Environment=PATH=",
            f"Environment=OTHER_SOURCE={DEV}\nEnvironment=PATH=",
        ),
    ]
]


def check_mutations(source, mutations, test_file, override) -> int:
    original = source.read_text()
    with tempfile.TemporaryDirectory(prefix="han-mail-mutations-") as temp:
        for name, test, before, after in mutations:
            assert original.count(before) == 1, f"mutation anchor changed: {name}"
            target = Path(temp) / f"{name}{source.suffix}"
            target.write_text(original.replace(before, after))
            result = subprocess.run(
                [
                    "uv",
                    "run",
                    "--no-sync",
                    "pytest",
                    f"{test_file}::{test}",
                    "-q",
                    "--tb=short",
                ],
                cwd=ROOT,
                env={**os.environ, override: str(target)},
                text=True,
                capture_output=True,
            )
            killed = (
                result.returncode == 1
                and "1 failed" in result.stdout
                and f"FAILED {test_file}::{test}" in result.stdout
            )
            print(f"{name}: {'KILLED' if killed else 'FAILED TO KILL'}", flush=True)
            if not killed:
                print(result.stdout)
                print(result.stderr)
                return 1
    return 0


def main() -> int:
    return check_mutations(
        SOURCE, MUTATIONS, "tests/test_han_mail_pull.py", "HAN_MAIL_PULL_UNDER_TEST"
    ) or check_mutations(
        ROOT / "systemd/units/han-mail-pull.service",
        UNIT_MUTATIONS,
        "tests/systemd/test_han_mail_pull_unit.py",
        "HAN_MAIL_UNIT_UNDER_TEST",
    )


if __name__ == "__main__":
    raise SystemExit(main())
