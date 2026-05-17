# CI merge queue required-check audit

**Date**: 2026-05-17
**Task**: `ci-merge-queue-required-check-audit`
**Lane**: `codex-ci-merge-audit`
**Branch**: `codex/ci-merge-queue-required-check-audit`
**Scope**: docs-only audit. No workflow, source, or test files were changed.

## Summary

As of 2026-05-17T15:48:02Z, `main` is protected by five required
GitHub Actions checks: `lint`, `test`, `typecheck`, `web-build`, and
`vscode-build`. The repository has one visible ruleset, `main-merge-queue`,
with `enforcement: active`, targeting `refs/heads/main` and requiring a merge
queue.

Recent `merge_group` CI runs show the required `test` job is the dominant
merge-queue cost. The sampled CI workflow durations ranged from 833s to 1031s;
the required `test` job accounts for nearly all of that wall time.

The live branch-protection surface and GitHub's current docs imply a strict
invariant for future required checks: required check names must be reported on
both pull-request validation and merge-queue validation. A PR-triggered workflow
without `merge_group`, or a required workflow skipped by workflow-level branch
or path filters, can leave the merge path waiting on an unreported or pending
required check.

## Current GitHub docs basis

Docs source: Context7 `/websites/github_en_actions` and `/github/docs`, checked
on 2026-05-17, with spot checks against docs.github.com.

Current GitHub docs establish these constraints:

- Merge queues require CI to trigger and report for `merge_group`; GitHub says
  required GitHub Actions workflows need the `merge_group` event, otherwise the
  required status check is not reported and the merge can fail.
  Source: [GitHub Actions `merge_group` event](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#merge_group)
  and [Managing a merge queue](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue#triggering-merge-group-checks-with-github-actions).
- Required status checks must pass before a protected branch or ruleset target
  can be changed. Rulesets can also pin a required check to a specific source
  app.
  Source: [Available rules for rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets#require-status-checks-to-pass-before-merging).
- If a workflow is skipped due to workflow-level branch filtering, path
  filtering, or a skip instruction, the associated checks remain pending and a
  PR requiring those checks is blocked.
  Source: [Workflow syntax branch/path filters](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#onpull_requestpull_request_targetbranchesbranches-ignore)
  and [Skipping workflow runs](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/skip-workflow-runs).

Local policy inference: keep required workflow and job check names instantiated
on the required events, then put selectivity inside the job using step-level
conditions, sentinel steps, or an aggregator job. This inference follows from
the docs above and from the observed CI pattern where required jobs exist and
report success while some internal steps can be skipped.

## Live branch protection

Command:

```bash
gh api repos/hapax-systems/hapax-council/branches/main/protection \
  --jq '{required_status_checks:.required_status_checks, required_pull_request_reviews:.required_pull_request_reviews, enforce_admins:.enforce_admins.enabled, required_linear_history:.required_linear_history.enabled, allow_force_pushes:.allow_force_pushes.enabled, allow_deletions:.allow_deletions.enabled}'
```

Observed at 2026-05-17T15:48:02Z:

| Field | Value |
|---|---|
| Required checks | `lint`, `test`, `typecheck`, `web-build`, `vscode-build` |
| Required check app IDs | all `15368` |
| Strict required checks | `false` |
| Required PR reviews | `null` |
| Enforce admins | `false` |
| Required linear history | `false` |
| Allow force pushes | `false` |
| Allow deletions | `false` |

The required-check set exactly matches the five CI jobs currently under main
branch protection.

## Live rulesets

Commands:

```bash
gh api 'repos/hapax-systems/hapax-council/rulesets?includes_parents=true' \
  --jq '[.[] | {id, name, target, source_type, source, enforcement, updated_at, created_at}]'

gh api repos/hapax-systems/hapax-council/rulesets/16186443 \
  --jq '{id,name,target,enforcement,conditions,rules:[.rules[] | {type, parameters}]}'
```

Observed ruleset list:

| ID | Name | Target | Source | Enforcement | Created | Updated |
|---:|---|---|---|---|---|---|
| 16186443 | `main-merge-queue` | `branch` | `hapax-systems/hapax-council` | `active` | 2026-05-10T00:58:45.158-05:00 | 2026-05-10T00:58:45.169-05:00 |

Ruleset detail:

| Field | Value |
|---|---|
| Condition | include `refs/heads/main`; exclude `[]` |
| Rule type | `merge_queue` |
| Check response timeout | 60 minutes |
| Grouping strategy | `ALLGREEN` |
| Max entries to build | 3 |
| Max entries to merge | 3 |
| Min entries to merge | 1 |
| Min entries wait | 0 minutes |
| Merge method | `SQUASH` |

No parent rulesets were visible through the repository rulesets API with
`includes_parents=true`.

## Recent merge-group CI runs

Command:

```bash
gh run list --repo hapax-systems/hapax-council --event merge_group --limit 20 \
  --json databaseId,workflowName,createdAt,updatedAt,conclusion,headBranch,url \
  --jq '.[] | select(.workflowName == "CI") | {run_id:.databaseId, conclusion, createdAt, updatedAt, duration_seconds: ((.updatedAt | fromdateiso8601) - (.createdAt | fromdateiso8601)), headBranch, url}'
```

Sampled CI `merge_group` runs:

| Run | PR queue ref | Conclusion | Created | Completed | Duration |
|---:|---|---|---|---|---:|
| 25994803749 | `pr-3390` | success | 2026-05-17T15:22:12Z | 2026-05-17T15:37:58Z | 946s |
| 25990721895 | `pr-3389` | success | 2026-05-17T12:22:28Z | 2026-05-17T12:39:25Z | 1017s |
| 25987964455 | `pr-3387` | success | 2026-05-17T10:10:19Z | 2026-05-17T10:27:17Z | 1018s |
| 25987619425 | `pr-3388` | success | 2026-05-17T09:53:25Z | 2026-05-17T10:09:29Z | 964s |
| 25986956767 | `pr-3383` | success | 2026-05-17T09:21:00Z | 2026-05-17T09:36:39Z | 939s |
| 25986810826 | `pr-3386` | success | 2026-05-17T09:13:50Z | 2026-05-17T09:31:01Z | 1031s |
| 25986517738 | `pr-3384` | success | 2026-05-17T08:59:56Z | 2026-05-17T09:16:32Z | 996s |
| 25986506188 | `pr-3382` | success | 2026-05-17T08:59:23Z | 2026-05-17T09:13:16Z | 833s |
| 25986505926 | `pr-3385` | success | 2026-05-17T08:59:23Z | 2026-05-17T09:15:34Z | 971s |
| 25986474592 | `pr-3382` | failure | 2026-05-17T08:57:50Z | 2026-05-17T09:14:49Z | 1019s |

The 60-minute merge queue timeout leaves current CI with a large margin, but
the steady 14-17 minute duration means queue throughput is dominated by the
slowest required job rather than by rule or queue overhead.

## Dominant required job

Command pattern:

```bash
gh run view <run-id> --repo hapax-systems/hapax-council --json jobs \
  --jq '.jobs[] | select(.name=="lint" or .name=="test" or .name=="typecheck" or .name=="web-build" or .name=="vscode-build") | {job_id:.databaseId, name, conclusion, startedAt, completedAt, duration_seconds: ((.completedAt|fromdateiso8601)-(.startedAt|fromdateiso8601))}'
```

Required-job durations from representative successful merge-group CI runs:

| Run | `lint` | `test` | `typecheck` | `web-build` | `vscode-build` |
|---:|---:|---:|---:|---:|---:|
| 25994803749 | 97s | 922s | 15s | 47s | 21s |
| 25990721895 | 95s | 995s | 13s | 42s | 20s |
| 25987964455 | 91s | 996s | 15s | 47s | 19s |
| 25986506188 | 92s | 811s | 17s | 48s | 16s |

`test` is the dominant required check. Any queue-throughput work that preserves
the required-check contract should target `test` first, or split/aggregate it
without changing the required public context name unless branch protection is
updated in the same governed operation.

## PR #3390 evidence

PR #3390 (`fix(sdlc): allow governed intake bootstrap without claim`) merged
through the merge queue:

| Field | Value |
|---|---|
| PR | <https://github.com/hapax-systems/hapax-council/pull/3390> |
| Merge commit | `bfa53d99bda0840004f9ee1573890be5dc942ae0` |
| Merge-group CI run | <https://github.com/hapax-systems/hapax-council/actions/runs/25994803749> |
| Merge-group head | `gh-readonly-queue/main/pr-3390-293eeb6f81309a5b9a966a980a7e4322942a7ce4` |
| CI run completion | success at 2026-05-17T15:37:58Z |
| Required `test` job | job 76407348421, success at 2026-05-17T15:37:57Z |
| PR merged | 2026-05-17T15:38:30Z |

The observed order is consistent with merge queue behavior: required CI
completed successfully, then GitHub merged the queued PR.

## PR workflows not safe to require as-is

Command used:

```bash
python3 - <<'PY'
from pathlib import Path
import yaml

class Loader(yaml.SafeLoader):
    pass
for ch, resolvers in list(Loader.yaml_implicit_resolvers.items()):
    Loader.yaml_implicit_resolvers[ch] = [r for r in resolvers if r[0] != 'tag:yaml.org,2002:bool']

for path in sorted(Path('.github/workflows').glob('*.y*ml')):
    data = yaml.load(path.read_text(), Loader=Loader) or {}
    on = data.get('on', {})
    if isinstance(on, str):
        events = {on: None}
    elif isinstance(on, list):
        events = {event: None for event in on}
    elif isinstance(on, dict):
        events = on
    else:
        events = {}
    has_pr = any(event in events for event in ('pull_request', 'pull_request_target'))
    has_merge_group = 'merge_group' in events
    if not has_pr or has_merge_group:
        continue
    jobs = []
    for job_id, job in (data.get('jobs') or {}).items():
        jobs.append((job.get('name') if isinstance(job, dict) and job.get('name') else job_id))
    pr_cfg = events.get('pull_request') or events.get('pull_request_target') or {}
    filters = []
    if isinstance(pr_cfg, dict):
        filters = [key for key in ('branches', 'branches-ignore', 'paths', 'paths-ignore') if key in pr_cfg]
    print(f"{path.name}\t{data.get('name')}\tfilters={','.join(filters) or '-'}\tjobs={', '.join(jobs) or '-'}")
PY
```

These workflows have a PR trigger but no `merge_group` trigger. They should not
be added to required status checks without a merge-queue-compatible redesign.

| Workflow | Name | Workflow-level PR filters | Job contexts |
|---|---|---|---|
| `audio-graph-validate.yml` | `audio-graph-validate` | `branches`, `paths` | `passive-validator` |
| `audit-yaml-validate.yml` | `Audit-yaml schema validate` | `paths` | `validate` |
| `authority-case-check.yml` | `AuthorityCase Check` | none | `authority-case-check` |
| `claude-md-rot.yml` | `CLAUDE.md rotation policy` | `branches`, `paths` | `rot-check` |
| `claude-review.yml` | `Claude PR Review` | none | `review` |
| `dependabot-auto-merge.yml` | `Dependabot Auto-Merge` | none | `auto-merge` |
| `experiment-freeze.yml` | `Experiment Freeze Gate` | `branches` | `freeze-check` |
| `post-merge-deploy-coverage.yml` | `Post-merge deploy coverage` | `paths` | `coverage` |
| `pr-admission.yml` | `pr-admission` | none | `pr-admission` |
| `sdlc-review.yml` | `SDLC: Adversarial Review` | `branches-ignore` | `review` |
| `vale-lint.yml` | `Vale Style Check` | `branches`, `paths` | `vale` |

Risk classification:

- High required-check risk: `authority-case-check`, `pr-admission`,
  `experiment-freeze`, and `Claude PR Review` are gate-like names that may be
  tempting to require, but they do not currently report on `merge_group`.
- Pending-check risk if required: `audio-graph-validate`, `audit-yaml-validate`,
  `claude-md-rot`, `post-merge-deploy-coverage`, and `vale-lint` use
  workflow-level path or branch filters. If any associated check becomes
  required, docs-only or unrelated changes can leave that check pending.
- Ambiguous context-name risk: both `Claude PR Review` and `SDLC: Adversarial
  Review` expose a job named `review`. If either becomes required, keep the
  required context unambiguous and source-pinned.

`CI` and `Security Extras` already include `merge_group`; only `CI` is currently
required by branch protection.

## Follow-up items

1. **WSJF 9.0 - required-check coverage guard**
   Add or extend a deterministic guard that compares live branch protection
   required checks against `.github/workflows/ci.yml` job names and asserts the
   required workflow includes `merge_group`. This belongs with the existing CI
   required-coverage test surface and should be sequenced with the owner of
   `tests/test_ci_required_coverage_claims.py`.

2. **WSJF 8.5 - merge-queue docs-only fast path**
   Reduce the required `test` job cost for docs-only or governance-note changes
   while preserving the public `test` check name. Use step-level conditions or a
   required-check aggregator; do not move the required job behind workflow-level
   path filters.

3. **WSJF 7.5 - required-check promotion checklist**
   Before promoting any PR-triggered workflow to required, require all of:
   `merge_group` trigger present, no workflow-level path or branch filter that
   can suppress the check, stable unique job context, and source app pinned to
   GitHub Actions if branch protection supports it.

4. **WSJF 6.5 - merge-group duration dashboard**
   Track rolling `merge_group` CI duration, slowest required job, and timeout
   margin. Current runs are below the 60-minute timeout, but `test` is stable
   enough to deserve a visible throughput metric.

5. **WSJF 6.0 - non-required gate review**
   Decide explicitly whether gate-like jobs such as `authority-case-check` and
   `pr-admission` should stay advisory or become required. If they become
   required, redesign them for merge queue first.

## Verification

This audit used live API and docs commands only. It did not print or persist
tokens.

Commands run:

```bash
gh api repos/hapax-systems/hapax-council/branches/main/protection --jq '{required_status_checks:.required_status_checks, required_pull_request_reviews:.required_pull_request_reviews, enforce_admins:.enforce_admins.enabled, required_linear_history:.required_linear_history.enabled, allow_force_pushes:.allow_force_pushes.enabled, allow_deletions:.allow_deletions.enabled}'
gh api 'repos/hapax-systems/hapax-council/rulesets?includes_parents=true' --jq '[.[] | {id, name, target, source_type, source, enforcement, updated_at, created_at}]'
gh api repos/hapax-systems/hapax-council/rulesets/16186443 --jq '{id,name,target,enforcement,conditions,rules:[.rules[] | {type, parameters}]}'
gh run list --repo hapax-systems/hapax-council --event merge_group --limit 20 --json databaseId,workflowName,createdAt,updatedAt,conclusion,headBranch,url --jq '.[] | select(.workflowName == "CI") | {run_id:.databaseId, conclusion, createdAt, updatedAt, duration_seconds: ((.updatedAt | fromdateiso8601) - (.createdAt | fromdateiso8601)), headBranch, url}'
gh run view 25994803749 --repo hapax-systems/hapax-council --json databaseId,displayTitle,event,status,conclusion,createdAt,updatedAt,headBranch,headSha,jobs,url
gh pr view 3390 --repo hapax-systems/hapax-council --json number,title,state,mergedAt,mergeCommit,url,headRefName,baseRefName,statusCheckRollup
```
