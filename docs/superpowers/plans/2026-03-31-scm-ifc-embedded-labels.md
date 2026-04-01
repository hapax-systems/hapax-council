# IFC Embedded Labels

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the consent algebra operational across process boundaries by embedding consent labels in JSON payloads, so labels survive /dev/shm serialization.

**Architecture:** New `shared/labeled_trace.py` provides `write_labeled_trace()` and `read_labeled_trace()` that inject/extract `_consent` metadata in JSON. Gradual migration: readers treat absent `_consent` as bottom (public). Writers upgraded one at a time, person-adjacent first. Five boundary gates enforce at egress.

**Tech Stack:** Python 3.12+, ConsentLabel (shared/governance/consent_label.py), JSON serialization

**Source research:** `docs/research/2026-03-31-scm-concrete-formalizations.md` §8

---

### Task 1: Create Labeled Trace I/O Module

**Files:**
- Create: `shared/labeled_trace.py`
- Test: `tests/test_labeled_trace.py`

- [ ] **Step 1: Write test**

```python
# tests/test_labeled_trace.py
"""Test consent-labeled trace I/O."""

import json
from pathlib import Path

from shared.governance.consent_label import ConsentLabel


def test_write_read_roundtrip(tmp_path):
    from shared.labeled_trace import read_labeled_trace, write_labeled_trace

    label = ConsentLabel(frozenset({("alice", frozenset({"operator"}))}))
    path = tmp_path / "state.json"
    write_labeled_trace(path, {"value": 42}, label, provenance=frozenset({"contract-1"}))

    data, recovered_label = read_labeled_trace(path, stale_s=30.0)
    assert data is not None
    assert data["value"] == 42
    assert "_consent" not in data  # popped by reader
    assert recovered_label is not None
    assert recovered_label.policies == label.policies


def test_write_null_label(tmp_path):
    from shared.labeled_trace import read_labeled_trace, write_labeled_trace

    path = tmp_path / "state.json"
    write_labeled_trace(path, {"value": 1}, None)

    data, label = read_labeled_trace(path, stale_s=30.0)
    assert data is not None
    assert label == ConsentLabel.bottom()


def test_read_legacy_file_returns_bottom(tmp_path):
    from shared.labeled_trace import read_labeled_trace

    path = tmp_path / "state.json"
    path.write_text(json.dumps({"value": 1}))  # no _consent field

    data, label = read_labeled_trace(path, stale_s=30.0)
    assert data is not None
    assert label == ConsentLabel.bottom()


def test_stale_file_returns_none(tmp_path):
    import os
    import time

    from shared.labeled_trace import read_labeled_trace

    path = tmp_path / "state.json"
    path.write_text(json.dumps({"value": 1}))
    os.utime(path, (time.time() - 60, time.time() - 60))

    data, label = read_labeled_trace(path, stale_s=10.0)
    assert data is None
    assert label is None
```

- [ ] **Step 2: Implement**

```python
# shared/labeled_trace.py
"""Consent-labeled /dev/shm trace I/O.

Extension of shared/trace_reader.py that embeds/extracts ConsentLabel
in the _consent envelope. Writers use write_labeled_trace() to attach
labels. Readers use read_labeled_trace() to reconstruct ConsentLabel.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from shared.governance.consent_label import ConsentLabel


def serialize_label(
    label: ConsentLabel | None, provenance: frozenset[str] = frozenset()
) -> dict | None:
    """Serialize ConsentLabel to _consent JSON envelope."""
    if label is None:
        return None
    return {
        "label": [
            {"owner": owner, "readers": sorted(readers)}
            for owner, readers in sorted(label.policies)
        ],
        "provenance": sorted(provenance),
        "labeled_at": time.time(),
    }


def deserialize_label(consent_data: dict | None) -> tuple[ConsentLabel, frozenset[str]]:
    """Reconstruct ConsentLabel from _consent JSON."""
    if consent_data is None:
        return ConsentLabel.bottom(), frozenset()
    policies: set[tuple[str, frozenset[str]]] = set()
    for entry in consent_data.get("label", []):
        owner = entry.get("owner", "")
        readers = frozenset(entry.get("readers", []))
        if owner:
            policies.add((owner, readers))
    provenance = frozenset(str(x) for x in consent_data.get("provenance", []))
    return ConsentLabel(frozenset(policies)), provenance


def write_labeled_trace(
    path: Path,
    data: dict,
    label: ConsentLabel | None,
    provenance: frozenset[str] = frozenset(),
) -> None:
    """Write JSON trace with embedded consent label. Atomic (tmp + rename)."""
    enriched = {**data, "_consent": serialize_label(label, provenance)}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(enriched), encoding="utf-8")
    os.replace(str(tmp), str(path))


def read_labeled_trace(
    path: Path, stale_s: float
) -> tuple[dict | None, ConsentLabel | None]:
    """Read JSON trace with staleness check and consent extraction.

    Returns (data_without_consent, label) or (None, None) if stale/missing.
    """
    try:
        age = time.time() - path.stat().st_mtime
        if age > stale_s:
            return None, None
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, None
    consent_data = raw.pop("_consent", None)
    label, _provenance = deserialize_label(consent_data)
    return raw, label
```

- [ ] **Step 3: Run tests, commit**

```bash
uv run pytest tests/test_labeled_trace.py -v
git commit -m "feat: labeled trace I/O — consent labels survive /dev/shm serialization"
```

---

### Task 2: Migrate Perception State Writer

The first person-adjacent writer to embed labels.

**Files:**
- Modify: `agents/hapax_daimonion/_perception_state_writer.py` (or wherever perception-state.json is written)

- [ ] **Step 1: Find and read the writer**

Search for the function that writes `/dev/shm/hapax-daimonion/perception-state.json`. Read it. Replace `json.dumps()` + atomic rename with `write_labeled_trace()`. The label comes from `ConsentStateTracker.phase`:
- NO_GUEST → `ConsentLabel.bottom()`
- CONSENT_GRANTED → `ConsentLabel.from_contract(active_contract)`
- GUEST_DETECTED / CONSENT_PENDING / CONSENT_REFUSED → restricted label

- [ ] **Step 2: Implement, test, commit**

```bash
git commit -m "feat(consent): embed consent label in perception-state.json"
```

---

### Task 3: Migrate DMN Observations Writer

**Files:**
- Modify: `agents/dmn/__main__.py` (the `publish_observations` call)

- [ ] **Step 1: Update DMN to propagate label from perception**

In `_write_output()`, after reading the sensor snapshot, extract the `_consent` field from perception-state.json and propagate it to observations.json via `write_labeled_trace()`.

- [ ] **Step 2: Commit**

```bash
git commit -m "feat(consent): propagate consent label through DMN observations"
```

---

### Task 4: Migrate Imagination Daemon Writer

**Files:**
- Modify: `agents/imagination_daemon/__main__.py`

- [ ] **Step 1: Read observation label, propagate to fragment**

When reading observations via `read_labeled_trace()`, capture the label. When the imagination loop produces a fragment, write `current.json` via `write_labeled_trace()` with the joined label.

- [ ] **Step 2: Commit**

```bash
git commit -m "feat(consent): propagate consent label through imagination fragments"
```

---

### Task 5: Add API Egress Gate

**Files:**
- Create: `logos/api/deps/consent_gate.py`

- [ ] **Step 1: Implement gate dependency**

```python
# logos/api/deps/consent_gate.py
"""API egress gate — check _consent labels before serving data."""

from shared.governance.consent_label import ConsentLabel
from shared.labeled_trace import deserialize_label


def gate_response(data: dict, target_label: ConsentLabel = ConsentLabel.bottom()) -> dict:
    """Check _consent label before API egress.

    For single-operator: target is always bottom (operator reads everything).
    Gate exists for structural completeness and future guest-facing surfaces.
    """
    consent_data = data.pop("_consent", None)
    if consent_data is None:
        return data
    label, _prov = deserialize_label(consent_data)
    if label.can_flow_to(target_label):
        return data
    return {"_redacted": True, "reason": "consent_label_flow_denied"}
```

- [ ] **Step 2: Commit**

```bash
git commit -m "feat(consent): API egress gate for labeled trace responses"
```
