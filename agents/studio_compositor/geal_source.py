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
import time
from dataclasses import dataclass, field
from typing import Any

import cairo

from agents.studio_compositor.cairo_source import CairoSource
from agents.studio_compositor.sierpinski_renderer import (
    VIDEO_ATTENTION_PATH,
    GeometryCache,
    SierpinskiCairoSource,
)
from shared.geal_curves import Envelope, SecondOrderLP
from shared.geal_grounding_classifier import Apex as ClassifierApex
from shared.geal_grounding_classifier import classify_source
from shared.geal_palette_bridge import GealPaletteBridge
from shared.tts_envelope_reader import TtsEnvelopeReader

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
_VIDEO_ATTENTION_STALE_S = 3.0

# G2 latch-and-fade parameters (spec §6.3 / §7.5): three_phase 100/80/1200
# commit band + 450 ms log-decay settle.
_G2_ANTICIPATE_MS = 100.0
_G2_COMMIT_MS = 80.0
_G2_SETTLE_MS = 1200.0
_G2_SETTLE_TAU_MS = 450.0

# S2 apex-weight redistribution table (spec §6.2). Each row sums to 1.0
# except CRITICAL (all apices dark; rendered as a near-zero weight set
# which the S2 renderer treats as "mid-edge glow territory").
_S2_APEX_WEIGHTS: dict[str, tuple[float, float, float]] = {
    "NOMINAL": (0.33, 0.33, 0.33),
    "SEEKING": (0.55, 0.22, 0.22),
    "CAUTIOUS": (0.15, 0.42, 0.42),
    "DEGRADED": (0.60, 0.20, 0.20),
    "CRITICAL": (0.05, 0.05, 0.05),
}

# V1 Chladni — number of sub-triangle slivers to ignite per
# (centroid × rms) amplitude range. Spec §6.1: 1-3 of the 9 L2
# sub-triangle slivers.
_V1_MAX_IGNITIONS = 3
_V1_OMEGA = 12.0
_V1_ZETA = 0.7

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
    # Phase 2 — TTS envelope reader. Optional: if the file is missing
    # (daimonion not running), GEAL falls back to the Phase 1 constant
    # voice gate so the render path stays alive.
    _tts_envelope_reader: TtsEnvelopeReader = field(default_factory=TtsEnvelopeReader)
    # Per-tick cached video-attention scalar (spec §5.1). Read from
    # ``/dev/shm/hapax-compositor/video-attention.f32`` at the top of
    # every render; used to scale every GEAL layer's alpha so the
    # avatar never fights active video for the viewer's attention.
    _video_attention: float = 0.0
    # Smoothed voice envelope (RMS) for V2 halo drive.
    _voice_rms_lp: SecondOrderLP = field(
        default_factory=lambda: SecondOrderLP(omega=12.0, zeta=0.7)
    )
    # V1 Chladni ignition amplitude filter (centroid × rms → fill).
    _v1_ignite_lp: SecondOrderLP = field(
        default_factory=lambda: SecondOrderLP(omega=_V1_OMEGA, zeta=_V1_ZETA)
    )

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

        Phase 2 also spawns a G2 latch-and-fade: ``hash(source_id) %
        num_cells`` picks a deterministic L2 sub-triangle sliver; same
        source_id → same cell, so repeated recognitions ("Jason",
        "paper-42") build a spatial memory the viewer learns.
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
            # Imagination-converge spawns three latches — one per apex.
            for concrete in _APEX_ORDER:
                self._active_latches.append(
                    _LatchFade(
                        apex=concrete,
                        sub_triangle_idx=self._hash_to_cell_idx(source_id, concrete),
                        envelope=Envelope.three_phase(
                            fire_at_s=now_s,
                            anticipate_ms=_G2_ANTICIPATE_MS,
                            commit_ms=_G2_COMMIT_MS,
                            settle_ms=_G2_SETTLE_MS,
                            peak_amp=0.9,
                            settle_tau_ms=_G2_SETTLE_TAU_MS,
                        ),
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
            self._active_latches.append(
                _LatchFade(
                    apex=apex,
                    sub_triangle_idx=self._hash_to_cell_idx(source_id, apex),
                    envelope=Envelope.three_phase(
                        fire_at_s=now_s,
                        anticipate_ms=_G2_ANTICIPATE_MS,
                        commit_ms=_G2_COMMIT_MS,
                        settle_ms=_G2_SETTLE_MS,
                        peak_amp=0.9,
                        settle_tau_ms=_G2_SETTLE_TAU_MS,
                    ),
                )
            )

    @staticmethod
    def _hash_to_cell_idx(source_id: str, apex: ClassifierApex) -> int:
        """Deterministic cell selection within an apex's sliver triad.

        Three slivers per apex (apex / left / right) → picks one of
        those three. Using a stable Python hash variant ensures the
        same source_id always maps to the same cell regardless of
        interpreter start-up.
        """
        import hashlib

        digest = hashlib.blake2b(f"{apex}::{source_id}".encode(), digest_size=4).digest()
        return int.from_bytes(digest, "little") % 3

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

        # Spec §5.1 — read ``video_attention`` and shrink every GEAL
        # layer's alpha by ``(1.0 - 0.7 × attention)``. Active YT rect
        # → GEAL backs off to ~30 % intensity; empty rect → full.
        self._video_attention = self._read_video_attention()

        # Expire old events BEFORE rendering so we don't waste a tick on
        # envelopes whose time has passed.
        self._active_wavefronts = [
            w for w in self._active_wavefronts if not w.envelope.is_expired(t)
        ]
        self._active_latches = [L for L in self._active_latches if not L.envelope.is_expired(t)]

        # Layer 3 — V1 Chladni sub-triangle ignition (centroid × rms → fill).
        self._paint_v1_chladni(cr, geom, palette, t, state)
        # Layer 3 — G2 deterministic per-source latches (on top of V1).
        self._paint_g2_latches(cr, geom, palette, t)
        # Layer 6 — V2 vertex halos (additive, modulated by stance apex-weight S2).
        self._paint_vertex_halos(cr, geom, palette, roles, t, state, stance=stance)
        # Layer 7 — G1 wavefronts (additive, clipped away from YT rects).
        self._paint_wavefronts(cr, geom, t)

    # -- Internal paint helpers --------------------------------------------

    def _read_video_attention(self) -> float:
        """Read the scalar the Sierpinski source writes each tick.

        Missing, stale, truncated, or unreadable attention is interpreted
        as peak attention so GEAL fails quiet instead of painting a full
        intensity substrate when the Sierpinski publisher is absent.
        """
        try:
            stat = os.stat(VIDEO_ATTENTION_PATH)
            if time.time() - stat.st_mtime > _VIDEO_ATTENTION_STALE_S:
                return 1.0
            with open(VIDEO_ATTENTION_PATH, "rb") as fh:
                data = fh.read(4)
        except OSError:
            return 1.0
        if len(data) != 4:
            return 1.0
        import struct as _struct

        return max(0.0, min(1.0, _struct.unpack("<f", data)[0]))

    def _budget_scale(self) -> float:
        """Spec §5.1 activation budget multiplier.

        ``1.0 - 0.7 × video_attention`` — at attention 1.0 GEAL sits
        at 0.3 intensity; at 0.0 it runs at full.
        """
        return max(0.0, 1.0 - 0.7 * self._video_attention)

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
        *,
        stance: str = "NOMINAL",
    ) -> None:
        """Layer 6 — V2 additive radial halos at each L0 apex, modulated by S2.

        S2 (spec §6.2) redistributes attention across the three primary
        apices via a per-stance weight triple; V2 halo alpha is scaled
        by the corresponding weight so viewers read "where Hapax is
        pointing" without the grammar ever using a facial cue.
        """
        role_tokens = (roles.apex, roles.bl, roles.br)
        s2_weights = _S2_APEX_WEIGHTS.get(stance, _S2_APEX_WEIGHTS["NOMINAL"])
        halo_alpha = 0.35 + roles.halo_alpha_boost
        halo_omega = roles.lp_omega_override or _V2_OMEGA_DEFAULT
        halo_base_radius_px = min(geom.inscribed_rects[0][2], geom.inscribed_rects[0][3]) * 0.35

        # Voice-activity gate. Phase 2 reads the TTS envelope ring (100 Hz
        # RMS/centroid/ZCR/F0/voicing) and drives the halo scale off
        # smoothed RMS. When the publisher isn't running (daimonion down
        # / tests without SHM) the reader returns empty and we fall back
        # to the Phase 1 constant gate based on state["tts_active"].
        samples = self._tts_envelope_reader.latest(8)
        if samples:
            # Average RMS across the most-recent window of samples. RMS
            # is already in [0, 1]-ish range for int16 PCM / 32768; we
            # rescale to 0.2..0.9 so the V2 halo pulse maps cleanly onto
            # the conversing register's baseline/peak span.
            rms_avg = sum(s[0] for s in samples) / float(len(samples))
            target = 0.20 + min(0.70, max(0.0, rms_avg * 8.0))
        else:
            voice_active = bool(state.get("tts_active", False))
            target = 0.75 if voice_active else 0.20
        signal = self._voice_rms_lp.tick(t, target)

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
            # S2 apex-weight scale: 0.33 is the NOMINAL baseline, so we
            # rescale by 3 × weight to keep NOMINAL visually identical
            # and let SEEKING / CAUTIOUS redistribute intensity.
            weight_scale = 3.0 * s2_weights[idx]
            gradient = cairo.RadialGradient(cx, cy, 0.0, cx, cy, radius)
            gradient.add_color_stop_rgba(
                0.0, r, g, b, halo_alpha * radius_scale * weight_scale * self._budget_scale()
            )
            gradient.add_color_stop_rgba(1.0, r, g, b, 0.0)
            cr.set_source(gradient)
            cr.arc(cx, cy, radius, 0.0, 2.0 * math.pi)
            cr.fill()
        cr.restore()

    def _paint_v1_chladni(
        self,
        cr: cairo.Context,
        geom: GeometryCache,
        palette: Any,
        t: float,
        state: dict[str, Any],
    ) -> None:
        """Layer 3 — V1 Chladni sub-triangle ignition.

        ``spectral_centroid × rms`` drives the number + placement of
        sub-triangles that fill in as "still points" while the rest of
        the geometry dithers. High centroid (consonants) → apex apex
        slivers. Low centroid (vowels / silence) → base slivers.

        Samples come from the TTS envelope ring; silence = no ignition.
        """
        samples = self._tts_envelope_reader.latest(4)
        if not samples:
            return

        rms_avg = sum(s[0] for s in samples) / float(len(samples))
        centroid_avg = sum(s[1] for s in samples) / float(len(samples))
        # Normalise centroid to [0, 1] — human speech ranges ~400–4000 Hz.
        centroid_norm = max(0.0, min(1.0, centroid_avg / 4000.0))
        raw = rms_avg * centroid_norm * 6.0  # scale into useful amplitude
        amp = self._v1_ignite_lp.tick(t, raw)
        if amp < 0.05:
            return

        # Pick number of ignitions (1-3) from amplitude.
        n_ignite = max(1, min(_V1_MAX_IGNITIONS, int(amp * _V1_MAX_IGNITIONS + 0.5)))
        # Centroid selects apex-weighted (top) vs base (bl/br) bias.
        apex_bias: list[ClassifierApex]
        if centroid_norm > 0.6:
            apex_bias = ["top", "top", "bl", "br"]
        elif centroid_norm < 0.3:
            apex_bias = ["bl", "br", "bl", "br"]
        else:
            apex_bias = ["top", "bl", "br"]

        fill = _lab_to_srgb(tuple(palette.dominant_lab))

        cr.save()
        self._clip_to_non_video(cr, geom)
        cr.set_operator(cairo.OPERATOR_OVER)
        for i in range(n_ignite):
            apex_kind = apex_bias[i % len(apex_bias)]
            apex_idx = _APEX_ORDER.index(apex_kind)
            triad = geom.corner_slivers[apex_idx]
            # Rotate through sliver index so repeated ignitions don't
            # stack on the same cell during a single utterance.
            poly = triad[(i + int(t * 3.0)) % len(triad)]
            if not poly:
                continue
            cr.move_to(*poly[0])
            for x, y in poly[1:]:
                cr.line_to(x, y)
            cr.close_path()
            cr.set_source_rgba(
                fill[0], fill[1], fill[2], min(0.55, amp * 0.85) * self._budget_scale()
            )
            cr.fill()
        cr.restore()

    def _paint_g2_latches(
        self,
        cr: cairo.Context,
        geom: GeometryCache,
        palette: Any,
        t: float,
    ) -> None:
        """Layer 3 — G2 deterministic latch-and-fade cells.

        Each live :class:`_LatchFade` envelope maps to one sliver
        polygon (selected at fire time via ``hash(source_id)``) and
        paints it in the apex's accent LAB at the envelope's current
        amplitude. Same source_id → same cell, so the viewer learns
        "that cell = that thing" over the course of a session.
        """
        if not self._active_latches:
            return

        cr.save()
        self._clip_to_non_video(cr, geom)
        cr.set_operator(cairo.OPERATOR_OVER)
        for latch in self._active_latches:
            amp = latch.envelope.tick(t)
            if amp < 0.02:
                continue
            apex_idx = _APEX_ORDER.index(latch.apex)
            triad = geom.corner_slivers[apex_idx]
            if not triad:
                continue
            poly = triad[latch.sub_triangle_idx % len(triad)]
            if not poly:
                continue
            try:
                lab = self._palette_bridge.grounding_latch_lab(palette.id, latch.apex)
            except KeyError:
                continue
            r, g, b = _lab_to_srgb(lab)
            cr.move_to(*poly[0])
            for x, y in poly[1:]:
                cr.line_to(x, y)
            cr.close_path()
            cr.set_source_rgba(r, g, b, min(0.7, amp) * self._budget_scale())
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
            gradient.add_color_stop_rgba(0.5, r, g, b, amp * 0.45 * self._budget_scale())
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
