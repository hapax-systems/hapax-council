---
title: "Consent degradation levels 1–4"
date: 2026-05-21
status: authoritative
authority: agents/_governance/degradation.py, shared/governance/degradation.py
---

# Consent Degradation Levels

Four levels govern how content is transformed when it references persons
who lack consent contracts. Each level is distinct and independently
reachable.

## Level 1 — Full access

**Disclosure**: Content returned unchanged.

**Trigger**: All referenced persons have active consent contracts, or the
content references no persons.

**Example**: "Meeting with Alice at 3pm" → "Meeting with Alice at 3pm"

## Level 2 — Abstraction (default)

**Disclosure**: Unconsented person identifiers replaced with counts/roles.
Content structure and non-person details preserved.

**Trigger**: Any referenced person lacks a consent contract. This is the
default when no explicit level is requested.

**Example**: "Meeting with Alice and Bob at 3pm" → "Meeting with 2 people at 3pm"

**Category-specific behavior**:
- Calendar: `(with Name1, Name2)` → `(with N people)`
- Email: `alice@corp.com` → `[someone at corp.com]`
- Document: `Alice` → `Someone`

## Level 3 — Existence only

**Disclosure**: Only the existence and count of items is confirmed. No
content fields, no timing, no topics, no identifiers.

**Trigger**: Explicit `level=3` parameter to `degrade()`. No automatic
escalation policy currently assigns this level — it requires a caller
to request it.

**Example**: "Meeting with Alice at 3pm" → "You have 1 calendar event
(details withheld pending consent)."

**Implementation**: `degrade_to_existence(category, item_count)` in both
`agents/_governance/degradation.py` and `shared/governance/degradation.py`.

## Level 4 — Total suppression

**Disclosure**: Empty string returned. Even acknowledging existence would
violate consent (e.g., someone's presence at a sensitive location).

**Trigger**: Explicit `level=4` parameter to `degrade()`, or `level >= 4`.

**Example**: "Meeting with Alice at 3pm" → ""

**Implementation**: `degrade_to_suppression()` returns `""`.

## Escalation policy

Levels 1 and 2 are automatically assigned by `ConsentGatedReader.filter()`:
- No unconsented persons → level 1
- Any unconsented person → level 2

Levels 3 and 4 require explicit caller request via the `level` parameter.
No automatic escalation from level 2 to level 3/4 exists yet. Designing
this escalation policy is a separate task (per-category sensitivity rules,
per-person consent flags).

## Configuration

No operator configuration is required. The `level` parameter defaults to 2
for backward compatibility. Callers that want level 3/4 behavior must pass
it explicitly:

```python
from agents._governance.degradation import degrade

result = degrade(content, unconsented, "calendar", level=3, item_count=5)
```

## Implementation files

| File | Contains |
|------|----------|
| `agents/_governance/degradation.py` | Production `degrade()` with levels 1–4 |
| `shared/governance/degradation.py` | Shared `degrade()` with levels 1–4 |
| `agents/_governance/consent_reader.py` | `ConsentGatedReader.filter()` (currently levels 1–2 only) |
| `tests/test_consent_degradation_levels.py` | 14 tests covering all 4 levels |
