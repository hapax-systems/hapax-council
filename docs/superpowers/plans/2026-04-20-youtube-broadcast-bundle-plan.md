# YouTube Broadcast Bundle (#144 + #145) — Implementation Plan

**Status:** ready-to-execute
**Date:** 2026-04-20
**Author:** alpha (refining spec into per-PR execution)
**Owner:** alpha (zone)
**Spec:** `docs/superpowers/specs/2026-04-18-youtube-broadcast-bundle-design.md`
**Origin:** D-31 unplanned-spec triage recommended this as the next plan slot — operator surfaced the underlying #144 + #145 concerns 2026-04-06 + flagged AttributionSource as "powerful reusable strategy."
**WSJF:** 6.5 (HIGH per D-31 vault-task triage; load-bearing for DMCA/attribution posture)
**Branch:** trio-direct (per existing burst pattern; #144 + #145 ship as 2-3 separate commits on main)
**Total effort:** ~6-8h focused work across 3 PR-sized phases

## 0. Why this plan exists

Per D-31 unplanned-specs triage
(`docs/research/2026-04-20-d31-unplanned-specs-triage.md`):

> Recommended next plan slot: youtube-broadcast-bundle (description-update
> infra exists; OAuth + reverse-ducker are the gaps; load-bearing for
> DMCA/attribution posture).

Operator's 2026-04-06 framing: real-time public attribution turns
chat-shared links into public record, mirroring how the
operator→YT ducker shipped (PR #1000). The spec calls this a
"powerful reusable strategy" — the `AttributionSource` Protocol is
the structural fix.

## 1. Pre-flight

- [ ] Verify `scripts/youtube-player.py::LivestreamDescriptionUpdater`
      still exists at lines 357-572 (per spec §2.1)
- [ ] Verify `agents/studio_compositor/youtube_description.py`
      `check_and_debit()` + `assemble_description()` +
      `update_video_description()` shipped per spec §2.1
- [ ] Verify `agents/studio_compositor/youtube_description_syncer.py`
      hash-dedup at `~/.cache/hapax/youtube-desc-last-state.json`
- [ ] Verify `shared/google_auth.py` ALL_SCOPES requests
      `youtube.force-ssl` per spec §2.2
- [ ] Verify the operator-gated OAuth blocker still applies — run
      `scripts/youtube-auth.py --check` (read-only) to confirm token
      mint state. If active token: code activates immediately on
      first sync; if not (expected): code runs in silent-skip mode
      until operator mints.
- [ ] Verify `config/pipewire/voice-over-ytube-duck.conf` exists as
      mirror-shape source for §145 (per spec §3.3)

## 2. Phase 1 — `AttributionSource` Protocol + URL extractor (~2h)

Spec §2.4 + §2.3.

### 2.1 Tasks

**T1.1** New `shared/attribution.py`:
- `AttributionSource` Protocol with one method:
  ```python
  def emit_entries(self, since: datetime | None = None) -> Iterator[AttributionEntry]: ...
  ```
- `AttributionEntry` Pydantic dataclass with: `kind: AttributionKind`,
  `url: str`, `title: str | None`, `source: str`, `emitted_at: datetime`,
  `metadata: dict[str, Any] = {}`.
- `AttributionKind = Literal["citation", "album-ref", "doi", "tweet",
  "youtube", "github", "wikipedia", "other"]`.
- `AttributionRingBuffer` — per-kind FIFO with TTL (default 24h) +
  size cap (default 100 entries per kind) for memory bound.
- `AttributionFileWriter` — append-only JSONL per kind under
  `~/Documents/Personal/30-areas/legomena-live/{kind}.jsonl`. Atomic
  via tmp+rename (D-20 pattern).

**T1.2** New `shared/url_extractor.py`:
- `extract_urls(text: str) -> list[str]` — pure-regex extraction with
  unwrap (`https://t.co/X` redirects, etc.). No HTTP requests at
  extract time; classifier may resolve later.
- `classify_url(url: str) -> AttributionKind` — pure-string heuristic
  on hostname + path. Examples: `doi.org` → `doi`; `bandcamp.com|
  soundcloud.com|spotify.com|youtube.com/watch` → `album-ref`;
  `twitter.com|x.com` → `tweet`; `github.com` → `github`;
  `*.wikipedia.org` → `wikipedia`; `nature.com|arxiv.org|sciencedirect`
  → `citation`; default `other`.

**T1.3** Tests at `tests/shared/test_attribution.py` +
`tests/shared/test_url_extractor.py`:
- AttributionEntry shape + Pydantic validation
- AttributionRingBuffer TTL eviction + size cap
- AttributionFileWriter atomic append + idempotency on dedup hash
- extract_urls regex corpus (50 fixtures: bare URLs, markdown
  links, t.co wraps, HTML entities, ASCII brackets, inline
  punctuation)
- classify_url decision table (one fixture per AttributionKind)

### 2.2 Exit criterion

`uv run pytest tests/shared/test_attribution.py tests/shared/test_url_extractor.py -q` green.

### 2.3 Commit

```
feat(shared): YT bundle Phase 1 — AttributionSource protocol + URL extractor (#144)
```

## 3. Phase 2 — chat-monitor wire + syncer extension (~2h)

Spec §2.3 + §2.4 + §2.6.

### 3.1 Tasks

**T2.1** Modify `scripts/chat-monitor.py`:
- Add a `URLExtractor` stage AFTER message ingestion, BEFORE the
  structural batch.
- For each message, run `extract_urls()` + `classify_url()`. Build
  `AttributionEntry` per URL with `source="chat:{author_id_hash}"`
  (privacy: hash author IDs per `feedback_consent_latency_obligation`).
- Append to `AttributionRingBuffer` + `AttributionFileWriter`.
- Non-invasive: existing structural-batch code path unchanged.

**T2.2** Modify `agents/studio_compositor/youtube_description_syncer.py`:
- `_snapshot_state()` enumerates registered `AttributionSource`s
  (vault-file-backed reader for now; future producers can register
  in-memory).
- Hash-dedup logic preserved.

**T2.3** Modify `agents/studio_compositor/youtube_description.py`:
- `assemble_description()` produces per-kind sections with per-kind
  markers `<!-- attr-{kind} -->...<!-- /attr-{kind} -->` so each
  kind dedupes independently.
- Per-kind char budget: 5000 chars total, divided proportionally;
  spec §2.6 quota math.

**T2.4** Tests:
- `tests/scripts/test_chat_monitor_url_extraction.py` — synthetic
  chat fixture, assert N URLs extracted + classified + persisted
- `tests/studio_compositor/test_youtube_description_per_kind.py` —
  marker-section dedup; per-kind budget
- Mocked YT API integration test in
  `tests/studio_compositor/test_youtube_description_syncer_attribution.py`

### 3.2 Exit criterion

End-to-end fixture: feed 10 chat messages with mix of URLs → assert
description state file contains expected per-kind sections, mock YT
API receives a single `videos.update` call.

### 3.3 Commit

```
feat(youtube): YT bundle Phase 2 — chat URL → description backflow wire (#144)
```

## 4. Phase 3 — Reverse-direction ducking (#145) (~2h)

Spec §3.

### 4.1 Tasks

**T3.1** New `config/pipewire/ytube-over-24c-duck.conf`:
- Mirror-shape of `config/pipewire/voice-over-ytube-duck.conf`.
- Trigger: YT/OBS audio active → step down `hapax-24c-ducked` sink
  by -12 dB (operator-tunable).
- Attack: 50 ms (operator-tunable per spec §3.4 line 178).
- Release: 200 ms.

**T3.2** Modify `config/pipewire/README.md`:
- Add routing diagram per spec §5 line 156:
  ```
  24c hw mix → hapax-24c-ducked → phys-out
  YT/OBS → hapax-ytube-ducked (normalized) → phys-out
  loopback: YT → 24c ducker sidechain
  ```

**T3.3** Pre-ducker loudness normalization (spec §3.4):
- Add `loudness-normalization` module to YT input chain at LUFS=-23
  (broadcast-standard) before the sidechain.
- Decision: pre-PiP compositor (per spec §3.4 line 179 — keeps
  sidechain clean, accepts compositor-headroom hit).

**T3.4** Tests at `tests/pipewire/`:
- `test_ytube_over_24c_duck_config.py` — config-lint regression pin
  (file syntax + module-loaded assertion via `pw-cli ls Module`)
- `test_three_way_ducking_matrix.py` — S1-S4 from spec §3.5;
  measure attenuation dB on each bus via `pw-cli` / `pw-top`;
  assert no oscillation (±1 dB over 5s window once steady-state).

### 4.2 Exit criterion

`uv run pytest tests/pipewire/ -q` green. Manual: route YT audio
→ verify 24c hw mix steps down -12 dB within 50ms; YT off → 24c
recovers within 200ms.

### 4.3 Commit

```
feat(pipewire): YT bundle Phase 3 — YT → 24c reverse ducker + LUFS normalization (#145)
```

## 5. Phase 4 (optional) — `liveChatMessages.insert` sidecar (~1h)

Spec §2.5. Defer until #144 has shipped + had quota review per spec
§7 open question 1.

## 6. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| OAuth token never minted | M | #144 stays silent-skip | Code lands behind silent-skip shield; activates immediately on operator mint. Tests assert "disabled with clear warning" not "succeeds." |
| URL extractor false-positives produce spam attribution | M | Description noise | Classify→other for unknown hosts; ring buffer caps + 5000-char dedup ceiling. |
| Chat author IDs leak to description | L | Consent violation | Hash author_id at `URLExtractor` boundary; never write raw IDs to AttributionEntry.source. |
| 24c ducker pumps on percussive YT content | M | Operator complaint | Spec calls out: expose attack in .conf as tunable. Default 50ms; operator can raise to 100ms. |
| YT loudness normalization clips post-compositor signal | L | Audible artifact | Tests assert ≤-1 dBFS peak; LUFS=-23 leaves 6+ dB headroom. |

## 7. Acceptance criteria

- [ ] `AttributionSource` Protocol + 8 AttributionKinds shipped
- [ ] `URLExtractor` regex passes 50-fixture corpus
- [ ] chat-monitor.py extracts URLs without breaking existing
      structural batch
- [ ] description syncer enumerates AttributionSources, dedups per-
      kind, respects per-stream + daily caps
- [ ] silent-skip path verified: pre-OAuth, no `videos.update` HTTP call
      is attempted
- [ ] `ytube-over-24c-duck.conf` shipped; `pw-top` shows -12 dB
      attenuation on 24c when YT plays
- [ ] LUFS=-23 normalization verified via meter readout
- [ ] Three-way matrix test passes (S1-S4)
- [ ] PIPELINE.md routing diagram updated
- [ ] Spec gets a "shipped in" footer pointing at the merge SHA
      (close the audit-loop gap D-31 flagged)

## 8. Sequencing relative to other in-flight work

- **Independent of D-30** (CC-task SSOT — orthogonal)
- **Independent of HSEA Phase 0** (different infrastructure)
- **Independent of OQ-02 Phase 1 oracles** (those shipped)
- **Spec for cascade-2026-04-18 epic family** — cascade-phase-3
  shipped in PR #1080 family; this bundle is a follow-on, not a
  prerequisite for any current epic
- **D-31 audit-loop closure**: spec footer recommendation applies
  to ALL future spec→ship cycles; capture in a hooks-side audit pass
  separately

## 9. References

- Spec: `docs/superpowers/specs/2026-04-18-youtube-broadcast-bundle-design.md`
- D-31 triage: `docs/research/2026-04-20-d31-unplanned-specs-triage.md`
- Source PRs (#144 + #145 cascade): cited in spec §2.1 + §3.1
- Operator framing: 2026-04-06 conversation log (per spec §1)
- Existing infra: `scripts/youtube-player.py:357-572`,
  `agents/studio_compositor/youtube_description{,_syncer}.py`,
  `shared/google_auth.py`, `config/pipewire/voice-over-ytube-duck.conf`
