# Safe Music Repository — Directory Layout & Conventions

**Date:** 2026-04-23
**Status:** load-bearing convention
**Related:**
- `docs/superpowers/research/2026-04-23-content-source-registry-research.md`
- `docs/superpowers/plans/2026-04-23-content-source-registry-plan.md` Phase 2
- `shared/music_repo.py` (`LocalMusicTrack`, `LocalMusicRepo`)

## Why a recommended layout

`LocalMusicRepo.scan()` walks any root path and ingests every supported audio file. The repo doesn't enforce subdirectory structure — the broadcast-safety gate runs on the per-track `content_risk` and `broadcast_safe` fields, not on path. But a consistent layout makes the operator's mental model match the gate's behavior.

## Recommended layout

```
~/music/hapax-pool/
├── operator-owned/                  # TIER 0 — local operator-owned catalog
│   └── *.{flac,mp3,wav}
├── soundcloud-oudepode/             # TIER 0 — Oudepode SoundCloud bank
├── found-sounds/                    # TIER 1 — operator-curated interstitials
├── streambeats/                     # TIER 1 — inactive unless explicitly re-enabled
├── youtube-audio-library/           # TIER 1 — inactive unless explicitly re-enabled
├── freesound-cc0/                   # TIER 2 — verified CC0, broadcast-OK
├── bandcamp-direct/                 # TIER 3 — direct artist permission per release
└── sample-source-only/              # NEVER broadcast — DAW input only
    ├── cc-by/
    ├── cc0/
    ├── splice-loops/
    └── beatstars-leases/
```

## Per-track YAML sidecar (required for broadcast ingest)

Every track admitted by `LocalMusicRepo.scan()` for broadcast needs a YAML
sidecar with the same stem. Tracks without a sidecar, without a supported
license, or without required provenance fields are quarantined as
`music_provenance: unknown`, `broadcast_safe: false`, `content_risk:
tier_4_risky`; they remain visible for audit/DAW indexing but never surface in
`select_candidates()` or continuous programming.

```
~/music/hapax-pool/found-sounds/radio-static-short-bursts.mp3
~/music/hapax-pool/found-sounds/radio-static-short-bursts.yaml
```

Sidecar schema:

```yaml
attribution:
  artist: "(found sound)"
  title: "radio-static-short-bursts"
license:
  spdx: "operator-curated"
  attribution_required: false
content_risk: tier_1_platform_cleared
broadcast_safe: true
source: found-sound
whitelist_source: "operator-curated"
music_provenance: hapax-pool        # written by ingest from license/source
provenance_token: auto              # sha-derived token written by ingest
quarantine_reason: null             # non-null means never broadcast-selectable
bpm: null
musical_key: null
duration_seconds: 17
mood_tags: [texture, interstitial]
taxonomy_tags: [found-sound, radio]
vocals: false
stems_available: []
```

Phase 2 stores `content_risk`, `broadcast_safe`, `source`,
`whitelist_source`, `music_provenance`, `music_license`,
`provenance_token`, and `quarantine_reason` directly on `LocalMusicTrack`.
Only `cc-by`, `cc-by-sa`, `public-domain`, and `licensed-for-broadcast`
normalize into Hapax-pool provenance; proprietary, non-commercial, unknown, or
missing license strings quarantine the row.

## Gate behaviour by directory

| Directory | Default `content_risk` | Default `broadcast_safe` | `select_candidates()` admits at... |
|---|---|---|---|
| `operator-owned/` | `tier_0_owned` | `true` | always (default `max_content_risk`) |
| `soundcloud-oudepode/` | `tier_0_owned` | `true` | active livestream music source |
| `found-sounds/` | `tier_1_platform_cleared` | `true` | active livestream interstitial source |
| `streambeats/` | `tier_1_platform_cleared` | `true` | inactive unless explicitly re-enabled |
| `youtube-audio-library/` | `tier_1_platform_cleared` | `true` | inactive unless explicitly re-enabled |
| `freesound-cc0/` | `tier_2_provenance_known` | `true` | only if caller passes `max_content_risk="tier_2_provenance_known"` (programme opt-in) |
| `bandcamp-direct/` | `tier_3_uncertain` | `true` | only if caller passes `max_content_risk="tier_3_uncertain"` (operator session unlock) |
| `sample-source-only/` | varies | `false` | NEVER — selector hard-rejects regardless of caller |

## Backward compatibility

Existing tracks in `~/hapax-state/music-repo/tracks.jsonl` still load, but
legacy rows without `music_provenance` and `provenance_token` now fail closed:
they validate as `music_provenance = "unknown"` and are excluded from
broadcast selection until re-ingested or hand-tagged with explicit provenance.

## What this layout is NOT

- **Not a directory the system creates for you.** Operator runs `mkdir -p ~/music/hapax-pool/{operator-owned,soundcloud-oudepode,found-sounds,...}` when ready to populate.
- **Not a directory the gate checks.** The broadcast-safety gate reads fields
  on `LocalMusicTrack`, not paths. A track in `sample-source-only/` with
  `broadcast_safe=true` still needs valid `music_provenance` and
  `provenance_token`; missing provenance quarantines it before selection.
- **Not a replacement for the existing JSONL persistence path.** `LocalMusicRepo` continues to persist scan results to `~/hapax-state/music-repo/tracks.jsonl`. The pool directory is for source files; the JSONL is the index.
