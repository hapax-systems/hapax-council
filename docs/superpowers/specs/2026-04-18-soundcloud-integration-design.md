# SoundCloud Integration (Operator Account) — Design Spec

**Task:** #131 (from `docs/superpowers/research/2026-04-18-homage-follow-on-dossier.md` § #131)
**Date:** 2026-04-18
**Status:** Stub — contingent on SoundCloud API credential issuance
**Sibling:** #130 (local music repo), #127 (SPLATTRIBUTION)

## 1. Goal

Stream Hapax-selected tracks from the operator's SoundCloud account during **vinyl-absent windows** (`vinyl_playing == False`). Same gate as #130; SoundCloud is the networked complement to the local repo. Hapax performs track selection; operator does not pick.

## 2. API friction context (2026)

- SoundCloud Public API remains open but registration is **friction-laden**: account creation routed through a conversational AI agent on `developers.soundcloud.com`, followed by **human review** before credential issuance.
- Historical churn documented in `soundcloud/api` issues `#47`, `#127`, `#219` (rate-limit opacity, token refresh quirks, scope drift).
- Implication: spec ships a complete integration surface but remains dormant until credentials land. Fallback path (§5) keeps the vinyl-absent window filled regardless.

## 3. Playlist source

- Endpoint: `GET /me/tracks?access=playable`
- Filter to tracks where `user_id == operator_user_id` (defense against future API shape changes that surface collaborator/repost content).
- Response cached to `~/.cache/hapax/soundcloud/operator_tracks.json`; TTL 24h; invalidated on explicit refresh.
- Track selection is Hapax-internal (same selector stack as #130): stimmung-weighted, recency-aware, avoids recent replays.

## 4. Rate override

- Inherits `HAPAX_LOCAL_MUSIC_PLAYBACK_RATE` (single env var governs all non-vinyl music playback, including #130).
- Half-speed DMCA shield applies identically to SoundCloud streams and #130 local files — no SoundCloud-specific override.
- Implemented in the shared playback layer; SoundCloud module only supplies the URL and duration.

## 5. Fallback strategy

Decision tree evaluated on every vinyl-absent window entry:

1. SoundCloud credentials present AND API reachable AND rate-limit budget available → stream from SoundCloud.
2. Any of the above fails → delegate to #130 local music repo.
3. #130 empty → silence (do not fall back further; silence is a valid state).

Failure modes are logged to `operator_corrections` Qdrant collection for later review, not surfaced as nudges.

## 6. Gate

- Same gate as #130: `vinyl_playing == False` (authoritative signal from cortado contact-mic / vinyl RPM detector).
- No SoundCloud-specific override. If vinyl returns mid-track, SoundCloud playback fades out over 2s.

## 7. File-level plan

| Path | Purpose |
|------|---------|
| `agents/soundcloud_source/__init__.py` | Module entry |
| `agents/soundcloud_source/client.py` | OAuth2 token cache, refresh, `/me/tracks` fetch |
| `agents/soundcloud_source/selector.py` | Hapax-internal track picker (stimmung + recency) |
| `agents/soundcloud_source/playback.py` | Stream URL resolver; inherits rate override |
| `shared/music_sources.py` | Shared dispatcher: vinyl-absent window → SoundCloud → #130 → silence |
| `tests/test_soundcloud_client.py` | Mocked OAuth + rate-limit scenarios |
| `tests/test_music_sources_dispatch.py` | Dispatch fallback chain |
| `.envrc.example` | `SOUNDCLOUD_CLIENT_ID`, `SOUNDCLOUD_CLIENT_SECRET`, `SOUNDCLOUD_REFRESH_TOKEN` via `pass` |

## 8. Test strategy

- **Mock OAuth:** `unittest.mock` fixtures for token grant, refresh, and 401→refresh→retry path.
- **Rate-limit simulation:** inject 429 responses with and without `Retry-After`; assert backoff → fallback to #130 within one vinyl-absent window.
- **Credential absence:** unset env vars → dispatcher skips SoundCloud silently, routes to #130. Assert no exception bubbles to caller.
- **Rate override propagation:** set `HAPAX_LOCAL_MUSIC_PLAYBACK_RATE=0.5`, assert SoundCloud playback layer receives the same value as #130.
- **Operator-id filter:** response containing foreign `user_id` entries is correctly narrowed.
- No live API in tests. Tests marked `llm` excluded by default (no LLM here, but integration tier is network-gated).

## 9. Open questions

1. **Refresh token lifetime:** SoundCloud docs ambiguous on refresh token TTL in 2026 — budget for monthly manual re-grant or build a nudge path?
2. **Scope minimum:** does `/me/tracks?access=playable` require `non-expiring` scope, or is default sufficient?
3. **Caching policy:** 24h track-list TTL vs event-driven invalidation (webhook support unverified in 2026).
4. **Attribution display:** does SoundCloud's embed/attribution requirement conflict with livestream overlay minimalism? Coordinate with #127 SPLATTRIBUTION.
5. **Multi-device:** operator uploads from phone occasionally — does cache invalidate fast enough, or do new uploads wait up to 24h to appear?

## 10. Related

- **#130** — Local music repo (sibling source, fallback target). Shared dispatcher and rate override.
- **#127 SPLATTRIBUTION** — Attribution rendering for non-vinyl sources; SoundCloud embeds may need explicit attribution per TOS.
- **DMCA half-speed shield** — Cross-cuts #130 and #131; governed by single env var.
