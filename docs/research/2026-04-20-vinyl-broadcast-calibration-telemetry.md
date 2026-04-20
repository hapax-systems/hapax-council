# Vinyl Broadcast Calibration + Telemetry: Scientific Instrumentation for the Livestream-as-Research-Instrument

Status: research
Date: 2026-04-20
Operator: single hip-hop producer ("LegomenaLive" YouTube channel)
Parent doc: [2026-04-20-vinyl-collection-livestream-broadcast-safety.md](2026-04-20-vinyl-collection-livestream-broadcast-safety.md) §8 (pre-stream checklist + mid-stream fallback) + §9 (items "actually unknowable without trial")
Stack reference: parent doc §7 routing diagram (Handytraxx → Evil Pet + Torso S-4 → Zoom L6 → host VST chain → YouTube RTMP)
Register: engineering + scientific. Distinguishes measurable signal from interpretation, observed behavior from documented behavior.

---

## §1 TL;DR

The scientific-instrumentation problem is: **how do we calibrate transformation-defeats-Content-ID hypotheses without burning the YouTube channel as test apparatus?** The third strike is catastrophic and irreversible (channel termination + ban on new channels — [YouTube Help: Understand copyright strikes](https://support.google.com/youtube/answer/2814000)), so the empirical loop must be staged outside the production channel. The viable test venues, ranked by safety and signal quality:

1. **YouTube private/unlisted upload + Checks** — same Content ID engine as live, but a claim against a private/unlisted upload yields a *claim*, not a *strike* (claims do not accrue toward the 3-strike threshold; strikes only arise from formal §512 takedown notices, per YouTube). This is the primary calibration venue.
2. **YouTube pre-publish "Checks"** — surfaces copyright + ad-suitability flags before publish ([YouTube Help: Use Copyright Match Tool](https://support.google.com/youtube/answer/7648743), [Social Media Today on Checks rollout](https://www.socialmediatoday.com/news/youtube-rolls-out-copyright-checks-tool-which-analyzes-your-video-prior-to/596922/)). Treat as fast pre-flight; not the final authority.
3. **Pex Attribution Engine (free)** — third-party fingerprint lookup, free and unmetered for individual creators ([Pex Attribution Engine launch](https://www.decodedmagazine.com/pex-introduces-its-new-free-attribution-engine-to-connect-creatorscopyright-and-content-seamlessly/), [Pex technology](https://pex.com/technology/)). Useful as a second-source fingerprint check.
4. **ACRCloud / AcoustID / Dejavu** — open / commercial fingerprinting for our own corpus only; cannot mirror Content ID's reference catalog.
5. **Mixcloud upload** — Mixcloud's own fingerprinter blocks non-compliant uploads ([Mixcloud Help: Featured Artist Rules](https://help.mixcloud.com/hc/en-us/articles/360004031080-What-are-the-Featured-Artist-Rules-and-why-is-my-upload-unavailable-for-copyright-reasons)), so a successful Mixcloud upload tells us "Mixcloud's licensed catalog covers this transformation," not directly "YouTube's Content ID will let it pass." Useful as a third-source signal.

**Bayesian framing.** Each `(track_id, transformation_pattern)` tuple is a hypothesis with a Beta-prior of safety. Smitelli's 2020 thresholds ([scottsmitelli.com](https://www.scottsmitelli.com/articles/youtube-audio-content-id/)) give us informed priors. Each unlisted upload result updates the posterior, exactly the conjugate-prior Beta(α+S, β+n−S) update used by Hapax's existing Thompson sampling for affordance recruitment ([Wikipedia: Thompson sampling](https://en.wikipedia.org/wiki/Thompson_sampling), [Stanford TS Tutorial](https://web.stanford.edu/~bvr/pubs/TS_Tutorial.pdf)). Per-track per-Mode safety scores accumulate over time and drive pre-stream rehearsal.

**Three highest-priority Prometheus metrics to ship FIRST** (the "if we only get three, ship these" set):

1. `hapax_vinyl_broadcast_panic_mute_total{trigger}` — counter. Every time Mode C panic-mute fires, with the trigger source (operator manual, chat keyword, API warning, audio-loss heartbeat). This is the **single load-bearing safety metric** — its rate-of-change over 24h directly predicts the strike-risk trajectory.
2. `hapax_vinyl_broadcast_track_played_total{track_id, mode, monetization_risk}` — counter. Every time a track starts in a given Mode. With `panic_mute_total` this gives the per-track per-Mode hazard rate.
3. `hapax_vinyl_broadcast_mode{mode}` — gauge (1 for active mode, 0 otherwise). Joined against the panic counter at query time, this gives "panic events per Mode-second" — the derived KPI that drives rehearsal calibration.

Three metrics, two questions answered: *am I escalating risk* (panic_mute_total slope) and *which routing config is responsible* (mode-aware track + mode gauge).

---

## §2 Pre-Stream Calibration Without Burning the Channel

### §2.1 The fundamental constraint

YouTube enforces a 3-strike rolling-90-day rule with channel termination on the third ([YouTube Help: Understand copyright strikes](https://support.google.com/youtube/answer/2814000), [YouTube Blog: Making our strikes system clear and consistent](https://blog.youtube/news-and-events/making-our-strikes-system-clear-and/)). On the live stream itself, even **one** copyright-removal of an active stream produces a strike + 7-day livestream restriction ([Business Standard summary of three-strike rule](https://www.business-standard.com/technology/tech-news/youtube-s-three-strike-rule-what-creators-should-know-and-how-to-appeal-125052600554_1.html)). So the calibration loop must NOT use the live stream as the test surface. It must use surrogate venues that share enough of YouTube's enforcement apparatus to be informative, but where an adverse result is recoverable.

The crucial doctrinal asymmetry: **a Content ID claim against an unlisted/private upload is not a strike** — strikes arise only from formal §512 removal requests. Private/unlisted uploads are scanned by Content ID at the same intensity as public ones (a 2023 community study found 94.3% of unlisted uploads matched within 4 minutes — see [LifeTips on private/unlisted scanning](https://lifetips.alibaba.com/tech-efficiency/how-to-avoid-copyright-strikes-on-private-and-unlisted)), and the resulting claim sits on the upload but does not accrue toward strike-count. This makes private upload the **primary calibration substrate**.

### §2.2 YouTube private/unlisted upload as Content ID test rig

Procedure for a single hypothesis test:

```
1. Render N seconds of {track, transformation_mode, params} to a video file (audio-only is fine; pair with static image).
2. Upload to YouTube as PRIVATE.
3. Wait for "Checks" stage to complete (typically 1–10 min for short clips; up to 30 min for longer).
   Reference: YouTube Help: Copyright Match Tool documentation, OTTVerse on Checks rollout.
4. Read claim status from Studio (Copyright tab) or via API.
5. Record outcome to local JSONL: {test_id, track_id, mode, params, ts, claim_status, claim_owner, policy}.
6. Delete upload (optional; private uploads count toward storage but not policy).
7. Update Bayesian posterior for (track_id, mode, params) tuple.
```

**Cost per test:** ~5 min wall-clock + ~30s operator time (queue, observe, record). At 12 tests/hour that's ~36 sec of human attention per test — bursty but parallelizable across N tracks rendered in batch.

**Caveat — fingerprint version drift:** YouTube does not version its Content ID model publicly. Smitelli 2020's ~6% pitch / ~4–5% resampling thresholds are stale; modern model is reportedly more aggressive on neural-fingerprint matching. Re-run baseline calibration once per quarter.

**Caveat — live vs VOD fingerprint may differ:** parent doc §9 item 2. Live Content ID is more compute-constrained; reports suggest it is slightly *less* sensitive. So a private-upload test result is a **conservative** signal — anything that passes private-upload Checks is very likely to pass live, but the converse isn't guaranteed.

### §2.3 YouTube pre-publish "Checks" tool

[YouTube Help: Use Copyright Match Tool](https://support.google.com/youtube/answer/7648743) and [Social Media Today rollout coverage](https://www.socialmediatoday.com/news/youtube-rolls-out-copyright-checks-tool-which-analyzes-your-video-prior-to/596922/) document the pre-publish Checks step: when uploading, YouTube offers an optional pre-flight scan against Content ID + ad-suitability rules. Outcomes:

- Green = no issues found
- Yellow = monetization restriction (territorial or ad-suitability)
- Red = block

This is the mechanism `agents/youtube_calibration.py` should poll via Studio (no public API for direct claim-status read on private uploads — confirmed by absence in [YouTube Data API v3](https://developers.google.com/youtube/v3/) and [Reporting API](https://developers.google.com/youtube/reporting) docs, though the [Copyright Match Tool](https://support.google.com/youtube/answer/7648743) does have automation surfaces in YouTube Studio for asset-creator accounts). Practical implementation: scrape Studio's copyright tab via authenticated browser automation (Playwright with persistent profile) — slow but reliable.

### §2.4 Pex Attribution Engine (free, third-party)

[Pex Attribution Engine](https://pex.com/) launched as a free service for individual creators ([Decoded Magazine launch coverage](https://www.decodedmagazine.com/pex-introduces-its-new-free-attribution-engine-to-connect-creatorscopyright-and-content-seamlessly/)). Pex's reference catalog covers ~20 billion fingerprints ([Designing for Analytics episode](https://designingforanalytics.com/resources/episodes/039-how-pex-fingerprinted-20-billion-audio-and-video-files-and-turned-it-into-a-product-to-help-musicians-artists-and-creators-monetize-their-work/)) — close in scale to YouTube's. Pex licenses its tech to platforms (Facebook/Meta uses Pex), so a Pex match strongly correlates with what other large platforms detect, though not 1:1 with YouTube's specific fingerprint.

**Operator usage path:**

1. Free Attribution Engine via Pex's web dashboard (drm.pex.com or attribution.pex.com).
2. Bulk asset upload (audio file → fingerprint → match report).
3. For continuous tracking across platforms: Discovery service starts at $1/file/month ([Pex Discovery FAQ PDF](https://3053552.fs1.hubspotusercontent-na1.net/hubfs/3053552/Pex%20Discovery%20Real%20time%20FAQ%209523%20.pdf)).

For our calibration purpose: Pex's Attribution Engine gives a **second opinion** on whether a transformation is detectable. If both YouTube private upload AND Pex flag the transformation, confidence in failure is high. If only YouTube flags it, the issue is YouTube-specific (e.g., Music Reports / NMPA pipeline that doesn't reach Pex's catalog).

### §2.5 Open-source fingerprinters: Chromaprint / AcoustID, Dejavu, audfprint

These are useful for **building our own reference catalog of the operator's record collection** — not for predicting Content ID matches against major-label catalog (we don't have access to YouTube's reference set). Use cases:

- **Identify which records are in our crate** (given a vinyl rip, fingerprint and resolve via [AcoustID](https://acoustid.org/) for MusicBrainz metadata enrichment — same engine as the [beets chroma plugin](https://beets.readthedocs.io/en/stable/plugins/chroma.html)).
- **Detect which transformations defeat our own fingerprinter** — Chromaprint analyzes the first 120s, 12 chroma bins at 8 Hz ([Chromaprint algorithm overview by Lukáš Lalinský](https://oxygene.sk/2011/01/how-does-chromaprint-work/), [Essentia documentation](https://essentia.upf.edu/tutorial_fingerprinting_chromaprint.html)). If Chromaprint can no longer match our transformed output to the original, that's a *necessary but not sufficient* condition for defeating Content ID (which uses a more sophisticated model).
- **Test transformation-resilience comparators**: Panako and similar are explicitly designed to remain robust to time-stretch and pitch-shift ([Comparative Analysis of Audio Fingerprinting Algorithms IJCSET](https://www.ijcset.com/docs/IJCSET17-08-05-021.pdf)) — Chromaprint is *not*. So a transformation that defeats Chromaprint defeats only the Shazam-style class; defeating Panako-style hashing is the harder bar.
- **Dejavu** ([github.com/worldveil/dejavu](https://github.com/worldveil/dejavu)) hits 100% recall on disk-read against fingerprinted catalog and ~96% on 2s of microphone audio per [Will Drevo's writeup](https://willdrevo.com/fingerprinting-and-audio-recognition-with-python/). Useful as a local sanity check.
- **audfprint** (Dan Ellis at Columbia/LabROSA) — peak-pair Shazam-style fingerprinter; closer in lineage to Content ID's underlying approach than Chromaprint's chroma-class approach.

**Practical recommendation:** maintain a local Chromaprint+audfprint dual-fingerprint of our entire vinyl crate, indexed in Qdrant under a new collection `legomena_vinyl_fingerprints`. This is independently useful for now-playing identification when the operator is unsure which side they just dropped.

### §2.6 Mixcloud as a mirror test venue

Per parent doc §4, Mixcloud holds platform-level licenses and runs its own fingerprinter ([Mixcloud Help: Featured Artist Rules](https://help.mixcloud.com/hc/en-us/articles/360004031080-What-are-the-Featured-Artist-Rules-and-why-is-my-upload-unavailable-for-copyright-reasons), [Mixcloud Live blog on copyright](https://www.mixcloud.com/blog/2025/01/01/how-to-live-stream-music-without-copyright-takedown-issues/), [Mixcloud upload flow](https://www.mixcloud.com/blog/2022/10/17/how-to-upload-tracks-on-mixcloud/)).

**Asymmetry from YouTube:** Mixcloud's enforcement is licensed-or-block, not licensed-or-monetize. A Mixcloud upload that succeeds tells us "this transformation is unrecognizable to Mixcloud's fingerprinter (which is licensed by industry partners)" — strong evidence the source is unrecognizable to fingerprint-class methods generally. A Mixcloud upload that fails tells us either (a) the fingerprint matched, or (b) the matched track exceeds Featured Artist Rules limits.

**Use as a tertiary calibration channel** — slow (manual upload), but the failure mode is non-punitive (block of upload, not strike against the operator's identity), and Mixcloud's catalog overlaps differently with YouTube's, so it surfaces cases YouTube might miss.

### §2.7 Non-options to be explicit about

- **Audio-recognition-as-a-service (Shazam SDK, Apple Music etc.)**: not exposed for arbitrary "does this look like X" queries.
- **YouTube Studio's Copyright Match Tool** (per [YouTube Help](https://support.google.com/youtube/answer/7648743)): **does not** check arbitrary uploads against Content ID catalog. It scans for matches of the operator's own asserted-rights content elsewhere on YouTube. Useful for the operator's *own* originals being re-uploaded; useless for "does my transformed vinyl match a major-label Content ID asset?" That's what private upload + Checks accomplishes.
- **Identifyy / AdRev / HAAWK** ([Identifyy](https://www.identifyy.com/), [HAAWK](https://www.haawk.com/), per [Sound on Sound forum discussion](https://www.soundonsound.com/forum/viewtopic.php?t=89282) and [Passive Promotion comparison](https://passivepromotion.com/audiam-adrev-and-youtube-content-id/)): these are Content ID *administrators* — they help rights-holders register and monetize their assets in YouTube's CID system. They are not test surfaces for the operator's transformation-defeat hypotheses.

---

## §3 Bayesian Hypothesis-Test Framework for Transformation Patterns

### §3.1 Hypothesis as a tuple

Each calibration test is a hypothesis of the form:

```
H : transformation_pattern P defeats Content ID for source-track T
  where P = (mode, grain_size_ms, density, pitch_jitter_cents, dry_wet, ...)
        T = (artist, album, track, release_year, label)
        defeat = no claim raised against private/unlisted upload of P(T)
```

Outcome is binary per trial. Multiple trials per `(P, T)` tuple build a Beta posterior on `θ = P(defeat | P, T)`. Standard conjugate Bayesian update ([Wikipedia: Thompson sampling](https://en.wikipedia.org/wiki/Thompson_sampling), [Bayesian A/B testing with Thompson sampling — Zlatan Kremonic](https://zlatankr.github.io/posts/2017/04/07/bayesian-ab-testing), [Towards Data Science: Bayesian A/B testing](https://towardsdatascience.com/bayesian-a-b-testing-explained-344a6df88c1a/)):

```
prior:     θ ~ Beta(α₀, β₀)
posterior: θ | (S successes in n trials) ~ Beta(α₀ + S, β₀ + n − S)
mean:      α / (α + β)
95% CI:    scipy.stats.beta.interval(0.95, α, β)
```

### §3.2 Informed priors from Smitelli 2020

Use Smitelli's reported thresholds ([scottsmitelli.com on YouTube audio Content ID](https://www.scottsmitelli.com/articles/youtube-audio-content-id/)) to set per-pattern priors:

| Pattern | Prior |
|---|---|
| Mode A (selector, untransformed) | Beta(1, 19) — strong prior of detection |
| Mode B (turntablist, ≥6% pitch+time, parallel granular) | Beta(8, 4) — moderate prior of defeat |
| Mode D (granular wash, grain ≤30ms, jitter ≥60%) | Beta(15, 2) — strong prior of defeat |
| Mode B w/ Soundtoys Crystallizer engaged | Beta(12, 3) |
| Reverb-only ≥80% wet | Beta(3, 7) — Smitelli says single-stage reverb does not defeat |

Re-anchor priors annually as YouTube's model evolves. Current priors are calibration-survey averages, not measurements; they exist to pull early posteriors toward sensible values when n is small.

### §3.3 Sample size heuristic

For binary outcomes with conjugate Beta updates, the Bayesian approach converges with smaller samples than frequentist NHST ([Mastercard Dynamic Yield: The Bayesian Approach to A/B Testing](https://www.dynamicyield.com/lesson/bayesian-approach-to-ab-testing/)). Operator-time-aware target:

| Confidence level | Trials per (P, T) tuple | Operator time |
|---|---|---|
| Coarse "is this safe-ish?" | 3 | ~15 min wall, ~2 min attention |
| "Add to setlist" | 7 | ~35 min wall, ~5 min attention |
| "Ship to live stream" | 12 | ~60 min wall, ~10 min attention |

A track moves from the rotation pool to the live setlist only after its safety posterior mean exceeds 0.85 with at least 7 trials. The track gets dropped if the posterior mean ever falls below 0.4 (2 surprise-claims in early trials should kick the test back to coarse-tier).

### §3.4 Reusing Hapax's existing Bayesian apparatus

Hapax's affordance pipeline already runs Thompson sampling with optimistic Beta(2,1) priors over capability recruitment — the same algorithm class, the same Beta-Bernoulli conjugate update. The relevant infrastructure:

- `shared/qdrant_schema.py` — define a new `vinyl_safety_posteriors` collection with `track_id`, `mode`, `params_hash`, `alpha`, `beta`, `n_trials`, `last_test_ts` payload.
- `agents/reverie_prediction_monitor.py` shows the Prometheus pattern: timer-driven `sample()` writes a JSON snapshot to `/dev/shm` plus appends to a JSONL history. We mirror that structure for `agents/vinyl_calibration_monitor.py`.
- The `MonitorSample` / `PredictionResult` dataclass pattern, the ntfy-on-alert wiring, and the JSONL append pattern all carry over directly.

The new agent should be `agents/vinyl_calibration.py` (test runner — kicks off private uploads, polls Studio for results, updates posteriors) + `agents/vinyl_calibration_monitor.py` (Prometheus exporter — reads posterior store, exposes per-track-per-mode safety metrics).

### §3.5 What this calibration apparatus is **not**

It is not:

- A proof of fair use. The legal posture (parent doc §2.5–§2.7) is independent of Content ID detection. Defeating Content ID does not establish fair use; failing to defeat it does not preclude fair use.
- A guarantee that successful pattern P remains successful as YouTube updates the model. Posteriors decay — the prior should be regularized toward the original Smitelli baseline at a slow exponential rate (e.g., halve trial counts every 90 days).
- Informative about the *stream-time* fingerprint. Live and VOD may use slightly different models (parent doc §9 item 2). Treat private-upload outcomes as conservative proxy.

---

## §4 Pre-Stream Rehearsal Protocol

### §4.1 End-to-end pre-flight (T-2h before stream)

Hardware + routing checklist (run via `scripts/vinyl-stream-preflight.sh`, ntfy on each step):

1. **PSU + thermal** — turntable + Evil Pet + Torso + L6 powered, 30 min warm-up minimum (analog gear stable).
2. **USB topology** — Zoom L6 enumerated as USB altset 2 (24-channel multitrack mode). Verify via `lsusb -v | grep -i zoom`. PreSonus Studio 24c enumerated separately on its own root hub.
3. **PipeWire graph** — Cortado contact mic at +48V phantom, captured into `Contact Microphone` source. Voice FX chain loaded if `HAPAX_TTS_TARGET=hapax-voice-fx-capture` is exported (per `config/pipewire/README.md`).
4. **VST chain CPU budget** — render 60s test through full chain, confirm RTL < 10ms and no xruns. Spectral analyzer shows transformed branch dominant.
5. **LUFS calibration** — run `ffmpeg -i test_60s.wav -af ebur128=peak=true -f null -` and confirm integrated loudness ≈ -16 LUFS for streaming target ([EBU R128 spec PDF](https://tech.ebu.ch/docs/r/r128.pdf), [FFmpeg ebur128 filter](http://underpop.online.fr/f/ffmpeg/help/ebur128.htm.gz), [Peter Forgacs: Audio Loudness Normalization with ffmpeg](https://medium.com/@peter_forgacs/audio-loudness-normalization-with-ffmpeg-1ce7f8567053)). EBU recommends -23 LUFS for broadcast; YouTube/streaming targets are typically -14 to -16 LUFS ([EBU R 128 Wikipedia summary](https://en.wikipedia.org/wiki/EBU_R_128)).
6. **Channel state** — `gh api channels/.../strikes` (or Studio scrape) confirms 0 active strikes in the rolling 90-day window. **If 1 strike active: proceed with caution. If 2 strikes active: ABORT.**
7. **OBS V4L2 input** — confirms `/dev/video42` reading from compositor + audio routed.
8. **MIDI Dispatch macro layer** — Mode A→C single-press transition fires within 300ms.
9. **Bed-music safe stems** — at least 30 min of YouTube Audio Library / Pretzel cued on L6 ch5/6.
10. **Now-playing overlay test** — splattribution renders with current track metadata.

### §4.2 Per-track pre-flight (T-30min)

For each track in the planned setlist:

1. **Identify** — fingerprint the vinyl rip via Chromaprint, resolve via AcoustID to canonical metadata.
2. **Classify** — assign Mode (A / B / C / D) based on track's pattern history. New tracks default to Mode D until they have ≥3 calibration trials.
3. **Look up posterior** — read `vinyl_safety_posteriors` Qdrant collection. Surface mean + 95% CI to operator.
4. **Decision rule:**
   - posterior mean ≥ 0.85, n ≥ 7, last_test < 90d: **GREEN — proceed in selected mode**
   - 0.6 ≤ mean < 0.85, n ≥ 5: **YELLOW — proceed in deepest available mode (D)**
   - mean < 0.6 or n < 3: **RED — drop from setlist OR run 3 more calibration tests right now (~15 min)**
   - last_test > 90d ago: **STALE — re-test, treat as RED until refreshed**

### §4.3 Warm-spinning (T-30min, optional but recommended)

Actually play each setlist track through the chain in private. No upload, just listen + watch the spectral analyzer. Confirm:
- Transformation branches dominate dry signal.
- No cartridge mistracking on the run-out groove (vinyl-specific concern).
- Onset/level stays inside the limiter ceiling.

### §4.4 Time budget

Realistic operator-attention budget for a 4-hour stream:

| Activity | Time |
|---|---|
| End-to-end pre-flight (§4.1) | 15 min |
| Per-track classification + posterior lookup, 25 tracks | 10 min |
| Calibration top-up (3 tracks at YELLOW/RED) | 30 min |
| Warm-spin pass, 8 tracks | 20 min |
| **Total** | **~75 min** |

For 4h of stream this is ~30% pre-flight overhead. Reduces to ~10 min once posteriors stabilize across regular setlist (most tracks GREEN, no top-up needed).

---

## §5 In-Stream Prometheus Metrics + Collection

### §5.1 Metric definitions (full set)

Following [Prometheus naming conventions](https://prometheus.io/docs/practices/naming/) — snake_case, base unit suffix, `_total` for counters, low-cardinality labels only ([OneUptime: Prometheus label best practices](https://oneuptime.com/blog/post/2026-01-30-prometheus-label-best-practices/view), [Robust Perception: On the naming of things](https://www.robustperception.io/on-the-naming-of-things/)):

```
# Core mode / track lifecycle
hapax_vinyl_broadcast_mode{mode="A|B|C|D"}                                       gauge   (1 active, 0 else)
hapax_vinyl_broadcast_mode_duration_seconds_total{mode}                          counter (cumulative time per mode)
hapax_vinyl_broadcast_mode_transition_total{from_mode, to_mode}                  counter (transition events)
hapax_vinyl_broadcast_track_played_total{track_id, mode, monetization_risk}      counter (track plays)
hapax_vinyl_broadcast_attribution_displayed_total{track_id}                      counter (splattribution surfacing)

# Safety + risk
hapax_vinyl_broadcast_panic_mute_total{trigger}                                  counter (Mode C panic)
hapax_vinyl_broadcast_youtube_warning_total{warning_kind}                        counter (CID warning, manual flag)
hapax_vinyl_broadcast_chat_complaint_total{keyword}                              counter ("no audio", "muted")

# Audio integrity
hapax_vinyl_broadcast_loudness_lufs_integrated                                   gauge   (running EBU R128 integrated)
hapax_vinyl_broadcast_loudness_lufs_short_term                                   gauge   (3s window)
hapax_vinyl_broadcast_loudness_lufs_momentary                                    gauge   (400ms window)
hapax_vinyl_broadcast_loudness_true_peak_dbtp                                    gauge   (true peak)

# Calibration apparatus
hapax_vinyl_calibration_test_total{venue, outcome}                               counter (private upload, mixcloud, pex)
hapax_vinyl_calibration_posterior_mean{track_id, mode}                           gauge   (Beta(α,β) mean, in [0,1])
hapax_vinyl_calibration_posterior_n_trials{track_id, mode}                       gauge

# Forensics
hapax_vinyl_youtube_strike_active                                                gauge   (0/1/2 — 90d window)
hapax_vinyl_youtube_claim_total{policy, claimant_kind}                           counter (post-stream, from Reporting API)
hapax_vinyl_bandcamp_clickthrough_total{artist, track_id}                        counter (referrer-tracked)

# Operator-only signals
hapax_vinyl_broadcast_operator_alert_total{severity}                             counter (pings to Stream Deck / haptic)
```

### §5.2 Cardinality discipline

- `track_id` is unbounded (the operator's full crate). Use a stable hash (sha1 of artist+title+release-year, first 8 chars). Cap unique values at 5000. If exceeded, drop oldest by `last_played_ts`.
- `monetization_risk` is `{low, medium, high, unknown}` — 4 values, safe.
- `mode` is `{A, B, C, D}` — 4 values, safe.
- `trigger` is `{operator_manual, chat_keyword, api_warning, audio_loss_heartbeat, vst_chain_panic}` — 5 values, safe.
- `warning_kind` is `{cid_block, cid_monetize, manual_flag}` — 3 values, safe.
- `keyword` is the matched chat keyword from a curated allowlist (`{no audio, muted, cut, dead, silent, broken, glitch}`) — ~10 values, safe.

Per [Chronosphere Prometheus naming recommendations](https://docs.chronosphere.io/ingest/metrics-traces/collector/mappings/prometheus/prometheus-recommendations) and [Prometheus naming conventions](https://prometheus.io/docs/practices/naming/), avoid putting any free-form text or per-user identifier in labels. The `claimant_kind` label is `{label_major, label_indie, publisher, individual_artist, unknown}` — bucketed, not per-claimant.

### §5.3 Collection mechanism

Mirror the existing pattern from `agents/reverie_prediction_monitor.py`:

```
agents/vinyl_broadcast_monitor.py
  - 30s systemd timer: hapax-vinyl-broadcast-monitor.timer
  - sample() → MonitorSample dataclass
  - writes /dev/shm/hapax-vinyl-broadcast/snapshot.json
  - appends ~/hapax-state/monitors/vinyl-broadcast.jsonl
  - exposes http://localhost:8051/api/vinyl-broadcast/metrics (FastAPI route, Prometheus exposition)
```

Loudness gauge updated by a long-running `agents/vinyl_loudness_meter.py` reading from a PipeWire tap on the encoder pre-input bus, running `ffmpeg -af ebur128` and parsing the per-frame metadata stream ([FFmpeg ebur128 metadata injection mode](http://underpop.online.fr/f/ffmpeg/help/ebur128.htm.gz)). EBU recommends momentary + short-term + integrated reporting at 10Hz ([EBU R128 official PDF](https://tech.ebu.ch/docs/r/r128.pdf)); we publish all three to Prometheus.

### §5.4 Three highest-priority first-shipped metrics

To avoid analysis paralysis: **ship these three metrics first, in this order, before building anything else**:

1. **`hapax_vinyl_broadcast_panic_mute_total{trigger}`** — counter. The single load-bearing safety signal. Its rate tells us at-a-glance whether risk is escalating. With trigger labels we can attribute panics to source (chat-driven vs API-driven vs operator-manual).
2. **`hapax_vinyl_broadcast_track_played_total{track_id, mode, monetization_risk}`** — counter. Without this, we cannot attribute panics to specific tracks/modes for posterior update.
3. **`hapax_vinyl_broadcast_mode{mode}`** — gauge. With (1) and (2), this lets us compute "panics per Mode-second active" — the derived KPI that drives rehearsal calibration.

Everything else is forensic enrichment. Ship these three on the first stream, then add LUFS gauges + chat keyword counter on the second, then layer in calibration + claim metrics over the next two weeks.

---

## §6 YouTube Live Warning Detection + Observability

### §6.1 What YouTube does and does not surface

Per parent doc §3.2 + [YouTube Help: Use Content ID matching on live streams](https://support.google.com/youtube/answer/9896248) + [YouTube Help: Copyright issues with live streams](https://support.google.com/youtube/answer/3367684):

- Live Content ID match → **warning to streamer** (in YouTube Studio, no API push)
- Continued match → stream replaced with static-image-no-sound
- Persistent → stream terminated + 7-day live restriction + strike

The warning is not pushed via webhook or any documented push channel. There is no real-time push API for "your live stream just got matched." This is a material gap.

### §6.2 YouTube Live Streaming API polling

Per [YouTube Live Streaming API: liveBroadcasts](https://developers.google.com/youtube/v3/live/docs/liveBroadcasts) + [liveBroadcasts.list](https://developers.google.com/youtube/v3/live/docs/liveBroadcasts/list) + [Life of a Broadcast](https://developers.google.com/youtube/v3/live/life-of-a-broadcast):

The `status` block surfaces `lifeCycleStatus` (created, ready, testing, live, complete, revoked, liveStarting), `privacyStatus`, and `recordingStatus`. There is no `contentIdWarning` field documented.

The `liveBroadcastListResponse` does **not** include a copyright-status field per the public API surface ([API Reference for Live Streaming](https://developers.google.com/youtube/v3/live/docs)). Practical consequence: we cannot poll the API for "is my current live stream under copyright warning?" The only API signal that surfaces is `lifeCycleStatus = revoked` which is **after** stream termination — too late.

**Polling strategy that does work:** poll `lifeCycleStatus` every 30s. If transition to `complete` or `revoked` is unexpected (operator did not initiate stop), this is the strongest early-warning we get from the API surface alone. Alert immediately.

### §6.3 YouTube Live Chat API

[YouTube Live Streaming API: liveChatMessages](https://developers.google.com/youtube/v3/live/docs/liveChatMessages) + [liveChatMessages.list](https://developers.google.com/youtube/v3/live/docs/liveChatMessages/list) provides chat polling. Use `pollingIntervalMillis` from response (typically 2–5s, server-controlled). The newer `streamList` method ([liveChatMessages docs](https://developers.google.com/youtube/v3/live/docs/liveChatMessages)) pushes new messages without polling — preferred to stay under quota.

**Chat-keyword listener:**

```python
# pseudo, runs in agents/vinyl_chat_listener.py
KEYWORDS = ["no audio", "muted", "audio gone", "no sound", "cut out", "dead air",
            "silent", "broken", "glitch", "audio dropped"]

for message in stream_chat(broadcast_id):
    text = message.snippet.displayMessage.lower()
    for kw in KEYWORDS:
        if kw in text:
            increment_metric("hapax_vinyl_broadcast_chat_complaint_total", labels={"keyword": kw})
            if recent_complaints_in_60s() >= 2:
                trigger_panic_mute("chat_keyword")
```

Two complaints in 60s = panic-mute trigger. Single complaint within 30s of a known panic-mute event is suppressed (it's just the audience noting the silence we already created).

### §6.4 Operator's own Studio scraping path

For real-time visibility into copyright tab warnings, the only mechanism is authenticated browser automation. Practical implementation:

```
agents/youtube_studio_scraper.py
  - Headless Chromium via Playwright with persistent profile
  - Logged into operator's Studio account
  - Polls Studio's "Copyright" tab + active live broadcast page every 60s
  - DOM-scrapes for warning indicators (red-banner detection)
  - Increments hapax_vinyl_broadcast_youtube_warning_total{warning_kind="cid_block"} on detection
```

Fragile (DOM changes break it) but currently the only path. Run as systemd user unit with `Restart=always` and a `RestartSec=300` so DOM regressions don't cascade.

### §6.5 Audio-loss self-heartbeat

Independent of YouTube's signal: monitor our own RTMP encoder output for audio loss. If the encoder reports audio frames dropped or silence-detected (`silencedetect=noise=-50dB:duration=2`) for >2s, that's evidence either we panic-muted ourselves or YouTube's static-image replacement has kicked in. Either way: alert.

```
agents/vinyl_audio_heartbeat.py
  - taps RTMP stream pre-encoder via PipeWire monitor
  - ffmpeg silencedetect filter
  - on silence > 2s when not in Mode C: alert + increment panic_mute_total{trigger="audio_loss_heartbeat"}
```

### §6.6 Detection latency expected

| Signal | Detection latency | Coverage |
|---|---|---|
| API `lifeCycleStatus = revoked` | 30s (poll cadence) | Catches termination only |
| Chat keyword | 5–60s (polling + ≥2 complaints rule) | Catches user-perceived audio failure |
| Studio scraper | 60s | Catches Studio-surfaced warnings |
| Audio heartbeat | 2s | Catches encoder-side silence |
| Operator manual (Stream Deck button) | 0s | Operator's eyes on Studio |

Defense-in-depth: parallel detection paths because no single one is reliable. Operator manual override is the canonical path; the rest are fallbacks for moments when operator attention is on the platter rather than Studio.

---

## §7 Mid-Stream Fallback Playbook (Precise Sequence + Timing)

### §7.1 Trigger fan-in

A "panic-mute trigger" event arises from any of:

1. Operator presses Stream Deck "PANIC" button (canonical path, 0ms latency)
2. `vinyl_chat_listener.py` sees ≥2 audio-failure keywords in 60s
3. `youtube_studio_scraper.py` sees a copyright warning banner
4. `vinyl_audio_heartbeat.py` sees >2s silence not attributable to Mode C
5. `liveBroadcasts.list` sees unexpected `lifeCycleStatus` transition

All five paths converge on a single FastAPI endpoint: `POST /api/vinyl-broadcast/panic` (idempotent, debounced 5s).

### §7.2 Sequence (T+0 = trigger received)

| T | Action |
|---|---|
| **T+0ms** | `POST /api/vinyl-broadcast/panic` fires. MIDI Dispatch macro sent: Mode B/D → Mode C transition. |
| **T+50ms** | Audio source switches to bed-music (L6 ch5/6 unmute, ch1 cut). VST chain stays running but bypassed. |
| **T+100ms** | Splattribution overlay swaps to `"ambient bed (cc-licensed)"` or hides entirely. Replaces now-playing track display. |
| **T+200ms** | Stream Deck "PANIC" button flashes red. Audible-to-operator-only ping (kokoro TTS via `HAPAX_TTS_TARGET=hapax-voice-fx-capture` → Studio 24c monitor out, NOT to broadcast bus). |
| **T+500ms** | Hapax Logos UI renders alert banner with trigger source + last-known track + suggested next action. |
| **T+1s** | `hapax_vinyl_broadcast_panic_mute_total{trigger}` incremented. Append to `~/hapax-state/vinyl-broadcast/panics.jsonl`. |
| **T+2s** | Operator gets clear notification (visual + auditory). Decision time. |
| **T+5s** | Operator either: (a) physically lifts needle, swaps record, signals resume → MIDI Dispatch re-routes to Mode B/D; (b) extends bed-music period; (c) cuts to "back soon" card. |
| **T+30s** | If operator has not signaled resume AND warning trigger persists: cut to "back soon" video card; stop RTMP cleanly; restart broadcast under new ID. |
| **T+60s** | Post-incident note appended to operator's daily Obsidian note (`## Stream Incidents` section) via `vault_context_writer.py`. |

### §7.3 Why this sequence

- **MIDI Dispatch first, before any UI render** — minimizes audio-out delay. The operator's audience hears bed-music before seeing the banner.
- **Splattribution swap before operator notification** — protects the artist's name from association with whatever just got panicked. If the panic was a false positive, no harm; if the panic was a real CID match, we don't want the offending track's artist credited on a panicked stream.
- **Operator notification is auditory + visual** — operator may be looking at the platter (manipulating vinyl) and not Logos. Audible ping carries through. Stream Deck flash carries even with eyes elsewhere.
- **30s grace before stream-restart** — allows operator one full breath to triage, decide if it's recoverable, and avoids restart-thrash on a flickery DOM-scraper false positive.

### §7.4 What the operator should NOT see

- The audience should never see "PANIC MUTE ACTIVE" or any equivalent. Splattribution swap to bed-music is enough; the audience reads it as a track-change moment.
- The chat should never see auto-bot messages from us reacting to its complaints. (Avoids feedback-loop: chat complains about audio, our bot responds, looks like distress signaling.)
- Stream metadata should not change mid-stream (don't update title to "having technical issues"). Discrete recovery looks more professional than apologetic recovery.

### §7.5 What we record for forensics

Append to `~/hapax-state/vinyl-broadcast/panics.jsonl`:

```json
{
  "ts": "2026-04-20T15:23:11.482Z",
  "broadcast_id": "abc123",
  "trigger": "chat_keyword",
  "trigger_detail": {"keyword": "no audio", "complainant_count_60s": 3},
  "track_at_panic": "ts_legomena_2025_q3_brainfeeder_mash_b3",
  "mode_at_panic": "B",
  "mode_after": "C",
  "params_at_panic": {"grain_size_ms": 50, "density": 0.3, "pitch_jitter_cents": 15},
  "operator_resumed_at": "2026-04-20T15:23:42.110Z",
  "operator_resumed_to": "B",
  "audience_chat_messages_60s_post": 12
}
```

This is the input to §8 forensics + §9 calibration update.

---

## §8 Post-Stream Forensics + Iteration

### §8.1 Data sources

After the stream ends, we have:

1. **Hapax telemetry** — `panics.jsonl`, Prometheus scrape archive (Loki), tracks-played log.
2. **YouTube Studio export** — manual CSV download from Analytics + Copyright tab. Per [YouTube Help: Download reports in Studio Content Manager](https://support.google.com/youtube/answer/9718397), Studio export is limited to 500 rows; bulk via [YouTube Reporting API](https://developers.google.com/youtube/reporting/v1/reports).
3. **YouTube Reporting API** ([Reporting API overview](https://developers.google.com/youtube/reporting), [Content Owner Reports](https://developers.google.com/youtube/reporting/v1/reports/content_owner_reports), [jobs.reports.list](https://developers.google.com/youtube/reporting/v1/reference/rest/v1/jobs.reports/list)) — bulk CSV reports, scheduled jobs. Reports persist 30–60 days. Per [The YouTube Reporting API guide](https://krbnite.github.io/The-YouTube-Reporting-API/) and [Oreate AI deep dive](https://www.oreateai.com/blog/unlocking-your-youtube-data-a-deep-dive-into-the-reporting-api/a61620835ddeb26a0185849fcbd2ddb9): create a reporting job for `channel_basic_a2` (channel-level) — **note** the operator's channel almost certainly is not a content-owner-level account, so `content_owner_basic_a3` is unavailable. Channel-level reports do not include detailed per-claim copyright data; copyright claim detail must be CSV-scraped from Studio.
4. **YouTube Live Chat archive** — `liveChatMessages` archived only for the duration of the broadcast; pull during the stream (already in `vinyl_chat_listener.py` log).
5. **VOD claims (if archived)** — Content ID runs against any archived VOD at standard claim level (parent doc §3.2). Read claim status from Studio.

### §8.2 Cross-reference workflow

Per-stream post-mortem (run via `scripts/vinyl-stream-postmortem.sh <broadcast_id>`):

1. Fetch `panics.jsonl` entries for this broadcast.
2. Fetch tracks-played log (from `hapax_vinyl_broadcast_track_played_total` time series).
3. Fetch Studio Copyright tab CSV export (if archived) or chat archive (if not).
4. Cross-tabulate: `(track_id, mode, params) → {panics, claims, chat_complaints}`.
5. Update Bayesian posteriors in `vinyl_safety_posteriors`:
   - For each `(track_id, mode, params_hash)` played without panic and without claim: success += 1, n += 1.
   - For each played with panic OR claim: failure += 1, n += 1.
6. Append outcome JSONL row for historical analysis.
7. Render `~/hapax-state/vinyl-broadcast/postmortem-{broadcast_id}.md` with summary + posterior delta table.

### §8.3 Claim severity classification

Not every claim is equal. Per parent doc §3.1 + [YouTube Help: Upload and match policies](https://support.google.com/youtube/answer/107129), match policy options are Block / Monetize / Track. After fact, classify each claim:

| Policy | Posterior penalty |
|---|---|
| Block-worldwide | -10 trials worth of failure (strong evidence pattern is unsafe) |
| Block in some territories | -3 trials (territorial; operator can choose to drop track or accept) |
| Monetize (revenue redirected, no block) | -1 trial (annoying but not catastrophic; track is broadcastable but unprofitable) |
| Track only | 0 (no penalty; treated as success since stream wasn't impacted) |

Apply asymmetrically: monetization claims do not erode the "is this safe to play" posterior much, since safe-to-play is binary on stream survival. The Bayesian update is on the safety question, not the monetization question.

### §8.4 Strike posture

If a strike occurs:

1. Read takedown notice carefully (per parent doc §8.4).
2. Immediately decrement `hapax_vinyl_youtube_strike_active` to reflect new strike count.
3. Cease all streaming for 7 days (mandatory restriction).
4. Identify offending track + Mode + params from cross-reference.
5. Move the (track_id, mode) to permanent no-play list — do NOT just lower its posterior. A strike means the rights-holder will likely strike again on next play.
6. Counter-notice only if good-faith fair-use belief is genuine and strong (parent doc §8.4).
7. Re-anchor priors: if strike happened in Mode B/D, treat the prior on that mode as freshly conservative for next 30 days.

---

## §9 Continuous Improvement Loop

### §9.1 Cadence

| Frequency | Activity | Owner |
|---|---|---|
| Per stream | Post-mortem + Bayesian posterior update (§8) | `scripts/vinyl-stream-postmortem.sh` |
| Daily | Aggregate panic-mute rates, chat-complaint rates; ntfy if >baseline | `agents/vinyl_broadcast_monitor.py` daily summary timer |
| Weekly | Review past week's claims; update transformation params for tracks now in YELLOW range; re-test STALE tracks | Operator + `vinyl_calibration.py` |
| Monthly | Full setlist audit: tracks moved low→medium risk get warmer-mode reclassification; persistent-issue tracks dropped from rotation | Operator |
| Quarterly | Re-run Smitelli-style baseline (12 tracks, full sweep across pitch/time/grain parameter grid); update prior calibration | `agents/vinyl_calibration.py` quarterly job |
| Annually | Re-anchor priors against latest YouTube model behavior; survey peer-DJ community for fingerprint-update intel | Operator + research notes |

### §9.2 What gets persisted

- `vinyl_safety_posteriors` Qdrant collection — survives forever, indexed by `(track_id, mode, params_hash)`.
- `~/hapax-state/vinyl-broadcast/panics.jsonl` — append-only.
- `~/hapax-state/vinyl-broadcast/postmortem-*.md` — one per stream.
- `~/hapax-state/vinyl-broadcast/calibration-history.jsonl` — every private-upload test outcome.
- `~/hapax-state/vinyl-broadcast/no-play-list.yaml` — tracks + artists + reasons + date-added (per parent doc §6.4).

### §9.3 Decay schedule for posteriors

Posteriors should decay toward the Smitelli prior over time (since YouTube's model evolves out from under us). Apply on monthly cron:

```python
# half-life decay: every 90d, halve trial counts toward prior
days_since_last_test = (now - last_test_ts).days
if days_since_last_test > 90:
    decay_factor = 0.5 ** ((days_since_last_test - 90) / 90)
    posterior.alpha = prior.alpha + (posterior.alpha - prior.alpha) * decay_factor
    posterior.beta = prior.beta + (posterior.beta - prior.beta) * decay_factor
```

After 270 days untested, posterior is 12.5% of original "evidence weight" above prior. This forces re-test of dormant setlist tracks before they're trusted again.

### §9.4 Surfacing improvements to operator

Weekly briefing (via existing `briefing` skill) gets a new section "Vinyl broadcast state":

```
- 14 tracks tested this week (3 GREEN→YELLOW, 1 YELLOW→GREEN)
- 2 panic-mutes total (rate: 0.3 per stream-hour, baseline: 0.4)
- 0 strikes, 1 monetize claim (Stones Throw 2018 release, Mode B)
- 7 STALE tracks in rotation — schedule re-test before next stream
- Bandcamp click-through rate: 4.2% (tracks with splattribution active)
```

---

## §10 Grafana Dashboard Layout (Concrete)

Following [Grafana dashboard best practices](https://grafana.com/docs/grafana/latest/visualizations/dashboards/build-dashboards/best-practices/) + [Stat panel docs](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/visualizations/stat/) + [Time series panel docs](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/visualizations/time-series/) + [Status history docs](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/visualizations/status-history/).

### §10.1 Single-pane "Vinyl Broadcast Health" dashboard

Layout (4-row grid, 24 columns):

**Row 1 (top, 4 rows tall, row height 6) — current operational state**

- Left (6 cols): **Stat panel** — current Mode, color-coded (A=red, B=yellow, C=blue, D=green; semantic: A is risky, D is safest). Background gradient. Sparkline of last 10 min of mode transitions.
- Center (6 cols): **Stat panel** — Time-in-current-Mode counter (mm:ss). Plain text, big.
- Center-right (6 cols): **Stat panel** — Live integrated LUFS. Color thresholds: <-20 red (too quiet), -16±1 green (target), >-13 red (too loud). Per [EBU R128 spec](https://tech.ebu.ch/docs/r/r128.pdf).
- Right (6 cols): **Stat panel** — Strikes active in 90d window. Color: 0 green, 1 yellow, 2 red. Background gradient.

**Row 2 (4 rows tall, height 8) — recent activity**

- Left (12 cols): **Time series panel** — `rate(hapax_vinyl_broadcast_track_played_total[5m])` segmented by `mode`, stacked area. Shows mode usage distribution over the stream.
- Right (12 cols): **Status history panel** — last-N tracks played, with color = Mode + width = duration. Hover shows track_id + monetization_risk.

**Row 3 (4 rows tall, height 8) — risk telemetry (always visible)**

- Left (8 cols): **Time series panel** — `rate(hapax_vinyl_broadcast_panic_mute_total[15m])` stacked by `trigger`. Y-axis: panics per 15-min window. Threshold line at "1 panic per 15 min" (warning), "3" (critical).
- Center (8 cols): **Stat panel** group — small multiples — YouTube warnings: last-1h, last-24h, last-7d, all-time. Big numbers, sparklines underneath.
- Right (8 cols): **Time series panel** — `rate(hapax_vinyl_broadcast_chat_complaint_total[5m])` by keyword. Useful for "viewers report dropouts in real time" overlay.

**Row 4 (4 rows tall, height 8) — calibration state**

- Left (12 cols): **Bar gauge** — top 20 tracks by `hapax_vinyl_calibration_posterior_mean`, sorted ascending (showing the riskiest first). Color: red <0.5, yellow 0.5–0.85, green ≥0.85.
- Right (12 cols): **Time series panel** — `hapax_vinyl_calibration_test_total` by venue (private_upload, mixcloud, pex). Shows calibration cadence — are we testing enough?

**Row 5 (4 rows tall, height 6) — post-stream summary (last 24h)**

- Left (8 cols): **Stat panel** — total hours streamed last 24h, last 7d.
- Center (8 cols): **Stat panel** — total time per Mode last 7d (table-style: A: 0:32, B: 4:12, C: 0:08, D: 1:47).
- Right (8 cols): **Stat panel** — Bandcamp click-throughs last 24h, with sparkline.

### §10.2 Dashboard URL + provisioning

Dashboard JSON committed to `infrastructure/grafana/dashboards/vinyl-broadcast-health.json`. Provisioning via existing Grafana Compose mount; URL `localhost:3001/d/vinyl-broadcast-health/`.

### §10.3 Alerting rules (Grafana-native)

In addition to ntfy from `vinyl_broadcast_monitor.py`:

- `panic_mute_total` rate > 3/15min → ntfy critical (this stream is in trouble)
- `youtube_warning_total` increment > 0 → ntfy critical (immediate operator action)
- `loudness_lufs_integrated` outside [-18, -14] for >60s → ntfy warning (encoder-side issue)
- `strike_active` increases → ntfy critical + halt all streaming via `hapax-vinyl-broadcast-monitor` writing a sentinel file checked by stream-launch script

---

## §11 Open Questions

1. **Does the YouTube private-upload Content ID model match the live-stream model byte-for-byte?** Parent doc §9 item 2 already flagged. Empirical test: take 10 known-detected tracks, render at varied transformation levels, upload as private; correlate Checks outcomes with what those same patterns trigger on actual live stream. Cost: 10 trials × ~5 min wall = ~1 hour. Risk: zero (private uploads don't strike; live tests would be done at a calibrated cushion above the comfort threshold).
2. **What is the Studio scraper's DOM stability over 6 months?** Headless Playwright against authenticated Studio is the only path to real-time CID warning visibility, but Google ships UI changes regularly. Plan: track scraper failure rate as its own Prometheus metric (`hapax_vinyl_youtube_scraper_failure_total`); when failure rate > 5%/day, treat scraper output as untrusted until updated.
3. **Does `streamList` (vs `list`) on liveChatMessages have lower latency for our keyword-detection use case?** [YouTube Live Streaming API revision history](https://developers.google.com/youtube/v3/live/revision_history) does not specify quota or latency for streamList. Empirical: time-stamp every received message and measure delay to operator's chat-side timestamp.
4. **Pex Attribution Engine's overlap with YouTube CID's reference catalog — what fraction of Major-label catalog is dual-indexed?** No public documentation. Test plan: run 30 known-on-YouTube tracks through Pex, count how many resolve. If >75% resolve, Pex is a reliable second opinion. If <30%, it's a different signal entirely.
5. **Do persistent-cookie multi-account approaches survive Studio's anti-automation?** Operator may want to test on a burner account before risking primary. Studio terms forbid this; not recommended. Better: use the primary channel's private-upload only, since the failure mode is non-punitive.
6. **What is the behavior of YouTube's `silencedetect`-equivalent during Mode C bed-music?** If our bed-music itself happens to fingerprint-match (e.g., some YouTube Audio Library tracks have surprising claims), we could be panic-muting into a different claim. Mitigation: quarterly Pex sweep of bed-music library; replace any flagged stems.
7. **Can we instrument splattribution-driven Bandcamp click-through?** Bandcamp's `?ref=` URL parameter ([Bandcamp embed docs](https://get.bandcamp.help/hc/en-us/articles/23020711574423-How-do-I-create-a-Bandcamp-embedded-player)) supports referrer tags. Bandcamp's stats system surfaces referrer-attributed sales ([Bandcamp Pro stats](https://get.bandcamp.help/hc/en-us/sections/23000094167703-Pro-Stats)). For chat-link clicks specifically: route Bandcamp links through a self-hosted shortener (`go.legomena.live/bc/<artist>`) and count hits there. Per-track clickthrough = self-hosted log.
8. **Do `hapax_vinyl_calibration_posterior_n_trials` track_id labels exceed Prometheus cardinality budget over time?** With ~5000 tracks × 4 modes × 5 params_hash variants = 100k time series. This is above safe for Prometheus alone ([OneUptime: cardinality best practices](https://oneuptime.com/blog/post/2026-01-30-prometheus-label-best-practices/view)). Mitigation: keep posteriors in Qdrant only; expose only top-20-riskiest as Prometheus gauges. Dashboard reads top-20 from gauges + drill-down via Qdrant query.
9. **Does the auto-archive-as-VOD setting scan archives at higher sensitivity than live?** Parent doc §8.3 says yes (default to NOT archiving vinyl streams). Empirical confirmation would require comparing live-stream survival vs same-content private upload — currently treated as common knowledge but unverified.
10. **What does Smitelli 2025+ look like?** No current peer-reviewed benchmark of YouTube CID's behavior in 2026. Operator's quarterly calibration sweeps generate the only data we have. Consider publishing aggregate findings (anonymized) to the DJ-research community as a baseline contribution — peer effort would benefit all.

---

## §12 Sources

### YouTube — official policy + API

- [YouTube Help: Use Copyright Match Tool](https://support.google.com/youtube/answer/7648743?hl=en)
- [YouTube Help: Enterprise Copyright Match Tool](https://support.google.com/youtube/answer/6005923?hl=en)
- [YouTube Help: Use Enterprise Copyright Match Tool](https://support.google.com/youtube/answer/15912865?hl=en)
- [YouTube Help: Qualify for Content ID](https://support.google.com/youtube/answer/1311402?hl=en)
- [YouTube Help: How Content ID works](https://support.google.com/youtube/answer/2797370)
- [YouTube Help: Upload and match policies](https://support.google.com/youtube/answer/107129)
- [YouTube Help: Use Content ID matching on live streams](https://support.google.com/youtube/answer/9896248)
- [YouTube Help: Copyright issues with live streams](https://support.google.com/youtube/answer/3367684)
- [YouTube Help: Understand copyright strikes](https://support.google.com/youtube/answer/2814000)
- [YouTube Help: Community Guidelines strike basics](https://support.google.com/youtube/answer/2802032?hl=en)
- [YouTube Help: Download reports in Studio Content Manager](https://support.google.com/youtube/answer/9718397?hl=en)
- [YouTube Help: Data and performance measurement tools](https://support.google.com/youtube/answer/14645915?hl=en)
- [YouTube Blog: Making our strikes system clear and consistent](https://blog.youtube/news-and-events/making-our-strikes-system-clear-and/)
- [YouTube Copyright Tools — How YouTube Works](https://www.youtube.com/howyoutubeworks/copyright/)
- [YouTube Live Streaming API: Overview](https://developers.google.com/youtube/v3/live/getting-started)
- [YouTube Live Streaming API: API Reference](https://developers.google.com/youtube/v3/live/docs)
- [YouTube Live Streaming API: liveBroadcasts](https://developers.google.com/youtube/v3/live/docs/liveBroadcasts)
- [YouTube Live Streaming API: liveBroadcasts.list](https://developers.google.com/youtube/v3/live/docs/liveBroadcasts/list)
- [YouTube Live Streaming API: liveBroadcasts.update](https://developers.google.com/youtube/v3/live/docs/liveBroadcasts/update)
- [YouTube Live Streaming API: liveBroadcasts.transition](https://developers.google.com/youtube/v3/live/docs/liveBroadcasts/transition)
- [YouTube Live Streaming API: liveChatMessages](https://developers.google.com/youtube/v3/live/docs/liveChatMessages)
- [YouTube Live Streaming API: liveChatMessages.list](https://developers.google.com/youtube/v3/live/docs/liveChatMessages/list)
- [YouTube Live Streaming API: Life of a Broadcast](https://developers.google.com/youtube/v3/live/life-of-a-broadcast)
- [YouTube Live Streaming API: Errors](https://developers.google.com/youtube/v3/live/docs/errors)
- [YouTube Live Streaming API: Revision History](https://developers.google.com/youtube/v3/live/revision_history)
- [YouTube Reporting API: Overview](https://developers.google.com/youtube/reporting)
- [YouTube Reporting API: Reports](https://developers.google.com/youtube/reporting/v1/reports)
- [YouTube Reporting API: REST reference](https://developers.google.com/youtube/reporting/v1/reference/rest)
- [YouTube Reporting API: Content Owner Reports](https://developers.google.com/youtube/reporting/v1/reports/content_owner_reports)
- [YouTube Reporting API: jobs.reports.list](https://developers.google.com/youtube/reporting/v1/reference/rest/v1/jobs.reports/list)
- [YouTube Analytics and Reporting APIs: Introduction](https://developers.google.com/youtube/analytics)
- [YouTube ChatBot sample (App Engine)](https://github.com/youtube/youtubechatbot)
- [YouTube API samples: ListLiveChatMessages.java](https://github.com/youtube/api-samples/blob/master/java/src/main/java/com/google/api/services/samples/youtube/cmdline/live/ListLiveChatMessages.java)

### Mixcloud + third-party CID administrators

- [Mixcloud Help: Featured Artist Rules](https://help.mixcloud.com/hc/en-us/articles/360004031080-What-are-the-Featured-Artist-Rules-and-why-is-my-upload-unavailable-for-copyright-reasons)
- [Mixcloud Blog: How to Live Stream Without Copyright Issues](https://www.mixcloud.com/blog/2025/01/01/how-to-live-stream-music-without-copyright-takedown-issues/)
- [Mixcloud Blog: How to upload Tracks](https://www.mixcloud.com/blog/2022/10/17/how-to-upload-tracks-on-mixcloud/)
- [Mixcloud Blog: Tribute Mix without Breaking Copyright Rules](https://www.mixcloud.com/blog/2025/02/04/how-to-make-a-tribute-mix-without-breaking-copyright-rules/)
- [Mixcloud Help: Policies and Safety](https://help.mixcloud.com/hc/en-us/categories/9923274844316-Policies-and-safety)
- [Identifyy](https://www.identifyy.com/)
- [HAAWK](https://www.haawk.com/)
- [Sound on Sound forum: AdRev / Identifyy / Hawkk Content ID](https://www.soundonsound.com/forum/viewtopic.php?t=89282)
- [Passive Promotion: Audiam, AdRev, and YouTube Content ID](https://passivepromotion.com/audiam-adrev-and-youtube-content-id/)
- [Foximusic: What Is AdRev?](https://www.foximusic.com/what-is-adrev-youtube-content-id-and-adrev-explained/)
- [RouteNote vs AdRev for YouTube Content ID](https://routenote.com/s/routenote-vs-adrev-for-youtube-content-id)

### Fingerprinting science + tools

- [Pex — Identify recordings, compositions, AI-generated music](https://pex.com/)
- [Pex Technology page](https://pex.com/technology/)
- [Pex Discovery FAQ PDF](https://3053552.fs1.hubspotusercontent-na1.net/hubfs/3053552/Pex%20Discovery%20Real%20time%20FAQ%209523%20.pdf)
- [Decoded Magazine: Pex Free Attribution Engine launch](https://www.decodedmagazine.com/pex-introduces-its-new-free-attribution-engine-to-connect-creatorscopyright-and-content-seamlessly/)
- [Pex audio-fingerprinting-benchmark-toolkit GitHub](https://github.com/Pexeso/audio-fingerprinting-benchmark-toolkit)
- [Designing for Analytics: How Pex Fingerprinted 20 Billion Files](https://designingforanalytics.com/resources/episodes/039-how-pex-fingerprinted-20-billion-audio-and-video-files-and-turned-it-into-a-product-to-help-musicians-artists-and-creators-monetize-their-work/)
- [Pex 2019 EU stakeholder dialogue PDF](https://www.communia-association.org/wp-content/uploads/2019/12/stakholderdialoog3_PEX.pdf)
- [ACRCloud — Audio Recognition Services](https://www.acrcloud.com/)
- [ACRCloud Music Recognition](https://www.acrcloud.com/music-recognition/)
- [ACRCloud Identification API](https://docs.acrcloud.com/reference/identification-api)
- [ACRCloud Recognize Music tutorial](https://docs.acrcloud.com/tutorials/recognize-music)
- [ACRCloud Wikipedia](https://en.wikipedia.org/wiki/ACRCloud)
- [Chromaprint | AcoustID](https://acoustid.org/chromaprint)
- [Chromaprint GitHub](https://github.com/acoustid/chromaprint)
- [AcoustID Wikipedia](https://en.wikipedia.org/wiki/AcoustID)
- [Lukáš Lalinský: How does Chromaprint work?](https://oxygene.sk/2011/01/how-does-chromaprint-work/)
- [Essentia: Music fingerprinting with Chromaprint](https://essentia.upf.edu/tutorial_fingerprinting_chromaprint.html)
- [acoustid-index GitHub](https://github.com/acoustid/acoustid-index)
- [pyacoustid PyPI](https://pypi.org/project/pyacoustid/)
- [beets chroma plugin documentation](https://beets.readthedocs.io/en/stable/plugins/chroma.html)
- [Dejavu — Audio fingerprinting in Python](https://github.com/worldveil/dejavu)
- [Will Drevo: Fingerprinting and audio recognition with Python](https://willdrevo.com/fingerprinting-and-audio-recognition-with-python/)
- [Dejavu: How I Built an Audio Fingerprinting System (Medium)](https://medium.com/@varunpm132109/how-i-built-an-audio-fingerprinting-system-in-python-using-dejavu-88fa5a5fe744)
- [Comparative Analysis of Audio Fingerprinting Algorithms IJCSET](https://www.ijcset.com/docs/IJCSET17-08-05-021.pdf)
- [Scott Smitelli: Fun with YouTube's Audio Content ID System](https://www.scottsmitelli.com/articles/youtube-audio-content-id/)
- [LifeTips: Avoid Copyright Strikes on Private and Unlisted Videos](https://lifetips.alibaba.com/tech-efficiency/how-to-avoid-copyright-strikes-on-private-and-unlisted)
- [OTTVerse: YouTube Checks tool warns creators before publishing](https://ottverse.com/youtube-checks-warn-creators-about-copyright-issues/)
- [Social Media Today: YouTube rolls out Copyright Checks pre-publish](https://www.socialmediatoday.com/news/youtube-rolls-out-copyright-checks-tool-which-analyzes-your-video-prior-to/596922/)
- [Hello Thematic: How YouTube Copyright Actually Works](https://hellothematic.com/how-copyright-works-on-youtube/)

### Bayesian + Thompson sampling references

- [Wikipedia: Thompson sampling](https://en.wikipedia.org/wiki/Thompson_sampling)
- [Stanford BVR: A Tutorial on Thompson Sampling (PDF)](https://web.stanford.edu/~bvr/pubs/TS_Tutorial.pdf)
- [Zlatan Kremonic: Bayesian A/B testing with Thompson sampling](https://zlatankr.github.io/posts/2017/04/07/bayesian-ab-testing)
- [Towards Data Science: Bayesian A/B Testing Explained](https://towardsdatascience.com/bayesian-a-b-testing-explained-344a6df88c1a/)
- [Towards Data Science: Thompson Sampling](https://towardsdatascience.com/thompson-sampling-fc28817eacb8/)
- [Mastercard Dynamic Yield: Bayesian Approach to A/B Testing](https://www.dynamicyield.com/lesson/bayesian-approach-to-ab-testing/)
- [Kenneth Foo: MAB Analysis of Thompson Sampling Algorithm](https://kfoofw.github.io/bandit-theory-thompson-sampling-analysis/)
- [Agrawal & Goyal 2012: Analysis of Thompson Sampling for the Multi-armed Bandit (MLR PDF)](http://proceedings.mlr.press/v23/agrawal12/agrawal12.pdf)

### Prometheus + Grafana + observability

- [Prometheus: Metric and label naming](https://prometheus.io/docs/practices/naming/)
- [Prometheus: Metric types](https://prometheus.io/docs/concepts/metric_types/)
- [Robust Perception: On the naming of things](https://www.robustperception.io/on-the-naming-of-things/)
- [Chronosphere: Prometheus metric naming recommendations](https://docs.chronosphere.io/ingest/metrics-traces/collector/mappings/prometheus/prometheus-recommendations)
- [VictoriaMetrics: Prometheus Metrics Explained](https://victoriametrics.com/blog/prometheus-monitoring-metrics-counters-gauges-histogram-summaries/)
- [OneUptime: Prometheus Label Best Practices](https://oneuptime.com/blog/post/2026-01-30-prometheus-label-best-practices/view)
- [OneUptime: Metric Naming Conventions](https://oneuptime.com/blog/post/2026-01-30-metric-naming-conventions/view)
- [Last9: Prometheus Metrics Types Deep Dive](https://last9.io/blog/prometheus-metrics-types-a-deep-dive/)
- [Dash0: Understanding the Prometheus Metric Types](https://www.dash0.com/knowledge/prometheus-metrics)
- [Grafana: Dashboard best practices](https://grafana.com/docs/grafana/latest/visualizations/dashboards/build-dashboards/best-practices/)
- [Grafana: Stat panel](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/visualizations/stat/)
- [Grafana: Time series panel](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/visualizations/time-series/)
- [Grafana: Status history panel](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/visualizations/status-history/)
- [Grafana Labs blog: Stat panel range retrieval](https://grafana.com/blog/2023/10/18/how-to-easily-retrieve-values-from-a-range-in-grafana-using-a-stat-panel/)
- [Andreas Sommer: Grafana dashboards-as-code](https://andidog.de/blog/2022-04-21-grafana-dashboards-best-practices-dashboards-as-code)

### Loudness + EBU R128

- [EBU R128 specification PDF](https://tech.ebu.ch/docs/r/r128.pdf)
- [EBU Technology & Innovation: Loudness](https://tech.ebu.ch/loudness)
- [EBU R128 Wikipedia](https://en.wikipedia.org/wiki/EBU_R_128)
- [FFmpeg ebur128 filter documentation](http://underpop.online.fr/f/ffmpeg/help/ebur128.htm.gz)
- [FFmpeg ebur128 (8.0) documentation](https://ayosec.github.io/ffmpeg-filters-docs/8.0/Filters/Multimedia/ebur128.html)
- [FFmpeg libavfilter/ebur128.h](https://ffmpeg.org/doxygen/trunk/ebur128_8h.html)
- [Peter Forgacs: Audio Loudness Normalization with FFmpeg](https://medium.com/@peter_forgacs/audio-loudness-normalization-with-ffmpeg-1ce7f8567053)

### Bandcamp embeds + Pro stats

- [Bandcamp Help: Create an embedded player](https://get.bandcamp.help/hc/en-us/articles/23020711574423-How-do-I-create-a-Bandcamp-embedded-player)
- [Bandcamp Help: Connect to Google Analytics](https://get.bandcamp.help/hc/en-us/articles/23020690440983-How-do-I-connect-Bandcamp-to-Google-Analytics)
- [Bandcamp Help: Pro Stats](https://get.bandcamp.help/hc/en-us/sections/23000094167703-Pro-Stats)
- [Bandcamp: Google Analytics integration](https://bandcamp.com/help/google_analytics)
- [Bandcamp Pro overview](https://bandcamp.com/pro)
- [Bandcamp URL parameters gist](https://gist.github.com/seabass/603735f4da1342ad356dae992385e59d)

### Strike system + livestream lifecycle

- [Business Standard: YouTube three-strike rule explained](https://www.business-standard.com/technology/tech-news/youtube-s-three-strike-rule-what-creators-should-know-and-how-to-appeal-125052600554_1.html)
- [Lenos: YouTube Copyright Strike — What Is It & Consequences 2025](https://www.lenostube.com/en/youtube-copyright-strike-what-is-it-its-consequences/)
- [AIR Media-Tech: How to handle multiple YouTube strikes](https://air.io/en/youtube-hacks/how-to-handle-multiple-youtube-strikes-without-losing-your-channel)
- [Cincopa: YouTube 3-strike Community Guideline](https://www.cincopa.com/blog/youtube-3-strikes-community-guideline-what-is-it/)
- [Castr: How to Test Your Stream Before Live Broadcast](https://docs.castr.com/en/articles/5165509-how-to-test-your-stream-before-the-live-broadcast)
- [TuBeast: How to Test YouTube Live Stream Before Broadcasting](https://tubeast.com/how-to-test-your-youtube-live-stream-before-broadcasting)
- [Phyllo: Guide to YouTube Live Streaming API](https://www.getphyllo.com/post/guide-on-how-to-use-youtube-live-streaming-api)
- [Gyre: Avoid copyright restrictions during YouTube live streams](https://gyre.pro/blog/how-to-avoid-copyright-restrictions-on-youtube-live-stream)

### Hapax internal references (workspace, not citable URLs but key ground truth)

- `agents/reverie_prediction_monitor.py` — reference pattern for systemd-timer-driven Prometheus exporter with JSONL history.
- `shared/qdrant_schema.py` — canonical schema location for the new `vinyl_safety_posteriors` collection.
- `shared/notify.py` — `send_notification()` for ntfy + desktop alerts.
- `config/pipewire/README.md` — voice FX chain target documentation; relevant for routing operator-only audio.
- `agents/studio_compositor/budget.py` — pattern for `BudgetTracker` + `publish_costs` (Prometheus exposition mechanism).
- `docs/superpowers/specs/2026-04-02-unified-semantic-recruitment-design.md` — canonical Bayesian / Thompson-sampling apparatus already in place.
- `~/.cache/hapax/working-mode` — sole mode source-of-truth (research/rnd) controlling whether calibration runs aggressively or conservatively.
