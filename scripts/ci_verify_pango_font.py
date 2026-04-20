#!/usr/bin/env python3
"""CI verification: confirm a font family is resolvable through Pango.

Usage: ``uv run python scripts/ci_verify_pango_font.py "<family-name>"``

Exit 0 when Pango resolves the family. Exit 1 with diagnostic output
otherwise. This is a load-bearing CI step for PR #1109 (HARDM aesthetic
rework depends on Px437 IBM VGA 8x16); silent font fallback produces
blank HARDM cells, which looks like a Cairo regression to any reader of
the subsequent test failures.

The diagnostic output captures:
- Whether the Pango typelib is importable
- The fontconfig-visible entry for the target family (via fc-match)
- The top few families Pango sees whose name starts with the same
  character class as the target
"""

from __future__ import annotations

import subprocess
import sys


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: ci_verify_pango_font.py <family-name>", file=sys.stderr)
        return 2
    family = sys.argv[1]

    # 1. Probe fontconfig directly (ground truth).
    fc_match = subprocess.run(["fc-match", family], capture_output=True, text=True, check=False)
    print(f"fc-match {family!r}: {fc_match.stdout.strip() or '<empty>'}")
    if fc_match.returncode != 0:
        print(f"fc-match stderr: {fc_match.stderr.strip()}", file=sys.stderr)

    # 2. Probe Pango. Mirror the text_render.has_font code path exactly
    # so the CI verification reflects what the HARDM render will see.
    try:
        from agents.studio_compositor.text_render import _HAS_PANGO, has_font
    except Exception as exc:
        print(f"ERROR importing text_render: {exc}", file=sys.stderr)
        return 1

    print(f"_HAS_PANGO: {_HAS_PANGO}")
    if not _HAS_PANGO:
        print(
            "ERROR: Pango typelib unavailable. Install gir1.2-pango-1.0 "
            "(and gobject-introspection).",
            file=sys.stderr,
        )
        return 1

    resolved = has_font(family)
    print(f"has_font({family!r}): {resolved}")
    if resolved:
        print(f"Pango resolves {family!r}: OK")
        return 0

    # Diagnostic enumeration.
    import gi

    gi.require_version("Pango", "1.0")
    gi.require_version("PangoCairo", "1.0")
    from gi.repository import PangoCairo  # noqa: E402

    font_map = PangoCairo.FontMap.get_default()
    families = sorted(f.get_name() for f in font_map.list_families())
    prefix = family[:2].casefold()
    matching = [f for f in families if f.casefold().startswith(prefix)]
    print(
        f"Pango total families: {len(families)}. First 20 starting with {prefix!r}: {matching[:20]}"
    )
    print(f"ERROR: Pango cannot resolve {family!r}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
