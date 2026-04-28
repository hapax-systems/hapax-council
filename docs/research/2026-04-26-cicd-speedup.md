# CI/CD Speedup Research Drop

**Date:** 2026-04-26
**Author:** alpha (research mode)
**Status:** research-only; implementation downstream
**Scope:** `hapax-council/.github/workflows/ci.yml` — 8 jobs, ~14k tests

## 1. Current Cost Surface

Two recent successful CI runs sampled — `gh run view` data, real wallclock per job (seconds):

| Job | run 24946682707 (push/main) | run 24946573905 (PR) | run 24946518706 (PR) | Notes |
|---|---:|---:|---:|---|
| **test** | **356** | **406** | **390** | xdist `-n 2 --dist loadfile`; 22-min timeout; 26 ignore/deselect lines |
| **typecheck** | **296** | **286** | **286** | pyright basic mode, almost all reports off |
| **homage-visual-regression** | 83 | 97 | 103 | `continue-on-error: true` (informational); duplicates uv sync |
| **lint** | 93 | 85 | 82 | ruff + 6 verifier scripts; no setup-uv cache (regression) |
| **web-build** | 46 | 51 | 44 | pnpm/Vite/Tauri frontend; cache OK |
| **security** | 35 | 32 | 31 | Bandit on bare `setup-python`; pip install bandit each run |
| **vscode-build** | 27 | 26 | 21 | tiny; pnpm cache OK |
| **secrets-scan** | 21 | 18 | 21 | gitleaks `fetch-depth: 0` (full history clone) |
| **PR wallclock** | ~6:00 | ~6:50 | ~6:30 | governed by **test** + **typecheck** + queue time |

### Per-job cost breakdown

**test (356–406s, dominant):**
- system-deps apt-get (cairo, gobject, gst, pango): ~23s
- font install + fc-cache: ~4s
- `setup-uv` w/ cache hit: ~3s
- `uv sync --extra ci`: ~40s (cache HIT — most of this is solving + linking)
- pango font verify: ~2s
- **pytest itself: ~280–325s** (this is the actual reducible cost)

**typecheck (286–296s):**
- system-deps apt: ~23s
- `uv sync --extra ci`: ~38s
- **`pyright` itself: ~225s** (this is the actual cost)

### Cache state

- `astral-sh/setup-uv@v7` cache **hits** (~1MB pruned cache). Pyright cache **not** persisted via `actions/cache`.
- **bug:** the `lint` job uses `astral-sh/setup-uv@v7` WITHOUT `enable-cache: true`. Test/typecheck/homage-vr/web-build all enable-cache; lint does not. Likely a regression — the job now does `uv sync --extra ci` for verifier scripts but installs cold each run. ~10–15s recoverable.
- pyright has a `.pyright/` cache directory that is currently never persisted across runs.

### Scope of the test-job ignore list

26 `--ignore` / `--deselect` lines in ci.yml exclude entire categories: `hapax_daimonion`, `contract`, `frame_gate`, `pipecat_tts`, `perception_integration`, `sensor_tier2_tier3`, `fortress`, demo screencasts/screenshots/video/timeline, visual_regression, follow_mode, face_obscure, camera_pipeline_phase2, captions_in_default_layout, several default-layout tests. These are real cross-cutting bug surfaces being skipped — see §4.

### What's already optimized

- `paths-ignore: docs/**, *.md, lab-journal/**, research/**, axioms/**/*.md` — broad, correct.
- `concurrency.cancel-in-progress: true` — superseded runs are cancelled.
- `pytest -n 2 --dist loadfile` — workers are running.
- `uv sync` cache (where enabled).
- `pnpm` cache via `actions/setup-node` (web-build, vscode-build).
- Tests already run with `-m "not llm"`, `-k "not golden and not goldens"`.

## 2. Top 5 High-Impact Opportunities

Ranked by `(estimated speedup) × (1 / effort)`.

### #1 — Replace pyright with pyrefly in `typecheck`. Est: −230s (−4 min), effort: ~2h.

**Change:** swap `uv run pyright` for `uv run pyrefly check` in `typecheck` job. Add `pyrefly>=0.x` to `[ci]` extras, port `pyrefly.toml` from `pyrightconfig.json` (include/exclude/typeCheckingMode).

**Benchmarks (April 2026):**
- pyright/numpy: 70.9s, 3 GB RAM. pyrefly/numpy: 4.8s, 1 GB RAM. ~15× faster.
- pyright/Django 5.2.1: 16.3s. pyrefly: 911 ms. ~18× faster.
- Pyrefly throughput: 1.85 M LOC/sec; Instagram's 20M-line codebase in ~30s.

**Risk:** pyrefly is at ~90% typing-spec conformance vs pyright's ~99%. With our `pyrightconfig.json` already disabling 12 reports (`reportOptionalMemberAccess`, `reportGeneralTypeIssues`, `reportAttributeAccessIssue`, `reportCallIssue`, `reportArgumentType`, `reportReturnType`, `reportAssignmentType`, etc.), conformance gap is mostly moot — we're using basic mode for import-resolution and undefined-name catches.

**Downside:** pyrefly is younger; edge-case false negatives possible. Mitigation: keep pyright in a low-frequency path-triggered job (e.g., daily cron + on `shared/**` changes).

**Sources:** [Pyrefly speed comparison](https://pyrefly.org/blog/speed-and-memory-comparison/), [Engineering at Meta — Pyrefly intro](https://engineering.fb.com/2025/05/15/developer-tools/introducing-pyrefly-a-new-type-checker-and-ide-experience-for-python/), [Astral ty announcement](https://astral.sh/blog/ty)

**Constitutional fit:** matches `feedback_features_on_by_default` — flip default ON, no shadow mode beyond a sanity-check window.

### #2 — Increase pytest-xdist workers from `-n 2` to `-n 4`. Est: −90s to −150s, effort: ~30m.

**Change:** `-n 2 --dist loadfile` → `-n 4 --dist loadfile` in test job. ubuntu-latest has 4 vCPUs; current `-n 2` leaves 50% of compute idle.

**Verification:** must monitor first 3 PRs after change for OOM/contention. If `MemoryError` or socket-conflict surfaces, fall back to `-n 3`.

**Risk:** /dev/shm and /tmp write-pattern collisions across more workers (the comment in ci.yml at line 149-151 cited 2-worker headroom for "subprocess + system load"). With `--dist loadfile` preserving file-scope serialization, collisions are unlikely but possible in tests using shared paths in `/dev/shm/hapax-*/`.

**Downside:** if a flaky test surfaces (cf. `test_writers_continue_after_rotate` per epsilon's rubric), more workers = more parallel re-trigger surface area.

**Sources:** [pytest-xdist distribution docs](https://pytest-xdist.readthedocs.io/en/latest/distribution.html)

### #3 — Persist pyright/pyrefly cache via `actions/cache`. Est: −60s to −90s, effort: ~30m.

**Change:** add `actions/cache@v4` step in `typecheck` for `~/.cache/pyrefly` (or `.pyright/`) keyed by `${{ hashFiles('pyrightconfig.json', 'pyproject.toml', 'uv.lock') }}`.

Currently each typecheck run re-analyzes everything from scratch; a cache hit would cut analysis to incremental-only changes.

**Risk:** stale cache on dependency-set changes — keyed on lock file mitigates.

**Downside:** marginal; restoring cache costs ~2s.

### #4 — Fix lint-job missing `enable-cache: true` on setup-uv. Est: −10s to −15s, effort: ~5m.

**Change:** ci.yml line 34, add `with: enable-cache: true` to lint's `astral-sh/setup-uv@v7` step.

**Risk:** none. Pure regression fix.

### #5 — Fold `homage-visual-regression` into the `test` matrix or move behind a label gate. Est: −83s wallclock, effort: ~1h.

**Change:** the job is `continue-on-error: true` AND duplicates 23s apt + 40s uv sync of the test job. Two options:
- (a) Drop the standalone job. Make it a `pull_request:` event run only when `paths` includes `tests/studio_compositor/test_visual_regression_homage.py` or `assets/aesthetic-library/**`.
- (b) Run it on a self-hosted runner only (workstation with the operator's font cache — would actually pass).

**Risk:** path-trigger misses indirect changes (new ward → new rendering path). Mitigation: nightly cron on main keeps a cadence.

**Downside:** loses on-PR informational signal. Diff PNGs still uploaded as artifacts; operator can run locally.

## 3. Top 3 Lower-Priority Opportunities

### A — Self-hosted ephemeral runner on the workstation. Est: −2 to −5 min/job, effort: 1–2 days.

Workstation has spare CPU during off-hours; would run actions runner as ephemeral systemd unit in a transient nspawn container. Persistent-bucket cache 10× faster than GHA cache for large repos. **Cost gotcha:** GitHub announced (then postponed) a $0.002/min platform charge for self-hosted minutes from 2026-03-01 — recheck status before committing infrastructure work.

**Sources:** [GitHub Actions 2026 pricing changelog](https://github.blog/changelog/2025-12-16-coming-soon-simpler-pricing-and-a-better-experience-for-github-actions/), [Northflank self-hosted alternatives](https://northflank.com/blog/github-pricing-change-self-hosted-alternatives-github-actions)

### B — Test sharding across 2 matrix shards. Est: −150s, effort: half-day.

Split test job into `test-shard-1` and `test-shard-2` running in parallel via matrix strategy. Use `pytest-split` or simple `--collect-only` partitioning by hash. Doubles runner cost; halves test wallclock.

**Risk:** session-scoped fixtures, shared `/dev/shm` artifacts may break. Effort to triage cross-shard flakes.

### C — `actions/cache@v4` for apt deps. Est: −18s/job × 4 jobs = −72s effort, modest.

Cache `/var/cache/apt/archives/` keyed by the apt list. Mainstream pattern is `awalsh128/cache-apt-pkgs-action`. Each `apt-get install` step costs ~20s and runs in 4 jobs (test, typecheck, lint, homage-vr).

**Note:** marginal because many of these jobs run in parallel — only matters once we've already cut test+typecheck.

## 4. Refused Options (constitutional reasons)

- **pytest-testmon / Test Impact Analysis**: per `feedback_ci_local_parity`, "local pytest pass ≠ CI pass". Subset selection misses cross-cutting bugs. Council's filesystem-as-bus + global state in `shared/` means impact graphs under-estimate the blast radius of any change to `shared/config.py`, `shared/qdrant_schema.py`, or `axioms/`. Reject.
- **Skip-tests-on-paths-ignore for code paths**: same reason. We already use `paths-ignore` for `docs/`, `*.md`, `lab-journal/`. Extending to code paths is unsafe; the reactive engine + axiom system make most "surface" changes ripple.
- **Drop the `homage-visual-regression` informational diffs entirely**: needed for visual triage when the operator iterates wards. Keep behind path-trigger or self-hosted runner — don't drop.
- **Permanent expansion of the 26-item `--ignore`/`--deselect` list**: this list IS the cross-cutting-bug debt — many of those tests fail in CI for environmental reasons (font hinting, missing GPU, etc.). Reducing it is a separate epic, not a CI-speedup tactic.
- **`continue-on-error: true` on more jobs to "make CI faster"**: false economy. Hides regressions. Already justified for homage-vr (env divergence); refuse for anything else.
- **Skip `pyright`/`pyrefly` on PRs with no `.py` changes**: the existing `paths-ignore` already covers docs; further code-path skipping risks `shared/config.py` bypass. Reject.

## 5. Quick Wins (≤1h to implement, ship today)

1. **Add `enable-cache: true` to `lint` job's setup-uv step** (ci.yml line 34). 5 min, 10–15s saved per PR.
2. **Bump test job from `-n 2` to `-n 4`**. 5 min change, 90–150s saved per PR. Monitor 3 runs.
3. **Add `pip cache` to `security` job** so Bandit doesn't re-download every run. 10 min, ~10s saved.
4. **Wire `actions/cache@v4` for `~/.cache/pyrefly`** (or pyright pre-swap). 30 min, 60–90s saved per PR.
5. **Fix `secrets-scan` `fetch-depth: 0` cost** by switching to gitleaks's PR-only mode (`fetch-depth: 1` + `--log-opts="origin/main..HEAD"`). 20 min, ~5–10s saved.

## 6. Implementation Sequencing — 5 PRs

Listed in WSJF order (cost-of-delay ÷ job-size). High WSJF first.

| # | PR | WSJF rationale | Cost-of-delay | Job size | Order |
|---|---|---|---|---|---|
| 1 | **Quick wins bundle** (enable-cache fix + xdist `-n 4` + pip cache + pyright cache + gitleaks fetch-depth) | Hits every PR, low risk, parallel-mergeable | High (saves ~150s/PR × 30+ PRs/week) | 1h | **first** |
| 2 | **Pyrefly swap in `typecheck`** (replace pyright; pyright kept on weekly cron) | Largest single-job speedup; enables more typecheck-blocked deferred work | High (~230s/PR) | 2h | second |
| 3 | **Homage visual-regression path-gate** | Frees a parallel job slot, reduces queue contention | Medium | 1h | third |
| 4 | **apt deps cache via cache-apt-pkgs-action** (test + typecheck + lint + homage-vr) | Compounds with #2 because typecheck no longer needs system deps after pyrefly swap (pyrefly is pure-python) | Medium (~70s wallclock with all 4 jobs in parallel) | half-day | fourth |
| 5 | **Self-hosted ephemeral runner experiment** (one job: test) | High potential 5× speedup but ops cost; recheck GH 2026 pricing first | Medium-low (depends on pricing decision) | 1–2 days | last; gate on GH pricing decision |

After PRs 1+2: PR wallclock target ~2:30–3:00, down from ~6:30. After PR 3: parallel-jobs slot pressure reduced. PR 4 is incremental; PR 5 is contingent.

## 7. 5-line ntfy summary

```
CI/CD speedup research: PR wallclock 6:30 → ~3:00 achievable via 2 PRs.
Top wins: pyrefly replaces pyright (-230s, 15× faster on benchmarks).
Quick: xdist -n 2 → -n 4 (-150s), fix lint missing enable-cache (-15s).
Refused: pytest-testmon + path-skip-on-code (cross-cutting-bug risk per feedback_ci_local_parity).
Sequencing: ship quick-wins bundle today; pyrefly swap next PR; homage path-gate after.
```

## Sources

- [Pyrefly speed and memory comparison](https://pyrefly.org/blog/speed-and-memory-comparison/)
- [Pyrefly typing conformance](https://pyrefly.org/blog/typing-conformance-comparison/)
- [Engineering at Meta — Introducing Pyrefly](https://engineering.fb.com/2025/05/15/developer-tools/introducing-pyrefly-a-new-type-checker-and-ide-experience-for-python/)
- [Edward Li — Pyrefly vs ty](https://blog.edward-li.com/tech/comparing-pyrefly-vs-ty/)
- [InfoWorld — Pyrefly and ty compared](https://www.infoworld.com/article/4005961/pyrefly-and-ty-two-new-rust-powered-python-type-checking-tools-compared.html)
- [Astral — ty announcement](https://astral.sh/blog/ty)
- [Pyrefly conformance deep-dive](https://sinon.github.io/future-python-type-checkers/)
- [pytest-xdist distribution docs](https://pytest-xdist.readthedocs.io/en/latest/distribution.html)
- [pytest-xdist auto worker count issue #553](https://github.com/pytest-dev/pytest-xdist/issues/553)
- [Astral setup-uv action](https://github.com/astral-sh/setup-uv)
- [uv caching docs](https://docs.astral.sh/uv/concepts/cache/)
- [GitHub Actions 2026 pricing changelog](https://github.blog/changelog/2025-12-16-coming-soon-simpler-pricing-and-a-better-experience-for-github-actions/)
- [Northflank — self-hosted alternatives](https://northflank.com/blog/github-pricing-change-self-hosted-alternatives-github-actions)
- [pytest-testmon docs](https://www.testmon.org/)
- [Instawork engineering — testmon TIA](https://engineering.instawork.com/test-impact-analysis-the-secret-to-faster-pytest-runs-e44021306603)

## Related operator memories

- `feedback_ci_local_parity` — Local pytest pass ≠ CI pass; informs the refusal of test-impact analysis.
- `feedback_features_on_by_default` — Pyrefly swap defaults ON, no permanent shadow.
- `project_main_ci_red_20260420` — HOMAGE choreographer tests fail in CI but pass locally; same family as the visual-regression dev-env-pinned divergence noted in §1.
- `feedback_verify_before_claiming_done` — any of these PRs ship with at least 3 verified-green PRs before declaring success.
- `feedback_no_stale_branches` — sequencing one PR at a time per session per the workspace branch discipline.
