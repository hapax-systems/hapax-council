"""enlightenment-moksha-authentic-v1 — library-sourced HOMAGE package.

Phase 2 of ytb-AUTH-ENLIGHTENMENT. Mirrors the ``bitchx_authentic.py``
pattern: derive the HomagePackage from the canonical, SHA-pinned,
license-tracked ``shared.aesthetic_library`` entry rather than inline
Python constants.

* Palette: extracted at build time from
  ``assets/aesthetic-library/enlightenment/themes/moksha.edc`` via
  :func:`shared.aesthetic_library_loader.load_default_moksha`. The
  7 EDC color classes map onto HomagePalette role fields; three roles
  without a Moksha equivalent (accent_magenta, accent_yellow, accent_blue)
  fall back to the inline ``enlightenment_moksha`` values to preserve
  the Moksha aesthetic register.
* Grammar / typography / transitions / coupling / signature: reused
  verbatim from the inline ``enlightenment_moksha`` package — those
  carry no asset-derived data (they're aesthetic rules, not graphical
  content).
* ``asset_library_ref`` is set so the package is rebuildable from the
  same library state.

When authentic upstream Moksha .edc is acquired, this package
automatically picks up the new values — no code changes, just the
asset swap + SHA pin update.

Spec: ytb-AUTH-ENLIGHTENMENT (Phase 2).
"""

from __future__ import annotations

from agents.studio_compositor.homage.enlightenment_moksha import (
    _MOKSHA_COUPLING,
    _MOKSHA_GRAMMAR,
    _MOKSHA_PALETTE,
    _MOKSHA_SIGNATURE,
    _MOKSHA_TRANSITIONS,
    _MOKSHA_TYPOGRAPHY,
)
from shared.aesthetic_library_loader import load_default_moksha
from shared.homage_package import HomagePackage, HomagePalette
from shared.palette_curve_evaluator import lab_to_rgb
from shared.voice_register import VoiceRegister


def _lab_to_rgba(
    lab: tuple[float, float, float], alpha: float = 1.0
) -> tuple[float, float, float, float]:
    """Convert a CIE-LAB triple to an RGBA tuple in ``[0, 1]``, alpha-typed.

    Uses :func:`shared.palette_curve_evaluator.lab_to_rgb` (D65,
    out-of-gamut values clamped to ``[0, 1]``) and appends the alpha.
    """
    r, g, b = lab_to_rgb(*lab)
    return (r, g, b, alpha)


def _palette_from_moksha_edc(
    edc_colors: dict[str, tuple[float, float, float]],
) -> HomagePalette:
    """Map 7 Moksha color classes → HomagePalette role fields.

    Roles without a Moksha equivalent (accent_magenta, accent_yellow,
    accent_blue) carry the inline enlightenment_moksha values so the
    Moksha aesthetic register is preserved across the full role set.

    Mapping rationale:

    * ``muted`` (punctuation skeleton)        ← ``fg_color`` (soft light foreground)
    * ``bright`` (identity accent)            ← ``fg_selected`` (selection highlight)
    * ``accent_cyan`` (selection / focus)     ← ``focus_color`` (cornflower blue accent)
    * ``accent_magenta`` (mode alert)         ← inline fallback (Moksha lacks this class)
    * ``accent_green`` (ok indicator)         ← ``success_color``
    * ``accent_yellow`` (warning chrome)      ← inline fallback
    * ``accent_red`` (critical)               ← ``alert_color``
    * ``accent_blue``                         ← inline fallback
    * ``terminal_default`` (content body)     ← ``text_color``
    * ``background`` (composite; alpha 0.88)  ← ``bg_color`` (with inline-matching alpha)
    """
    return HomagePalette(
        muted=_lab_to_rgba(edc_colors["fg_color"]),
        bright=_lab_to_rgba(edc_colors["fg_selected"]),
        accent_cyan=_lab_to_rgba(edc_colors["focus_color"]),
        accent_magenta=_MOKSHA_PALETTE.accent_magenta,
        accent_green=_lab_to_rgba(edc_colors["success_color"]),
        accent_yellow=_MOKSHA_PALETTE.accent_yellow,
        accent_red=_lab_to_rgba(edc_colors["alert_color"]),
        accent_blue=_MOKSHA_PALETTE.accent_blue,
        terminal_default=_lab_to_rgba(edc_colors["text_color"]),
        # Background carries alpha=0.88 (matches the inline package's
        # composite-with-shader convention; Moksha EDC colors are full-
        # opacity by default).
        background=_lab_to_rgba(edc_colors["bg_color"], alpha=0.88),
    )


def build_enlightenment_moksha_authentic_package(version: str = "v1") -> HomagePackage:
    """Build the ``enlightenment-moksha-authentic-{version}`` package.

    Loads the Moksha EDC from the aesthetic library, extracts the 7
    color classes, maps them onto HomagePalette role fields, and
    composes a HomagePackage that otherwise reuses the inline
    enlightenment_moksha grammar / typography / transitions / coupling
    / signature.

    Fails import-time if the EDC is missing or unparseable — the
    operator needs to know immediately, not at first render. The
    Phase 1 inline ``enlightenment_moksha`` package remains available
    as a deprecation-ready fallback.
    """
    edc_colors = load_default_moksha()
    if edc_colors is None:
        raise RuntimeError(
            "enlightenment-moksha-authentic: failed to load Moksha EDC from "
            "shared.aesthetic_library_loader.DEFAULT_MOKSHA_EDC_PATH. "
            "The authored placeholder is expected to ship in-repo; verify "
            "assets/aesthetic-library/enlightenment/themes/moksha.edc exists."
        )

    package_name = f"enlightenment-moksha-authentic-{version}"
    return HomagePackage(
        name=package_name,
        version=version,
        description=(
            "Enlightenment/Moksha-grammar HOMAGE — palette sourced from "
            "shared.aesthetic_library (CC0-1.0 authored Moksha EDC placeholder "
            "until upstream acquisition). Authentic variant of the inline "
            "'enlightenment-moksha-v1' package; same grammar / transitions / "
            "coupling, library-backed palette."
        ),
        grammar=_MOKSHA_GRAMMAR,
        typography=_MOKSHA_TYPOGRAPHY,
        palette=_palette_from_moksha_edc(edc_colors),
        transition_vocabulary=_MOKSHA_TRANSITIONS,
        coupling_rules=_MOKSHA_COUPLING,
        signature_conventions=_MOKSHA_SIGNATURE,
        voice_register_default=VoiceRegister.TEXTMODE,
        signature_artefacts=(),
        refuses_anti_patterns=frozenset(
            [
                "emoji",
                "anti-aliased",
                "proportional-font",
                "iso-8601-timestamp",
                "swiss-grid-motd",
                "flat-ui-chrome",
            ]
        ),
        asset_library_ref=package_name,
    )


# Build at module import so registration in homage/__init__.py picks it up
# the same way as BITCHX_AUTHENTIC_PACKAGE. Failures here are import-time
# fatal per the authenticity contract.
ENLIGHTENMENT_MOKSHA_AUTHENTIC_PACKAGE: HomagePackage = (
    build_enlightenment_moksha_authentic_package("v1")
)


__all__ = [
    "ENLIGHTENMENT_MOKSHA_AUTHENTIC_PACKAGE",
    "build_enlightenment_moksha_authentic_package",
]
