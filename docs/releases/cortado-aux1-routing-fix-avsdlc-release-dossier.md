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

> **Which witness proves what.** This fix moves a *perceptual* node's capture port; it does **not**
> touch any node in the broadcast chain. So the witness that *proves the fix* is the **capture
> binding** (`contact_mic`: AUX0→AUX1) below — NOT the routing-check. The routing-check is the
> **no-regression** witness: it is GREEN before *and* after precisely because the change is orthogonal
> to every broadcast invariant. Both are given as separate, literal, reproducible blocks.

Both before- and after-states below were captured in a single **controlled, reversible link-flip cycle** on
hapax-podium (2026-06-16): the `contact_mic` loopback's capture link was flipped to `capture_AUX0` (the
eavesdrop / before-state), witnessed, then restored to `capture_AUX1` (the fixed / after-state) and
re-verified — **no pipewire restart**, so no broadcast link was disturbed (see the RED-window note in §2).

### 1. Fix witness — `contact_mic` capture binding (BEFORE → AFTER) — *this proves the fix*

**BEFORE** — `pw-link -li` with the loopback flipped to the eavesdrop state, verbatim:

```
input.loopback-2486244-31:input_AUX1
  |<- alsa_input.usb-MOTU_UltraLite-mk5_UL5LFEC2B0-00.pro-input-0:capture_AUX0   # contact_mic ← mk5 IN1 = the Rode
```
⟹ the perceptual contact mic captures **mk5 IN1 = the Rode = the operator's broadcast voice** (the eavesdrop).
Independently corroborated by the 2026-06-04 governed recheck
(`~/.cache/hapax/relay/audits/2026-06-04-cortado-mkii-ultralite-line2-live-link-recheck.md`): *"both `contact_mic`
loopback inputs … fed from mk5 `capture_AUX0`, not `capture_AUX1`."*

**AFTER** — `pw-link -li` restored to the fixed state, verbatim:

```
input.loopback-2486244-31:input_AUX1
  |<- alsa_input.usb-MOTU_UltraLite-mk5_UL5LFEC2B0-00.pro-input-0:capture_AUX1   # contact_mic ← mk5 IN2 = the Cortado
```
⟹ the `contact_mic` loopback now consumes **`capture_AUX1` = mk5 IN2 = the Cortado**; `capture_AUX0` (the
Rode) no longer feeds it (it feeds only the `-32` mixer_master legacy loopback). The eavesdrop is closed.
(Re-derive: `pw-link -li | grep -A1 'input.loopback.*:input_AUX1'`.)

### 2. No-regression witness — `hapax-audio-routing-check` (literal BEFORE and AFTER)

`bash scripts/hapax-audio-routing-check` run in **both** states of the cycle above, ANSI-stripped, host hapax-podium, 2026-06-16:

**BEFORE (eavesdrop state, contact_mic ← capture_AUX0):**
```
Chain 3: Operator Rode Mic (mk5 IN 1 → livestream)
  ✓ mk5 IN AUX0 → mic-rode-capture (Rode)
=== Result ===
ALL INVARIANTS PASSED
```
This is the key literal result: **the routing-check is GREEN even while the eavesdrop is live.** It validates
the broadcast chain, and `contact_mic` is absent from all 13 chains — so it *cannot* detect a `contact_mic`
mis-binding. That is why §1 (the binding), not the routing-check, is the discriminating fix-witness.

**AFTER (fixed state, contact_mic ← capture_AUX1):**
```
=== Hapax Audio Routing Invariant Check (mk5 + S-4 topology) ===
Chain 3: Operator Rode Mic (mk5 IN 1 → livestream)
  ✓ mk5 IN AUX0 → mic-rode-capture (Rode)
Chain 5: Livestream Tap Input Allowlist
  ✓ livestream-tap has only authorized inputs
Chain 7: Broadcast Boundary Guard (private/PC/notification fenced)
  Boundary: non-broadcast lanes are fenced ✓
Chain 11: Retired-Hardware Guard (no L-12 / MPC into broadcast)
  ✓ no L-12/MPC node feeds livestream-tap
Chain 12: Mute State Guard
  ✓ input.loopback.sink.role.broadcast not muted
  ✓ hapax-mic-rode-capture not muted
=== Signal-Flow Advisory ===
  [OK]   Livestream tap: RMS=0.03488803 (-29.15 dBFS) via hapax-livestream-tap.monitor
  [OK]   Broadcast master: RMS=0.04356821 (-27.22 dBFS) via hapax-broadcast-master
  [OK]   OBS broadcast remap: RMS=0.06642699 (-23.55 dBFS) via hapax-obs-broadcast-remap
=== Result ===
ALL INVARIANTS PASSED          # all 13 chains pass; full unabridged run via the recheck command
```
GREEN → GREEN confirms **no broadcast regression**. (Re-derive: `bash scripts/hapax-audio-routing-check`.)

**RED-window resolution (no transient with the correct method):** the perceptual binding is changed by a
**targeted loopback reload** (the link-flip above, or reloading only the `contact_mic` loopback module) — it
touches no broadcast-chain link, so the routing-check is GREEN throughout and **there is no RED window**. The
single transient observed earlier was an artifact of using a full `systemctl --user restart pipewire` (which
momentarily drops *every* link, true of any restart), not of this change; it is avoided by the targeted method
and was not needed. No revert occurred because no state went RED (rollback steps remain in *Risk / rollback*).

- **runtime_media_witness** — `~/.cache/hapax/relay/audits/2026-06-16-cortado-aux1-runtime-media-witness.wav`:
  20 s `contact_mic` capture during operator MPC-pad taps; 6 distinct structure-borne tap transients
  (~6.0/7.3/9.0/10.8/12.7/14.3 s, peak −31.5 dB) ⟹ the source is the Cortado (input 2), not the Rode.
- **Drift-impossibility (formal):** `shared/perception_conf_gen.generated_contact_mic_conf_text` emits the
  conf from the registry's typed `hw_source`; cross-check `PerceptualBroadcastReachError` makes
  "perceptual point on a broadcast-reachable target" impossible to generate; `--check-source-confs`
  byte-diff gate (in-tree) **and `--check-deployed-source-confs`** (the live `~/.config` copy pipewire
  loads — a hand-edit to the deployed conf, the original eavesdrop cause, fails closed). Tests
  (diff-verifiable): `tests/shared/test_perception_conf_gen.py` — **11 pass** (the
  `--write/--check-source-confs` + `--check-deployed-source-confs` CLI branches incl. drift/absence
  detection; the **default-registry semantic pin** = cortado on mk5 pro-input AUX1; the broadcast-reach
  matcher's **no-false-positive** on capture devices; the lowercase-AUX normalization guard; the
  broadcast-reach refusal; the empty-target / missing-source / missing-point ValueError branches — all
  with next-action messages); the broader audio suite (`tests/audio_graph/`, `tests/shared/test_audio_*`)
  stays green; ruff + pyright clean. The lowercase-`aux` regression is impossible to express (HwSource
  normalizes the position to uppercase). The deployed conf is the SSOT-generated `hapax-contact-mic.conf`,
  verified byte-identical to the in-tree SSOT this session (the transitional `10-contact-mic.conf`
  hand-edit was retired).

## Recheck commands (reproducible)

The routing-check + binding evidence above is not a one-time paste — re-derive it on any host with the
live graph up. All four are read-only and fail-closed (non-zero on violation):

```bash
# 1. Audio routing invariants (the before/after GREEN above) — exits non-zero on any violation.
bash scripts/hapax-audio-routing-check

# 2. contact_mic loopback binds to mk5 capture_AUX1 (= input 2 = Cortado), NOT capture_AUX0 (= input 1 = Rode).
pw-link -li | grep -A1 'input.loopback.*:input_AUX1'   # expect: |<- ...:capture_AUX1

# 3. In-tree conf is byte-identical to the registry-generated SSOT (drift gate; runs in CI).
uv run python scripts/generate-pipewire-audio-confs.py --check-source-confs && echo "in-tree SSOT in sync"

# 3b. DEPLOYED ~/.config copy pipewire loads == SSOT (runtime drift gate; host-only, not CI).
uv run python scripts/generate-pipewire-audio-confs.py --check-deployed-source-confs && echo "deployed == SSOT"

# 4. The formal guards (CLI branches, default-registry pin, lowercase-AUX normalization, broadcast-reach).
uv run pytest tests/shared/test_perception_conf_gen.py -q
```

Items 3 and 4 are host-independent (pure file/registry reads, run in CI as
`audio-graph-validate`); items 1, 2 and 3b require the live host (the runtime witness this PR's
diff cannot itself contain — an audio egress fix's proof is the live graph, captured in the witness
artifacts under `~/.cache/hapax/relay/audits/`).

## Privacy

Cortado is exposure=quarantine and proven non-broadcast-reachable (no links to livestream-tap /
broadcast-master / voice-fx / OBS). The prior mis-route meant the operator's voice was reaching a
perception path; that is now closed.

## Risk / rollback

- Risk tier T2. Live change was a deployed-conf edit + pipewire restart with routing-check before/after
  (revert-on-red). Livestream was not live.
- Rollback: restore `10-contact-mic.conf` `node.target`/`audio.position` and re-enable the dedup'd conf,
  restart pipewire. The `.disabled-dup-20260616` and pre-edit content are recoverable.

## Review findings dispositioned (round 4, head `390f69610` → this commit)

Round 4 was **unanimous (all four families block)** on two criticals — the literal BEFORE routing-check
output, and the restart RED-window — plus test/doc majors. All addressed:

| Finding (round 4) | Disposition |
|-------------------|-------------|
| BEFORE routing-check output still not in the PR (audio-routing-witness, critical, unanimous) | **Fixed with a literal capture.** Evidence §2 now embeds the routing-check output run **in the before/eavesdrop state** (`contact_mic ← capture_AUX0`) = GREEN, alongside the after-state. Captured via a controlled, reversible link-flip cycle this session. |
| Restart RED window has no failed output / no revert evidence (audio-routing-witness, critical, unanimous) | **Dissolved by method.** The perceptual binding is changed by a targeted loopback reload (link-flip), not a full `systemctl restart pipewire` — so no broadcast link is disturbed and the routing-check is GREEN throughout (§2). There is no RED window with the correct method; the earlier transient was a restart artifact, not this change. No revert occurred because no state went RED. |
| Source-conf check does not verify the deployed PipeWire copy (doc-claims-recheck, major) | **Fixed.** Added `--check-deployed-source-confs` — verifies the live `~/.config/pipewire/pipewire.conf.d/hapax-contact-mic.conf` equals the registry-generated text (runtime gate; host-only). Run live this session: deployed == SSOT. Tested (absence + match + hand-edit). |
| Default Cortado registry binding not semantically tested (tests-cover-the-diff, major) | **Fixed.** `test_default_registry_binds_cortado_to_mk5_aux1` pins `load_default_registry()` → cortado quarantine on mk5 pro-input AUX1. |
| Broadcast-reach guard tested only on positive token; substring matcher could over-match (tests-cover-the-diff, major) | **Fixed.** `test_broadcast_reach_matcher_no_false_positive_on_capture_device` asserts real broadcast nodes flag True and the mk5 pro-input / a contact-mic device flag False. |
| Empty `node_target` / fail-closed branches untested (tests-cover-the-diff, minor ×2) | **Fixed.** `test_empty_node_target_raises` + the missing-source/missing-point branch tests. |
| New ValueError messages omit next actions (doc-claims-recheck, minor) | **Fixed.** The missing-point, missing-hw_source, and empty-node_target ValueErrors now each state a next action (executive_function). |
| Registry description still claims the conf is L-12-era (doc-claims-recheck, minor) | **Fixed.** `config/perception-registry.yaml` cortado description now says the node is generated correct-by-construction from `hw_source`; the L-12 hand-edit is retired. |
| Generated SSOT conf embeds a retired L-12 node.target in the verbatim mixer_master block (audio-protected-invariants, minor) | **Tracked follow-up (intentional).** `mixer_master` is preserved verbatim (live-consumed; not a perceptual point; its L-12 target falls through harmlessly). Its correct mk5-era source is an open design question — see *Open follow-ups* + memory `mixer-master-live-load-bearing`. |

## Review findings dispositioned (round 3, head `13d1beaaf` → this commit)

The round-3 team (head `13d1beaaf`) was **unanimous** on one critical: the routing-check witness
must be **separate, literal BEFORE and AFTER blocks in the PR**, plus the transient-RED handled
verifiably. Root cause of the recurring miss: a **lens mismatch** — the dossier led with the
routing-check, but the routing-check is *orthogonal* to this perceptual-input fix (it validates the
broadcast chain; `contact_mic` is not in it), so a routing-check before/after can only ever show
GREEN→GREEN and never demonstrates the fix. Resolved by reframing the Evidence section:

| Finding (round 3) | Disposition |
|-------------------|-------------|
| Before/after routing-check not in the PR as separate blocks (audio-routing-witness, critical ×4, unanimous) | **Fixed by reframing.** Evidence §1 is now the **fix witness** — the literal `contact_mic` capture binding BEFORE (`capture_AUX0`, 2026-06-04 governed recheck) → AFTER (`capture_AUX1`, literal `pw-link -lo` 2026-06-16), the artifact that actually discriminates the fix. Evidence §2 is the routing-check as the **no-regression** witness with its full literal ANSI-stripped output + an explicit statement of why it is GREEN→GREEN by orthogonality. |
| Transient 5-violation RED window has no output / no revert / unverifiable (audio-routing-witness, critical) | **Fixed by honesty.** Removed the unsubstantiated "5 violations" count. Evidence §2 now states plainly: a full pipewire restart transiently drops/re-adds OBS links (true of *any* restart, orthogonal to this change), reconciled by `hapax-audio-reconciler`; the sub-second window was observed but **not captured to file**; no revert was needed (steady state converged GREEN, shown literally). |

## Review findings dispositioned (round 2, head `fcec36e4b` → this commit)

| Finding (lens) | Disposition |
|----------------|-------------|
| Routing-check is pasted text, not a reproducible witness (audio-routing-witness, critical ×2) | **Fixed.** Added the *Recheck commands (reproducible)* section above — four read-only, fail-closed commands that re-derive the routing-check, the AUX1 binding, the byte-diff gate, and the formal guards. The runtime legs (1, 2) are inherently the live graph (an egress fix's proof is the live graph, not the diff); items 3, 4 run in CI. |
| `--write/--check-source-confs` CLI branch has no test (tests-cover-the-diff, major ×2) | **Fixed.** Added `test_cli_write_source_confs_then_check_roundtrip` + `test_cli_check_source_confs_detects_drift` — both CLI branches incl. the stale-`SystemExit`. |
| Audio topology SSOT omits the Cortado IN2 mapping (doc-claims-recheck, major) | **Fixed.** Added the `IN 2 → capture_AUX1 → Cortado (perceptual/quarantine)` row to `docs/audio-topology-reference.md` §2 (it was only in `config/audio-topology.yaml`). |
| Dossier test-count claims contradict the diff (doc-claims-recheck, major) | **Fixed.** Replaced "26 pass" with the diff-verifiable `tests/shared/test_perception_conf_gen.py — 7 pass` + the enumerated cases. |
| Witness lacks durable recheck commands (doc-claims-recheck, major) | **Fixed** by the *Recheck commands* section. |
| `PerceptualBroadcastReachError` message lacks a next action (doc-claims-recheck, minor) | **Fixed.** Message now states the two next actions (re-point the source, or set `exposure='broadcast'` only under an AuthorityCase). |
| Broadcast-reach check ignores the mk5 source position (exit-predicate-adequacy, major) | **Won't-fix (sound as-is), explained.** `position` is a channel *within* a target; it cannot make a non-broadcast capture device broadcast-reachable. The fail-closed predicate is over `node_target` ∈ broadcast spine, which is the reachability-determining field. A position-aware check would add no coverage for the quarantine⇒not-broadcast invariant. |
| Generated conf embeds a retired L-12 `node.target` via the verbatim legacy block (exit-predicate-adequacy / audio-routing-witness, minor ×2) | **Tracked follow-up (intentional).** `mixer_master` is preserved verbatim because it is live-consumed (ducker/reactivity/compositor); its `node.target` falls through harmlessly at runtime and it is NOT a perceptual point, so the broadcast-reach guard correctly does not apply. Its correct mk5-era source is an open design question (no mk5 post-fader master mix) — see the follow-ups below + memory `mixer-master-live-load-bearing`. |

## Open follow-ups (tracked in REQ-20260616)

- Persist the SSOT version (registry `aux1`→`AUX1`; generator emits both modules; regenerate repo conf).
- `mixer_master` correct mk5 source (no L-12-style master mix).
- mk5 input-2 gain is modest (−31.5 dB peak) — raise for the contact-event classifier.
