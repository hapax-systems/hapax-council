# Evil Pet — Broadcast Source Policy

**Date:** 2026-04-23
**Status:** load-bearing operational policy
**Trigger:** YouTube ContentID warning during vinyl playback through Evil Pet wet processing 2026-04-23.
**Related:**
- `docs/superpowers/research/2026-04-23-content-source-registry-research.md`
- `docs/superpowers/plans/2026-04-23-content-source-registry-plan.md`
- `config/pipewire/hapax-l12-evilpet-capture.conf`

## Rule

The Evil Pet hardware loop is the **only path** by which non-microphone audio reaches the L-12 broadcast capture sum. The Evil Pet input may carry **only sources whose `content_risk` is TIER 0 or TIER 1** (operator-owned, generated, or platform-cleared per the content-source registry).

**Specifically PROHIBITED at the Evil Pet input during a live stream:**
- Vinyl (Korg Handytraxx on L-12 CH9/10, AUX8/9). Modulation through Evil Pet does not defeat Content ID.
- Any commercial / unlicensed audio (Spotify, YouTube ripped audio, Apple Music, Tidal, etc.).
- CC0 / public-domain audio sources on the broadcast path (false-positive trap; only the operator's DAW-internal sample work counts as safe).
- Beatstars / Splice / Loopcloud loops played raw.

**Specifically PERMITTED at the Evil Pet input during a live stream:**
- Operator's own oudepode catalog (TIER 0).
- Epidemic Sound recordings, stems, and EditRecording loop edits (TIER 1, channel-whitelisted).
- Streambeats by Harris Heller (TIER 1).
- YouTube Audio Library content (TIER 1).
- Operator's own contact-mic / sample-pad performance audio (TIER 0).

## Mechanism

The L-12 broadcast capture filter-chain (`hapax-l12-evilpet-capture.conf`) drops AUX8/9 (vinyl), AUX10/11 (PC line-out direct), and AUX12/13 (MASTER L/R) from the capture sum. The only non-microphone source feeding broadcast is AUX5 (Evil Pet return on CH6).

The operator routes content into Evil Pet via L-12 hardware AUX-B sends:
- AUX-B receives whatever channels the operator opens (AUX-B fader on each strip).
- AUX-B output → Evil Pet input.
- Evil Pet output → L-12 CH1/CH6 → AUX5 → broadcast.

**The policy applies at the operator's hardware action level**: the operator opens AUX-B sends only on strips carrying TIER 0 / TIER 1 sources during a live stream. Vinyl AUX-B sends remain closed during broadcast.

## Off-broadcast Evil Pet use

Vinyl can feed Evil Pet for offline sampling, monitor experiments, or pre-stream rehearsal — when the broadcast is not live. Stop the broadcast first; vinyl-to-Evil-Pet routing is then unconstrained.

## Runtime safeguard

The `hapax-audio-safety` systemd user unit (`agents/audio_safety`) reads the L-12 multitrack capture and correlates simultaneous activity on AUX5 (Evil Pet return) and AUX8/9 (vinyl L/R). When sustained simultaneous activity exceeds the dwell threshold (default 2 seconds) during live stream conditions, the agent emits:

- A high-priority ntfy notification to the operator ("vinyl is feeding Evil Pet → broadcast — duck or unroute").
- An impingement to `/dev/shm/hapax-dmn/impingements.jsonl` with source `audio.safety.vinyl_pet` and intent_family `governance.broadcast_safety`, available for downstream affordance pipeline reaction.

This is a real-time human-in-the-loop alert that beats YouTube's ContentID detection by seconds, allowing the operator to drop AUX-B before the strike fires.

## Why this is policy and not enforcement

The operator's L-12 is multi-use and the AUX-B routing is a creative tool the operator must retain control of. Hard-disabling vinyl AUX-B sends would prevent legitimate non-broadcast use (sampling, monitor work). The policy is documented + alert-monitored; the runtime safeguard catches the failure mode without locking the hardware.

## Future tightening

If false-positive ContentID warnings occur despite this policy, candidates for harder enforcement (deferred until needed):

1. **L-12 SD-card scene change** — create a `BROADCAST` scene that explicitly mutes AUX-B sends on CH9/10 (vinyl strips); operator loads the scene at stream onset. Policy becomes a single hardware action.
2. **PipeWire-level intercept** — add a per-strip AUX-B monitor that hard-mutes vinyl-strip AUX-B output to Evil Pet input when the broadcast tap is active. Most invasive; defer until needed.
