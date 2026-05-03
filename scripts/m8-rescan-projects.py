#!/usr/bin/env python3
"""m8-rescan-projects — read M8 SD card via host cardreader, emit YAML.

cc-task ``m8-song-queue-control``. The M8's file browser sorts FAT32
entries alphabetically; the host cannot read the SD card while M8 is
USB-attached (the M8 captures the card). This script runs operator-
physical: operator ejects M8 USB, inserts SD card into host cardreader,
runs this script, reconnects M8.

The script:
  1. Refuses to run if the M8 is currently USB-attached (per the
     /dev/hapax-m8-serial symlink existing).
  2. Auto-detects the mounted SD card by scanning common mount paths
     (/run/media/<user>/M8*, /media/<user>/M8*, /mnt/m8) for the
     telltale ``/Songs`` directory the M8 creates.
  3. Walks the Songs directory, sorts entries case-insensitively
     (matching M8's browser sort), computes button sequences for each.
  4. Emits the YAML index per ``M8ProjectIndex`` schema.

The button-sequence computation: the M8's LOAD PROJECT view starts at
the FIRST entry. Navigation: each step is one DOWN; selection is EDIT.
For project at index N (0-based), sequence is ``["EDIT"] + ["DOWN"] * N
+ ["EDIT"]`` — the first EDIT enters LOAD PROJECT, N DOWNs walk to the
target, final EDIT queues it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

DEFAULT_OUTPUT = Path("config/m8/project_index.yaml")
M8_SERIAL_SYMLINK = Path("/dev/hapax-m8-serial")
COMMON_MOUNT_ROOTS: list[Path] = [
    Path("/run/media"),
    Path("/media"),
    Path("/mnt"),
]


def m8_is_usb_attached(symlink: Path = M8_SERIAL_SYMLINK) -> bool:
    """True iff /dev/hapax-m8-serial exists (udev rule wired)."""
    return symlink.exists()


def find_sd_card_root(roots: list[Path] | None = None) -> Path | None:
    """Locate the mounted M8 SD card by looking for /Songs directory.

    Returns the first mount root containing ``Songs/`` (case-insensitive
    match because M8 may write SONGS or Songs depending on firmware).
    Returns None if nothing matches.
    """
    roots = roots if roots is not None else COMMON_MOUNT_ROOTS
    for root in roots:
        if not root.exists():
            continue
        # Walk one level deep — typical mount layout is /run/media/<user>/<label>/.
        for entry in root.rglob("*"):
            if not entry.is_dir():
                continue
            # Match case-insensitively for "songs".
            try:
                if any(
                    child.is_dir() and child.name.lower() == "songs" for child in entry.iterdir()
                ):
                    return entry
            except (PermissionError, OSError):
                continue
    return None


def list_m8_projects(songs_dir: Path) -> list[str]:
    """Return project names sorted M8-browser-equivalent (case-insensitive)."""
    entries = []
    try:
        for child in songs_dir.iterdir():
            if not child.is_file():
                continue
            # M8 project files have .m8s extension (per M8 manual).
            if child.suffix.lower() != ".m8s":
                continue
            entries.append(child.stem)
    except OSError:
        return []
    # M8 file browser sort = case-insensitive alphabetical.
    entries.sort(key=str.lower)
    return entries


def compute_button_sequence(index: int) -> list[str]:
    """Per cc-task notes: ``["EDIT"] + ["DOWN"] * N + ["EDIT"]``.

    First EDIT enters LOAD PROJECT view; N DOWNs walk to the target
    (0-indexed); final EDIT selects + queues.
    """
    return ["EDIT"] + ["DOWN"] * index + ["EDIT"]


def render_yaml(project_names: list[str]) -> str:
    """Emit the YAML matching `M8ProjectIndex` schema."""
    payload = {
        "projects": [
            {
                "name": name,
                "button_sequence": compute_button_sequence(idx),
                # duration_estimate_s, tempo_bpm, tonal_tags left unset
                # — operator populates these manually per project taste.
            }
            for idx, name in enumerate(project_names)
        ]
    }
    return yaml.safe_dump(payload, sort_keys=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"YAML output path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--sd-card-root",
        type=Path,
        default=None,
        help="Override SD card root (skip auto-detection)",
    )
    parser.add_argument(
        "--allow-m8-attached",
        action="store_true",
        help="Bypass the M8-USB-attached refusal (debug only)",
    )
    args = parser.parse_args()

    if m8_is_usb_attached() and not args.allow_m8_attached:
        print(
            "ERROR: SD card is captive — M8 is USB-attached "
            f"({M8_SERIAL_SYMLINK} exists). "
            "Disconnect M8 first, then re-run.",
            file=sys.stderr,
        )
        return 2

    if args.sd_card_root:
        if not args.sd_card_root.exists():
            print(f"ERROR: --sd-card-root {args.sd_card_root} does not exist", file=sys.stderr)
            return 3
        songs_dir = args.sd_card_root / "Songs"
        if not songs_dir.exists():
            songs_dir = args.sd_card_root / "SONGS"
        if not songs_dir.exists():
            print(f"ERROR: no Songs/ directory under {args.sd_card_root}", file=sys.stderr)
            return 3
    else:
        sd_root = find_sd_card_root()
        if sd_root is None:
            print(
                "ERROR: no M8 SD card detected at common mount points. "
                "Mount the card and re-run, or pass --sd-card-root explicitly.",
                file=sys.stderr,
            )
            return 4
        songs_dir = sd_root / "Songs" if (sd_root / "Songs").exists() else sd_root / "SONGS"

    projects = list_m8_projects(songs_dir)
    if not projects:
        print(f"WARNING: no .m8s files under {songs_dir}", file=sys.stderr)

    yaml_text = render_yaml(projects)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(yaml_text, encoding="utf-8")
    print(f"Wrote {len(projects)} projects to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
