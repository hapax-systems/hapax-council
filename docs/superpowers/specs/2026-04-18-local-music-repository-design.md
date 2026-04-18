# Local Music Repository for Hapax — Design

**Date:** 2026-04-18
**Status:** Spec stub (provisional approval, dossier task #130)
**Source:** `docs/superpowers/research/2026-04-18-homage-follow-on-dossier.md` § #130
**Priority:** MED — depends on #127 (SPLATTRIBUTION), blocks #131 (SoundCloud), relates to #142 (vinyl rate)

---

## 1. Goal

Give Hapax a curated local music library it can draw from when the operator's turntable is silent. When `vinyl_playing == False` (signal defined by #127 SPLATTRIBUTION), the livestream's music bed stops being operator-selected vinyl and becomes Hapax-selected from a pre-licensed local pool.

**Operator directive:** Decouple music featuring from vinyl. Task #65 completed the attribution + overlay layer when vinyl *is* playing; this is the next layer — what Hapax features when the vinyl is quiet. No reliance on external streaming services in this stub (#131 SoundCloud is the sibling pathway, contingent on credentials).

**DMCA posture:** Every track in the pool is pre-licensed — operator-owned masters, CC-licensed releases, or public domain. No fingerprint-matchable commercial recordings. This is the primary safety invariant.

## 2. Repository Layout

**Root:** `~/music/hapax-pool/`

```
~/music/hapax-pool/
├── README.md                    # Operator-authored curation notes
├── index.json                   # Cached by LocalMusicRepository (rebuilt on mtime change)
├── operator-owned/              # Operator's own production output
│   ├── legomena-alpha/
│   │   ├── track-001.flac
│   │   └── track-001.yaml       # Per-track frontmatter
│   └── ...
├── cc-by/                       # CC-BY licensed tracks
├── cc-by-sa/                    # CC-BY-SA licensed tracks
├── cc0/                         # Public domain / CC0
└── other-licensed/              # Other explicit licenses (documented)
```

**Per-track YAML frontmatter schema** (`<track>.yaml` sidecar next to audio file):

```yaml
attribution:
  artist: "Oudepode"                    # Display name for splattribution
  title: "Cortado 3am"
  year: 2024
  url: "https://oudepode.bandcamp.com/track/cortado-3am"  # optional
license:
  spdx: "CC-BY-4.0"                     # SPDX ID or "operator-owned"
  attribution_required: true
  attribution_text: "Oudepode — Cortado 3am (CC-BY 4.0)"
mood_tags: [dusty, warm, contemplative, night]
bpm: 87.5                               # Required; float
key: "F minor"                          # Required; tonal key label
duration_seconds: 245
dynamics: { peak_dbfs: -1.2, rms_dbfs: -16.4 }  # optional
notes: ""                               # operator freeform
```

Frontmatter is parsed by `shared/frontmatter.py` (canonical parser — do not duplicate). Missing `bpm` or `key` → track is excluded from the selectable pool at load time with a log warning.

## 3. Selection Logic

`LocalMusicRepository.select_next(stimmung: StimmungVector, last_vinyl: TrackMeta | None) -> Track`:

1. **Filter to selectable:** license intact, `bpm` + `key` present, file exists.
2. **Stimmung score** (`0..1`, higher = better): cosine similarity between `stimmung.to_mood_vector()` and `track.mood_vector` (mood_tags embedded via `shared/embed.py`; cached in `index.json`).
3. **BPM affinity** (`0..1`): Gaussian around last vinyl BPM, σ = 6 BPM. If no last vinyl in the current session, uniform = 1.0.
4. **Key affinity** (`0..1`): Camelot-wheel distance from last vinyl key (same key = 1.0, adjacent = 0.8, relative minor/major = 0.7, tritone = 0.2). Uniform = 1.0 if no last vinyl.
5. **Repetition penalty** (`0..1`): last 5 plays stored in session memory; exact match = 0.0, otherwise 1.0.
6. **Final score:** `0.45 × stimmung + 0.25 × bpm + 0.20 × key + 0.10 × repetition_penalty`.
7. **Selection:** softmax with temperature `τ=0.35` (not strict argmax — preserves variety).

Top 3 candidates surface in Langfuse trace for operator auditability. Selected track's attribution text is written to `/dev/shm/hapax-compositor/music-attribution.txt` so `album_overlay.py` picks it up via the existing splattribution pathway (same contract as YouTube player's `yt-attribution-0.txt` write).

## 4. Rate Control

Environment variable **`HAPAX_LOCAL_MUSIC_PLAYBACK_RATE`** — parsed at playback start, defaults `1.0`, clamped to `(0.25, 2.0)`. Operator override to `0.5` for artistic reasons is a first-class case (mirrors `HAPAX_YOUTUBE_PLAYBACK_RATE` in `scripts/youtube-player.py:47`).

Implementation reuses the ffmpeg `setpts` / `atempo` preset from `youtube-player.py::VideoSlot.play`. No v4l2 output — audio-only path, straight to a named PipeWire sink (`hapax-local-music`) the compositor audio capture already consumes.

Unlike #142 (vinyl rate, operator-facing analog concern), this rate is purely a software knob on the local pool pathway. Default 1.0 because local tracks are already pre-licensed — no DMCA shield needed, fidelity preferred. The 0.5 override exists for aesthetic coupling with vinyl-mode pitch drops.

## 5. Gate — `vinyl_playing`

Entry condition: `vinyl_playing == False` (derived signal from #127, sourced from OXI One MIDI `transport_state` + `beat_position_rate`).

**State machine:**

- `IDLE` → `PLAYING`: when `vinyl_playing` latches False for ≥ 3 s (debounce against MIDI clock hiccups) AND a track is selectable.
- `PLAYING` → `PLAYING (next)`: when current track's ffmpeg exits cleanly (EOF marker via the same `hapax-finished-local-{id}` pattern as youtube-player); `select_next` runs, new track starts.
- `PLAYING` → `HALTING`: when `vinyl_playing` latches True. Current track is **not interrupted mid-play**. Halt occurs at the next track boundary. Audio sink is released so vinyl has the stage.
- `HALTING` → `IDLE`: at next track boundary, ffmpeg exits, state resets.

No crossfade on transition to vinyl — the vinyl's own turntable attack is the transition. On transition *from* vinyl back to local, a 2 s linear fade-in covers the gap. Both behaviors are observable via `hapax_local_music_state{state}` Prometheus gauge.

## 6. File-Level Plan

New files (under the council repo):

- `agents/studio_compositor/local_music/__init__.py`
- `agents/studio_compositor/local_music/repository.py` — `LocalMusicRepository` (loads `~/music/hapax-pool/`, caches `index.json`, exposes `select_next`)
- `agents/studio_compositor/local_music/player.py` — `LocalMusicPlayer` (ffmpeg subprocess, PipeWire sink, rate control, EOF watchdog — cribbed from `scripts/youtube-player.py::VideoSlot`)
- `agents/studio_compositor/local_music/gate.py` — `VinylGate` (reads `vinyl_playing` signal, runs the state machine)
- `agents/studio_compositor/local_music/attribution.py` — writes `music-attribution.txt` in the format `album_overlay._draw_attrib` expects
- `scripts/hapax-music-pool-validate` — CLI: walks the pool, verifies frontmatter, reports missing/invalid, suggests fixes
- `systemd/user/hapax-local-music.service` — owns the player process
- `config/local_music.yaml` — pool root, stimmung weight overrides, softmax τ

Modified:

- `shared/signals.py` — expose the `vinyl_playing` derived signal (depends on #127 shipping)
- `agents/studio_compositor/album_overlay.py` — nothing changes; it already reads `music-attribution.txt`

Out of scope for this stub: web UI for browsing the pool, operator-facing curation tools beyond the validate CLI, auto-ingest from new files (cron-rescan is sufficient v1).

## 7. Test Strategy

- `tests/studio_compositor/local_music/test_repository_selection.py` — stimmung + BPM + key fixtures → deterministic top-1, softmax reproducibility with fixed seed.
- `tests/studio_compositor/local_music/test_gate_state_machine.py` — vinyl on/off transitions, debounce, halt-at-boundary.
- `tests/studio_compositor/local_music/test_frontmatter_validation.py` — malformed YAML, missing BPM/key, bad license SPDX → all excluded with log lines.
- `tests/studio_compositor/local_music/test_rate_env.py` — `HAPAX_LOCAL_MUSIC_PLAYBACK_RATE` parsing, clamping, default.
- `tests/studio_compositor/local_music/test_attribution_write.py` — attribution text lands in the `album_overlay` contract format (three lines, matches existing parser).
- Property-based (Hypothesis): Camelot distance symmetry, stimmung cosine bounds, selection never returns unlicensed.

`uv run pytest tests/studio_compositor/local_music/ -q` must pass with all deterministic fixtures; no live ffmpeg calls in unit tests (mock `subprocess.Popen`).

## 8. Open Questions

1. **Pool bootstrap:** who curates the initial 20–50 tracks? Operator-owned output is obvious; CC seeding needs a one-shot ingest script that pulls from an operator-curated Bandcamp/Free Music Archive list. Out of scope here — new task if needed.
2. **BPM/key auto-tagging:** should the `hapax-music-pool-validate` CLI offer to compute BPM/key with `librosa` / `madmom` when missing, or strictly require operator to set them? Recommendation: offer but don't auto-write (frontmatter is operator-authored contract).
3. **Silence gap policy:** if the pool is empty or fully filtered out, does Hapax stay silent or fall through to #131 SoundCloud (when ready)? Recommendation: silent, with a Prometheus gauge `hapax_local_music_empty_pool=1` + throttled ntfy, and explicit opt-in for SoundCloud fallback.
4. **Session memory scope:** repetition penalty window — per-session, per-day, or rolling N plays? Recommendation: per-session + rolling 5 within session.
5. **Cross-session mood tracking:** should selections persist to Qdrant `operator-corrections` when the operator skips a track via UI? Defer until skip-UX exists.

## 9. Related

- **#127 SPLATTRIBUTION** (`docs/superpowers/specs/2026-04-18-splattribution-no-vinyl-design.md`) — upstream: defines the `vinyl_playing` signal this spec gates on. Blocks implementation.
- **#131 SoundCloud integration** (`docs/superpowers/specs/2026-04-18-soundcloud-integration-design.md`) — sibling source for the same `vinyl_playing == False` window. Inherits `HAPAX_LOCAL_MUSIC_PLAYBACK_RATE` semantics; fallback target when pool is empty or API unavailable.
- **#142 vinyl rate** — operator-facing turntable pitch concern; orthogonal to this rate but conceptually paired (both are "how fast does music play" knobs, one analog, one software).
- **`agents/studio_compositor/album_overlay.py`** — already reads `/dev/shm/hapax-compositor/music-attribution.txt`; unchanged consumer of this spec's attribution writes.
- **`scripts/youtube-player.py`** — reference implementation for ffmpeg rate control (`_playback_rate`), PipeWire sink naming, EOF watchdog, attribution contract.
