"""Moksha (Enlightenment E17) theme ``.edc`` loader.

Phase 1 of ``ytb-AUTH-PALETTE`` (Moksha portion). Parses a Moksha
theme ``.edc`` file and extracts the seven canonical color classes
into a dict of CIE-LAB triples (D65, ``shared.palette_curve_evaluator``
convention). Phase 2 wires this into compositor boot so operator-
supplied Moksha .edc files augment the static registry palettes with
byte-exact theme colours; Phase 1 is the skeleton + graceful-fallback
contract.

Graceful fallback: on missing file, non-file path, empty content, or
parse failure, ``load()`` returns None. The compositor can continue
booting without hard-failing when authentic Moksha assets are not
yet acquired.

EDC color_class syntax (simplified):

    color_class {
      name: "bg_color";
      color: 37 37 37 255;
    }

The parser tolerates whitespace, newlines, extra attributes
(``color2:`` / ``color3:``), and interleaved blocks; it requires a
``name:`` string and a ``color:`` tuple of at least 3 bytes per
class declaration.

Spec: cc-task ``ytb-AUTH-PALETTE-scrim-extension``.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from shared.palette_curve_evaluator import rgb_to_lab

log = logging.getLogger(__name__)

# Seven canonical Moksha color classes the loader targets. Additional
# class names in the .edc are ignored; these seven are the ones the
# cc-task design calls out as load-bearing for ScrimPalette synthesis.
MOKSHA_COLOR_CLASSES: tuple[str, ...] = (
    "bg_color",
    "fg_color",
    "text_color",
    "fg_selected",
    "focus_color",
    "success_color",
    "alert_color",
)

LabTriple = tuple[float, float, float]

# Matches: color_class { ... name: "X" ... color: R G B [A] ... }
# The block is DOTALL so it spans newlines; lazy to catch nested-brace
# edge cases where a later block starts before the current closes.
_COLOR_CLASS_RE = re.compile(
    r"color_class\s*\{"
    r"(?P<body>[^{}]*?)"  # body has no nested braces (simple EDC case)
    r"\}",
    re.DOTALL,
)
_NAME_RE = re.compile(r'name\s*:\s*"(?P<name>[^"]+)"')
_COLOR_RE = re.compile(r"color\s*:\s*(?P<r>\d+)\s+(?P<g>\d+)\s+(?P<b>\d+)(?:\s+(?P<a>\d+))?")


class MokshaThemeLoader:
    """Load a Moksha theme ``.edc`` file → ``dict[color_class, LabTriple]``.

    Stateless — a fresh instance per load site is fine; constructed
    as a class so future Phase 2 work can attach a log-throttle or
    checksum cache.
    """

    def load(self, edc_path: Path) -> dict[str, LabTriple] | None:
        """Return a mapping of Moksha color-class name → LAB triple.

        Returns None when the file is missing, is not a regular file,
        is empty, or yields zero parseable color classes. The caller
        logs-and-continues on None; never hard-fails.
        """
        try:
            if not edc_path.is_file():
                log.debug("moksha-edc: not a file (%s); skipping", edc_path)
                return None
            text = edc_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            log.warning("moksha-edc: read failed (%s): %s", edc_path, exc)
            return None

        if not text.strip():
            log.debug("moksha-edc: empty file (%s); skipping", edc_path)
            return None

        try:
            extracted = self._parse(text)
        except Exception as exc:
            log.warning("moksha-edc: parse failed (%s): %s", edc_path, exc)
            return None

        if not extracted:
            log.debug("moksha-edc: no color classes found (%s); skipping", edc_path)
            return None

        return extracted

    def _parse(self, text: str) -> dict[str, LabTriple]:
        """Extract color classes from EDC text. Only the seven canonical names
        are returned; unknown classes are skipped."""
        out: dict[str, LabTriple] = {}
        for block in _COLOR_CLASS_RE.finditer(text):
            body = block.group("body")
            name_match = _NAME_RE.search(body)
            color_match = _COLOR_RE.search(body)
            if name_match is None or color_match is None:
                continue
            name = name_match.group("name")
            if name not in MOKSHA_COLOR_CLASSES:
                continue
            r8 = int(color_match.group("r"))
            g8 = int(color_match.group("g"))
            b8 = int(color_match.group("b"))
            # Clamp to byte range — tolerant to malformed-but-parseable
            # values rather than rejecting the whole file.
            r8 = max(0, min(255, r8))
            g8 = max(0, min(255, g8))
            b8 = max(0, min(255, b8))
            out[name] = rgb_to_lab(r8 / 255.0, g8 / 255.0, b8 / 255.0)
        return out


# Canonical in-repo path to the authored Moksha EDC placeholder. When an
# authentic upstream .edc is acquired the bytes at this path are replaced
# (loader contract is byte-value-agnostic; swapping is a pure asset update).
# Phase 2 of ytb-AUTH-PALETTE per beta's 2026-04-24 workstream realignment.
DEFAULT_MOKSHA_EDC_PATH: Path = (
    Path(__file__).resolve().parent.parent
    / "assets"
    / "aesthetic-library"
    / "enlightenment"
    / "themes"
    / "moksha.edc"
)


def load_default_moksha() -> dict[str, LabTriple] | None:
    """Convenience wrapper — load the in-repo Moksha EDC placeholder.

    Returns the same shape as :meth:`MokshaThemeLoader.load`. Intended as
    the compositor-boot entry point: import + call, no path plumbing at
    the call site.
    """
    return MokshaThemeLoader().load(DEFAULT_MOKSHA_EDC_PATH)


__all__ = [
    "DEFAULT_MOKSHA_EDC_PATH",
    "MOKSHA_COLOR_CLASSES",
    "LabTriple",
    "MokshaThemeLoader",
    "load_default_moksha",
]
