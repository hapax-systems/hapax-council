#!/usr/bin/env python3
"""Guard the broadcast-master limiter controls against the loudness SSOT.

The single ``fast_lookahead_limiter`` on ``hapax-broadcast-normalized`` carries the
public egress loudness knobs — ``Input gain (dB)`` (the makeup), ``Limit (dB)`` (the
true-peak ceiling) and ``Release time (s)``. These MUST equal the constants in
``shared/audio_loudness.py`` (the SSOT). Nothing else enforces this: the existing
``check-audio-conf-consistency.py`` checks node-name/route STRUCTURE, not these VALUES.
The motivating case: a silent makeup drift in the DEPLOYED conf (``~/.config/pipewire``
is not git) — the +6-vs-SSOT-16 dB deploy-drift the audio-topology research measured and
corrected. Underscale on the public egress is easy to miss live (the LUFS-S silence floor
masks it), which is exactly why a value gate belongs in CI and the deploy-time check.

This is the SSOT↔conf value drift guard. Run it on:
  - the repo conf (CI / pre-commit) to stop the tracked template drifting from the SSOT;
  - the DEPLOYED conf (``--installed``, runtime/timer) to catch deploy-time drift — the
    failure mode that actually happened (``~/.config/pipewire`` is not git).

Usage:
  check-broadcast-master-loudness-ssot.py              # repo conf (config/pipewire/...)
  check-broadcast-master-loudness-ssot.py --installed  # deployed ~/.config/pipewire conf
  check-broadcast-master-loudness-ssot.py --conf PATH
Exit 0 = match; 1 = drift or conf missing.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.audio_loudness import (  # noqa: E402
    EGRESS_TRUE_PEAK_DBTP,
    MASTER_INPUT_MAKEUP_DB,
    MASTER_LIMITER_RELEASE_MS,
)

REPO_CONF = (
    Path(__file__).resolve().parents[1] / "config" / "pipewire" / "hapax-broadcast-master.conf"
)
INSTALLED_CONF = (
    Path.home() / ".config" / "pipewire" / "pipewire.conf.d" / "hapax-broadcast-master.conf"
)

# Quoted control key = numeric value (the filter.graph control block). Comment lines
# (which carry the same key UNquoted) are stripped first so a stale comment never matches.
_CONTROL_RE = re.compile(r'"([^"]+)"\s*=\s*(-?\d+(?:\.\d+)?)')


def parse_limiter_controls(text: str) -> dict[str, float]:
    """Extract quoted ``"key" = number`` control pairs, ignoring comment lines."""
    body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    return {m.group(1): float(m.group(2)) for m in _CONTROL_RE.finditer(body)}


def ssot_limiter_controls() -> dict[str, float]:
    """The expected limiter controls derived from the loudness SSOT."""
    return {
        "Input gain (dB)": MASTER_INPUT_MAKEUP_DB,
        "Limit (dB)": EGRESS_TRUE_PEAK_DBTP,
        "Release time (s)": MASTER_LIMITER_RELEASE_MS / 1000.0,
    }


def ssot_drift(text: str) -> list[str]:
    """Return human-readable drift lines; empty when the conf matches the SSOT."""
    controls = parse_limiter_controls(text)
    drift: list[str] = []
    for key, expected in ssot_limiter_controls().items():
        actual = controls.get(key)
        if actual is None:
            drift.append(f"{key}: MISSING in conf (SSOT expects {expected})")
        elif abs(actual - expected) > 1e-9:
            drift.append(f"{key}: conf={actual} != SSOT={expected}")
    return drift


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--installed", action="store_true", help="check the deployed ~/.config/pipewire conf"
    )
    parser.add_argument("--conf", type=Path, help="check an explicit conf path")
    args = parser.parse_args(argv)

    conf = args.conf or (INSTALLED_CONF if args.installed else REPO_CONF)
    if not conf.exists():
        print(f"check-broadcast-master-loudness-ssot: conf not found: {conf}", file=sys.stderr)
        return 1

    drift = ssot_drift(conf.read_text(encoding="utf-8"))
    if drift:
        print(
            f"check-broadcast-master-loudness-ssot: loudness SSOT drift in {conf}:", file=sys.stderr
        )
        for line in drift:
            print(f"  - {line}", file=sys.stderr)
        print(
            "  fix: reconcile shared/audio_loudness.py (the SSOT) and the conf so the "
            "limiter controls match (makeup→Input gain, EGRESS_TRUE_PEAK_DBTP→Limit, "
            "MASTER_LIMITER_RELEASE_MS/1000→Release time).",
            file=sys.stderr,
        )
        return 1

    print(
        f"check-broadcast-master-loudness-ssot: {conf} matches SSOT "
        f"(makeup={MASTER_INPUT_MAKEUP_DB} dB, peak={EGRESS_TRUE_PEAK_DBTP} dBTP, "
        f"release={MASTER_LIMITER_RELEASE_MS / 1000.0} s)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
