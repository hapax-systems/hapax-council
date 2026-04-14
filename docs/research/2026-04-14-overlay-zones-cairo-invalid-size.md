# overlay_zones cairo invalid-size burst — call-chain analysis

**Date:** 2026-04-14
**Author:** delta (beta role)
**Scope:** Follow-up to `2026-04-14-compositor-frame-budget-forensics.md`
finding 3 (overlay_zones render failure burst at 09:36:22 CDT) and
drop H5 (cause hypothesis). Asks: what in the overlay_zones code
path can make `text_render.render_text_to_surface` raise
`cairo.Error: invalid value` when allocating the final ImageSurface?
**Register:** scientific, neutral
**Status:** investigation only — no code change. Root cause not
determined; narrowed from "any of many" to "one of three specific
content scenarios, needs a capture-on-failure diagnostic to
distinguish".

## Headline

**Three findings.**

1. **The failure is deterministic in its code path but content-dependent
   in its trigger.** `text_render.py:188
   cairo.ImageSurface(FORMAT_ARGB32, sw, sh)` raises only when `sw` or
   `sh` is ≤ 0 or > 32767 (the pixman int16 cap for ARGB32). Every
   other code path in the call chain (markup parsing, layout
   construction, `measure_text`) succeeds before the error fires —
   otherwise the stack trace would terminate higher up. The trigger
   is therefore a `(text_w, text_h)` pair that is out of bounds for
   cairo, and the only runtime-variable input to that pair is the
   content of one overlay file.
2. **The overlay source files are stable.** `find ... -newermt
   "2026-04-14 09:00"` in `~/Documents/Personal/30-areas/stream-
   overlays/` returns nothing for the main-zone folder, and the
   zones are small (336 B largest). The failure cannot be caused by
   a file size explosion or a freshly edited file. A `track-lyrics.txt`
   mtime of 09:52 puts it after the 09:36:22 burst, but the file is
   2.3 KB / 72 lines — also too small to directly produce a
   32 767 px layout.
3. **The only way to definitively identify which content triggered
   the burst is to capture the failing `(sw, sh, len(style.text))`
   tuple at the exception site.** The current log line at
   `cairo_source.py:418` surfaces the stack trace but drops the
   input tuple. A two-line diagnostic (catch `ValueError` /
   `cairo.Error` at `text_render.py:188`, log `sw`, `sh`,
   `self.id`, and a prefix of `style.text`) converts the
   investigation from "enumerate hypotheses" to "read the next
   burst's log line". No behavioral change required.

## 1. Call chain (verified)

```text
cairo_source.py:418  CairoSourceRunner._render_one_frame
  cairo_source.py:409  self._source.render(cr, canvas_w, canvas_h, t, state)
  overlay_zones.py:358  OverlayZonesCairoSource.render  → for zone in self.zones: zone.render(...)
  overlay_zones.py:265  OverlayZone.render  → if _cached_surface is None: _rebuild_surface(cr)
  overlay_zones.py:301  OverlayZone._rebuild_surface
  overlay_zones.py:328    surface, sw, sh = render_text_to_surface(style, padding_px=4)
  text_render.py:167   render_text_to_surface(style, padding_px)
  text_render.py:184     text_w, text_h = measure_text(measure_surface, style)   ← SUCCEEDS
  text_render.py:186     sw = text_w + 8
  text_render.py:187     sh = text_h + 8
  text_render.py:188     surface = cairo.ImageSurface(FORMAT_ARGB32, sw, sh)     ← RAISES
```

Everything before line 188 returns successfully. The error is
produced inside `cairo.ImageSurface.__init__`, which is a thin
wrapper over pixman's `pixman_image_create_bits`. Pixman's `ARGB32`
format is backed by an `int32` stride and `int16` width/height —
effective cap ≈ 32 767 per dimension. Values ≤ 0 or > 32 767 are
rejected with cairo's `INVALID_SIZE` status, which the Python
binding surfaces as `cairo.Error: invalid value (typically too big)
for the size of the input (surface, pattern, etc.)` verbatim.

## 2. Inputs to the failure — what changes the (sw, sh) pair

```python
# text_render.py:167-191
def render_text_to_surface(style: TextStyle, padding_px: int = 4):
    measure_surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)
    measure_cr = cairo.Context(measure_surface)
    text_w, text_h = measure_text(measure_cr, style)   # Pango.get_pixel_size()
    sw = text_w + padding_px * 2                        # = text_w + 8
    sh = text_h + padding_px * 2                        # = text_h + 8
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, sw, sh)
    ...
```

`text_w` and `text_h` come from `layout.get_pixel_size()` after
`_build_layout` constructs a Pango layout from the `TextStyle`. The
`TextStyle` for overlay zones is built at `overlay_zones.py:318-327`
with:

```python
style = TextStyle(
    text=self._pango_markup,
    font_description=self.font_desc,
    ...
    max_width_px=self.max_width,   # 1000 for "main", 500 for "lyrics"
    wrap="word_char",
    markup_mode=True,
)
```

Four inputs determine the layout's pixel size:

| input | source | possible values |
|---|---|---|
| `style.text` | `_pango_markup` from `parse_overlay_content()` | Pango-escaped markdown or ANSI text from a file |
| `style.font_description` | zone config | `"JetBrains Mono Bold 20"` (main), `"JetBrains Mono 14"` (lyrics) |
| `style.max_width_px` | zone config | 1000 (main), 500 (lyrics) |
| `style.wrap` | hardcoded | `"word_char"` — wrap at words, fall back to char |

`max_width_px` is static (1000 and 500 — both valid and not
pathological). `wrap="word_char"` means Pango wraps at word
boundaries and falls back to mid-word wrapping if a word exceeds
`max_width_px`. `font_description` and `markup_mode` are static.

**Only `style.text` varies at runtime.** It is derived from the
on-disk file content by `parse_overlay_content(raw, is_ansi=...)`.

## 3. Ruled-out causes

### R1 — `max_width_px` zero or negative

Not possible with current zone configs. Both zones have fixed
positive ints. If a new zone shipped with `max_width=0`, Pango
would silently wrap every character onto its own line; for a
long-enough text, height could exceed 32 767. The *existing*
zones do not have this value, so this is not the active cause. It
is, however, a structural footgun: adding a zone with `max_width=0`
or forgetting the key (default fallback: `700`, which is safe)
would expose it.

### R2 — File size explosion

All files in `~/Documents/Personal/30-areas/stream-overlays/` are
under 400 bytes. `track-lyrics.txt` is 2.3 KB, 72 lines. At
font 14 Mono and line height ~18 px, 72 lines are 1 296 px tall —
two orders of magnitude below cairo's cap. File size is not the
trigger.

### R3 — Markup injection via file content

`overlay_parser.markdown_to_pango` escapes `&`, `<`, `>` *before*
inserting Pango markup via regex substitution. User content cannot
open a span that Pango would parse. The markup generated for
`# heading` uses `<span size="x-large"><b>...</b></span>` — all
preset sizes, none affect layout beyond font-metric multiples.
Markup injection is not possible from on-disk files.

### R4 — Malformed ANSI producing unbalanced spans

`overlay_parser.ansi_to_pango` closes any open span at EOF
(line 67-68) and only opens a span for codes in the
`ANSI_COLORS` table. 256-colour sequences (`\x1b[38;5;N`) match
the regex, get split into tokens, then fall through silently.
Unbalanced spans are not reachable from this parser. Note: the
stream-overlays folder has *no* `.ansi` files (listing shows
only `.md`), so this path does not apply to the current burst at
all.

### R5 — Parser stripping frontmatter incorrectly

`markdown_to_pango` line 28 strips the first `---\n...\n---\n`
block via a non-greedy DOTALL regex. If a file starts with `---\n`
but has no closing `---\n`, the regex fails to match and the
leading `---` passes through as literal text. This does not
produce an invalid size.

## 4. Remaining plausible causes

### H1 — Pango layout height exceeds 32 767 px for a specific input

Requires a text that lays out to ~1 500+ lines at the zone's font
size. None of the on-disk files are that long. `track-lyrics.txt`
could become that long if a long song is loaded (thousands of
lines). The 72-line sample captured at 09:52 does not trigger it,
but the file is written dynamically by whatever feeds it (the
compositor's track-lyrics source isn't clear from this drop).
Worth checking whether track-lyrics.txt can ever be truncated to
an empty line plus a many-line block during a song transition.

### H2 — Pango layout width exceeds 32 767 px under wrap pressure

If the text has a single word longer than `max_width_px` that
cannot be mid-word-wrapped (e.g. a URL or code fence with no
break points), `word_char` should fall back to character wrap.
But if the specific content defeats `word_char` (pathological
unicode, zero-width joins, etc.), Pango might lay out a single
run wider than `max_width_px`. 500 px / 7 px per char ≈ 70 chars
of unbreakable text exceeds 500 px. For the width to exceed
32 767 px, the unbreakable run would need to be ~4 600 chars. Not
impossible, but unlikely for plain quotes.

### H3 — Concurrent content-file update during parse

`_tick_file` in OverlayZone reads the file, parses it, assigns
`_pango_markup` — this happens on the CairoSourceRunner background
thread. The file could be mid-write when read (`track-lyrics.txt`
is updated by whatever pipeline produces lyrics; the 09:52 mtime
implies it changes during streaming). A torn read that terminates
mid-markup-tag could produce a long run of unparseable text that
Pango lays out as one huge glyph or very wide line. Races like
this are often burst-shaped: the race happens for a few ticks
while the write is in flight, then the file settles and the next
read parses cleanly. **This matches the observed burst profile
(4 seconds of failures, then recovery).**

## 5. Recommended diagnostic

Rather than guessing which of H1–H3 is active, capture the input
at the exception site on the next burst. Minimal, non-behavioral
change at `text_render.py:188`:

```python
try:
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, sw, sh)
except (cairo.Error, ValueError) as exc:
    log.error(
        "render_text_to_surface failed: sw=%d sh=%d text_w=%d "
        "text_h=%d text_len=%d text_prefix=%r",
        sw, sh, text_w, text_h, len(style.text), style.text[:120],
    )
    raise
```

Adds four diagnostic values (`sw`, `sh`, `text_w`, `text_h`,
`text_len`, `text_prefix`) to the existing error log line. Does
not change behavior. **One burst after this diagnostic lands and
we will know definitively which of H1/H2/H3 is responsible.**

After the diagnostic identifies the root cause, the fix is
hypothesis-specific:

- H1 (height overflow): clamp layout height in `_rebuild_surface`
  by setting a max height on the Pango layout, or render only
  the first N lines.
- H2 (width overflow under wrap): set an absolute ceiling on
  `sw` and `sh` at `text_render.py:186-187`; if exceeded, return
  `None` and let `_rebuild_surface` skip the zone.
- H3 (torn read race): read the file atomically (tmp + rename
  by the writer) or detect truncation (last byte not a newline,
  content hash mismatch on re-read) and skip this tick.

A defensive skip with a warning log is probably correct for all
three cases: a single dropped overlay frame is invisible to the
livestream, a cairo exception costs a full traceback write to
journald per tick.

## 6. Compositor impact of the burst

During each 4-second burst at the measured rate (~12 failures/s at
peak), the rendering thread pays:

- One full Python stack-frame unwind per failure
- JSON-serialized exception traceback (~2.5 KB)
- Journald socket write
- All the work inside `measure_text` (Pango layout construction)
  is done but thrown away

At 12 failures/s × 2.5 KB = 30 KB/s of journald traffic purely
from this one source. Not catastrophic in absolute terms, but
asymmetric: this single bug contributes more journald bandwidth
than all other compositor sources combined during the burst. The
per-frame CPU cost of a 4-second burst on the renderer thread is
noticeable in isolation but masked inside the 560 % CPU baseline.
**The primary case for fixing this is observability hygiene and
eliminating a known-intermittent failure mode, not CPU recovery.**

## 7. References

- `2026-04-14-compositor-frame-budget-forensics.md` finding 3 and
  hypothesis H5 — original observation of the burst
- `agents/studio_compositor/text_render.py:167-191` — the failure
  site (`render_text_to_surface`)
- `agents/studio_compositor/overlay_zones.py:301-330` — the caller
  (`OverlayZone._rebuild_surface`)
- `agents/studio_compositor/overlay_parser.py` — markdown/ANSI
  parser (`parse_overlay_content`)
- `~/Documents/Personal/30-areas/stream-overlays/` — the on-disk
  content feeding the "main" zone
- `/dev/shm/hapax-compositor/track-lyrics.txt` — the file feeding
  the "lyrics" zone
- Pixman source (external): `pixman-bits-image.c` — the ARGB32
  surface allocation limits mentioned in § 1
