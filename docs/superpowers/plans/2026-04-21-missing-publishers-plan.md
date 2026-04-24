# FINDING-V — Missing Publishers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close FINDING-V by capturing the shipped state, fixing the single drift artefact (a missing systemd timer unit file in the repo), and retiring the three false-missings with regression pins that prevent a future audit from reopening them.

**Architecture:** Three publishers are already live (`recent-impingements.json`, `youtube-viewer-count.txt`, `chat-state.json`). Three "missing" files are false-missings — the consumers read a different path that already has an upstream. One timer unit file exists in live user-systemd state but has drifted out of the repo. This plan adds one missing unit file, five regression pins, and closes FINDING-V in the audit tracker.

**Tech Stack:** systemd user units, pytest source-grep pins, pydantic for schema pins.

**Spec:** `docs/superpowers/specs/2026-04-21-missing-publishers-design.md`
**Research:** `docs/research/2026-04-21-missing-publishers-research.md`

---

### Task 1: Restore `hapax-youtube-viewer-count.timer` unit file in the repo

**Files:**
- Create: `systemd/units/hapax-youtube-viewer-count.timer`
- Source: copy from `~/.config/systemd/user/hapax-youtube-viewer-count.timer` (live state)

- [ ] **Step 1: Copy the live unit file into the repo**

Read the live unit:

```bash
cat ~/.config/systemd/user/hapax-youtube-viewer-count.timer
```

Write an identical file at `systemd/units/hapax-youtube-viewer-count.timer`. Do NOT retype by hand — preserve exact formatting (including `[Unit]`, `[Timer]`, `[Install]` sections and `OnCalendar=` / `OnBootSec=` / `OnUnitActiveSec=` directives as they are). This is drift-capture, not redesign.

- [ ] **Step 2: Verify `systemctl --user status hapax-youtube-viewer-count.timer` reports `Loaded: loaded` instead of `not-found`**

After the file is in the repo, run the deploy step (`systemd/README.md` install step, or equivalent `cp` + `systemctl --user daemon-reload`). Confirm:

```bash
systemctl --user status hapax-youtube-viewer-count.timer | head -5
```

Expected: `Loaded: loaded (~/.config/systemd/user/hapax-youtube-viewer-count.timer; enabled)`.

- [ ] **Step 3: Commit**

```bash
git add systemd/units/hapax-youtube-viewer-count.timer
git commit -m "fix(systemd): restore hapax-youtube-viewer-count.timer (FINDING-V timer drift)"
```

---

### Task 2: Add systemd-units regression pin

**Files:**
- Create: `tests/systemd/test_publisher_units_present.py`

- [ ] **Step 1: Write the failing test**

```python
"""Regression pin: FINDING-V publisher systemd units must exist in repo.

Catches drift where a unit file is deployed to the user systemd dir
and then silently deleted from ``systemd/units/`` (what happened with
hapax-youtube-viewer-count.timer between 2026-04-22 and 2026-04-24).
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS_DIR = REPO_ROOT / "systemd" / "units"

FINDING_V_PUBLISHER_UNITS = (
    "hapax-recent-impingements.service",
    "hapax-youtube-viewer-count.service",
    "hapax-youtube-viewer-count.timer",
)


@pytest.mark.parametrize("unit_name", FINDING_V_PUBLISHER_UNITS)
def test_finding_v_publisher_unit_present(unit_name: str) -> None:
    unit_path = UNITS_DIR / unit_name
    assert unit_path.exists(), (
        f"{unit_name} missing from {UNITS_DIR}. FINDING-V publishers must "
        "ship with their unit files in the repo — live-only units drift "
        "silently when daemon-reload is triggered."
    )
```

- [ ] **Step 2: Run test to verify it passes after Task 1**

```bash
uv run pytest tests/systemd/test_publisher_units_present.py -q
```

Expected: `3 passed` (all three units now present).

- [ ] **Step 3: Commit**

```bash
git add tests/systemd/test_publisher_units_present.py
git commit -m "test(systemd): pin FINDING-V publisher units to prevent drift"
```

---

### Task 3: Pin `chat_ambient_ward` canonical input path (retire false-missing)

**Files:**
- Create: `tests/studio_compositor/test_chat_ambient_ward_canonical_input.py`

- [ ] **Step 1: Write the pin test**

```python
"""Regression pin: chat_ambient_ward reads hapax-chat-signals.json.

FINDING-V audit (2026-04-20) listed chat-keyword-aggregate.json and
chat-tier-aggregates.json as "missing publishers". Those filenames
were aspirational and never matched the shipped consumer — the ward
reads hapax-chat-signals.json which is produced by chat-monitor.service.

This pin prevents a future audit from reopening the false-missing
entries by asserting the canonical input path is hapax-chat-signals
and that neither "missing" filename appears in the consumer.
"""

from __future__ import annotations

from pathlib import Path

WARD = (
    Path(__file__).resolve().parents[2]
    / "agents"
    / "studio_compositor"
    / "chat_ambient_ward.py"
)


def test_ward_references_hapax_chat_signals() -> None:
    text = WARD.read_text()
    assert "hapax-chat-signals" in text, (
        "chat_ambient_ward.py must reference the canonical "
        "hapax-chat-signals input — FINDING-V spec 2026-04-21."
    )


def test_ward_does_not_reference_deprecated_audit_filenames() -> None:
    """The two FINDING-V audit filenames are false-missings.

    If a future engineer implements one of these files, they also need
    to update the consumer, the FINDING-V spec + plan, and remove this
    pin. The pin exists to force that conversation.
    """
    text = WARD.read_text()
    assert "chat-keyword-aggregate" not in text
    assert "chat-tier-aggregates" not in text
```

- [ ] **Step 2: Run test**

```bash
uv run pytest tests/studio_compositor/test_chat_ambient_ward_canonical_input.py -q
```

Expected: `2 passed`.

- [ ] **Step 3: Commit**

```bash
git add tests/studio_compositor/test_chat_ambient_ward_canonical_input.py
git commit -m "test(compositor): pin chat_ambient_ward canonical input (retires FINDING-V false-missing)"
```

---

### Task 4: Pin grounding-provenance ticker tails director-intent.jsonl (retire false-missing)

**Files:**
- Create: `tests/studio_compositor/test_grounding_ticker_intent_read.py`

- [ ] **Step 1: Write the pin test**

```python
"""Regression pin: grounding_provenance_ticker reads director-intent.jsonl.

FINDING-V audit listed grounding-provenance.jsonl as a "missing
publisher" but the consumer already has a working upstream — it tails
director-intent.jsonl and reads grounding_provenance off the last
entry. A separate SHM file would duplicate data and add staleness.

This pin prevents a future audit from reopening the false-missing.
"""

from __future__ import annotations

from pathlib import Path

LEGIBILITY = (
    Path(__file__).resolve().parents[2]
    / "agents"
    / "studio_compositor"
    / "legibility_sources.py"
)


def test_ticker_reads_director_intent_jsonl() -> None:
    text = LEGIBILITY.read_text()
    assert "director-intent.jsonl" in text, (
        "legibility_sources.py must read director-intent.jsonl — "
        "FINDING-V spec 2026-04-21 confirmed no separate "
        "grounding-provenance.jsonl is needed."
    )
    assert "_read_latest_intent" in text, (
        "_read_latest_intent tailer must exist — retirement rationale "
        "depends on this reader."
    )


def test_no_separate_grounding_provenance_file() -> None:
    """Retirement contract: no code creates a separate grounding-provenance.jsonl.

    The FINDING-V audit conflated "data not in a separate SHM file"
    with "no producer." Director INTENT JSONL already carries the
    provenance array. Creating a second file would be a regression.
    """
    text = LEGIBILITY.read_text()
    assert "grounding-provenance.jsonl" not in text, (
        "legibility_sources.py must NOT reference a separate "
        "grounding-provenance.jsonl — ward tails director INTENT JSONL."
    )
```

- [ ] **Step 2: Run test**

```bash
uv run pytest tests/studio_compositor/test_grounding_ticker_intent_read.py -q
```

Expected: `2 passed`.

- [ ] **Step 3: Commit**

```bash
git add tests/studio_compositor/test_grounding_ticker_intent_read.py
git commit -m "test(compositor): pin grounding ticker reads director-intent.jsonl (retires FINDING-V false-missing)"
```

---

### Task 5: Pin chat_signals publisher wiring

**Files:**
- Create: `tests/studio_compositor/test_chat_signals_publishers.py`

- [ ] **Step 1: Write the pin test**

```python
"""Regression pin: chat-state.json has a production producer.

FINDING-V audit listed chat-state.json as production-unwritten
(only mock-chat.py wrote it). This was closed by chat-monitor.service
(scripts/chat-monitor.py) plus the ChatSignals.publish_chat_state_sidecar
enrichment path. This pin prevents a future refactor from removing
the production writer without replacement.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHAT_MONITOR = REPO_ROOT / "scripts" / "chat-monitor.py"
CHAT_SIGNALS = REPO_ROOT / "agents" / "studio_compositor" / "chat_signals.py"


def test_chat_monitor_references_chat_state_path() -> None:
    text = CHAT_MONITOR.read_text()
    assert "chat-state.json" in text, (
        "chat-monitor.py must write chat-state.json — FINDING-V "
        "production producer."
    )


def test_chat_signals_sidecar_present() -> None:
    text = CHAT_SIGNALS.read_text()
    assert "publish_chat_state_sidecar" in text, (
        "ChatSignals must expose publish_chat_state_sidecar — secondary "
        "producer path for chat-state.json."
    )
```

- [ ] **Step 2: Run test**

```bash
uv run pytest tests/studio_compositor/test_chat_signals_publishers.py -q
```

Expected: `2 passed`.

- [ ] **Step 3: Commit**

```bash
git add tests/studio_compositor/test_chat_signals_publishers.py
git commit -m "test(compositor): pin chat-state.json production producer"
```

---

### Task 6: Close FINDING-V in tracker + cc-task

**Files:**
- Modify: `docs/research/2026-04-20-wiring-audit-findings.md` — add a FINDING-V §closure note pointing at this plan
- Close via `scripts/cc-close` in the vault:
  - `finding-v-publishers` (this task)
  - `ef7b-178` (parent native task; spec supersedes)

- [ ] **Step 1: Add closure note to the wiring audit**

Append a §"FINDING-V — closure (2026-04-24)" section under the existing FINDING-V header pointing at `docs/superpowers/specs/2026-04-21-missing-publishers-design.md` and `docs/superpowers/plans/2026-04-21-missing-publishers-plan.md`. Note shipped-vs-retired verdicts in one line each.

- [ ] **Step 2: Close cc-tasks**

```bash
CLAUDE_ROLE=delta scripts/cc-close finding-v-publishers --pr <PR#>
CLAUDE_ROLE=delta scripts/cc-close ef7b-178 --pr <PR#>
```

- [ ] **Step 3: Commit the audit doc update**

```bash
git add docs/research/2026-04-20-wiring-audit-findings.md
git commit -m "docs(audit): mark FINDING-V closed (3 shipped, 3 false-missings retired)"
```

---

### Task 7: Open PR

- [ ] **Step 1: Push branch**

```bash
git push -u origin feat/finding-v-publishers-research-spec-plan
```

- [ ] **Step 2: Open PR**

Title: `chore(FINDING-V): close — spec + plan + drift fix + 5 regression pins`

Body:

- Summary of the 6-publisher status audit (3 shipped, 3 retired as false-missings)
- Single drift fix: `hapax-youtube-viewer-count.timer` captured back into repo
- 5 regression pins covering the three shipped producers + the two retirement contracts
- Cross-links to research + spec + audit closure note
- Test plan: all five pin tests pass locally; CI runs full compositor suite

- [ ] **Step 3: Monitor CI, admin-merge per rubric v2 on disjoint failures or TIMED-OUT**

---

## Phase Ordering Rationale

Phases are ordered by dependency:

1. **Task 1** (timer restoration) is the only code gap. Do first so Task 2's pin passes.
2. **Task 2** (systemd units pin) prevents recurrence of Task 1's drift.
3. **Tasks 3–5** (retirement + shipped-producer pins) can run in any order; they are independent. Ship together for PR cohesion.
4. **Task 6** (tracker closure) depends on 1–5 passing so the audit note can cite concrete SHAs.
5. **Task 7** (PR) is the ship step.

Rollback: each task is a standalone commit. A regression in one pin can be reverted without losing the others.

## Dependencies on Existing Services

- `systemctl --user daemon-reload` to re-materialise the timer unit after Task 1.
- `hapax-rebuild-services.timer` (5-min cadence) will pick up the timer-unit change automatically on the next tick, but a manual `daemon-reload` is faster for verification.

## Operator Decisions Needed

None. All verdicts in the spec are session-authoritative per `feedback_no_operator_approval_waits` (2026-04-24T19:10Z directive).

## Risks

- **Nothing currently broken.** Three publishers are live; three wards already render from alternate upstreams. The drift on `hapax-youtube-viewer-count.timer` is latent — if a rebuild deletes the live unit file before the repo is updated, viewer count freezes until restored.
- **Retirement pins may become load-bearing.** If a future engineer wants to add a `chat-keyword-aggregate.json` file for a new reason, they will hit Task 3's pin and be forced to update this spec first. That is the intended behaviour.

## Out of Scope

- **FINDING-W** (pre_fx/post_fx cairooverlay) — shipped in PRs #1316 + #1330.
- **FINDING-V Q4 chat-keywords consumer ward** (ef7b-180) — separate research + design task for a new ward.
- **FINDING-V-corollary** (HARDM perception source emptiness) — alpha-owned.
- **Any implementation beyond what is specified above** — no new publishers, no new wards, no cadence changes.
