"""L-12 channel-strip diagnostic ward — scribble-strip Cairo source.

Per cc-task ``feedback-prevention-scribble-strip-ward`` (WSJF 4.0):
diagrammatic 12-channel L-12 input strip + AUX A-E + EFX, each
carrying its routing assertion as a short structured invariant
statement (NOT narrative prose, per ``feedback_show_dont_tell_director``).

The ward consumes:
- The per-channel routing-assertion table (compile-time constant for
  this hardware setup; the L-12 is single-operator hardware)
- The awareness state spine — specifically ``studio.monitor_aux_c_active``
  per the monitor-aggregate-awareness-signal cc-task (PRs #1700-#1702
  ship the data layer)
- The feedback-loop detector signal (loop-detector cc-task closed)

Phase 1 (this PR): routing-assertion data table + minimal Cairo render
stub that draws the strip framework. The full per-strip indicator art
+ smooth-envelope feedback indicator follows in Phase 2, after the
ward registry consumer + cairo-source runner integration is plumbed.

Constitutional posture:
- ``feedback_show_dont_tell_director``: assertions are short structured
  invariants, never narrative prose.
- ``feedback_no_blinking_homage_wards``: indicator transitions use
  smooth envelopes (sine/log decay), no hard on/off flashes.
- Single-operator: hardware setup is fixed; the routing table is
  compile-time, not configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cairo

from agents.studio_compositor.cairo_source import CairoSource


@dataclass(frozen=True, slots=True)
class StripAssertion:
    """One channel-strip's routing-assertion entry.

    Attributes:
        strip: short label (``"CH 1"``, ``"AUX A"``, ``"EFX"``)
        signal: source signal name (``"Cortado contact mic"``,
            ``"Evil Pet return"``, etc.) or ``"reserve"`` for unused
        flags: list of structured invariant assertions
            (``"+48V"``, ``"phantom OFF"``, ``"→ AUX B → Evil Pet"``)
    """

    strip: str
    signal: str
    flags: tuple[str, ...]


# Compile-time L-12 routing table per the cc-task spec body. Order
# matches the L-12's physical layout (left-to-right on the surface).
DEFAULT_ROUTING_TABLE: tuple[StripAssertion, ...] = (
    StripAssertion("CH 1", "reserve", ("phantom-bank 1-4",)),
    StripAssertion("CH 2", "Cortado contact mic", ("+48V",)),
    StripAssertion("CH 3", "reserve", ("phantom-bank 1-4",)),
    StripAssertion("CH 4", "Sampler chain", ("phantom-safe",)),
    StripAssertion("CH 5", "Rode Wireless Pro", ("phantom OFF",)),
    StripAssertion("CH 6", "Evil Pet return", ("phantom OFF", "SEND B = 0")),
    StripAssertion("CH 7", "reserve", ()),
    StripAssertion("CH 8", "reserve", ()),
    StripAssertion("CH 9", "Handytraxx L", ("→ AUX B → Evil Pet",)),
    StripAssertion("CH 10", "Handytraxx R", ("→ AUX B → Evil Pet",)),
    StripAssertion("CH 11", "Hapax voice (broadcast)", ("→ MASTER",)),
    StripAssertion("CH 12", "Hapax voice (private)", ("→ AUX C → PHONES C",)),
    StripAssertion("AUX A", "monitor sends", ()),
    StripAssertion("AUX B", "Evil Pet wet bus", ()),
    StripAssertion("AUX C", "operator monitor mix", ("Scene-8 indicator",)),
    StripAssertion("AUX D", "spare", ()),
    StripAssertion("AUX E", "spare", ()),
    StripAssertion("EFX", "Evil Pet master", ()),
)


class ScribbleStripSource(CairoSource):
    """Diagnostic scribble-strip ward.

    Phase 1 stub: draws the strip framework (rectangles + labels)
    without the per-strip indicator art. The framework is sufficient to
    verify the ward registers + renders into the compositor's surface
    pool; the per-strip indicator + the smooth-envelope feedback
    layer ship in Phase 2.
    """

    def __init__(
        self,
        *,
        routing_table: tuple[StripAssertion, ...] = DEFAULT_ROUTING_TABLE,
    ) -> None:
        self._routing_table = routing_table

    @property
    def routing_table(self) -> tuple[StripAssertion, ...]:
        return self._routing_table

    def render(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        """Draw one tick of the scribble-strip framework.

        Phase 1: dark background + per-strip vertical rectangles +
        strip-label text. Indicator art (per-strip status pip + AUX-C
        Scene-8 indicator + feedback-loop warning glow) is Phase 2.
        """
        # Dark, low-luminosity background; ward is informational, not
        # broadcast-foreground content.
        cr.set_source_rgb(0.05, 0.05, 0.07)
        cr.rectangle(0, 0, canvas_w, canvas_h)
        cr.fill()

        n_strips = len(self._routing_table)
        if n_strips == 0:
            return

        strip_w = canvas_w / n_strips
        for i, strip in enumerate(self._routing_table):
            x = i * strip_w
            self._draw_strip_frame(cr, x, 0, strip_w, canvas_h, strip)

    @staticmethod
    def _draw_strip_frame(
        cr: cairo.Context,
        x: float,
        y: float,
        w: float,
        h: float,
        strip: StripAssertion,
    ) -> None:
        """Draw one strip's rectangle + label (Phase 1 framework).

        Indicator state (active/idle, feedback-loop warning, etc.)
        deferred to Phase 2.
        """
        # Strip border
        cr.set_source_rgb(0.18, 0.18, 0.22)
        cr.set_line_width(1.0)
        cr.rectangle(x + 1, y + 1, w - 2, h - 2)
        cr.stroke()

        # Strip label (top of the strip)
        cr.set_source_rgb(0.85, 0.85, 0.90)
        cr.select_font_face("Px437 IBM VGA 8x16", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(11)
        cr.move_to(x + 4, y + 14)
        cr.show_text(strip.strip)

        # Signal name (small, below the label)
        cr.set_source_rgb(0.55, 0.55, 0.62)
        cr.set_font_size(9)
        cr.move_to(x + 4, y + 28)
        # Truncate the signal name to fit; full name is in the data
        # source for downstream consumers (tests, exports).
        signal_display = strip.signal[: max(1, int((w - 8) / 6))]
        cr.show_text(signal_display)
