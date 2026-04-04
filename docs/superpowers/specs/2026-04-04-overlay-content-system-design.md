# Overlay Content System

## Goal

Replace hardcoded briefing overlay text with a configurable content system supporting markdown formatting and ANSI art, rendered via Pango on the GStreamer cairooverlay surface.

## Architecture

```
Content files (/dev/shm/hapax-compositor/overlay-*.md or .ansi)
  -> State loop reads on change (100ms poll, mtime check)
  -> Parser converts markdown or ANSI to Pango markup
  -> Cached PangoLayout (re-created only on content change)
  -> on_draw() calls PangoCairo.show_layout() each frame (<1ms)
```

## Content Sources

Overlay zones read from files in `/dev/shm/hapax-compositor/`:

| File | Zone | Default content |
|------|------|-----------------|
| `overlay-main.md` | Main info panel (currently briefing text) | Empty (no overlay) |
| `overlay-status.md` | Status line (flow state, activity) | Auto-generated from perception state |
| `overlay-art.ansi` | ANSI art zone | Empty |

File extension determines parser:
- `.md` -> markdown-to-Pango parser
- `.ansi` -> ANSI escape code to Pango `<span foreground>` parser
- `.txt` -> plain text (Pango-escaped, no formatting)

Any process can write to these files: agents, scripts, the operator via `echo`, the Logos API. The compositor reads them.

## Obsidian Note Cycling

A zone can point to a folder of Obsidian notes instead of a single file. The compositor cycles through them on a configurable interval.

**Configuration:**

```python
{
    "id": "main",
    "folder": "~/Documents/Personal/30-areas/stream-overlays/",
    "cycle_seconds": 45,
    "font": "JetBrains Mono 11",
    ...
}
```

When `folder` is set instead of `file`:
1. On startup, scan the folder for `.md` files (sorted alphabetically)
2. Display the first note's content
3. Every `cycle_seconds`, advance to the next note (wrap to first at end)
4. Re-scan the folder periodically (every 60s) to pick up new/removed notes
5. YAML frontmatter is stripped before rendering (everything before the first `---` pair)

The folder can be anywhere — an Obsidian vault subfolder, a symlink, or a path in `/dev/shm`. Notes are standard markdown files. The operator curates content by adding/removing `.md` files from the folder.

**Example:** Create `~/Documents/Personal/30-areas/stream-overlays/` with:
```
01-welcome.md      -> "# Legomena Live\n*building AI + making beats*"
02-gear-list.md    -> "## Studio Gear\n- MPC Live II\n- SP-404\n..."
03-links.md        -> "## Links\n**YouTube**: ...\n**GitHub**: ..."
04-ansi-art.md     -> Raw ANSI art block
```

The overlay cycles through these every 45 seconds during the stream.

## Markdown Support

Regex-based conversion to Pango markup:

| Markdown | Pango |
|----------|-------|
| `**bold**` | `<b>bold</b>` |
| `*italic*` | `<i>italic</i>` |
| `` `code` `` | `<tt>code</tt>` |
| `# Heading` | `<span size="x-large"><b>Heading</b></span>` |
| `## Subhead` | `<span size="large"><b>Subhead</b></span>` |
| `~~strike~~` | `<s>strike</s>` |

No need for a full markdown parser. Pango handles the rendering.

## ANSI Art Support

ANSI escape codes (`\033[31m` etc.) converted to Pango `<span foreground="...">` markup.

16-color ANSI palette mapped to Gruvbox colors:

| ANSI | Color | Gruvbox hex |
|------|-------|-------------|
| 30 | Black | #282828 |
| 31 | Red | #cc241d |
| 32 | Green | #98971a |
| 33 | Yellow | #d79921 |
| 34 | Blue | #458588 |
| 35 | Magenta | #b16286 |
| 36 | Cyan | #689d6a |
| 37 | White | #a89984 |
| 90-97 | Bright variants | Gruvbox bright equivalents |

Font: `MxPlus IBM VGA 9x16` (already installed at `/usr/share/fonts/TTF/MxPlus_IBM_VGA_9x16.ttf`). Renders CP437 block characters correctly.

## Overlay Zone Configuration

Each zone has configurable position, size, font, and content source. Defined in a simple Python dict in `overlay.py`:

```python
OVERLAY_ZONES = [
    {
        "id": "main",
        "file": "overlay-main.md",
        "x": 20, "y": 160,
        "max_width": 700,
        "font": "JetBrains Mono 11",
        "color": (0.92, 0.86, 0.70, 0.9),  # #ebdbb2 at 90% alpha
    },
    {
        "id": "status",
        "file": "overlay-status.md",
        "x": 20, "y": 10,
        "max_width": 1200,
        "font": "JetBrains Mono Bold 14",
        "color": (0.92, 0.86, 0.70, 0.95),
    },
    {
        "id": "art",
        "file": "overlay-art.ansi",
        "x": 20, "y": 800,
        "max_width": 900,
        "font": "MxPlus IBM VGA 9x16 12",
        "color": (0.92, 0.86, 0.70, 0.85),
    },
]
```

## Performance

- Pango layout cached per zone, recreated only when file mtime changes
- `PangoCairo.show_layout()` is sub-millisecond per zone
- File mtime checked every 100ms in the existing state loop (no extra polling)
- Total overlay render budget: <3ms for all zones at 24fps

## What Changes

| File | Change |
|------|--------|
| `agents/studio_compositor/overlay.py` | Replace hardcoded text rendering with Pango-based zone system |
| New: `agents/studio_compositor/overlay_parser.py` | Markdown and ANSI to Pango markup parsers |
| `agents/studio_compositor/state.py` | Read overlay zone files, track mtime for cache invalidation |
| `agents/studio_compositor/models.py` | Add overlay zone content to OverlayState |

## What This Does NOT Include

- Interactive editing of overlay text from Logos UI (future)
- Overlay zone drag-and-drop positioning (future)
- Image/logo overlay (future — would use cairo surface compositing)
- Live markdown preview
