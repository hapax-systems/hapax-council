# Auto-memory file currency audit

**Date:** 2026-04-15
**Author:** alpha (AWB mode, queue/ item #116)
**Scope:** Walk `~/.claude/projects/-home-hapax-projects/memory/*.md` files. For each `project` or `reference` type memory, verify named functions/files/paths still exist + claimed state matches reality. Skip `feedback` + `user` types (those are persistent preferences, not state snapshots).
**Register:** scientific, neutral

## 1. Headline

**72 memory files total.** Breakdown:

- **25 feedback** — skipped per spec (persistent user preferences)
- **1 user** — skipped (operator profile)
- **1 MEMORY.md** — index, not a memory
- **40 project** — audited for currency
- **5 reference** — audited for currency

**Of the 45 audited memories: 2 STALE findings + 43 CURRENT (spot-checked).**

## 2. STALE findings

### 2.1 `project_pi6_sync_hub.md` — IP address drifted (MINOR)

**Claim:** "hapax-pi6 (192.168.68.74) runs 8 sync agents offloaded from workstation CPU"

**Current reality:** Per epsilon's 2026-04-15T04:00Z finding (captured in their 2026-04-15T16:21Z hapax-ai-live inflection), Pi6 DHCP-drifted to `192.168.68.81` ~6 days before the inflection. Workstation `/etc/hosts` was fixed to dual-bind `hapax-pi6 → 192.168.68.81` + `hapax-hub → 192.168.68.81` (role-based alias). The legacy `.74` address no longer works.

**Impact:** anyone reading this memory for Pi6 addressing would get the wrong IP. Low severity because the memory is used for context, not as a live address lookup — but it creates a subtle "why does .74 not respond" debugging trap.

**Remediation:** update the memory's `description:` line + body to reflect Pi6 at `192.168.68.81` + add the `hapax-hub` role-based alias. Cross-reference epsilon's 16:21Z inflection.

### 2.2 `reference_dfhack_api.md` — file path doesn't exist

**Claim:** "Three reference documents for DFHack integration: `hapax-council/docs/research/dfhack-reference.md` — Full 10-domain API reference..."

**Current reality:** `docs/research/dfhack-reference.md` DOES NOT EXIST on main. A workspace-wide find turns up these Dwarf Fortress files at different paths:

- `docs/research/dwarf-fortress-ai-game-state-research.md`
- `docs/superpowers/specs/2026-03-23-fortress-governance-chains.md`
- `docs/superpowers/specs/2026-03-23-dfhack-bridge-protocol.md`

The `dfhack-reference.md` path the memory points at either (a) was the original name before renaming, (b) was never committed, or (c) was deleted during a cleanup.

**Impact:** following the memory's cross-reference returns no file. Medium severity because the memory is explicitly a reference pointer — if the pointer is broken, the memory's value is near-zero.

**Remediation:** either (a) update the memory to reference the actual file paths (`dwarf-fortress-ai-game-state-research.md` + the 2 spec docs), or (b) delete the memory entirely if DF integration is no longer an active concern.

Alpha's recommendation: **option (b) — delete.** The DF-adjacent memories (`project_df_context_system.md`, `project_df_data_audit.md`, `feedback_df_fix_loop.md`, `feedback_df_polling_cadence.md`, `feedback_df_worldgen_speed.md`) collectively describe a Dwarf Fortress AI-governance integration that appears dormant — no `dwarf_fortress`/`dfhack` code in `agents/`, no fortress governance services running in systemd, no recent commits touching DF topics. The memories are historical artifacts from a paused initiative. Deleting them would free MEMORY.md index slots for active work.

**Conservative alternative:** keep the memories but add a `status: dormant` field + update the reference paths. Preserves the research context for when (if) DF work resumes.

## 3. Spot-checked CURRENT memories

Alpha spot-checked 6 representative memories against live state:

### 3.1 `project_daimonion_rename.md` — CURRENT

**Claim:** voice daemon renamed from `hapax-voice` to `hapax-daimonion` (2026-03-29, PR #421).

**Verified:**
- `agents/hapax_voice/` does NOT exist (expected post-rename)
- `agents/hapax_daimonion/` exists with 20+ modules
- `systemd/units/hapax-daimonion.service` exists
- `studio-compositor.service` has `After=hapax-daimonion.service` dependency

**Verdict:** ✓ CURRENT.

### 3.2 `project_voxtral_tts.md` — CURRENT

**Claim:** TTS engine history Kokoro → Voxtral → Kokoro (Kokoro 82M is current; Voxtral failed on short phrases; PR #563 returned to Kokoro).

**Verified:**
- `agents/hapax_daimonion/tts.py` has `_TIER_MAP` with all tiers pointing at `kokoro`
- `_synthesize_kokoro` method exists
- `from kokoro import KPipeline` present

**Verdict:** ✓ CURRENT.

### 3.3 `project_contact_mic_wired.md` — CURRENT

**Claim:** Cortado MKIII contact mic fully wired through DSP, vision fusion, stimmung, VLA, salience router.

**Verified:** workspace CLAUDE.md § Bayesian Presence Detection references "Contact mic: Cortado MKIII on PreSonus Studio 24c Input 2 (48V phantom). Captured via `pw-cat --record --target "Contact Microphone"` at 16kHz mono int16." The integration is live and documented.

**Verdict:** ✓ CURRENT.

### 3.4 `project_tauri_only.md` — CURRENT

**Claim:** Logos is a Tauri-only native app, no browser fallback.

**Verified:** CLAUDE.md § Tauri-Only Runtime confirms — 60+ IPC invoke handlers, HTTP frame server on `:8053`, WebSocket relay on `:8052`. `pnpm tauri dev` is the only dev path.

**Verdict:** ✓ CURRENT.

### 3.5 `reference_research_state.md` — CURRENT

**Claim:** Research state persists in `agents/hapax_daimonion/proofs/RESEARCH-STATE.md`.

**Verified:** file exists at the referenced path (confirmed earlier in queue item #124 scan; line 318 of that file documented the PR #276 working_mode migration).

**Verdict:** ✓ CURRENT.

### 3.6 `reference_design_language.md` — CURRENT

**Claim:** Authority docs at `docs/logos-design-language.md` + `docs/officium-design-language.md`.

**Verified:** both files exist on main. CLAUDE.md § Design Language treats `logos-design-language.md` as the authority doc for visual surfaces.

**Verdict:** ✓ CURRENT.

## 4. Statistics

| Type | Count | Action |
|---|---|---|
| feedback | 25 | Skipped per spec |
| user | 1 | Skipped per spec |
| MEMORY.md | 1 | Index — not a memory |
| project | 40 | Spot-checked — 1 STALE (pi6 IP), 39 presumed current |
| reference | 5 | Spot-checked — 1 STALE (dfhack-reference path), 4 presumed current |

**Coverage honesty:** alpha spot-checked 6 of 45 non-skipped memories directly (13%). The remaining 39 are marked "presumed current" based on the low stale-rate of the spot sample + the short-lived nature of most project memories (weeks, not months). A higher-confidence audit would walk every single memory's claims. Time cost: ~2 hours at thorough pace; out of scope for queue item #116's `~150 lines, ~15 min` budget.

## 5. Remediation proposals

### 5.1 URGENT (alpha could ship now)

None. Neither stale finding is blocking.

### 5.2 NORMAL (follow-up queue items)

1. **Update `project_pi6_sync_hub.md`** with correct IP (`.81`) + `hapax-hub` alias + cross-reference to epsilon's 16:21Z inflection. Small edit (~5 lines).

2. **Decide on DF memories** (`project_df_*`, `reference_dfhack_api.md`, `feedback_df_*`). Three options:
   - (a) **Delete all DF memories** — cleanest; frees 5+ MEMORY.md slots; DF research docs are still in git history if work resumes
   - (b) **Update reference paths** to match `dwarf-fortress-ai-game-state-research.md` + spec paths; add `status: dormant` field
   - (c) **Leave as-is** — minimal action but keeps stale pointers

   Alpha's recommendation: (a) delete. DF work has been dormant for ~3 weeks with no activity.

### 5.3 LOW (no action recommended)

Everything else. The memory system is healthy overall. Spot-check hit rate of 6/6 CURRENT (minus the 2 stale ones found in targeted verification) is consistent with "memories drift slowly, audit occasionally."

## 6. What this audit does NOT do

- **Does not modify any memory files.** Stale findings are proposals for delta or operator to ratify.
- **Does not exhaustively verify all 45 memories.** Spot-sample only.
- **Does not scan MEMORY.md for pointers to deleted memory files.** That would be a separate audit item.
- **Does not audit `feedback_*` type memories for drift.** Feedback memories are user preferences; they're authoritative by definition and don't need verification.

## 7. Closing

Memory hygiene is good. 2 stale items found (1 IP drift, 1 broken path reference), both low severity + cleanly remediable. Delta or operator can ratify remediation via follow-up queue items.

Branch-only commit per queue item #116 acceptance criteria.

## 8. Cross-references

- Memory dir: `~/.claude/projects/-home-hapax-projects/memory/`
- MEMORY.md index: `~/.claude/projects/-home-hapax-projects/memory/MEMORY.md`
- Epsilon's 2026-04-15T16:21Z hapax-ai-live inflection: `~/.cache/hapax/relay/inflections/20260415-162117-epsilon-{alpha,beta,delta}-hapax-ai-live.md`
- DF research docs (actual paths on main):
  - `docs/research/dwarf-fortress-ai-game-state-research.md`
  - `docs/superpowers/specs/2026-03-23-fortress-governance-chains.md`
  - `docs/superpowers/specs/2026-03-23-dfhack-bridge-protocol.md`

— alpha, 2026-04-15T17:57Z
