#!/usr/bin/env python3
"""One-shot PipeWire link-map applicator for audio stack startup.

This script used to hard-code the old L-12 USB return routing. The live
audio baseline is now MPC Live III first: desired links live in
``~/.config/hapax/audio-link-map.conf`` and forbidden dry/private paths
live in ``~/.config/hapax/audio-forbidden-links.conf``. This oneshot keeps
its systemd boot hook but delegates all routing truth to those files.
The continuous ``hapax-audio-reconciler`` service remains authoritative.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_LINK_MAP = Path("~/.config/hapax/audio-link-map.conf").expanduser()
DEFAULT_FORBIDDEN_LINKS = Path("~/.config/hapax/audio-forbidden-links.conf").expanduser()


def _configured_path(env_name: str, default: Path) -> Path:
    return Path(os.environ.get(env_name, str(default))).expanduser()


def _read_links(path: Path) -> list[tuple[str, str]]:
    links: list[tuple[str, str]] = []
    if not path.exists():
        return links
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if "|" not in line:
            print(f"skip malformed link-map line in {path}: {raw_line}", file=sys.stderr)
            continue
        src, dst = (part.strip() for part in line.split("|", 1))
        if src and dst:
            links.append((src, dst))
    return links


def _run_pw_link(args: list[str]) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["pw-link", *args],
            text=True,
            capture_output=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if proc.returncode == 0:
        return True, ""
    return False, (proc.stderr or proc.stdout or "").strip()


def _apply_desired(links: list[tuple[str, str]]) -> int:
    failures = 0
    for src, dst in links:
        ok, err = _run_pw_link([src, dst])
        if ok or "File exists" in err:
            continue
        failures += 1
    return failures


def _apply_forbidden(links: list[tuple[str, str]]) -> int:
    removed = 0
    for src, dst in links:
        ok, _ = _run_pw_link(["-d", src, dst])
        if ok:
            removed += 1
    return removed


def main() -> int:
    link_map = _configured_path("HAPAX_RECONCILER_LINK_MAP", DEFAULT_LINK_MAP)
    forbidden = _configured_path("HAPAX_RECONCILER_FORBIDDEN_LINKS", DEFAULT_FORBIDDEN_LINKS)
    desired_links = _read_links(link_map)
    forbidden_links = _read_links(forbidden)

    if not desired_links:
        print(f"USB router: no desired links found at {link_map}; nothing to apply.")
        return 0

    print(f"USB router: applying {len(desired_links)} desired links from {link_map}.")
    final_failures = len(desired_links)
    removed = 0
    for _ in range(15):
        final_failures = _apply_desired(desired_links)
        removed += _apply_forbidden(forbidden_links)
        if final_failures == 0:
            break
        time.sleep(1)

    if removed:
        print(f"USB router: removed {removed} forbidden stale link(s).")
    if final_failures:
        print(
            f"USB router: {final_failures}/{len(desired_links)} links unresolved; "
            "continuous reconciler will retry.",
            file=sys.stderr,
        )
    else:
        print("USB router: link-map applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
