---
date: 2026-05-02
author: alpha
register: scientific, neutral
status: design
related:
  - docs/superpowers/specs/2026-04-21-evilpet-s4-dynamic-dual-processor-design.md (the dual-processor spec this amendment narrows)
  - docs/superpowers/specs/2026-04-23-livestream-audio-unified-architecture-design.md (decision #2 — NO DRY HAPAX origin)
  - docs/superpowers/specs/2026-04-28-broadcast-audio-safety-ssot-design.md (private/broadcast invariant SSOT)
  - /tmp/routing-discovery-2026-05-02.md (research substrate that produced this resolution)
  - config/audio-topology.yaml (descriptor where private/broadcast classification lives)
  - config/wireplumber/55-hapax-private-no-restore.conf (private-monitor pin shipped in PR #2221)
  - config/wireplumber/56-hapax-private-pin-yeti.conf (current Yeti pin; to be retargeted to S-4)
  - scripts/hapax-private-broadcast-leak-guard (runtime leak scanner; rule set to be extended)
  - scripts/audio-leak-guard.sh (static check enforcing no analog-OUT-1/2 → L-12 USB IN path)
amends:
  - docs/superpowers/specs/2026-04-21-evilpet-s4-dynamic-dual-processor-design.md (only §3.1 row "Voice (TTS, Rode) — private bypass case" — see §11)
---

# Hapax Private-Monitor Track-Fenced via S-4 — Spec Amendment (Option C Resolution)

## §1. Purpose

Resolve the contradiction between two operator-locked invariants:

1. **NO DRY HAPAX** (constitutional, anti-anthropomorphism): "There should be NO DRY HAPAX because it violates the mandate against anthropomorphism (Hapax should make every effort to destabilize anthropomorphic expectations)."
2. **PRIVATE HAPAX NEVER REACHES BROADCAST** (constitutional, fail-closed safety contract per `2026-04-28-broadcast-audio-safety-ssot-design.md`).

Document operator's chosen resolution (locked in 2026-05-02T~17:00Z): the S-4's per-track output destination is the compartmentalization fence. A track whose output is the S-4 analog OUT 1/2 pair is private; a track whose output reaches the L-12 USB IN capture chain is broadcast. The privacy invariant is enforced at the **track-output level**, not at the device level. The S-4 itself remains a multi-purpose hardware processor available to broadcast roles.

This amendment is doc-only; the implementation work is the follow-up cc-task `private-hapax-s4-track-fenced-implementation`.

## §2. The contradiction (with verbatim quotes)

The unified-architecture spec carries the operator's anti-anthropomorphism mandate as decision #2: *"All sources route through Evil Pet by default; nothing dry by default."* On approval the operator restated it: *"by default EVERYTHING should go through the evil pet and NOTHING should be dry"* (`2026-04-23-livestream-audio-unified-architecture-design.md` §1).

The broadcast-audio-safety SSOT carries the privacy invariant as a fail-closed contract: *"Assistant, private, and notification routes must fail closed away from every broadcast path"* (`2026-04-28-broadcast-audio-safety-ssot-design.md`). Forbidden private-route targets are explicitly enumerated: L-12 outputs, `hapax-livestream`, `hapax-livestream-tap`, `hapax-voice-fx-capture`, `hapax-pc-loudnorm`, multimedia loopback.

Today the Evil Pet hardware processor sits on the L-12 broadcast bus (loop: `Ryzen analog → L-12 CH11/12 → MONITOR A → Evil Pet IN → Evil Pet OUT → CH1 XLR → AUX5 → broadcast`). Any signal routed through it is by construction reachable from the broadcast capture path. The two invariants are therefore mutually exclusive *if Evil Pet is the only hardware character available to Hapax voice* — applying NO-DRY to private TTS would route private speech onto a path that the safety SSOT enumerates as forbidden.

The contradiction is resolvable because the constitutional ground of NO-DRY-HAPAX is **anti-anthropomorphism, which is a function rather than a specific timbre**. Any character that destabilizes the dry-voice default satisfies the mandate. The Torso S-4's per-track routing flexibility lets a private track carry such a character on a path that does not touch the broadcast bus.

## §3. Resolution: per-track output fence on S-4

The S-4 has 4 parallel tracks with independent input source selection (Stereo / Mono In 1 / Mono In 2 / Line / USB pair) and independent output destination selection (Main Mix / standalone OUT). Each track is a 5-slot serial chain (`Material → Granular → Filter → Color → Space`). The 4 tracks operate simultaneously and can route to physically distinct outputs (`/tmp/routing-discovery-2026-05-02.md` §2).

The compartmentalization model:

- **Track routed to S-4 analog OUT 1/2 → private.** This track's output never enters the L-12 USB IN capture chain because S-4 analog OUT 1/2 are TR line outputs that the operator patches into a non-broadcast monitor sink (§5).
- **Track routed to S-4 USB OUT pair → broadcast.** The USB pair returns to the host as `s4-output` (descriptor lines 375–384), and from there is loopback'd via `s4-loopback` into `hapax-livestream-tap` (descriptor lines 386–397). Anything on this path is in the broadcast set.
- **Track routed to L-12 USB IN via analog patch → broadcast.** When operator deliberately patches an S-4 analog out into an L-12 channel (e.g., for music-modulation companion roles), the track participates in broadcast.

The invariant is enforced at **TRACK-OUTPUT level, not device level**. The S-4 itself is dual-citizen: some of its tracks are private, some are broadcast. The compartmentalization fence is the per-track output destination.

`scripts/audio-leak-guard.sh` enforces the static guard at check time: no track whose output is S-4 analog OUT 1/2 may have any downstream electrical or software path back to L-12 USB IN. The runtime scanner `scripts/hapax-private-broadcast-leak-guard` (shipped in PR #2221) enforces the inverse invariant via pw-link scanning at session boot and on PipeWire restart.

## §4. Track allocation (current proposal)

The proposed track allocation reproduces the operator's locked-in table.

| Track role | Output destination | Class |
|---|---|---|
| Music modulation companion | S-4 USB pair OUT → L-12 USB return → L-12 USB IN capture | broadcast |
| Voice modulation companion | S-4 USB pair OUT → L-12 → broadcast | broadcast |
| Memory-companion / sampler companion | analog or USB → broadcast | broadcast |
| **Private-monitor wet (NEW)** | S-4 analog OUT 1/2 → operator monitor amp/HDA, never touches L-12 USB IN | **private** |
| Spare / future | — | TBD |

Operator's design intent on multi-citizenship (verbatim): *"we should NOT reserve s-4 for private comms only, it has routing that can be compartmentalized/fenced in reliable ways and it is too powerful and flexible to exclude livestream from its purview."*

**Carry-forward.** Broadcast roles in the table above (music modulation, voice modulation, memory/sampler companion) are CARRIED FORWARD without regression from the dual-processor spec §3.1 source-→-engine contract (`2026-04-21-evilpet-s4-dynamic-dual-processor-design.md` §3.1, "Voice (TTS, Rode) — primary Evil Pet, secondary S-4 Track 1" and "Music — primary S-4 Track 2, secondary Evil Pet"). The only NEW allocation is the private-monitor wet track.

The track index numbering (Track 1 / Track 2 / etc.) is left to the implementation cc-task; the spec only fixes the *role* / *output destination* / *class* binding. The dual-processor spec §3.1 currently names the dual-engine voice secondary as "S-4 Track 1," and §11 of this amendment carries that forward as a constraint on the implementation if it does not collide with the new private-monitor allocation.

## §5. Hardware patch requirement

The S-4 analog OUT 1/2 pair must be patched into a non-broadcast monitor sink. Operator's explicit position (verbatim): *"I do not need to patch in private comms at the blue yeti point (patch in mon can be separate from mic input) — can patch in anywhere, in fact might be better elsewhere given a more flexible topology."*

The patch is operator-side hardware action; software cannot enforce its destination. This spec therefore enumerates *acceptable* and *forbidden* destinations.

**Acceptable patch destinations** (any non-broadcast monitor sink):

- Standalone headphone amp dedicated to operator monitoring (e.g., a small TR-input headphone amp with no further outputs).
- Motherboard HDA analog OUT (Ryzen onboard codec) to operator monitor speaker / headphones.
- Separate USB headphone interface (e.g., a Zoom AMS-22 or similar) whose output is operator monitor only.
- L-12 MONITOR B return *only if* that bus is hardware-fenced from the L-12 MASTER (and therefore from L-12 USB IN). This requires verifying that MON B is a true monitor-only bus on the operator's L-12 firmware revision; if there is any bleed path from MON B to MASTER or USB IN, this destination is forbidden.

**Forbidden patch destinations** (anything that re-enters the broadcast bus):

- Any L-12 channel input (CH1..CH12 or stereo PC IN) whose fader can be opened to MASTER. This is the immediate failure mode the safety SSOT addresses.
- Any S-4 USB IN pair (would loop the private signal back through S-4 USB OUT and into `s4-loopback` → `hapax-livestream-tap`).
- Any other USB capture surface that participates in the broadcast graph (see `config/audio-topology.yaml` for the canonical list).

The operator's choice of acceptable destination is recorded once at provisioning time. The runtime leak guard does not need to know the destination — it only needs to verify that the private track's S-4 analog OUT 1/2 routing has no software path back to L-12 USB IN.

## §6. Software wiring

The amendment requires the following software changes (all are scoped to the follow-up cc-task — this spec only specifies the deltas):

- **WirePlumber pin retargeting.** `config/wireplumber/56-hapax-private-pin-yeti.conf` currently pins `hapax-private-playback` to the Yeti monitor sink. Update it (or replace with a successor `56-hapax-private-pin-s4-track-input.conf`) to pin the private-playback role to the S-4 USB IN slot that feeds the new private-monitor track. The existing `55-hapax-private-no-restore.conf` (which prevents WirePlumber from restoring stale targets on the private role) is unchanged in policy and continues to apply.
- **S-4 internal scene programming.** The new private-monitor track requires an S-4 scene that wires `Track N: input = USB IN <pair>, output = analog OUT 1/2, slots = <Bypass · Mosaic · Ring · Deform · Vast or operator-chosen wet character>`. The scene is programmed via S-4 firmware (PC + per-slot CC burst) following the same delivery mechanism as the existing 10-scene library in `shared/s4_scenes.py`. The new scene's name should be `HAPAX-PRIVATE-MONITOR` to make its role legible in the registry.
- **`scripts/hapax-private-broadcast-leak-guard` rule extension.** The runtime scanner currently forbids any pw-link path from `hapax-private*` to L-12 broadcast targets. Extend its rule set with three explicit cases relative to the S-4 path: (a) FORBID `hapax-private-playback → S-4-USB-OUT-pair` (the broadcast-back path); (b) FORBID `hapax-private-playback → L-12-USB-IN` (direct broadcast leak); (c) ALLOW `hapax-private-playback → S-4-USB-IN-track-N` where Track N is the private-monitor track. The scanner needs to know which S-4 USB IN pair maps to the private-monitor track input — this is recorded once in `config/audio-topology.yaml` per the next bullet.
- **`config/audio-topology.yaml` descriptor.** Add: (a) a node entry for the S-4 USB IN slot that feeds the private-monitor track (kind: alsa_sink fragment within the existing `s4-output` capability set, with `params.role = private-monitor-track-input`); (b) a node entry for the S-4 analog OUT 1/2 pair (kind: alsa_source on the S-4 multichannel-output device's analog-out side, with `params.private_monitor_endpoint = true`, `params.forbidden_target_family = l12-broadcast`); (c) edge entries describing `hapax-private-playback → s4-private-track-input → s4-analog-out-1-2` as the canonical private-monitor path; (d) explicit exclusion edges (or schema-level annotation) recording that no path may exist from `s4-analog-out-1-2` back to `l12-capture`.

The static check `scripts/audio-leak-guard.sh` already enforces the inverse "no broadcast loopback from analog OUT 1/2 back to L-12 capture" guard; it needs no rule change for this amendment, only confirmation that the new descriptor entries are picked up by its parser.

## §7. Anti-anthropomorphism preserved

This resolution satisfies NO-DRY-HAPAX because:

- Private Hapax TTS is processed by an S-4 wet character (Vast / Mosaic / Diva / Deform / Ring per scene programming) on its way to the operator's monitor. The operator never hears a "naked" Hapax voice on the private path.
- The constitutional ground of NO-DRY is anti-anthropomorphism — destabilizing the human-voice default. That is a *function* (apply non-naturalistic processing) rather than a specific timbre (the Evil Pet's particular granular character). The function is preserved when S-4 character is substituted for Evil Pet character on the private path.
- The broadcast path remains unchanged: broadcast Hapax TTS continues to flow through the Evil Pet hardware loop with the existing 13-preset T-tier ladder (`shared/evil_pet_presets.py`). Listeners on the livestream hear the same processed voice they hear today.
- A secondary benefit: the private and broadcast paths now have *intentionally distinct* wet characters. The operator hears Hapax-on-S-4 in private deliberation; the audience hears Hapax-on-Evil-Pet in broadcast. The private/broadcast distinction is sonically legible.

## §8. Privacy invariant preserved

This resolution satisfies PRIVATE-NEVER-BROADCASTS because:

- The S-4 analog OUT 1/2 pair is hardware-isolated from the L-12 USB IN capture chain by construction: TR line outputs go to operator monitor amp / HDA / headphone interface, not to L-12 channel inputs.
- `scripts/audio-leak-guard.sh` enforces the static "no analog-OUT-1/2 → L-12-USB-IN" guard at check time. With the descriptor updates in §6, the static check covers the new private-monitor path.
- `scripts/hapax-private-broadcast-leak-guard` (PR #2221) enforces the runtime invariant via pw-link scanning. With the rule-set extensions in §6, the runtime scanner explicitly forbids private-playback → S-4-USB-OUT-pair and private-playback → L-12-USB-IN, while explicitly permitting private-playback → S-4-USB-IN-track-N.
- The fail-closed null-sink baseline on `hapax-private` (descriptor lines 79–88, `params.fail_closed = true`, `params.forbidden_target_family = l12-broadcast`) is preserved. If WirePlumber cannot pin the private-playback role to the S-4 track input (e.g., S-4 not USB-enumerated), the role degrades to silence rather than to a broadcast-eligible sink.

## §9. Trade-offs

**Pros:**

- Hardware FX character on the private path. The operator hears actual analog/granular processing (S-4 Vast/Mosaic/Ring/Deform), not a software approximation.
- S-4 remains multi-purpose. Broadcast roles 2–4 in the §4 table are unaffected. The S-4 is not reserved for private comms only.
- The existing private-broadcast leak guard (PR #2221) generalizes cleanly: only rule-set extension is needed, not architectural rework.
- The audio-topology descriptor extends naturally: per-track output classification is the canonical compartmentalization mechanism going forward; introducing more S-4 tracks (e.g., when Respeaker XVF3800 lands and shifts the routing matrix per `respeaker-xvf3800-introduction` cc-task) follows the same pattern.

**Cons:**

- Requires operator hardware patch (one-time): S-4 analog OUT 1/2 → chosen non-broadcast monitor destination (§5).
- S-4 must be present and USB-enumerated for private Hapax to be wet. The 2026-04-21 audit (`docs/research/2026-04-21-audio-systems-live-audit.md`) noted that the S-4 has not historically been USB-enumerated. The operator already requires S-4 presence for current broadcast roles (dual-processor spec §3.1), so this is no net regression — but if the broader stack needs to tolerate "private wet without S-4," a software-Evil-Pet fallback (the §6.A option in the routing-discovery doc) becomes a future consideration.
- The S-4's wet character is not the Evil Pet's wet character. By the operator's own framing this is acceptable (and arguably desirable) — anti-anthropomorphism is preserved as a function — but operators with timbral-parity preferences would want a different solution.

## §10. Implementation path

This spec is doc-only. Implementation is the follow-up cc-task `private-hapax-s4-track-fenced-implementation` (created alongside this spec, see `~/Documents/Personal/20-projects/hapax-cc-tasks/active/private-hapax-s4-track-fenced-implementation.md`).

Reference: `respeaker-xvf3800-introduction` cc-task (`~/Documents/Personal/20-projects/hapax-cc-tasks/active/respeaker-xvf3800-introduction.md`). The Respeaker XVF3800 introduction will affect track allocation when it lands — it adds a far-field operator capture surface that may itself want a dedicated S-4 track, or may compete for the same private-monitor track if used for AEC reference. The implementation cc-task therefore depends on `broadcast-chain-monitor-zero-investigation` (current in-flight) and is sequenced ahead of the Respeaker introduction so the private-monitor track is reserved before the array re-shuffles allocations.

## §11. Supersession

This amendment SUPERSEDES the dual-processor spec §3.1 row "Voice (TTS, Rode) — private bypass case" with respect to the private path only. Specifically: the prior contract treated private TTS as `dry` by default with no engine assigned (the role-assistant chain was a fail-closed null sink). The new contract is: private TTS routes to the S-4 private-monitor track, which is wet via S-4 character on its way to operator monitor.

The broadcast row of dual-processor §3.1 ("Voice — primary Evil Pet, secondary S-4 Track 1") is **unchanged**. Music ("primary S-4 Track 2, secondary Evil Pet"), Vinyl, Sampler, Operator SFX, and Contact mic rows are **unchanged**. The 12-class topology registry, the three-layer policy arbiter, and Phase A/B/C plan structure are **unchanged**.

The dual-processor spec frontmatter has been updated with a `superseded_by` pointer to this amendment, scoped explicitly to the private-bypass row (see that spec's frontmatter note).

## §12. Open questions for operator

These three carry over from `/tmp/routing-discovery-2026-05-02.md` §8 with their status updated:

1. **Does NO-DRY-HAPAX extend to the operator's Rode voice on broadcast?** The unified-architecture spec says all sources go through Evil Pet by default; the dual-processor §3.1 carries operator voice as `mostly dry`; the constitutional ground of NO-DRY is specifically anti-anthropomorphism *for Hapax*. Awaiting operator clarification. Out of scope for this amendment.

2. **Software-FX function-parity vs hardware-Evil-Pet timbral parity?** PARTIALLY ANSWERED. Operator chose hardware FX via S-4 Track-fenced approach for the private path — function parity through a different timbre, not software emulation of Evil Pet. The remaining open question is whether the operator wants timbral parity later (Option B: second physical Evil Pet on a private path) — this can be revisited but is not currently in the path.

3. **Does Hapax actually emit private internal monologue today, or is it a future affordance?** The role-assistant chain is wired (descriptor lines 79–88, `config/audio-routing.yaml` lines 54–82) but no code path is currently observed emitting `role.assistant`-targeted TTS. If the answer is "yes today," the implementation cc-task is urgent. If the answer is "future affordance," the spec can be in place while the implementation defers until a private-emitting consumer ships.

---

## Sources

- Operator directive 2026-05-02T~17:00Z (locking the per-track output fence resolution)
- Operator clarification 2026-05-02T~17:00Z (S-4 multi-citizenship; patch destination flexibility)
- `/tmp/routing-discovery-2026-05-02.md` (research substrate; §6 Option C; §8 open questions)
- `docs/superpowers/specs/2026-04-21-evilpet-s4-dynamic-dual-processor-design.md` (current canonical dual-processor spec; §3.1 source → engine contract)
- `docs/superpowers/specs/2026-04-23-livestream-audio-unified-architecture-design.md` (NO-DRY-HAPAX origin, decision #2)
- `docs/superpowers/specs/2026-04-28-broadcast-audio-safety-ssot-design.md` (private/broadcast invariant SSOT)
- `config/audio-topology.yaml` (descriptor; private/broadcast classification location)
- PR #2221 (just-shipped 3-layer private→broadcast leak guard)
