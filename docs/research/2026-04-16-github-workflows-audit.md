---
title: github/workflows CI coverage audit
date: 2026-04-16
queue_item: '315'
epic: lrr
phase: substrate-scenario-2
status: catalog
---

# .github/workflows/ — CI coverage audit

## Summary

| Metric | Count |
|---|---|
| Workflow files | 12 |

## Workflows

| File | Triggers | Job names |
|---|---|---|
| `auto-fix.yml` | workflow_run | auto-fix |
| `ci.yml` | push,pull_request | lint,typecheck,test,web-build,vscode-build,secrets-scan,security |
| `claude-md-rot.yml` | push,pull_request | rot-check |
| `claude-review.yml` | pull_request | review |
| `codebase-map.yml` | schedule,workflow_dispatch | generate |
| `dependabot-auto-merge.yml` | pull_request_target | auto-merge |
| `experiment-freeze.yml` | pull_request | freeze-check |
| `lab-journal.yml` | push | build,deploy |
| `sdlc-axiom-gate.yml` | pull_request_review | axiom-gate |
| `sdlc-implement.yml` | repository_dispatch,pull_request_review | plan-and-implement,fix-round |
| `sdlc-review.yml` | pull_request | review |
| `sdlc-triage.yml` | issues | triage |

## Branch protection required checks (main)

```
lint
test
typecheck
web-build
vscode-build
```
