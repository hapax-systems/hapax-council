"""BitchX-authentic-v1 HomagePackage — sourced from ``shared.aesthetic_library``.

The ``bitchx`` package shipped originally with palette + typography + signature
artefacts defined as inline Python constants. ``bitchx-authentic-v1`` derives
the same kind of package, but its palette + font reference + splash artefacts
come from the canonical, SHA-pinned, license-tracked
``shared.aesthetic_library`` (ytb-AUTH1):

* Palette: byte-exact from ``bitchx/colors/mirc16.yaml`` (the documented
  mIRC 16-color contract). The classical mIRC values are factually
  uncopyrightable; the YAML carries provenance + the schema declaration.
* Typography: ``Px437 IBM VGA 8x16`` (CC-BY-SA-4.0). The font file lives
  in the library at ``fonts/font/px437``; CI installs it system-wide so
  Pango finds it by family name (``primary_font_family``). No font-path
  refactor is needed at the typography model level — the source-of-truth
  for the FILE migrates to the library, the consumption pattern is
  unchanged.
* Signature artefacts: ``bitchx/splash/banner`` (a one-line BitchX banner)
  is added on top of the existing seed corpus loaded from
  ``assets/homage/bitchx/artefacts.yaml``. The classical "BitchX dragon"
  is NOT present in the upstream tree (per epsilon's AUTH1 ship note);
  the banner is the closest authentic-corpus splash and ships in its
  place. A dedicated dragon acquisition can follow later.

The original inline ``bitchx`` package (in ``bitchx.py``) is RETAINED as a
deprecated fallback. Operator can flip between the two via the active-
package SHM file (``/dev/shm/hapax-compositor/homage-active.json``).

Compile-time default flipped from ``bitchx`` to ``bitchx-authentic-v1``
under AUTH-HOMAGE (workstream-realignment v3 §1.4 "Aesthetic sign-off,
default-flag flips ... all session-callable without operator gating" +
operator's 19:10Z 2026-04-24 no-approval-waits absolute rule). The
inline package stays registered for revert-via-SHM if needed.

**Palette divergence from inline `bitchx`:** the inline ``bitchx`` package
uses bespoke "dimmer" RGB values that diverge from the byte-exact mIRC
16-color contract (e.g. inline cyan is (0.00, 0.78, 0.78); mIRC slot 11
"cyan" is (0.00, 1.00, 1.00)). ``bitchx-authentic-v1`` ships the byte-exact
values per the YAML — operator should expect a visible saturation lift on
the accent roles when flipping to the authentic variant.

Spec: ytb-AUTH-HOMAGE; depends on ytb-AUTH1.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from agents.studio_compositor.homage.bitchx import (
    _BITCHX_COUPLING,
    _BITCHX_GRAMMAR,
    _BITCHX_SIGNATURE,
    _BITCHX_TRANSITIONS,
    _BITCHX_TYPOGRAPHY,
)
from agents.studio_compositor.homage.bitchx import (
    _load_artefacts as _load_inline_artefacts,
)
from shared.aesthetic_library import library
from shared.homage_package import (
    HomagePackage,
    HomagePalette,
    SignatureArtefact,
)
from shared.voice_register import VoiceRegister


def _hex_to_rgba(hex_str: str, alpha: float = 1.0) -> tuple[float, float, float, float]:
    """Convert ``"#RRGGBB"`` → normalized RGBA tuple."""
    s = hex_str.lstrip("#")
    if len(s) != 6:
        raise ValueError(f"expected 6-char hex (e.g. '#RRGGBB'), got {hex_str!r}")
    r = int(s[0:2], 16) / 255.0
    g = int(s[2:4], 16) / 255.0
    b = int(s[4:6], 16) / 255.0
    return (r, g, b, alpha)


def _load_mirc16_slots(palette_yaml_path: Path) -> dict[str, str]:
    """Return ``{slot_str: hex_str}`` from the mirc16 YAML."""
    data = yaml.safe_load(palette_yaml_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{palette_yaml_path}: expected top-level mapping")
    slots = data.get("slots") or {}
    if not isinstance(slots, dict):
        raise ValueError(f"{palette_yaml_path}: 'slots' must be a mapping")
    out: dict[str, str] = {}
    for slot_key, entry in slots.items():
        if not isinstance(entry, dict):
            continue
        hex_val = entry.get("hex")
        if isinstance(hex_val, str):
            out[str(slot_key)] = hex_val
    return out


def _palette_from_mirc16(slots: dict[str, str]) -> HomagePalette:
    """Map mIRC 16-color slots → HomagePalette role fields.

    Mapping rationale follows the inline ``bitchx`` package's role
    intent (see ``bitchx.py`` palette comments) but uses the byte-exact
    classical mIRC values rather than the inline-bespoke dimmer
    variants:

    * muted (punctuation skeleton)        → slot 14 grey      ``#7F7F7F``
    * bright (identity / emphasis)         → slot 15 light_grey ``#D2D2D2``
    * accent_cyan (status-bar fg / accent) → slot 11 cyan      ``#00FFFF``
    * accent_magenta (own-message)         → slot 06 purple    ``#9C009C``
    * accent_green (op indicator)          → slot 09 light_green ``#00FC00``
    * accent_yellow (highlight / warning)  → slot 08 yellow    ``#FFFF00``
    * accent_red (critical)                → slot 04 red       ``#FF0000``
    * accent_blue (status-bar bg accent)   → slot 12 light_blue ``#0000FC``
    * terminal_default (content body)      → slot 15 light_grey ``#D2D2D2``
    * background (composite, alpha 0.90)   → slot 01 black     ``#000000`` α=0.90
    """
    return HomagePalette(
        muted=_hex_to_rgba(slots["14"]),
        bright=_hex_to_rgba(slots["15"]),
        accent_cyan=_hex_to_rgba(slots["11"]),
        accent_magenta=_hex_to_rgba(slots["06"]),
        accent_green=_hex_to_rgba(slots["09"]),
        accent_yellow=_hex_to_rgba(slots["08"]),
        accent_red=_hex_to_rgba(slots["04"]),
        accent_blue=_hex_to_rgba(slots["12"]),
        terminal_default=_hex_to_rgba(slots["15"]),
        background=_hex_to_rgba(slots["01"], alpha=0.90),
    )


def _banner_artefact(banner_text: str) -> SignatureArtefact:
    """Wrap the library-sourced BitchX banner as a ``join-banner`` artefact.

    The HomagePackage ``SignatureArtefactForm`` enum has no ``splash``
    variant; ``join-banner`` is the closest semantic match (CP437 block-art
    banner with inline attribution, per ``assets/homage/bitchx/artefacts.yaml``
    docstring) and is what BitchX itself emits as the splash on connect.
    The provenance string lives in ``author_tag`` to keep the asset's
    library source traceable from any consumer that walks artefacts.
    """
    return SignatureArtefact(
        form="join-banner",
        content=banner_text.strip("\n"),
        author_tag="bitchx/splash/banner (BSD-3-Clause; via shared.aesthetic_library)",
    )


def build_bitchx_authentic_package(version: str = "v1") -> HomagePackage:
    """Build the ``bitchx-authentic-{version}`` HomagePackage from the library.

    Reuses the existing inline ``bitchx`` grammar / typography / transitions /
    coupling / signature-conventions — those carry no asset-derived data
    (they're aesthetic rules, not graphical content). Replaces palette +
    extends signature_artefacts with the library-sourced banner.
    """
    lib = library()

    palette_asset = lib.get("bitchx", "palette", "mirc16")
    splash_asset = lib.get("bitchx", "splash", "banner")
    # Resolved for traceability; consumed by operators auditing provenance.
    # The font itself is registered at the system level by CI; HOMAGE
    # consumers reach it via ``primary_font_family`` (Pango family lookup).
    _font_asset = lib.get("fonts", "font", "px437")

    slots = _load_mirc16_slots(palette_asset.path)
    palette = _palette_from_mirc16(slots)
    splash = _banner_artefact(splash_asset.text())

    # Extend the original inline seed corpus with the library-sourced
    # splash so authentic-v1 has both the curated quotes + the banner.
    seed_artefacts = _load_inline_artefacts()
    artefacts: tuple[SignatureArtefact, ...] = (splash, *seed_artefacts)

    package_name = f"bitchx-authentic-{version}"
    return HomagePackage(
        name=package_name,
        version=version,
        description=(
            "BitchX-grammar HOMAGE — palette + splash sourced from "
            "shared.aesthetic_library (byte-exact mIRC 16-color, BSD-3 "
            "BitchX corpus). Authentic variant of the inline 'bitchx' "
            "package; same grammar / transitions / coupling, library-"
            "backed visual content."
        ),
        grammar=_BITCHX_GRAMMAR,
        typography=_BITCHX_TYPOGRAPHY,
        palette=palette,
        transition_vocabulary=_BITCHX_TRANSITIONS,
        coupling_rules=_BITCHX_COUPLING,
        signature_conventions=_BITCHX_SIGNATURE,
        voice_register_default=VoiceRegister.TEXTMODE,
        signature_artefacts=artefacts,
        refuses_anti_patterns=frozenset(
            [
                "emoji",
                "anti-aliased",
                "proportional-font",
                "flat-ui-chrome",
                "iso-8601-timestamp",
                "rounded-corners",
                "right-aligned-timestamp",
                "fade-transition",
                "swiss-grid-motd",
                "box-draw-inline-rule",
            ]
        ),
        asset_library_ref=package_name,
    )


# Build at module import so registration in homage/__init__.py picks it up
# the same way as BITCHX_PACKAGE. Failures here are import-time fatal — the
# operator needs to know immediately, not at first render.
BITCHX_AUTHENTIC_PACKAGE: HomagePackage = build_bitchx_authentic_package("v1")


__all__ = ["BITCHX_AUTHENTIC_PACKAGE", "build_bitchx_authentic_package"]
