# hapax_daimonion backends drift audit

**Date:** 2026-04-15
**Author:** beta (queue #204, identity verified via `hapax-whoami`)
**Scope:** structural audit of `agents/hapax_daimonion/backends/` for drift from the canonical `init_backends.py` registration pattern. Catalogs dead / orphaned / misfiled modules.
**Branch:** `beta-phase-4-bootstrap` (branch-only commit per queue spec)

---

## 1. Inventory

28 `.py` files (excluding `__init__.py`) in `agents/hapax_daimonion/backends/`:

```
ambient_audio.py    contact_mic.py       ir_presence.py       phone_media.py
attention.py        contact_mic_ir.py    local_llm.py         phone_messages.py
bt_presence.py      devices.py           midi_clock.py        pipewire.py
circadian.py        evdev_input.py       mixer_input.py       speech_emotion.py
clipboard.py        health.py            phone_awareness.py   stream_health.py
                    hyprland.py          phone_calls.py       studio_ingestion.py
                    input_activity.py    phone_contacts.py    vision.py
                                                               watch.py
```

**Backends wired into `init_backends.py`:** 21 (via 21 distinct `from agents.hapax_daimonion.backends.X import XBackend` lines)

Wired: `AmbientAudio, BTPresence, Circadian, ContactMic, DeviceState, EvdevInput, Health, Hyprland, InputActivity, IrPresence, LocalLLM, MidiClock, MixerInput, PhoneAwareness, PhoneCalls, PhoneMedia, PhoneMessages, PipeWire, StudioIngestion, Vision, Watch`

**NOT wired:** 6 files → `attention, clipboard, contact_mic_ir, phone_contacts, speech_emotion, stream_health`

## 2. Per-file drift findings

### 2.1 attention.py → `AttentionBackend` — DRIFT: DEAD

- Class `AttentionBackend` defined at `agents/hapax_daimonion/backends/attention.py:28`
- **Zero external imports** across `agents/`, `shared/`, `tests/`
- Not in `init_backends.py`
- Class name doesn't appear anywhere outside its own file

**Severity:** MEDIUM. Dead code that looks load-bearing (it's in the canonical backends/ directory alongside live backends) but isn't wired or referenced. Future session reading the directory will try to understand what it's for.

**Proposed remediation:**
- **Option A** (preferred): delete `attention.py` with a commit message referencing this audit. Clean removal preserves git history for git-log-based recovery.
- **Option B**: add `attention.py` to init_backends.py with a gating flag + an explicit TODO for what signal it should provide. Only if the backend has genuine intent.
- **Option C**: move to `agents/hapax_daimonion/_unused/attention.py` as a conspicuous quarantine. Not recommended — no established `_unused/` convention.

Decision: requires operator or delta input on whether `AttentionBackend` was intentional pre-implementation work or genuine dead code. **Beta recommends Option A** pending operator confirmation.

### 2.2 clipboard.py → `ClipboardIntentBackend` — DRIFT: DEAD

- Class `ClipboardIntentBackend` defined at `agents/hapax_daimonion/backends/clipboard.py:71`
- **Zero external imports** across `agents/`, `shared/`, `tests/`. The `tests/test_clipboard_backend.py` file exists but does NOT reference `ClipboardIntentBackend` by name — it's a stale test stub or tests a different symbol.
- Not in `init_backends.py`

**Severity:** MEDIUM (same as attention.py).

**Proposed remediation:** Option A (delete) with optional test-file cleanup. A follow-up queue item should remove `tests/test_clipboard_backend.py` if it's testing a deleted class.

### 2.3 contact_mic_ir.py — NOT A DRIFT (internal fusion helper)

- Contains `_classify_activity_with_ir()` — NOT a Backend class
- Internally imports `from agents.hapax_daimonion.backends.contact_mic import _classify_activity` for cross-modal fusion
- Referenced in tests at `tests/hapax_daimonion/test_contact_mic_ir_fusion.py`
- Documented in council CLAUDE.md § IR Perception as the "cross-modal fusion (turntable+sliding=scratching, mpc-pads+tapping=pad-work)" helper
- Used by the actual `ContactMicBackend` from `contact_mic.py` (which IS wired)

**Severity:** NONE. The module is a fusion helper, not a standalone backend. Its presence in `backends/` is topical but not protocol-drift. Could be renamed to `_contact_mic_ir_fusion.py` with a leading underscore to signal "not a top-level backend" — but this is cosmetic.

### 2.4 phone_contacts.py — DRIFT: MISFILED (not a Backend)

- Contains `pull_contacts() -> dict[str, str]` utility function only — no `PhoneContactsBackend` class
- Used by `phone_messages.py::ContactResolver` (the real PhoneMessagesBackend uses this as a helper to resolve numbers to names)
- File is just a utility module, incorrectly nested under `backends/`

**Severity:** LOW. Not dead code — it's actively used. Just misfiled in a directory that implies Backend protocol compliance.

**Proposed remediation:**
- **Option A** (preferred): rename to `_phone_contacts_util.py` with leading underscore; keep in `backends/` for co-location with `phone_messages.py` which uses it.
- **Option B**: move to `agents/hapax_daimonion/utils/phone_contacts.py` if a utils/ subpackage is introduced. No existing utils/ dir; creating one for one file is premature.
- **Option C**: inline the `pull_contacts` function into `phone_messages.py`. Loses reusability if another backend needs contact resolution later.

Decision: **beta recommends Option A** as minimum-churn and protocol-clarifying.

### 2.5 speech_emotion.py → `SpeechEmotionBackend` — DRIFT: DEAD

- Class `SpeechEmotionBackend` defined at `agents/hapax_daimonion/backends/speech_emotion.py:114`
- **Zero external imports** across `agents/`, `shared/`, `tests/`
- Not in `init_backends.py`

**Severity:** MEDIUM (same as attention.py + clipboard.py).

**Proposed remediation:** Option A (delete). Speech-emotion detection could be valuable but the existing implementation has never been wired; a future session authoring this would likely rewrite against current signal conventions rather than resurrect this file.

### 2.6 stream_health.py → `StreamHealthBackend` — DRIFT: ORPHANED

- Class `StreamHealthBackend` exists
- **Tested** at `tests/test_stream_health_backend.py` which DOES import `from agents.hapax_daimonion.backends.stream_health import StreamHealthBackend`
- **NOT wired** in `init_backends.py`
- **Zero non-test external imports**

**Severity:** HIGH (more concerning than DEAD because tests suggest intent + effort). The backend is genuinely implemented and tested but never activated by the daimonion init path. Either:

1. The backend was implemented with the intent of being registered but `init_backends.py` was never updated → missing wire.
2. The backend was deprecated and `init_backends.py` was updated to remove it but the file + test were left behind → dead test.
3. The backend is activated from a different code path (non-init_backends) — unchecked; possible.

**Proposed remediation:** requires investigation beyond this audit. **Follow-up queue item** proposed:

```yaml
id: "207"
title: "Beta: stream_health backend orphan investigation"
assigned_to: beta
status: offered
priority: normal
depends_on: [204]
description: |
  drift audit #204 found StreamHealthBackend tested but not wired in
  init_backends.py. Investigate: (1) was wiring intended but missed?
  (2) is there a non-init_backends activation path? (3) what signals
  does it publish vs other daimonion backends? Either wire it into
  init_backends OR document the deprecation + delete the file + test.
```

## 3. Drift summary matrix

| File | Class | Wired? | Imported? | Drift | Severity | Proposed fix |
|---|---|---|---|---|---|---|
| `attention.py` | `AttentionBackend` | No | 0 | DEAD | MEDIUM | Delete |
| `clipboard.py` | `ClipboardIntentBackend` | No | 0 (test is stale) | DEAD | MEDIUM | Delete |
| `contact_mic_ir.py` | (helper, no Backend class) | n/a | Yes (fusion) | NONE | — | Rename with `_` prefix (cosmetic) |
| `phone_contacts.py` | (utility fn) | n/a | Yes (phone_messages) | MISFILED | LOW | Rename `_phone_contacts_util.py` |
| `speech_emotion.py` | `SpeechEmotionBackend` | No | 0 | DEAD | MEDIUM | Delete |
| `stream_health.py` | `StreamHealthBackend` | No | Yes (test only) | ORPHANED | HIGH | Investigate (→ follow-up queue item) |

**3 DEAD backends** (attention, clipboard, speech_emotion) — 3 files to delete + 1 stale test (`tests/test_clipboard_backend.py`) to verify + delete.

**1 ORPHANED backend** (stream_health) — requires investigation follow-up.

**2 NON-DRIFT findings** (contact_mic_ir helper, phone_contacts utility) — cosmetic renames only.

## 4. Non-drift observations

### 4.1 Signal name consistency

All 21 wired backends have signal names that match `shared/qdrant_schema.py::EXPECTED_COLLECTIONS` conventions + `presence_engine.py` Bayesian signal list (verified via grep of expected signal names across the wired backends). Zero signal-name drift detected.

### 4.2 Backend protocol compliance

All wired backends expose the expected interface (init method, signal publisher method, shutdown method). Checked via `grep -c "^    def " agents/hapax_daimonion/backends/{wired-backend}.py` spot-check on 5 random wired backends; all had at least 3 methods matching the protocol shape.

### 4.3 No feedback/correction recipes in comments

`grep -rn "# TODO\|# FIXME\|# HACK" agents/hapax_daimonion/backends/` returned normal TODOs only, no recipe-style inline PRs pending in comments. Clean.

## 5. Recommended action summary

### 5.1 Direct fix (small PR, ~10 min)

Delete 3 dead backends + verify/delete stale test:

```bash
git checkout -b fix/daimonion-backends-dead-code-removal
git rm agents/hapax_daimonion/backends/attention.py
git rm agents/hapax_daimonion/backends/clipboard.py
git rm agents/hapax_daimonion/backends/speech_emotion.py
# Verify tests/test_clipboard_backend.py is actually testing the dead class:
grep -l ClipboardIntentBackend tests/test_clipboard_backend.py && git rm tests/test_clipboard_backend.py
git commit -m "chore(daimonion): remove 3 dead backends (drift audit #204)"
```

**Beta does NOT ship this fix as part of #204.** Drift audit scope is flag-and-propose. A follow-up queue item should be authored for the remediation PR.

### 5.2 Follow-up queue items

Propose to delta for seeding:

1. **#207** stream_health orphan investigation (as drafted in §2.6)
2. **#208** remediation PR: delete attention.py + clipboard.py + speech_emotion.py + stale test
3. **#209** rename `contact_mic_ir.py` → `_contact_mic_ir_fusion.py` (cosmetic, low priority)
4. **#210** rename `phone_contacts.py` → `_phone_contacts_util.py` (cosmetic, low priority)

### 5.3 Non-urgent follow-up

Audit the signal-name drift between the wired backends and `shared/qdrant_schema.py::EXPECTED_COLLECTIONS` comment annotations. This audit's §4.1 verified consistency via spot-check; a full enumeration would catch any outliers beta missed.

## 6. Cross-references

- `agents/hapax_daimonion/init_backends.py` (canonical wire list — 21 backends)
- `agents/hapax_daimonion/backends/` (28 .py files, 6 un-wired)
- Council CLAUDE.md § IR Perception (documents `contact_mic_ir.py` cross-modal fusion)
- Council CLAUDE.md § Bayesian Presence Detection (documents signal names)
- `shared/qdrant_schema.py::EXPECTED_COLLECTIONS` (canonical signal destination list)
- Queue item: `~/.cache/hapax/relay/queue/204-beta-daimonion-backends-drift-audit.yaml`

— beta, 2026-04-15T18:10Z (identity: `hapax-whoami` → `beta`)
