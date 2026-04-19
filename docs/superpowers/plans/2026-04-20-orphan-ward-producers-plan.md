# Orphan Ward Producers — Implementation Plan (2026-04-20)

**Owner:** cascade session (hotfix worktree) → delta for execution dispatch.
**Scope:** FINDING-V from the alpha wiring audit 2026-04-19 — five ward inputs
shipped with consumer code but zero producer code. Operator directive
2026-04-19: AUTHOR all five, no retirement.
**Constraint:** this plan is artefact-only. No producer scripts are written
here; Delta will dispatch execution subagents against the phase breakdown
below.

---

## §0. Scope and correction to the brief

The task brief enumerated five "orphan" files. Grounding the work in the
actual consumer code corrects the picture in three non-trivial ways — the
plan must reflect ground truth, not the brief's summary.

1. **`recent-impingements.json` is NOT what `ImpingementCascadeCairoSource`
   reads.** The consumer
   (`agents/studio_compositor/hothouse_sources.py::ImpingementCascadeCairoSource`)
   calls `_active_perceptual_signals(limit=14)` which walks
   `~/.cache/hapax-daimonion/perception-state.json` + `/dev/shm/hapax-stimmung/state.json`.
   It does not open any SHM file named `recent-impingements.json`. A new
   producer feeding that path would render no pixels until the consumer
   is rewritten.
2. **`chat-keyword-aggregate.json` / `chat-tier-aggregates.json` have NO
   reader.** `ChatAmbientWard.render_content()` consumes a state dict whose
   keys come from `ChatSignals` (`t4_plus_rate_per_min`,
   `unique_t4_plus_authors_60s`, `t5_rate_per_min`, `t6_rate_per_min`,
   `message_rate_per_min`, `audience_engagement`). The canonical sink for
   those counters is `/dev/shm/hapax-chat-signals.json`
   (`agents/studio_compositor/chat_signals.py::DEFAULT_CHAT_SIGNALS_PATH`).
3. **`chat-state.json` already has a producer** —
   `scripts/chat-monitor.py::ChatMonitor._write_state` writes it via
   `chat-downloader`. `chat-monitor.service` is enabled and active; the
   reason `/dev/shm/hapax-compositor/chat-state.json` does not exist on
   the live rig is that the process is blocked in `_wait_for_video_id`
   (no `YOUTUBE_VIDEO_ID` env var or
   `/dev/shm/hapax-compositor/youtube-video-id.txt`).

The grounded scope is therefore five **logical** orphans mapping to a
**smaller** set of producer scripts than the brief implied:

| # | Consumer ward | Reader path / contract | Producer action |
|---|---------------|------------------------|-----------------|
| 1 | `impingement_cascade` | reads perception-state + stimmung state (existing files) | ship a narrow re-ranker that publishes a tightened top-N overlay state for the consumer to optionally adopt + add the video-id wire for chat-monitor |
| 2 | `chat_ambient` | state dict keyed by ChatSignals fields | ship `chat_signals_producer.py` driving `ChatSignalsAggregator.write_shm` + wire `ChatAmbientWard.state()` to read `/dev/shm/hapax-chat-signals.json` |
| 3 | `grounding_provenance_ticker` | tails `~/hapax-state/stream-experiment/director-intent.jsonl`, reads `grounding_provenance` field directly | consumer already self-serves; the orphan reading is wrong — ship a broadcast-id resolver + video-id publisher (source of the chat-monitor block) |
| 4 | `whos_here` + hothouse `WhosHereCairoSource` | reads `/dev/shm/hapax-compositor/youtube-viewer-count.txt` | ship `youtube_viewer_count_producer.py` |
| 5 | `stream_overlay` `_format_chat` | reads `/dev/shm/hapax-compositor/chat-state.json` | unblock the existing `chat-monitor.service` by publishing the YouTube video id (covered by §Phase 6 wire-up); no new producer script |

**Consequence:** the plan ships two fully new producers
(`youtube_viewer_count_producer.py`, `chat_signals_producer.py`), one
wiring patch (`agents/studio_compositor/chat_ambient_ward.py` gets a
`state()` override), one new `youtube-broadcast-resolver` shared helper,
one tiny `youtube-video-id-writer` producer that publishes the broadcast
ID into `/dev/shm/hapax-compositor/youtube-video-id.txt` (this both
unblocks `chat-monitor.service` and is reusable by downstream producers),
and one companion re-ranker shim for the impingement cascade consumer.

All SHM writes go through `atomic_write_json` from
`agents/studio_compositor/atomic_io.py` or `shared/stream_archive.py`. No
new tmp+rename helper is required.

---

## §1. Success definition

Per-producer quantitative success criteria. All must hold simultaneously
during a 10-minute live `/dev/video42` capture under working-mode `research`
with a YouTube live broadcast active on the operator's channel.

Per-producer pass conditions:

1. **Consumer ward renders non-empty, non-placeholder content**, verified
   from a single `/dev/video42` frame grab. Definition of "non-empty":
   - `impingement_cascade`: at least 3 rows; no row reads `—`.
   - `chat_ambient`: `[Users(#hapax:1/N)]` shows `N ≥ 0`, `[Mode +v +H]`
     renders in muted tones (T5/T6 at 0.0 is legitimate), rate-gauge row
     has at least one muted cell (empty gauge is fine when rate is 0).
   - `whos_here`: sub-label reads `present · <integer> viewers` where
     `<integer>` is ≥ 0 (0 is fine when broadcast is offline).
   - `stream_overlay`: `[CHAT|…]` row renders via `_format_chat`
     contract; `idle` is acceptable only when chat-monitor's `total=0`,
     not when the producer is missing.
   - `grounding_provenance_ticker`: shows at least one `* <signal>` row
     on any non-empty `grounding_provenance` director intent (already
     works when the director is running — this is verified end-to-end
     post-wiring).

2. **Prometheus freshness gauge** `compositor_source_frame_<id>_age_seconds`
   stays under the expected cadence + 3× grace (2s cadence → < 6s age) for
   at least 90 % of the 10 minute window for every affected ward. Already
   instrumented by `CairoSourceRunner` — the plan does not add new
   gauges for the Cairo sources, only verifies coverage.

3. **Producer freshness gauges** (new):
   - `hapax_ward_producer_freshness_seconds{producer="chat_signals"}`
   - `hapax_ward_producer_freshness_seconds{producer="youtube_viewer_count"}`
   - `hapax_ward_producer_freshness_seconds{producer="youtube_video_id"}`

   Stay below `2 × poll_cadence` for at least 90 % of the window.

4. **YouTube API quota burn stays within plan** (see §4). No HTTP 403
   `quotaExceeded` in the journal for `youtube-*.service` units over a
   24-hour bakeoff window.

5. **Broadcast-offline survival**: after the operator takes the live
   stream offline, all producers continue running, log one `broadcast
   offline` warning, and publish `{"live": false}` (viewer count file
   writes `0`) within 30 s. No crash, no restart spiral.

6. **Consent discipline**: `ChatAmbientWard._coerce_counters` does not
   raise `TypeError` at any runtime tick — verified by absence of the
   specific exception in journal. No author handle appears anywhere
   under `/dev/shm/hapax-compositor/` or `/dev/shm/hapax-chat-signals.json`.

---

## §2. Per-phase breakdown

### Phase 1 — `chat_ambient_ward.state()` wire-up (smallest independent wedge)

**Goal**: make `ChatAmbientWard` pull `/dev/shm/hapax-chat-signals.json`
on every render tick. No new daemon; this is a single file edit in
`agents/studio_compositor/chat_ambient_ward.py`.

**Scope**:
1. Override `CairoSource.state(self) -> dict[str, Any]` on
   `ChatAmbientWard` to read `DEFAULT_CHAT_SIGNALS_PATH` via
   `json.loads` inside a try/except, filtering to the six keys in
   `_COUNTER_KEYS`.
2. Path import comes from `agents.studio_compositor.chat_signals.DEFAULT_CHAT_SIGNALS_PATH`.
3. Cache the last-good dict on `self._last_state_cache` to ride through
   sub-second read failures (file rotation / partial write on tmpfs).
   Freshness expiry: if mtime is older than 120 s, drop to empty dict
   so the ward renders the idle state instead of stale rates.

**Acceptance**:
- Unit test: monkeypatch the path to `tmp_path/chat-signals.json`, write
  a JSON payload with all six counters, call `state()`, assert the
  return dict filters correctly.
- Unit test: monkeypatch path to a non-existent file, assert `state()`
  returns `{}` without raising.
- Unit test: write a payload with a string in `t5_rate_per_min`, assert
  `render_content` raises `TypeError` when the state dict is passed
  into `_coerce_counters`. The existing guard is the right place.

**Risk**: LOW. No new daemon. Change is 20 LOC. Existing test harness
covers the render path.

### Phase 2 — `chat_signals_producer.py` (medium producer)

**Goal**: drive `ChatSignalsAggregator` on a 30 s cadence, writing to
`/dev/shm/hapax-chat-signals.json`. Input: the existing `chat-monitor`
process is the natural arrival point for `ChatMessage` objects — the
cleanest shape is **to fold the aggregator into `chat-monitor.py`**
rather than ship a standalone daemon.

**Shape**:
1. In `scripts/chat-monitor.py`, instantiate a `StructuralSignalQueue`
   (rolling 60 s window) and a `ChatSignalsAggregator` wrapping it.
2. In `ChatMonitor._process_message`: after hashing `author_id`, push a
   `ChatMessage(author_handle=<hash>, text=<redacted_never>, ts=<ts>,
   embedding=<optional>)` into the queue. Never pass raw text downstream;
   the aggregator only needs timestamps, author hashes, optional
   embeddings.
3. Classify each message into `ChatTier` (T1–T6) at push time using
   `agents.studio_compositor.chat_classifier`. Call
   `aggregator.record_classification(ts, tier, author_handle)` with the
   pre-hashed handle. The aggregator hashes again (sha256, first 16 hex
   chars) — this double-hash is cheap and keeps the boundary explicit.
4. Replace the existing `_batch_loop` 30 s cadence action: on each tick,
   call `aggregator.compute_signals(now=time.time())` + `aggregator.write_shm(signals)`.
5. Delete the stale `_publish_structural_signals` implementation — it
   references `agents/chat_monitor/structural_analyzer` which ships
   `StructuralSignals` (a different dataclass) via `agents/chat_monitor/sink.py`.
   The two paths publish to the same SHM file but with different schemas.
   `ChatAmbientWard` needs the `ChatSignals` schema; `StructuralSignals`
   is a dev artefact from the LRR Phase 9 epic. The replacement path
   publishes only `ChatSignals`.
   
   **Open question 1**: retire `agents/chat_monitor/sink.py`? It is
   currently imported by `scripts/chat-monitor.py` but the output
   overlaps with the new aggregator path. Answer: keep as deprecated
   alias for a +30 day window, emit `DeprecationWarning` on import,
   excise after Bayesian R&D sprint 3.

6. Emit producer freshness gauge
   `hapax_ward_producer_freshness_seconds{producer="chat_signals"}` via
   `shared.freshness_gauge.FreshnessGauge` on every successful write.

**Acceptance**:
- Unit test: push 10 `ChatMessage` instances at different tiers into the
  queue, call `compute_signals`, assert the output `ChatSignals` has the
  correct tier aggregates (`t4_plus_rate_per_min` etc.).
- Integration test: spawn chat-monitor against a fixture JSONL chat
  stream, verify `/dev/shm/hapax-chat-signals.json` contents match the
  expected `ChatSignals` fields after a 60 s window.
- Integration test: assert no message text or raw author handle appears
  in `/dev/shm/hapax-chat-signals.json` — grep the serialized payload
  for a known fixture author name, assert no hit.

**Risk**: MEDIUM. Touches an active service. Must preserve the token
ledger + preset reactor + chat-queue paths already in
`chat-monitor.py`. The current `_publish_structural_signals` is a soft
failure (silent skip) so its removal is safe. The aggregator is pure
functions; the queue is pure data.

### Phase 3 — `youtube_broadcast_resolver.py` (shared helper)

**Goal**: resolve the currently-active YouTube broadcast ID, cache it,
refresh on 404, and expose it as a reusable Python module.

**Location**: `shared/youtube_broadcast_resolver.py` (shared because
Phase 4 + Phase 6 both need it; `shared/` is the right layer — this is
not a studio-only capability).

**Shape**:
1. Module-level function
   `resolve_active_broadcast_id(creds) -> tuple[str | None, datetime | None]`
   returns `(broadcast_id, cache_ttl_expiry)`.
2. Internally:
   - Call `liveBroadcasts.list(broadcastStatus=active, part=id,snippet, mine=true)`
     via `googleapiclient.discovery.build("youtube", "v3", credentials=creds)`.
   - If no active, fall through to `broadcastStatus=upcoming` (mirrors
     `scripts/youtube-player.py::_find_active_broadcast`).
   - Return `(items[0]["id"], now + 15min)` on hit, `(None, now + 60s)`
     on miss. The short TTL for the miss path is important — the
     operator goes live mid-session.
3. Module-level cache in a `@dataclass` (`_Cache`) keyed by the string id
   of the creds object so tests can mutate.
4. Single atomic writer: `publish_broadcast_id(path: Path, bid: str | None)`
   writes the id (or empty file on None) atomically. Used by Phase 6's
   video-id publisher.

**Acceptance**:
- Unit test with a mock `googleapiclient` discovery object: inject an
  active broadcast, assert resolver returns its id.
- Unit test: active broadcast path returns empty, upcoming returns a
  broadcast, assert resolver returns the upcoming id.
- Unit test: simulate HTTP 404 on `liveBroadcasts.list`, assert resolver
  returns `(None, short_ttl)` and does not raise.

**Risk**: LOW. Pure logic; no new infrastructure.

### Phase 4 — `youtube_viewer_count_producer.py` (simple YouTube producer)

**Goal**: poll concurrent viewer count on a 60 s cadence and publish to
`/dev/shm/hapax-compositor/youtube-viewer-count.txt`.

**Location**: `scripts/youtube-viewer-count-producer.py` (matches the
filename convention of `scripts/youtube-player.py`,
`scripts/chat-monitor.py`).

**Shape**:
1. Entry point: `main()` loads creds via
   `shared.google_auth.get_google_credentials(["https://www.googleapis.com/auth/youtube.force-ssl"])`.
2. Resolve broadcast id via
   `shared.youtube_broadcast_resolver.resolve_active_broadcast_id(creds)`.
   If None, sleep 30 s and retry (don't burn quota spinning).
3. On a resolved id, poll `videos.list(part=liveStreamingDetails, id=<bid>)`
   every 90 s. Cost: 1 quota unit per call → ~960 units/day.
4. Extract `items[0]["liveStreamingDetails"]["concurrentViewers"]`. The
   field is a **string** per the API (not int); cast to int with a
   try/except ValueError fallback to 0.
5. Write as plain integer text file via atomic tmp+rename. The
   `WhosHereCairoSource` reader casts via `int(text)` — the file must
   not contain a trailing newline, JSON wrapper, or the literal string
   `None`. Write `"0"` when broadcast is offline.
6. On HTTP 404 or broadcast end, invalidate cache via resolver, set
   viewer count to 0, log `broadcast offline`, sleep 30 s, retry.
7. Emit `hapax_ward_producer_freshness_seconds{producer="youtube_viewer_count"}`
   on every successful write.
8. systemd user unit `hapax-youtube-viewer-count.service`:
   - `Type=simple`, `Restart=on-failure`, `RestartSec=10`, `TimeoutStopSec=5`.
   - `After=hapax-secrets.service` (creds need pass available).
   - `WantedBy=default.target`.
   - Environment variables mirror `youtube-player.service`:
     `HOME`, `XDG_RUNTIME_DIR`, `DBUS_SESSION_BUS_ADDRESS`.

**Acceptance**:
- Unit test with mocked `videos.list`: inject `concurrentViewers: "42"`,
  assert `youtube-viewer-count.txt` contains exactly `42` (no newline,
  no JSON).
- Unit test with broadcast offline: assert the file contains `0`.
- Integration test (manual, operator-gated): run against the live
  broadcast, verify viewer count updates within 90 s of a real viewer
  entering.

**Risk**: LOW-MEDIUM. Single API endpoint, tiny quota footprint. Main
failure mode is broadcast-id resolver returning stale ids after the
operator ends a broadcast; 30 s fallback cadence + cache invalidation
covers it.

### Phase 5 — `youtube-video-id-publisher.service` (unblocks chat-monitor)

**Goal**: publish the active YouTube broadcast id into
`/dev/shm/hapax-compositor/youtube-video-id.txt` so `chat-monitor.py`
unblocks its `_wait_for_video_id()` loop. This is the wiring step that
lets `chat-state.json` actually appear on the live rig.

**Shape**:
1. Minimal daemon script `scripts/youtube-video-id-publisher.py`.
2. Every 60 s: call the shared resolver, write result to
   `/dev/shm/hapax-compositor/youtube-video-id.txt` via atomic
   tmp+rename.
3. Quota cost: 1 unit per `liveBroadcasts.list` call → 1440 units/day,
   cache-ttl reduces to a few hundred actual calls/day.
4. Emit producer freshness gauge
   `hapax_ward_producer_freshness_seconds{producer="youtube_video_id"}`.
5. systemd unit `hapax-youtube-video-id.service`:
   - Same systemd boilerplate as Phase 4.
   - `Before=chat-monitor.service` so the id is available when chat-monitor
     starts polling.

**Acceptance**:
- Unit test: mock resolver returns an id, assert file contents.
- Integration test: start the service, verify chat-monitor.service
  transitions from `_wait_for_video_id()` warning state to active
  polling within 60 s of a broadcast going live.

**Risk**: LOW. Single function + systemd unit.

### Phase 6 — `impingement_cascade` overlay path

**Goal**: address the consumer contract mismatch flagged in §0(1).

**Operator question 2 (blocking decision, surfaced below in §11)**: does
the operator want the consumer rewritten to read a new
`recent-impingements.json`, or is the existing walk of
`perception-state.json` + `stimmung/state.json` the grounded behaviour?

If the operator's intent was **"what the ward already does is fine, just
make sure something is writing the upstream perception state"**, then
FINDING-V is a false positive for this ward — both files exist and are
maintained by existing daemons (hapax-daimonion publishes
`perception-state.json`; VLA publishes `stimmung/state.json`).

If the operator's intent was **"surface a narrowed-salience feed distinct
from raw perception"**, then the right shape is:
   
1. New `scripts/recent-impingements-producer.py` that tails
   `/dev/shm/hapax-dmn/impingements.jsonl`, selects last 15 entries with
   `salience >= 0.35`, and writes
   `/dev/shm/hapax-compositor/recent-impingements.json`.
2. Modify `ImpingementCascadeCairoSource.render_content` to prefer the
   new file when present, falling back to `_active_perceptual_signals`
   when absent. This preserves backwards compatibility and gives the
   operator an override path.
3. systemd unit `hapax-recent-impingements.service` — `Type=simple`,
   2 s poll cadence on `impingements.jsonl`.

The plan treats Phase 6 as **conditional** pending operator answer on
Question 2. The default assumption (encoded in the phase DAG below) is
the **second interpretation** — ship the new producer + the consumer
preference path — since that is the only interpretation that closes
FINDING-V for this ward.

**Acceptance** (conditional):
- Unit test: seed `impingements.jsonl` with 20 entries of varying
  salience, assert the producer writes exactly 15 with salience ≥ 0.35.
- Unit test: ward prefers `recent-impingements.json` when present,
  falls back to perception-state walk when absent.

**Risk**: MEDIUM. The ward is high-traffic; a contract change has
visible consequences on the stream. The fallback path is a hedge.

### Phase 7 — Deploy and observability wrap

**Goal**: enable the new systemd units, verify Grafana tiles light up,
confirm metrics reach Prometheus.

**Actions**:
1. `systemctl --user daemon-reload` + `systemctl --user enable --now`
   for each new unit.
2. Add freshness-gauge panels to `grafana/dashboards/compositor.json`:
   one per producer, threshold line at `2 × cadence`.
3. `loginctl enable-linger hapax` (already enabled; no-op verification).
4. Update `systemd/expected-timers.yaml` if any timers were added (none
   in this plan — all units are long-running services).
5. Dry-run verification: grep the `/metrics` endpoint at
   `127.0.0.1:9482` for the three new `hapax_ward_producer_freshness_seconds`
   labels.
6. Live verification: capture a single `/dev/video42` frame via
   `ffmpeg -y -f v4l2 -i /dev/video42 -frames:v 1 /tmp/orphan-verify.jpg`
   and confirm:
   - `chat_ambient` cell shows live `N` ≥ 0 unique authors.
   - `whos_here` sub-label shows live `viewers` count.
   - `stream_overlay` `[CHAT|…]` row shows live idle/quiet/active state.
   - (If Phase 6 shipped) `impingement_cascade` shows non-empty rows.
7. 24-hour bakeoff: verify no `quotaExceeded` in journal, no
   `RestartSec` loops, no freshness-gauge regressions.

---

## §3. Shared helpers to extract

Exactly one new helper: `shared/youtube_broadcast_resolver.py` (Phase 3).
Its `resolve_active_broadcast_id` is used by Phase 4 (viewer count) and
Phase 5 (video id publisher).

**Not extracted**:
- `atomic_write_json` already exists in two canonical locations
  (`agents/studio_compositor/atomic_io.py`,
  `shared/stream_archive.atomic_write_json`). Reusing these directly is
  correct; shipping a third copy would regress the 2026-04-13 delta drop
  #41 finding 2 cleanup.
- Google OAuth credential loading is already abstracted in
  `shared/google_auth.py::get_google_credentials`. Every new YouTube
  producer calls it identically; no wrapper is needed.

---

## §4. Quota and rate-limit budget

YouTube Data API v3 default quota: **10,000 units per project per day**.
All new producers share the existing project-level quota used by
`scripts/youtube-player.py::LivestreamDescriptionUpdater` and by the
sync agent ecosystem (`youtube-sync.service`).

### Per-endpoint cost (from YouTube Data API v3 cost table)
- `liveBroadcasts.list` — 1 unit per call.
- `liveChatMessages.list` — 5 units per call.
- `videos.list` (with `liveStreamingDetails`) — 1 unit per call.
- `videos.update` — 50 units per call (used by the existing
  `LivestreamDescriptionUpdater`, not this plan).

### Per-producer day-budget

| Producer | Endpoint | Cadence | Calls/day | Units/day |
|----------|----------|---------|-----------|-----------|
| youtube-video-id-publisher | liveBroadcasts.list | 60 s (cached 15 min on hit) | ~96 resolves | ≤ 96 |
| youtube-viewer-count-producer | videos.list | 90 s | 960 | 960 |
| youtube-viewer-count-producer | liveBroadcasts.list (cache-miss only) | on 404 | ~10 | ~10 |
| chat-monitor (already running) | — | `chat-downloader` library, not Data API | N/A | 0 |
| Existing `LivestreamDescriptionUpdater` | liveBroadcasts.list + videos.update | on-track-change | ~60 | ~3000 |
| Existing `youtube-sync.service` | various | 6 h | small | ~500 |

**Planned day-budget total from this plan**: ≤ 1,100 units.
**Ecosystem total (plan + existing)**: ≤ ~4,700 units, well under the
10,000 ceiling with head-room for a second live stream and unforeseen
retry amplification.

### Defensive quota handling

Each producer:
1. Wraps API calls in a per-call retry-with-backoff (2 retries, 2 s +
   4 s delay) on HTTP 5xx.
2. On HTTP 403 `quotaExceeded`, logs a single warning, holds the
   last-good value, and sleeps for 1 hour before retrying. No crash,
   no restart spiral.
3. Publishes a Prometheus counter `youtube_api_quota_hits_total{producer=...}`
   so the operator can see quota exhaustion in Grafana.

**Note**: `liveChatMessages.list` is not used by any producer in this
plan. The chat contents path (`scripts/chat-monitor.py`) uses the
`chat-downloader` PyPI package which scrapes the YouTube web chat
endpoint, not the Data API. This is critical — the brief's worry
about chat quota burn at 3 s poll cadence does not apply because we
are not using the Data API for chat.

---

## §5. Non-goals

1. **No Twitch API integration.** `agents/studio_compositor/twitch_director.py`
   stays untouched. Its `_CHAT_RECENT_PATH` reads
   `/dev/shm/hapax-compositor/chat-recent.json` which is already
   produced by `scripts/chat-monitor.py::_write_state` (line 401).
2. **No chat moderation.** The producers read, they do not moderate. All
   text redaction happens at the boundary; counters flow onward.
3. **No chat persistence beyond the SHM snapshot.** Per axiom
   `interpersonal_transparency`: no persistent state about non-operator
   persons without active consent contract. The SHM files are tmpfs-backed
   and evaporate at reboot.
4. **No author-identified chat display.** `ChatAmbientWard`'s aggregate
   contract is constitutional. Author handles are hashed at the
   boundary and never surface in the SHM JSON.
5. **No migration of `scripts/mock-chat.py`.** It is a dev tool; once
   `chat-state.json` ships in production it is unused. Explicit
   retirement is out of scope for this plan; a separate follow-up PR
   moves it under `tests/fixtures/` if the operator wants it preserved.
6. **No new LLM calls.** All producers are deterministic aggregation
   layers. The existing LLM batch analysis in `chat-monitor.py` is
   unchanged.

---

## §6. Consent and governance

Per axiom `interpersonal_transparency` (weight 88, T0) and the specific
redaction invariant codified on `ChatAmbientWard`
(`chat_ambient_ward.py::_coerce_counters`):

| Data class | Flow boundary | Persistent state? |
|-----------|---------------|-------------------|
| Chat aggregate counters (rates, unique hashes) | SHM (tmpfs) | No |
| Chat author handles | Hashed (sha256, first 16 hex) at push boundary, never leave the ChatSignalsAggregator | No |
| Chat message text | Never reaches the aggregator; never written to SHM | No |
| Viewer count | Public API surface | No |
| Impingement cascade entries | Operator-authored perception events | No external persons |
| Grounding provenance | Director-authored text | No external persons |

Every new producer carries a **no-logging-of-chat-text** invariant.
Covering test: grep the journal after a fixture chat session for a
known distinctive message — assert no hit. This test ships with the
Phase 2 integration suite.

Broadcast-id publication (Phase 5) exposes the YouTube video id in an
SHM file under `/dev/shm/hapax-compositor/`. The video id is a public
URL-embedded value — posting it under a local-only SHM path is below
the consent bar.

---

## §7. DAG and critical path

```
Phase 3 (resolver, shared helper)
  ├── Phase 4 (viewer count producer)
  └── Phase 5 (video-id publisher)
         └── unblocks chat-monitor.service
                └── Phase 1 (ChatAmbientWard.state() wire-up)
                        └── Phase 2 (chat_signals_producer inside chat-monitor)

Phase 6 (impingement cascade) — independent, runs in parallel with Phases 3–5
  └── BLOCKED on operator answer to Question 2 (see §11)

Phase 7 (deploy + observability) — depends on all prior
```

**Critical path**: Phase 3 → Phase 5 → Phase 1 → Phase 2 → Phase 7.
Estimated effort (single session, small PRs):
- Phase 1: 1 PR, ~30 min.
- Phase 2: 1 PR, ~2 h (touches live service; needs integration fixture).
- Phase 3: 1 PR, ~45 min.
- Phase 4: 1 PR, ~45 min.
- Phase 5: 1 PR, ~30 min.
- Phase 6: 1 PR, ~1 h (conditional).
- Phase 7: 1 PR for Grafana/systemd wiring, ~30 min + 24 h bake.

**Total**: 6–7 PRs, ~5 h implementation + 24 h bake-off.

---

## §8. Risk register

| Phase | Risk | Likelihood | Mitigation |
|-------|------|-----------|------------|
| 1 | `state()` read cost on the hot render thread | LOW | File-mtime guard + last-good cache, 120 s staleness window |
| 2 | Breaking chat-monitor.service mid-stream | MEDIUM | Integration fixture against JSONL chat replay before merge; canary on beta worktree first |
| 2 | ChatClassifier cost-per-message on hot path | LOW | Existing classifier already runs on every message in the LRR Phase 9 path |
| 3 | Resolver cache thrash under broadcast flicker | LOW | 60 s min TTL on cache-miss |
| 4 | YouTube returns `concurrentViewers: None` for some broadcast states | MEDIUM | Try/except, default to 0 |
| 5 | video-id race with chat-monitor startup | LOW | `Before=chat-monitor.service` in systemd + chat-monitor's existing `_wait_for_video_id()` poll |
| 6 | Consumer contract change lands without producer ready | MEDIUM | Consumer-preference pattern — ward prefers new file, falls back to existing walk; zero-downtime |
| 7 | Grafana dashboards not updated in lockstep with metrics | LOW | Add dashboard JSON in same PR as producer |

Ecosystem-wide risks:
- **YouTube quota exhaustion affecting OTHER systems**: the shared
  project quota is consumed by `LivestreamDescriptionUpdater` and
  `youtube-sync.service`. Adding ~1100 units/day leaves ~5000 units of
  head-room. A single `videos.update` burst from the description updater
  can still cause a quota event; §4 defensive handling covers the
  behaviour.
- **Running producers during non-live periods**: all producers handle
  broadcast-offline gracefully. Running them during a non-stream day
  costs ~120 units/day (resolver-miss cost only).

---

## §9. Branch and PR strategy

Per workspace CLAUDE.md branch discipline: one PR per phase, merge in
DAG order. No stacked branches.

PR titles and conventional commit scopes:

1. `feat(studio): wire ChatAmbientWard to hapax-chat-signals.json` —
   Phase 1.
2. `feat(chat): fold ChatSignalsAggregator into chat-monitor` — Phase 2.
3. `feat(shared): add youtube-broadcast-resolver` — Phase 3.
4. `feat(yt): ship youtube-viewer-count producer` — Phase 4.
5. `feat(yt): ship youtube-video-id publisher` — Phase 5.
6. `feat(studio): add recent-impingements producer + consumer
   preference` — Phase 6 (conditional).
7. `chore(obs): grafana + systemd for orphan ward producers` — Phase 7.

**Merge order**: 3 → 5 → 1 → 2 → 4 → (6) → 7. The ordering minimizes
partial states — by the time Phase 1 merges, Phase 5 has already
unblocked chat-monitor so `chat-state.json` is live; by Phase 2 the
counters are flowing; Phase 4 is independent and can land earlier if
convenient.

**CI**: every PR includes unit tests at minimum. Phase 2 and Phase 7
include integration tests against fixture JSONL streams. Every PR
bundles a non-docs change to trigger branch-protection checks (per
council CLAUDE.md note on `paths-ignore` behaviour).

**Ownership**: the author of each PR owns it through merge, per
workspace policy. After Phase 2 merges, rebase alpha onto main so the
running vite dev server + compositor service pick up the change (the
chat-monitor process will auto-restart on unit-file change via systemd;
no manual intervention).

---

## §10. Acceptance checklist

Before marking FINDING-V closed:

- [ ] `ls /dev/shm/hapax-compositor/chat-state.json` — exists,
  mtime < 120 s.
- [ ] `ls /dev/shm/hapax-compositor/youtube-viewer-count.txt` — exists,
  mtime < 180 s, contents parse as `int`.
- [ ] `ls /dev/shm/hapax-compositor/youtube-video-id.txt` — exists,
  contents match the active broadcast id or empty.
- [ ] `ls /dev/shm/hapax-chat-signals.json` — exists, mtime < 60 s,
  JSON parses to `ChatSignals` schema.
- [ ] (Phase 6 conditional) `ls /dev/shm/hapax-compositor/recent-impingements.json`
  — exists, mtime < 10 s, JSON is a list of objects with `salience` key.
- [ ] `systemctl --user status hapax-youtube-viewer-count.service` —
  active, no `Restart=` spiral.
- [ ] `systemctl --user status hapax-youtube-video-id.service` —
  active.
- [ ] `systemctl --user status chat-monitor.service` — active, journal
  shows transition from `_wait_for_video_id()` to message-processing.
- [ ] `curl -s http://127.0.0.1:9482/metrics | grep hapax_ward_producer_freshness_seconds`
  — returns three lines for `chat_signals`, `youtube_viewer_count`,
  `youtube_video_id`.
- [ ] `ffmpeg -f v4l2 -i /dev/video42 -frames:v 1 /tmp/verify.jpg` plus
  visual inspection of the captured frame confirms non-empty rendering
  of all five wards.
- [ ] 24 h bakeoff: `journalctl --user -u hapax-youtube-*.service --since=-1d | grep quotaExceeded`
  returns nothing.
- [ ] 24 h bakeoff: no `TypeError` from `_coerce_counters` in journal.
- [ ] No chat author name or message text appears in any SHM JSON
  (grep-verified with known fixture handles).

---

## §11. Open questions blocking execution

Operator answers needed before Phase 2 and Phase 6 can dispatch.

1. **Multi-channel broadcast selection** (blocks Phase 3, Phase 4, Phase 5):
   when multiple live broadcasts exist on the authenticated account,
   which one does the resolver pick? Options:
   - A. Newest by `snippet.publishedAt` (default today, implicit from
     API order).
   - B. Channel-tagged — require the operator's main channel id and
     filter. Adds a config env var `HAPAX_YOUTUBE_CHANNEL_ID`.
   - C. `broadcastStatus=active` (not `upcoming`) if present, else
     newest upcoming.
   **Default if unanswered**: C.

2. **Impingement cascade scope** (blocks Phase 6):
   is FINDING-V for `recent-impingements.json` a false positive (the
   consumer already works off existing files and no new producer is
   needed), or a real gap (the operator wants a salience-filtered feed
   distinct from the raw perception walk)?
   **Default if unanswered**: real gap — ship Phase 6 as a
   consumer-preference overlay.

3. **Chat tier classification at push time** (Phase 2):
   the `ChatClassifier` has a T1–T6 tier system. The plan assumes every
   message is classified once at queue-push time. If the classifier is
   expensive (embedding call), this is a CPU hit proportional to chat
   rate. Should classification be async / batched?
   **Default if unanswered**: synchronous at push, measure in canary,
   batch later if CPU shows measurable regression.

4. **Keyword extraction scope** (brief §Phase 3 mentioned this):
   the brief asked for a per-tick keyword extraction. `ChatSignals` as
   implemented does not carry keywords — it carries rates. Is the
   keyword extraction out of scope (the brief was over-broad), or does
   the operator want a separate `chat-keywords.json` surface? No
   existing consumer reads such a file.
   **Default if unanswered**: out of scope for this plan; add as a
   separate FINDING if the operator wants it.

5. **`agents/chat_monitor/sink.py` retirement** (Phase 2):
   the duplicate `StructuralSignals` path writing to
   `/dev/shm/hapax-chat-signals.json` with a different schema — do we
   keep it as deprecated, or excise immediately?
   **Default if unanswered**: deprecate with `DeprecationWarning`, excise
   after 30 days.

---

## §12. Cross-references

- FINDING-V source: alpha wiring audit 2026-04-19 (session handoff document).
- Consumer contracts:
  - `agents/studio_compositor/stream_overlay.py::_format_chat` (lines 78–88)
  - `agents/studio_compositor/chat_ambient_ward.py::_COUNTER_KEYS` (lines 58–65)
  - `agents/studio_compositor/chat_ambient_ward.py::_coerce_counters` (lines 194–223)
  - `agents/studio_compositor/hothouse_sources.py::WhosHereCairoSource` (lines 863–988)
  - `agents/studio_compositor/hothouse_sources.py::ImpingementCascadeCairoSource` (lines 229–371)
  - `agents/studio_compositor/legibility_sources.py::GroundingProvenanceTickerCairoSource` (lines 652–775)
- Existing producer infrastructure:
  - `shared/google_auth.py::get_google_credentials` (already covers all scopes)
  - `scripts/youtube-player.py` (systemd pattern + OAuth cache pattern)
  - `scripts/chat-monitor.py` (chat-state.json producer, currently blocked on video-id)
  - `agents/studio_compositor/chat_signals.py::ChatSignalsAggregator` (unwired aggregator)
  - `agents/studio_compositor/atomic_io.py::atomic_write_json` (tmp+rename helper)
- Governing axiom: `interpersonal_transparency` (weight 88, T0,
  `axioms/registry.yaml`).
- Consent retirement scope: `docs/governance/consent-safe-gate-retirement.md`.

---

## §13. Plan summary

Five ward inputs, five phases plus a deploy wrap, six PRs (seven if
Phase 6 conditional ships). Quota cost ≤ 1,100 units/day. Zero new
external dependencies; all new code sits inside existing infrastructure
(systemd user units, `shared/google_auth.py`, compositor chrome).

Two blocking operator questions (§11 Q1, Q2). Sensible defaults encoded
so Delta can dispatch Phase 3 + Phase 5 + Phase 4 in parallel
immediately without waiting for answers, and Phase 1 + Phase 2 sequence
once Phase 5 lands.

FINDING-V closes when the §10 acceptance checklist is green and the
24-hour bakeoff completes without quotaExceeded events.
