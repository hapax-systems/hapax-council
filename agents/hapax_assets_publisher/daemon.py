"""Long-running publisher daemon — watches the aesthetic-library source tree and
pushes changes to the ryanklee/hapax-assets external repository.

Modes:
    --dry-run   compute what would be synced; do not touch the checkout
    --once      run a single sync → commit → push cycle and exit
    --watch     run continuously; coalesces rapid events by polling at
                debounce_sec intervals; relies on sync's idempotence rather
                than inotify race-freedom

CLI entry:
    uv run python -m agents.hapax_assets_publisher [--dry-run | --once | --watch]

External-repo bootstrap is out of scope for the daemon — use
`scripts/setup-hapax-assets-repo.sh` once (operator action) to create the
remote repo, seed it with README + workflow, and enable GitHub Pages.
The daemon will log-and-skip cleanly if the checkout is not yet configured.
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time
from pathlib import Path

from agents.hapax_assets_publisher.config import PublisherConfig
from agents.hapax_assets_publisher.push_throttle import PushThrottle
from agents.hapax_assets_publisher.sync import (
    PathChange,
    build_commit_message,
    has_diff,
    sync_tree,
)

log = logging.getLogger(__name__)

DEBOUNCE_SEC_DEFAULT = 5


def _git(checkout: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=checkout,
        capture_output=True,
        text=True,
        check=False,
    )


def ensure_checkout_ready(cfg: PublisherConfig) -> bool:
    """Verify the checkout directory is a git working tree pointing at the
    configured remote. Returns True if ready; logs diagnostics and returns
    False otherwise. Does not mutate.
    """
    if not cfg.checkout_dir.is_dir():
        log.warning(
            "checkout directory %s does not exist — run scripts/setup-hapax-assets-repo.sh",
            cfg.checkout_dir,
        )
        return False
    if not (cfg.checkout_dir / ".git").exists():
        log.warning(
            "checkout directory %s is not a git repo — run scripts/setup-hapax-assets-repo.sh",
            cfg.checkout_dir,
        )
        return False
    probe = _git(cfg.checkout_dir, "remote", "get-url", "origin")
    if probe.returncode != 0 or cfg.remote_url not in probe.stdout:
        log.warning(
            "checkout remote does not match %s (got %s)",
            cfg.remote_url,
            probe.stdout.strip(),
        )
        return False
    return True


def commit_and_push(
    cfg: PublisherConfig, changes: list[PathChange], throttle: PushThrottle
) -> bool:
    """Stage + commit + push whatever is in the checkout. Returns True on
    push, False on no-op / throttled."""
    if not changes:
        log.info("no changes to publish")
        return False
    if not throttle.try_acquire():
        log.info(
            "throttled — minimum %ds since last push not yet elapsed",
            cfg.min_push_interval_sec,
        )
        return False

    add = _git(cfg.checkout_dir, "add", "-A")
    if add.returncode != 0:
        log.error("git add failed: %s", add.stderr)
        return False

    msg = build_commit_message(changes)
    commit = _git(cfg.checkout_dir, "commit", "-m", msg)
    if commit.returncode != 0 and "nothing to commit" not in commit.stdout:
        log.error("git commit failed: %s %s", commit.stdout, commit.stderr)
        return False

    push = _git(cfg.checkout_dir, "push", "origin", cfg.branch)
    if push.returncode != 0:
        log.error("git push failed: %s", push.stderr)
        return False

    log.info("pushed %d change(s) to %s:%s", len(changes), cfg.remote_url, cfg.branch)
    return True


def run_once(cfg: PublisherConfig, *, dry_run: bool = False) -> int:
    if not ensure_checkout_ready(cfg):
        return 0 if dry_run else 2
    if not has_diff(cfg.source_dir, cfg.checkout_dir):
        log.info("clean — no changes to publish")
        return 0

    if dry_run:
        # Show what would change without mutating.
        # We do a throwaway sync into a tmp dir mirror of the checkout to
        # compute the PathChange list, but NOT the real checkout.
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # Copy existing synced-namespace files so the diff is accurate.
            shutil.copytree(
                cfg.checkout_dir,
                tmp_path / "mirror",
                dirs_exist_ok=False,
                ignore=shutil.ignore_patterns(".git"),
            )
            preview = sync_tree(cfg.source_dir, tmp_path / "mirror")
        print(f"dry-run: {len(preview)} change(s) would be published:")
        for c in preview[:20]:
            print(f"  {c.kind}: {c.path}")
        return 0

    changes = sync_tree(cfg.source_dir, cfg.checkout_dir)
    throttle = PushThrottle(
        state_file=cfg.rate_state_file, min_interval_sec=cfg.min_push_interval_sec
    )
    commit_and_push(cfg, changes, throttle)
    return 0


def run_watch(cfg: PublisherConfig, debounce_sec: int = DEBOUNCE_SEC_DEFAULT) -> int:
    """Poll-based watch loop. Uses sync's idempotence rather than inotify
    race-freedom — each cycle is independent, so a missed event still gets
    caught on the next tick.
    """
    if not ensure_checkout_ready(cfg):
        return 2
    throttle = PushThrottle(
        state_file=cfg.rate_state_file, min_interval_sec=cfg.min_push_interval_sec
    )

    log.info(
        "watch mode — source %s → %s every %ds",
        cfg.source_dir,
        cfg.checkout_dir,
        debounce_sec,
    )
    while True:
        try:
            if has_diff(cfg.source_dir, cfg.checkout_dir):
                changes = sync_tree(cfg.source_dir, cfg.checkout_dir)
                commit_and_push(cfg, changes, throttle)
        except Exception:
            log.exception("publisher loop iteration failed; continuing")
        time.sleep(debounce_sec)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="preview only")
    mode.add_argument("--once", action="store_true", help="single sync cycle")
    mode.add_argument("--watch", action="store_true", help="long-running watch loop")
    p.add_argument(
        "--debounce-sec",
        type=int,
        default=DEBOUNCE_SEC_DEFAULT,
        help="watch-mode poll interval",
    )
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    cfg = PublisherConfig.from_env()

    if args.watch:
        return run_watch(cfg, debounce_sec=args.debounce_sec)
    # Default + --once + --dry-run all go through run_once.
    return run_once(cfg, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
