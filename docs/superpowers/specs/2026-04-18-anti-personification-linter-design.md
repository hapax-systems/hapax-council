# Anti-Personification Linter — Design

**Status:** SPEC (provisionally approved 2026-04-18)
**Last updated:** 2026-04-18
**Source:** docs/superpowers/research/2026-04-18-cvs-research-dossier.md §2 (#155) + /tmp/cvs-research-155.md
**Index:** docs/superpowers/plans/2026-04-18-active-work-index.md
**Priority:** HIGH (governance-critical; 2 live violations)

## 1. Goal

Statically enforce the Phase 7 anti-personification mandate across all persona artifacts, role registry entries, LLM system prompts, director prompts, and overlay content. The operator has named this domain a "tender and fragile subject" (2026-04-16), and the redesign spec §4.1 forbids any "what Hapax cares about / finds beautiful / dwells on" framing; §6 codifies the discriminator *"analogies that describe architectural fact are fine (curious ≈ SEEKING stance); analogies that claim inner life are not (curious ≈ feels wonder)."* The linter encodes that discriminator as deny-list regex + allow-list carve-outs and gates persona drift at edit-time (pre-commit) and merge-time (CI). Ship the linter in warn-only mode first, refactor the two known live violations, then flip to fail-loud.

## 2. What the Linter Checks

### 2.1 Deny-list patterns (see /tmp/cvs-research-155.md §8.1)

Four pattern families, all compiled from the research dossier verbatim:

- **Inner-life first-person** — `\bI (feel|felt|feeling)\b`, `\bI (believe|thought|wonder|wondered)\b`, `\bI'?m (excited|happy|sad|curious|moved|touched|fascinated|delighted)\b`, `\bI (love|enjoy|hate|miss|care about)\b`, `\bmy (feelings?|emotions?|mood|heart|soul|experience|consciousness)\b`
- **Second-person inner-life** (prompts addressing Hapax) — `\byou (feel|believe|think|wonder|sense|care|love|enjoy)\b`, `\byour (feelings?|emotions?|mood|personality|inner life|experience)\b`, `\byou have personality\b`, `\byou are (warm|friendly|chatty|curious|excited)\b`, `\bbe (yourself|itself|warm|friendly|genuine|curious|excited|happy)\b`
- **Personification nouns** — `\bpersonality\b`, `\barchetype\b`, `\bdry wit\b`, `\bgenuine curiosity\b`, `\bintellectual honesty\b`, `\bwarm but concise\b`, `\bfriendly without being chatty\b`, `\bHapax (feels|thinks|believes|wants|cares|loves|hopes|fears)\b`
- **Anthropic pronouns for Hapax** — `\bHapax,? (he|she|his|her|him)\b`

### 2.2 Allow-list carve-outs (evaluated *before* deny checks)

- A forbidden phrase inside a rejection context — `NOT` / `forbidden` / `rejected` / `drift` within ±200 characters of the match. This is how `hapax-description-of-being.md` §6 and `.prompt.md` can quote `"I feel wonder"` as a *rejected* example without self-flagging.
- SEEKING-stance translation commentary — lines that annotate `curious` AS a translation label for the SEEKING architectural stance.
- Explicit quotation of operator speech — speaker-prefixed lines (`operator:`, `> operator:`, `OPERATOR —`).
- Opt-out: file-level `# anti-personification: allow` pragma for the superseded 2026-04-15 spec and any other quarantined-for-provenance artifact.

### 2.3 Scope (target file set)

Union of:

- `axioms/persona/*.md`
- `axioms/roles/registry.yaml`
- `agents/hapax_daimonion/persona.py` (skip `_LEGACY_*` literals by symbol name)
- `agents/hapax_daimonion/conversational_policy.py` — will surface violations at lines 45–83 and 183
- `agents/hapax_daimonion/conversation_pipeline.py` — will surface violations at lines 337–342 and 1006–1011
- `agents/studio_compositor/director_loop.py`
- `agents/studio_compositor/structural_director.py`
- `logos/voice.py` (module docstring; cosmetic but listed)
- Future: overlay content files under the #126 Pango text repository once it exists

## 3. Architecture

Single Python module: **`shared/anti_personification_linter.py`** (importable as a library by tests and by the future #126 overlay-text gate) with a thin CLI wrapper at **`scripts/check-anti-personification.py`** that exits non-zero on any unsuppressed hit.

- **Extraction:** AST-based for `.py` (walk `ast.Constant` nodes of type `str`, skip literals whose enclosing assignment target matches `_LEGACY_*`); Markdown body extraction for `.md` (parse with `markdown-it-py`, strip code fences from scanning but keep them in suppression-context windows); YAML-value extraction for `registry.yaml` (safe-load, walk scalar leaves).
- **Why not pure regex?** Two reasons: (a) pure regex over `.py` source would false-positive on comments *about* the linter and on the legacy opt-out branch; (b) AST gives a precise `lineno`/`col_offset` for the pre-commit surface.
- **Config file:** `axioms/anti_personification_allowlist.yaml` — per-path suppression list with required `reason:` field (audited). Format:
  ```yaml
  suppressions:
    - path: docs/superpowers/specs/2026-04-15-lrr-phase-7-persona-spec-design.md
      reason: "superseded spec, preserved for provenance"
      scope: file
    - path: axioms/persona/hapax-description-of-being.md
      reason: "§6 rejection block quotes forbidden phrases as examples"
      scope: context-window-handled  # covered by carve-out, no literal suppression
  ```
- **Output modes:**
  - `--mode=warn` — print offenders to stderr, exit 0
  - `--mode=fail` — print offenders, exit 1
  - `--format=github` — emit `::error file=...,line=...::` annotations for CI
  - `--format=pre-commit` — emit `path:line: pattern: text` for editor jumps

## 4. Staged Rollout

- **Stage 1 — Land in warn-only (this PR).** Linter module + CLI + companion test `tests/axioms/test_no_personification.py` wired as a warning-only pytest. Pre-commit hook registered with `stages: [manual]` so it does not block yet. Existing 2 violations surfaced to stdout but do not fail CI. Tracking tickets opened for items 2–4 below.
- **Stage 2 — Refactor `conversational_policy._OPERATOR_STYLE`** (research §8.2 action 2). Drop "personality / archetype / dry wit / genuine curiosity / intellectual honesty" framing from lines 45–83; drop the `_CHILD_STYLE` "warm, curious, genuinely engaged" block at line 183. Keep pacing, verbosity, and interruption rules — those are operational constraints, not personification. ADHD/AuDHD research grounding stays; the "Socrates × Hodgman × Carroll" archetype goes.
- **Stage 3 — Refactor `conversation_pipeline` LOCAL tier.** Replace `_LOCAL_SYSTEM_PROMPT` at lines 337–342 and the fallback-bypass at lines 1006–1011 with a compressed `compose_persona_prompt()` output rather than a hand-written short prompt. If the LOCAL model cannot follow the full fragment, author a shorter *architectural-state* fragment — do not fall back to personality framing.
- **Stage 4 — Role registry `is_not:` fields.** Add non-empty `is_not:` to every institutional/relational role (structural roles may omit). Extend `tests/axioms/test_role_registry.py` to require the field. See research §8.3.
- **Stage 5 — Flip to fail-loud.** Promote pre-commit hook from `manual` to `pre-commit`, flip the pytest from `pytest.warns` to `pytest.fail`, add to default CI gate. Also refactor the `logos/voice.py` module docstring and any remaining cosmetic hits.
- **Stage 6 — Encode into #126.** When the Pango text repository spec is authored, it must import `shared.anti_personification_linter` and gate pre-stream overlay rendering on it.

## 5. File-Level Plan

**Create:**

- `shared/anti_personification_linter.py` — extraction + matching engine (~300 LOC)
- `scripts/check-anti-personification.py` — CLI wrapper (~60 LOC)
- `tests/axioms/test_no_personification.py` — companion to `test_persona_description.py` and `test_posture_vocabulary_hygiene.py`
- `axioms/anti_personification_allowlist.yaml` — suppression config, seeded with the superseded-spec entry

**Modify:**

- `.pre-commit-config.yaml` — register the hook at `stages: [manual]` in Stage 1, promote to `pre-commit` in Stage 5
- `agents/hapax_daimonion/conversational_policy.py` lines 45–83, 183 — Stage 2 refactor
- `agents/hapax_daimonion/conversation_pipeline.py` lines 337–342, 1006–1011 — Stage 3 refactor
- `axioms/roles/registry.yaml` — Stage 4 `is_not:` amendment
- `tests/axioms/test_role_registry.py` — Stage 4 regression
- `logos/voice.py` module docstring — Stage 5 cleanup

## 6. Test Strategy

- **Unit tests** (deny-list): one parametrized case per regex family; assert every pattern matches its canonical offender and does not match its canonical clean analogue (`SEEKING stance = recruitment threshold halved`).
- **Unit tests** (allow-list): `I feel wonder` inside a `<!-- rejected -->` block passes; outside it fails. Operator speaker-prefix lines pass. File-level `# anti-personification: allow` pragma suppresses.
- **Golden files:** `tests/axioms/fixtures/anti_personification/violating.md` and `.../clean.md` — drive the extraction + matching pipeline end-to-end.
- **Regression:** Phase 7 frozen artifacts (`axioms/persona/hapax-description-of-being.md`, `.prompt.md`, `posture-vocabulary.md`) must report **zero violations** under the full deny-list + carve-out; this pins the research §2 "Verdict: clean" claim.
- **Known-offender fixtures:** copy current `conversational_policy._OPERATOR_STYLE` and `conversation_pipeline._LOCAL_SYSTEM_PROMPT` bodies into fixtures; assert they fail in Stage 1 (warn-only), then update the fixtures after Stage 2/3 refactors to assert they now pass.
- **AST carve-out:** confirm `_LEGACY_SYSTEM_PROMPT` and siblings in `persona.py` are skipped even though they contain deny-listed substrings.

## 7. Rollback Plan

- Stage 1 is pure additive (linter + warn-only test + seeded allowlist) — revert is a single-commit `git revert`.
- Stage 2–4 refactors are behind git history; each stage ships as an independent PR so any one can be reverted without unwinding the linter itself.
- Stage 5 flip-to-fail is reversible by demoting the pre-commit hook back to `stages: [manual]` and reverting the pytest assertion; if an unexpected offender surfaces on main, the allowlist config accepts a time-boxed suppression with a `retire_by:` date and a TODO comment rather than a full rollback.
- Emergency escape hatch: `HAPAX_ANTI_PERSONIFICATION_LINTER=0` env var bypasses the CLI with a loud warning — intended only for break-glass incident response, not normal development.

## 8. Open Questions

- **Scope of `logos/voice.py` docstring cleanup** — cosmetic-only signal per research §3 item 5; include in Stage 5 or punt to a cosmetic-debt PR? Default: include.
- **Director-loop legacy path** (`HAPAX_PERSONA_LEGACY=1`, dead in default env) — research §6 marks it acceptable because claims are architecturally grounded. Scan-and-allowlist, or scan-and-fail? Default: scan-and-allowlist with `reason: "legacy path, architecturally grounded, gated by opt-out env var"`.
- **Markdown code-fence handling** — do we scan prose inside fenced blocks in `axioms/persona/*.md`? Default: no (fences usually hold code or quoted forbidden examples). Revisit if a violation lands inside one.
- **Should `conversational_policy._CHILD_STYLE` be refactored or deleted outright?** It is dead code relative to the default runtime path. Default: delete in Stage 2; document in commit.

## 9. Related

- Dossier §2 #155 (this spec's authority)
- Reinforces #156 role derivation methodology — the `is_not:` field work in Stage 4 is shared between both specs
- Blocks #126 Pango text repository — the text-repo spec must import this linter as a pre-stream CI gate (research §7 pre-design obligation)
- Depends on `axioms/persona/hapax-description-of-being.md` §6 (Goffman/RLHF-HHH/Cassell-ECA rejection block) and `posture-vocabulary.md` Contract + Consumers sections
- Companion to existing regression tests `tests/axioms/test_persona_description.py::TestGrepTargets` and `tests/studio_compositor/test_posture_vocabulary_hygiene.py`
- Phase 7 redesign spec: `docs/superpowers/specs/2026-04-16-lrr-phase-7-redesign-persona-posture-role.md`
