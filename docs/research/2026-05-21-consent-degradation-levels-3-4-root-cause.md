---
title: "Root Cause: consent degradation levels 3 & 4 unimplemented"
date: 2026-05-21
author: epsilon
status: confirmed
source: CCTV disconfirmation audit 2026-05-18
cc_task: 202605181934-disconfirm-consen-p0-research-root-cause
authority_case: CASE-202605181934-DISCONF
---

# Root Cause: consent degradation levels 3 & 4 unimplemented

## Finding

The consent degradation system declares 4 levels but only implements 2. Levels 3
(existence-only) and 4 (total suppression) fall through to level-2 (abstraction)
behavior in all production code paths.

## Root Cause

Three independent gaps prevent levels 3/4 from firing:

1. **API mismatch.** `agents/_governance/degradation.py:degrade()` has no `level`
   parameter. The `shared/governance/degradation.py` version does, and routes
   levels 3/4 correctly (lines 144–151), but the agents version is the one
   imported by the production consent reader.

2. **Decision logic gap.** `ConsentGatedReader.filter()` in both
   `agents/_governance/consent_reader.py` (line 165–188) and
   `shared/governance/consent_reader.py` (line 151–174) only ever assigns
   `degradation_level=1` (no unconsented persons) or `degradation_level=2`
   (any unconsented person). No code path evaluates whether level 3 or 4
   should apply.

3. **Missing escalation policy.** No data structure maps data categories or
   per-person consent states to degradation levels above 2. The design doc
   (`docs/research/2026-03-15-consent-gated-retrieval-research.md`) specifies
   the behavior but not the trigger conditions.

## Evidence

### Declaration (all 4 levels)

| Location | Form |
|----------|------|
| `agents/_governance/degradation.py:6-12` | Module docstring |
| `agents/_governance/consent_reader.py:48` | `ReaderDecision.degradation_level` type comment: `# 1=full, 2=abstract, 3=existence, 4=suppress` |
| `shared/governance/degradation.py:6-12` | Module docstring |
| `shared/governance/degradation.py:130-142` | `degrade()` signature with `level` parameter |
| `docs/research/2026-03-15-consent-gated-retrieval-research.md` | Sections on Level 3 and Level 4 behavior |

### Implementation (only levels 1 and 2)

**Agents path** (`agents/_governance/consent_reader.py:165-188`):
```python
if not unconsented:
    decision = ReaderDecision(..., degradation_level=1, ...)  # line 169
else:
    filtered = degrade(content, frozenset(unconsented), category)  # no level param
    decision = ReaderDecision(..., degradation_level=2, ...)  # line 180
```

**Agents `degrade()` signature** (`agents/_governance/degradation.py:121`):
```python
def degrade(content: str, unconsented: frozenset[str], category: str = "default") -> str:
```
No `level` parameter exists — always performs level-2 abstraction.

**Shared `degrade()` — correct routing exists but is unreachable**
(`shared/governance/degradation.py:144-151`):
```python
if level == 3:
    return degrade_to_existence(category, item_count)  # implemented
if level >= 4:
    return degrade_to_suppression()  # implemented
```

### Actual vs expected behavior

| Level | Expected | Actual |
|-------|----------|--------|
| 1 — Full | Return content unchanged | Works |
| 2 — Abstract | Replace names with counts/roles | Works |
| 3 — Existence | "You have N items (details withheld)" | Falls through to level 2 |
| 4 — Suppress | Return empty string | Falls through to level 2 |

### Reproducible probe

```python
from agents._governance.consent_reader import ConsentGatedReader
reader = ConsentGatedReader(consent_store=..., operator_name="Ryan")
# Any datum with unconsented persons → degradation_level is always 2
# regardless of data sensitivity or person-specific policy
```

## Test coverage gap

`tests/test_consent_reader.py` (442 lines) tests only levels 1 and 2.
No test for `degrade_to_existence()` or `degrade_to_suppression()`.
No test asserts that levels 3/4 produce different output from level 2.

## Remediation path

1. Add `level` parameter to `agents/_governance/degradation.py:degrade()`,
   matching the shared version's routing logic.
2. Add escalation logic to `ConsentGatedReader.filter()` — determine when
   level 3/4 should apply (per-category policy or per-person consent flags).
3. Add tests covering all 4 levels in `tests/test_consent_reader.py`.
4. Define the escalation policy document (which categories → which levels).
