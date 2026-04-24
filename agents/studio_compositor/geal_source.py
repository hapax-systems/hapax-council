"""GealCairoSource — Grounding Expression Anchoring Layer (Phase 1 MVP).

Draws the three high-confidence GEAL primitives of spec §6 on top of
the Sierpinski geometry cache that the Sierpinski source publishes:

- **S1 — recursive-depth breathing.** Current stance drives a target
  recursion depth (L3 baseline, L4 under SEEKING). A three-phase
  envelope crossfades on stance transitions so the viewer reads the
  depth change as a felt move, not a hard toggle.
- **V2 — vertex halos.** Three additive-blend radial halos anchored
  at the L0 apices. Register permutes which palette role paints which
  halo (announcing → dominant-at-apex, choral → accent-at-apex,
  ritual → all-dominant with slow ω). Radius and opacity driven by a
  SecondOrderLP on voice activity — Phase 1 uses a constant 220 Hz F0
  placeholder until the TTS envelope publisher lands in Phase 2.
- **G1 — apex-of-origin wavefronts.** Each ``grounding_provenance``
  source is classified to an apex (``top`` / ``bl`` / ``br``, or
  ``"all"`` for imagination-converge); a gaussian-pulse brightness
  packet travels from that apex down the recursion tree. Carries
  meaning through geometry alone (viewer learns the grammar within
  minutes of exposure).

Ward-gated behind ``HAPAX_GEAL_ENABLED=1`` — renders a no-op when the
env var is unset. Defaults OFF so Phase 1 ships without immediately
mutating the broadcast.

Spec: ``docs/superpowers/specs/2026-04-23-geal-spec.md`` §§5-8.
Plan: ``docs/superpowers/plans/2026-04-23-geal-plan.md`` Task 1.4.
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, field
from typing import Any

import cairo

from agents.studio_compositor.cairo_source import CairoSource
from agents.studio_compositor.sierpinski_renderer import (
    GeometryCache,
    SierpinskiCairoSource,
)
from shared.geal_curves import Envelope, SecondOrderLP
from shared.geal_grounding_classifier import Apex as ClassifierApex
from shared.geal_grounding_classifier import classify_source
from shared.geal_palette_bridge import GealPaletteBridge

log = logging.getLogger(__name__)

# Env gate: set to ``1`` (or any truthy string) to enable GEAL. All
# other values — including unset — render a no-op.
_ENV_VAR = "HAPAX_GEAL_ENABLED"


def _gate_enabled() -> bool:
    return os.environ.get(_ENV_VAR, "").strip().lower() in ("1", "true", "yes", "on")


# Spec §6.2 stance → S1 target depth (L3 baseline, L4 under SEEKING).
_STANCE_DEPTH: dict[str, int] = {
    "NOMINAL": 3,
    "SEEKING": 4,
    "CAUTIOUS": 3,
    "DEGRADED": 3,
    "CRITICAL": 3,
}

# Spec §7.5 — V2 halo ω at baseline (≈ 8 Hz). Ritual register drops it.
_V2_OMEGA_DEFAULT = 8.0
_V2_ZETA = 0.8

# G1 wavefront parameters (spec §6.3 / §7.5).
_G1_SIGMA_MS = 120.0
_G1_TRAVEL_MS = 600.0

# Palette apex ordering — matches the GeometryCache.vertex_halo_centers
# list (main triangle vertices in order apex / base-left / base-right).
_APEX_ORDER: tuple[ClassifierApex, ClassifierApex, ClassifierApex] = ("top", "bl", "br")


def _lab_to_srgb(lab: tuple[float, float, float]) -> tuple[float, float, float]:
    """Cheap LAB → sRGB conversion (perceptual-luminance approximation).

    Phase 1 renders halos directly into sRGB so we need a lightweight
    LAB conversion. Uses the D65 reference white with the standard
    piecewise transfer from CIE LAB → XYZ → sRGB; accuracy adequate for
    halo tints (where LAB drift of a few ΔE is below the human JND
    at halo-strength alpha values).
    """
    L, a, b = lab
    # LAB → XYZ (D65).
    fy = (L + 16.0) / 116.0
    fx = fy + a / 500.0
    fz = fy - b / 200.0
    eps = 216.0 / 24389.0
    kappa = 24389.0 / 27.0

    def _f_inv(t: float) -> float:
        t3 = t * t * t
        return t3 if t3 > eps else (116.0 * t - 16.0) / kappa

    Xr, Yr, Zr = 0.95047, 1.0, 1.08883
    X = Xr * _f_inv(fx)
    Y = Yr * _f_inv(fy)
    Z = Zr * _f_inv(fz)

    # Linear-sRGB
    rl = 3.2406 * X - 1.5372 * Y - 0.4986 * Z
    gl = -0.9689 * X + 1.8758 * Y + 0.0415 * Z
    bl = 0.0557 * X - 0.2040 * Y + 1.0570 * Z

    def _gamma(c: float) -> float:
        c = max(0.0, min(1.0, c))
        return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1.0 / 2.4)) - 0.055

    return _gamma(rl), _gamma(gl), _gamma(bl)


def _chroma_scale_lab(lab: tuple[float, float, float], chroma: float) -> tuple[float, float, float]:
    """Scale LAB chroma (a*, b*) around the neutral axis."""
    L, a, b = lab
    return L, a * chroma, b * chroma


@dataclass
class _Wavefront:
    """One G1 wavefront packet, live in the render registry."""

    apex: ClassifierApex
    envelope: Envelope
    palette_id: str


@dataclass
class _LatchFade:
    """One G2 sub-triangle latch-and-fade event (Phase 1 scaffolding)."""

    apex: ClassifierApex
    sub_triangle_idx: int
    envelope: Envelope


@dataclass
class GealCairoSource(CairoSource):
    """Phase 1 GEAL MVP — S1 + V2 + G1 on top of the Sierpinski geometry.

    Wire-up expectations (Phase 1):

    - Stance is read from ``state["stance"]`` each tick; defaults to
      ``"NOMINAL"`` when absent. Phase 2 will pull this directly from
      ``/dev/shm/hapax-dmn/stimmung.json``.
    - Register is read from ``state["register"]`` each tick; defaults
      to ``"conversing"``. Phase 2 will read
      ``/dev/shm/hapax-compositor/homage-voice-register.json``.
    - Grounding events are fired via :meth:`fire_grounding_event`; the
      director loop will call this as the
      ``DirectorIntent.grounding_provenance`` list grows.
    """

    source_id: str = "geal"
    _palette_bridge: GealPaletteBridge = field(default_factory=GealPaletteBridge.load_default)
    _sierpinski_geom_provider: SierpinskiCairoSource = field(default_factory=SierpinskiCairoSource)
    _active_wavefronts: list[_Wavefront] = field(default_factory=list)
    _active_latches: list[_LatchFade] = field(default_factory=list)
    # One SecondOrderLP per halo slot for V2 radius smoothing.
    _halo_radius_lps: dict[int, SecondOrderLP] = field(default_factory=dict)
    # Last applied S1 depth (for three-phase crossfades when stance flips).
    _last_depth_target: int = 3
    _last_stance: str = "NOMINAL"
    _stance_transition_env: Envelope | None = None

    # -- Public control surface --------------------------------------------

    def depth_target_for_stance(self, stance: str) -> int:
        """Spec §6.2 — map stance → {L3, L4}."""
        return _STANCE_DEPTH.get(stance, 3)

    def fire_grounding_event(self, source_id: str, now_s: float) -> None:
        """Dispatch a grounding-provenance event to the right apex.

        Caller passes the raw source identifier; the classifier resolves
        it to an apex (or ``"all"`` for imagination-converge, which
        fans out to three simultaneous wavefronts). Safe to call from
        any thread that holds the runner's tick lock; the wavefronts
        are consumed on the next render tick.
        """
        if not _gate_enabled():
            return
        apex = classify_source(source_id)
        palette_id = self._current_palette_id()
        if apex == "all":
            for concrete in _APEX_ORDER:
                self._active_wavefronts.append(
                    _Wavefront(
                        apex=concrete,
                        envelope=Envelope.gaussian_pulse(
                            fire_at_s=now_s,
                            center_ms=_G1_TRAVEL_MS * 0.5,
                            sigma_ms=_G1_SIGMA_MS,
                            peak_amp=0.5,
                        ),
                        palette_id=palette_id,
                    )
                )
        else:
            self._active_wavefronts.append(
                _Wavefront(
                    apex=apex,
                    envelope=Envelope.gaussian_pulse(
                        fire_at_s=now_s,
                        center_ms=_G1_TRAVEL_MS * 0.5,
                        sigma_ms=_G1_SIGMA_MS,
                        peak_amp=0.55,
                    ),
                    palette_id=palette_id,
                )
            )

    # -- CairoSource render entry point ------------------------------------

    def render(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        """Paint the Phase 1 GEAL layers onto ``cr``.

        No-op when the ward gate is off. Otherwise:

        1. Drop expired wavefronts + latches.
        2. Resolve palette from stance; resolve halo roles from register.
        3. Paint layer 6 (V2 vertex halos, additive).
        4. Paint layer 7 (G1 wavefront packets, additive).
        5. Paint layer 3 (G2 sub-triangle latches, over) — Phase 1
           scaffolding only; the operator's aesthetic goldens land in
           task 1.6.

        Every draw clips to the non-video regions (slivers, centre
        void, halo bboxes) so the inscribed YT rects remain untouched.
        """
        if not _gate_enabled():
            return

        stance = str(state.get("stance", "NOMINAL"))
        register = str(state.get("register", "conversing"))

        # S1 depth-target tracking (Phase 1 scaffolding — the renderer
        # does not yet emit the extra L3/L4 edges, but we track the
        # transition so Phase 2's edge work can slot in without schema
        # changes).
        self._update_depth_transition(stance, t)

        # Resolve geometry once per tick (cheap: cached by canvas size).
        geom = self._sierpinski_geom_provider.geometry_cache(
            target_depth=self.depth_target_for_stance(stance),
            canvas_w=canvas_w,
            canvas_h=canvas_h,
        )

        palette = self._palette_bridge.resolve_palette(stance).palette
        roles = self._palette_bridge.halo_roles(palette.id, register)

        # Expire old events BEFORE rendering so we don't waste a tick on
        # envelopes whose time has passed.
        self._active_wavefronts = [
            w for w in self._active_wavefronts if not w.envelope.is_expired(t)
        ]
        self._active_latches = [L for L in self._active_latches if not L.envelope.is_expired(t)]

        # Layer 6 — V2 vertex halos (additive).
        self._paint_vertex_halos(cr, geom, palette, roles, t, state)
        # Layer 7 — G1 wavefronts (additive, clipped away from YT rects).
        self._paint_wavefronts(cr, geom, t)

    # -- Internal paint helpers --------------------------------------------

    def _current_palette_id(self) -> str:
        """Snapshot current palette id for attaching to a wavefront at fire time."""
        resolved = self._palette_bridge.resolve_palette(self._last_stance)
        return resolved.palette.id

    def _update_depth_transition(self, stance: str, now_s: float) -> None:
        target = self.depth_target_for_stance(stance)
        if stance != self._last_stance:
            # Fire a three_phase transition envelope so Phase 2's visible
            # L3/L4 edge work can crossfade instead of stepping.
            self._stance_transition_env = Envelope.three_phase(
                fire_at_s=now_s,
                anticipate_ms=120.0,
                commit_ms=90.0,
                settle_ms=600.0,
                peak_amp=1.0,
            )
            self._last_stance = stance
        self._last_depth_target = target

    def _resolve_halo_colour(
        self,
        role: str,
        palette: Any,
    ) -> tuple[float, float, float]:
        """Map a role token to an sRGB triple from the active palette."""
        dominant = tuple(palette.dominant_lab)
        accent = tuple(palette.accent_lab)
        if role == "dominant":
            return _lab_to_srgb(dominant)
        if role == "accent":
            return _lab_to_srgb(accent)
        if role == "accent_low_chroma":
            return _lab_to_srgb(_chroma_scale_lab(accent, 0.4))
        if role in ("duotone_high", "duotone_low"):
            # Phase 1 duotone approximation: mix 50/50 dominant + accent
            # in LAB. Phase 3 will drive the mix by instantaneous F0.
            midpoint = tuple((d + a) * 0.5 for d, a in zip(dominant, accent, strict=True))
            return _lab_to_srgb(midpoint)  # type: ignore[arg-type]
        if role == "off":
            return (0.0, 0.0, 0.0)
        # Fallback — shouldn't happen in practice, but keep the render
        # alive on a future YAML typo.
        return _lab_to_srgb(dominant)

    def _paint_vertex_halos(
        self,
        cr: cairo.Context,
        geom: GeometryCache,
        palette: Any,
        roles: Any,
        t: float,
        state: dict[str, Any],
    ) -> None:
        """Layer 6 — V2 additive radial halos at each L0 apex."""
        role_tokens = (roles.apex, roles.bl, roles.br)
        halo_alpha = 0.35 + roles.halo_alpha_boost
        halo_omega = roles.lp_omega_override or _V2_OMEGA_DEFAULT
        halo_base_radius_px = min(geom.inscribed_rects[0][2], geom.inscribed_rects[0][3]) * 0.35

        # Voice-activity gate (Phase 1: constant 0.6 when tts_active is
        # reported in state, else 0.2 ambient presence).
        voice_active = bool(state.get("tts_active", False))
        signal = 0.75 if voice_active else 0.20

        cr.save()
        self._clip_to_non_video(cr, geom)
        cr.set_operator(cairo.OPERATOR_ADD)
        for idx, (centre, role_token) in enumerate(
            zip(geom.vertex_halo_centers, role_tokens, strict=True)
        ):
            if role_token == "off":
                continue
            lp = self._halo_radius_lps.get(idx)
            if lp is None or lp.omega != halo_omega:
                lp = SecondOrderLP(omega=halo_omega, zeta=_V2_ZETA)
                self._halo_radius_lps[idx] = lp
            radius_scale = lp.tick(t, signal)
            radius = halo_base_radius_px * (0.6 + 0.6 * radius_scale)
            r, g, b = self._resolve_halo_colour(role_token, palette)
            cx, cy = centre
            gradient = cairo.RadialGradient(cx, cy, 0.0, cx, cy, radius)
            gradient.add_color_stop_rgba(0.0, r, g, b, halo_alpha * radius_scale)
            gradient.add_color_stop_rgba(1.0, r, g, b, 0.0)
            cr.set_source(gradient)
            cr.arc(cx, cy, radius, 0.0, 2.0 * math.pi)
            cr.fill()
        cr.restore()

    def _paint_wavefronts(
        self,
        cr: cairo.Context,
        geom: GeometryCache,
        t: float,
    ) -> None:
        """Layer 7 — G1 wavefronts travelling from apex-of-origin.

        Phase 1 MVP renders a gaussian brightness packet radially from
        the source apex, clipped to the sliver polygons + centre void
        so the inscribed video rects remain untouched. Phase 2 will
        switch to path-based traversal along ``edge_polylines``.
        """
        if not self._active_wavefronts:
            return

        # Build a clip path covering the non-video regions.
        cr.save()
        self._clip_to_non_video(cr, geom)
        cr.set_operator(cairo.OPERATOR_ADD)

        apex_map = dict(zip(_APEX_ORDER, geom.vertex_halo_centers, strict=True))
        max_radius = max(geom.inscribed_rects[0][2], geom.inscribed_rects[0][3]) * 2.0

        for wavefront in self._active_wavefronts:
            centre = apex_map.get(wavefront.apex)
            if centre is None:
                continue
            amp = wavefront.envelope.tick(t)
            if amp < 0.01:
                continue
            try:
                lab = self._palette_bridge.grounding_latch_lab(wavefront.palette_id, wavefront.apex)
            except KeyError:
                continue
            r, g, b = _lab_to_srgb(lab)
            # Radius grows with packet age — at envelope peak the
            # wavefront has travelled ~half its distance.
            # Event-bound envelopes require fire_at_s; the classmethod
            # factory guarantees it's set, so this narrowing is safe.
            assert wavefront.envelope.fire_at_s is not None
            age_ms = (t - wavefront.envelope.fire_at_s) * 1000.0
            travel_frac = min(1.0, age_ms / _G1_TRAVEL_MS)
            radius = max_radius * travel_frac
            cx, cy = centre
            gradient = cairo.RadialGradient(cx, cy, max(0.0, radius - 40.0), cx, cy, radius + 40.0)
            gradient.add_color_stop_rgba(0.0, r, g, b, 0.0)
            gradient.add_color_stop_rgba(0.5, r, g, b, amp * 0.45)
            gradient.add_color_stop_rgba(1.0, r, g, b, 0.0)
            cr.set_source(gradient)
            cr.arc(cx, cy, radius + 40.0, 0.0, 2.0 * math.pi)
            cr.fill()

        cr.restore()

    def _clip_to_non_video(self, cr: cairo.Context, geom: GeometryCache) -> None:
        """Restrict further drawing to the slivers + centre void.

        The sliver polygons are already constructed to NOT overlap the
        inscribed video rects (a triangular sliver with two vertices on
        a rect edge sits entirely on one side of that edge). Building
        the clip path as the union of slivers + centre void is therefore
        sufficient — no rect subtraction required.
        """
        cr.new_path()
        for triad in geom.corner_slivers:
            for polygon in triad:
                if not polygon:
                    continue
                cr.move_to(*polygon[0])
                for x, y in polygon[1:]:
                    cr.line_to(x, y)
                cr.close_path()
        if geom.center_void:
            cr.move_to(*geom.center_void[0])
            for x, y in geom.center_void[1:]:
                cr.line_to(x, y)
            cr.close_path()
        cr.set_fill_rule(cairo.FillRule.WINDING)
        cr.clip()


__all__ = ["GealCairoSource"]
