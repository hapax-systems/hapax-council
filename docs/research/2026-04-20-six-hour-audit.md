---
date: 2026-04-20
author: alpha (Claude Opus 4.7, 1M context, audit)
audience: operator + next session
register: scientific, neutral, engineering-audit
status: ad-hoc audit — 8 axes across 16 commits in a 6-hour window
window-start: 2026-04-20 04:36:54 -0500
window-end: 2026-04-20 10:36:54 -0500
related:
  - docs/research/2026-04-20-dead-bridge-modules-audit.md (precedent)
  - docs/superpowers/plans/2026-04-20-demonetization-safety-plan.md
  - docs/superpowers/plans/2026-04-20-programme-layer-plan.md
  - docs/research/2026-04-20-mixquality-skeleton-design.md
---

# Six-Hour Audit — main (2026-04-20 04:36 → 10:36 CDT)

## §1. TL;DR

**Volume:** 16 commits on `main` in the audit window. ~2,800 LOC of new
production Python in `shared/governance/`, `shared/`, `shared/mix_quality/`
across 9 new modules + 1 systemd drop-in + 2 PipeWire/audit doc bundles +
6 docs/handoffs.

**Findings by severity:**

| Severity | Count | Distribution |
|---|---|---|
| HIGH | 5 | dead-bridge regression (3), uncommitted Phase 1 work (1), broken doc reference (1) |
| MEDIUM | 11 | concurrency (2), error handling (2), atomic-write gap (1), test gap (1), edge-case (3), spec drift (2) |
| LOW | 9 | naming consistency (2), missed observability (3), dead-code (1), doc-lag (3) |

**Three most-urgent fixes (recommended for immediate action):**

1. **HIGH — Commit or quarantine the in-flight Ring 2 Phase 1 work.**
   `shared/governance/ring2_classifier.py` is modified-not-staged AND
   three new files (`shared/governance/ring2_prompts.py`,
   `scripts/benchmark_ring2.py`, `scripts/generate_ring2_benchmark.py`)
   are untracked. This contradicts the `eb1657358` capstone claim that
   "delta queue is fully closed" and the workspace `feedback_no_stale_branches`
   directive. Either (a) finish Phase 1 and commit, or (b) `git stash` /
   move to a feature branch before next session loss-window.

2. **HIGH — Wire the new governance modules into a caller.** All four
   demonet primitives shipped in this window (`monetization_egress_audit`,
   `quiet_frame`, `music_policy`, `ring2_classifier`) plus
   `programme_store`, `vinyl_chain_verify`, `evil_pet_presets`,
   `mix_quality` have **zero production import sites** outside their
   own tests and docs. Same dead-bridge anti-pattern that
   `docs/research/2026-04-20-dead-bridge-modules-audit.md` (commit
   `3d70dddba`) was supposed to prevent. The `71674c3ef` commit fixed one
   dead bridge (`mental_state_redaction`) but the same session shipped
   eight new ones. Net dead-bridge count went UP this window.

3. **HIGH — Write the missing handoff doc or amend `8816040eb`.**
   The `fix(rag-ingest)` commit message references
   `docs/superpowers/handoff/2026-04-20-delta-to-alpha-rag-ingest-livestream-research.md`
   verbatim, but the file does not exist on `main`. Either create the
   handoff (if delta intended to leave one) or remove the reference
   from any downstream summary that depends on it.

## §2. Methodology

**Audit window:** UTC offset −0500. Commits with `author-date >`
`2026-04-20 04:36:54 -0500` and `<= 2026-04-20 10:36:54 -0500` on `main`.

**Method:**

1. Enumerated commits via `git log --since "6 hours ago" --pretty=format:'%h %ai %s' main`.
2. For each commit: read full message + `git show --stat` to identify
   touched files and zone (governance / audio / programme / docs / fix).
3. For commits referencing a spec or research doc: verified the doc
   exists at the path claimed (`ls docs/...`), then sampled the spec
   to confirm the implementation matches the documented contract.
4. For high-risk commits (any touching audio, governance, mutex,
   gateway, GPU isolation): read the full diff and matching test file.
5. For new modules: ran `Grep` for production import sites to confirm
   the module is actually referenced outside its own tests + docs.
6. Cross-checked working-tree state against the `eb1657358` capstone
   claim of "queue cleared; working tree clean."

**Verification protocol** (per `pr-review-toolkit:review-verification-protocol`):
findings cite SHA + file:line + verbatim quote. Where a finding makes a
claim about absence (e.g., "no production callers"), the supporting
ripgrep search is named in the evidence column.

## §3. Commit Inventory

| SHA | Subject | Author | Files (+/−) | Family | Spec/Plan |
|---|---|---|---|---|---|
| `a45e21207` | docs: WSJF reorganization of delta queue | rylklee | 1 (+359/−0) | docs/handoff | self |
| `0fc9d755d` | docs: delta pre-compaction commitment handoff | rylklee | 1 (+352/−0) | docs/handoff | self |
| `8816040eb` | fix(rag-ingest): GPU-isolate + watch-only | rylklee | 2 (+15/−10) | systemd/fix | workspace CLAUDE.md |
| `a9ede44f9` | feat(demonet): Ring 2 classifier Phase 0 skeleton | rylklee | 2 (+159+142) | demonet | demonet plan §3 |
| `eb1657358` | docs(handoff): delta queue cleared capstone | rylklee | 1 (+237/−0) | docs/handoff | self |
| `a19e8389f` | feat(evil-pet): CC-burst preset pack | rylklee | 2 (+189+220) | evil-pet | evil-pet plan §Phase 4 |
| `b54e6883d` | feat(demonet): classifier fail-closed degradation Phase 4 | rylklee | 2 (+234+190) | demonet | demonet plan §4 |
| `865f296aa` | feat(demonet): quiet-frame programme Phase 11 | rylklee | 2 (+157+136) | demonet | demonet plan §11 |
| `86cef679d` | feat(vinyl): chain verifier composing with audio-topology | rylklee | 2 (+226+~150) | vinyl/audio | vinyl signal-chain research §1–4 |
| `8b1804a3b` | research(audio): LADSPA plugin syntax | rylklee | 2 (+331/−0) | audio/research | self |
| `f893ddfbc` | feat(demonet): music policy Path A + Path B Phase 8 | rylklee | 2 (+195+~150) | demonet | demonet plan §8 + §11 Q1 |
| `023b14c53` | docs(handoff): L6 multitrack retargets runbook | rylklee | 1 (+177/−0) | docs/handoff | self |
| `71674c3ef` | feat(governance): wire mental_state_redaction into Qdrant | rylklee | 2 (+74+177) | governance/wiring | dead-bridge audit |
| `3d1415340` | feat(mix-quality): skeleton aggregate + 6 sub-scores | rylklee | 3 (+396/−0) | mix-quality | mixquality skeleton design §6 |
| `bee082804` | feat(demonet): egress audit JSONL writer Phase 6 | rylklee | 2 (+205+~200) | demonet | demonet plan §6 |
| `1917e939e` | feat(programme): ProgrammePlanStore Phase 2 | rylklee | 2 (+200+~250) | programme | programme-layer plan §Phase 2 |

Author: rylklee (single operator, all commits Co-Authored by Claude Opus 4.7).

Family rollup:
- **demonet**: 5 commits (Phases 4, 6, 8, 11, Ring 2 Phase 0) ≈ 950 LOC prod + 850 LOC tests.
- **programme/governance wiring**: 3 commits (programme_store, mental_state wiring, quiet_frame) ≈ 430 LOC prod.
- **audio/vinyl/mix-quality**: 4 commits ≈ 950 LOC prod + 770 LOC tests + research.
- **evil-pet**: 1 commit ≈ 190 LOC prod.
- **systemd/fix**: 1 commit (rag-ingest GPU isolate) ≈ 15 LOC config.
- **docs/handoff**: 4 commits ≈ 1,125 LOC docs only.

## §4. Spec Compliance (Axis 1: Against Spec)

### 4.1 HIGH

**`a9ede44f9` (Ring 2 Phase 0 skeleton) — incomplete relative to its own spec under same SHA.**

The commit message itemizes Phase 1 todo as deferred:
> "Per-SurfaceKind system prompts per `docs/research/2026-04-19-demonetization-safety-design.md` §6
> benchmarks/demonet-ring2-500.jsonl (operator-labelled),
> scripts/benchmark-ring2-classifier.py,
> Precision target ≥ 0.95 for high-risk class, regression-pinned"

Working-tree shows three uncommitted Phase 1 files matching that list:
- `shared/governance/ring2_prompts.py` (untracked, present)
- `scripts/benchmark_ring2.py` (untracked, present)
- `scripts/generate_ring2_benchmark.py` (untracked, present)

Plus `shared/governance/ring2_classifier.py` is modified-not-staged with
the file header rewritten:
> `+"""Ring 2 pre-render classifier — Phase 1 (#202).`

**Severity:** HIGH. The `eb1657358` capstone claim "delta queue is
fully closed" + "working tree clean — no uncommitted delta code at
disk risk" (from `0fc9d755d` line 74) is contradicted by reality. If
the next session/worktree-cleanup loses these files, ~400 LOC of
Phase 1 work is gone, and the demonet Ring 2 spec stays at the
fail-closed-skeleton state.

**Recommended fix:** Commit Phase 1 to `main` with proper test
coverage OR move the four files to a feature branch + push it before
ending this session. Update `eb1657358` capstone (next handoff doc)
to reflect actual state.

### 4.2 MEDIUM

**`b54e6883d` (Phase 4 fail-closed) — phase ordering inversion vs plan.**

Commit subject: "Phase 4 shipped BEFORE Phase 3 — fail-closed logic is
classifier-independent." Defended in body. Plan
(`docs/superpowers/plans/2026-04-20-demonetization-safety-plan.md` §0)
prescribes a phased sequence; shipping out-of-order is fine *if* the
caller (Phase 3 Ring 2) is already pre-wired to throw the right
exceptions. Phase 0 skeleton (`a9ede44f9`) does throw
`ClassifierBackendDown`, so the contract is intact. **No correctness
defect, but spec narrative drift** — plan should be updated to record
the actual ship order so the next reader doesn't trust §3-then-§4
sequencing.

**`f893ddfbc` (music policy) — operator-gated decision shipped without operator input.**

Commit body acknowledges:
> "Alpha handoff Tier 3 #13 — was operator-gated on §11 Q1 decision.
> Per 'unblock yourself, make the calls' directive, delta picked
> Path A (mute-and-transcript) as the default."

The plan §0.4 names two operator-input gates as "blocking." This commit
unilaterally resolves one. The "unblock yourself" directive is
real, but the plan still says blocking — so plan and code disagree on
who decided. **Severity:** MEDIUM (governance attribution). Update plan
§0.4 to record the delta-decided default.

### 4.3 LOW

**`3d1415340` (mix-quality skeleton) — matches design doc §3 cleanly.**
LOUDNESS_TARGET_LUFS, tolerance, dynamic-range window, six sub-scores,
min() aggregator all match `docs/research/2026-04-20-mixquality-skeleton-design.md`.
No drift. (cite: spec doc §2 table; impl `shared/mix_quality/aggregate.py:25-37`)

**`865f296aa` (quiet-frame) — matches plan §11.** Programme constructed
with `role=AMBIENT`, `monetization_opt_ins=set()`, tier band `(0, 2)`
per plan body. (cite: `shared/governance/quiet_frame.py:75-104`)

## §5. Intent Compliance (Axis 2: Against Stated Intent)

### 5.1 HIGH

**`eb1657358` (capstone "queue cleared") — diff under-delivers vs the body's claims.**

Commit body: "delta queue is fully closed" + the §3 inventory promises
"#202 scope + what's pre-wired + recommended Phase 3 shape + benchmark
path — next delta session picks up with full context." The diff is
237 lines of one new handoff doc only — no commits to verify the
"~200 new tests, all green, 0 reverts" claim in §2 of the doc.
Working tree had Phase 1 code present but uncommitted at the time
this capstone landed (next commit `eb1657358` was 8:02:04, ring2 mod
must have happened after — the modified-but-uncommitted state today
proves the capstone was the last word on disk-tracked work).

**Severity:** HIGH (claim mismatch with reality, plus the
"working tree clean" claim in `0fc9d755d` is also wrong).

### 5.2 MEDIUM

**`8816040eb` (rag-ingest fix) — broken doc reference in commit body.**

Body cites:
> "see docs/superpowers/handoff/2026-04-20-delta-to-alpha-rag-ingest-livestream-research.md"

`ls` confirms file does not exist:
```
$ ls docs/superpowers/handoff/2026-04-20-delta-to-alpha-rag-ingest-livestream-research.md
ls: cannot access ...: No such file or directory
```

Fix itself is sound: `Environment=CUDA_VISIBLE_DEVICES=""` matches the
ollama.service pattern, `--watch-only` ExecStart override removes the
firehose. But the handoff this points to was never written.
**Severity:** MEDIUM. Either write the handoff or remove the reference.

### 5.3 LOW

**`a45e21207` (WSJF reorg) — matches body intent.** WSJF table in the
new doc, all 16 items scored, top-5 in the body match the doc's §1.
No drift. (cite: `docs/superpowers/handoff/2026-04-20-delta-wsjf-reorganization.md`)

**`023b14c53` (L6 retargets runbook) — matches body intent.** Five
retargets enumerated in body match the runbook's §1-§5.

## §6. Cross-Commit Consistency (Axis 3)

### 6.1 MEDIUM

**Naming inconsistency in surface-area public symbols.**

The new governance modules diverge on `default_*` factory naming:
- `shared/programme_store.py:198` — `def default_store() -> ProgrammePlanStore:`
- `shared/governance/monetization_egress_audit.py:201` — `def default_writer() -> MonetizationEgressAudit:`
- `shared/governance/music_policy.py:194` — `def default_policy() -> MusicPolicy:`
- `shared/governance/quiet_frame.py` — no `default_*` factory; uses two top-level activate/deactivate functions instead.

Three modules use a noun (`store`, `writer`, `policy`); the fourth
(`quiet_frame`) uses imperative verbs. Pick one convention. **Recommended:**
add `default_quiet_frame_handle()` or keep all four as imperative
verbs and demote the others to module-level constants. Severity LOW
on its own but compounds across the family.

### 6.2 MEDIUM

**SHM/state path conventions diverge across the family.**

- `programme_store.py:42` — `Path.home() / "hapax-state" / "programmes.jsonl"`
- `monetization_egress_audit.py:47` — `Path.home() / "hapax-state" / "demonet-egress-audit.jsonl"`

Both use `~/hapax-state/`. Good. But the demonet plan §0.1 prescribes
`~/hapax-state/programmes/egress-audit/<date>/<hour>.jsonl`. The
shipped writer uses `~/hapax-state/demonet-egress-audit.jsonl` flat,
not `programmes/egress-audit/...` nested-by-date. **Severity:** MEDIUM
(spec drift; consumers reading per-date dirs will not find files).

### 6.3 LOW

**Test-file location conventions diverge.**

- `tests/governance/test_quiet_frame.py` (governance/)
- `tests/governance/test_classifier_degradation.py` (governance/)
- `tests/governance/test_ring2_classifier.py` (governance/)
- `tests/governance/test_qdrant_gate_read_redaction.py` (governance/)
- `tests/governance/test_music_policy.py` (governance/)
- `tests/governance/test_monetization_egress_audit.py` (governance/)
- `tests/shared/test_programme_store.py` (shared/)
- `tests/shared/test_evil_pet_presets.py` (shared/)
- `tests/shared/test_vinyl_chain_verify.py` (shared/)
- `tests/shared/mix_quality/test_aggregate.py` (shared/mix_quality/)

Mix of `tests/governance/` and `tests/shared/`, with one nested
`tests/shared/mix_quality/`. Programme primitives live in `shared/`
but `programme_store` is in `tests/shared/`, while `quiet_frame`
(which depends on it) is in `tests/governance/`. **Severity:** LOW
(no break, just future grep-for-callers friction).

## §7. Completeness (Axis 4)

### 7.1 HIGH

**Eight modules shipped without production callers.**

`Grep` for production import sites of new modules
(excluding own-test files and docs):

| Module | Import sites outside tests + docs |
|---|---|
| `shared/programme_store.py` | 1 (`shared/governance/quiet_frame.py:53`) — only used by the other new module shipped same window |
| `shared/governance/monetization_egress_audit.py` | **0** |
| `shared/governance/quiet_frame.py` | **0** |
| `shared/governance/music_policy.py` | **0** |
| `shared/governance/ring2_classifier.py` | **0** (called only inside the module's `classify_rendered_payload` helper) |
| `shared/governance/classifier_degradation.py` | 1 (`shared/governance/ring2_classifier.py:19`) — only the new sibling |
| `shared/vinyl_chain_verify.py` | **0** |
| `shared/evil_pet_presets.py` | **0** |
| `shared/mix_quality/aggregate.py` | **0** |

**Severity:** HIGH (8 dead bridges shipped). The `71674c3ef` commit
solved exactly one dead bridge (`mental_state_redaction`) by wiring it
into `ConsentGatedQdrant`; the same session shipped eight new ones.
Net dead-bridge count went UP, contradicting the spirit of the
2026-04-20 dead-bridge audit (`docs/research/2026-04-20-dead-bridge-modules-audit.md`).

**Recommended fix:** Within the next session, wire each module to at
least one production caller:
- `monetization_egress_audit.default_writer().record(...)` → call site in
  `MonetizationRiskGate.assess()` or wherever the gate emits a `RiskAssessment`.
- `quiet_frame.activate_quiet_frame()` → CLI entry in
  `scripts/hapax-quiet-frame` and a programmatic call in the
  pre-monetization-window logic.
- `music_policy.default_policy()` → CPAL audio loop or compositor mute path.
- `vinyl_chain_verify.verify_vinyl_chain()` → `hapax-audio-topology`
  CLI subcommand (`hapax-audio-topology verify --profile vinyl`).
- `evil_pet_presets.recall_preset()` → MIDI dispatch keyboard shortcut
  in studio compositor.
- `mix_quality.aggregate_mix_quality()` → director loop publish step.

### 7.2 MEDIUM

**`bee082804` egress audit ships rotation but no operator timer.**

Body acknowledges:
> "Deferred (operator-owned): systemd timer for daily rotate+prune,
> Grafana dashboard for egress-by-risk-level + block-count + opt-in-acceptance-rate."

Without the timer, `rotate()` + `prune_old_archives()` never fire in
production. The 30-day retention promise in the commit subject is
**not actually enforced** until the operator adds the timer.
**Severity:** MEDIUM. Recommended fix: ship the systemd timer alongside
the writer (~10 LOC) instead of deferring.

### 7.3 LOW

**`a9ede44f9` (Ring 2 Phase 0) — Phase 1 todo list in commit body matches the uncommitted files.** The commit honestly enumerates what's deferred; the deferral becomes a HIGH issue (§4.1) only because Phase 1 was then implemented out-of-tree.

**`3d1415340` (mix-quality) — Phase 1-6 deferral matches §6 of design doc.** Honest.

## §8. Correctness (Axis 5)

### 8.1 MEDIUM

**`bee082804` `_DEFAULT_WRITER` global has TOCTOU race on first call.**

`shared/governance/monetization_egress_audit.py:201-205`:
```python
def default_writer() -> MonetizationEgressAudit:
    global _DEFAULT_WRITER
    if _DEFAULT_WRITER is None:
        _DEFAULT_WRITER = MonetizationEgressAudit()
    return _DEFAULT_WRITER
```

Two threads racing the first call could both pass the `is None` check,
each construct a `MonetizationEgressAudit`, and one of the writers is
GC'd (its `Lock` instance with it). This is benign in CPython under
the GIL because dict mutations are atomic, but the per-instance Lock
is the entire concurrency safety claim. The likelihood is low (only
fires on cold start) but the cost of fixing is one `threading.Lock`
guard. **Severity:** MEDIUM. Fix: wrap the lazy init in a module-level
`Lock`, or use `functools.cache`.

### 8.2 MEDIUM

**`f893ddfbc` `MusicPolicy._path_b_window_opened_at` is unsynchronized mutable state.**

`shared/governance/music_policy.py:117-180` — `MusicPolicy` is a
non-frozen dataclass with mutable `_path_b_window_opened_at: float | None`.
`evaluate()` reads-then-writes it on the Path B branch with no lock.
If two consumers call `evaluate()` concurrently (e.g., director loop +
chronicle loop on the same policy instance), the window state could
race: thread A opens the window, thread B sees the same `None`, both
set it. Not catastrophic (worst case the window is opened twice, both
to roughly the same `ts`), but the operator-`reset_window()` semantic
is also vulnerable to a stale "still open" decision running concurrently
with a reset.

**Severity:** MEDIUM. Either document "single-thread only" in the class
docstring or guard the state with a `threading.Lock`.

### 8.3 MEDIUM

**`1917e939e` `ProgrammePlanStore` mid-write crash leaves `.tmp` orphan.**

`shared/programme_store.py:189-196`:
```python
def _rewrite(self, programmes: list[Programme]) -> None:
    self.path.parent.mkdir(parents=True, exist_ok=True)
    tmp = self.path.with_suffix(self.path.suffix + ".tmp")
    with tmp.open("w") as f:
        for p in programmes:
            f.write(p.model_dump_json() + "\n")
    os.replace(tmp, self.path)
```

`os.replace` is atomic w.r.t. readers (good). But if the process dies
mid-`f.write()` loop, the `.tmp` file is left orphaned. Next call to
`_rewrite` calls `tmp.open("w")` which truncates — so it self-heals on
next write, but there's a window where `programmes.jsonl.tmp` sits as
junk. The test suite verifies "tmp file cleaned up after write"
(commit body bullet 12) — but does not verify cleanup-after-crash
semantics. **Severity:** MEDIUM. Add a startup `_cleanup_tmp()` or
filter `.tmp` files in `all()`.

### 8.4 MEDIUM

**`8816040eb` rag-ingest deleted timer but unit still has `enabled` state on disk.**

Verified post-fact (`systemctl --user list-unit-files | grep rag-ingest`):
```
rag-ingest.service                                    linked    enabled
```

The timer was deleted from the repo but the service unit is still
linked + enabled in the user systemd state. The fix relies on the
service running with the GPU-isolation drop-in — but the operator's
existing systemd state has no enforcement against re-enabling the
deleted timer if a stale link is reintroduced (e.g., from a backup
restore). **Severity:** MEDIUM (low likelihood, but the workspace
CLAUDE.md "Subagent Git Safety" rule about lost work has analogue
here for systemd state diverging from repo). Recommended fix: add a
`scripts/hapax-systemd-reconcile.sh` step that disables timers absent
from `systemd/units/` on the next sync.

### 8.5 LOW

**`71674c3ef` `_redact_points` swallows ALL import errors.**

`agents/_governance/qdrant_gate.py:281-285`:
```python
try:
    from shared.governance.mental_state_redaction import (...)
except Exception:
    log.debug("mental_state_redaction unavailable; skipping redaction", exc_info=True)
    return points
```

Fail-CLOSED would be: raise on import failure (the module is in the
same repo; a missing import is a packaging bug, not a runtime
condition). Current implementation fails-OPEN — operator mental-state
content leaks to public stream if the import fails. The rationale
("import failure must not break reads") prioritizes availability over
governance. **Severity:** LOW (the import is from same repo and
unlikely to fail), but contradicts the dead-bridge audit's spirit of
"correctness-load-bearing read-side gate."

### 8.6 LOW

**`b54e6883d` timeout enforcement is post-hoc, not preemptive.**

`shared/governance/classifier_degradation.py:151-163`:
```python
start = time.monotonic()
assessment = classifier.classify(...)
elapsed = time.monotonic() - start
if elapsed > timeout_s:
    raise ClassifierTimeout(...)
```

The classifier is allowed to run as long as it wants; the timeout is
checked AFTER it returns. A 30-second `classify()` call still blocks
the broadcast loop for 30 seconds before the fail-closed path fires.
The docstring acknowledges "Timeout enforcement is the classifier's
responsibility" but the wrapper's name (`classify_with_fallback`) +
default `DEFAULT_CLASSIFIER_TIMEOUT_S = 2.0` invite the misreading
that the wrapper enforces. **Severity:** LOW (Phase 1 classifier
implementation needs to honor timeout itself; document loudly in the
wrapper's docstring).

## §9. Robustness (Axis 6)

### 9.1 MEDIUM

**`bee082804` `prune_old_archives` is not crash-safe under partial unlink.**

`shared/governance/monetization_egress_audit.py` (prune loop, lines
~165-188): iterates `iterdir()` and calls `unlink()` per match. If the
process dies mid-loop, half the old archives are gone, half remain —
no transactional rollback. For a 30-day retention this is benign (the
remaining files just get deleted next call), but combined with the
no-timer issue (§7.2) and a single ad-hoc operator invocation, a
crash mid-prune is possible. **Severity:** MEDIUM. Recommended fix:
log start/end of prune, or batch-delete via single rm-rf of a temp
quarantine dir.

### 9.2 MEDIUM

**`f893ddfbc` `MusicPolicy.evaluate()` does not handle detector exceptions.**

The detector `Protocol` declares `detect(audio_window) -> MusicDetectionResult`
but raises are not caught. If a real `AcoustIDDetector` (Phase 3) hits
a network error, `evaluate()` raises and the broadcast loop crashes.
The Phase 4 fail-closed pattern in `classifier_degradation.py` exists
exactly for this; the music-policy module should plug into that same
fail-closed wrapper or wrap the detector call in a try/except.
**Severity:** MEDIUM. Recommended fix: wrap `self.detector.detect(audio_window)`
in try/except → `MusicDetectionResult(detected=False, source="error")`
so the loop never crashes on a flaky detector.

### 9.3 LOW

**`86cef679d` `verify_vinyl_chain` substring matching is case-insensitive but doesn't normalize Unicode.**

`shared/vinyl_chain_verify.py:160` substrings are lowercased then
matched against `n.pipewire_name.lower()`. PipeWire names are usually
ASCII but can contain manufacturer Unicode (e.g., the brand "R-with-stroke-de").
Substring "rode" misses that form. **Severity:** LOW (Rode products
in this rig surface as "Wireless" not the umlauted form in pw-cli).
Recommended: `unicodedata.normalize('NFKD', ...)` before lowercasing.

### 9.4 LOW

**`1917e939e` `ProgrammePlanStore.all()` reads full file every call.**

For a session with many `add()` + `activate()` calls, `O(N²)` rewrite cost.
The commit body explicitly defers SQLite migration; for the projected
"tens to hundreds" volume this is fine. But there's no warning emitted
when the file crosses a threshold. **Severity:** LOW. Recommended: log
a `warning` if `self.path.stat().st_size > 1_000_000`.

## §10. Edge Cases (Axis 7)

### 10.1 MEDIUM

**`865f296aa` `activate_quiet_frame` always calls `add()` before `activate()`, including the duplicate-add path.**

`shared/governance/quiet_frame.py:130-145`:
```python
existing = st.get(QUIET_FRAME_PROGRAMME_ID)
programme = build_quiet_frame_programme(...)
if existing is None:
    st.add(programme)
else:
    # Replace the stored record with the freshly-built one
    st.add(programme)
```

Both branches call `st.add(programme)` — the `if/else` is semantically
a no-op. The dedup-by-id behavior in `ProgrammePlanStore.all()`
(last-record-wins) makes this work, but it's confusing. Also the
*store grows monotonically* on every reactivation: each call appends
a JSONL row, never compacts. After 100 quiet-frame activations the
store has 100 quiet-frame rows. **Severity:** MEDIUM. Recommended fix:
collapse to a single `st.add(programme)` and rely on dedup; consider a
`compact()` method on the store or rely on dedup at read time.

### 10.2 MEDIUM

**`a9ede44f9` `classify_rendered_payload` has no `surface=NOTIFICATION` short-circuit.**

The Phase 0 skeleton's `classify_rendered_payload` calls
`classify_with_fallback` for every surface. The uncommitted Phase 1
work (`shared/governance/ring2_classifier.py` modified-not-staged in
working tree) adds the short-circuit:
> "Internal surfaces (CHRONICLE, NOTIFICATION, LOG) — default-pass with
> risk='none' and NO LLM call."

Until Phase 1 commits, every notification call hits the fail-closed
path and returns `allowed=False`. This means **no notifications can
fire while the skeleton is in production**. The honest fail-closed
intent is fine for broadcast; it's spurious for internal surfaces.
**Severity:** MEDIUM. Tied to §4.1 — committing Phase 1 resolves this.

### 10.3 LOW

**`3d1415340` `_loudness_to_band(None)` returns `None` (good); `_loudness_to_band(-15.0)` returns `1.0`; what about `_loudness_to_band(float('nan'))`?**

The function uses `abs(lufs - LOUDNESS_TARGET_LUFS)` which produces
`nan` for `nan` input and then propagates through. The `<=` comparison
with `nan` is False, so it falls through to falloff branch and may
return `nan`. Aggregator's `min()` over `nan` is undefined.
**Severity:** LOW (no caller is going to feed `nan` from a real LUFS
meter). Recommended: `if not math.isfinite(lufs): return None`.

### 10.4 LOW

**`a19e8389f` `recall_preset` cold-start: first MIDI write may fail if engine port not open.**

`shared/evil_pet_presets.py:130-158` (recall_preset): calls `send_cc`
in a loop, "tolerates single failures" per body. But cold-start
scenario (just-plugged Evil Pet, MIDI port not yet enumerated by ALSA)
fails ALL CCs in the burst → preset never lands. Body says "tolerates
single failures" — for cold-start it's not "single," it's "all."
**Severity:** LOW (operator notices when their preset doesn't recall).
Recommended: optional `verify_port=True` flag that pings the port
before issuing the burst.

## §11. Missed Opportunities (Axis 8)

### 11.1 MEDIUM

**Zero Prometheus metrics across 8 new governance modules.**

None of the modules (`monetization_egress_audit`, `quiet_frame`,
`music_policy`, `ring2_classifier`, `classifier_degradation`,
`programme_store`, `vinyl_chain_verify`, `mix_quality`) export a
single Prometheus counter. The council CLAUDE.md `## Bayesian Presence
Detection` section documents the workspace's investment in
observability (metrics on `127.0.0.1:9482` etc.); these new modules
ship blind. Operator can't see in Grafana:

- Egress audit lines/sec
- Quiet-frame activation count
- Music-policy mute decisions
- Ring 2 classifier latency / fail-closed rate / fail-open rate
- Programme store size

**Severity:** MEDIUM (debug-time-cost). Recommended: add at minimum
`hapax_demonet_egress_records_total{risk,allowed}`,
`hapax_classifier_unavailable_total{reason}`, and
`hapax_programme_store_active_count` in the next session.

### 11.2 MEDIUM

**`8816040eb` (rag-ingest fix) — same file references CLAUDE.md but the workspace CLAUDE.md hasn't been updated.**

The fix message correctly cites:
> "matching the ollama.service GPU-isolation pattern (workspace CLAUDE.md
> § Shared Infrastructure — TabbyAPI exclusively owns the GPU)."

But the workspace CLAUDE.md doesn't yet add `rag-ingest` to the
GPU-isolated list (which currently enumerates only ollama). When the
operator next reads the doc they won't know rag-ingest is also
CPU-only. **Severity:** MEDIUM. Recommended: add a one-line bullet to
the workspace CLAUDE.md `Shared Infrastructure` section.

### 11.3 LOW

**`a19e8389f` (evil-pet presets) — `_BASE_SCENE` is a copy of `scripts/evil-pet-configure-base.py §3.8`.**

The values are duplicated in two places (the script and the new
module). If the operator tunes the base scene in the script, the
preset pack drifts. Recommended: extract `BASE_SCENE_CCS` to a
constant in `shared/evil_pet_presets.py` and have the script import
it. **Severity:** LOW.

### 11.4 LOW

**`86cef679d` (vinyl_chain_verify) — could compose into `hapax-audio-topology verify` subcommand same window.**

The new module adds `verify_vinyl_chain()` and `format_report()`. The
existing `hapax-audio-topology` CLI (council CLAUDE.md `## Audio
Topology`) already has a `verify` subcommand. A 5-line addition would
expose `verify --profile vinyl` to the operator without a separate
script. The commit body says "Operator applies remediation via the L6
retargets runbook (#210)" but there's no operator-facing entry point
for the verify itself. **Severity:** LOW.

### 11.5 LOW

**`b54e6883d` `classify_with_fallback` lacks an egress audit hook.**

The fail-closed and fail-open branches both build a `RiskAssessment`
but neither calls `MonetizationEgressAudit.record()` (which shipped in
the same window, `bee082804`). A natural composition: every fail-closed
event becomes a `classifier_unavailable` egress record. **Severity:**
LOW. Recommended: optional `audit_writer: MonetizationEgressAudit | None`
parameter on `classify_with_fallback`.

### 11.6 LOW

**Eight new tests files but zero hypothesis-driven tests.**

Council CLAUDE.md `## Council-Specific Conventions` notes "Hypothesis
for property-based algebraic proofs." All 134 new tests this window
use plain `pytest` parametrize. Modules like `aggregate_mix_quality`
(deterministic algebraic over `min`-of-floats) and `_parse_verdict`
(JSON-shape parser) are exactly the property-based-testing sweet
spot. **Severity:** LOW.

## §12. Cross-Cutting Patterns

### 12.1 The "skeleton-then-defer" anti-pattern

5 of the 11 feature commits (`a9ede44f9` Ring 2 Phase 0, `b54e6883d`
Phase 4-before-3, `865f296aa` quiet-frame Phase 11, `f893ddfbc` music
policy Phase 8 with NullDetector, `3d1415340` mix-quality Phase 0)
ship a skeleton with a deferral list pointing at later phases. The
pattern is intentional and defended in commit bodies. The dead-bridge
finding (§7.1) is the consequence: skeletons that never get a caller
because the next phase doesn't materialize on schedule.

**Pattern fix:** Each "skeleton" PR should include at minimum one
production caller (even if guarded by an env flag) so the import-graph
edge exists. A skeleton without a caller is indistinguishable from a
dead-bridge module.

### 12.2 Stateful dataclasses without locks

`MusicPolicy` (§8.2) and `MonetizationEgressAudit._DEFAULT_WRITER`
(§8.1) both mutate state without explicit lock contracts. The dataclass
shorthand makes it easy to forget that the instance has lifecycle.
Recommended: where mutation lives in a dataclass field, document
"single-thread caller" or add a `_lock: Lock = field(default_factory=Lock)`
slot.

### 12.3 Atomic-rename usage is correct everywhere it appears

`programme_store._rewrite` uses `os.replace`, `monetization_egress_audit`
uses appending writes under a lock (line-atomic), `gpu-isolate.conf`
uses systemd's drop-in-dir mechanism (atomic). No instances found of
non-atomic write semantics where atomic was needed. **Good.**

### 12.4 Spec/research/handoff doc count vs production wiring

Of 16 commits: 4 are pure docs (`a45e21207`, `0fc9d755d`, `eb1657358`,
`023b14c53` — all handoff/runbook), 1 is research+config (`8b1804a3b`
LADSPA syntax). Pure-docs commits are 25% of the window's commit
count. None of the documented workflows have an operator entry point
(no new CLI script, no new MCP tool, no new keyboard binding). The
pattern from the workspace `feedback_workflow_autonomy_concision`
memory ("drop preamble, single-focus research") is at risk of
inverting: more docs about future work than wired work itself.

### 12.5 `Co-Authored-By` consistency

All 16 commits include `Co-Authored-By: Claude Opus 4.7 (1M context)`
trailer. Consistent. **Good.**

## §13. Recommended Remediation Queue

Prioritized for next-session pickup. Each item independently
shippable; no cross-dependencies except where noted.

| # | Severity | Effort | Action |
|---|---|---|---|
| 1 | HIGH | S (5min) | Run `git status` + `git diff`; either commit Phase 1 ring2 work to `main` OR move to `phase-1-ring2-prompts` branch + push (resolve §4.1). |
| 2 | HIGH | M (60min) | Wire `MonetizationEgressAudit.default_writer().record(...)` into `MonetizationRiskGate.assess()` in `shared/governance/monetization_safety.py` (resolve §7.1 partially). |
| 3 | HIGH | S (15min) | Either write the missing rag-ingest handoff doc or amend the next handoff to remove the dangling reference (resolve §5.2). |
| 4 | HIGH | M (45min) | Add `scripts/hapax-quiet-frame` CLI exposing `activate_quiet_frame` + `deactivate_quiet_frame` (resolve §7.1 for quiet_frame). |
| 5 | HIGH | M (45min) | Add `hapax-audio-topology verify --profile vinyl` subcommand wrapping `vinyl_chain_verify.verify_vinyl_chain` (resolve §7.1 + §11.4). |
| 6 | MEDIUM | S (10min) | Wrap `_DEFAULT_WRITER` lazy-init in module-level Lock (resolve §8.1). |
| 7 | MEDIUM | S (10min) | Add `threading.Lock` field to `MusicPolicy` OR document "single-thread caller" in the docstring (resolve §8.2). |
| 8 | MEDIUM | S (15min) | Add `_cleanup_tmp()` startup hook to `ProgrammePlanStore` (resolve §8.3). |
| 9 | MEDIUM | M (30min) | Ship the systemd timer for `monetization_egress_audit` daily rotate+prune (resolve §7.2). |
| 10 | MEDIUM | S (15min) | Wrap `MusicPolicy.evaluate()` detector call in try/except (resolve §9.2). |
| 11 | MEDIUM | S (10min) | Update workspace CLAUDE.md `Shared Infrastructure` to add rag-ingest to GPU-isolated list (resolve §11.2). |
| 12 | MEDIUM | M (30min) | Reconcile demonet plan §0.1 path (`programmes/egress-audit/<date>/<hour>.jsonl`) vs shipped flat path (resolve §6.2). Either update the impl OR the spec. |
| 13 | MEDIUM | S (15min) | Update demonet plan §0.4 to record delta-decided Path A default (resolve §4.2 / §5.2 attribution). |
| 14 | MEDIUM | M (30min) | Add `surface=NOTIFICATION` short-circuit to `classify_rendered_payload` (resolve §10.2). Subsumed by item 1 if Phase 1 commits. |
| 15 | LOW | S (10min) | Promote import failure in `_redact_points` from log+continue to raise (resolve §8.5). Operator-decided. |
| 16 | LOW | M (60min) | Add `hapax_demonet_*` Prometheus counters across new modules (resolve §11.1). |

## §14. Sources

**Commit SHAs (chronological):** `1917e939e`, `bee082804`, `3d1415340`,
`71674c3ef`, `023b14c53`, `f893ddfbc`, `8b1804a3b`, `86cef679d`,
`865f296aa`, `b54e6883d`, `a19e8389f`, `eb1657358`, `a9ede44f9`,
`8816040eb`, `0fc9d755d`, `a45e21207`.

**Files cited (repo-relative paths from hapax-council root):**

- `shared/governance/ring2_classifier.py:1` (Phase 1 header drift, modified-not-staged)
- `shared/governance/ring2_prompts.py` (untracked)
- `scripts/benchmark_ring2.py` (untracked)
- `scripts/generate_ring2_benchmark.py` (untracked)
- `shared/governance/classifier_degradation.py:151-163` (post-hoc timeout)
- `shared/governance/monetization_egress_audit.py:201-205` (TOCTOU)
- `shared/governance/monetization_egress_audit.py:47` (path differs from plan §0.1)
- `shared/governance/music_policy.py:117-180` (unsynchronized state)
- `shared/governance/music_policy.py:194` (default_policy naming)
- `shared/governance/quiet_frame.py:53` (only consumer of programme_store)
- `shared/governance/quiet_frame.py:130-145` (no-op if/else)
- `shared/programme_store.py:42` (DEFAULT_STORE_PATH)
- `shared/programme_store.py:189-196` (atomic-write window)
- `shared/programme_store.py:198` (default_store naming)
- `shared/vinyl_chain_verify.py:160` (substring matching)
- `shared/evil_pet_presets.py:130-158` (recall_preset cold-start)
- `shared/mix_quality/aggregate.py:25-37` (pass-band constants vs design doc)
- `agents/_governance/qdrant_gate.py:281-285` (_redact_points fails-OPEN on import failure)
- `systemd/overrides/rag-ingest.service.d/gpu-isolate.conf` (GPU isolation drop-in)
- `docs/superpowers/handoff/2026-04-20-delta-to-alpha-rag-ingest-livestream-research.md` (REFERENCED, NOT FOUND)
- `docs/superpowers/plans/2026-04-20-demonetization-safety-plan.md:60` (path prescription)
- `docs/superpowers/plans/2026-04-20-demonetization-safety-plan.md:100` (operator-input gates)
- `docs/research/2026-04-20-mixquality-skeleton-design.md` (verified §3, §4, §6)
- `docs/research/2026-04-20-vinyl-broadcast-signal-chain-topology.md` (verified §1-§4)
- `docs/research/2026-04-20-dead-bridge-modules-audit.md` (precedent for §7.1)
- `CLAUDE.md` (council; Shared Infrastructure section, GPU isolation pattern)
- workspace `CLAUDE.md` (workspace; Shared Infrastructure list missing rag-ingest)

**Verification searches performed:**

- `git log --since "6 hours ago" --pretty=format:'%h %ai %s' main` — commit enumeration
- `git show --stat <sha>` for each of the 16 SHAs
- `git status` + `git diff HEAD -- shared/governance/ring2_classifier.py` — uncommitted state
- `Grep monetization_egress_audit|MonetizationEgressAudit` — caller absence (zero outside tests/docs)
- `Grep programme_store|ProgrammePlanStore` — caller absence (only quiet_frame)
- `Grep music_policy|MusicPolicy|MusicDetector` — caller absence
- `Grep vinyl_chain_verify|verify_vinyl_chain` — caller absence
- `Grep ring2_classifier|Ring2Classifier|classify_rendered_payload` — caller absence
- `Grep quiet_frame|QUIET_FRAME|activate_quiet_frame` — caller absence
- `Grep evil_pet_presets|recall_preset|EvilPetPreset` — caller absence
- `ls docs/superpowers/handoff/2026-04-20-delta-to-alpha-rag-ingest-livestream-research.md` — confirmed missing
- `systemctl --user list-unit-files | grep rag-ingest` — confirmed unit still enabled

End of audit.
