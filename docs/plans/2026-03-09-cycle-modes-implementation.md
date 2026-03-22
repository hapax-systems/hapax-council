# Cycle Modes (Dev/Prod) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add dev/prod cycle modes to contract timer schedules and agent thresholds during heavy development.

**Architecture:** A mode file (`~/.cache/hapax/cycle-mode`) is the single source of truth. A shared Python module reads it. A bash script writes it and installs systemd timer overrides. The logos API exposes GET/PUT endpoints. Agents read the mode at invocation to adjust internal thresholds.

**Tech Stack:** Python 3.12, FastAPI, systemd timers, bash, pytest

---

### Task 1: Create `shared/cycle_mode.py` + tests

**Files:**
- Create: `shared/cycle_mode.py`
- Create: `tests/test_cycle_mode.py`

**Step 1: Write the failing tests**

Create `tests/test_cycle_mode.py`:

```python
"""Tests for shared.cycle_mode — cycle mode reader."""
from __future__ import annotations

from unittest.mock import patch
from pathlib import Path

import pytest


def test_cycle_mode_enum_has_two_members():
    from shared.cycle_mode import CycleMode
    assert set(CycleMode) == {CycleMode.PROD, CycleMode.DEV}


def test_get_cycle_mode_default_prod(tmp_path):
    """Missing file defaults to prod."""
    from shared.cycle_mode import get_cycle_mode, CycleMode
    with patch("shared.cycle_mode.MODE_FILE", tmp_path / "nonexistent"):
        assert get_cycle_mode() == CycleMode.PROD


def test_get_cycle_mode_reads_dev(tmp_path):
    """File containing 'dev' returns DEV."""
    from shared.cycle_mode import get_cycle_mode, CycleMode
    mode_file = tmp_path / "cycle-mode"
    mode_file.write_text("dev\n")
    with patch("shared.cycle_mode.MODE_FILE", mode_file):
        assert get_cycle_mode() == CycleMode.DEV


def test_get_cycle_mode_reads_prod(tmp_path):
    """File containing 'prod' returns PROD."""
    from shared.cycle_mode import get_cycle_mode, CycleMode
    mode_file = tmp_path / "cycle-mode"
    mode_file.write_text("prod\n")
    with patch("shared.cycle_mode.MODE_FILE", mode_file):
        assert get_cycle_mode() == CycleMode.PROD


def test_get_cycle_mode_invalid_defaults_prod(tmp_path):
    """File containing garbage defaults to prod."""
    from shared.cycle_mode import get_cycle_mode, CycleMode
    mode_file = tmp_path / "cycle-mode"
    mode_file.write_text("turbo\n")
    with patch("shared.cycle_mode.MODE_FILE", mode_file):
        assert get_cycle_mode() == CycleMode.PROD
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cycle_mode.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'shared.cycle_mode'`

**Step 3: Write minimal implementation**

Create `shared/cycle_mode.py`:

```python
"""shared/cycle_mode.py — Cycle mode reader.

Single source of truth for the current cycle mode (dev or prod).
The mode file is written by the hapax-mode CLI script and the
logos API. Agents read it at invocation to adjust thresholds.
"""
from __future__ import annotations

from enum import StrEnum
from pathlib import Path


class CycleMode(StrEnum):
    PROD = "prod"
    DEV = "dev"


MODE_FILE = Path.home() / ".cache" / "hapax" / "cycle-mode"


def get_cycle_mode() -> CycleMode:
    """Read the current cycle mode. Defaults to PROD if file is missing or invalid."""
    try:
        return CycleMode(MODE_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return CycleMode.PROD
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cycle_mode.py -v`
Expected: 5 passed

**Step 5: Commit**

```bash
git add shared/cycle_mode.py tests/test_cycle_mode.py
git commit -m "feat: add cycle mode reader (shared/cycle_mode.py)"
```

---

### Task 2: Create systemd timer override files

**Files:**
- Create: `systemd/overrides/dev/claude-code-sync.timer`
- Create: `systemd/overrides/dev/obsidian-sync.timer`
- Create: `systemd/overrides/dev/chrome-sync.timer`
- Create: `systemd/overrides/dev/gdrive-sync.timer`
- Create: `systemd/overrides/dev/profile-update.timer`
- Create: `systemd/overrides/dev/digest.timer`
- Create: `systemd/overrides/dev/daily-briefing.timer`
- Create: `systemd/overrides/dev/drift-detector.timer`
- Create: `systemd/overrides/dev/knowledge-maint.timer`
- Create: `tests/test_timer_overrides.py`

**Step 1: Write the failing test**

Create `tests/test_timer_overrides.py`:

```python
"""Tests for systemd timer override files — validates syntax and structure."""
from __future__ import annotations

import configparser
from pathlib import Path

import pytest

OVERRIDES_DIR = Path(__file__).parent.parent / "systemd" / "overrides" / "dev"

EXPECTED_TIMERS = [
    "claude-code-sync.timer",
    "obsidian-sync.timer",
    "chrome-sync.timer",
    "gdrive-sync.timer",
    "profile-update.timer",
    "digest.timer",
    "daily-briefing.timer",
    "drift-detector.timer",
    "knowledge-maint.timer",
]


def test_all_override_files_exist():
    for name in EXPECTED_TIMERS:
        assert (OVERRIDES_DIR / name).is_file(), f"Missing override: {name}"


@pytest.mark.parametrize("timer_name", EXPECTED_TIMERS)
def test_override_has_timer_section(timer_name):
    """Each override must have a [Timer] section with schedule directives."""
    parser = configparser.ConfigParser()
    parser.read(OVERRIDES_DIR / timer_name)
    assert "Timer" in parser.sections(), f"{timer_name} missing [Timer] section"
    timer_section = dict(parser["Timer"])
    has_schedule = any(
        k in timer_section
        for k in ("oncalendar", "onbootsec", "onunitactivesec")
    )
    assert has_schedule, f"{timer_name} has no schedule directive"


def test_override_count_matches():
    """No extra override files beyond the expected set."""
    actual = {f.name for f in OVERRIDES_DIR.glob("*.timer")}
    assert actual == set(EXPECTED_TIMERS)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_timer_overrides.py -v`
Expected: FAIL with `Missing override: claude-code-sync.timer`

**Step 3: Create the override files**

Each file is a systemd timer drop-in containing only the `[Timer]` section. When installed as `<timer>.timer.d/override.conf`, systemd merges it with the base timer. We must clear existing schedule directives first (empty assignment) before setting new ones.

Create `systemd/overrides/dev/claude-code-sync.timer`:

```ini
[Timer]
OnCalendar=
OnCalendar=*-*-* *:00/10:00
RandomizedDelaySec=30
```

Create `systemd/overrides/dev/obsidian-sync.timer`:

```ini
[Timer]
OnCalendar=
OnCalendar=*-*-* *:00/10:00
RandomizedDelaySec=30
```

Create `systemd/overrides/dev/chrome-sync.timer`:

```ini
[Timer]
OnCalendar=
OnCalendar=*-*-* *:00/20:00
RandomizedDelaySec=60
```

Create `systemd/overrides/dev/gdrive-sync.timer`:

```ini
[Timer]
OnCalendar=
OnCalendar=*-*-* *:00:00
RandomizedDelaySec=120
```

Create `systemd/overrides/dev/profile-update.timer`:

```ini
[Timer]
OnBootSec=
OnUnitActiveSec=
OnBootSec=5min
OnUnitActiveSec=45min
RandomizedDelaySec=5min
```

Create `systemd/overrides/dev/digest.timer`:

```ini
[Timer]
OnCalendar=
OnCalendar=*-*-* 00/2:45:00
```

Create `systemd/overrides/dev/daily-briefing.timer`:

```ini
[Timer]
OnCalendar=
OnCalendar=*-*-* 03/4:00:00
```

Create `systemd/overrides/dev/drift-detector.timer`:

```ini
[Timer]
OnCalendar=
OnCalendar=*-*-* 03:00:00
RandomizedDelaySec=5min
```

Create `systemd/overrides/dev/knowledge-maint.timer`:

```ini
[Timer]
OnCalendar=
OnCalendar=*-*-* 04:30:00
RandomizedDelaySec=5min
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_timer_overrides.py -v`
Expected: 11 passed (1 existence + 9 parametrized section + 1 count)

**Step 5: Commit**

```bash
git add systemd/overrides/ tests/test_timer_overrides.py
git commit -m "feat: add dev-mode systemd timer overrides"
```

---

### Task 3: Create `hapax-mode` CLI script

**Files:**
- Create: `scripts/hapax-mode`

**Step 1: Write the script**

Create `scripts/hapax-mode`:

```bash
#!/usr/bin/env bash
set -euo pipefail

# Cycle mode switcher for hapax agent timers.
# Usage: hapax-mode [dev|prod]
#   No argument: print current mode.

MODE_FILE="$HOME/.cache/hapax/cycle-mode"
OVERRIDES_SRC="$(dirname "$(readlink -f "$0")")/../systemd/overrides/dev"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"

TIMERS=(
    claude-code-sync
    obsidian-sync
    chrome-sync
    gdrive-sync
    profile-update
    digest
    daily-briefing
    drift-detector
    knowledge-maint
)

current_mode() {
    if [[ -f "$MODE_FILE" ]]; then
        cat "$MODE_FILE"
    else
        echo "prod"
    fi
}

# No argument: print current mode
if [[ $# -eq 0 ]]; then
    echo "$(current_mode)"
    exit 0
fi

MODE="$1"
if [[ "$MODE" != "dev" && "$MODE" != "prod" ]]; then
    echo "Usage: hapax-mode [dev|prod]" >&2
    exit 1
fi

# Write mode file
mkdir -p "$(dirname "$MODE_FILE")"
echo "$MODE" > "$MODE_FILE"

if [[ "$MODE" == "dev" ]]; then
    # Install timer overrides
    for timer in "${TIMERS[@]}"; do
        drop_in="$SYSTEMD_USER_DIR/${timer}.timer.d"
        mkdir -p "$drop_in"
        cp "$OVERRIDES_SRC/${timer}.timer" "$drop_in/override.conf"
    done
    echo "Installed dev timer overrides for ${#TIMERS[@]} timers"
else
    # Remove timer overrides
    for timer in "${TIMERS[@]}"; do
        drop_in="$SYSTEMD_USER_DIR/${timer}.timer.d"
        rm -rf "$drop_in"
    done
    echo "Removed dev timer overrides"
fi

# Reload systemd and restart affected timers
systemctl --user daemon-reload
for timer in "${TIMERS[@]}"; do
    systemctl --user restart "${timer}.timer" 2>/dev/null || true
done

# Notify
if command -v curl &>/dev/null; then
    curl -s -o /dev/null \
        -H "Title: Hapax Cycle Mode" \
        -d "Cycle mode → $MODE" \
        "http://127.0.0.1:8090/hapax" 2>/dev/null || true
fi

echo "Cycle mode → $MODE"

# Print active schedules for affected timers
echo ""
echo "Active schedules:"
for timer in "${TIMERS[@]}"; do
    next=$(systemctl --user show "${timer}.timer" -p NextElapseUSecRealtime --value 2>/dev/null || echo "unknown")
    printf "  %-24s %s\n" "${timer}" "$next"
done
```

**Step 2: Make executable**

```bash
chmod +x scripts/hapax-mode
```

**Step 3: Manual verification**

Run: `scripts/hapax-mode`
Expected: Prints `prod` (default, no mode file exists yet)

Run: `scripts/hapax-mode dev`
Expected: Installs overrides, prints "Cycle mode → dev" and schedule summary

Run: `scripts/hapax-mode prod`
Expected: Removes overrides, prints "Cycle mode → prod" and schedule summary

Run: `scripts/hapax-mode`
Expected: Prints `prod`

**Step 4: Commit**

```bash
git add scripts/hapax-mode
git commit -m "feat: add hapax-mode CLI script for cycle switching"
```

---

### Task 4: Update agent thresholds to be mode-aware

**Files:**
- Modify: `cockpit/micro_probes.py:17-19`
- Modify: `logos/api/cache.py:131-132`
- Modify: `tests/test_micro_probes.py:13-14`
- Create: `tests/test_cycle_mode_integration.py`

**Step 1: Write the failing integration tests**

Create `tests/test_cycle_mode_integration.py`:

```python
"""Integration tests for cycle mode affecting agent thresholds."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from shared.cycle_mode import CycleMode


def test_probe_cooldown_prod(tmp_path):
    mode_file = tmp_path / "cycle-mode"
    mode_file.write_text("prod\n")
    with patch("shared.cycle_mode.MODE_FILE", mode_file):
        from logos.micro_probes import _probe_cooldown
        assert _probe_cooldown() == 600


def test_probe_cooldown_dev(tmp_path):
    mode_file = tmp_path / "cycle-mode"
    mode_file.write_text("dev\n")
    with patch("shared.cycle_mode.MODE_FILE", mode_file):
        from logos.micro_probes import _probe_cooldown
        assert _probe_cooldown() == 1800


def test_probe_idle_threshold_prod(tmp_path):
    mode_file = tmp_path / "cycle-mode"
    mode_file.write_text("prod\n")
    with patch("shared.cycle_mode.MODE_FILE", mode_file):
        from logos.micro_probes import _probe_idle_threshold
        assert _probe_idle_threshold() == 300


def test_probe_idle_threshold_dev(tmp_path):
    mode_file = tmp_path / "cycle-mode"
    mode_file.write_text("dev\n")
    with patch("shared.cycle_mode.MODE_FILE", mode_file):
        from logos.micro_probes import _probe_idle_threshold
        assert _probe_idle_threshold() == 900


def test_cache_fast_interval_prod(tmp_path):
    mode_file = tmp_path / "cycle-mode"
    mode_file.write_text("prod\n")
    with patch("shared.cycle_mode.MODE_FILE", mode_file):
        from logos.api.cache import _fast_interval, _slow_interval
        assert _fast_interval() == 30
        assert _slow_interval() == 300


def test_cache_intervals_dev(tmp_path):
    mode_file = tmp_path / "cycle-mode"
    mode_file.write_text("dev\n")
    with patch("shared.cycle_mode.MODE_FILE", mode_file):
        from logos.api.cache import _fast_interval, _slow_interval
        assert _fast_interval() == 15
        assert _slow_interval() == 120
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cycle_mode_integration.py -v`
Expected: FAIL with `ImportError: cannot import name '_probe_cooldown'`

**Step 3: Update `cockpit/micro_probes.py`**

Replace lines 17-19 (the constants) with mode-aware functions:

```python
# Before:
# Minimum idle seconds before a probe can surface
PROBE_IDLE_THRESHOLD = 300  # 5 minutes
# Minimum seconds between probes
PROBE_COOLDOWN = 600  # 10 minutes

# After:
from shared.cycle_mode import get_cycle_mode, CycleMode

def _probe_idle_threshold() -> int:
    """Minimum idle seconds before a probe can surface."""
    return 900 if get_cycle_mode() == CycleMode.DEV else 300

def _probe_cooldown() -> int:
    """Minimum seconds between probes."""
    return 1800 if get_cycle_mode() == CycleMode.DEV else 600

# Backward-compatible constants for imports
PROBE_IDLE_THRESHOLD = 300
PROBE_COOLDOWN = 600
```

Then update line 162 where `PROBE_COOLDOWN` is used in `get_probe()`:

```python
# Before:
        if time.time() - self._last_probe_time < PROBE_COOLDOWN:

# After:
        if time.time() - self._last_probe_time < _probe_cooldown():
```

**Step 4: Update `logos/api/cache.py`**

Replace lines 131-132 (the constants) with mode-aware functions:

```python
# Before:
FAST_INTERVAL = 30   # seconds
SLOW_INTERVAL = 300  # seconds

# After:
from shared.cycle_mode import get_cycle_mode, CycleMode

def _fast_interval() -> int:
    return 15 if get_cycle_mode() == CycleMode.DEV else 30

def _slow_interval() -> int:
    return 120 if get_cycle_mode() == CycleMode.DEV else 300

FAST_INTERVAL = 30   # backward-compat
SLOW_INTERVAL = 300  # backward-compat
```

Then update lines 145 and 150 where the constants are used in the refresh loops:

```python
# Before:
            await asyncio.sleep(FAST_INTERVAL)
...
            await asyncio.sleep(SLOW_INTERVAL)

# After:
            await asyncio.sleep(_fast_interval())
...
            await asyncio.sleep(_slow_interval())
```

**Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_cycle_mode_integration.py tests/test_micro_probes.py tests/test_cycle_mode.py -v`
Expected: All pass

**Step 6: Commit**

```bash
git add cockpit/micro_probes.py logos/api/cache.py tests/test_cycle_mode_integration.py
git commit -m "feat: make probe cooldowns and cache intervals cycle-mode-aware"
```

---

### Task 5: Add logos API endpoints

**Files:**
- Create: `logos/api/routes/cycle_mode.py`
- Modify: `logos/api/app.py:40,49-60`
- Create: `tests/test_cycle_mode_api.py`

**Step 1: Write the failing tests**

Create `tests/test_cycle_mode_api.py`:

```python
"""Tests for logos API cycle-mode endpoints."""
from __future__ import annotations

from unittest.mock import patch, AsyncMock
from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport

from logos.api.app import app


@pytest.fixture
def mode_file(tmp_path):
    f = tmp_path / "cycle-mode"
    f.write_text("prod\n")
    return f


@pytest.mark.asyncio
async def test_get_cycle_mode_returns_current(mode_file):
    with patch("cockpit.api.routes.cycle_mode.MODE_FILE", mode_file):
        with patch("cockpit.api.cache.start_refresh_loop", new_callable=AsyncMock):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/cycle-mode")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "prod"
    assert "switched_at" in data


@pytest.mark.asyncio
async def test_put_cycle_mode_switches(mode_file):
    with patch("cockpit.api.routes.cycle_mode.MODE_FILE", mode_file):
        with patch("cockpit.api.routes.cycle_mode._run_hapax_mode", return_value=(0, "Cycle mode -> dev\n")):
            with patch("cockpit.api.cache.start_refresh_loop", new_callable=AsyncMock):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.put("/api/cycle-mode", json={"mode": "dev"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "dev"


@pytest.mark.asyncio
async def test_put_cycle_mode_rejects_invalid(mode_file):
    with patch("cockpit.api.routes.cycle_mode.MODE_FILE", mode_file):
        with patch("cockpit.api.cache.start_refresh_loop", new_callable=AsyncMock):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.put("/api/cycle-mode", json={"mode": "turbo"})
    assert resp.status_code == 422
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cycle_mode_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cockpit.api.routes.cycle_mode'`

**Step 3: Create the route module**

Create `logos/api/routes/cycle_mode.py`:

```python
"""Logos API routes for cycle mode switching."""
from __future__ import annotations

import asyncio
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from shared.cycle_mode import CycleMode, MODE_FILE

router = APIRouter(prefix="/api", tags=["system"])

# Resolve hapax-mode script path
_SCRIPT = Path(__file__).parent.parent.parent.parent / "scripts" / "hapax-mode"


class CycleModeRequest(BaseModel):
    mode: CycleMode

    @field_validator("mode", mode="before")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        if v not in ("dev", "prod"):
            raise ValueError("mode must be 'dev' or 'prod'")
        return v


async def _run_hapax_mode(mode: str) -> tuple[int, str]:
    """Run hapax-mode script asynchronously."""
    script = shutil.which("hapax-mode") or str(_SCRIPT)
    proc = await asyncio.create_subprocess_exec(
        script, mode,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    return proc.returncode or 0, stdout.decode()


@router.get("/cycle-mode")
async def get_cycle_mode():
    try:
        mode = CycleMode(MODE_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        mode = CycleMode.PROD

    try:
        mtime = MODE_FILE.stat().st_mtime
        switched_at = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
    except FileNotFoundError:
        switched_at = None

    return {"mode": mode.value, "switched_at": switched_at}


@router.put("/cycle-mode")
async def put_cycle_mode(body: CycleModeRequest):
    returncode, output = await _run_hapax_mode(body.mode.value)
    if returncode != 0:
        raise HTTPException(status_code=500, detail=f"hapax-mode failed: {output}")

    return await get_cycle_mode()
```

**Step 4: Register the router in `logos/api/app.py`**

Add after line 51 (after the demos import):

```python
from logos.api.routes.cycle_mode import router as cycle_mode_router
```

Add after line 60 (after `app.include_router(demos_router)`):

```python
app.include_router(cycle_mode_router)
```

Also add `"PUT"` to `allow_methods` on line 40:

```python
# Before:
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],

# After:
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
```

**Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_cycle_mode_api.py -v`
Expected: 3 passed

**Step 6: Run all cycle-mode tests together**

Run: `uv run pytest tests/test_cycle_mode.py tests/test_cycle_mode_integration.py tests/test_cycle_mode_api.py tests/test_timer_overrides.py -v`
Expected: All pass

**Step 7: Commit**

```bash
git add logos/api/routes/cycle_mode.py logos/api/app.py tests/test_cycle_mode_api.py
git commit -m "feat: add logos API cycle-mode endpoints (GET/PUT)"
```
