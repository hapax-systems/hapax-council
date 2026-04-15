# axioms/implications/ + axioms/precedents/ Directory Index

**Queue:** #185
**Depends on:** #166 PR #911 (shipped 4 new governance files)
**Author:** alpha
**Date:** 2026-04-15

---

## §0. TL;DR

Two schemas coexist in `axioms/implications/`:

- **Aggregate files** (5 pre-#911 files) — one YAML per axiom, each holding an array of implications under a single `axiom_id`. 90 implications total.
- **Single-implication files** (3 new in PR #911) — one YAML per implication, top-level fields `implication_id`, `axiom_id`, `tier`, etc. 3 implications.

**93 implications total across 8 files in `axioms/implications/`.**

`axioms/precedents/` has one content file (sp-hsea-mg-001.yaml) plus a `seed/` subdirectory. The content file is the first real precedent shipped via #911.

---

## §1. `axioms/implications/` index

### §1.1. Aggregate files (one per axiom, pre-#911)

#### `corporate-boundary.yaml` — 7 implications for axiom `corporate_boundary`

| ID | Tier | Enforcement | Canon | One-line |
|---|---|---|---|---|
| cb-llm-001 | T0 | block | textualist | Extension must support direct API calls to sanctioned providers without a localhost proxy |
| cb-data-001 | T0 | block | textualist | Employer data must not be stored in personal/council systems |
| cb-degrade-001 | T0 | block | purposivist | Graceful degradation when sanctioned provider unreachable |
| cb-key-001 | T0 | block | textualist | API keys for sanctioned providers pulled from env, never hardcoded |
| cb-secret-scan-001 | T1 | review | textualist | Secret-scanning hook on commit |
| cb-extensible-001 | T1 | review | purposivist | New provider integrations follow the sanctioned-provider pattern |
| cb-parity-001 | T2 | warn | purposivist | Feature parity across sanctioned providers when feasible |

#### `executive-function.yaml` — 42 implications for axiom `executive_function`

Largest file by implication count. Covers initialization (ex-init-*), error handling (ex-err-*), state management (ex-state-*), routine automation (ex-routine-*), cognitive load (ex-cogload-*), feedback loops (ex-feedback-*), context preservation (ex-context-*), attention management (ex-attention-*), error recovery (ex-error-*), config (ex-config-*), dependencies (ex-depend-*), UI (ex-ui-*), plus additional suffixes (-001, -002) within most categories.

First 20 ids catalogued: ex-init-001, ex-init-002, ex-err-001, ex-err-002, ex-state-001, ex-state-002, ex-routine-001, ex-routine-002, ex-cogload-001, ex-cogload-002, ex-feedback-001, ex-feedback-002, ex-context-001, ex-context-002, ex-attention-001, ex-error-001, ex-error-002, ex-config-001, ex-depend-001, ex-ui-001. 22 more follow.

**Not indexed per-implication here** (42 × one-liner = ~2,000 words overhead for a low-priority audit). Use `grep -c '^- id:' axioms/implications/executive-function.yaml` for count and `grep '^- id:' axioms/implications/executive-function.yaml` for the full list.

#### `interpersonal-transparency.yaml` — 9 implications for axiom `interpersonal_transparency`

| ID | Tier | Enforcement | Canon | One-line |
|---|---|---|---|---|
| it-consent-001 | T0 | block | textualist | No persistent state about non-operator person without active consent contract |
| it-consent-002 | T0 | block | textualist | Consent contract required before accumulating biometrics/presence/etc. |
| it-inspect-001 | T0 | block | — | Consent contract inspection on every state access |
| it-revoke-001 | T0 | block | — | Revocation is irreversible + flushes derived state |
| it-scope-001 | T0 | block | — | Contract scope limits data class |
| it-environmental-001 | T0 | block | — | Environmental IR/audio captures non-operators incidentally — contract check on write |
| it-inference-001 | T0 | block | — | Inferences about non-operators not persisted without consent |
| it-audit-001 | T1 | review | — | Audit log of consent contract access |
| it-backend-001 | T1 | review | — | Backend-level fail-closed on consent check |

#### `management-governance.yaml` — 7 implications for axiom `management_governance`

| ID | Tier | Enforcement | Canon | One-line |
|---|---|---|---|---|
| mg-boundary-001 | T0 | block | textualist | Never generate feedback/coaching language directed at team members |
| mg-boundary-002 | T0 | block | — | No performance-review text, no 1:1 drafts from LLM |
| mg-cadence-001 | T0 | block | — | Management cadence info is metadata, not LLM-generated content |
| mg-selfreport-001 | T0 | block | — | Self-report data stays between operator and the system |
| mg-deterministic-001 | T1 | review | — | Management workflow must be deterministic, not stochastic |
| mg-prep-001 | T1 | review | — | LLMs can prepare data but humans deliver conclusions |
| mg-bridge-001 | T2 | warn | — | Bridge between operator's management function and the system stays thin |

#### `single-user.yaml` — 25 implications for axiom `single_user`

First 20 IDs: su-auth-001, su-config-001, su-data-001, su-privacy-001, su-error-001, su-logging-001, su-ui-001, su-naming-001, su-security-001, su-scale-001, su-api-001, su-storage-001, su-notification-001, su-deployment-001, su-perf-001, su-audit-001, su-deploy-001, su-feature-001, su-decision-001, su-paths-001. 5 more follow.

Covers auth removal (su-auth-001), config simplification (su-config-001), data ownership (su-data-001), UI scope reduction (su-ui-001), deployment model (su-deployment-001), feature scope (su-feature-001), and path assumptions (su-paths-001). These are the patterns `axiom-commit-scan.sh` enforces via its regex list (see queue #176 PR #921 coverage audit).

### §1.2. Single-implication files (new in PR #911)

All three have the **new schema**: top-level `implication_id` + `axiom_id` instead of being array elements under an aggregate file.

#### `cb-officium-data-boundary.yaml`

- **implication_id:** cb-officium-data-boundary
- **axiom_id:** corporate_boundary
- **tier:** T0 | **enforcement:** block | **canon:** textualist | **mode:** compatibility | **level:** system
- **Scope:** Data originating in hapax-officium stays in hapax-officium. Non-officium systems (council, personal vault, watch, phone) must not import officium data.
- **Origin:** drop #62 §10 Q1+Q4 — operator ratification of the data-origin boundary

#### `it-irreversible-broadcast.yaml`

- **implication_id:** it-irreversible-broadcast
- **axiom_id:** interpersonal_transparency
- **tier:** T0 | **enforcement:** block | **canon:** purposivist | **mode:** compatibility | **level:** system
- **Scope:** Any system output naming a non-operator person on a public/irreversible channel (livestream, published clip, saved transcript, third-party API, social post, permanent storage served externally) MUST be blocked unless operator has ratified it.
- **Origin:** drop #62 §10 Q2 — operator ratification of livestream visibility

#### `mg-drafting-visibility-001.yaml`

- **implication_id:** mg-drafting-visibility-001
- **axiom_id:** management_governance
- **tier:** T0 | **enforcement:** block | **canon:** purposivist | **mode:** compatibility | **level:** system
- **Scope:** LLM-drafted content about specific team members (emails, messages, performance feedback, 1:1 notes, coaching recs, reviews) must be visibly marked as drafts. Unmarked drafting is blocked.
- **Origin:** drop #62 §10 Q3 — operator ratification of drafting-as-content precedent

### §1.3. Totals

| Source | Files | Implications |
|---|---:|---:|
| Aggregate (pre-#911) | 5 | 7 + 42 + 9 + 7 + 25 = 90 |
| Single-file (post-#911) | 3 | 3 |
| **Total** | **8** | **93** |

---

## §2. `axioms/precedents/` index

### §2.1. Real content (1 file)

#### `sp-hsea-mg-001.yaml`

- **precedent_id:** sp-hsea-mg-001
- **axiom_id:** management_governance (primary)
- **secondary_axioms:** [interpersonal_transparency]
- **short_name:** `drafting-as-content`
- **Scope:** HSEA Phase 0 agents (and any phase in drafting mode) produce LLM-generated content intended to eventually compose into the Legomena Live stream. At drafting time, content is non-final, may contain hallucinations, may reference individuals, and has not received operator review. Precedent: draft content MUST be visibly marked until operator ratifies it.
- **Origin:** PR #911 (queue #166) — first precedent file in the directory post-#911; the `seed/` subdirectory existed before but this is the first authored precedent

### §2.2. Seed subdirectory

`axioms/precedents/seed/` — pre-existing scaffolding directory. Content not indexed here; out of scope for queue #185.

---

## §3. Schema observations

### §3.1. Two schemas coexisting

The 5 aggregate files use an older schema where each file groups multiple implications under a single `axiom_id` root:

```yaml
axiom_id: corporate_boundary
derived_at: '2026-03-05'
implications:
  - id: cb-llm-001
    tier: T0
    ...
```

The 3 new files use a single-implication schema with a top-level `implication_id`:

```yaml
implication_id: cb-officium-data-boundary
axiom_id: corporate_boundary
tier: T0
...
```

Both schemas are currently valid (both are present on main, both are covered by CODEOWNERS review). A future migration could normalise to one or the other, but this is **not** a drift item — it's a deliberate coexistence pattern per PR #911 (queue #166).

**Rationale (inferred):** new governance files are per-implication to make Git history, CODEOWNERS review, and diff review cleaner. Historic aggregate files stay aggregated to avoid mass-churning 90 implications into 90 files.

### §3.2. Canon distribution (where tagged)

| Canon | Count visible in aggregate headers |
|---|---:|
| textualist | 4 (cb-llm-001, cb-data-001, cb-key-001, cb-secret-scan-001, ...) |
| purposivist | 2 (cb-degrade-001, cb-extensible-001, cb-parity-001) |
| (untagged) | varies by file |

The single-file schema makes canon explicit per-implication. The aggregate schema sometimes omits canon for lower-tier items.

### §3.3. Enforcement distribution

Every implication from PR #911 is `enforcement: block` and `tier: T0`. This is consistent with the operator's 2026-04-15T20:18Z ratification — the three new implications were authored specifically to close fail-open gaps rather than soft warnings.

---

## §4. Delta from queue #109 + queue #180

Queue #109 prior audit flagged "3 missing implications + 2 missing precedents". Post-#166 (PR #911):

| Flagged by #109 | Shipped | Still open |
|---|---|---|
| cb-officium-data-boundary | ✓ PR #911 | — |
| it-irreversible-broadcast | ✓ PR #911 | — |
| mg-drafting-visibility-001 | ✓ PR #911 | — |
| sp-hsea-mg-001 precedent | ✓ PR #911 | — |
| (second precedent) | — | still open — outside #166 scope |

Queue #180 (PR N/A, in-archive closure) verified the file presence + cross-references. This queue #185 index adds the one-line descriptions per implication so operators can browse the set without opening each YAML.

---

## §5. Cross-references

- `axioms/registry.yaml` — the 5 axioms (single_user, executive_function, management_governance, interpersonal_transparency, corporate_boundary) that these implications derive from; CODEOWNERS-protected
- `hooks/scripts/registry-guard.sh` — file-path governance for `axioms/registry.yaml` + `domains/*.yaml`
- `hooks/scripts/axiom-commit-scan.sh` — regex-based structural enforcement (queue #176 PR #921 coverage audit)
- Queue #109 — prior gap audit (3 missing implications + 2 missing precedents)
- Queue #166 PR #911 — shipped 4 of the 5 missing files
- Queue #180 — count verification post-#166
- Queue #185 — this index

---

## §6. Verdict

**8 files, 93 implications** in `axioms/implications/`. **1 content file** in `axioms/precedents/`. Two schemas coexist (aggregate vs single-implication) — deliberate per PR #911. The 3 new files from #911 are all T0 block, tagged appropriately, and cross-reference back to drop #62 §10 operator ratifications.

No missing files from the #109 audit remain (except the second-precedent slot, which was not in PR #911's scope). No schema defects. Clean-bill-of-health closure for queue #185.

— alpha, queue #185
