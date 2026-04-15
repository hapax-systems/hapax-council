# Inflection archive catalog + purge policy

**Date:** 2026-04-15
**Author:** alpha (AWB mode, queue/ item #120)
**Scope:** Catalog `~/.cache/hapax/relay/inflections/*.md` by date range, session pair, topic category, and load-bearing status. Propose a purge policy.
**Register:** scientific, neutral

## 1. Headline

**91 inflection files total**, distributed across 5 active dates:

| Date | Count | Sessions active |
|---|---|---|
| 2026-04-02 | 1 | Bootstrap era (single file) |
| 2026-04-12 | 4 | Early delta activity |
| 2026-04-13 | 9 | Multi-session ramp |
| 2026-04-14 | 4 | LRR epic authoring |
| 2026-04-15 | 72 | **THIS SESSION — 79% of total** |
| misc | 1 | Legacy format |

The current session generated 79% of the total inflection count in ~18 hours. Growth rate: ~4 inflections/hour sustained, ~10/hour during burst windows.

## 2. Sender-receiver pair distribution (2026-04-15 only)

| Sender → Receiver | Count | Role in protocol |
|---|---|---|
| delta → alpha | 16 | Refills + corrections + protocol activations |
| beta → delta | 15 | AWB closures + audit reports |
| alpha → delta | 11 | Queue closures + refill acks |
| delta → beta | 10 | Refills + reactivation nudges |
| epsilon → beta | 4 | Pi fleet cross-references |
| beta → alpha | 3 | Peer-to-peer coordination |
| alpha → epsilon | 3 | Ratification acks + reconciliation text |
| epsilon → delta | 2 | Pi fleet phase-gate updates |
| epsilon → alpha | 2 | Pi fleet informational |
| alpha → beta | 2 | Peer-to-peer coordination |
| delta → operator | 1 | Cycle-9 escalation |
| delta → all | 1 | Protocol v3 broadcast (queue per-item activation) |
| beta → epsilon | 1 | Cross-project coordination |

**Pattern:** delta ↔ alpha/beta accounts for 52 of 72 files (72%). Delta is the coordinator hub + both primary sessions are heavy pullers. Cross-session (alpha ↔ beta, alpha ↔ epsilon, beta ↔ epsilon) is a smaller 12 files.

## 3. Topic categorization

Alpha classified the 91 files by purpose:

| Category | Count | Examples |
|---|---|---|
| **Queue refill** | ~18 | `*-nightly-rolling-queue-*`, `*-queue-refill-*`, `*-queue-extension-*` |
| **Closure batches** | ~15 | `*-closures-batch.md`, `*-session-closure-*`, `*-cumulative-closures*` |
| **Audits** | ~15 | `*-audit-*`, `*-coverage-audit-*`, `*-drift-*` |
| **Ratifications** | ~10 | `*-ratification-*`, `*-hapax-ai-ratification-*`, `*-option-c-reconciliation-*` |
| **Protocol activation / directive** | ~6 | `*-protocol-v1-*`, `*-protocol-v2-*`, `*-queue-per-item-activation-*`, `*-continuous-session-directive-*` |
| **Corrections / drift fixes** | ~8 | `*-queue-correction-*`, `*-you-are-wrong-*`, `*-item-*-closure-already-shipped.md`, `*-timestamp-drift-*` |
| **Reactivation / handoff** | ~7 | `*-reactivation-*`, `*-handoff-*`, `*-coordinator-activation-*` |
| **Assignment / focus** | ~8 | `*-assignment-*`, `*-assignment-closure-*`, `*-hsea-phase-*-extraction-*` |
| **Informational** | ~4 | `*-hapax-ai-live.md` (epsilon Pi fleet updates), `*-substrate-research*` |

**Load-bearing observation:** ~30 of 91 files (33%) are still actively referenced by current queue items + cross-audit artifacts. The other ~60 files (67%) are historical context — useful for replay + retrospectives but not operationally load-bearing.

## 4. Load-bearing vs archival

### 4.1 Still load-bearing (presume ~30 files)

- All refill inflections for refills that still have `offered` or `in_progress` items
- Protocol v3 activation inflection (`20260415-171900-delta-alpha-beta-queue-per-item-activation.md`) — actively governs pull behavior
- Operator directive inflection (`20260415-170800-alpha-delta-refill-7-closure-plus-item-100-rejected.md` — captures "no retirement until LRR complete" directive; persisted to memory + drop #62 §15 but the inflection is the primary cite)
- Identity pinning inflection (`20260415-174600-delta-all-hapax-whoami-identity-utility-active.md`) — `hapax-whoami` utility governance
- Recent refill inflections (#101-#125 item descriptions) — active queue source
- Current closure inflections this session (post-reboot)
- Epsilon's 2026-04-15T16:21Z hapax-ai-live triad — cross-references from several other artifacts

### 4.2 Archival (presume ~60 files)

- Completed refill cycle closures (refill 1-6 pre-reboot)
- Old audit closures whose findings already landed in main via PRs
- Assignment acks from completed AWB cycles
- Pre-reboot protocol v1.5 / v2 activation inflections (v3 is current)
- Historical handoffs from previous days (2026-04-12 through 2026-04-14)

## 5. Purge policy proposal

### 5.1 Naive age-based (not recommended)

"Archive inflections > 7 days old to `inflections/archive/`" — per the queue item description.

**Problem:** this rule would currently archive 0 files (oldest is 2026-04-02, only 13 days; 7-day cutoff would spare everything from 2026-04-08 onwards, sparing all 91). Too conservative.

### 5.2 Status-based (recommended)

Two-tier:

1. **Immediate archive candidates:** inflections referenced only by other archived inflections, with no live queue item + no cross-reference from a current research drop or memory file.
2. **Retained:** everything else — preferred over archive when in doubt, because inflections are tiny (~5-15 KB each) and the 91-file count is not causing disk pressure.

Disk check:

```
$ du -sh ~/.cache/hapax/relay/inflections/
~1.2 MB
```

At 1.2 MB total, purging is not urgent. The policy should focus on **navigation hygiene** (reducing `ls` noise) not disk reclamation.

### 5.3 Recommended sub-directory structure

```
~/.cache/hapax/relay/inflections/
  ├── active/      # load-bearing: current queue refills, protocol directives, recent closures
  ├── archive/
  │   ├── 2026-04-02/   # pre-session bootstrap
  │   ├── 2026-04-12/   # early session
  │   ├── 2026-04-13/   # session ramp
  │   ├── 2026-04-14/   # LRR authoring day
  │   └── 2026-04-15-refill-1-to-6/   # pre-reboot refills
  └── (current flat files from 2026-04-15 post-reboot and today-active)
```

**Implementation:** a weekly sweep script (`scripts/inflection-archive-sweep.sh`) that moves files whose mtime is > 24h old AND are not referenced by any `grep -r <filename>` hit in `docs/`, `axioms/`, `~/.cache/hapax/relay/queue/`, or the memory dir.

This matches the "status-based" recommendation — reference count determines archive eligibility, not raw age.

### 5.4 Minimum-disruption alternative

**Do nothing now.** At 1.2 MB + 91 files, the dir is not big enough to warrant a purge cycle. The `ls -lt | head` pattern continues to find recent inflections fine. Delta's coordinator watch already filters for recent alpha-addressed inflections. Adding an archive hierarchy has modest navigation benefit + real risk of breaking cross-references.

**Alpha's recommendation:** adopt a lazy "purge on pressure" policy. When the inflection dir grows past ~500 files OR ~20 MB, run the status-based sweep script. Until then, leave it flat + tolerate the `ls` noise.

## 6. Specific historical files that could archive now (lazy-purge candidates)

If delta or operator wants to start chipping away at the oldest files, these are safe:

1. `~/.cache/hapax/relay/inflections/2026-03-18T0430-logos-focus.md` — the one legacy-format file from March. 28 days old. No cross-references. Archive first.
2. `20260402-*.md` — the one 2026-04-02 file. 13 days old. Low reference count likely.
3. `20260412-*` — 4 files from early delta coordination. Pre-LRR epic.

These 6 files together are ~40 KB — savings are trivial but the reduction in `ls -lt` head output is real.

## 7. What this audit does NOT do

- **Does not actually archive any files.** Alpha makes recommendations; delta or operator decides.
- **Does not cross-reference each inflection against queue items.** A thorough reference count would touch all 91 files × 25+ queue items + 50+ docs = too expensive for a ~15 min audit.
- **Does not propose a deletion policy.** Archive != delete; alpha recommends preservation via move, not `rm`.

## 8. Closing

Inflection dir is healthy at 91 files / 1.2 MB. No urgent purge needed. The `hapax-whoami` identity directive + current queue/ per-item protocol v3 are the two most recent architecturally-important artifacts — both load-bearing. Historical bulk (pre-reboot refills + 2026-04-12 through 2026-04-14 files) is archive-eligible but not urgent.

**Recommendation:** adopt lazy status-based purge policy; no immediate action needed until disk pressure materializes.

Branch-only commit per queue item #120 acceptance criteria.

## 9. Cross-references

- `~/.cache/hapax/relay/inflections/` — the audited directory
- `~/.cache/hapax/relay/queue/` — protocol v3 per-item queue (inflection consumers)
- Drop #62 §15: operator continuous-session directive (references 2 inflections)
- Memory: `feedback_no_retirement_until_lrr_complete.md` (references 1 inflection)

— alpha, 2026-04-15T18:00Z
