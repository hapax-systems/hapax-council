# CI/CD Speedup PR3-5 Priorities

**Date:** 2026-04-26
**Author:** alpha (research mode)
**Status:** research-only; beta dispatches in priority order
**Predecessor:** `docs/research/2026-04-26-cicd-speedup.md`
**Baseline:** post-PR1 (#1515) + PR2 (#1519) — `test=225s`, `typecheck=83s`, `secrets-scan=6s`

## 1. WSJF per PR

WSJF = (Business-Value + Time-Criticality + Risk-Reduction) / Job-Size. All axes 1-10. Job-size in days (rounded).

**Dimensions:**
- **Business-value**: per-PR wallclock saved + parallel-slot pressure relieved + queue-noise reduction.
- **Time-criticality**: how much delay erodes the value (e.g., gating on external pricing).
- **Risk-reduction**: chance of catching/preventing a regression or operational cost trap.
- **Job-size**: implementation + verify days; smaller is better.

| PR | BV | TC | RR | Size (d) | WSJF |
|---|---:|---:|---:|---:|---:|
| **PR3 — homage-vr path-gate** | 3 | 2 | 4 | 0.13 (~1h) | **69** |
| **PR4 — apt deps cache (3 jobs)** | 2 | 1 | 1 | 0.5 | **8** |
| **PR5 — self-hosted ephemeral runner** | 8 | 7 | 3 | 1.5 | **12** |

### PR3 rationale
- BV=3: zero wallclock benefit (job is `continue-on-error: true`, runs parallel). Pure parallel-slot relief on PRs that don't touch homage paths (~95% of PRs) + removes informational noise from CI status.
- TC=2: not gating anything; current state is already non-blocking.
- RR=4: nightly cron on main retains the regression cadence; path-gate prevents the homage-vr job from generating false-positive flake noise that masks real signal. Mild risk-reduction via reduced alert fatigue.
- Size=~1h: ci.yml `paths:` clause + nightly cron entry. Lowest-risk change in the bundle.

### PR4 rationale (revised post-pyrefly)
- BV=2: typecheck is now pure-python (pyrefly), so the `~23s apt-get` saving in that job is **zero** — pyrefly doesn't need cairo/gst/pango. Remaining beneficiaries are `test`, `lint`, and `homage-vr`. With these jobs running in parallel, the wallclock impact on PR turnaround is bounded by the slowest of the three (`test` at 225s); apt is ~10% of test setup overhead, savings hidden inside parallel runtime. Effective wallclock saving ≈ 0-20s, not the originally-modeled 70s.
- TC=1: nothing depends on this; pure micro-optimization.
- RR=1: `cache-apt-pkgs-action` adds a new cache surface (key drift, cache poisoning vectors) for marginal gain.
- Size=~0.5d: action wiring + per-job cache keys + verification across 3 jobs.

### PR5 rationale (with pricing recheck)
- BV=8: `test` at 225s is now the dominant CI cost. A self-hosted runner on the workstation with persistent cache, NVMe scratch, and 16+ cores realistically delivers a 3-5x speedup on `test` alone (40-75s vs 225s) — biggest single-PR business-value lever remaining.
- TC=7: every week of delay = ~30 PRs paying the full 225s test cost. The pyrefly+xdist gains lower the urgency floor but do not eliminate the test-job dominance.
- RR=3: introduces ops surface (runner lifecycle, secrets isolation, network egress, repo-write blast radius if compromised). Net risk-positive only with strict ephemeral nspawn + rootless + per-job teardown.
- Size=1.5d: nspawn template + ephemeral systemd unit + GH runner registration + PAT scoping + smoke-test 3 PRs.

**Pricing recheck (GitHub Actions self-hosted minute charge):**
- Original announcement: 2025-12-15 — $0.002/min platform charge on self-hosted runners (private repos), effective 2026-03-01.
- **Postponement: ~2025-12-22** (one week after the announcement), per GitHub Changelog and Jared Palmer's public statement.
- **Status as of 2026-04-26: SHELVED INDEFINITELY.** Not implemented, not formally rescinded. GitHub committed to "consultation with developers/customers/partners" before any future monetization attempt; no new effective date has been published. The 39% reduction on GitHub-hosted runners (also 2026-01-01) proceeded as planned.
- **Implication for PR5:** the operational-cost penalty that was the original gating concern is **currently zero**. At the originally-announced $0.002/min, council CI usage (~6.5 min × 30 PRs/week × 4 weeks = 780 min/mo private + non-PR pushes) would have cost ~$1.56/mo — already trivial. Postponement makes this strictly free. **No reason to defer PR5 on pricing grounds.**
- Watch-item: re-run this check at the next rotation milestone or if GitHub posts new pricing on the changelog. If the charge re-activates, council usage stays well under any plausible included-minutes ceiling, so the cost remains negligible.

## 2. Ranking

1. **PR3** (WSJF 69) — ship next.
2. **PR5** (WSJF 12) — ship after PR3.
3. **PR4** (WSJF 8) — defer or refuse.

## 3. Dispatch recommendation

**Ship PR3 next.** Cheapest action with non-zero value; clears the homage-vr noise out of the way before larger surgery and decongests the parallel job slot for the PR5 self-hosted runner experiment. **Then ship PR5** — `test` is the dominant remaining cost and self-hosted is the only lever with 3-5x potential left. The pricing concern that originally gated PR5 is moot: GitHub postponed the $0.002/min charge ~2025-12-22 and it remains shelved as of today (2026-04-26); even if reactivated, council's volume puts the cost in the cents-per-month range, well inside any plausible plan's free tier. **Defer (and likely refuse) PR4** — pyrefly's pure-python nature collapsed PR4's value math: the apt-cache bundle now saves at most 0-20s of hidden parallel-runtime overhead across 3 jobs, for half a day of work and a new cache surface to maintain. WSJF 8 doesn't justify the implementation cost when PR5 is sitting at 12 with 5-10x more headroom. Revisit only if a future PR forces a typecheck-job system-deps regression.

## Sources

- [GitHub Actions 2026 pricing changelog (original announcement, 2025-12-15)](https://github.blog/changelog/2025-12-16-coming-soon-simpler-pricing-and-a-better-experience-for-github-actions/)
- [SAMexpert — GitHub Actions Pricing: Price Cuts, Backlash, and a Rapid Retreat](https://samexpert.com/github-actions-pricing-backlash-2026/)
- [The Register — GitHub walks back plan to charge for self-hosted runners](https://www.theregister.com/2025/12/17/github_charge_dev_own_hardware/)
- [Socket.dev — GitHub Actions Pricing Whiplash](https://socket.dev/blog/github-actions-pricing-whiplash)
- [Jared Palmer (GitHub) — postponement announcement](https://x.com/jaredpalmer/status/2001373329811181846)
- [Reduced pricing for GitHub-hosted runners (2026-01-01, proceeded as planned)](https://github.blog/changelog/2026-01-01-reduced-pricing-for-github-hosted-runners-usage/)
- [GitHub Actions runner pricing reference docs](https://docs.github.com/en/billing/reference/actions-runner-pricing)
- [pytest-xdist distribution docs](https://pytest-xdist.readthedocs.io/en/latest/distribution.html)
- [awalsh128/cache-apt-pkgs-action](https://github.com/awalsh128/cache-apt-pkgs-action)

## Related operator memories

- `feedback_features_on_by_default` — PRs 3/5 ship enabled by default, no shadow window.
- `feedback_no_stale_branches` — beta dispatches one PR at a time per session.
- `feedback_verify_before_claiming_done` — PR5 needs at least 3 verified-green PRs against the new self-hosted runner before declaring done.
- `feedback_ci_local_parity` — PR5 self-hosted runner must NOT diverge from GHA-hosted env for the 26-item ignore list (font hinting, missing GPU). The whole point is parity-or-better.
