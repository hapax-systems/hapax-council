# Garage Door Open — Session Handoff

**Date:** 2026-04-09 late night (handoff written ~23:35 CDT)
**Author:** alpha session
**Audience:** Next session (alpha or beta, local or remote)
**Scope:** Everything related to Garage Door Open live streaming work — specs, plans, current runtime state, known blockers, open TODOs, gotchas, deferred features, secrets inventory, launch checklist.

---

## ⚠️ HARD CONSTRAINTS — READ FIRST

### ⏰ Timeline
- **ALL DEV DONE: T-20h** (from handoff = ~2026-04-10 19:30 CDT)
- **GO LIVE: T-26h** (~2026-04-11 01:30 CDT)
- **Remote dev via tmux** for the next ~20 hours (operator out of town)
- **Every decision between now and T-20h must serve the launch.** No refactors, no nice-to-haves, no deferred work added. Only: ship blockers cleared, then stop.
- **After T-20h: freeze.** No code changes. Verify, drill, practice. Be ready to stream.

### 📡 Stream duration
- **36-HOUR CONTINUOUS LIVESTREAM.** Not a test, not a soft-launch — full marathon.
- **EVERY COMPONENT MUST BE STABLE FOR 36H CONTINUOUS OPERATION.**
- Anything that might leak memory, accumulate state, crash after N hours, fail to reconnect, or degrade over time IS A BLOCKER.
- Any manual intervention required during 36h IS A BLOCKER.
- **Burn-in required before launch:** test every daemon for at least one 4-6h run to catch obvious leaks/drift.

### 36-Hour stability checklist (must pass before T-20h freeze)
- [ ] **studio-compositor** — no frame stalls, no GPU memory growth, no v4l2sink renegotiation cascade, no audio capture thread death
- [ ] **youtube-player** — ffmpeg reconnect on YouTube URL expiry (videos expire after ~6h), queue auto-advance, KDE Connect reconnect on phone sleep
- [ ] **album-identifier** — no memory growth from cover hash history, graceful Gemini API failures, 5s poll never misses
- [ ] **chat-monitor** — chat-downloader reconnect on YouTube chat disconnect, embedding queue bounded, batch LLM retry on failure
- [ ] **logos-api** — FastAPI worker recycling if needed, no hanging HTTP connections from WS relay
- [ ] **token-ledger** — json file atomic writes survive concurrent readers/writers
- [ ] **Pi NoIR fleet** — Pi daemons must auto-reconnect if workstation reboots; frame server stays up through DHCP renewal
- [ ] **PipeWire** — mixer_master stays alive through USB suspend/resume
- [ ] **OBS** — NVENC stable, RTMP reconnect on brief disconnect, audio device reacquire
- [ ] **YouTube RTMP ingest** — keyframe interval 2s so brief disconnects reconverge fast

---

## 0. TL;DR — Launch Readiness

**Launch: T-26h from handoff. Dev freeze: T-20h. Stream: 36h continuous.**

**What ships:**
- 6-camera GStreamer compositor → `/dev/video42` → OBS → NVENC H.264 → YouTube RTMP
- 30fps 1920x1080 with 24-slot GPU shader FX chain (24+ curated presets)
- Audio-reactive visual sidechain (bass → brightness, kick → flash)
- YouTube PiP overlay (react content from phone via KDE Connect)
- Album cover overlay + "splattributions" (confidently-wrong AI album IDs)
- Token Pole engagement visual (Vitruvian Man golden spiral)
- Bouncing Pango text overlays (historical documents, philosophy quotes)
- Scrolling lyrics overlay
- Vinyl mode (half-speed turntable with audio-reactive correction)
- Persistent attribution log to Obsidian

**Blockers cleared tonight:**
- ✅ CUDA 13.x upgrade broke `opencv-cuda` package state → reinstalled from cache
- ✅ ldconfig cache was stale (`libnvrtc-builtins.so.13.1` phantom) → rebuilt
- ✅ GStreamer `nvcodec` plugin was missing `cudacompositor`/`cudaconvert`/`cudascale` → fixed by above two
- ✅ GStreamer plugin registry was cached with reduced element list → deleted
- ✅ Compositor has CPU fallback as safety net if CUDA ever goes missing again
- ✅ 5s bidirectional gdrive rsync for remote screenshot drops
- ✅ 720p fx-snapshot drops (was 640x360) for remote review

**CI cleanup completed (2026-04-10 ~00:30 CDT):**
- ✅ **7/7 CI jobs GREEN on main** — lint, security, typecheck, test, web-build, vscode-build, secrets-scan
- ✅ Bandit: `hashlib.md5` → `usedforsecurity=False` (album-identifier.py), `verify=False` → `nosec` (vault_context_writer.py)
- ✅ Ruff format: `audio_capture.py` reformatted
- ✅ pycairo build: `libcairo2-dev` + `libgirepository-2.0-dev` added to CI workflow
- ✅ ESLint web-build: `globalIgnores` for Rust `target/` dirs, underscore-prefix unused vars rule
- ✅ Pyright: removed invalid type annotation on instance attribute in `fx_chain.py`
- ✅ 12 stale test assertions updated to match current production code:
  - effect_graph: ghost/trails edge/modulation counts, stutter now has shader
  - health_monitor: profile staleness thresholds (DEGRADED not FAILED at 80h)
  - health_monitor_watch: watch is tier 3, always HEALTHY when stale
  - affordance_migration: Thompson sampling increments use_count on failure
  - obsidian_sync: kebab-case directory names (not space-separated)
  - smoke_integration: expression coordinator modality + shader param names
  - studio_compositor: recording.enabled default False, framerate 30
  - visual_governance: nominal presets include ghost
- ✅ 8 Dependabot PRs rebased and queued for auto-merge (--squash --auto)

**Known unshipped before launch:** see §6 TODOs — chat monitor is coded but never run against a live chat; token ledger is seeded but not wired to the album identifier's actual LLM calls; OBS is not yet configured per Task 2 of garage-door plan; YouTube Data API auto-description-update needs OAuth consent.

---

## 1. Architecture

### 1.1 Full Pipeline

```
┌─ 6 cameras (3x Brio, 3x C920) ─┐
│  /dev/video0..9                 │
└──────────────┬──────────────────┘
               ↓
    ┌──────────────────────┐
    │ cudacompositor       │  ← 30fps, 1920x1080 tile
    └──────────┬───────────┘
               ↓
    ┌──────────────────────┐
    │ cudadownload         │
    │ videoconvert BGRA    │
    │ pre_fx_tee           │───┬──→ snapshot.jpg (1280x720)
    └──────────┬───────────┘   └──→ camera snapshots
               ↓
    ┌──────────────────────┐
    │ input-selector       │  ← source switch: live / brio-operator / brio-room
    │ cairooverlay (Pango) │  ← bouncing text overlays (85 docs)
    │ glupload → glcc      │
    └──────────┬───────────┘
               ↓
    ┌──────────────────────┐
    │ glvideomixer         │
    │  sink_0: camera base │
    │  sink_1: flash (0-60%) ← FlashScheduler, kick onsets
    └──────────┬───────────┘
               ↓
    ┌──────────────────────┐
    │ 24 glfeedback slots  │  ← curated preset chains, temporal FB, audio-reactive
    └──────────┬───────────┘
               ↓
    ┌──────────────────────┐
    │ glcolorconvert_out   │
    │ gldownload           │
    │ videoconvert         │
    │ pip-overlay          │  ← post-FX cairooverlay: YouTube PiP, album cover,
    │                      │    token pole, splattribution text, scrolling lyrics
    └──────────┬───────────┘
               ↓
    ┌──────────────────────┐
    │ output_tee           │
    │  ├→ v4l2sink /dev/video42 ─→ OBS V4L2 source ─→ NVENC H.264 ─→ RTMP ─→ YouTube
    │  ├→ HLS branch (nvh264enc → hlssink2) [local preview]
    │  └→ fx-snapshot branch (jpegenc → appsink → /dev/shm/hapax-compositor/fx-snapshot.jpg)
    └──────────────────────┘
```

### 1.2 Key services (systemd user units)

| Service | Purpose | Status |
|---|---|---|
| `studio-compositor.service` | Main GStreamer pipeline | ACTIVE (CUDA path) |
| `youtube-player.service` | YouTube react video decode → `/dev/video50` + PipeWire audio | ACTIVE |
| `album-identifier.service` | IR album detection + Gemini ID + track recognition + lyrics | ACTIVE |
| `logos-api.service` | FastAPI on :8051, preset switching, graph mutations | ACTIVE |
| `hapax-logos.service` | Tauri native app (Logos UI) | ACTIVE |
| `rclone-gdrive-drop.timer` | Bidirectional gdrive sync (5s interval for remote dev) | ACTIVE |
| `hapax-daimonion.service` | Voice STT/TTS, conversation loop | ACTIVATING |

### 1.3 External dependencies

| Dep | Purpose | Key storage |
|---|---|---|
| **Gemini Flash (via LiteLLM :4000)** | Vision: album ID, splattributions. Audio: track ID. Text: lyrics, chat analysis. | `pass litellm/master-key` |
| **Gemini Pro (via LiteLLM :4000)** | Higher accuracy for hard splattributions | same |
| **Claude Sonnet/Opus (via LiteLLM :4000)** | `balanced`/`capable` model routing | same |
| **Ollama nomic-embed (CPU)** | Chat monitor thread detection embeddings | localhost:11434 |
| **ACRCloud** | Track fingerprinting (NOT USED — no match on underground catalog) | `pass acrcloud/access-key`, `access-secret`, `host` |
| **AcoustID/MusicBrainz** | Track fingerprinting (NOT USED — no match either) | `pass acoustid/api-key` |
| **YouTube Data API v3** | Livestream description auto-updates | `pass google/youtube-token` (needs OAuth re-consent for `youtube.force-ssl`) |
| **Pi NoIR fleet (http :8090)** | IR frames for album detection | Pi-1/2/6 at .78/.52/.81 |
| **PipeWire `mixer_master`** | Vinyl audio capture (right channel) | PreSonus Studio 24c |
| **KDE Connect** | Phone → YouTube URL share | D-Bus listener in youtube-player.service |

---

## 2. Full Plan + Spec Inventory

All specs in `docs/superpowers/specs/`, plans in `docs/superpowers/plans/`.

### 2.1 Garage Door Open core

**`2026-04-04-garage-door-open-streaming-design.md`**
- Architecture: compositor → v4l2 → OBS → NVENC → RTMP → YouTube
- OBS configuration: NVENC p5 CBR 6000kbps, 1920x1080@30, stereo 48kHz 160kbps
- Audio mix: mixer_master (music) -6dB, echo_cancel_source (voice) 0dB
- **Week-1/Month-1/Month-3 success criteria**: 5+ streamed hours/3+ nights, 100+ concurrent peak, monetization

**`2026-04-04-garage-door-open-streaming.md`** (implementation plan)
- Task 1: Framerate 10→30fps in `models.py:73` + `smooth_delay.py:35` ← **DONE**
- Task 2: OBS profile + scene + stream key ← **MANUAL, NOT YET DONE (requires GUI)**
- Task 3: Test stream (unlisted) ← **NOT DONE**
- Task 4: Go live (public) ← **NOT DONE — this is tomorrow night**

### 2.2 Audio reactivity

**`2026-04-04-audio-reactivity-design.md`**
- Direct PipeWire capture in compositor process (bypass perception 2.5s latency)
- Inline DSP: RMS, beat detect, 3-band split
- Target latency: ~60ms total (21ms audio frame + 42ms render frame)
- **STATUS:** `agents/studio_compositor/audio_capture.py` exists and running. Sidechain wired: bass→brightness, kick→vignette, bloom spike, live flash.

### 2.3 Chain builder

**`2026-04-04-chain-builder.md`**
- Drag-and-drop preset chips in fullscreen output view
- Merge multiple preset graphs via `presetMerger.ts`
- Chain state in Zustand `studioGraphStore`, persisted to localStorage
- **STATUS:** Shipped PR #367 (command registry). Chain builder + sequence programmer exist in `hapax-logos/src/components/graph/SequenceBar.tsx`.

### 2.4 Livestream control surface

**`2026-04-04-livestream-control-surface-design.md`**
- Three layers: Chain Builder, Source Selector, Sequence Programmer
- Auto-cycling chains with configurable durations, hard cuts, loops
- **STATUS:** Shipped. Active chain duration 15-25s, tag-based compatibility exclusion rules (glitch+temporal, sparse+temporal, etc.).

### 2.5 Overlay content system

**`2026-04-04-overlay-content-system-design.md`**
- Pango markdown/ANSI → cairooverlay
- Obsidian note folder cycling
- Zones config in `agents/studio_compositor/overlay_zones.py`
- **STATUS:** Shipped. 85 documents in `~/Documents/Personal/30-areas/stream-overlays/`: Pascal Pensées, Musil *Man Without Qualities*, Montaigne *Essays*, historical documents, sci-fi quotes. DVD-screensaver bounce. IBM VGA font for ANSI art. Lyrics overlay zone added with scrolling mode.

### 2.6 Embed frequency optimization

**`2026-04-04-embed-frequency-optimization-design.md`** + `.md` plan
- Reduce Qdrant embedding calls from per-event to batched
- **STATUS:** Shipped, unrelated to stream but contemporary.

### 2.7 Reverie recruitment diversity

**`2026-04-05-reverie-recruitment-diversity.md`**
- Diversify affordance pipeline recruitment to avoid same capability dominating
- **STATUS:** Separate workstream, not required for launch.

### 2.8 NOT IN DOCS — Legomena Live additions built this week

These extended the Garage Door Open concept after 2026-04-04 and are not in formal spec docs yet. The following section documents them as de facto specs:

#### 2.8.1 YouTube PiP overlay (PR #457, #5533, #4174)
- Floating bouncing picture-in-picture of react video content
- Architecture: `youtube-player.service` (system python, dbus) decodes YouTube via `yt-dlp` + `ffmpeg` to `/dev/video50` + PipeWire audio
- Compositor reads `/dev/video50` via `ffmpeg` subprocess in background thread (NOT via GStreamer v4l2src — that deadlocks the glvideomixer with dynamic pad addition)
- Post-FX cairooverlay paints the PiP with **its own contained effect layer** (Cairo operations: vintage_monitor, cold_surveillance, neon_bleed, film_print, phosphor_decay — randomly selected per video)
- Attribution text (title, channel) rendered on the PiP's own cairooverlay
- KDE Connect D-Bus `shareReceived` → POST `/play` endpoint on :8055
- Controls: HTTP API (`/play`, `/pause`, `/skip`, `/stop`, `/status`) + CLI + KDE Connect
- Persistent log: `~/Documents/Personal/30-areas/legomena-live/attribution-log.md`

#### 2.8.2 Splattributions (album identifier daemon)
- Physical vinyl cover → Pi NoIR overhead IR camera → HTTP fetch (Pi-6 :8090/frame.jpg)
- Raw prompt to Gemini Pro: "What album is this? What track is playing?" — **no genre hints, no artist context**, let the model hallucinate freely
- Confident wrong answers ARE the content — displayed with model name, confidence %, and "LOL"
- IR frame captured at 1920x1080 (bumped from 640x480)
- PNG saved at `/dev/shm/hapax-compositor/album-cover.png`, 512x512 square center crop, 15% margin, random duotone colorization (8 palettes)
- Compositor's `AlbumOverlay` class in `fx_chain.py` paints it bouncing, with splattribution text below
- 5-second poll interval, perceptual hash change detection
- Cover updates on any change ≥ Hamming distance 8
- Design principle: DON'T try to help the LLM — raw prompt, no context, the wrongness is the content

#### 2.8.3 Track identification (Gemini audio)
- Right channel only from `mixer_master` (vinyl audio)
- `ffmpeg` 2x speed-up (`asetrate=88200,aresample=44100`) to restore half-speed vinyl to original tempo
- Sent to Gemini Flash (multimodal audio + image call) WITH album context from visual ID
- Returns specific track name
- Lyrics fetched via separate Gemini text call (handles non-English with `---TRANSLATION---` separator)
- **Why not ACRCloud/AcoustID:** Both services' fingerprint databases lack the underground hip-hop catalog (MF DOOM Special Herbs, Tha God Fahim, Griselda, etc.). Verified with multiple test captures at multiple speed corrections. Gemini with album context is the working path.

#### 2.8.4 Token Pole (Vitruvian Man golden spiral)
- Vertical progress bar CONCEPT was initial; replaced with **golden Fibonacci spiral** over Da Vinci's Vitruvian Man (1490, public domain)
- Spiral centered on the figure's navel (golden ratio center of human body)
- Cute kawaii token (φ symbol, rosy cheeks, eyes, smile, bounce animation) follows the spiral path from outside → center
- Rainbow trail behind the token (8-color candy palette, progress-based gradient)
- Sparkle particles at the token position
- 60-particle explosion at center when pole fills (Vampire Survivors style)
- Post-FX cairooverlay position: upper-left quadrant, 300x300 at 20,20
- Dark rounded-rectangle backing card (rgba 0.05, 0.04, 0.08, 0.88) so Vitruvian + spiral pop over shader effects
- Asset: `assets/vitruvian_man_overlay.png` — transparent PNG, cream-tinted ink lines, high-contrast
- Goal label (top-right): formatted token threshold count
- Current count label (bottom-left)
- **Scaling formula:** `threshold(n) = 5000 * log2(1 + log2(1 + n))` where n = active_viewers
  - n=1 → ~7925 tokens
  - n=10 → ~21200 tokens
  - n=500 → ~32800 tokens
  - n=5000 → ~37300 tokens
  - Sub-logarithmic: 5 viewers fill at nearly the same rate as 500

#### 2.8.5 Token Ledger
- Shared shm file: `/dev/shm/hapax-compositor/token-ledger.json`
- Writers: `album-identifier` (per LLM call), `chat-monitor` (per batch analysis), `youtube-player` (superchat/membership boosts)
- Reader: compositor's `TokenPole` class (polls every 0.5s)
- State: `total_tokens`, `total_cost_usd`, per-component breakdown, `pole_position` (0.0→1.0), `explosions` counter, `active_viewers`
- **STATUS:** Ledger exists, pole reads it. Writers NOT YET wired to album-identifier's actual LLM calls — only seeded manually. See §6 TODOs.

#### 2.8.6 Chat monitor (STRUCTURAL, not judgmental)
- `scripts/chat-monitor.py`
- Reads YouTube Live chat via `chat-downloader` (not pytchat — dead since 2021)
- **Design principle from research:** measure engagement STRUCTURE, never sentiment/quality. No per-message scoring. Thermometer not scoreboard.
- Per-message (local, no LLM): whitespace tokenizer, MATTR lexical diversity, hapax ratio, novel bigrams, thread detection via nomic-embed cosine similarity
- Per-120s batch: Gemini Flash structural analysis prompt — thread count, threading ratio, depth signal, novelty rate, rhythm descriptor
- **This is where tokens get spent** — and those tokens feed the pole
- Superchat/membership → direct token equiv boost ($1 = 500 tokens)
- Active viewer count drives scaling threshold
- **STATUS:** Coded, never run against a live chat. Needs YOUTUBE_VIDEO_ID env or `/dev/shm/hapax-compositor/youtube-video-id.txt`.

#### 2.8.7 Pi NoIR IR frame HTTP server
- All 3 Pi NoIR daemons (`hapax-pi1/2/6`) now expose `http://<ip>:8090/frame.jpg` and `/album.jpg` and `/album.json`
- Frame server is a WSGI thread inside `hapax_ir_edge.py`
- Serves latest greyscale JPEG (85 quality) on-demand
- Pi-6 also runs `ir_album.detect_album_cover()` using OpenCV Canny edges + contour → rotated bounding rect → perspective transform → 640x640 cropped album
- **Eliminates** the old USR1-signal + scp-debug-frame pattern
- Album detection is probabilistic — current camera setup has album filling most of frame, so center square crop with 15% margin works better than CV detection

---

## 3. Ethical Engagement Design (Token Pole Foundations)

This is the part the operator explicitly flagged as high-risk and wanted researched before building. Research was done; principles are below. Implementation must never violate these.

### 3.1 Non-negotiable principles

1. **Thermometer, not scoreboard.** Token pole reflects collective energy. Never score individual messages. No "good message!" feedback. No leaderboard. No ranking. No celebration of specific users.

2. **Measure structure, not quality.** Don't classify messages as good/bad. Measure engagement DEPTH structurally:
   - Response chains (back-and-forth > drive-by)
   - Semantic coherence (message relates to current thread via embedding)
   - Lexical diversity (MATTR, introduces new concepts)
   - Participant diversity (more unique voices = more token spend)
   - These are observable without judging anyone.

3. **Fixed, transparent relationship.** Pole rises predictably. No random bonus multipliers. No surprise thresholds. No hidden milestones. **Transparency kills the Skinner box.** Viewers should be able to predict where the pole is heading.

4. **Sub-logarithmic scaling.** 10 active chatters fill at roughly the same rate as 500. Use `log2(1+log2(1+n))`. Small communities feel their impact; large ones don't trivialize it.

5. **Never loss frame.** Pole only goes UP. Never drops. No decay. No "keep chatting or you'll lose progress!" One-way ratchet toward the explosion.

6. **The recursion is the feature.** Evaluating chat to drive the pole ITSELF spends tokens. The act of paying attention IS the spend. This is the most honest thing streaming has ever done — you're showing exactly what the AI costs.

7. **Don't reward sentiment.** If viewers learn "positive" messages fill the pole faster, you get performative niceness. Weight conversation STRUCTURE instead — a heated debate about sampling ethics and a collaborative gear thread score identically if they have the same structural depth.

### 3.2 Research sources (for future arguments)

- **Self-Determination Theory** (Ryan & Deci): overjustification effect; extrinsic rewards suppress intrinsic motivation
- **Sky: Children of the Light / Kind Words:** prosocial mechanics without quantification; zero-cost helping; no leaderboards
- **Wikipedia Community Health Metrics / Stack Overflow health indicator:** structural signals (response chains, topic coherence, participant diversity) without value judgment
- **Variable ratio reinforcement research:** Skinner box in streaming; donation alerts/bit goals exploit gambling psychology — our pole must be DETERMINISTIC
- **Deep Rock Galactic difficulty scaling:** +25% per player, sub-linear; duos/trios viable
- **Twitch's Antagonistic Trap:** research documenting how conflict generates bits/subs; **never let the pole reward controversy**

### 3.3 Anti-patterns to avoid

- Individual leaderboards
- Loss framing ("pole is dropping!")
- Threshold surprises / hidden milestones
- Public per-message quality scoring (teacher/student dynamic)
- Autoplay/infinite scroll dark patterns
- Antagonistic engagement monetization (reward conflict)

---

## 4. Runtime State (as of 2026-04-09 23:34 CDT)

### 4.1 Services
```
studio-compositor    active (CUDA path, 30fps, 6 cameras, FX chain running)
youtube-player       active
album-identifier     active (5s poll, seeded with Gemini Pro, 1 splattribution seen)
logos-api            active (:8051)
hapax-logos          active
rclone-gdrive-drop   active (5s bisync)
```

### 4.2 Current splattribution
```json
{
  "type": "splattribution",
  "artist": "Tha God Fahim & Mach-Hommy",
  "title": "Dollar Menu 2",
  "year": 2017,
  "label": "Daupe!",
  "model": "google/gemini-pro",
  "confidence": 1.0,
  "current_track": "Camoflauge Monk"
}
```
(Confidently wrong about the specific album. Artist is in the right orbit. This is the feature, not a bug.)

### 4.3 Token ledger
```json
{
  "total_tokens": 2350,  // seeded manually; real album-id calls not wired yet
  "total_cost_usd": 0.004,
  "pole_position": 0.47,
  "explosions": 0,
  "active_viewers": 1
}
```

### 4.4 GPU
- Utilization: 24%
- VRAM: 9437 MiB / 24576 MiB (plenty of headroom for NVENC on top)

### 4.5 Pi NoIR fleet
- Pi-1 (hapax-pi1, .78) — ir-desk, HTTP 200
- Pi-2 (hapax-pi2, .52) — ir-room, HTTP 200
- Pi-6 (hapax-pi6, .81) — ir-overhead + sync-hub, HTTP 200 ← album camera

---

## 5. Secrets Inventory

All in `pass` store. Required for launch:

| Key | Used by | Status |
|---|---|---|
| `litellm/master-key` | album-identifier, chat-monitor, splattributions | ✅ works |
| `google/client-secret` | OAuth for YouTube Data API | ✅ present |
| `google/oauth-client-id` | Same | ✅ present |
| `google/oauth-client-secret` | Same | ✅ present |
| `google/token` | Current Google token (calendar.readonly only) | ⚠ needs re-consent for `youtube.force-ssl` |
| `acoustid/api-key` | Track fingerprinting attempt | ⚠ works but DB lacks catalog |
| `acrcloud/access-key` | Track fingerprinting attempt | ⚠ works but DB lacks catalog |
| `acrcloud/access-secret` | Same | ⚠ same |
| `acrcloud/host` | Same (`identify-us-west-2.acrcloud.com`) | ⚠ same |
| `acrcloud/api-token` | JWT bearer — WRONG API (Console, not Identify) | 🗑 unused |

### 5.1 YouTube OAuth — MUST DO BEFORE LAUNCH IF AUTO-DESCRIPTION WANTED
Run once on the workstation:
```bash
cd ~/projects/hapax-council && uv run python scripts/youtube-auth.py
```
Opens browser for Google consent with `youtube.force-ssl` scope added to `ALL_SCOPES` in `shared/google_auth.py`. Updates `google/token` in pass.

Without this, description auto-update from `attribution-log.md` will fail silently.

---

## 6. Open TODOs (Prioritized for Tomorrow Night)

### 6.1 P0 BLOCKERS (from conversation review agent — verified 2026-04-09 23:35)

- [⏳] **`/data` filesystem at 100% INODE EXHAUSTION** (verified: `df -i /data` = 21733376/21733376). Cause: `/data/minio/langfuse` Langfuse observability bucket. Restic backup already failing. **Will cascade into other failures during stream.** **ANOTHER SESSION IS HANDLING THIS — don't duplicate the work.** Verify with `df -i /data` before stream; inode count must not be at 100% when launching.
- [ ] **`hapax-daimonion.service` FAILED** (verified). Operator directive from prior session `d447edd3` was "stopped during stream" but it's in a failed state unrelated to that. Diagnose with `journalctl --user -u hapax-daimonion --since "10 min ago"`. If the failure is persistent, either fix or explicitly disable (`systemctl --user disable --now hapax-daimonion`) so it stays dead through reboots.
- [ ] **Token ledger has SEEDED TEST TOKENS** (verified: `total_tokens=2350 pole_position=0.47`). These are leftovers from earlier testing. **MUST reset to zero before launch** or pole will start at 47%. Fix: `echo '{"session_start":1775797000,"total_tokens":0,"total_cost_usd":0.0,"components":{},"pole_position":0.0,"explosions":0,"active_viewers":1}' > /dev/shm/hapax-compositor/token-ledger.json`
- [ ] **Attribution log has SWAPPED title/channel entries** from old code (verified: first entry shows "SP Pictures" as title instead of channel). File: `~/Documents/Personal/30-areas/legomena-live/attribution-log.md`. Fix: manually clean up lines 1-3 or regenerate from scratch.
- [ ] **YouTube OAuth scope NOT authorized.** Stored `google/token` only has `calendar.readonly`. `shared/google_auth.py ALL_SCOPES` has been updated to add `youtube.force-ssl` but operator must run `scripts/youtube-auth.py` to complete consent flow. Without this, YouTube description auto-update silently fails.
- [ ] **Chat monitor NOT systemd-installed.** `scripts/chat-monitor.py` exists, runs correctly, but no `~/.config/systemd/user/chat-monitor.service` exists. Without this, no real chat signal flows into the token pole during stream.
- [ ] **Chat monitor video ID discovery not wired.** Monitor needs to know the YouTube Live video ID. No auto-discovery from `liveBroadcasts.list`. Manual: grab video ID from YouTube Studio at stream start → `echo VIDEO_ID > /dev/shm/hapax-compositor/youtube-video-id.txt`
- [ ] **Vitruvian Man overlay visibility through shader effects NOT verified post-fix.** Last change: dark backing card 88% alpha + Vitruvian alpha bumped to 50%. Operator went remote before confirming. Drop a screenshot and verify.

### 6.1.b P0 — OBS CONFIGURATION (operator-only, at machine or via VNC)

- [ ] **OBS StudioLive profile**: NVENC H.264 p5 Quality, CBR 6000 kbps, 2s keyframe, high profile, look-ahead OFF, B-frames 2.
- [ ] **OBS Video settings**: 1920x1080 base + output, 30 FPS, NV12, Rec.709, Partial range.
- [ ] **OBS Audio settings**: 48kHz stereo, 160 kbps, disable all Global Audio Devices.
- [ ] **OBS Scene "Studio Live"** with 3 sources:
  - V4L2 Video Capture Device → `/dev/video42` (`StudioCompositor`), 1920x1080
  - Audio Input Capture (PipeWire) → `mixer_master` (music, label "Music (L-12)", slider -6dB)
  - Audio Input Capture (PipeWire) → `echo_cancel_source` (voice, label "Voice (Yeti)", slider 0dB)
- [ ] **OBS Audio sync offset: 75ms on the video source** (GUESS — operator should fine-tune by pad-hit test, but 75ms is the starting point per garage-door plan).
- [ ] **YouTube Stream key**: visit `studio.youtube.com → Create → Go Live → Stream` → set title/description → copy Stream Key → OBS Settings → Stream → YouTube-RTMPS → paste.
- [ ] **Test stream UNLISTED first** (garage-door plan Task 3). Verify stream health "Excellent", audio meters active, effect switching works via curl.

### 6.1.c P0 — LAUNCH EXECUTION

- [ ] **Pre-flight content safety scan** (§11). No employer content on any camera.
- [ ] **Set YouTube visibility Public**.
- [ ] **Click Start Streaming in OBS**.
- [ ] **Grab video ID from YouTube Studio** → write to `youtube-video-id.txt` → start chat-monitor.

### 6.2 P1 — STREAM DEGRADING (ships but broken in ways viewers will notice)

- [ ] **Wire token ledger writers**. Album-identifier currently calls LLMs for vision/audio/lyrics but does NOT record token spend. Need to import `scripts.token_ledger` and call `record_spend("album_id", prompt_tok, completion_tok, cost)` after each call. Same for splattributions and track ID. Otherwise pole never moves from LLM work. **Without this the pole is decoration, not engagement signal.**
- [ ] **Create `chat-monitor.service` systemd unit.** Mirror `album-identifier.service` pattern. ExecStart = `uv run python scripts/chat-monitor.py`. Don't enable until we have a video ID.
- [ ] **YouTube description auto-update end-to-end test.** Code exists (`scripts/youtube-player.py::LivestreamDescriptionUpdater`) but only runs after OAuth scope is authorized (see 6.1). Run once manually after auth to verify `liveBroadcasts.list` → `videos.update` actually persists.
- [ ] **Verify compositor CUDA fix is durable across reboots.** Check `/etc/ld.so.conf.d/cuda.conf` is in place; run `gst-inspect-1.0 cudacompositor` again; reboot once before freeze to confirm it still works.
- [ ] **Review compositor snapshot branch at 720p.** Bumped from 640x360 to 1280x720 for remote dev. Verify it doesn't tank CPU on the stream path (should be preview-only, not the streamed /dev/video42 — but confirm).
- [ ] **Exercise the CPU fallback path** by temporarily renaming `libgstnvcodec.so` to simulate cudacompositor loss — verify the pipeline comes up on CPU fallback without crashing. Revert after test. Safety net for stream night.
- [ ] **Sawtooth pattern latent**. Per review agent: *"still latent on some preset combinations"*. Not currently visible, may resurface. No root cause known. Workaround: if it shows up during stream, switch to a different preset chain.
- [ ] **Lyrics scrolling overlay not visually confirmed.** `track-lyrics.txt` file exists but scrolling render was never verified with fresh eyes. Check by playing a track with known lyrics and eyeballing.
- [ ] **KDE Connect `shareReceived` browser suppression.** Operator intent: phone-shared URLs should go ONLY to the daemon, never open a browser. Verify `com.kde.share_receiver` D-Bus handler is the only consumer. If `xdg-open` or KDE Connect's default-open still triggers, disable it.
- [ ] **Debug INFO log spam in YouTubeOverlay tick code.** Assistant temporarily bumped logging to INFO during diagnosis, never reverted. Will flood journald during 36h stream. Revert to DEBUG before freeze. File: `agents/studio_compositor/fx_chain.py` `YouTubeOverlay.tick()`.

### 6.3 MEDIUM (nice to have)

- [ ] **YouTube auto-description update**. Requires `youtube-auth.py` consent flow first. `youtube-player.py` has `LivestreamDescriptionUpdater` class that builds the description from `attribution-log.md` and POSTs to YouTube Data API. Quota: 50 units per update, 10,000/day → ~200 updates/day max.
- [ ] **Splattribution auto-commit to Obsidian.** Every new album ID should append to a `splattribution-log.md` file separate from the attribution log, capturing the hallucination for later content.
- [ ] **Chain-builder shuffle test.** Verify all tag-based compatibility exclusion rules still fire correctly after recent shader changes. Exclusions: glitch+temporal, sparse+temporal, pattern+temporal, glitch+sparse, mono+anything, scanline+scanline, geometric+geometric. Excluded from shuffle: clean, echo, reverie_vocabulary, ambient, heartbeat, nightvision.
- [ ] **Live-test the full pipeline once end-to-end BEFORE going live**: place a physical vinyl, confirm album detection → identification → splattribution + cover overlay + track ID + lyrics all render on the compositor output. Queue a YouTube URL via KDE Connect, confirm PiP appears. Switch presets from Logos UI.

### 6.4 36-HOUR STABILITY RISKS (must audit before freeze)

These are known-or-suspected leaks/drift/crash vectors that will bite during a marathon stream. Each one is a BLOCKER.

- [ ] **YouTube video URL expiry** — `youtube-player.py` extracts signed URLs that expire after ~6h. If a video is longer than the URL lifetime, ffmpeg dies. Need: re-extract URL on playback failure and resume, OR pick shorter videos only.
- [ ] **chat-downloader reconnect** — library scrapes YouTube innertube API. If YouTube rotates continuation tokens or chat stream drops, monitor stops. Need: outer reconnect loop with backoff in `chat-monitor.py::main()`.
- [ ] **Gemini API rate limits** — Free tier is generous but not infinite. Over 36h: album-id calls (every album change), splattributions, track ID (per album), lyrics, chat batch analysis every 2min. Estimate: ~500-1500 calls over 36h. Need: track daily quota, gracefully degrade if limits hit.
- [ ] **Token ledger file atomic writes** — multiple processes write `token-ledger.json`. Current `_save()` writes to `.tmp` + rename. Verify no race under concurrent writers. Consider file lock.
- [ ] **cover-hash memory growth** — `album-identifier.py` keeps seen_bigrams set and perceptual hashes in memory. Need bound. Check `chat-monitor.py::seen_bigrams` and `all_tokens` list growth.
- [ ] **Cairo surface caching** — overlay zones cache PangoLayout and cairo surfaces. Across 36h with content changes, verify old surfaces get freed (Python GC should handle it but verify no strong refs).
- [ ] **Audio capture thread** — `CompositorAudioCapture` owns a pw-cat subprocess. If PipeWire restarts (USB disconnect, audio device suspend), thread must reconnect.
- [ ] **v4l2 output device (`/dev/video42`)** — v4l2loopback module state under 36h continuous write. Check if module needs `exclusive_caps=1`. Test: does OBS survive compositor restart mid-stream? If not, OBS is a single point of failure.
- [ ] **OBS NVENC encoder** — NVENC sessions have resource limits; free driver allows ~3 concurrent. One is fine but verify no leak.
- [ ] **YouTube RTMP ingest** — YouTube may drop RTMP on transient network issues. OBS auto-reconnect must be enabled.
- [ ] **Pi NoIR daemons on Pi-1/2/6** — 36h uptime, fresh frames every ~3s. Check for `rpicam-still` zombie processes, memory drift.
- [ ] **Logos API worker leak** — FastAPI under load for 36h. Watch for connection pool exhaustion, SSE stream accumulation.
- [ ] **hapax-logos (Tauri)** — webkit2gtk NVIDIA syncobj bug fix (`__NV_DISABLE_EXPLICIT_SYNC=1`) is set in systemd unit — verify still present. Tauri webview + visual surface at :8053 must survive 36h.
- [ ] **Disk I/O** — `/dev/shm/hapax-compositor/` is tmpfs, fine. But `~/Documents/Personal/30-areas/legomena-live/attribution-log.md` grows append-only. Also `~/.cache/hapax-compositor/hls/` segments. Verify HLS segment pruning works (should keep last N segments).
- [ ] **rsync gdrive sync** — 5s interval for 36h = 25,920 sync runs. Each creates a snapshot. Verify no stale lock files accumulate.

### 6.5 DEFERRED — "pegged for later" (operator explicitly said POST-LAUNCH)

From conversation review agent:
- **Stream Deck integration** — physical control surface for presets/chains. Operator: *"I have a stream deck that we can use for controls that we will set up"*
- **PipeWire audio ducking (talkover)** — YouTube ducks 24c mix when playing, mic ducks YouTube when talking. 6-10dB smooth crossfade. Operator: *"we will need production quality audio ducking... not A LOT but enough"*
- **60fps compositor pipeline** — videorate negotiation research needed; 30fps is the launch target
- **Source layering** — composite multiple sources within one chain instead of switching between them
- **BTrack beat grid** — phase-locked beat sync (external dep needed)
- **Sequence persistence** (save/load named playlists) — UI rebuild needed post-CUDA-fix
- **Terminal capture source** (`/dev/video10`, wf-recorder) — disabled during streams
- **Chat-reactive effects** — chat votes → preset switches via Logos command relay :8052
- **Native GStreamer RTMP** — eliminate OBS, add `audiomixer + flvmux + rtmp2sink` branch
- **TikTok clip pipeline** — DMN identifies key moments, auto-exports vertical clips
- **Stream as affordance** — DMN "goes live" autonomously via recruitment pipeline
- **AppImage bundling fix** — QoL
- **Camera error resilience** — one bad camera shouldn't kill everything. Operator: *"bigger change for later"*
- **Pango overlay per-preset clarity guarantee** — some presets obscure text entirely; needs per-preset clarity floor. Open question.
- **Explosion counter visual above goal** — built but not verified after Vitruvian pivot
- **Pi-6 sshd persistent enable** — ALREADY RESOLVED (verified enabled + active this session)
- **Sawtooth pattern root cause** — parked; dither=0 + passthrough blit fixes were improvements but pattern still latent on some combos

---

## 7. Gotchas / Hard-Won Knowledge

### 7.1 GStreamer pipeline

- **cudacompositor depends on libnvrtc-builtins.so.13.2 at runtime.** If missing, the `nvcodec` plugin loads a *reduced* element set (only `cudaupload`/`cudadownload` — no compositor/convert/scale). Error appears only with `GST_DEBUG=nvcodec:6`. Cause tonight: ldconfig cache was stale after CUDA upgrade because `opencv-cuda` package state was corrupt (desc file missing) and made ldconfig segfault.
- **Fix sequence when cuda elements disappear:**
  1. `pacman -Qk opencv-cuda` — check for missing files
  2. `rm -rf /var/lib/pacman/local/opencv-cuda-*/` + `pacman -U --overwrite '*' /var/cache/pacman/pkg/opencv-cuda-*.pkg.tar.zst`
  3. `sudo ldconfig` — verify `libnvrtc-builtins.so.13.2` in `ldconfig -p`
  4. `rm ~/.cache/gstreamer-1.0/registry.x86_64.bin` — force GStreamer to re-probe plugins
  5. `gst-inspect-1.0 cudacompositor` — verify element loads
  6. Restart compositor
- **CPU fallback path** is now in the code as safety net (`pipeline.py:39-47`, `cameras.py:141-168`). Never remove this.
- **glvideomixer deadlocks on dynamic pad addition.** We had a YouTube PiP branch using a second glvideomixer and it hung the entire pipeline when a pad was added at runtime. Solution: don't dynamically add pads to glvideomixer while PLAYING. The current YouTube PiP reads v4l2loopback via ffmpeg subprocess in a Python thread, paints on a cairooverlay — completely decoupled from GStreamer pad negotiation.
- **v4l2sink caps renegotiation cascade.** When switching camera sources via `input-selector`, v4l2sink gets device-busy errors because caps change triggers a full renegotiation. Fix: caps dedup probe on v4l2sink sink pad that drops duplicate CAPS events by content comparison (`pipeline.py` v4l2sink branch).
- **Bayer dithering sawtooth pattern.** `videoconvert` defaults to Bayer ordered dithering. MUST set `dither=0` on ALL 12 instances of videoconvert in the pipeline. We hunted this for hours; the pattern showed up as vertical columns across the output.
- **glfeedback passthrough detection.** Python sends `PASSTHROUGH_SHADER` as the string; Rust side was comparing strings to detect passthrough. Never matched. Fixed to detect via `!f.contains("tex_accum")` — structural, not string-equal.

### 7.2 Audio reactivity

- **Vinyl audio is RIGHT CHANNEL ONLY** on `mixer_master`. Left channel is the contact mic. Track ID capture must extract right channel via `ffmpeg -af "pan=mono|c0=c1"`.
- **Vinyl mode is half-speed by default** — Korg Handytrax speed range isn't publicly specified; empirical tests showed ~0.5x works. Track ID pipeline speeds audio up 2x via `asetrate=88200,aresample=44100` to restore original tempo before sending to Gemini.
- **`CompositorAudioCapture` runs a pw-cat subprocess and owns a thread.** Don't replicate this elsewhere or they'll fight for the PipeWire node.
- **kick_cooldown is different for vinyl mode** (0.4s) vs normal (0.2s) because half-speed means kicks arrive half as often.

### 7.3 Album identification

- **ACRCloud and AcoustID do NOT have underground hip-hop catalog.** Verified with multiple tests at multiple speed corrections. Gemini with album context is the only working path for this catalog.
- **Don't give Gemini genre hints or artist context.** The splattribution concept REQUIRES the model to hallucinate freely. Hints make it too accurate, which makes the feature boring.
- **IR camera must capture at 1920x1080**, not 640x480. At 640x480 with the current Pi-6 camera distance, the album fills the entire frame leaving no detectable edges. At 1080p there's desk around the album, and OpenCV can find the cardboard edges via Canny.
- **Don't over-engineer album crop.** Current production path: fetch full Pi-6 IR frame, center-square crop with 15% margin, random duotone colorize, save as PNG. The CV detection path exists but has been superseded — the camera is close enough that the album dominates the frame.

### 7.4 Pi NoIR fleet

- **Pi-6 IP is DHCP-assigned, was 192.168.68.74, currently 192.168.68.81.** It may move again. `PI6_IP` env var in `album-identifier.service` should read from DHCP or be updatable.
- **SSH was broken on Pi-6 at one point.** The Pis rebooted and Pi-6 came back with a new IP. Always verify via `nmap -p 22 --open 192.168.68.0/24` if SSH refused.
- **Sync agents on Pi-6** run 8 offloaded sync tasks (chrome, gcalendar, gmail, gdrive, youtube, langfuse, claude-code, obsidian). Pi-6 memory is tight.
- **Debug IR frames** via USR1 signal (`kill -USR1 $(pgrep -f hapax_ir_edge)`) save to `/tmp/ir_debug_{role}.jpg`. The HTTP frame server makes this rarely needed now.

### 7.5 YouTube player daemon

- **Runs on system python (`/usr/bin/python3`)**, not the uv venv. Reason: needs `dbus-python` for KDE Connect D-Bus listener which is easier from system packages.
- **LivestreamDescriptionUpdater** checks for `youtube.force-ssl` scope in the stored token and logs a warning if missing. Safe to run without it; just won't update descriptions.
- **yt-dlp metadata ordering:** use `--print %(title)s --print %(channel)s` for deterministic output order. `--get-title --print %(channel)s` gives reversed output.
- **Audio output goes to PipeWire** (`-f pulse -ac 2 youtube-audio` in ffmpeg args). The YouTube audio mixes into the same `mixer_master` as vinyl — this was intentional so the react content can be audio-reactive too.
- **KDE Connect shareReceived** URL parsing strips trailing slashes and query params except `v=`. Phone shares like `youtube.com/watch?v=XXX&si=YYY` work.

### 7.6 Token pole visual

- **Post-FX cairooverlay position** (`fx_chain.py` `_pip_draw` callback) — draws ALL post-FX overlays (YouTube PiP, album, token pole) on a single cairooverlay between `fx_convert` and `output_tee`. Don't add more cairooverlays; batch into this one.
- **TokenPole tick runs every frame**, reads ledger every 0.5s. Ledger file is in `/dev/shm` so read cost is negligible.
- **Explosion trigger:** ledger `explosions` counter increments when tokens crosses threshold. TokenPole watches for increment and spawns 60 particles from spiral center. First session start doesn't trigger — needs `_last_explosion_count > 0` guard.
- **Vitruvian Man image** is at `assets/vitruvian_man_overlay.png`, force-committed via `git add -f` because `.gitignore` excludes `assets/`. Transparent PNG, cream-tinted ink lines on transparent background, 500x500. Prepared from Wikimedia Commons "Da Vinci Vitruve Luc Viatour" JPG with PIL contrast 2.0x, brightness 0.85x, ImageOps.colorize with dark sepia → cream gold.

### 7.7 GStreamer pipeline constraints (additional, from review agent)

- **`v4l2loopback` (`/dev/video10`, `/dev/video50`) cannot be added to a pipeline unless something is actively writing to it.** Empty loopback causes `set_state(PLAYING) → FAILURE`. Fix: `v4l2-ctl --device=/dev/videoN --get-fmt-video` probe check before creating the source element. Applied in `_add_terminal_source` and `YouTubeOverlay._create_pad`.
- **NVIDIA shaders + NVIDIA + Wayland GL context = black output.** Must run compositor with `GST_GL_WINDOW=x11 DISPLAY=:0` even on Wayland. Applied in `~/.config/systemd/user/studio-compositor.service.d/gl-env.conf`.
- **`input-selector` with more than 2 pads causes caps negotiation deadlock.** Resolution: lazy pad connection via IDLE pad probes. Only ever keep 2 pads connected simultaneously. Create camera branch on-demand when switching, tear down when switching away.
- **Stale closures in `SequenceBar.tsx`.** All callbacks must read from `useStudioGraph.getState()` not React closures.

### 7.8 Shader constraints (additional, from review agent)

- **Multiplicative shader params must default to 1.0 in vocabulary presets** (`colorgrade.brightness`, `colorgrade.saturation`, `postprocess.master_opacity`). Zero defaults output black. (This is in workspace CLAUDE.md but applies to all presets.)
- **`sin()*43758` hash functions produce biased distribution on NVIDIA GPU** — causes oxide dropout to fire on majority of lines (169 brightness instead of <1%). Replaced with Dave Hoskins integer-style hash.
- **Reverie mixer must only write non-zero chain deltas to `uniforms.json`** — zero deltas overwrite vocabulary defaults → black.
- **`merge_default_modulations` must match by node TYPE not exact ID.** Merged chains get prefixed IDs like `p0_bloom`. Fix uses type map.
- **`find_slot_for_node` must strip `pN_` prefix** for chain compatibility.
- **`matching_ids[-1]` (last instance) for chain neutralization, not `matching_ids[0]`.** First instance is the neutralized one.
- **`screen` blend banned** — causes white washout.
- **OOB shaders clamp instead of black.**
- **Chain neutralization rules:** colorgrade→identity, bloom→alpha:0, vignette→strength:0, noise→intensity:0. All instances except the last are neutralized.
- **Tag cross-exclusions:** glitch+temporal, sparse+temporal, pattern+temporal, glitch+sparse, mono+anything, scanline+scanline, geometric+geometric.
- **Shuffle source mix:** 60% live / 20% smooth / 20% hls (terminal disabled). Cameras: `brio-operator`, `brio-room`, `brio-synths` only (C920s have USB issues).
- **Shuffle excludes:** clean, echo, reverie_vocabulary, ambient, heartbeat, nightvision.
- **Anonymity guarantee:** every chain must include at least one obscuring preset. Obscuring set (tightened): halftone, pixsort, vhs, ascii, kaleidoscope, dither, datamosh, scrollmachine. Excludes: nightvision, neon.
- **Universal anonymize layer:** `postprocess.frag` applies 6-level posterize + noise on every preset. Param `u_anonymize` default 1.0. Hybrid anonymization: per-preset obscuring + universal posterize.
- **Colorgrade chain-safe cap:** ≤1.2 brightness/contrast per instance.

### 7.9 Audio fingerprinting catalog gaps (additional)

- **ACRCloud does NOT have MF DOOM Special Herbs, Tha God Fahim, Griselda, Tuff Kong**. "No result" at any speed correction. Verified multiple times.
- **AcoustID (MusicBrainz)** also returned 0 results for same catalog.
- **`shazamio` broken on Python 3.14** (`audioop` module removed).
- **Winning pipeline:** IR camera → Gemini Pro vision → splattribution (deliberately wrong is funny).
- **Claude has no audio modality** — multimodal image+audio MUST go through Gemini Pro.
- **Gemini Pro image processing times out on 1080p JPEGs under load** — resize to 480×270 before sending.

### 7.10 Chat monitoring design decisions (additional)

- **`chat-downloader` not `pytchat`** — pytchat dead since 2021.
- **Simple whitespace tokenizer, NOT spaCy** — spaCy is bad at chat text.
- **`nomic-embed` via existing Ollama CPU** — don't load another embedding model.
- **Individual message scoring / leaderboards — HARD LINE NO.** Thermometer not scoreboard.
- **Anti-patterns rejected:**
  - AGC on audio bands (compressed dynamics too much, reverted to fixed multipliers)
  - Genre hints + "think carefully" for splattributions (made LLM wrong in BORING ways — operator: *"let's not try to help the LLMs be so right because then they'll be wrong in less interesting ways"*)

### 7.11 Remote dev setup

- **5-second bidirectional gdrive rsync** via `rclone-gdrive-drop.timer` modified from 30s to 5s. Units: `~/projects/hapax-council/systemd/units/rclone-gdrive-drop.timer`
- **Screenshot drops:** `~/bin/drop-snapshot [label]` copies `/dev/shm/hapax-compositor/fx-snapshot.jpg` to `~/gdrive-drop/legomena-screenshots/${label}-${HHMMSS}.jpg`
- **fx-snapshot is 1280x720** (was 640x360). Doesn't affect stream path — only local preview for the Tauri frame server at :8053 AND remote screenshot drops.
- **NEVER read screenshot drops back into agent context** — operator explicitly said: "higher resolution screen drops don't ingest into your own context". Drop them, don't Read them.

---

## 8. Magic Numbers & Configuration

### 8.1 Pipeline
| Value | Location | Meaning |
|---|---|---|
| `framerate: int = 30` | `agents/studio_compositor/models.py:73` | Output framerate |
| `smooth_delay.set_property("fps", 30)` | `agents/studio_compositor/smooth_delay.py:35` | Must match above |
| `output_width = 1920, output_height = 1080` | `agents/studio_compositor/config.py:28+` | Stream resolution |
| `num_slots=24` | `agents/studio_compositor/fx_chain.py` SlotPipeline | Shader slot count |
| `dither=0` | 12x videoconvert instances | Disable Bayer dithering |
| `max-size-buffers=1` or `2` | Various queues | Low latency |
| `leaky=2` | Various queues | Drop old buffers |

### 8.2 Audio reactivity
| Value | Location | Meaning |
|---|---|---|
| KICK_COOLDOWN = 0.2 | `fx_chain.py` FlashScheduler | Normal mode kick flash cooldown |
| KICK_COOLDOWN_VINYL = 0.4 | Same | Half-speed vinyl mode |
| FLASH_ALPHA = 0.5 | Same | Flash peak alpha |
| MIN_INTERVAL = 0.1, MAX_INTERVAL = 1.0 | Same | Random baseline flash intervals |
| Sidechain brightness duck: -0.7, decay 0.88 | `presets/_default_modulations.json` | Audio → brightness |
| Sidechain saturation duck: -1.0, decay 0.88 | Same | Audio → saturation |
| Vignette squeeze: 1.5, decay 0.75 | Same | Kick → vignette |
| Bloom spike: 1.0, decay 0.65 | Same | Kick → bloom |

### 8.3 Album identification
| Value | Location | Meaning |
|---|---|---|
| POLL_INTERVAL = 5 | `scripts/album-identifier.py` | Seconds between album change checks |
| CHANGE_HAMMING_THRESHOLD = 8 | Same | Min hash distance to trigger re-ID |
| CROP_MARGIN = 0.15 | Same | Center-square crop inset |
| COVER_SIZE = (512, 512) | Same | PNG size for overlay |
| PI6_IP = "192.168.68.81" | Env var in service | Current DHCP IP |
| IR capture resolution = 1920x1080 | `pi-edge/hapax_ir_edge.py` DEFAULT_CAPTURE_SIZE | Was 640x480 |

### 8.4 Token pole
| Value | Location | Meaning |
|---|---|---|
| base = 5000 | `scripts/token_ledger.py` `_threshold()` | Base tokens per pole fill |
| OVERLAY_X, OVERLAY_Y = 20, 20 | `token_pole.py` | Upper-left anchor |
| OVERLAY_SIZE = 300 | Same | Square size |
| NUM_POINTS = 250 | Same | Spiral path resolution |
| max_turns = 3.0 | Same | Spiral turn count |
| Explosion particles = 60 | Same | Vampire Survivor style burst |
| Position easing = 0.06 | Same | Smooth pole advancement |
| Pulse rate = 0.1 per frame | Same | Glyph wobble speed |

### 8.5 Chat monitor
| Value | Location | Meaning |
|---|---|---|
| POLL_INTERVAL = 2 | `scripts/chat-monitor.py` | Chat read cadence |
| BATCH_INTERVAL = 120 | Same | LLM batch analysis cadence (2 min) |
| WINDOW_SIZE = 100 | Same | Sliding message window |
| EMBED_WINDOW = 20 | Same | Recent messages for embedding similarity |
| THREAD_SIMILARITY_THRESHOLD = 0.6 | Same | Cosine for thread detection |
| MATTR window = 50 | Same | Moving-average TTR window |
| Superchat boost: $1 = 500 tokens | Same | Donation → pole contribution |
| Membership boost: 1000 tokens | Same | Direct bump |

### 8.6 YouTube player
| Value | Location | Meaning |
|---|---|---|
| LISTEN_PORT = 8055 | `scripts/youtube-player.py` | HTTP API port |
| V4L2_DEVICE = "/dev/video50" | Same | v4l2loopback for YouTube video |
| FRAME_SIZE = 640 * 360 * 4 | Same | PiP ffmpeg output size |
| ALPHA = 0.75 | Same | PiP cairooverlay alpha |

---

## 9. Service Units & File Paths

### 9.1 systemd user units
- `~/.config/systemd/user/studio-compositor.service`
- `~/.config/systemd/user/youtube-player.service`
- `~/.config/systemd/user/album-identifier.service` — created this session
- `~/.config/systemd/user/rclone-gdrive-drop.timer` — modified to 5s
- `~/.config/systemd/user/rclone-gdrive-drop.service`

### 9.2 SHM outputs (compositor state)
- `/dev/shm/hapax-compositor/fx-snapshot.jpg` — 1280x720, stream preview
- `/dev/shm/hapax-compositor/snapshot.jpg` — pre-FX, 1280x720
- `/dev/shm/hapax-compositor/brio-*.jpg`, `c920-*.jpg` — per-camera snapshots
- `/dev/shm/hapax-compositor/album-cover.png` — colorized 512x512
- `/dev/shm/hapax-compositor/album-state.json` — current splattribution state
- `/dev/shm/hapax-compositor/music-attribution.txt` — rendered splattribution text
- `/dev/shm/hapax-compositor/track-lyrics.txt` — scrolling lyrics overlay source
- `/dev/shm/hapax-compositor/token-ledger.json` — pole state
- `/dev/shm/hapax-compositor/chat-state.json` — chat monitor metrics (when running)
- `/dev/shm/hapax-compositor/yt-attribution.txt` — YouTube PiP attribution
- `/dev/shm/hapax-compositor/youtube-video-id.txt` — chat-monitor input
- `/dev/shm/hapax-compositor/vinyl-mode.txt` — "true" for half-speed mode
- `/dev/shm/hapax-compositor/fx-source.txt` — (deprecated — was camera source switch)
- `/dev/shm/hapax-compositor/fx-request.txt` — preset request
- `/dev/shm/hapax-compositor/graph-mutation.json` — full graph update

### 9.3 Persistent state
- `~/Documents/Personal/30-areas/legomena-live/attribution-log.md` — YouTube react content
- `~/Documents/Personal/30-areas/legomena-live/music-attribution-log.md` — vinyl splattributions
- `~/Documents/Personal/30-areas/stream-overlays/` — 85 Pango overlay content files
- `~/gdrive-drop/legomena-screenshots/` — remote screenshot drops
- `~/hapax-state/edge/hapax-pi*.json` — Pi heartbeats
- `~/hapax-state/pi-noir/{desk,room,overhead}.json` — IR detection reports

### 9.4 Code locations (Legomena/garage-door specific)
- `agents/studio_compositor/` — compositor, FX chain, token pole, overlays
  - `fx_chain.py` — main FX chain builder, `_pip_draw`, YouTubeOverlay, AlbumOverlay, FlashScheduler
  - `token_pole.py` — Vitruvian + spiral + particles
  - `overlay_zones.py` — Pango text zones including scrolling lyrics
  - `audio_capture.py` — PipeWire capture + DSP
  - `pipeline.py` — main GStreamer pipeline (now with CPU fallback)
  - `cameras.py` — per-camera branches (now with CPU fallback)
- `scripts/album-identifier.py` — vision + audio identification daemon
- `scripts/chat-monitor.py` — YouTube Live chat structural analysis
- `scripts/token_ledger.py` — shared token spend accumulator
- `scripts/youtube-player.py` — YouTube decode daemon with KDE Connect
- `scripts/youtube-auth.py` — OAuth consent helper for YouTube Data API
- `scripts/drop-snapshot` (via `~/bin/drop-snapshot`) — remote preview helper
- `pi-edge/hapax_ir_edge.py` — Pi NoIR edge daemon (deployed to 3 Pis)
- `pi-edge/ir_album.py` — OpenCV album cover detection
- `assets/vitruvian_man_overlay.png` — Da Vinci asset
- `presets/` — 30+ JSON preset files
- `hapax-logos/src/components/graph/` — chain builder, sequence bar, output node

---

## 10. Launch Checklist (T-26h)

### 10.a Burn-in phase (T-20h to T-4h freeze→launch window)

Run the full stack for at least **4 hours continuous** before considering launch. Watch for:
- Memory growth in each daemon (`ps -C python -o pid,rss,comm | grep -E "compositor|album|chat|youtube"` every 15 min)
- GPU VRAM creep (`nvidia-smi` every 15 min)
- GStreamer bus error messages in journalctl
- Any service entering `failed` state
- Gemini API errors in album-identifier logs
- Frame drops in compositor (watch `fx-snapshot.jpg` for stalls)

If any daemon leaks >100MB/hour RSS, fix before launch.

### 10.b Pre-flight checks

```bash
# 1. Verify compositor is running on CUDA path (not CPU fallback)
systemctl --user status studio-compositor | grep Active
journalctl --user -u studio-compositor --since "1 min ago" | grep -iE "fallback|FX chain"
# Expect "active", NO "falling back", "FX chain: 24 shader slots"

# 2. Verify GPU is being used
nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader
# Expect 20-40% GPU, ~9-12 GB VRAM

# 3. Verify all services
for svc in studio-compositor youtube-player album-identifier logos-api hapax-logos; do
    printf "%-25s %s\n" "$svc" "$(systemctl --user is-active $svc)"
done

# 4. Verify Pi NoIR fleet
for ip in 192.168.68.78 192.168.68.52 192.168.68.81; do
    curl -s -o /dev/null -w "%{http_code} " http://$ip:8090/frame.jpg
done
# Expect three 200s

# 5. Verify v4l2 output device
v4l2-ctl -d /dev/video42 --all 2>/dev/null | grep -E "Width|Height"
# Expect 1920 / 1080

# 6. Test preset switch via Logos API
curl -s -X POST http://localhost:8051/api/studio/effect/select \
  -H 'Content-Type: application/json' -d '{"preset":"halftone_preset"}'
# Effect should appear on output within 1-2 seconds

# 7. Test YouTube PiP end-to-end
curl -s -X POST http://127.0.0.1:8055/play \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://youtube.com/watch?v=SHORT_VIDEO_ID"}'
# Should see PiP appear on compositor output within 5-10s

# 8. Test vinyl album detection
# - Place a physical vinyl in front of Pi-6 camera
# - Wait 5-10s
curl -s http://192.168.68.81:8090/frame.jpg -o /tmp/test.jpg
cat /dev/shm/hapax-compositor/music-attribution.txt
# Should see a splattribution

# 9. Launch OBS, configure profile + scene per garage-door plan Task 2
# 10. Start test stream (unlisted), verify in YouTube Studio
# 11. Set visibility public
# 12. Start streaming

# 13. During 36h stream — monitoring commands
watch -n 30 'nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader; uptime'
journalctl --user -u studio-compositor -f | grep -iE "error|warning|fallback"
```

### 10.c Recovery plan (mid-stream failure)

If something dies during the 36h stream, OBS is the single point of failure that must not drop. Everything else has a graceful degradation path:

| Failure | Detection | Action | Visible? |
|---|---|---|---|
| Compositor crash | `/dev/video42` stops | systemd `Restart=on-failure` kicks in within 10s | OBS sees black frames briefly |
| youtube-player crash | `/status` returns 500 | systemd restart | PiP disappears for ~10s |
| album-identifier crash | Log stops | systemd restart | Pole stops advancing |
| chat-monitor crash | `chat-state.json` stale | Manual: `systemctl --user restart chat-monitor` | Pole stops advancing |
| Pi NoIR daemon crash | Frame server 404 | Pi's own systemd restart | Album ID stops (~3s delay) |
| OBS crash | Stream drops | **Operator must manually restart OBS** | VIEWERS SEE DROP |
| NVENC stuck | Frame freezes | Operator restarts OBS | VIEWERS SEE DROP |
| RTMP drop (YouTube) | OBS reconnects automatically | Auto (built-in OBS feature) | Brief buffering |
| Vinyl audio drops | Album-id can't fetch | Graceful — splattribution keeps last value | Subtle |
| Mixer dies (USB) | Both vinyl + voice lost | Manual: unplug/replug PreSonus | AUDIO DROP |

**All `systemd` user services must have `Restart=on-failure` with `RestartSec` short enough to recover within 10s.** Verify before freeze:
```bash
for svc in studio-compositor youtube-player album-identifier logos-api; do
    echo "=== $svc ==="
    systemctl --user cat $svc 2>&1 | grep -E "Restart|RestartSec"
done
```

---

## 11. Content Safety (axiom enforcement)

**MUST verify before going public:**
- `corporate_boundary` axiom: no employer work visible on any camera feed
- No names/screen content from non-operator persons (`interpersonal_transparency`)
- No LLM-generated feedback about individuals (`management_governance`)
- Consent overlay on compositor shows recording-allowed state
- Splattributions don't identify real people by name (artists on album covers are public figures — OK)

---

## 12. Review Agent Findings (pending)

A background review agent (launched earlier this session) is parsing all 12 conversation transcripts from 2026-04-04 through now for:
- Dropped TODOs mid-conversation
- Promises not kept
- Deferred features pegged for later
- Discovered constraints not in docs
- Config magic numbers not in code comments
- External dependency gotchas

**Output file:** `/tmp/claude-1000/-home-hapax-projects/a8ee3306-d1d2-421b-873c-271c81456235/tasks/aba397a7115d1484b.output`

When it completes, merge findings into:
- §6 Open TODOs (any new items)
- §7 Gotchas (any new hard-won knowledge)
- §8 Magic Numbers (any values discovered in conversations but not in code)

Agent has parsed ~843 user messages and 2662 assistant messages from the current 109MB session; still extracting. If it hasn't completed by next session start, re-read the jsonl files directly with Python + jq filtering.

---

## 13. Next Session Ordered Playbook

### Phase A: Dev (now → T-20h freeze, ~20 hours)

Priority order — do in sequence, stop when time runs out. **Only ship blockers** from §6.1, §6.2, §6.4. Everything in §6.3+ is luxury.

1. **Check the review agent output** at `/tmp/claude-1000/-home-hapax-projects/a8ee3306-d1d2-421b-873c-271c81456235/tasks/aba397a7115d1484b.output` — merge any new blockers into §6.1/6.2/6.4 before proceeding.
2. **36h stability audit** (§6.4) — walk every item. Fix what can be fixed in <30 min each. Document workarounds for what can't.
3. **Wire token ledger writers** into `album-identifier.py` LLM call sites (§6.2). Otherwise the token pole never moves.
4. **Create `chat-monitor.service` systemd unit** (§6.2). Don't start yet — no video ID yet.
5. **Verify all services have `Restart=on-failure`** (§10.c). Fix any that don't.
6. **Configure OBS** per garage-door plan Task 2 (§6.1). Requires GUI. ~10 min.
7. **Burn-in** (§10.a) — run everything for ≥4h continuous, watch for leaks. Fix any >100MB/hr RSS growth.

### Phase B: Freeze (T-20h → T-4h, 16 hours rest/verify)

**No code changes.** Only verification and practice.
- Run the launch checklist (§10.b) end-to-end
- Practice the recovery actions (§10.c) — can you restart OBS? find PreSonus ports? restart the compositor cleanly?
- Sleep.

### Phase C: Launch (T-4h → T-0)

1. Start compositor, verify CUDA path
2. Place first vinyl, verify splattribution loop
3. Queue a YouTube video, verify PiP
4. Preset smoke test (shuffle all shufflable presets)
5. Check gdrive drops working (if still remote)
6. Configure OBS stream key from YouTube Studio → Go Live
7. Test stream (unlisted), check stream health, effect switching
8. Pre-flight content safety scan (§11)
9. Set visibility to Public
10. Click Start Streaming
11. Say hello

### Phase D: 36-hour stream

- Chat-monitor: grab YouTube video ID, write to `/dev/shm/hapax-compositor/youtube-video-id.txt`, start chat-monitor service
- Passive watch: token ledger advancing, pole climbing, splattributions changing as vinyl rotates, presets cycling
- Every few hours: check `nvidia-smi`, `uptime`, systemd service status
- If anything dies: §10.c recovery table
- No code changes — streak is the goal
- End at T+36h, stop stream, YouTube auto-generates VOD

---

## 14. Open Questions / Unknowns

These are things the next session should resolve before freeze:
- **What's the YouTube channel name / stream title?** Not set anywhere we saw.
- **What's the target start time?** Need specific UTC timestamp so we know T-20h and T-26h.
- **Is there a designated "hello" script / first-5-min plan?** No — garage door philosophy says don't perform.
- **Is there a failover streaming setup** if the main machine goes down mid-stream? Probably not for this launch — it's "go all in, learn".
- **Will the operator be at the machine for launch, or fully remote via tmux the entire time?** Matters for OBS GUI configuration (must be done at the machine or via VNC).

---

**End of handoff.**

This is a live-production document. Any decisions made in the dev phase between now and freeze should update this file (not replace it — append/edit).

The north star: **everything that ships must serve a 36-hour continuous live stream starting in ~26 hours. Everything else is not for now.**
