# Pre-Live Audit — Final Holistic Synthesis

**Date**: 2026-04-20
**Inputs**:
- Catalog: `docs/research/2026-04-20-livestream-audit-catalog.md`
- Cascade slice: `docs/research/2026-04-20-cascade-audit-results.yaml` (67 audits, 73 result rows)
- Alpha slice: relay file `alpha-audit-results-20260419.yaml` (37 audits, 37 result rows)

**Total coverage**: 104 catalog audits across 110 result entries (cascade
split a few IDs into sub-items for granularity).

---

## §0. Combined headline

| Outcome | Cascade (67) | Alpha (37) | **Total (104)** | %  |
|---|---|---|---|---|
| Pass | 53 | 22 | **75** | 68% |
| Warn | 11 | 8 | **19** | 17% |
| Fail | 0 | 2 | **2** | 2%  |
| Indeterminate | 9 | 5 | **14** | 13% |

**Two hard fails, both in alpha's slice**:
- **12.1** — grounding_provenance 99.3% empty; constitutional axiom violation
- **11.2** — reverie pool_reuse_ratio = 0.0 (likely restart-freshness, needs 30-min re-audit)

**Alpha's four incident flags** (from their YAML):
1. 12.1 grounding_provenance invariant silently broken
2. 11.2 texture-pool cache never hitting
3. 9.2 pi4/pi5/hapax-ai heartbeat coverage gap
4. 4.4 voice-over-ytube-duck.conf missing (PipeWire sink ducking absent)

---

## §1. Pre-live gate verdict

**GO for monetization-safety.** No stream-stop findings. The two hard
fails are a governance-layer silent-break (12.1) and a performance
concern under re-audit (11.2) — neither threatens YouTube Partner
Program eligibility or dignity invariants.

Advisory pre-live operator actions (all ≤ 10 min each):

1. **Install voice-over-ytube-duck.conf** (alpha 4.4 remediation).
   Real quality gain — YT audio dips under Hapax TTS at the
   PipeWire sink layer instead of relying on the SlotAudioControl
   mute_all_except logic alone. Template in `config/pipewire/README.md`.
2. **Physical-mixer photo or test-signal pass** (alpha 4.8 requires
   operator verify).
3. **Visually review YouTube title/description** before pushing live
   (cascade 1.8/13.4 both warn that LLM-origin metadata isn't
   automatically scanned).

Optional hardening (not blocking):

4. **Re-run 11.2 after 30 min steady-state** to confirm pool reuse
   climbs above 0.9 as the compositor warms.
5. **Install hapax-heartbeat.timer on pi4/pi5/hapax-ai** (alpha 9.2
   + pi-fleet-audit F1). Doesn't affect live stream — affects
   post-live observability.

---

## §2. Cross-cutting patterns — the four load-bearing insights

### Pattern 1: Observability blind spots enable silent invariant breaks

Cascade's §7.1 warned "only 20+ prometheus registrations" in the
codebase without being sure coverage was complete. Alpha's **12.1 is
the exact realised failure mode of that gap**: the director-loop emits
compositional intents, and the spec §4.9 mandates every intent carry
grounding_provenance OR emit an UNGROUNDED warning. The director is
doing NEITHER. 99.3% of 454 recent intents have empty provenance and
no UNGROUNDED warning ever fired.

**This pattern (silent invariant break + dormant observability) is
the archetype** — the 2026-04-20 14:08 TTS leak was a different
instance of the same pattern (content-safety gate caught one variant,
another variant slipped past, no counter increment told us).

**Remediation**: every invariant-emitter code path must have a
counter that increments on BOTH the happy path AND the spec-violation
path. Then scrape alerts on the violation-counter tell us before a
human ear/eye does. File as post-live hardening epic.

### Pattern 2: Multi-layer defences work only when every layer is present

Audio ducking is a 4-layer stack:
- (a) producer publishes `yt-audio-state.json` — FINDING-C ✅
- (b) FSM transitions normal/yt_active/voice_active/both_active — ✅
- (c) PipeWire sink-level gain modulation via
  `voice-over-ytube-duck.conf` — **MISSING ❌** (alpha 4.4)
- (d) youtube-player wpctl-tick re-mute — FINDING-E ✅

Layers a/b/d work but without (c) there's no smooth gain curve when
Hapax speaks over YT — operator will hear a hard cut rather than a
duck. **The FSM alone is logical; the perception requires the sink
gain too.**

Same pattern in content-safety:
- (a) LLM prompt-level prohibition — **MISSING ❌** (task #165)
- (b) post-LLM text-level regex gate — ✅ (shipped today)
- (c) TTS-synthesis fail-closed — ✅ (integrated into TTSManager)
- (d) audio-egress last-chance filter — not implemented

The 2026-04-20 14:08 leak happened because (a) is missing; (b)
caught one variant; (c) doesn't detect slur tokens, only synthesises
them; (d) doesn't exist. **One layer working is not defence-in-depth.**

### Pattern 3: Recent deploys (Choreographer, FINDING-B) propagate correctness downstream

Alpha's 3.4, 3.5, 3.6 all pass — package-swap correctness, FSM
coverage, emphasis envelope — **because FINDING-B (Choreographer
wiring `54e2d36d6` earlier today) cascaded fresh data into the
ward-properties file that these observables depend on**. Pre-fix,
all three would have been hard FAIL. This is visible in alpha's
cross_cutting_observations.

**Implication for the pre-live gate**: the "go-safe" verdict today
is contingent on hapax-daimonion / studio-compositor / hapax-imagination
staying restart-stable. A restart after a bad commit could regress
2026-04-19 02:29 → 11:47 all over again. Recommend a post-deploy
sanity cycle that re-runs alpha's 37-audit slice whenever any of those
three services restarts.

### Pattern 4: Cascade-indeterminate ↔ alpha-fail pairs reveal observability coverage gaps

Cascade's 9 indeterminates cluster around "couldn't verify from outside
the service"; alpha's 2 fails + 5 indeterminates cluster around
"couldn't find the metric/file". **Where they touch the same surface,
we have evidence the observability layer needs a metric.**

Specific pairs:
- cascade 5.2 indirect + alpha §11 compositor regression → fail-closed
  face-obscure should have a Prometheus gauge flipped on detector
  crash
- cascade 2.3 FINDING-V ok + alpha 12.4 no compositional dispatch
  counter → ward.highlight firing observable empirically (508 hits)
  but no rate metric exists
- cascade 7.1 metric coverage warn + alpha 12.1 grounding_provenance
  fail — direct-pair confirmation

---

## §3. The 2026-04-20 14:08 leak — post-mortem through both slices

The tuple of findings together explains the leak:

1. YT player (slot 1) started `State Of Street Rap` commentary video.
2. LLM saw that content as context + generated narration that
   naturally used slur tokens (no prompt-level prohibition — Pattern 2
   layer (a) missing).
3. Speech-safety regex (layer b) caught one `nigga` → substituted
   `kinsman` (14:08:43 log).
4. **LLM emitted additional slur variants** — likely `niggah` /
   `niggaz` — that the original regex didn't cover.
5. Gate didn't fire on the variant; TTSManager.synthesize synthesised
   verbatim; broadcast leaked.

Cascade's response (this session):
- Widened regex (`303e5fd2a`) — fixes step 4 for these variants.
- Deterministic KMD pool (`4f071e4ac`) — aesthetic quality of step 3.

What's still NOT fixed:
- Step 2: LLM is still producing slur tokens. Prompt-level
  prohibition is task #165.
- Step 5: no last-chance audio-side filter. Phoneme-level ASR of the
  TTS output → re-check would be a layer (d) candidate. Heavy.

**If operator goes live now, the surviving risk is that a NEW slur
variant (not in the regex's [aeuohi]+[rzsx]? class) emerges from the
LLM.** Low-probability but non-zero.

---

## §4. Operator-facing single-table verdict

| Concern | Status | Action |
|---|---|---|
| N-word leaks via TTS | **Mitigated, not eliminated** | Task #165 prompt-level; consider ring-1 audio filter post-live |
| Face obscure + consent | Pass (alpha confirms render integrity) | — |
| Audio routing (op mic + TTS → broadcast) | Pass | — |
| Audio ducking | **Logical works, sink-level missing** | Install voice-over-ytube-duck.conf (5 min, ≤ pre-live) |
| Hardware readiness | Pass (GPU/cameras/disk/RTMP/shader) | — |
| Pi fleet observability | Pass for livestream-relevant pi1/2/6; pi4/5/ai silent | Post-live hardening |
| Grounding invariant | **Constitutionally broken (12.1)** | Post-live fix; not monetization-risk |
| Texture pool reuse | 0% (11.2) | Re-audit after 30 min steady-state; if still 0 → investigate |
| Governance drift | Pass | — |
| YT metadata review | No automated scanner | **Operator visual review pre-publish** |
| Live-egress kill-switch | Pass | Test once before stream start |

---

## §5. Recommended pre-live minimal-sweep (operator ≤ 15 min)

Not the 30-row catalog gate — the distilled irreducible sweep based on
what BOTH slices actually found today:

1. `ls ~/.config/pipewire/pipewire.conf.d/voice-over-ytube-duck.conf`
   — if missing, cat the template from `config/pipewire/README.md`
   and install; restart pipewire. (Alpha 4.4)
2. Photo the PreSonus Studio 24c mixer, or run a test tone pass.
   (Alpha 4.8)
3. Review the YouTube broadcast title + description + tags for any
   LLM-origin text that might be a monetization concern. (Cascade
   1.8/13.4)
4. Run the cascade canary oneliner from
   `docs/research/2026-04-20-finding-v-deploy-status.md` — every SHM
   file under expected age.
5. Manually test the live-egress kill switch: `touch ~/.cache/hapax/egress-kill` → verify compositor stops publishing → `rm` the flag → verify resumes. (Cascade 16.6)

If all 5 pass, pre-live gate is green.

---

## §6. Post-live hardening epic — proposed sequence

Not blocking, but material to stream quality + reliability:

1. **Prompt-level slur prohibition** (task #165) — the Pattern 2
   layer (a) that's missing from content-safety
2. **Grounding-provenance invariant fix** (alpha 12.1) — director
   emits provenance OR logs UNGROUNDED
3. **Observability-counter invariant** (Pattern 1 meta-fix) — every
   new emitter ships with a hit-counter + a violation-counter
4. **Pool-reuse investigation** (alpha 11.2) — 30-min steady-state
   re-audit; if still 0, TransientTexturePool key-derivation bug
5. **Pi heartbeat coverage** (alpha 9.2 + pi-fleet F1) — rsync the
   heartbeat unit to pi4/pi5/hapax-ai
6. **Audit-as-systemd-timer** — weekly scheduled run of both slices
   against steady-state; dashboard the delta vs baseline

---

## §7. Open questions this synthesis doesn't resolve

1. **Is 11.2 pool_reuse_ratio actually a bug or restart artefact?**
   Need 30-min re-audit.
2. **How aggressive should prompt-level slur prohibition be?** Task
   #165 scope — blanket "never generate" vs "substitute at
   generation" vs "mark as redactable and let speech_safety
   substitute". Different downstream effects.
3. **Should we ship Audit-as-systemd-timer before or after the first
   live stream?** Recommendation: after, because the baseline it
   diffs against should be the steady-state of a working stream.

---

## Cross-reference appendix

- Cascade raw: `docs/research/2026-04-20-cascade-audit-results.yaml`
- Alpha raw: relay file `alpha-audit-results-20260419.yaml`
- Catalog: `docs/research/2026-04-20-livestream-audit-catalog.md`
- Cascade synthesis (pre-alpha): `docs/research/2026-04-20-audit-synthesis.md`
- This final synthesis: the file you are reading
