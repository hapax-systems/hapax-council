"""Overlay zone manager — reads content files, cycles folders, caches Pango layouts.

Phase 3b-final of the compositor unification epic. The per-tick logic for
all zones lives in :class:`OverlayZonesCairoSource`, which conforms to the
:class:`CairoSource` protocol and is driven by a :class:`CairoSourceRunner`
on a background thread. The :class:`OverlayZoneManager` facade preserves
the original public API (``tick``/``render``) so the existing call sites
in :mod:`state` and :mod:`overlay` keep working.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .cairo_source import CairoSourceRunner
from .homage.transitional_source import HomageTransitionalSource
from .overlay_parser import parse_overlay_content

if TYPE_CHECKING:
    import cairo

    from agents.studio_compositor.budget import BudgetTracker

log = logging.getLogger(__name__)

SNAPSHOT_DIR = Path("/dev/shm/hapax-compositor")
RENDER_FPS = 10

# LRR Phase 8 item 12: the ``active_when_activities`` field gates a zone on
# whether any active research objective lists at least one of those
# activities in its ``activities_that_advance`` list. When the gate is
# unsatisfied the zone produces no output; the operator's other zones keep
# rendering. Empty / missing field → always-on (preserves existing
# behaviour for ``main`` + ``lyrics``).
ZONES: list[dict[str, Any]] = [
    {
        "id": "main",
        # Task #126: prefer the Hapax-managed text repo
        # (``shared.text_repo``). Obsidian folder remains as a seed /
        # fallback — the zone drops to folder-scan whenever the repo is
        # empty or missing, so the transition is reversible.
        "use_text_repo": True,
        "folder": "~/Documents/Personal/30-areas/stream-overlays/",
        "suffixes": (".md", ".txt", ".ansi"),
        "cycle_seconds": 15,
        "x": 40,
        "y": 200,
        "max_width": 1000,
        "font": "JetBrains Mono Bold 20",
        "color": (1.0, 0.97, 0.90, 1.0),
        # 2026-04-23 operator "wards off screen" (intermittent, drift-cycle
        # dependent). _tick_float drifts wards near canvas edges on a DVD
        # bounce; when Pango overflows ``max_width`` on a long token the
        # oversized surface clips at the right edge during the bounce
        # window. Disabled until a proper repositioning story ships with
        # the video-container epic. Wards stay at declared x/y anchor.
        "randomize_position": False,
    },
    {
        "id": "research",
        "use_text_repo": True,
        "folder": "~/Documents/Personal/30-areas/stream-overlays/research/",
        "suffixes": (".md", ".txt", ".ansi"),
        "cycle_seconds": 20,
        "x": 60,
        "y": 240,
        "max_width": 1000,
        "font": "JetBrains Mono Bold 18",
        "color": (0.90, 0.95, 1.00, 1.0),
        "randomize_position": False,
        # Only cycle research content when Hapax is in a study-oriented
        # objective window; outside of that the audience doesn't need it
        # and the main zone owns the space.
        "active_when_activities": ("study",),
        # Text-repo context keys: entries tagged study/research/rnd score
        # higher while the research gate is open.
        "text_repo_context": ("study", "research"),
    },
    {
        "id": "lyrics",
        "file": "/dev/shm/hapax-compositor/track-lyrics.txt",
        "x": 1350,
        "y": 0,
        "max_width": 500,
        "font": "JetBrains Mono 14",
        "color": (0.95, 0.90, 0.80, 0.9),
        "scroll": True,
        "scroll_speed": 0.5,
    },
    {
        # Right-column fill. Lyrics owns the right column whenever a
        # track is playing; this zone surfaces a slow-cycle marker
        # (aphorism / philosophical line) into the dead air the rest
        # of the time, so the audience side of the broadcast is never
        # blank in that pixel real estate. ``gate_when_file_empty``
        # closes this zone whenever the lyrics file has content.
        "id": "right_marker",
        "use_text_repo": True,
        "folder": "~/Documents/Personal/30-areas/stream-overlays/markers/",
        "suffixes": (".md", ".txt", ".ansi"),
        "cycle_seconds": 30,
        "x": 1350,
        "y": 0,
        "max_width": 500,
        "font": "JetBrains Mono Bold 16",
        "color": (0.92, 0.86, 0.70, 0.9),
        "randomize_position": False,
        "gate_when_file_empty": "/dev/shm/hapax-compositor/track-lyrics.txt",
        "text_repo_context": ("aphorism", "marker", "philosophical"),
    },
]


# ── Objective-activity gate ─────────────────────────────────────────────────

_ACTIVITY_CACHE_TTL_S = 5.0
_DEFAULT_OBJECTIVES_DIR = Path.home() / "Documents" / "Personal" / "30-areas" / "hapax-objectives"


def _read_active_objective_activities(
    directory: Path | None = None,
    *,
    now_fn: Any = time.monotonic,
) -> frozenset[str]:
    """Return the union of ``activities_that_advance`` across active objectives.

    Returns an empty set when the directory is missing or nothing is active —
    the gate will then close for any zone with a non-empty
    ``active_when_activities``.
    """
    directory = (directory or _DEFAULT_OBJECTIVES_DIR).expanduser()
    if not directory.is_dir():
        return frozenset()

    activities: set[str] = set()
    for md in directory.glob("*.md"):
        raw = _read_frontmatter_block(md)
        if raw is None:
            continue
        if raw.get("status") != "active":
            continue
        for a in raw.get("activities_that_advance", []) or []:
            if isinstance(a, str) and a:
                activities.add(a)
    del now_fn  # reserved for future caching; monotonic clock is the seam
    return frozenset(activities)


def _read_frontmatter_block(path: Path) -> dict[str, Any] | None:
    """Load the YAML frontmatter of an objective markdown file."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    import yaml

    try:
        data = yaml.safe_load(text[3:end])
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


class OverlayZone:
    def __init__(self, config: dict[str, Any]) -> None:
        self.id = config["id"]
        self.folder = config.get("folder")
        self.file = config.get("file")
        self.suffixes = tuple(config.get("suffixes", (".md", ".ansi", ".txt")))
        self.cycle_seconds = config.get("cycle_seconds", 45)
        self.base_x = config["x"]
        self.base_y = config["y"]
        self.x = self.base_x
        self.y = self.base_y
        self.max_width = config.get("max_width", 700)
        self.font_desc = config.get("font", "JetBrains Mono 11")
        self.color = config.get("color", (0.92, 0.86, 0.70, 0.9))
        self.randomize_position = config.get("randomize_position", False)
        self._attribution_format = config.get("attribution_format", False)
        self._scroll = config.get("scroll", False)
        self._scroll_speed = config.get("scroll_speed", 0.5)  # pixels per tick
        self._scroll_offset = 0.0
        self._is_image = False
        self._image_surface: Any = None
        self._pango_markup: str = ""
        self._content_hash: int = 0
        self._cached_surface: Any = None
        self._cached_surface_size: tuple[int, int] = (0, 0)
        self._last_mtime: float = 0
        self._folder_files: list[Path] = []
        self._folder_index: int = 0
        self._folder_last_scan: float = 0
        self._cycle_start: float = 0
        # LRR Phase 8 item 12: optional activity-gate. Empty tuple = always on.
        active_when = config.get("active_when_activities", ())
        self._active_when_activities: tuple[str, ...] = tuple(active_when)
        self._gate_last_check: float = 0
        self._gate_open: bool = not self._active_when_activities
        # Right-column-fill gate: when set to a path, this zone is OPEN
        # only while that path is missing or zero bytes. Used by the
        # ``right_marker`` zone to fill the right column whenever the
        # lyrics zone is silent (no current track) without overlapping
        # lyrics whenever a track IS playing.
        gate_file = config.get("gate_when_file_empty")
        self._gate_when_file_empty: Path | None = (
            Path(os.path.expanduser(gate_file)) if gate_file else None
        )
        # Task #126: Hapax-managed text repo as primary content source.
        # When the repo is empty / missing, ``_tick_repo`` falls through
        # to the legacy folder scan so the Obsidian content keeps
        # rendering until the repo is seeded.
        self._use_text_repo: bool = bool(config.get("use_text_repo", False))
        self._text_repo_context: tuple[str, ...] = tuple(config.get("text_repo_context", ()))
        self._text_repo: Any = None  # Lazy init — avoids import at class load
        self._text_repo_last_load: float = 0.0
        self._text_repo_entry_id: str | None = None

    def tick(self) -> None:
        now = time.monotonic()
        if self._gate_when_file_empty is not None and self._is_gate_file_populated():
            self._pango_markup = ""
            self._cached_surface = None
            return
        if self._active_when_activities and now - self._gate_last_check > _ACTIVITY_CACHE_TTL_S:
            active = _read_active_objective_activities()
            self._gate_open = any(a in active for a in self._active_when_activities)
            self._gate_last_check = now
        if not self._gate_open:
            self._pango_markup = ""
            self._cached_surface = None
            return
        if self._use_text_repo and self._tick_repo(now):
            # Repo produced content — done for this tick. Falls through
            # to folder-scan only when the repo is empty/missing.
            pass
        elif self.folder:
            self._tick_folder(now)
        elif self.file:
            self._tick_file()
        # Float/bounce every tick regardless of content source
        if self.randomize_position:
            self._tick_float()
        elif self._scroll:
            self._tick_scroll()

    def _is_gate_file_populated(self) -> bool:
        """Return True when the gate file exists with non-zero size.

        A populated gate file closes ``gate_when_file_empty`` zones —
        i.e., the lyrics file having content closes the right-column
        marker. Missing files are treated as empty so the gate is open
        while the producer hasn't created the path yet.
        """
        if self._gate_when_file_empty is None:
            return False
        try:
            return self._gate_when_file_empty.stat().st_size > 0
        except OSError:
            return False

    def _init_float(self) -> None:
        """Initialize DVD-screensaver-style floating motion."""
        import random

        self._vx = random.choice([-1, 1]) * random.uniform(0.8, 2.0)  # pixels per tick
        self._vy = random.choice([-1, 1]) * random.uniform(0.5, 1.5)
        self._float_x = float(self.base_x)
        self._float_y = float(self.base_y)

    def _tick_scroll(self, canvas_h: int = 1080) -> None:
        """Scroll text upward like credits. Resets when fully scrolled off."""
        self._scroll_offset += self._scroll_speed
        text_h = self._cached_surface_size[1] if self._cached_surface_size[1] else 200
        # When text scrolls completely off the top, reset to bottom
        if self._scroll_offset > text_h + canvas_h:
            self._scroll_offset = 0.0

    def _tick_float(self, canvas_w: int = 1920, canvas_h: int = 1080) -> None:
        """Move position and bounce off screen edges."""
        if not hasattr(self, "_vx"):
            self._init_float()

        sw, sh = self._cached_surface_size if self._cached_surface_size[0] else (400, 200)
        margin = 20

        self._float_x += self._vx
        self._float_y += self._vy

        # Bounce off edges
        if self._float_x <= margin:
            self._float_x = margin
            self._vx = abs(self._vx)
        elif self._float_x + sw >= canvas_w - margin:
            self._float_x = canvas_w - sw - margin
            self._vx = -abs(self._vx)

        if self._float_y <= margin:
            self._float_y = margin
            self._vy = abs(self._vy)
        elif self._float_y + sh >= canvas_h - margin:
            self._float_y = canvas_h - sh - margin
            self._vy = -abs(self._vy)

        # 2026-04-23 operator "wards off screen" — belt-and-suspenders
        # clamp post-bounce. Guarantees the ward stays within
        # [margin, canvas_w-margin-sw] even if Pango renders a surface
        # wider than max_width (long-token overflow) or the bounce math
        # drifts due to velocity accumulation. Also clamps y. No-op for
        # the common case where bounce already placed the ward in bounds.
        self._float_x = max(float(margin), min(self._float_x, float(canvas_w - margin - sw)))
        self._float_y = max(float(margin), min(self._float_y, float(canvas_h - margin - sh)))

        self.x = int(self._float_x)
        self.y = int(self._float_y)

    def _tick_repo(self, now: float) -> bool:
        """Try to pull content from the Hapax-managed text repo.

        Returns ``True`` when an entry was surfaced (so the caller should
        skip the folder-scan path). Returns ``False`` when the repo is
        empty, missing, or the import fails — the caller then falls
        through to :meth:`_tick_folder` so the Obsidian content keeps
        rendering as a fallback.
        """
        try:
            from shared.text_repo import TextRepo
        except Exception:
            return False

        # Reload the repo on a cycle-aligned cadence so operator
        # ``add-text`` sidechat writes show up without reading JSONL
        # every frame.
        if self._text_repo is None:
            self._text_repo = TextRepo()
        reload_interval = max(float(self.cycle_seconds), 1.0)
        if now - self._text_repo_last_load > reload_interval or not len(self._text_repo):
            try:
                self._text_repo.load()
            except Exception:
                log.debug("Overlay zone '%s' text repo load failed", self.id, exc_info=True)
                return False
            self._text_repo_last_load = now
        if not len(self._text_repo):
            return False

        # Cycle timer drives reselection — same cadence as folder scan.
        if self._cycle_start == 0 or self._text_repo_entry_id is None:
            entry = self._text_repo.select_for_context(
                activity=self._text_repo_context[0] if self._text_repo_context else "",
                stance=self._text_repo_context[1] if len(self._text_repo_context) > 1 else "",
                scene=self._text_repo_context[2] if len(self._text_repo_context) > 2 else "",
                now=now,
            )
            if entry is None:
                return False
            self._text_repo_entry_id = entry.id
            self._cycle_start = now
            self._apply_repo_entry(entry)
            try:
                self._text_repo.mark_shown(entry.id, when=now)
            except Exception:
                log.debug("mark_shown failed for %s", entry.id, exc_info=True)
            return True
        elif now - self._cycle_start >= self.cycle_seconds:
            entry = self._text_repo.select_for_context(
                activity=self._text_repo_context[0] if self._text_repo_context else "",
                stance=self._text_repo_context[1] if len(self._text_repo_context) > 1 else "",
                scene=self._text_repo_context[2] if len(self._text_repo_context) > 2 else "",
                now=now,
            )
            if entry is not None and entry.id != self._text_repo_entry_id:
                self._text_repo_entry_id = entry.id
                self._cycle_start = now
                self._apply_repo_entry(entry)
                try:
                    self._text_repo.mark_shown(entry.id, when=now)
                except Exception:
                    log.debug("mark_shown failed for %s", entry.id, exc_info=True)
            return True
        # Mid-cycle: keep rendering the current entry (already applied).
        return True

    def _apply_repo_entry(self, entry: Any) -> None:
        """Set pango_markup from a :class:`TextEntry`, matching folder-scan semantics."""
        body = entry.body or ""
        content_hash = hash(("repo", entry.id, body))
        if content_hash == self._content_hash:
            return
        # Entries already carry inline Pango markup (seeded from .md via
        # parse_overlay_content) or plain text — both are Pango-safe when
        # passed through the same escaping path used by text files.
        self._pango_markup = parse_overlay_content(body, is_ansi=False)
        self._content_hash = content_hash
        self._cached_surface = None
        self._is_image = False
        self._image_surface = None
        if self._scroll:
            self._scroll_offset = 0.0
        log.debug(
            "Overlay zone '%s' loaded repo entry %s (%d chars)",
            self.id,
            entry.id,
            len(body),
        )

    def _tick_folder(self, now: float) -> None:
        folder = Path(self.folder).expanduser()
        if not folder.is_dir():
            return
        if now - self._folder_last_scan > 60.0 or not self._folder_files:
            self._folder_files = sorted(
                f for f in folder.iterdir() if f.suffix in self.suffixes and f.is_file()
            )
            self._folder_last_scan = now
            if not self._folder_files:
                return
        if self._cycle_start == 0:
            self._cycle_start = now
        elif now - self._cycle_start >= self.cycle_seconds:
            import random

            # Random file each cycle, avoid repeating the same one
            old_idx = self._folder_index
            self._folder_index = random.randrange(len(self._folder_files))
            if self._folder_index == old_idx and len(self._folder_files) > 1:
                self._folder_index = (self._folder_index + 1) % len(self._folder_files)
            self._cycle_start = now
        if self._folder_files:
            idx = self._folder_index % len(self._folder_files)
            self._load_content(self._folder_files[idx])

    def _tick_file(self) -> None:
        path = Path(self.file)
        if not path.exists():
            if self._content_hash != 0:
                self._content_hash = 0
                self._pango_markup = ""
                self._is_image = False
                self._image_surface = None
            return
        try:
            mtime = os.path.getmtime(path)
            if mtime != self._last_mtime:
                self._load_content(path)
                self._last_mtime = mtime
        except OSError:
            pass

    def _load_content(self, path: Path) -> None:
        """Load either a text file (Pango) or an image (PNG surface)."""
        if path.suffix == ".png":
            self._load_image(path)
        else:
            self._load_text(path)

    def _load_image(self, path: Path) -> None:
        """Load a PNG/JPEG file via the shared ImageLoader.

        Phase 3d: delegates to :func:`get_image_loader`. The content
        hash is still computed locally for the on_change skip — the
        loader's own mtime cache is the second-level dedupe.
        """
        from .image_loader import get_image_loader

        path_str = str(path)
        content_hash = hash((path_str, os.path.getmtime(path)))
        if content_hash == self._content_hash:
            return
        surface = get_image_loader().load(path)
        if surface is None:
            log.warning("Overlay zone '%s' failed to load image %s", self.id, path.name)
            return
        self._image_surface = surface
        self._is_image = True
        self._content_hash = content_hash
        self._cached_surface = None
        self._pango_markup = ""
        self._cached_surface_size = (surface.get_width(), surface.get_height())
        log.debug(
            "Overlay zone '%s' loaded image %s (%dx%d)",
            self.id,
            path.name,
            surface.get_width(),
            surface.get_height(),
        )

    def _format_attribution(self, raw: str) -> str:
        """Format yt-attribution.txt (title\\nchannel\\nurl) as Pango markup."""
        lines = raw.strip().split("\n")
        title = lines[0] if lines else "Unknown"
        channel = lines[1] if len(lines) > 1 else ""
        url = lines[2] if len(lines) > 2 else ""
        # Escape for Pango
        title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        channel = channel.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        url = url.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        parts = [f"<b>{title}</b>"]
        if channel:
            parts.append(channel)
        if url:
            parts.append(f'<span size="small">{url}</span>')
        return "\n".join(parts)

    def _load_text(self, path: Path) -> None:
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        content_hash = hash(raw)
        if content_hash == self._content_hash:
            return
        if self._attribution_format:
            self._pango_markup = self._format_attribution(raw)
        else:
            is_ansi = path.suffix == ".ansi"
            self._pango_markup = parse_overlay_content(raw, is_ansi=is_ansi)
        self._content_hash = content_hash
        self._cached_surface = None
        self._is_image = False
        self._image_surface = None
        if self._scroll:
            self._scroll_offset = 0.0  # reset scroll on new content
        log.debug("Overlay zone '%s' updated from %s (%d chars)", self.id, path.name, len(raw))

    def render(self, cr: Any, canvas_w: int, canvas_h: int) -> None:
        # Per-zone ward properties — visibility gate + alpha + position offset.
        # Reads from ``/dev/shm/hapax-compositor/ward-properties.json`` keyed
        # by ``overlay-zone:<zone_id>``. The 200ms cache inside
        # ``ward_properties`` keeps this hot-path read sub-millisecond.
        from .ward_properties import resolve_ward_properties

        props = resolve_ward_properties(f"overlay-zone:{self.id}")
        if not props.visible:
            return
        if self._is_image and self._image_surface is not None:
            self._render_image(cr, canvas_w, canvas_h, props.alpha)
            return

        if not self._pango_markup:
            return

        if self._cached_surface is None:
            self._rebuild_surface(cr)
        if self._cached_surface is None:
            return

        # position_offset_x/y neutralized: drift-sine / drift-circle capabilities
        # oscillate wards up to ±20 px, which pushed right-edge content past the
        # 1920×1080 canvas. Operator 2026-04-23 ("still off screen") after the
        # scale_bump disable in PR #1236. Regression pin:
        # tests/studio_compositor/test_no_ward_position_drift.py.
        offset_x = 0
        offset_y = 0
        if self._scroll:
            scroll_y = canvas_h - self._scroll_offset
            cr.set_source_surface(self._cached_surface, self.x - 2 + offset_x, scroll_y + offset_y)
        else:
            cr.set_source_surface(
                self._cached_surface, self.x - 2 + offset_x, self.y - 2 + offset_y
            )
        if props.alpha < 0.999:
            cr.paint_with_alpha(max(0.0, min(1.0, props.alpha)))
        else:
            cr.paint()

    def _render_image(self, cr: Any, canvas_w: int, canvas_h: int, alpha_mod: float = 1.0) -> None:
        """Render a PNG image overlay, scaled to fit max_width.

        ``alpha_mod`` is multiplied with the zone's baseline alpha so per-ward
        ward.highlight + ward.staging dispatches modulate image overlays the
        same way they modulate Pango text overlays.
        """
        surf = self._image_surface
        iw, ih = surf.get_width(), surf.get_height()
        if iw == 0 or ih == 0:
            return
        scale = min(self.max_width / iw, 1.0)
        cr.save()
        cr.translate(self.x, self.y)
        cr.scale(scale, scale)
        cr.set_source_surface(surf, 0, 0)
        cr.paint_with_alpha(max(0.0, min(1.0, self.color[3] * alpha_mod)))
        cr.restore()

    def _rebuild_surface(self, cr: Any) -> None:
        """Pre-render outlined text to a cairo image surface (cached).

        Phase 3c: delegates to the shared text_render helper. The
        ``cr`` parameter is unused now (the helper allocates its own
        measurement surface) but kept for API compatibility with the
        single existing call site in :meth:`render`.

        No background rectangle — it would create visible edge
        artifacts when processed through shaders (thermal, halftone,
        mirror produce vertical stripe patterns from the rectangle
        borders). Text legibility comes from the thick 3px dark
        outline supplied via OUTLINE_OFFSETS_8.
        """
        del cr  # unused since the helper measures on its own surface
        from .text_render import OUTLINE_OFFSETS_8, TextStyle, render_text_to_surface

        style = TextStyle(
            text=self._pango_markup,
            font_description=self.font_desc,
            color_rgba=self.color,
            outline_color_rgba=(0.0, 0.0, 0.0, 0.9),
            outline_offsets=OUTLINE_OFFSETS_8,
            max_width_px=self.max_width,
            wrap="word_char",
            markup_mode=True,
        )
        surface, sw, sh = render_text_to_surface(style, padding_px=4)
        self._cached_surface = surface
        self._cached_surface_size = (sw, sh)


class OverlayZonesCairoSource(HomageTransitionalSource):
    """HOMAGE Phase 11c-batch-3 overlay-zone ward.

    Phase 3b implementation for the content overlay zones, migrated to
    inherit :class:`HomageTransitionalSource` so zone text participates
    in the HOMAGE FSM (ABSENT / ENTERING / HOLD / EXITING). Zone text is
    ward-scope content; the choreographer gates it via ``ticker-scroll-in``
    / ``ticker-scroll-out`` once ``HAPAX_HOMAGE_ACTIVE=1``. The per-zone
    chrome (background alpha override, DVD-float / scroll mechanics) is
    content-adjacent and stays inside ``render_content`` so the full
    zone visual is owned by the choreographer end-to-end.

    Owns the list of :class:`OverlayZone` instances. Every tick ticks each
    zone (cycling folders, reloading files, advancing scroll offsets,
    bouncing floating positions) then renders them into the runner's
    output surface. Synchronous consumers (cairooverlay on_draw) read the
    cached surface via the runner.
    """

    def __init__(self, zone_configs: list[dict[str, Any]] | None = None) -> None:
        # HOMAGE spec §4.10: overlay-zone text is ward-scope content, so
        # initial_state defaults to ABSENT — the choreographer animates
        # it in via the package's default entry transition on first
        # activation. Under ``HAPAX_HOMAGE_ACTIVE=0`` the base class
        # renders content regardless of FSM state, preserving the legacy
        # paint-and-hold behaviour that existing tests exercise.
        super().__init__(source_id="overlay_zones")
        configs = zone_configs or ZONES
        self.zones = [OverlayZone(cfg) for cfg in configs]

    def render_content(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        for zone in self.zones:
            zone.tick()
        for zone in self.zones:
            zone.render(cr, canvas_w, canvas_h)


class OverlayZoneManager:
    """Compositor-side facade around the polymorphic Cairo source pipeline.

    Preserves the original public API (``tick``/``render``) so the call
    sites in :func:`state_reader_loop` and :func:`on_draw` keep working.
    Owns a :class:`CairoSourceRunner` driving
    :class:`OverlayZonesCairoSource` on a background thread at
    :data:`RENDER_FPS`.
    """

    def __init__(
        self,
        zone_configs: list[dict[str, Any]] | None = None,
        *,
        budget_tracker: BudgetTracker | None = None,
    ) -> None:
        # A+ Stage 2 audit B2 fix (2026-04-17): canvas dims pulled from
        # config module constants. Same rationale as SierpinskiRenderer.
        from .config import OUTPUT_HEIGHT, OUTPUT_WIDTH

        self._source = OverlayZonesCairoSource(zone_configs)
        self._runner = CairoSourceRunner(
            source_id="overlay-zones",
            source=self._source,
            canvas_w=OUTPUT_WIDTH,
            canvas_h=OUTPUT_HEIGHT,
            target_fps=RENDER_FPS,
            budget_tracker=budget_tracker,
        )
        self._runner.start()
        log.info("OverlayZoneManager background thread started at %dfps", RENDER_FPS)

    @property
    def zones(self) -> list[OverlayZone]:
        """Expose the underlying zone list for tests and diagnostics."""
        return self._source.zones

    def tick(self) -> None:
        """No-op; the runner owns the tick cadence.

        Kept for API compatibility with :func:`state_reader_loop`, which
        calls ``tick()`` once per ~100ms polling cycle.
        """

    def stop(self) -> None:
        """Stop the background render thread. Idempotent."""
        self._runner.stop()

    def render(self, cr: cairo.Context, canvas_w: int, canvas_h: int) -> None:
        """Blit the pre-rendered output surface.

        This method runs on the GStreamer streaming thread and must stay
        under ~2ms. All content loading, Pango layout, and outlined-text
        rendering happens on the background runner thread.

        Meta-structural audit fix #5: honor the `all-chrome` alpha
        override from `/dev/shm/hapax-compositor/overlay-alpha-overrides.json`
        — written by ``compositional_consumer.dispatch_overlay_emphasis``
        when a ``overlay.dim.all-chrome`` capability is recruited. The
        read is cached on the manager and refreshed every ~200ms so the
        hot draw path stays under 2ms.
        """
        self._runner.set_canvas_size(canvas_w, canvas_h)
        surface = self._runner.get_output_surface()
        if surface is None:
            return
        alpha = self._resolve_chrome_alpha()
        cr.set_source_surface(surface, 0, 0)
        if alpha < 0.999:
            cr.paint_with_alpha(alpha)
        else:
            cr.paint()

    def _resolve_chrome_alpha(self) -> float:
        """Read the ``all-chrome`` alpha override (cached 200ms).

        Returns 1.0 when the override is absent, expired, or invalid,
        so the previous full-opacity behavior is the fail-open default.
        """
        import json as _json
        import time as _time
        from pathlib import Path as _Path

        cache_ttl_s = 0.2
        now = _time.monotonic()
        cached = getattr(self, "_chrome_alpha_cache", None)
        if cached is not None and (now - cached[0]) < cache_ttl_s:
            return cached[1]

        alpha = 1.0
        try:
            path = _Path("/dev/shm/hapax-compositor/overlay-alpha-overrides.json")
            if path.exists():
                data = _json.loads(path.read_text(encoding="utf-8"))
                entry = (data.get("overrides") or {}).get("all-chrome")
                if isinstance(entry, dict):
                    expires_at = float(entry.get("expires_at", 0.0))
                    if _time.time() <= expires_at:
                        raw_alpha = float(entry.get("alpha", 1.0))
                        alpha = max(0.0, min(1.0, raw_alpha))
        except Exception:
            alpha = 1.0
        self._chrome_alpha_cache = (now, alpha)
        return alpha
