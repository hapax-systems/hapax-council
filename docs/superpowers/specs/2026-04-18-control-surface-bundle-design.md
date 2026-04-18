# Control Surface Bundle — Stream Deck + KDEConnect + Vinyl Rate + IR Cadence

**Date:** 2026-04-18
**Scope:** CVS dossier items #140, #141, #142, #143 (four ship-owl items, one consolidated design)
**Source research:**
- `cvs-research-140.md` (in /tmp) — Stream Deck (80% shipped, 4 gaps, 2-PR plan)
- `cvs-research-141.md` (in /tmp) — KDEConnect interim (1–2 day PR)
- `cvs-research-142.md` (in /tmp) — Vinyl rate (ACTIVE BUG in album-identifier; 3-PR plan; float signal)
- `cvs-research-143.md` (in /tmp) — IR cadence (ACRCloud rejected; narrowed to cadence control)
- Dossier: `docs/superpowers/research/2026-04-18-cvs-research-dossier.md`

## 1. Goal

Ship a single, unified **control-surface bundle** so the operator can steer the
livestream from the physical studio surface (vinyl/MPC/contact-mic
workflow) without leaving it to touch a keyboard or web UI:

- Physical control surface (Stream Deck MK.2, already on desk).
- Phone control surface (KDEConnect, interim + permanent pocket fallback).
- Rate-aware audio correction (float `vinyl_playback_rate`, unblocks fingerprinting
  and beat/director tempo math at 45-on-33 and similar Handytraxx presets).
- IR feed cadence toggle (force-refresh, pause, preset cycle) routed through the
  same command registry.

The four items share two substrates: **one command registry** and **one file-bus**.
Shipping them as a bundle avoids four parallel wirings of the same plumbing.

## 2. Shared Backbone

Two substrates already exist and are reused end-to-end:

**logos-api `:8051` command registry** (reused by #140 + #141)
- `window.__logos.execute` in the Tauri frontend; relay on `:8052` forwards
  external clients into the registry (`hapax-logos/src-tauri/src/commands/relay.rs`).
- Stream Deck adapter (`agents/streamdeck_adapter/`) is a WS client of `:8052`.
- **Decision (open-question #1 from #140 research, resolved here):** for pure-backend
  commands (studio, research, attention, vinyl rate, album cadence), the adapter
  and `hapax-ctl` POST directly to logos-api `:8051` HTTP endpoints — **bypass the
  Tauri relay**. Relay is retained only for commands that need frontend state.
  Rationale: Stream Deck must remain live when the Logos window is closed.

**`/dev/shm/hapax-compositor/*.txt` file-bus** (reused by #142 + #143)
- Compositor and daimonion already poll files at 100 ms cadence. All new signals
  ride this bus: `vinyl-playback-rate.txt`, `album-cadence.json`, plus existing
  `vinyl-mode.txt` (legacy shim) and `half-speed` (CVS #3 alias).
- Writes are atomic via tempfile+rename. Missing file = no-op default.

Both substrates are live and tested; this bundle adds entries, not new infrastructure.

## 3. Per-Item Plans

### 3.1 Stream Deck (#140) — 2 PRs

**PR A — command-registry registrations (7 new entries):**

1. `studio.camera_profile.set(profile)` — writes `/dev/shm/hapax-studio/camera-profile`, compositor director loop reads. Phase 8 item 5 hero-mode switcher shim lands here.
2. `studio.stream_mode.toggle` — thin wrapper over existing Python stream-mode state.
3. `studio.private.enable` — same.
4. `studio.activity.override(activity)` — forwards to `agents/studio_compositor/director_loop.py` override path.
5. `research.condition.{open,close}` — shells to existing research-registry CLI.
6. `attention_bid.dismiss` — sets `/dev/shm/hapax-attention-bids/dismissed.flag` with 15-min TTL.
7. `studio.vinyl_rate.set(rate)` — delegated to #142 §3.3 (shared entry, one domain).
   Keys 13–14 reserve for HSEA-11 G13 emergency and LRR Phase 10 rating (tracked
   separately, stubbed here as no-ops).

Dispatch path: adapter POSTs to logos-api `:8051` for these commands (see §2).
The Tauri relay remains wired for Logos-UI-only commands (sidebar toggles, etc.).

**PR B — deployment chore (1–2 hour job, not a design question):**

1. `uv add streamdeck` — pin `python-elgato-streamdeck`.
2. Install `60-streamdeck.rules` at `/etc/udev/rules.d/` via new
   `scripts/studio-install-udev-rules.sh` + `udevadm trigger`.
3. Symlink `systemd/units/hapax-streamdeck-adapter.service` into user systemd,
   `daemon-reload`, `enable --now`.
4. Verify: key 0 → `studio.camera_profile.set` logged + relay fires.
5. LED feedback and SIGHUP rescan deferred (follow-ups).

### 3.2 KDEConnect (#141) — 1 PR

Single 1–2 day PR. Parity with `config/streamdeck.yaml` so phone and deck expose
the same verbs.

1. `scripts/hapax-ctl` — thin Python relay client, `<command> [json-args]`,
   one-shot connection to `ws://127.0.0.1:8052/ws/commands` **or direct HTTP
   POST to `:8051`** for backend commands (same routing split as Stream Deck).
2. `config/kdeconnect-runcommand.json` — declarative command list, mirror of
   `config/streamdeck.yaml`.
3. `scripts/install-kdeconnect-commands.sh` — idempotent renderer into
   `~/.config/kdeconnect/<device>/kdeconnect_runcommand/config` + `kdeconnect-cli --refresh`.
4. `docs/runbooks/kdeconnect-control.md` — pairing check, install steps, troubleshooting.
5. Test: `tests/scripts/test_hapax_ctl.py` using fake-relay pattern from
   `tests/streamdeck_adapter/test_adapter.py`.

No systemd unit. No logos-api changes. No Rust changes. Auth: KDEConnect pairing
is the boundary (single-operator axiom; no additional token layer).

### 3.3 Vinyl Rate (#142) — 3 PRs

**PR A — ACTIVE BUG FIX (blocker; others build on this):**

1. Introduce float signal `/dev/shm/hapax-compositor/vinyl-playback-rate.txt`.
   `1.0` = off. Legacy `vinyl-mode.txt=="true"` maps to `0.741` (45-on-33 default)
   with deprecation log; removed next release.
2. **Fix `scripts/album-identifier.py:295-346`** — it hardcodes
   `asetrate=88200,aresample=44100` (exactly 2×). At operator's actual rate
   (~0.74x), fingerprint submitted at 1.48x — guaranteed no-match. Parameterize
   `asetrate = 44100 / rate`; gate the whole ladder on `rate != 1.0`; fix Gemini
   prompts L404/L532 to state actual rate rather than "2x".
3. **BPM nominalization in `shared/beat_tracker.py`** — multiply median-interval
   BPM by `1/rate` when `rate != 1.0`. Expose `BeatGrid.bpm_nominal`.
4. Endpoints on logos-api: `POST /studio/vinyl-playback-rate {rate: float}`,
   `GET /studio/vinyl-playback-rate`. Retain `toggle` endpoint as alias (flips
   between `1.0` and last-set rate, default `0.741`).
5. Tests: golden audio at 0.741/0.5/1.0 through ffmpeg ladder; fingerprint
   round-trip mock; BPM nominal invariant.

**PR B — reactivity + director parameterization:**

1. `agents/studio_compositor/audio_capture.py` — `VINYL_MODE: bool` →
   `vinyl_rate: float`. Decay and onset thresholds parameterized on rate.
2. `agents/studio_compositor/fx_chain.py` — `KICK_COOLDOWN` scales as `base / rate`.
3. `agents/studio_compositor/director_loop.py` — pass `vinyl_rate` into the
   music-framing prompt: "playing at {rate:.2f}x (pitched down ~N semitones)".

**PR C — control surfaces:**

1. Stream Deck keys for presets: `1.0` / `0.741` / `0.577` / `0.5` via
   `studio.vinyl_rate.set`. Optional cycle key.
2. KDEConnect shortcuts — three entries (off / 0.741 / 0.5) in
   `config/kdeconnect-runcommand.json`.
3. Logos UI sidebar — segmented button + numeric override, same command verb.

### 3.4 IR Cadence (#143) — 2 PRs

ACRCloud is **not being integrated** (operator-ratified: underground catalog
absent; Gemini vision + rate-corrected audio is the winning pipeline).

**PR A — doc-only cleanup (15 min):**

1. Fix stale module docstring at `scripts/album-identifier.py` L6, L13, L46, L696
   — currently advertises "Track ID: ACRCloud"; actual path is Gemini Flash
   multimodal. One-line edits; no behaviour change.
2. Add closed-exploration footnote to CVS #127 SPLATTRIBUTION doc so the idea
   stops resurfacing in context sweeps.

**PR B — cadence control endpoint + bindings:**

1. Three FastAPI routes on logos-api: `POST /api/album/reid`,
   `POST /api/album/cadence`, `GET /api/album/cadence`. State file:
   `/dev/shm/hapax-compositor/album-cadence.json` (preset + next-pull timestamp).
2. `scripts/album-identifier.py` reads cadence state each tick. Presets:
   `fast` (2s poll / 15s re-ID), `normal` (5s / 30s — current), `idle` (∞ / ∞).
3. MIDI transport hook: skip polling while transport stopped; force-refresh on
   Start. (Consumer not yet wired — grep confirms — small addition.)
4. Stream Deck keys: force-reid, pause-toggle, cadence-cycle.
5. KDEConnect shortcuts: force-reid, pause-toggle.
6. Out of scope: Pi-edge daemon's 2s `POST_INTERVAL_S` — that feeds the
   daimonion presence stack; leave alone.

## 4. Interaction Matrix

| Signal / Action                  | Writer(s)                              | Reader(s)                                   | Control surfaces           |
|----------------------------------|----------------------------------------|---------------------------------------------|----------------------------|
| `vinyl-playback-rate.txt`        | logos-api `/studio/vinyl-playback-rate`| compositor, album-identifier, beat_tracker  | Stream Deck, KDEConnect, Logos UI |
| `vinyl-mode.txt` (legacy shim)   | deprecated; any remaining callers      | compositor (maps to 0.741)                  | —                          |
| `album-cadence.json`             | logos-api `/api/album/cadence`         | album-identifier                            | Stream Deck, KDEConnect    |
| `/api/album/reid` (one-shot)     | Stream Deck / KDEConnect               | album-identifier (force-refresh)            | Stream Deck, KDEConnect    |
| `camera-profile`, `stream-mode`, etc. | command registry                   | compositor director loop                    | Stream Deck, KDEConnect, Logos UI |
| `attention-bids/dismissed.flag`  | `attention_bid.dismiss`                | attention-bid dispatcher                    | Stream Deck, KDEConnect    |
| MIDI transport Start/Stop        | OXI One / deck                         | album-identifier (cadence gate)             | n/a                        |

Downstream unblocks: HSEA-11 G13, HSEA-7 D9, LRR Phase 9 disable toggle,
LRR Phase 10 post-stream rating, LRR Phase 8 item 10 attention-bid override.

## 5. Open Questions

1. **Handytraxx preset confirmation** — research assumes 45-on-33 (0.741x) is
   the operator's actual rate. If a DIY 0.5x rig or external DSP is in use,
   default preset should change. Confirm with operator before PR A of #142 lands.
   Not blocking: endpoint accepts any float; only the default flips.
2. **Stream Deck relay architecture** — §2 resolves this by splitting routing:
   Tauri `:8052` relay for UI-state commands, direct logos-api `:8051` POST for
   backend commands. Confirm this split is acceptable before PR A of #140 lands.
   Alternative (reject unless operator prefers): second lightweight Python WS
   relay on logos-api. Deferred.
3. **LED feedback and SIGHUP rescan** on Stream Deck — follow-up PRs after live
   use reveals need. Not in this bundle.

## 6. Test Strategy

- **#140:** `tests/streamdeck_adapter/test_{adapter,key_map}.py` already covers
  press/release, unbound key, duplicate-key error, dispatch round-trip. Extend
  to cover the 7 new command verbs with a mock registry. PR B deployment is
  manual-verify (press key, tail `journalctl --user -u hapax-streamdeck-adapter`).
- **#141:** `tests/scripts/test_hapax_ctl.py` — fake-relay pattern; asserts
  `execute` payload shape, exit status on ack/nack, JSON stdout on `query`/`list`.
- **#142 PR A:** golden audio fixtures at 0.741 / 0.5 / 1.0 → ffmpeg ladder →
  assert nominal tempo ±2%. BPM nominal invariant across rates. Fingerprint
  round-trip mock asserts submitted sample rate.
- **#142 PR B:** director prompt snapshot test asserts `"playing at"` string
  includes the current rate. Compositor FX decay curve test at three rates.
- **#142 PR C:** Stream Deck YAML binding parsing; KDEConnect JSON renderer
  round-trip; Logos UI segmented-button story in Storybook if applicable.
- **#143 PR A:** docstring diff only; no runtime test.
- **#143 PR B:** album-identifier respects cadence JSON (parametrize over the
  three presets); MIDI transport Stop halts polling; `POST /api/album/reid`
  triggers one capture regardless of cooldown.

---

Echo: `docs/superpowers/specs/2026-04-18-control-surface-bundle-design.md`
(repo: hapax-council--cascade-2026-04-18)
