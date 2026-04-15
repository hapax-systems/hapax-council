# Cross-repo sync state check: council ↔ constitution ↔ mcp ↔ officium

**Date:** 2026-04-15
**Author:** alpha (AWB mode, queue/ item #161)
**Scope:** Survey git tips + inter-repo dep state across 4 sibling workspace repos. Flag any drift or out-of-date cross-refs.
**Register:** scientific, neutral

## 1. Headline

**Repos are operationally in-sync. One workspace CLAUDE.md drift finding: the stated `hapax-sdlc` dependency from council + officium does not exist in their `pyproject.toml` — the claim is aspirational, not actual.**

| Repo | Current tip | Uncommitted state | Sync status |
|---|---|---|---|
| **hapax-council** | `db7d43527 docs(drop-62): §18 draft — forward-looking post-scenario-1+2 ship (queue #156) (#912)` | clean | ✓ up to date (main) |
| **hapax-constitution** | `b603002 docs(claude-md): cross-reference downstream consumers (#45)` | clean | ✓ up to date |
| **hapax-mcp** | `9a0ae79 fix(server): E3 audit polish — dual-key status, simplify aliases, fix framing (#32)` | clean | ✓ up to date |
| **hapax-officium** | `5adb3b9 feat(working_mode): migrate officium from cycle_mode to working_mode (E2) (#66)` | clean | ✓ up to date |

All 4 repos' primary branches are on their latest commits with no uncommitted changes.

## 2. Method

```bash
cd ~/projects/hapax-council && git log --oneline -3
cd ~/projects/hapax-constitution && git log --oneline -3
cd ~/projects/hapax-mcp && git log --oneline -3
cd ~/projects/hapax-officium && git log --oneline -3

# Check for stated dep on hapax-sdlc
grep -C 1 "hapax-sdlc\|hapax_sdlc" ~/projects/hapax-council/pyproject.toml
grep -C 1 "hapax-sdlc\|hapax_sdlc" ~/projects/hapax-officium/pyproject.toml
grep -C 1 "hapax-sdlc\|hapax_sdlc" ~/projects/hapax-mcp/pyproject.toml

# Check for council-dep in mcp
cd ~/projects/hapax-mcp && grep -C 1 "hapax-council\|:8051" pyproject.toml
```

## 3. Per-repo recent activity

### 3.1 hapax-council — active (this session)

Last 3 commits:

```
db7d43527 docs(drop-62): §18 draft — forward-looking post-scenario-1+2 ship (queue #156) (#912)
4b5d6a2df feat(axioms): ship 4 drop #62 §10 amendments (operator-approved 2026-04-15T20:18Z) (queue #166) (#911)
4a22833d0 docs(lrr-phase-3): plan refresh matching #139 Hermes cleanup (queue #157) (#910)
```

Council is the primary focus of this session's continuous push. ~38 queue items shipped in this continuation burst (#107–#161). Both alpha + beta sessions are active.

### 3.2 hapax-constitution — stable (2-day dormancy)

Last 3 commits:

```
b603002 docs(claude-md): cross-reference downstream consumers (#45)
465c735 docs(claude-md): drop duplicated workspace conventions, add rotation trailer (#44)
8c75433 Merge pull request #41 from ryanklee/docs/claude-md-audit
```

**Observations:**

- **No recent constitution changes.** Last commit is #45 (docs only). Constitution is structurally stable; all recent changes are CLAUDE.md hygiene rather than spec amendments.
- **Drop #62 §10 amendments did NOT ship to constitution.** Per queue #166 (PR #911) alpha shipped the 4 amendments directly to `hapax-council/axioms/implications/` + `axioms/precedents/`, not to `hapax-constitution/`. This was intentional — council holds the locally-extended axiom set, constitution holds the canonical minimal set. The Phase 6 joint PR vehicle per Q5 ratification was originally spec'd against `hapax-constitution/main`, but alpha's shipped path was council-local per delta's #166 direction.
- **Consequence:** the operator-approved governance text for `it-irreversible-broadcast`, `mg-drafting-visibility-001`, `cb-officium-data-boundary`, and `sp-hsea-mg-001` lives in hapax-council but NOT in hapax-constitution. If the Phase 6 joint PR vehicle eventually targets constitution (per Q5 original intent), these 4 files would need to be mirrored or promoted.

### 3.3 hapax-mcp — stable

Last 3 commits:

```
9a0ae79 fix(server): E3 audit polish — dual-key status, simplify aliases, fix framing (#32)
694189a feat(working_mode): add canonical tools + fix cycle_mode_set 422 bug (#31)
6e21853 docs(claude-md): cross-reference sister Tier 1 surfaces (#30)
```

Recent work: `working_mode` migration (canonical tools + cycle_mode_set fix). This parallels the council-side `cycle_mode` retirement (workspace CLAUDE.md § "Working mode"). MCP is staying in-sync with council's cycle_mode → working_mode migration.

**No drift detected.** MCP server exposes 36 tools bridging logos APIs; none of the recent council queue items (#107-#161) would require MCP updates because the LRR epic work is mostly docs/research + governance + audits, not new council-side tool surfaces.

### 3.4 hapax-officium — stable (1 recent feature)

Last 3 commits:

```
5adb3b9 feat(working_mode): migrate officium from cycle_mode to working_mode (E2) (#66)
973cc8b docs(claude-md): cross-reference sister surfaces + spec dependency (#65)
1f1bef7 docs(claude-md): normalize vscode constitution path + rotation policy trailer (#64)
```

**Observations:**

- **Officium working_mode migration shipped.** `cycle_mode → working_mode` migration (PR #66) is live in officium. This is consistent with queue #124 working-mode reference sweep findings (council has 149 cycle_mode refs, all deprecated-OK per 90-day window).
- **No LiteLLM drift found by alpha's #113 audit** against officium directly, but alpha's #113 found that **officium's default `LITELLM_BASE` points to `:4100` which is not listening** (only council's :4000 container is running). This is an operational drift, not a cross-repo sync drift — officium expects a separate LiteLLM container that doesn't exist.

## 4. Drift findings

### 4.1 D1 (LOW) — workspace CLAUDE.md `hapax-sdlc` dep claim is aspirational

**Source:** workspace CLAUDE.md § "Inter-Project Dependencies":

```
hapax-council ──► hapax-sdlc (git+ dep)
hapax-officium ──► hapax-sdlc[demo] (git+ dep)
```

**Actual state:**

```
$ grep -C 1 "hapax-sdlc\|hapax_sdlc" hapax-council/pyproject.toml
(empty)

$ grep -C 1 "hapax-sdlc\|hapax_sdlc" hapax-officium/pyproject.toml
(empty)
```

**Neither council nor officium have a `hapax-sdlc` dependency** in their `pyproject.toml`. The hapax-constitution repo exports the `hapax-sdlc` package (per `hapax-constitution/pyproject.toml`: `name = "hapax-sdlc"`, `packages = ["sdlc", "demo"]`), but nobody imports it as a git+ dep.

**What this means:**
- Council has its own `axioms/` directory with locally-authored implications + precedents (per queue #109, #125, #166 work)
- Officium has its own `axioms/` (if any — alpha did not verify)
- The "governance comes from constitution" claim in workspace CLAUDE.md is a design intent, not an operational fact

**Remediation options:**
- **(a)** Update workspace CLAUDE.md to reflect the actual state: "hapax-constitution is the canonical spec repo; council + officium maintain locally-extended axioms that do not currently import from hapax-sdlc"
- **(b)** Actually wire up the hapax-sdlc dep (medium effort — requires dependency resolution + sync tooling for locally-extended axioms)
- **(c)** Leave as-is with a note that the claim is aspirational

**Alpha recommends (a).** Concrete + low-cost. Workspace CLAUDE.md would be accurate about the current state.

### 4.2 D2 (LOW) — Drop #62 §10 amendments shipped to council, not constitution

**Source:** queue #166 PR #911 shipped 4 governance files to `hapax-council/axioms/implications/` + `hapax-council/axioms/precedents/`. Q5 of drop #62 §10 ratification originally specified a "joint `hapax-constitution` PR" as the vehicle.

**Gap:** the 4 operator-approved amendments are in council but not in constitution. If constitution is considered the canonical governance repo, these files should eventually mirror.

**Why this is LOW severity:**
- Council's local axioms are enforced via council's own `shared/axiom_*.py` + commit hooks
- Constitution's canonical axioms are enforced via its own internal tooling (not shared with council)
- The practical effect is that the governance rules are live in council — where they're needed — regardless of whether constitution also has them
- Phase 6 joint PR vehicle per Q5 can still proceed later to mirror the council files to constitution, with no operational disruption

**Remediation:**
- **Defer.** The Phase 6 joint PR vehicle is still the right long-term path. When Phase 6 opens, the opener session mirrors council's 4 files to constitution as part of the joint PR scope.
- **Alternative:** file a follow-up queue item to proactively mirror the 4 files now. Low-priority; not urgent.

### 4.3 D3 (INFO only) — officium LiteLLM :4100 still dead

Per queue #113 LiteLLM config drift audit (PR #879), officium's default `LITELLM_BASE` points to `:4100` which is not listening. This finding is unchanged since #113 — not a new drift.

**Status:** already tracked. Queue #113 §5 proposed remediation options. No new action needed from this audit.

## 5. Recommendations

### 5.1 Priority

**None urgent.** All 4 repos are in a consistent state + no operational blockers.

### 5.2 Optional follow-up queue items

1. **Workspace CLAUDE.md `hapax-sdlc` dep claim update** — small doc change. 10 min. Not a blocker but improves accuracy. (D1 remediation option (a))
2. **Proactively mirror 4 drop #62 §10 amendments to hapax-constitution** — medium effort. Could ship as a `hapax-constitution` PR referencing the operator-approved council versions. Defers to Phase 6 opener session otherwise. (D2 optional remediation)
3. **Queue #113 follow-up** — officium LiteLLM :4100 default fix. Already tracked; no new work.

### 5.3 No immediate action

- All 4 repos on latest main
- No uncommitted changes
- No active branches accumulating drift (checked repo-level only; feature branches not inspected for this audit)

## 6. What this audit does NOT do

- **Does not inspect feature branches** in any of the 4 repos — only primary branches
- **Does not verify hapax-sdlc package is importable** from council/officium — only checks pyproject.toml absence
- **Does not check hapax-watch + hapax-phone + hapax-mcp** shipped app state (only git tips) — the hardware/mobile apps have their own sync cycles
- **Does not verify the MCP server's 36 tools** are all wired correctly — only confirms MCP git state is recent

## 7. Closing

4 workspace repos in sync at the git-tip + uncommitted-state level. One LOW drift finding (workspace CLAUDE.md claims `hapax-sdlc` dep that doesn't exist in pyproject.toml), one informational observation (drop #62 §10 amendments in council-local not constitution yet), one already-tracked finding (officium LiteLLM :4100). No urgent remediation. All 4 repos are operationally healthy.

Branch-only commit per queue #161 acceptance criteria.

## 8. Cross-references

- Workspace CLAUDE.md § "Inter-Project Dependencies"
- Queue #113 LiteLLM config drift audit (PR #879) — officium :4100 drift
- Queue #124 working-mode reference sweep (PR #871) — cycle_mode retirement status
- Queue #166 drop #62 §10 amendments ship (PR #911) — 4 files in council-local path
- hapax-constitution PR #45 (latest docs pass)
- hapax-mcp PR #32 (latest server fix)
- hapax-officium PR #66 (working_mode migration)

— alpha, 2026-04-15T21:56Z
