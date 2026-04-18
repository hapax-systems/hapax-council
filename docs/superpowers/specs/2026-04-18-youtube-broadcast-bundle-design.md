# YouTube Broadcast Bundle Design (#144 + #145)

**Date:** 2026-04-18
**Scope:** Two YT-broadcast concerns treated as a single consolidated spec because they share infrastructure (broadcast lifecycle, audio routing, PipeWire graph, quota/observability discipline) and a single shared worktree.
**Sources:** `cvs-research-144.md`, `cvs-research-145.md` (both under `/tmp/`), CVS dossier.

---

## 1. Goal

Unify two YT-broadcast obligations the operator surfaced on 2026-04-06:

1. **Real-time attribution (#144):** chat-shared links — and any linkable artifact produced during a stream — must backflow into the YouTube livestream description in real time, so attribution becomes *public record* rather than a private log. Operator flagged this as a "powerful reusable strategy"; treat as such.
2. **Reverse-direction ducking (#145):** the 24c operator hardware mix must step down when YouTube / React content plays, mirroring the shipped operator→YT ducker. YT audio should itself be loudness-normalized before it hits the sidechain.

Both concerns terminate at the same physical broadcast. One spec keeps the implementation discipline coherent: same OAuth surface (#144), same PipeWire graph discipline (#145), same Prometheus namespace, same test matrix.

---

## 2. §2 — YouTube description auto-update (#144)

### 2.1 Infra inventory — Task #48 legacy is REUSABLE

Two independent implementations already live in-repo. The work mostly shipped; wiring is the gap.

- `scripts/youtube-player.py::LivestreamDescriptionUpdater` (`:357–572`) — auto-discovers active livestream via `liveBroadcasts?broadcastStatus=active&mine=true`, reads the vault-local `30-areas/legomena-live/attribution-log.md`, composes description via marker-section rewrite, PUTs `videos.update?part=snippet`. OAuth token refresh on 401.
- `agents/studio_compositor/youtube_description.py` — hardened quota-aware single source of truth. `check_and_debit()` (atomic tmp+rename quota state, per-stream + daily caps, `QuotaExhausted` silent-skip). `assemble_description()` renders condition/claim/objective/substrate lines. `update_video_description()` via google-api-python-client + `shared.google_auth.get_google_credentials()`.
- `agents/studio_compositor/youtube_description_syncer.py` — idempotent systemd-timer driver. Hash-of-state cache at `~/.cache/hapax/youtube-desc-last-state.json`. `HAPAX_YOUTUBE_VIDEO_ID` env var.

### 2.2 Blocker — OAuth consent

`shared/google_auth.py ALL_SCOPES` requests `https://www.googleapis.com/auth/youtube.force-ssl`, but no token has been minted with the scope. `_load_credentials()` logs warning + sets `_enabled=False`; every update silently no-ops. Operator must run `scripts/youtube-auth.py` interactively. Until then all paths fail silent — tests must assert "disabled with clear warning", not "updates succeed".

### 2.3 Missing wire — chat URL → AttributionSource

`scripts/chat-monitor.py` reads live chat + structural metrics + LLM-batches them, but **does NOT extract URLs**. That is the specific miss the operator flagged. Three additions:

```
chat-monitor.py  →  URL extractor (regex + unwrap)  →  Classifier (citation | album-ref | DOI | tweet | ...)
                 →  AttributionEntry (typed)
                 →  per-kind attribution file under vault 30-areas/legomena-live/
                 →  youtube_description_syncer.sync_once()  (already hash-deduped)
```

### 2.4 Reusable strategy — `AttributionSource` protocol

Operator's parenthetical is the real signal: *"think carefully about this last part, because it could be a powerful reusable strategy."* Define one contract that backflows every linkable artifact → description citation:

```python
class AttributionSource(Protocol):
    kind: Literal["yt-react", "splattribution", "citation", "homage", "vinyl", "objective", "condition"]
    url: str
    title: str
    author: str | None
    timestamp: datetime
```

Candidate producers already in-repo (all backflow the same shape):

| Source | Ingest path |
|---|---|
| Chat-posted URLs (§2.3) | chat-monitor → extractor (NEW) |
| SPLATTRIBUTION album IDs (#127) | `scripts/album-identifier.py` |
| YT React content | `youtube-player.py::play_video` (shipped) |
| LRR research objectives / condition / claim | syncer (shipped) |
| Homage artefacts (#136/#137) | `shared/homage_package.py` |
| Chat-ward DOI (#123 future) | DOI resolver (future) |
| Contact-mic vinyl detection | discogs/MusicBrainz (future) |

Writers emit the protocol; one syncer renders all active sources into per-kind description sections. Rolling window per kind (`deque(maxlen=10)`), YouTube 5000-char hard limit, oldest non-`yt-react` pruned first.

### 2.5 `liveChatId` sidecar (optional)

`liveBroadcasts.list?part=snippet` exposes `liveChatId`. `liveChatMessages.insert` (50u, same quota bucket) posts a message into live chat itself. Two-channel strategy:

- Description: low-frequency canonical state (≤5 writes/stream).
- Live chat: high-frequency ephemeral ack — "Citing: *title* — shared by *chatter*". Makes attribution visible in the moment, not just in a panel nobody reads.

### 2.6 Quota math

- `liveBroadcasts.list` = 1u, `videos.update` = 50u, `liveChatMessages.insert` = 50u (optional).
- Daily project allocation 10,000u. Config caps at `daily_budget_units: 2000` (20%), `per_stream_max_updates: 5`.
- 50u + 1u read = 51u/cycle → **~39 updates/day maximum** within 2000u cap. 40/day = 2040u, over.
- Write cadence: timer 5 min + hash dedup + per-stream cap 5 = no thrash. Already shipped.

---

## 3. §3 — 24c reverse-direction ducking (#145)

### 3.1 Shipped

| # | Trigger | Target | Where |
|---|---|---|---|
| A | Daimonion TTS | 3 YT PiP slots | PR #778 — `audio_control.duck()` wpctl envelope |
| B | Operator voice VAD | 3 YT PiP slots | PR #943 — `vad_ducking.DuckController` |
| C | Operator mic (sidechain) | `hapax-ytube-ducked` virtual sink | PR #1000 — `config/pipewire/voice-over-ytube-duck.conf`, LADSPA `sc4m_1916`, −30 dBFS / 8:1 / 5 ms attack / 300 ms release |

### 3.2 Missing — YT → 24c

The direction operator explicitly asked for is **zero-wired**. No trigger, no sink, no filter-chain. The 24c outbound bus has no ducking attached at all. Operator quote: *"ducking for the 24c mix coming in to get out of the way of any youtube/react content, not A LOT but enough to let the YouTube audio come in"*.

### 3.3 Mirror PR #1000 — symmetric sidechain

New PipeWire filter-chain `config/pipewire/ytube-over-24c-duck.conf`:

- Virtual sink `hapax-24c-ducked`; PreSonus Studio 24c hardware mix routes through it before hitting the physical output.
- LADSPA `sc4m_1916` sidechain compressor keyed on the **YT sink's output** (not the mic).
- Tuning: threshold **−20 dBFS**, ratio **2:1** ("not A LOT"), attack **50 ms**, release **500 ms** (slow — feels musical), target attenuation **~6 dB** (half the 12 dB of the mirror ducker, matches "enough").

### 3.4 YT loudness normalization

Operator parenthetical: *"(should itself be normalized)"*. Zero hits in-repo for `loudnorm` / `replaygain` / `ebur128` / LUFS in `config/pipewire/` or compositor audio code — the feed is un-normalized.

Add `module-loudnorm` (or LSP `loudness_mono`) on `hapax-ytube-ducked`: integrated loudness **−16 LUFS** (YouTube delivery standard), peak limiter **−1.5 dBTP**. Normalization sits upstream of the sidechain key so hot/quiet YT sources don't whip the ducker.

### 3.5 Three-way interaction matrix — extend R19

LRR Phase 9 §3.8 R19 anticipated the pairwise interaction. Three-way (operator speech × YT plays × Hapax TTS) is new. Matrix:

| Scenario | A (TTS) | B (VAD) | C (mic→YT) | D (YT→24c, NEW) | Expected net |
|---|---|---|---|---|---|
| S1: YT alone | — | — | — | duck 24c | YT audible |
| S2: op + YT | — | duck YT | duck YT | duck 24c | YT slightly attenuated, op forward, 24c bedded |
| S3: TTS + YT | duck YT | — | — | duck 24c | TTS forward, YT bedded, 24c bedded |
| S4: op + TTS + YT | duck YT | duck YT | duck YT | duck 24c | all-hands: verify no runaway |

Extend `tests/pipewire/test_voice_over_ytube_duck_config.py` shape; regression-pin the new `.conf`.

---

## 4. Shared observability

Both tasks emit into the same `hapax_broadcast_*` Prometheus namespace; one dashboard row, one alert family.

- `hapax_broadcast_yt_quota_units_used_total{day}` — daily counter, alert at 80% of 2000u.
- `hapax_broadcast_yt_description_updates_total{stream_id,result=(ok|dedup|disabled|quota|error)}`
- `hapax_broadcast_yt_attribution_entries{kind}` — gauge per `AttributionSource.kind`.
- `hapax_broadcast_duck_active{direction=(op_to_yt|yt_to_24c|tts_to_yt)}` — gauge, 0/1.
- `hapax_broadcast_duck_attenuation_db{direction}` — live reduction in dB.
- `hapax_broadcast_yt_loudness_lufs` — rolling integrated loudness on `hapax-ytube-ducked`.

---

## 5. File-level plan

**#144:**
- NEW `shared/attribution.py` — `AttributionSource` protocol + `AttributionEntry` dataclass + per-kind ring buffer + file-per-kind writer.
- MOD `scripts/chat-monitor.py` — URL extractor + classifier stage, non-invasive append to structural batch.
- MOD `agents/studio_compositor/youtube_description_syncer.py::_snapshot_state` — enumerate registered `AttributionSource`s.
- MOD `agents/studio_compositor/youtube_description.py::assemble_description` — per-kind sections with per-kind markers (dedup trick preserved).
- OPT NEW `agents/studio_compositor/youtube_livechat.py` — `liveChatMessages.insert` sidecar.
- OPERATOR-GATED `scripts/youtube-auth.py` — run interactively; not code work.

**#145:**
- NEW `config/pipewire/ytube-over-24c-duck.conf` — mirror-shape of `voice-over-ytube-duck.conf`.
- MOD `config/pipewire/README.md` — routing diagram: 24c hw mix → `hapax-24c-ducked` → phys-out; YT/OBS → `hapax-ytube-ducked` (normalized) → phys-out, with loopback to 24c ducker sidechain.
- NEW `tests/pipewire/test_ytube_over_24c_duck_config.py` — regression-pin config.
- NEW `tests/pipewire/test_three_way_ducking_matrix.py` — S1–S4 above.

---

## 6. Implementation order

1. **#144 description wiring first** — code-only (AttributionSource protocol, extractor, syncer extension). OAuth consent blocker is operator-gated and out-of-band; the code lands behind the silent-skip shield and activates the moment the token is minted.
2. **#145 PipeWire conf + normalization** — independent; no overlap with #144's Python surface. Safe parallel.
3. **Three-way matrix test** — after both above land.
4. **Optional livechat sidecar** — last; gated on quota-headroom review.

Because #144's activation is operator-gated (OAuth) and #145 is PipeWire-only, the two workstreams cannot collide. Shared-dir policy is safe.

---

## 7. Open questions

- Should `liveChatMessages.insert` be default-on, default-off, or operator-mode-gated (research/rnd/fortress)?
- Attribution file-per-kind under vault `30-areas/legomena-live/` — one file per kind, or one append-only JSONL with `kind` field? Vault ergonomics vs. atomicity.
- Chat URL classifier: LLM (same batch as structural analysis) or pure regex+heuristic? Cost vs. accuracy.
- 24c ducker attack 50 ms may pump on percussive YT content; expose as tunable in `.conf` for operator taste.
- Should YT normalization be pre- or post-PiP compositor? Pre keeps the sidechain clean; post preserves compositor headroom.

---

## 8. Test strategy

- **Unit:** `AttributionSource` protocol conformance per producer; URL extractor regex corpus; classifier decision table; per-kind ring buffer rotation + 5000-char pruning; `assemble_description` marker dedup.
- **Integration (mocked YT API):** `videos.update` happy path; 401 → refresh → retry; `QuotaExhausted` silent-skip; hash-dedup no-op on unchanged state; disabled-credentials path logs-warn-and-no-ops.
- **PipeWire:** config-lint regression pin for `ytube-over-24c-duck.conf`; loopback graph assertion (24c hw → `hapax-24c-ducked`; YT → `hapax-ytube-ducked` → sidechain key); normalization module loaded with correct LUFS target.
- **Three-way matrix:** S1–S4 above, measuring attenuation dB on each bus via `pw-cli` / pw-top; assert no oscillation (attenuation stable ±1 dB over 5 s window once steady-state).
- **Live smoke (post-OAuth):** description updates once per `research-marker.json` change, respects 5-min cadence + per-stream cap.

---

Echo path: `hapax-council--cascade-2026-04-18/docs/superpowers/specs/2026-04-18-youtube-broadcast-bundle-design.md`
