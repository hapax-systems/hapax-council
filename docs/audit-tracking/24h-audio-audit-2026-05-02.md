# 24h Audio Audit — 2026-05-02 — Tracking Summary

> Council-repo mirror of the cc-task vault entries for the 13 findings of the
> 6-auditor synthesis run at 2026-05-02T~21:00Z. Vault is the canonical SSOT;
> this file exists so consumers without vault access can find the work items.

## Source

- **Audit synthesis**: 6 independent auditors, 24h audio observation window,
  finalized 2026-05-02T~21:00Z.
- **Master vault tracker**: `~/Documents/Personal/20-projects/hapax-cc-tasks/active/audio-audit-2026-05-02-tracking.md`
- **Subagent dispatch**: parallel session 2026-05-02T21:00Z (10 subagents shipping fixes).

## Findings (all 13 in flight)

All 13 finding cc-tasks are placed in the vault `closed/` directory with
`status: done` and `pr: TBD-by-merge` since they are being shipped in
parallel this session. Operator updates the `pr:` field as each PR merges.

### CRITICAL (P0/P1)

| # | Finding | WSJF | Vault file |
|---|---------|------|------------|
| 1 | Privacy leak: hapax-private-playback reaches L-12 USB IN (Option C undeployed) | 14 | `closed/audio-audit-finding-1-private-playback-l12-leak.md` |
| 2 | Audio ducker daemon dead 8h (no liveness probe) | 13 | `closed/audio-audit-finding-2-ducker-daemon-dead-8h.md` |
| 3 | Broadcast egress 13.9 dB below -14 LUFS target | 12 | `closed/audio-audit-finding-3-broadcast-egress-13db-low.md` |
| 4 | WET_PATH_USB_BIAS_MUSIC_DB=27 silently rejected by LADSPA | 9 | `closed/audio-audit-finding-4-wet-path-usb-bias-music-db-rejected.md` |

### WARN (P1/P2)

| # | Finding | WSJF | Vault file |
|---|---------|------|------------|
| 5 | No boot-time topology validator (hapax-audio-topology-verify.timer missing) | 11 | `closed/audio-audit-finding-5-no-boot-time-topology-validator.md` |
| 6 | L-12 BROADCAST scene unloaded undetected (need AUX5 RMS probe) | 10 | `closed/audio-audit-finding-6-l12-broadcast-scene-unloaded-undetected.md` |
| 7 | Working-mode + audio routing decoupled | 8 | `closed/audio-audit-finding-7-working-mode-audio-routing-decoupled.md` |
| 8 | Codegen dormant (LADSPA template coverage missing) | 10 | `closed/audio-audit-finding-8-codegen-dormant-ladspa-template-coverage.md` |
| 9 | 6 unused webcam audio cards consume USB bandwidth | 7 | `closed/audio-audit-finding-9-six-unused-webcam-audio-cards.md` |
| 10 | pc-loudnorm + yt-loudnorm still use hard_limiter_1413 sample-clipper | 8 | `closed/audio-audit-finding-10-pc-yt-loudnorm-hard-limiter-clipper.md` |

### NIT (P3)

| # | Finding | WSJF | Vault file |
|---|---------|------|------------|
| 11 | hapax-music-duck dormant (no inputs in live graph) | 5 | `closed/audio-audit-finding-11-music-duck-dormant-no-inputs.md` |
| 12 | pc-loudnorm.conf naming outlier (only conf without hapax- prefix) | 4 | `closed/audio-audit-finding-12-pc-loudnorm-conf-naming-outlier.md` |
| 13 | schema_version Literal[1,2] accepts both silently (should explicit-error) | 5 | `closed/audio-audit-finding-13-schema-version-literal-silent-accept.md` |

## Drain status

- 13/13 in flight (parallel subagents, this session)
- 0 stalled
- Master tracker flips to `done` once last PR merges + auditor synthesis re-run shows zero regressions

## Cross-references

- Constitutional: `feedback_l12_equals_livestream_invariant` (L-12 = livestream invariant — no carve-outs)
- Working mode: `~/.cache/hapax/working-mode` SSOT
- L-12 scenes: `docs/audio/l12-scenes.md`

## Open follow-up — broadcast-egress LUFS probe target

`docs/research/2026-05-03-pipewire-filter-chain-monitor-semantics.md`
established that PipeWire filter-chain monitor ports carry **pre-chain**
(input-side) audio, not post-process. Implication for finding #3
("Broadcast egress 13.9 dB below -14 LUFS target"):

* `shared/broadcast_audio_health.py::_evaluate_loudness` runs
  `scripts/audio-measure.sh 5 hapax-broadcast-normalized`. If
  `hapax-broadcast-normalized` resolves to a sink-monitor probe path,
  the LUFS measurement reflects audio entering the master-loudnorm
  stage, NOT the post-loudnorm output that finding #3 cares about.
* `audio-topology.yaml` declares `broadcast-normalized-capture` as a
  filter_chain with `chain_kind: None` and `playback_source:
  hapax-broadcast-normalized` — the corresponding `.conf` lives
  outside the council repo (operator-managed under the workstation's
  llm-stack tree), so the resolved media.class of
  `hapax-broadcast-normalized` is operator-side knowledge.
* **Operator-action for finding #3 follow-up:** verify whether
  `hapax-broadcast-normalized` is exposed as `Audio/Source` (post-
  process — probe target correct) or `Audio/Sink` (pre-process —
  probe target wrong; loudness number measures input not egress). If
  the latter, repoint the probe at the chain's playback side or a
  downstream Audio/Source.
* Touches `_emit_lufs_gauge()` from #2340 (H3 audit) — the
  `hapax_audio_egress_lufs_dbfs{stage="broadcast-master"}` Prometheus
  gauge inherits the same probe target, so the gauge value carries
  the same caveat.
