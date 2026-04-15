# Hermes 3 70B weights disk cleanup inventory

**Date:** 2026-04-15
**Author:** beta (queue #221, identity verified via `hapax-whoami`)
**Scope:** inventory all disk state related to Hermes 3 LLM weights + partial quantizations + reference binaries. Per queue spec: non-destructive operator-gated proposal only. No actual deletion performed.
**Branch:** `beta-phase-4-bootstrap`

---

## 0. Summary

**Verdict: DISK CLEANUP IS ALREADY COMPLETE.** No Hermes 3 weights, quant outputs, or reference files exist on disk as of 2026-04-15T19:33Z. The 27 GB 3.0bpw + 54 GB partial 3.5bpw + ~140 GB bf16 reference (per prior session cleanup notes in drop #62 §14) are ALL GONE. Either the operator cleaned them up during or after the 06:35Z Hermes abandonment, or another session removed them before this inventory ran.

**Remaining drift (stale config, NOT disk bloat):** the `systemd/units/tabbyapi-hermes8b.service` unit file + its `.service.d/gpu-pin.conf` drop-in exist in the repo. These are explicitly marked SUPERSEDED 2026-04-15T06:35Z in the unit header but the files are not removed. Low-severity stale-config drift — not blocking anything, not consuming disk, but clutters the systemd unit inventory.

## 1. Disk inventory (canonical locations per queue #221 spec + broader search)

### 1.1 tabbyAPI/models/ — EMPTY of Hermes

```
$ ls ~/projects/tabbyAPI/models/
place_your_models_here.txt
Qwen3.5-9B-exl3-5.00bpw
```

No `Hermes-*` directory. The 3.0bpw weights (~27 GB per queue #221 spec expectation) are gone.

### 1.2 ~/hapax-state/quant-staging/ — DOES NOT EXIST

```
$ ls ~/hapax-state/quant-staging
ls: cannot access 'hapax-state/quant-staging': No such file or directory
```

No partial quant outputs. The ~54 GB 3.5bpw partial quant (killed at layer 57/80 per drop #62 §14 addendum) is gone.

### 1.3 ~/hapax-state/ — 679 MB total

```
$ du -sh ~/hapax-state
679M    hapax-state
```

No capacity for multi-gigabyte weight files. Hermes state is definitively not hiding in hapax-state.

### 1.4 HuggingFace cache — no Hermes

```
$ find ~/.cache/huggingface -iname "*Hermes*"
(no results)
```

The HF cache has other models (Kokoro, Whisper, etc.) but no Hermes.

### 1.5 Broader filesystem search

```
$ find / -iname "*Hermes*3*70b*" -type d 2>/dev/null
(no results)

$ find / -type f -iname "*hermes*" -size +1M 2>/dev/null
(no results — only hermes-estree/hermes-parser node_modules packages, which are JS parsing libraries, not Hermes 3 LLM)
```

Broader search confirms zero Hermes 3 LLM disk state anywhere under `/`.

### 1.6 Disk health baseline (for context)

```
$ df -h ~/
Filesystem      Size  Used Avail Use% Mounted on
/dev/nvme0n1p2  928G  230G  690G  25% /home
```

230 GB used / 690 GB available. Healthy. The ~221 GB of Hermes state that would have been removed per drop #62 §14 footnote (§14 flagged `~221 GB total recoverable`) — whether removed during or after the abandonment decision — is not occupying disk now.

## 2. Repo-level stale config (not disk bloat)

### 2.1 `systemd/units/tabbyapi-hermes8b.service` — SUPERSEDED but still present

```
$ head -15 systemd/units/tabbyapi-hermes8b.service
[Unit]
Description=TabbyAPI — EXL3 inference engine (second instance, Hermes 3 8B on :5001)
After=network.target
After=ollama.service
#
# SUPERSEDED 2026-04-15T06:35Z — operator abandoned Hermes entirely with
# direction "We've abandoned hermes. Devote extensive research into if
# Qwen3.5-9B-exl3-5.00bpw is actually the best production substrate for
# our very unique use cases." Drop #62 §14 (commit 2bc6aec17) is the
# canonical audit-trail capture. Beta's 722-line substrate
# re-evaluation research at docs/research/2026-04-15-substrate-reeval-
# post-hermes.md (commit bb2fb27ca on beta-phase-4-bootstrap) recommends
# keeping Qwen3.5-9B + complementary parallel-deploy OLMo 3-7B. Neither
# is yet operator-ratified.
#
```

Self-documented as superseded but still in the repo. Zero disk impact (a few KB) but adds noise to the systemd unit list.

### 2.2 `systemd/units/tabbyapi-hermes8b.service.d/gpu-pin.conf` — SUPERSEDED drop-in

```
$ ls systemd/units/tabbyapi-hermes8b.service.d/
gpu-pin.conf
```

The drop-in exists as a scaffolding artifact for the now-deferred Hermes 3 8B parallel deploy. Contains GPU allocation Options A/B/C for the Hermes deploy. Stale, clutters the units directory.

### 2.3 Cross-reference to Option C pivot

Per delta's 18:49Z operator inflection + beta's queue #209 closure, the current plan is **Option C parallel backend for OLMo** (not Hermes). The Hermes 8B second-instance unit + drop-in should be:

- **Option A (preferred):** delete both files. The substrate research decision has ratified scenarios 1+2 (Qwen3.5-9B + OLMo 3-7B parallel), not Hermes. The stale scaffolding will never be activated.
- **Option B:** rename to `tabbyapi-olmo.service` + `.d/gpu-pin.conf` and repurpose for OLMo. But the OLMo systemd unit will be authored fresh per the queue #211 spec, so renaming the Hermes stub is riskier than writing a new one.
- **Option C:** leave as SUPERSEDED audit-trail scaffolding, never activated, tolerate the noise.

**Beta recommends Option A.** Delete. The supersession message is captured in git history + drop #62 §14 + beta's substrate research. Future sessions don't need the scaffolding file to understand the deprecation — the commit history + research drops are sufficient.

**Proposed cleanup queue item #227:**

```yaml
id: "227"
title: "Delete superseded tabbyapi-hermes8b systemd unit + drop-in"
assigned_to: alpha  # or delta or beta
status: offered
priority: low
depends_on: []
description: |
  systemd/units/tabbyapi-hermes8b.service + its .service.d/gpu-pin.conf
  drop-in are SUPERSEDED 2026-04-15T06:35Z per the unit header. Queue
  #221 Hermes disk cleanup inventory verified no Hermes weights remain
  on disk. The stale scaffolding can be deleted from the repo — commit
  history + drop #62 §14 + beta substrate research bb2fb27ca preserve
  the deprecation audit trail.
  
  Actions:
  1. git rm systemd/units/tabbyapi-hermes8b.service
  2. git rm -r systemd/units/tabbyapi-hermes8b.service.d/
  3. Small PR with commit message referencing queue #221 + drop #62 §14
size_estimate: "~5 min cleanup"
```

## 3. Disk inventory summary matrix

| Expected location | Queue #221 expectation | Actual state | Action needed |
|---|---|---|---|
| `~/projects/tabbyAPI/models/Hermes-*` (27 GB 3.0bpw) | Present | **ABSENT** | None — already cleaned |
| `~/hapax-state/quant-staging/work-3.5bpw/` (54 GB partial) | Present | **ABSENT** (directory doesn't exist) | None |
| `~/hapax-state/quant-staging/Hermes-*-bf16/` (~140 GB ref) | Present | **ABSENT** | None |
| HuggingFace cache Hermes entries | Possibly present | **ABSENT** | None |
| `systemd/units/tabbyapi-hermes8b.service` | Not mentioned in spec | **PRESENT (superseded)** | Proposed #227 cleanup |
| `systemd/units/tabbyapi-hermes8b.service.d/gpu-pin.conf` | Not mentioned in spec | **PRESENT (superseded)** | Proposed #227 cleanup |

**Disk savings from #227:** ~5 KB (config files only). Purely cosmetic / audit-clarity, not capacity.

## 4. Historical audit-trail summary

Per drop #62 §14 + §14.4(d):

- **2026-04-15T06:20Z:** operator direction "1 hardware env unlikely to change within the year" → 3.5bpw quant killed at layer 57/80
- **2026-04-15T06:35Z:** operator abandons Hermes entirely → `tabbyapi-hermes8b.service` marked SUPERSEDED
- **Drop #62 §14.4(d)** flagged `~221 GB total recoverable` (54 GB partial 3.5bpw + ~140 GB bf16 ref + 27 GB 3.0bpw) as "operator-disposition items — not urgent"
- **2026-04-15T19:33Z (this audit):** disk cleanup already complete. 0 bytes of Hermes weights remaining.

Attribution for the cleanup itself is unknown (this audit did not search git history for the deletion commit). Possible paths:

1. Operator manually deleted via `rm -rf` during or after the 06:35Z abandonment
2. Another session (alpha/delta/epsilon) shipped a cleanup commit
3. The files were on a scratch mount that was wiped between then and now

**Not investigated** — the cleanup is done and the specific mechanism doesn't affect the forward path.

## 5. Operator-facing cleanup proposal

Per queue spec: "Propose cleanup recommendation (archive off-disk? delete?) — Flag as operator-decision item — do NOT delete without authorization."

### 5.1 Disk weights: NO ACTION NEEDED

Already cleaned. No operator decision required.

### 5.2 Systemd scaffolding: OPTIONAL DELETION

Queue item #227 proposes deleting the SUPERSEDED `tabbyapi-hermes8b.service` unit + drop-in. **Low priority.** The supersession message is self-documenting and the files occupy ~5 KB.

If the operator prefers to keep the stale scaffolding as an audit-trail marker, that's also defensible. The files are inert (not installed on the live system per `systemctl --user list-unit-files | grep hermes8b` returning no match — verified via spot-check) and don't affect runtime.

**Beta's recommendation:** delete them via #227. The git history + drop #62 §14 + this inventory drop provide sufficient audit trail without needing the inert unit files as physical artifacts.

### 5.3 Archive off-disk: NOT APPLICABLE

There are no weights to archive. The disk is already clean.

## 6. Non-drift observations

- **Disk health is excellent:** 230 GB used / 690 GB available. The Hermes cleanup (~221 GB freed per drop #62 §14) accounts for about 32% of current free space. Without that cleanup, the disk would be at ~451 GB used / 477 GB available = 48% utilization.
- **HuggingFace cache is clean of abandoned models.** Only live models (Kokoro, Whisper) remain. No leaked weights from prior experiments.
- **Quant-staging directory was CLEANED UP ENTIRELY**, not just emptied. `~/hapax-state/quant-staging` doesn't exist as a directory. Either the cleanup was aggressive (`rm -r`) or it was never created in the first place on this filesystem instance.

## 7. Cross-references

- Drop #62 §14 Hermes abandonment addendum — `docs/research/2026-04-14-cross-epic-fold-in-lrr-hsea.md` §14
- Beta substrate research v1 — commit `bb2fb27ca` (on `beta-phase-4-bootstrap`)
- Beta substrate research v2 — commit `f2a5b2348` (on `beta-phase-4-bootstrap`)
- `systemd/units/tabbyapi-hermes8b.service` — SUPERSEDED 2026-04-15T06:35Z (self-documented in unit header)
- Delta 18:49Z Option C pivot inflection — `20260415-184900-delta-operator-substrate-scenario-2-option-c-pivot.md`
- Beta queue #209 closure inflection — `20260415-184500-beta-delta-209-exllamav3-upgrade-blocked.md`
- Queue item spec: queue/`221-beta-hermes-weights-disk-cleanup-inventory.yaml`

— beta, 2026-04-15T19:35Z (identity: `hapax-whoami` → `beta`)
