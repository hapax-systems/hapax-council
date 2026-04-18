# DEGRADED-STREAM Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compositor displays a BitchX-authentic fallback surface during live code deploys (hapax-rebuild-services.timer cascade) so mid-update glitches never reach viewers.

**Architecture:** Systemd per-service ExecStartPre/ExecStartPost writes/removes `/dev/shm/hapax-compositor/degraded.flag`. Compositor main loop polls flag per frame. New `degraded_stream_ward.py` inheriting `HomageTransitionalSource` overrides full canvas when flag present. BitchX netsplit aesthetic: centered Px437 text + IRC-style progress bar + `-:-` status message.

**Tech Stack:** Python 3.12+, systemd units, Cairo (Px437 IBM VGA), HomagePackage (palette)
---

## Execution Notes

- Every task ends with `uv run ruff check .`, `uv run ruff format .`, and a commit.
- Run `uv run pytest tests/studio_compositor/ -q` after any test-bearing task.
- All paths in this plan are repo-relative. Absolute paths in shell examples use `$REPO_ROOT` and `$XDG_CONFIG_HOME` rather than hard-coded user paths.
- Commit directly to the current branch. No branch switching.
- TDD: write the failing test first, watch it fail, implement, watch it pass.

---

## Task 1: Helper Script `hapax-degraded-stream-signal.sh`

**Why:** Single entry point so every service's `ExecStartPre`/`ExecStartPost` calls the same shell, making the flag contract auditable from one file.

**Files**

- NEW: `systemd/hapax-degraded-stream-signal.sh`

### Steps

- [ ] 1.1 Create the flag directory on boot via tmpfiles (prep for script).

  Create `systemd/tmpfiles/hapax-compositor.conf`:

  ```
  d /dev/shm/hapax-compositor 0755 %U %U -
  ```

  Command: `systemd-tmpfiles --user --create systemd/tmpfiles/hapax-compositor.conf`
  Expected: no output, directory exists (`ls -ld /dev/shm/hapax-compositor`).

- [ ] 1.2 Write `systemd/hapax-degraded-stream-signal.sh`:

  ```bash
  #!/bin/sh
  # hapax-degraded-stream-signal.sh
  # Usage: hapax-degraded-stream-signal.sh {on|off} <unit-name>
  # Writes/removes /dev/shm/hapax-compositor/degraded.flag.
  set -eu

  FLAG_DIR="/dev/shm/hapax-compositor"
  FLAG="${FLAG_DIR}/degraded.flag"
  MODE="${1:-}"
  UNIT="${2:-unknown}"

  case "$MODE" in
    on)
      mkdir -p "$FLAG_DIR"
      TS="$(date +%s)"
      # Atomic write via tmp+rename so the compositor never reads a torn payload.
      TMP="$(mktemp "${FLAG_DIR}/.degraded.XXXXXX")"
      printf '{"reason":"rebuild","service":"%s","ts":%s}\n' "$UNIT" "$TS" > "$TMP"
      mv "$TMP" "$FLAG"
      ;;
    off)
      rm -f "$FLAG"
      ;;
    *)
      echo "usage: $0 {on|off} <unit-name>" >&2
      exit 64
      ;;
  esac
  ```

- [ ] 1.3 `chmod +x systemd/hapax-degraded-stream-signal.sh`.

- [ ] 1.4 Smoke-test manually:

  ```bash
  ./systemd/hapax-degraded-stream-signal.sh on test.service
  cat /dev/shm/hapax-compositor/degraded.flag  # expect JSON with service:test.service
  ./systemd/hapax-degraded-stream-signal.sh off test.service
  test ! -e /dev/shm/hapax-compositor/degraded.flag  # expect exit 0
  ```

- [ ] 1.5 `uv run ruff check .` (no-op for shell but ensures repo is clean).

**Commit:** `feat(degraded-stream): add signal helper script + tmpfiles dir`

---

## Task 2: `degraded_stream_ward.py` -- BitchX Netsplit Surface

**Why:** The ward is the full-canvas takeover. Building it first (before wiring) lets us exercise the visual in isolation with pytest-cairo snapshots.

**Files**

- NEW: `agents/studio_compositor/degraded_stream_ward.py`

### Steps

- [ ] 2.1 Stub the class with only the structural hooks so imports compile:

  ```python
  # agents/studio_compositor/degraded_stream_ward.py
  """Degraded-stream ward: BitchX netsplit fallback during live deploys."""

  from __future__ import annotations

  import json
  import time
  from dataclasses import dataclass, field
  from pathlib import Path

  import cairo

  from agents.studio_compositor.homage_transitional_source import HomageTransitionalSource
  from shared.homage_palette import BITCHX_PALETTE

  FLAG_PATH = Path("/dev/shm/hapax-compositor/degraded.flag")
  FADE_IN_MS = 300
  FADE_OUT_MS = 500


  @dataclass(slots=True)
  class FlagPayload:
      """Parsed payload from degraded.flag."""

      reason: str
      service: str
      ts: float

      @classmethod
      def read(cls, path: Path = FLAG_PATH) -> FlagPayload | None:
          try:
              raw = path.read_text()
          except FileNotFoundError:
              return None
          try:
              data = json.loads(raw)
          except json.JSONDecodeError:
              return None
          return cls(
              reason=str(data.get("reason", "rebuild")),
              service=str(data.get("service", "unknown")),
              ts=float(data.get("ts", time.time())),
          )
  ```

- [ ] 2.2 Add the ward class skeleton (state machine + `render` entry point):

  ```python
  @dataclass(slots=True)
  class DegradedStreamWard(HomageTransitionalSource):
      name: str = "degraded_stream_ward"
      fade_in_ms: int = FADE_IN_MS
      fade_out_ms: int = FADE_OUT_MS
      eta_seconds: float = 3.0
      _rolling_durations: list[float] = field(default_factory=list)

      def active_payload(self) -> FlagPayload | None:
          return FlagPayload.read()

      def progress_pct(self, payload: FlagPayload) -> int:
          elapsed = max(0.0, time.time() - payload.ts)
          eta = self._eta()
          pct = int(min(99, (elapsed / eta) * 100)) if eta > 0 else 0
          return max(0, pct)

      def _eta(self) -> float:
          if not self._rolling_durations:
              return self.eta_seconds
          # rolling mean of last 5 restart durations
          sample = self._rolling_durations[-5:]
          return sum(sample) / len(sample)

      def record_restart_duration(self, seconds: float) -> None:
          self._rolling_durations.append(seconds)
          self._rolling_durations = self._rolling_durations[-5:]
  ```

- [ ] 2.3 Add the Cairo render method -- centered text, IRC ASCII progress bar, `-:-` status:

  ```python
      def render(
          self,
          ctx: cairo.Context,
          width: int,
          height: int,
          payload: FlagPayload,
      ) -> None:
          # Background: Gruvbox-dark solid
          bg = BITCHX_PALETTE["gruvbox_dark_bg"]
          ctx.set_source_rgb(*bg)
          ctx.paint()

          # CP437 subtle noise (stipple)
          self._paint_cp437_noise(ctx, width, height)

          # Typography: Px437 IBM VGA 8x16
          ctx.select_font_face("Px437 IBM VGA 8x16", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
          ctx.set_font_size(18)

          pct = self.progress_pct(payload)
          bar_width = 40
          filled = int(bar_width * pct / 100)
          bar = "[" + "#" * filled + "-" * (bar_width - filled) + f"]  {pct:>2d}% complete"
          line1 = "*** hapax rebuilding \u2022 #hapax :+v operator"
          line2 = bar
          line3 = f"-:- restart in progress: {payload.service}"

          self._draw_centered(ctx, line1, width, height, y_offset=-28, color=BITCHX_PALETTE["bright_grey"])
          self._draw_centered(ctx, line2, width, height, y_offset=0, color=BITCHX_PALETTE["mirc_cyan"])
          self._draw_centered(ctx, line3, width, height, y_offset=28, color=BITCHX_PALETTE["mirc_yellow"])

      def _draw_centered(
          self,
          ctx: cairo.Context,
          text: str,
          width: int,
          height: int,
          y_offset: int,
          color: tuple[float, float, float],
      ) -> None:
          ctx.set_source_rgb(*color)
          xbearing, ybearing, tw, th, _, _ = ctx.text_extents(text)
          ctx.move_to((width - tw) / 2 - xbearing, (height + th) / 2 + y_offset)
          ctx.show_text(text)

      def _paint_cp437_noise(self, ctx: cairo.Context, width: int, height: int) -> None:
          # Sparse dotted lattice, 4% alpha, 8px grid
          ctx.set_source_rgba(0.80, 0.80, 0.80, 0.04)
          step = 8
          for y in range(0, height, step):
              for x in range(0, width, step):
                  ctx.rectangle(x, y, 1, 1)
          ctx.fill()
  ```

- [ ] 2.4 Verify Px437 font available: `fc-list | grep -i "Px437 IBM VGA 8x16"`. If missing, add to repo install docs (font ships via `ttf-px437` AUR).

- [ ] 2.5 Confirm `shared/homage_palette.py` exposes `BITCHX_PALETTE` with keys `gruvbox_dark_bg`, `bright_grey`, `mirc_cyan`, `mirc_yellow`. If not, add them -- open `shared/homage_palette.py`, append:

  ```python
  BITCHX_PALETTE = {
      "gruvbox_dark_bg": (0.109, 0.109, 0.109),
      "bright_grey": (0.80, 0.80, 0.80),
      "mirc_cyan": (0.0, 0.66, 0.66),
      "mirc_yellow": (0.93, 0.78, 0.20),
  }
  ```

- [ ] 2.6 `uv run ruff check agents/studio_compositor/degraded_stream_ward.py shared/homage_palette.py` and `uv run ruff format .`.

**Commit:** `feat(degraded-stream): add DegradedStreamWard with BitchX netsplit render`

---

## Task 3: Unit Tests -- Flag-on Activates, Flag-off Deactivates

**Why:** Encodes the state contract before any main-loop wiring, so downstream bugs show up here instead of on-stream.

**Files**

- NEW: `tests/studio_compositor/test_degraded_stream.py`

### Steps

- [ ] 3.1 Write the failing flag-parser test first:

  ```python
  # tests/studio_compositor/test_degraded_stream.py
  from __future__ import annotations

  import json
  import time
  from pathlib import Path

  import cairo
  import pytest

  from agents.studio_compositor.degraded_stream_ward import (
      FLAG_PATH,
      DegradedStreamWard,
      FlagPayload,
  )


  @pytest.fixture
  def flag_file(tmp_path, monkeypatch) -> Path:
      target = tmp_path / "degraded.flag"
      monkeypatch.setattr(
          "agents.studio_compositor.degraded_stream_ward.FLAG_PATH",
          target,
      )
      return target


  def test_flag_payload_missing_file_returns_none(flag_file: Path) -> None:
      assert FlagPayload.read(flag_file) is None


  def test_flag_payload_parses_json(flag_file: Path) -> None:
      flag_file.write_text(
          json.dumps({"reason": "rebuild", "service": "studio-compositor.service", "ts": 1700000000})
      )
      payload = FlagPayload.read(flag_file)
      assert payload is not None
      assert payload.service == "studio-compositor.service"
      assert payload.reason == "rebuild"
      assert payload.ts == 1700000000


  def test_flag_payload_malformed_json_returns_none(flag_file: Path) -> None:
      flag_file.write_text("not-json")
      assert FlagPayload.read(flag_file) is None
  ```

- [ ] 3.2 Run: `uv run pytest tests/studio_compositor/test_degraded_stream.py -q` -- all 3 pass.

- [ ] 3.3 Add activation-on/off tests:

  ```python
  def test_ward_active_payload_when_flag_present(flag_file: Path) -> None:
      flag_file.write_text(json.dumps({"reason": "rebuild", "service": "x.service", "ts": time.time()}))
      ward = DegradedStreamWard()
      assert ward.active_payload() is not None


  def test_ward_active_payload_none_when_flag_absent(flag_file: Path) -> None:
      ward = DegradedStreamWard()
      assert ward.active_payload() is None


  def test_ward_deactivates_after_flag_removed(flag_file: Path) -> None:
      flag_file.write_text(json.dumps({"reason": "rebuild", "service": "x.service", "ts": time.time()}))
      ward = DegradedStreamWard()
      assert ward.active_payload() is not None
      flag_file.unlink()
      assert ward.active_payload() is None
  ```

- [ ] 3.4 Add progress and ETA tests:

  ```python
  def test_progress_pct_uses_rolling_mean(flag_file: Path) -> None:
      ward = DegradedStreamWard()
      for d in (2.0, 3.0, 4.0):
          ward.record_restart_duration(d)
      # eta = mean(2,3,4) = 3.0; elapsed=1.5s => ~50%
      payload = FlagPayload(reason="rebuild", service="x", ts=time.time() - 1.5)
      pct = ward.progress_pct(payload)
      assert 40 <= pct <= 60


  def test_progress_pct_caps_at_99(flag_file: Path) -> None:
      ward = DegradedStreamWard()
      payload = FlagPayload(reason="rebuild", service="x", ts=time.time() - 60.0)
      assert ward.progress_pct(payload) == 99
  ```

- [ ] 3.5 Add render smoke (image surface doesn't crash):

  ```python
  def test_render_produces_surface_without_error(flag_file: Path) -> None:
      ward = DegradedStreamWard()
      surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1920, 1080)
      ctx = cairo.Context(surface)
      payload = FlagPayload(reason="rebuild", service="hapax-daimonion.service", ts=time.time())
      ward.render(ctx, 1920, 1080, payload)
      # Non-zero bytes written (background paint succeeded)
      assert len(surface.get_data()) > 0
  ```

- [ ] 3.6 Run: `uv run pytest tests/studio_compositor/test_degraded_stream.py -q` -- all green.

**Commit:** `test(degraded-stream): cover flag parsing, activation, progress, render`

---

## Task 4: Wire Into Compositor Main Loop

**Why:** Without polling, the ward is dead code. Polling is cheap (one `os.stat` per frame).

**Files**

- MOD: `agents/studio_compositor/compositor.py`

### Steps

- [ ] 4.1 Identify the per-frame render dispatch. Read `agents/studio_compositor/compositor.py` for the frame tick handler (likely `_on_frame` or `_compose_frame`).

- [ ] 4.2 Add the ward field to `StudioCompositor.__init__`:

  ```python
  from agents.studio_compositor.degraded_stream_ward import DegradedStreamWard

  # inside __init__, after existing ward initialization:
  self._degraded_ward = DegradedStreamWard()
  self._degraded_active = False
  self._degraded_entered_at: float | None = None
  ```

- [ ] 4.3 Add a helper `_check_degraded_flag`:

  ```python
  def _check_degraded_flag(self) -> "FlagPayload | None":
      """Poll /dev/shm for degraded.flag and update internal state. Called once per frame."""
      payload = self._degraded_ward.active_payload()
      now = time.time()
      if payload is not None and not self._degraded_active:
          self._degraded_active = True
          self._degraded_entered_at = now
          self._on_degraded_enter(payload)
      elif payload is None and self._degraded_active:
          self._degraded_active = False
          if self._degraded_entered_at is not None:
              duration = now - self._degraded_entered_at
              self._on_degraded_exit(duration)
              self._degraded_entered_at = None
      return payload
  ```

- [ ] 4.4 Wire it into the frame tick. In the existing frame-compose function, before ward composition:

  ```python
  payload = self._check_degraded_flag()
  if payload is not None:
      # Override: render only degraded ward, skip all others
      self._degraded_ward.render(ctx, width, height, payload)
      return
  # else: normal ward composition path
  ```

- [ ] 4.5 Stubs for hooks (metrics land in Task 7):

  ```python
  def _on_degraded_enter(self, payload: FlagPayload) -> None:
      pass  # filled in Task 7

  def _on_degraded_exit(self, duration: float) -> None:
      pass  # filled in Task 7
  ```

- [ ] 4.6 Run: `uv run pytest tests/studio_compositor/ -q`. Expect no regressions.

- [ ] 4.7 `uv run ruff check . && uv run ruff format .`.

**Commit:** `feat(degraded-stream): wire ward into compositor frame tick`

---

## Task 5: Ward Registry + Layout Registration

**Why:** The choreographer and other wards look up `degraded_stream_ward` by name. Without registry presence, it's invisible to the rest of the system.

**Files**

- MOD: `agents/studio_compositor/ward_registry.py` (or `legibility_sources.py` -- whichever holds the registry)

### Steps

- [ ] 5.1 Grep to confirm the registry location:

  ```
  rg -n "ward_registry|register_ward|WARD_REGISTRY" agents/studio_compositor/
  ```

- [ ] 5.2 Add the registration. Example if the registry uses a module-level dict:

  ```python
  # agents/studio_compositor/ward_registry.py (end of file, before exports)
  from agents.studio_compositor.degraded_stream_ward import DegradedStreamWard

  WARD_REGISTRY["degraded_stream_ward"] = DegradedStreamWard
  ```

- [ ] 5.3 Add a layout entry so the ward claims the full canvas:

  ```python
  # agents/studio_compositor/layouts.py or wherever Layout is assembled
  DEGRADED_STREAM_LAYOUT = Layout(
      surface_id="degraded_stream",
      x=0,
      y=0,
      width=1920,
      height=1080,
      z_index=999,  # on top of everything
      privileged=True,
  )
  ```

  If `Layout` lacks `privileged`, add it as an optional field in `shared/compositor_model.py`:

  ```python
  class Layout(BaseModel):
      ...
      privileged: bool = Field(default=False)
  ```

- [ ] 5.4 Add registry test:

  ```python
  # tests/studio_compositor/test_degraded_stream.py (append)
  def test_ward_registered_in_ward_registry() -> None:
      from agents.studio_compositor.ward_registry import WARD_REGISTRY
      assert "degraded_stream_ward" in WARD_REGISTRY
      ward = WARD_REGISTRY["degraded_stream_ward"]()
      assert ward.name == "degraded_stream_ward"
  ```

- [ ] 5.5 Run `uv run pytest tests/studio_compositor/ -q` -- green.

**Commit:** `feat(degraded-stream): register ward + privileged full-canvas layout`

---

## Task 6: Choreographer Privileged Override

**Why:** The choreographer's concurrency limit must not delay or reject the degraded ward during a live deploy -- it's the whole point.

**Files**

- MOD: `agents/studio_compositor/homage_choreographer.py` (or whichever file hosts the concurrency gate)

### Steps

- [ ] 6.1 Locate the rejection logic:

  ```
  rg -n "concurrency|rejection|reject" agents/studio_compositor/homage_*.py
  ```

- [ ] 6.2 Add a privileged bypass at the entry of the rejection-checking method:

  ```python
  def schedule_transition(self, ward: HomageTransitionalSource, to_state: WardState) -> bool:
      if getattr(ward, "privileged", False) or ward.name == "degraded_stream_ward":
          # Privileged override: skip concurrency limits, triggers mass-absent on others.
          self._mass_absent_others(except_name=ward.name)
          self._record_rejection_bypass(ward.name, reason="degraded_override")
          return True
      # ... existing concurrency / rejection path ...
  ```

- [ ] 6.3 Implement `_mass_absent_others`:

  ```python
  def _mass_absent_others(self, except_name: str) -> None:
      for name, other in list(self._active_wards.items()):
          if name == except_name:
              continue
          other.transition_to("absent")
  ```

- [ ] 6.4 Implement `_record_rejection_bypass` -- stub for now, wired to metric in Task 7:

  ```python
  def _record_rejection_bypass(self, ward_name: str, reason: str) -> None:
      pass  # Task 7 wires hapax_choreographer_rejection_total
  ```

- [ ] 6.5 Ensure `DegradedStreamWard` declares `privileged = True`:

  ```python
  # agents/studio_compositor/degraded_stream_ward.py
  @dataclass(slots=True)
  class DegradedStreamWard(HomageTransitionalSource):
      ...
      privileged: bool = True
  ```

- [ ] 6.6 Test: flag-on triggers mass-absent transition on peer wards:

  ```python
  def test_degraded_ward_triggers_mass_absent(monkeypatch) -> None:
      from agents.studio_compositor.homage_choreographer import HomageChoreographer
      from agents.studio_compositor.degraded_stream_ward import DegradedStreamWard

      choreo = HomageChoreographer()
      peer = _FakeWard(name="glitch_ward", state="hold")
      choreo._active_wards["glitch_ward"] = peer
      deg = DegradedStreamWard()
      assert choreo.schedule_transition(deg, "entering") is True
      assert peer.state == "absent"
  ```

  `_FakeWard` is a minimal test double with `name`, `state`, `transition_to`.

- [ ] 6.7 `uv run pytest tests/studio_compositor/ -q` -- green.

**Commit:** `feat(degraded-stream): choreographer privileged override bypasses concurrency`

---

## Task 7: Prometheus Metrics

**Why:** On-air decisions need visibility. The gauge lights up on the Grafana dashboard; the counter + histogram feed the rebuild-storm alert.

**Files**

- MOD: `shared/director_observability.py`
- MOD: `agents/studio_compositor/compositor.py`
- MOD: `agents/studio_compositor/homage_choreographer.py`

### Steps

- [ ] 7.1 Add metric definitions to `shared/director_observability.py`:

  ```python
  from prometheus_client import Counter, Gauge, Histogram

  compositor_degraded_active = Gauge(
      "hapax_compositor_degraded_active",
      "1 if compositor is currently in degraded-stream mode, 0 otherwise.",
      labelnames=("reason", "service"),
  )

  compositor_degraded_activation_total = Counter(
      "hapax_compositor_degraded_activation_total",
      "Total number of degraded-stream activations.",
      labelnames=("reason", "service"),
  )

  compositor_degraded_duration_seconds = Histogram(
      "hapax_compositor_degraded_duration_seconds",
      "Duration of degraded-stream activations in seconds.",
      buckets=(0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 13.0, 21.0, 34.0),
  )

  choreographer_rejection_total = Counter(
      "hapax_choreographer_rejection_total",
      "Choreographer rejections (and audited bypasses).",
      labelnames=("reason",),
  )
  ```

- [ ] 7.2 Fill in the compositor hooks (replacing the stubs from Task 4):

  ```python
  # agents/studio_compositor/compositor.py
  from shared.director_observability import (
      compositor_degraded_active,
      compositor_degraded_activation_total,
      compositor_degraded_duration_seconds,
  )

  def _on_degraded_enter(self, payload: FlagPayload) -> None:
      compositor_degraded_active.labels(reason=payload.reason, service=payload.service).set(1)
      compositor_degraded_activation_total.labels(reason=payload.reason, service=payload.service).inc()
      self._degraded_label_cache = (payload.reason, payload.service)

  def _on_degraded_exit(self, duration: float) -> None:
      compositor_degraded_duration_seconds.observe(duration)
      if self._degraded_label_cache is not None:
          reason, service = self._degraded_label_cache
          compositor_degraded_active.labels(reason=reason, service=service).set(0)
          self._degraded_label_cache = None
  ```

  Declare `self._degraded_label_cache: tuple[str, str] | None = None` in `__init__`.

- [ ] 7.3 Replace the choreographer stub:

  ```python
  # agents/studio_compositor/homage_choreographer.py
  from shared.director_observability import choreographer_rejection_total

  def _record_rejection_bypass(self, ward_name: str, reason: str) -> None:
      choreographer_rejection_total.labels(reason=reason).inc()
  ```

- [ ] 7.4 Test metric wiring (use `prometheus_client` registry inspection):

  ```python
  def test_metrics_emitted_on_activation(flag_file: Path, monkeypatch) -> None:
      from shared.director_observability import (
          compositor_degraded_activation_total,
          compositor_degraded_active,
      )
      before = compositor_degraded_activation_total.labels(
          reason="rebuild", service="hapax-daimonion.service"
      )._value.get()

      compositor = _build_compositor()  # helper: minimal compositor for tests
      flag_file.write_text(json.dumps({
          "reason": "rebuild",
          "service": "hapax-daimonion.service",
          "ts": time.time(),
      }))
      compositor._check_degraded_flag()

      after = compositor_degraded_activation_total.labels(
          reason="rebuild", service="hapax-daimonion.service"
      )._value.get()
      assert after == before + 1
      assert compositor_degraded_active.labels(
          reason="rebuild", service="hapax-daimonion.service"
      )._value.get() == 1
  ```

- [ ] 7.5 `uv run pytest tests/studio_compositor/ -q` -- green.

**Commit:** `feat(degraded-stream): prometheus gauge/counter/histogram + bypass counter`

---

## Task 8: Add ExecStartPre/Post to Visual-Surface Services

**Why:** This is the actual enablement -- every service whose restart can produce visual artifacts writes the flag. Answers Spec Q2: only visual-surface-adjacent services.

**Files**

- MOD (each): `systemd/user/hapax-daimonion.service`, `hapax-imagination.service`, `hapax-reverie.service`, `studio-compositor.service`, `visual-layer-aggregator.service`, `hapax-content-resolver.service`, `hapax-logos.service`

NOT touched (per spec Q2 decision):
- `hapax-watch-receiver.service` (biometrics only)
- `hapax-phone-receiver.service` (phone context only)
- `logos-api.service`, `officium-api.service` (data APIs, not visual)
- `tabbyapi.service`, `ollama.service` (inference)
- Timer units, oneshots (no visual surface)

### Steps

- [ ] 8.1 For each service file, add (or update) the `[Service]` directives using `${REPO_ROOT}` resolved by the drop-in installer (Step 8.2), so no hard-coded absolute paths live in the unit files themselves:

  ```ini
  [Service]
  ExecStartPre=/bin/sh -c '${REPO_ROOT}/systemd/hapax-degraded-stream-signal.sh on %n'
  ExecStartPost=/bin/sh -c '${REPO_ROOT}/systemd/hapax-degraded-stream-signal.sh off %n'
  ```

  Note: `studio-compositor.service` is a special case -- it clears its own flag on start since its restart is exactly what produces the artifact. Keep the ExecStartPre/Post anyway; the compositor will pick up its own flag only after it restarts, by which point the flag is already removed.

- [ ] 8.2 Add a single-source-of-truth helper in `systemd/drop-ins/degraded-stream.conf.template`:

  ```ini
  # Drop-in template; filled by install-degraded-stream-dropins.sh
  [Service]
  ExecStartPre=/bin/sh -c '__REPO_ROOT__/systemd/hapax-degraded-stream-signal.sh on %n'
  ExecStartPost=/bin/sh -c '__REPO_ROOT__/systemd/hapax-degraded-stream-signal.sh off %n'
  ```

  Script `systemd/install-degraded-stream-dropins.sh`:

  ```bash
  #!/bin/sh
  set -eu
  REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
  SERVICES="hapax-daimonion hapax-imagination hapax-reverie studio-compositor visual-layer-aggregator hapax-content-resolver hapax-logos"
  SRC="${REPO_ROOT}/systemd/drop-ins/degraded-stream.conf.template"
  UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
  for svc in $SERVICES; do
    DROP_DIR="${UNIT_DIR}/${svc}.service.d"
    mkdir -p "$DROP_DIR"
    sed "s|__REPO_ROOT__|${REPO_ROOT}|g" "$SRC" > "${DROP_DIR}/degraded-stream.conf"
  done
  systemctl --user daemon-reload
  ```

  `chmod +x systemd/install-degraded-stream-dropins.sh`.

- [ ] 8.3 Dry-run the install (won't restart services):

  ```bash
  ./systemd/install-degraded-stream-dropins.sh
  systemctl --user cat hapax-daimonion.service | grep -A1 degraded-stream
  ```

  Expected: drop-in visible in `cat` output.

- [ ] 8.4 Verify the drop-in fires once on a trivial service restart:

  ```bash
  systemctl --user restart hapax-content-resolver.service
  # Within the restart window, the flag should exist; after, gone
  ls -la /dev/shm/hapax-compositor/
  ```

- [ ] 8.5 `uv run ruff check . && uv run ruff format .`.

**Commit:** `feat(degraded-stream): systemd drop-ins for 7 visual-surface services`

---

## Task 9: Integration Test -- Live Restart -> Ward Visible in RTMP Capture

**Why:** End-to-end proof. Unit tests lie; a 3-second RTMP capture does not.

**Files**

- NEW: `tests/studio_compositor/test_degraded_stream_e2e.py`
- NEW: `scripts/capture-rtmp-window.sh` (helper)

### Steps

- [ ] 9.1 Write the helper: 5-second ffmpeg capture to a temp MP4:

  ```bash
  #!/bin/sh
  # scripts/capture-rtmp-window.sh <out-path> <duration-seconds>
  set -eu
  OUT="${1:-/tmp/rtmp-capture.mp4}"
  DUR="${2:-5}"
  ffmpeg -y -i rtmp://127.0.0.1:1935/live/stream -t "$DUR" -c copy "$OUT"
  ```

  `chmod +x scripts/capture-rtmp-window.sh`.

- [ ] 9.2 Write the E2E test (guarded by an env flag so CI doesn't run it):

  ```python
  # tests/studio_compositor/test_degraded_stream_e2e.py
  import os
  import subprocess
  import tempfile
  import time
  from pathlib import Path

  import pytest

  pytestmark = pytest.mark.skipif(
      os.environ.get("HAPAX_E2E") != "1",
      reason="E2E requires live compositor + RTMP relay (HAPAX_E2E=1)",
  )


  def test_daimonion_restart_triggers_degraded_ward_in_rtmp_capture() -> None:
      """Restart hapax-daimonion, capture RTMP, assert ward frames detected."""
      out = Path(tempfile.mkdtemp()) / "capture.mp4"

      # Kick off capture in the background
      cap = subprocess.Popen(
          ["./scripts/capture-rtmp-window.sh", str(out), "5"],
          stdout=subprocess.DEVNULL,
          stderr=subprocess.DEVNULL,
      )
      time.sleep(0.5)  # let capture settle

      # Trigger restart
      subprocess.run(
          ["systemctl", "--user", "restart", "hapax-daimonion.service"],
          check=True,
      )

      cap.wait(timeout=15)
      assert out.exists() and out.stat().st_size > 0

      # Extract middle frame and assert "hapax rebuilding" text presence via tesseract
      frame = Path(tempfile.mkdtemp()) / "frame.png"
      subprocess.run(
          ["ffmpeg", "-y", "-ss", "1.5", "-i", str(out), "-frames:v", "1", str(frame)],
          check=True,
          stdout=subprocess.DEVNULL,
          stderr=subprocess.DEVNULL,
      )
      ocr = subprocess.run(
          ["tesseract", str(frame), "-", "--psm", "6"],
          capture_output=True,
          text=True,
          check=True,
      )
      assert "hapax" in ocr.stdout.lower() or "rebuilding" in ocr.stdout.lower()
  ```

- [ ] 9.3 Manual verification (since `HAPAX_E2E=1` is opt-in):

  ```bash
  HAPAX_E2E=1 uv run pytest tests/studio_compositor/test_degraded_stream_e2e.py -q -s
  ```

  Expected: passes; otherwise, inspect capture.mp4 frame-by-frame in mpv.

- [ ] 9.4 Negative test -- ensure normal operation (no flag) captures without ward:

  ```python
  def test_no_ward_in_capture_without_restart() -> None:
      # Same HAPAX_E2E guard; capture 3s with no restart
      ...
  ```

**Commit:** `test(degraded-stream): e2e RTMP capture + OCR proof`

---

## Task 10: Grafana Alert Panel -- Rebuild-Storm Detection

**Why:** >20 activations/hour means the rebuild timer is flapping or a hook is thrashing. Operator needs to see it on the dashboard, not discover it three days later in logs.

**Files**

- NEW: `grafana/dashboards/degraded-stream.json`
- MOD: `grafana/provisioning/dashboards/hapax-dashboards.yaml` (if uid-indexed provisioning is used)

### Steps

- [ ] 10.1 Author `grafana/dashboards/degraded-stream.json`:

  ```json
  {
    "uid": "hapax-degraded-stream",
    "title": "Hapax Degraded Stream",
    "schemaVersion": 38,
    "version": 1,
    "panels": [
      {
        "type": "stat",
        "title": "Currently Degraded",
        "id": 1,
        "targets": [
          {
            "expr": "sum(hapax_compositor_degraded_active) > 0",
            "refId": "A"
          }
        ],
        "fieldConfig": {
          "defaults": {
            "color": {"mode": "thresholds"},
            "thresholds": {
              "mode": "absolute",
              "steps": [
                {"color": "green", "value": null},
                {"color": "red", "value": 1}
              ]
            }
          }
        },
        "gridPos": {"h": 4, "w": 6, "x": 0, "y": 0}
      },
      {
        "type": "timeseries",
        "title": "Activations per Hour",
        "id": 2,
        "targets": [
          {
            "expr": "sum(rate(hapax_compositor_degraded_activation_total[5m])) * 3600",
            "refId": "A",
            "legendFormat": "activations/hr"
          }
        ],
        "gridPos": {"h": 8, "w": 12, "x": 0, "y": 4},
        "alert": {
          "name": "Rebuild Storm",
          "conditions": [
            {
              "evaluator": {"type": "gt", "params": [20]},
              "query": {"params": ["A", "5m", "now"]},
              "reducer": {"type": "avg", "params": []},
              "type": "query"
            }
          ],
          "for": "5m",
          "noDataState": "no_data",
          "executionErrorState": "alerting"
        }
      },
      {
        "type": "timeseries",
        "title": "Degraded Duration Distribution (p50/p95)",
        "id": 3,
        "targets": [
          {
            "expr": "histogram_quantile(0.50, sum(rate(hapax_compositor_degraded_duration_seconds_bucket[15m])) by (le))",
            "legendFormat": "p50",
            "refId": "A"
          },
          {
            "expr": "histogram_quantile(0.95, sum(rate(hapax_compositor_degraded_duration_seconds_bucket[15m])) by (le))",
            "legendFormat": "p95",
            "refId": "B"
          }
        ],
        "gridPos": {"h": 8, "w": 12, "x": 12, "y": 4}
      }
    ]
  }
  ```

- [ ] 10.2 Provision: copy into Grafana's dashboard directory, reload:

  ```bash
  cp grafana/dashboards/degraded-stream.json \
     "${HAPAX_DOCKER_DATA:-$HOME/docker-data}/grafana/dashboards/"
  docker compose restart grafana
  ```

- [ ] 10.3 Verify in browser -- http://localhost:3000/d/hapax-degraded-stream -- panels render, alert rule saved.

- [ ] 10.4 Smoke the alert: manually touch the flag 25 times with 100ms gaps:

  ```bash
  for i in $(seq 1 25); do
    ./systemd/hapax-degraded-stream-signal.sh on fake.service
    sleep 0.05
    ./systemd/hapax-degraded-stream-signal.sh off fake.service
    sleep 0.05
  done
  ```

  Wait 5m, confirm "Rebuild Storm" alert fires in Grafana alert panel.

- [ ] 10.5 Final end-to-end: restart `hapax-content-resolver.service` and visually confirm BitchX surface appears on the livestream output.

**Commit:** `feat(degraded-stream): grafana dashboard + rebuild-storm alert`

---

## Done Criteria

- [ ] `/dev/shm/hapax-compositor/degraded.flag` written on every managed-service restart, removed on start completion.
- [ ] Compositor polls the flag per frame; BitchX ward occupies the full 1920x1080 canvas during flag presence.
- [ ] All 7 visual-surface services carry the drop-in. No watch/phone/API/inference unit touched.
- [ ] Unit tests cover flag parsing, activation, deactivation, progress, render, registry, and metrics.
- [ ] E2E test (`HAPAX_E2E=1`) passes: `systemctl --user restart hapax-daimonion` produces an OCR-detectable "hapax rebuilding" frame in the RTMP capture window.
- [ ] Grafana dashboard live at `/d/hapax-degraded-stream`; alert fires above 20 activations/hour.
- [ ] `uv run ruff check . && uv run pytest tests/studio_compositor/ -q` both green.
- [ ] Ten commits, one per task, all on the current branch.

## Spec Open-Question Resolutions

- **Q1 (ETA heuristic):** implemented rolling-mean-of-last-5 with 3-second fallback (Task 2 step 2.2 + 2.3).
- **Q2 (which services trigger):** visual-surface-adjacent only -- 7 services enumerated in Task 8. Watch/phone receivers, logos/officium APIs, tabbyapi, and ollama explicitly excluded.
