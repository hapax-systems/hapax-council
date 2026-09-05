"""Real Git history for the frame consumer's checkout-identity regressions."""

import subprocess
from pathlib import Path


def git_checkout(root: Path, *, history: str) -> None:
    """Create a real checkout with a deterministic root, without invoking commit hooks."""
    root.mkdir(parents=True, exist_ok=True)

    def git(*args: str, data: str | None = None) -> str:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            input=data,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    git("init", "--quiet")
    tree = git("mktree", data="")
    commit = git(
        "hash-object",
        "-t",
        "commit",
        "-w",
        "--stdin",
        data=(
            f"tree {tree}\n"
            "author Frame Test <frame@example.invalid> 1 +0000\n"
            "committer Frame Test <frame@example.invalid> 1 +0000\n"
            f"\n{history}\n"
        ),
    )
    git("update-ref", "HEAD", commit)
