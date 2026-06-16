# AVSDLC Release Dossier — Cortado contact-mic AUX1 routing fix

- **Task:** `audio-cortado-mkii-ultralite-line2-topology-reconciliation-20260604`
- **Request / program:** `REQ-20260616-perception-audio-ssot-program` (Phase 1)
- **AuthorityCase:** `CASE-VOICE-FOUNDATION-20260610`
- **Axes:** audio · audio_or_live_egress_sensitive
- **Collected:** 2026-06-16 · host hapax-podium · by cc-cns
- **Release authorized:** false (independent review required; this dossier is the support artifact)

## What changed

The `contact_mic` PipeWire loopback (the perceptual Cortado contact mic, exposure=quarantine) was
silently capturing **mk5 input 1 = the Rode (the operator's broadcast voice)** instead of **input 2 =
the Cortado** — a perceptual sensor eavesdropping the broadcast voice path. Root cause: the loopback's
`audio.position = [ aux1 ]` (lowercase) did not match the mk5's `AUX1` channel position, so pipewire
fell back to the first port (`capture_AUX0` = input 1 = Rode). This has been mis-routed since the L-12
retirement (cf. the 2026-06-04 live-link recheck "fed from capture_AUX0").

**Fix:** uppercase `audio.position = [ AUX1 ]` → the capture binds to `capture_AUX1` = input 2 = Cortado.
`mixer_master` (live-consumed by the ducker/reactivity) preserved verbatim. Duplicate
`hapax-contact-mic.conf` dedup'd. Applied to the deployed conf + pipewire restart (livestream not live).
The SSOT generator (registry `hw_source.position: AUX1`) becomes the sole writer (follow-up commit).

## Evidence (witnesses)

- **audio_witness** — `~/.cache/hapax/relay/audits/2026-06-16-cortado-aux1-fix-witness.md`:
  `contact_mic` loopback bound to `capture_AUX1`; NOT broadcast-reachable;
  `hapax-audio-routing-check` ALL INVARIANTS PASSED before+after.
- **runtime_media_witness** — `~/.cache/hapax/relay/audits/2026-06-16-cortado-aux1-runtime-media-witness.wav`:
  20 s `contact_mic` capture during operator MPC-pad taps; 6 distinct structure-borne tap transients
  (~6.0/7.3/9.0/10.8/12.7/14.3 s, peak −31.5 dB) ⟹ the source is the Cortado (input 2), not the Rode.
- **Drift-impossibility (formal):** `shared/perception_conf_gen.generated_contact_mic_conf_text` emits the
  conf from the registry's typed `hw_source`; cross-check `PerceptualBroadcastReachError` makes
  "perceptual point on a broadcast-reachable target" impossible to generate; `--check-source-confs`
  byte-diff gate. Tests: 23 pass; ruff + pyright clean.

## Privacy

Cortado is exposure=quarantine and proven non-broadcast-reachable (no links to livestream-tap /
broadcast-master / voice-fx / OBS). The prior mis-route meant the operator's voice was reaching a
perception path; that is now closed.

## Risk / rollback

- Risk tier T2. Live change was a deployed-conf edit + pipewire restart with routing-check before/after
  (revert-on-red). Livestream was not live.
- Rollback: restore `10-contact-mic.conf` `node.target`/`audio.position` and re-enable the dedup'd conf,
  restart pipewire. The `.disabled-dup-20260616` and pre-edit content are recoverable.

## Open follow-ups (tracked in REQ-20260616)

- Persist the SSOT version (registry `aux1`→`AUX1`; generator emits both modules; regenerate repo conf).
- `mixer_master` correct mk5 source (no L-12-style master mix).
- mk5 input-2 gain is modest (−31.5 dB peak) — raise for the contact-event classifier.
