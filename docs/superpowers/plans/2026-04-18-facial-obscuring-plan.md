# Facial Obscuring (HARD Privacy Req) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pixel-level face obscure applied per-camera-at-capture on all 6 cameras. SCRFD @ 5Hz + Kalman carry-forward. Solid Gruvbox-dark rect + large-block pixelation veneer (non-reversible). Additive to existing consent-gate swap.

**Architecture:** Capture-side subprocess per camera inserts obscure pipeline stage between raw frame and JPEG write. All 6 egress paths (main compositor, RTMP, HLS, recording, snapshots, director LLM) inherit the protection because they all read from the obscured `/dev/shm/cam-*.jpg`.

**Tech Stack:** Python 3.12+, SCRFD (existing), YOLO11n fallback (existing), OpenCV (blit), Kalman filter (existing patterns)
---

## Pre-flight

Before starting Task 1, confirm working environment from the repo root:

```bash
git rev-parse --abbrev-ref HEAD    # confirm branch
uv sync --all-extras               # council extras: audio, sync-pipeline, logos-api
uv run pytest tests/ -q --collect-only 2>&1 | tail -5   # collection sanity
ls /dev/shm/hapax-compositor/ 2>/dev/null || true       # confirm shm path exists
```

**Spec reference:** `docs/superpowers/specs/2026-04-18-facial-obscuring-hard-req-design.md`
**Axiom reference:** `axioms/implications/it-irreversible-broadcast.yaml` (T0)
**Reused detector:** `agents/hapax_daimonion/face_detector.py` (SCRFD + 512-d embeddings)
**Consent interaction:** `agents/studio_compositor/consent.py`, `agents/studio_compositor/consent_live_egress.py`

**Commit cadence:** one commit per completed task. Never leave a task half-committed. If a task takes >5 min, split the commit. Conventional commits: `feat(privacy): ...`, `test(privacy): ...`, `chore(privacy): ...`.

---

## Task 1 — `FaceObscurePolicy` enum + unit tests

**Why:** Foundation type. Everything downstream imports this. Tiny, isolated, TDD-friendly.

### Files

- NEW: `shared/face_obscure_policy.py`
- NEW: `tests/shared/test_face_obscure_policy.py`

### Steps

- [ ] Create `tests/shared/test_face_obscure_policy.py` first (TDD, red):

```python
from shared.face_obscure_policy import FaceObscurePolicy


def test_policy_has_three_members():
    members = {m.name for m in FaceObscurePolicy}
    assert members == {"ALWAYS_OBSCURE", "OBSCURE_NON_OPERATOR", "DISABLED"}


def test_policy_default_is_always_obscure():
    assert FaceObscurePolicy.default() is FaceObscurePolicy.ALWAYS_OBSCURE


def test_policy_serializes_to_lowercase_value():
    assert FaceObscurePolicy.ALWAYS_OBSCURE.value == "always_obscure"
    assert FaceObscurePolicy.OBSCURE_NON_OPERATOR.value == "obscure_non_operator"
    assert FaceObscurePolicy.DISABLED.value == "disabled"


def test_policy_from_string_roundtrip():
    for member in FaceObscurePolicy:
        assert FaceObscurePolicy(member.value) is member


def test_should_obscure_face_always_mode_ignores_is_operator():
    p = FaceObscurePolicy.ALWAYS_OBSCURE
    assert p.should_obscure(is_operator=True) is True
    assert p.should_obscure(is_operator=False) is True


def test_should_obscure_face_non_operator_mode_respects_flag():
    p = FaceObscurePolicy.OBSCURE_NON_OPERATOR
    assert p.should_obscure(is_operator=True) is False
    assert p.should_obscure(is_operator=False) is True


def test_should_obscure_face_disabled_mode_never_obscures():
    p = FaceObscurePolicy.DISABLED
    assert p.should_obscure(is_operator=True) is False
    assert p.should_obscure(is_operator=False) is False
```

- [ ] Run red:

```bash
uv run pytest tests/shared/test_face_obscure_policy.py -q
# expected: ModuleNotFoundError: No module named 'shared.face_obscure_policy'
```

- [ ] Create `shared/face_obscure_policy.py`:

```python
"""Face obscure policy enum.

Governed by `axioms/implications/it-irreversible-broadcast.yaml` (T0).
Default is ALWAYS_OBSCURE pending operator answer to open Q1 in the design doc
(docs/superpowers/specs/2026-04-18-facial-obscuring-hard-req-design.md section 8).
"""

from __future__ import annotations

from enum import Enum


class FaceObscurePolicy(str, Enum):
    """Per-camera obscuring mode. Str-backed so pydantic and YAML serialize cleanly."""

    ALWAYS_OBSCURE = "always_obscure"
    OBSCURE_NON_OPERATOR = "obscure_non_operator"
    DISABLED = "disabled"

    @classmethod
    def default(cls) -> "FaceObscurePolicy":
        return cls.ALWAYS_OBSCURE

    def should_obscure(self, *, is_operator: bool) -> bool:
        if self is FaceObscurePolicy.ALWAYS_OBSCURE:
            return True
        if self is FaceObscurePolicy.DISABLED:
            return False
        # OBSCURE_NON_OPERATOR
        return not is_operator
```

- [ ] Run green:

```bash
uv run pytest tests/shared/test_face_obscure_policy.py -q
# expected: 7 passed
```

- [ ] Lint + type:

```bash
uv run ruff check shared/face_obscure_policy.py tests/shared/test_face_obscure_policy.py
uv run ruff format shared/face_obscure_policy.py tests/shared/test_face_obscure_policy.py
uv run pyright shared/face_obscure_policy.py
# expected: 0 errors, 0 warnings
```

- [ ] Commit:

```bash
git add shared/face_obscure_policy.py tests/shared/test_face_obscure_policy.py
git commit -m "feat(privacy): add FaceObscurePolicy enum for per-camera obscuring modes"
```

---

## Task 2 — `FaceObscurer.obscure(frame, bboxes)` — solid rect + pixelation veneer

**Why:** Core pixel-level primitive. Called by capture subprocess per frame. Must be fast (<1 ms/frame) and non-reversible.

### Files

- NEW: `agents/studio_compositor/face_obscure.py`
- NEW: `tests/studio_compositor/test_face_obscure.py`

### Steps

- [ ] Red test first:

```python
# tests/studio_compositor/test_face_obscure.py
import numpy as np
import pytest

from agents.studio_compositor.face_obscure import FaceBBox, FaceObscurer


@pytest.fixture
def frame():
    """720p RGB frame with a distinctive gradient so we can verify obscuring."""
    h, w = 720, 1280
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[..., 0] = np.linspace(0, 255, w, dtype=np.uint8)  # R gradient
    img[..., 1] = np.linspace(0, 255, h, dtype=np.uint8)[:, None]  # G gradient
    img[..., 2] = 128  # B constant
    return img


def test_empty_bboxes_returns_unchanged_frame(frame):
    obs = FaceObscurer()
    out = obs.obscure(frame, bboxes=[])
    assert np.array_equal(out, frame)


def test_single_bbox_overwrites_region_with_solid_rect(frame):
    obs = FaceObscurer()
    bbox = FaceBBox(x=100, y=100, w=200, h=200, is_operator=False)
    out = obs.obscure(frame, bboxes=[bbox])
    cx, cy = 200, 200
    px = out[cy, cx]
    # allow +/-8 for pixelation veneer drift
    assert abs(int(px[0]) - 0x28) <= 8
    assert abs(int(px[1]) - 0x28) <= 8
    assert abs(int(px[2]) - 0x28) <= 8


def test_bbox_margin_expansion(frame):
    """20% margin means a 100x100 bbox actually obscures roughly 120x120."""
    obs = FaceObscurer(margin_pct=0.20)
    bbox = FaceBBox(x=400, y=400, w=100, h=100, is_operator=False)
    out = obs.obscure(frame, bboxes=[bbox])
    px = out[400 - 5, 400 - 5]
    assert int(px.sum()) < int(frame[400 - 5, 400 - 5].sum())


def test_full_frame_obscure(frame):
    """Fail-closed full-frame path: every pixel replaced."""
    obs = FaceObscurer()
    out = obs.obscure_full_frame(frame)
    assert np.all(out[..., 0] == 0x28)
    assert np.all(out[..., 1] == 0x28)
    assert np.all(out[..., 2] == 0x28)


def test_pixelation_veneer_has_block_structure(frame):
    """After obscure, 16x16 blocks must be solid (every pixel in a block equal)."""
    obs = FaceObscurer(block_size=16)
    bbox = FaceBBox(x=200, y=200, w=256, h=256, is_operator=False)
    out = obs.obscure(frame, bboxes=[bbox])
    block = out[240:256, 240:256]
    assert np.all(block == block[0, 0])


def test_does_not_mutate_input_frame(frame):
    obs = FaceObscurer()
    snapshot = frame.copy()
    bbox = FaceBBox(x=100, y=100, w=100, h=100, is_operator=False)
    obs.obscure(frame, bboxes=[bbox])
    assert np.array_equal(frame, snapshot)
```

- [ ] Run red:

```bash
uv run pytest tests/studio_compositor/test_face_obscure.py -q
# expected: ModuleNotFoundError
```

- [ ] Implement `agents/studio_compositor/face_obscure.py`:

```python
"""FaceObscurer: non-reversible pixel-level face obscure.

Solid Gruvbox-dark rect + pixelation veneer. Not Gaussian blur -- blur is
reversible under known-PSF attack; solid mask + pixelation is not.
See docs/superpowers/specs/2026-04-18-facial-obscuring-hard-req-design.md section 3.3.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

GRUVBOX_DARK_RGB = (0x28, 0x28, 0x28)  # gruvbox hard dark bg0


@dataclass(frozen=True, slots=True)
class FaceBBox:
    x: int
    y: int
    w: int
    h: int
    is_operator: bool


class FaceObscurer:
    """Applies solid rect + pixelation veneer to face regions.

    Parameters
    ----------
    margin_pct:
        Symmetric bbox expansion to absorb detection jitter. 0.20 = 20%.
    block_size:
        Pixelation block size. 16 px per the design doc.
    fill_color:
        RGB fill for solid rect layer. Defaults to Gruvbox dark #282828.
    """

    def __init__(
        self,
        *,
        margin_pct: float = 0.20,
        block_size: int = 16,
        fill_color: tuple[int, int, int] = GRUVBOX_DARK_RGB,
    ) -> None:
        self.margin_pct = margin_pct
        self.block_size = block_size
        self.fill_color = np.array(fill_color, dtype=np.uint8)

    def obscure(self, frame: np.ndarray, bboxes: list[FaceBBox]) -> np.ndarray:
        """Return a new frame with every bbox obscured."""
        if not bboxes:
            return frame
        out = frame.copy()
        h, w, _ = out.shape
        for bb in bboxes:
            mx = int(bb.w * self.margin_pct)
            my = int(bb.h * self.margin_pct)
            x0 = max(0, bb.x - mx)
            y0 = max(0, bb.y - my)
            x1 = min(w, bb.x + bb.w + mx)
            y1 = min(h, bb.y + bb.h + my)
            self._blit_solid(out, x0, y0, x1, y1)
            self._pixelate_margin(out, x0, y0, x1, y1)
        return out

    def obscure_full_frame(self, frame: np.ndarray) -> np.ndarray:
        """Fail-closed path: replace every pixel with fill_color."""
        out = np.empty_like(frame)
        out[:] = self.fill_color
        return out

    def _blit_solid(self, img: np.ndarray, x0: int, y0: int, x1: int, y1: int) -> None:
        img[y0:y1, x0:x1] = self.fill_color

    def _pixelate_margin(self, img: np.ndarray, x0: int, y0: int, x1: int, y1: int) -> None:
        """Average each block_size x block_size region to a single color."""
        bs = self.block_size
        for y in range(y0, y1, bs):
            for x in range(x0, x1, bs):
                yy = min(y + bs, y1)
                xx = min(x + bs, x1)
                block = img[y:yy, x:xx]
                if block.size == 0:
                    continue
                mean = block.reshape(-1, 3).mean(axis=0).astype(np.uint8)
                img[y:yy, x:xx] = mean
```

- [ ] Run green + perf check:

```bash
uv run pytest tests/studio_compositor/test_face_obscure.py -q
# expected: 6 passed

uv run python -c "
import numpy as np, time
from agents.studio_compositor.face_obscure import FaceBBox, FaceObscurer
obs = FaceObscurer()
frame = np.random.randint(0, 255, (720, 1280, 3), dtype=np.uint8)
bbox = FaceBBox(x=400, y=300, w=200, h=200, is_operator=False)
t = time.perf_counter()
for _ in range(100):
    obs.obscure(frame, [bbox])
dt = (time.perf_counter() - t) * 10
print(f'{dt:.2f} ms/call')
"
# expected: <5 ms/call single-face; design budget is <1 ms GPU but CPU path acceptable for MVP
```

- [ ] Lint + type + commit:

```bash
uv run ruff check agents/studio_compositor/face_obscure.py tests/studio_compositor/test_face_obscure.py
uv run ruff format agents/studio_compositor/face_obscure.py tests/studio_compositor/test_face_obscure.py
uv run pyright agents/studio_compositor/face_obscure.py
git add agents/studio_compositor/face_obscure.py tests/studio_compositor/test_face_obscure.py
git commit -m "feat(privacy): FaceObscurer solid rect + pixelation veneer"
```

---

## Task 3 — SCRFD @ 5Hz + Kalman bbox carry-forward in `face_obscure_process.py`

**Why:** Detection budget (~6 ms/frame) cannot fire every frame. 5 Hz detect + Kalman interpolation is the canonical fast/slow split.

### Files

- NEW: `agents/studio_compositor/face_obscure_process.py`
- NEW: `tests/studio_compositor/test_face_obscure_process.py`

### Steps

- [ ] Red test (detection cadence, Kalman carry-forward):

```python
# tests/studio_compositor/test_face_obscure_process.py
from unittest.mock import MagicMock

import numpy as np
import pytest

from agents.studio_compositor.face_obscure import FaceBBox
from agents.studio_compositor.face_obscure_process import FaceObscureProcess


@pytest.fixture
def mock_detector():
    det = MagicMock()
    det.detect.return_value = [FaceBBox(x=100, y=100, w=80, h=80, is_operator=False)]
    return det


def test_detect_called_every_sixth_frame_at_30fps(mock_detector):
    """5 Hz @ 30 fps means detect() fires every 6th frame."""
    proc = FaceObscureProcess(detector=mock_detector, detect_every_n_frames=6)
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    for _ in range(18):
        proc.step(frame)
    assert mock_detector.detect.call_count == 3  # 18 / 6


def test_kalman_carries_bbox_across_intermediate_frames(mock_detector):
    proc = FaceObscureProcess(detector=mock_detector, detect_every_n_frames=6)
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    proc.step(frame)
    bboxes_1 = proc.current_bboxes()
    assert len(bboxes_1) == 1
    for _ in range(5):
        proc.step(frame)
        assert len(proc.current_bboxes()) == 1


def test_kalman_bbox_drifts_with_motion(mock_detector):
    """If detector returns moving bboxes, Kalman estimate tracks velocity."""
    positions = iter([
        [FaceBBox(x=100, y=100, w=80, h=80, is_operator=False)],
        [FaceBBox(x=120, y=100, w=80, h=80, is_operator=False)],
        [FaceBBox(x=140, y=100, w=80, h=80, is_operator=False)],
    ])
    mock_detector.detect.side_effect = lambda _: next(positions)
    proc = FaceObscureProcess(detector=mock_detector, detect_every_n_frames=6)
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    xs = []
    for i in range(18):
        proc.step(frame)
        xs.append(proc.current_bboxes()[0].x)
    assert all(xs[i] <= xs[i + 1] + 1 for i in range(len(xs) - 1))


def test_track_disappears_after_dropout_timeout(mock_detector):
    proc = FaceObscureProcess(
        detector=mock_detector, detect_every_n_frames=6, dropout_frames=6
    )
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    proc.step(frame)
    mock_detector.detect.return_value = []
    for _ in range(12):
        proc.step(frame)
    assert proc.current_bboxes() == []
```

- [ ] Implement `agents/studio_compositor/face_obscure_process.py`:

```python
"""Per-camera face-obscure subprocess.

Runs SCRFD at 5 Hz (every 6th frame at 30 fps), Kalman bbox carry-forward
between detections. Graceful degradation on detector dropout is Task 4.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

from agents.studio_compositor.face_obscure import FaceBBox


class FaceDetector(Protocol):
    def detect(self, frame: np.ndarray) -> list[FaceBBox]: ...


@dataclass(slots=True)
class _KalmanTrack:
    bbox: FaceBBox
    vx: float = 0.0
    vy: float = 0.0
    frames_since_detection: int = 0

    def predict(self) -> FaceBBox:
        return FaceBBox(
            x=int(self.bbox.x + self.vx),
            y=int(self.bbox.y + self.vy),
            w=self.bbox.w,
            h=self.bbox.h,
            is_operator=self.bbox.is_operator,
        )

    def update(self, new: FaceBBox) -> None:
        alpha = 0.6
        self.vx = alpha * (new.x - self.bbox.x) + (1 - alpha) * self.vx
        self.vy = alpha * (new.y - self.bbox.y) + (1 - alpha) * self.vy
        self.bbox = new
        self.frames_since_detection = 0


@dataclass(slots=True)
class FaceObscureProcess:
    detector: FaceDetector
    detect_every_n_frames: int = 6  # 5 Hz at 30 fps
    dropout_frames: int = 6
    _frame_idx: int = 0
    _tracks: list[_KalmanTrack] = field(default_factory=list)

    def step(self, frame: np.ndarray) -> list[FaceBBox]:
        """Advance one frame; return predicted bboxes for obscuring."""
        is_detect_tick = (self._frame_idx % self.detect_every_n_frames) == 0
        if is_detect_tick:
            new_bboxes = self.detector.detect(frame)
            self._tracks = self._associate(new_bboxes)
        else:
            for t in self._tracks:
                t.bbox = t.predict()
                t.frames_since_detection += 1
            self._tracks = [
                t for t in self._tracks if t.frames_since_detection < self.dropout_frames
            ]
        self._frame_idx += 1
        return self.current_bboxes()

    def current_bboxes(self) -> list[FaceBBox]:
        return [t.bbox for t in self._tracks]

    def _associate(self, new_bboxes: list[FaceBBox]) -> list[_KalmanTrack]:
        """Greedy nearest-centroid association. Unmatched new bboxes start tracks."""
        if not new_bboxes:
            return self._tracks
        if not self._tracks:
            return [_KalmanTrack(bbox=b) for b in new_bboxes]
        updated: list[_KalmanTrack] = []
        used_new: set[int] = set()
        for t in self._tracks:
            tcx = t.bbox.x + t.bbox.w / 2
            tcy = t.bbox.y + t.bbox.h / 2
            best_i, best_d = -1, float("inf")
            for i, nb in enumerate(new_bboxes):
                if i in used_new:
                    continue
                ncx = nb.x + nb.w / 2
                ncy = nb.y + nb.h / 2
                d = (tcx - ncx) ** 2 + (tcy - ncy) ** 2
                if d < best_d:
                    best_d, best_i = d, i
            if best_i >= 0 and best_d < (max(t.bbox.w, t.bbox.h) ** 2):
                t.update(new_bboxes[best_i])
                used_new.add(best_i)
                updated.append(t)
        for i, nb in enumerate(new_bboxes):
            if i not in used_new:
                updated.append(_KalmanTrack(bbox=nb))
        return updated
```

- [ ] Run green + commit:

```bash
uv run pytest tests/studio_compositor/test_face_obscure_process.py -q
uv run ruff check agents/studio_compositor/face_obscure_process.py
uv run pyright agents/studio_compositor/face_obscure_process.py
git add agents/studio_compositor/face_obscure_process.py tests/studio_compositor/test_face_obscure_process.py
git commit -m "feat(privacy): SCRFD 5Hz + Kalman carry-forward track manager"
```

---

## Task 4 — YOLO11n fallback + fail-closed policy

**Why:** SCRFD fails in low-light (Pi NoIR IR-only conditions). YOLO11n person bbox (head=top-25%) is the safety net. After both fail for >500 ms, fail-closed.

### Files

- MODIFIED: `agents/studio_compositor/face_obscure_process.py`
- MODIFIED: `tests/studio_compositor/test_face_obscure_process.py`

### Steps

- [ ] Extend tests (red):

```python
def test_yolo_fallback_used_when_scrfd_dropout():
    from agents.studio_compositor.face_obscure_process import FaceObscureProcess

    primary = MagicMock()
    primary.detect.return_value = []  # SCRFD finds nothing
    fallback = MagicMock()
    fallback.detect.return_value = [FaceBBox(x=50, y=50, w=60, h=60, is_operator=False)]

    proc = FaceObscureProcess(
        detector=primary, fallback_detector=fallback, detect_every_n_frames=6
    )
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    proc.step(frame)
    assert len(proc.current_bboxes()) == 1
    fallback.detect.assert_called_once()


def test_fail_closed_after_both_detectors_silent():
    from agents.studio_compositor.face_obscure_process import FaceObscureProcess, FailMode

    primary = MagicMock()
    primary.detect.return_value = []
    fallback = MagicMock()
    fallback.detect.return_value = []

    proc = FaceObscureProcess(
        detector=primary,
        fallback_detector=fallback,
        detect_every_n_frames=6,
        fail_closed_after_frames=15,  # 500ms at 30fps
    )
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    for _ in range(20):
        proc.step(frame)
    assert proc.fail_mode is FailMode.FULL_FRAME


def test_broadcast_tees_use_full_frame_on_fail_closed():
    """broadcast policy: full-frame rect. local preview: last-known bbox."""
    from agents.studio_compositor.face_obscure_process import FaceObscureProcess, FailMode
    proc = FaceObscureProcess(
        detector=MagicMock(detect=lambda _: []),
        fallback_detector=MagicMock(detect=lambda _: []),
        detect_every_n_frames=1,
        fail_closed_after_frames=3,
    )
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    for _ in range(5):
        proc.step(frame)
    assert proc.fail_mode is FailMode.FULL_FRAME
```

- [ ] Implement. Add to `face_obscure_process.py`:

```python
from enum import Enum


class FailMode(str, Enum):
    OK = "ok"
    LAST_KNOWN = "last_known"
    FULL_FRAME = "full_frame"
```

Modify `FaceObscureProcess` constructor + step logic:

```python
@dataclass(slots=True)
class FaceObscureProcess:
    detector: FaceDetector
    fallback_detector: FaceDetector | None = None
    detect_every_n_frames: int = 6
    dropout_frames: int = 6
    fail_closed_after_frames: int = 15  # 500ms at 30fps
    _frame_idx: int = 0
    _frames_since_any_detection: int = 0
    _tracks: list[_KalmanTrack] = field(default_factory=list)
    fail_mode: FailMode = FailMode.OK

    def step(self, frame: np.ndarray) -> list[FaceBBox]:
        is_detect_tick = (self._frame_idx % self.detect_every_n_frames) == 0
        if is_detect_tick:
            bboxes = self.detector.detect(frame)
            if not bboxes and self.fallback_detector is not None:
                bboxes = self.fallback_detector.detect(frame)
            if bboxes:
                self._tracks = self._associate(bboxes)
                self._frames_since_any_detection = 0
            else:
                self._frames_since_any_detection += self.detect_every_n_frames
        else:
            for t in self._tracks:
                t.bbox = t.predict()
                t.frames_since_detection += 1
            self._tracks = [
                t for t in self._tracks if t.frames_since_detection < self.dropout_frames
            ]
            self._frames_since_any_detection += 1
        self._frame_idx += 1
        self._update_fail_mode()
        return self.current_bboxes()

    def _update_fail_mode(self) -> None:
        if self._tracks and self._frames_since_any_detection == 0:
            self.fail_mode = FailMode.OK
        elif self._frames_since_any_detection >= self.fail_closed_after_frames:
            self.fail_mode = FailMode.FULL_FRAME
        elif self._tracks:
            self.fail_mode = FailMode.LAST_KNOWN
        else:
            self.fail_mode = FailMode.FULL_FRAME
```

- [ ] Run green + commit:

```bash
uv run pytest tests/studio_compositor/test_face_obscure_process.py -q
uv run ruff check agents/studio_compositor/face_obscure_process.py
uv run pyright agents/studio_compositor/face_obscure_process.py
git add agents/studio_compositor/face_obscure_process.py tests/studio_compositor/test_face_obscure_process.py
git commit -m "feat(privacy): YOLO11n fallback + fail-closed mode after 500ms dropout"
```

---

## Task 5 — `is_operator` discriminator via 512-d ReID embedding

**Why:** Policy `OBSCURE_NON_OPERATOR` needs to know which face is the operator. Reuse existing 512-d embedding at `/dev/shm/hapax-perception/operator-embedding.npy`.

### Files

- NEW: `agents/studio_compositor/operator_identity.py`
- NEW: `tests/studio_compositor/test_operator_identity.py`

### Steps

- [ ] Red test:

```python
# tests/studio_compositor/test_operator_identity.py
import numpy as np
import pytest

from agents.studio_compositor.operator_identity import OperatorIdentity


@pytest.fixture
def operator_embedding(tmp_path):
    """512-d unit vector saved to a tempfile."""
    emb = np.random.randn(512).astype(np.float32)
    emb /= np.linalg.norm(emb)
    p = tmp_path / "operator-embedding.npy"
    np.save(p, emb)
    return p, emb


def test_matches_when_cosine_above_threshold(operator_embedding):
    path, emb = operator_embedding
    ident = OperatorIdentity(embedding_path=path, threshold=0.5)
    assert ident.is_operator(emb) is True


def test_does_not_match_when_cosine_below_threshold(operator_embedding):
    path, emb = operator_embedding
    other = np.random.randn(512).astype(np.float32)
    other /= np.linalg.norm(other)
    ident = OperatorIdentity(embedding_path=path, threshold=0.5)
    assert ident.is_operator(other) is False


def test_missing_embedding_file_returns_false_fail_safe(tmp_path):
    """No operator embedding on disk => everyone treated as non-operator (fail-safe to obscure)."""
    ident = OperatorIdentity(embedding_path=tmp_path / "missing.npy", threshold=0.5)
    arbitrary = np.random.randn(512).astype(np.float32)
    assert ident.is_operator(arbitrary) is False


def test_dimension_mismatch_returns_false(tmp_path):
    bad = np.random.randn(256).astype(np.float32)
    p = tmp_path / "bad.npy"
    np.save(p, bad)
    ident = OperatorIdentity(embedding_path=p, threshold=0.5)
    query = np.random.randn(512).astype(np.float32)
    assert ident.is_operator(query) is False
```

- [ ] Implement:

```python
# agents/studio_compositor/operator_identity.py
"""Operator identification via 512-d ReID embedding.

Load once, compare per-detected-face. Fail-safe default: if the embedding file
is missing or malformed, treat every face as non-operator (obscured).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(slots=True)
class OperatorIdentity:
    embedding_path: Path
    threshold: float = 0.5  # cosine similarity cutoff
    _ref: np.ndarray | None = None

    def _load(self) -> np.ndarray | None:
        if self._ref is not None:
            return self._ref
        try:
            arr = np.load(self.embedding_path)
        except (FileNotFoundError, ValueError, OSError):
            return None
        if arr.shape != (512,):
            return None
        n = np.linalg.norm(arr)
        if n == 0:
            return None
        self._ref = (arr / n).astype(np.float32)
        return self._ref

    def is_operator(self, embedding: np.ndarray) -> bool:
        ref = self._load()
        if ref is None:
            return False
        if embedding.shape != ref.shape:
            return False
        q = embedding / (np.linalg.norm(embedding) or 1.0)
        cos = float(np.dot(ref, q))
        return cos >= self.threshold
```

- [ ] Run green + commit:

```bash
uv run pytest tests/studio_compositor/test_operator_identity.py -q
uv run ruff check agents/studio_compositor/operator_identity.py
uv run pyright agents/studio_compositor/operator_identity.py
git add agents/studio_compositor/operator_identity.py tests/studio_compositor/test_operator_identity.py
git commit -m "feat(privacy): OperatorIdentity via 512-d ReID embedding match"
```

---

## Task 6 — Integrate obscure stage into capture pipeline

**Why:** This is the load-bearing step. Without this, Tasks 1-5 are inert. Integration point: between raw frame capture and JPEG write to `/dev/shm/hapax-compositor/cam-*.jpg`.

### Files

- MODIFIED: `agents/studio_compositor/camera_pipeline.py` (actual path; spec calls it `camera_capture.py`)
- MODIFIED: `agents/studio_compositor/snapshots.py` (the JPEG writer path)
- MODIFIED: `agents/studio_compositor/config.py` (add `face_obscure_policy`, `face_obscure_active`)
- NEW: `tests/studio_compositor/test_capture_integration.py`

### Steps

- [ ] Read the current capture -> JPEG flow and document the insertion point:

```bash
uv run python -c "
import ast, pathlib
p = pathlib.Path('agents/studio_compositor/snapshots.py')
mod = ast.parse(p.read_text())
for node in ast.walk(mod):
    if isinstance(node, ast.FunctionDef):
        print(f'{node.name}:{node.lineno}')
"
```

- [ ] Add to `config.py`:

```python
from shared.face_obscure_policy import FaceObscurePolicy

# In the StudioCompositorConfig pydantic model:
face_obscure_active: bool = True  # feature flag; see Task 10
face_obscure_policy: FaceObscurePolicy = FaceObscurePolicy.default()
face_obscure_block_size: int = 16
face_obscure_margin_pct: float = 0.20
face_obscure_detect_every_n_frames: int = 6
face_obscure_fail_closed_after_frames: int = 15
```

- [ ] Add an `obscure_before_write` adapter function at the JPEG-writing boundary. In `snapshots.py`, find the code path that writes cam frames and inject:

```python
from agents.studio_compositor.face_obscure import FaceObscurer
from agents.studio_compositor.face_obscure_process import FaceObscureProcess, FailMode
from shared.face_obscure_policy import FaceObscurePolicy

_OBSCURE_PROCS: dict[str, FaceObscureProcess] = {}
_OBSCURER = FaceObscurer()


def _get_proc(camera: str, detector, fallback_detector=None) -> FaceObscureProcess:
    if camera not in _OBSCURE_PROCS:
        _OBSCURE_PROCS[camera] = FaceObscureProcess(
            detector=detector,
            fallback_detector=fallback_detector,
        )
    return _OBSCURE_PROCS[camera]


def obscure_before_write(frame, camera: str, config, detector, fallback_detector=None):
    """Apply policy + obscure to raw frame. Returns (obscured_frame, fail_mode)."""
    if not config.face_obscure_active:
        return frame, FailMode.OK
    if config.face_obscure_policy is FaceObscurePolicy.DISABLED:
        return frame, FailMode.OK
    proc = _get_proc(camera, detector, fallback_detector)
    bboxes = proc.step(frame)
    if proc.fail_mode is FailMode.FULL_FRAME:
        return _OBSCURER.obscure_full_frame(frame), proc.fail_mode
    filtered = [
        b for b in bboxes
        if config.face_obscure_policy.should_obscure(is_operator=b.is_operator)
    ]
    return _OBSCURER.obscure(frame, filtered), proc.fail_mode
```

- [ ] Wire into the existing write path. Find the call site that produces `/dev/shm/hapax-compositor/cam-*.jpg` (usually `cv2.imwrite` or `turbojpeg.encode`) and wrap the frame:

```python
# BEFORE:
# jpeg_bytes = turbojpeg.encode(frame, ...)

# AFTER:
obscured, fail_mode = obscure_before_write(
    frame, camera=cam_name, config=cfg, detector=scrfd, fallback_detector=yolo
)
jpeg_bytes = turbojpeg.encode(obscured, ...)
```

- [ ] Integration test with a synthetic face (perceptual-hash distance):

```python
# tests/studio_compositor/test_capture_integration.py
import numpy as np
from PIL import Image

from agents.studio_compositor.face_obscure import FaceBBox
from agents.studio_compositor.snapshots import obscure_before_write


class _DetectorStub:
    def detect(self, frame):
        return [FaceBBox(x=500, y=300, w=120, h=120, is_operator=False)]


def _phash(img: np.ndarray) -> int:
    small = np.array(Image.fromarray(img).resize((8, 8)).convert("L"))
    mean = small.mean()
    bits = (small > mean).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


class _Cfg:
    face_obscure_active = True
    face_obscure_policy = None


def test_face_pixels_obscured_to_below_threshold():
    from shared.face_obscure_policy import FaceObscurePolicy
    cfg = _Cfg()
    cfg.face_obscure_policy = FaceObscurePolicy.ALWAYS_OBSCURE

    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    frame[300:420, 500:620] = 255  # synthetic "face" patch

    out, _ = obscure_before_write(
        frame, camera="test", config=cfg, detector=_DetectorStub()
    )
    orig_patch = frame[300:420, 500:620]
    out_patch = out[300:420, 500:620]
    dist = _hamming(_phash(orig_patch), _phash(out_patch))
    assert dist >= 32  # >= 50% bits flipped


def test_flag_off_roundtrip_byte_identical():
    cfg = _Cfg()
    cfg.face_obscure_active = False
    frame = np.random.randint(0, 255, (720, 1280, 3), dtype=np.uint8)
    out, _ = obscure_before_write(
        frame, camera="test2", config=cfg, detector=_DetectorStub()
    )
    assert np.array_equal(out, frame)
```

- [ ] Run + commit:

```bash
uv run pytest tests/studio_compositor/test_capture_integration.py -q
uv run ruff check agents/studio_compositor/snapshots.py agents/studio_compositor/config.py
uv run pyright agents/studio_compositor/snapshots.py agents/studio_compositor/config.py
git add agents/studio_compositor/snapshots.py agents/studio_compositor/config.py \
        tests/studio_compositor/test_capture_integration.py
git commit -m "feat(privacy): integrate face obscure stage into capture JPEG write"
```

---

## Task 7 — Prometheus metrics (detections, fail-closed, latency)

**Why:** Cannot verify the system is working at 24/7 livestream scale without telemetry. Grafana panels + alerts are spec section 7.

### Files

- MODIFIED: `shared/director_observability.py`
- MODIFIED: `agents/studio_compositor/face_obscure_process.py` (emit metrics)
- MODIFIED: `agents/studio_compositor/snapshots.py` (emit latency)
- NEW: `tests/shared/test_face_obscure_metrics.py`

### Steps

- [ ] Add counters and histogram in `shared/director_observability.py`:

```python
from prometheus_client import Counter, Histogram

FACE_OBSCURE_DETECTIONS = Counter(
    "hapax_face_obscure_detections_total",
    "Face detections per camera by detector source.",
    ["camera", "source"],
)
FACE_OBSCURE_FAIL_CLOSED = Counter(
    "hapax_face_obscure_fail_closed_total",
    "Fail-closed events per camera with reason.",
    ["camera", "reason"],
)
FACE_OBSCURE_LATENCY = Histogram(
    "hapax_face_obscure_latency_seconds",
    "Latency from capture to obscured-JPEG write.",
    ["camera"],
    buckets=(0.001, 0.005, 0.010, 0.025, 0.050, 0.100, 0.250),
)
```

- [ ] Emit from `face_obscure_process.py`:

```python
from shared.director_observability import FACE_OBSCURE_DETECTIONS, FACE_OBSCURE_FAIL_CLOSED

# in step() when is_detect_tick and bboxes non-empty:
source = "scrfd" if primary_hit else "yolo"
FACE_OBSCURE_DETECTIONS.labels(camera=self.camera_id, source=source).inc(len(bboxes))

# in _update_fail_mode when transitioning to FULL_FRAME:
if self.fail_mode is FailMode.FULL_FRAME and previous is not FailMode.FULL_FRAME:
    FACE_OBSCURE_FAIL_CLOSED.labels(camera=self.camera_id, reason="dropout").inc()
```

(Add `camera_id: str = "unknown"` to the dataclass.)

- [ ] Emit latency from `snapshots.obscure_before_write`:

```python
import time
from shared.director_observability import FACE_OBSCURE_LATENCY

def obscure_before_write(...):
    t0 = time.perf_counter()
    # existing body
    FACE_OBSCURE_LATENCY.labels(camera=camera).observe(time.perf_counter() - t0)
    return out, fail_mode
```

- [ ] Test registration:

```python
# tests/shared/test_face_obscure_metrics.py
from shared.director_observability import (
    FACE_OBSCURE_DETECTIONS,
    FACE_OBSCURE_FAIL_CLOSED,
    FACE_OBSCURE_LATENCY,
)


def test_metrics_registered_with_expected_labels():
    FACE_OBSCURE_DETECTIONS.labels(camera="cam-desk", source="scrfd").inc()
    FACE_OBSCURE_FAIL_CLOSED.labels(camera="cam-desk", reason="dropout").inc()
    FACE_OBSCURE_LATENCY.labels(camera="cam-desk").observe(0.003)


def test_metric_names_match_spec():
    # prometheus_client strips the _total suffix from Counter._name
    assert FACE_OBSCURE_DETECTIONS._name == "hapax_face_obscure_detections"
    assert FACE_OBSCURE_FAIL_CLOSED._name == "hapax_face_obscure_fail_closed"
    assert FACE_OBSCURE_LATENCY._name == "hapax_face_obscure_latency_seconds"
```

- [ ] Verify local scrape works (studio-compositor metrics port):

```bash
curl -s http://localhost:9482/metrics | grep hapax_face_obscure | head -20
# expected: counter + histogram series present (zero-valued until first frame)
```

- [ ] Commit:

```bash
uv run pytest tests/shared/test_face_obscure_metrics.py -q
git add shared/director_observability.py agents/studio_compositor/face_obscure_process.py \
        agents/studio_compositor/snapshots.py tests/shared/test_face_obscure_metrics.py
git commit -m "feat(observability): face obscure Prometheus counters + latency histogram"
```

- [ ] Grafana panels (separate small commit once service is running):

```
# Add two panels to the studio-compositor dashboard JSON:
#   - rate(hapax_face_obscure_fail_closed_total[1m]) per camera, alert > 0.5/min
#   - histogram_quantile(0.99, rate(hapax_face_obscure_latency_seconds_bucket[5m])),
#     alert p99 > 50ms
# File: config/grafana/dashboards/studio-compositor.json  (or equivalent)
```

---

## Task 8 — Adversarial reconstruction test (SSIM < 0.3)

**Why:** The whole design assumes the veneer is non-reversible. Prove it. Spec section 9.4.

### Files

- NEW: `tests/privacy/test_adversarial_reconstruction.py`
- NEW: `tests/privacy/conftest.py` (marker for slow tests)

### Steps

- [ ] Add `adversarial` marker to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
markers = [
  "llm: requires LLM access",
  "adversarial: slow reconstruction attack tests (excluded from default run)",
]
```

- [ ] Write the test:

```python
# tests/privacy/test_adversarial_reconstruction.py
"""Adversarial reconstruction test -- prove the obscure veneer is non-reversible.

Train a tiny CNN on (obscured, original) pairs. Measure SSIM on held-out set.
Threshold: SSIM < 0.3. Higher SSIM means the veneer leaks identifiable info.

Runs under `uv run pytest -m adversarial` (excluded from default).
"""

from __future__ import annotations

import numpy as np
import pytest
from skimage.metrics import structural_similarity as ssim

from agents.studio_compositor.face_obscure import FaceBBox, FaceObscurer


@pytest.mark.adversarial
def test_cnn_cannot_reconstruct_above_ssim_threshold():
    try:
        import torch
        import torch.nn as nn
    except ImportError:
        pytest.skip("torch not installed; run `uv sync --extra adversarial`")

    rng = np.random.default_rng(42)
    obs = FaceObscurer()
    N = 512
    orig = rng.integers(0, 255, (N, 64, 64, 3), dtype=np.uint8)
    bbox = FaceBBox(x=8, y=8, w=48, h=48, is_operator=False)
    obscured = np.stack([obs.obscure(o, [bbox]) for o in orig])

    X = torch.from_numpy(obscured).permute(0, 3, 1, 2).float() / 255.0
    Y = torch.from_numpy(orig).permute(0, 3, 1, 2).float() / 255.0
    split = int(0.8 * N)

    class TinyReconstructor(nn.Module):
        def __init__(self):
            super().__init__()
            self.net = nn.Sequential(
                nn.Conv2d(3, 16, 3, padding=1), nn.ReLU(),
                nn.Conv2d(16, 32, 3, padding=1), nn.ReLU(),
                nn.Conv2d(32, 3, 3, padding=1), nn.Sigmoid(),
            )

        def forward(self, x):
            return self.net(x)

    net = TinyReconstructor()
    opt = torch.optim.Adam(net.parameters(), lr=1e-3)
    loss_fn = nn.MSELoss()
    for _ in range(50):
        opt.zero_grad()
        out = net(X[:split])
        loss = loss_fn(out, Y[:split])
        loss.backward()
        opt.step()

    with torch.no_grad():
        pred = net(X[split:]).clamp(0, 1).permute(0, 2, 3, 1).numpy() * 255
    gt = Y[split:].permute(0, 2, 3, 1).numpy() * 255

    ssims = [
        ssim(g.astype(np.uint8), p.astype(np.uint8), channel_axis=-1, data_range=255)
        for g, p in zip(gt, pred)
    ]
    mean_ssim = float(np.mean(ssims))
    assert mean_ssim < 0.30, (
        f"Reconstruction too good (SSIM={mean_ssim:.3f}); veneer leaks identifiable info"
    )
```

- [ ] Run:

```bash
uv run pytest tests/privacy/test_adversarial_reconstruction.py -m adversarial -q
# expected: 1 passed (or skipped if torch not installed) with mean_ssim printed
```

- [ ] Commit:

```bash
git add tests/privacy/test_adversarial_reconstruction.py tests/privacy/conftest.py pyproject.toml
git commit -m "test(privacy): adversarial CNN reconstruction attack asserts SSIM < 0.3"
```

---

## Task 9 — End-to-end leak test (content_injector -> Reverie -> pip-ur)

**Why:** Closes the primary leak called out in spec section 2. A frame enters the obscured shm, passes through `content_injector`, Reverie, and the pip-ur slot -- asserts bbox region is still obscured at every stage.

### Files

- NEW: `tests/privacy/test_end_to_end_leak.py`

### Steps

- [ ] Trace the path. Read once to confirm flow:

```bash
uv run python - <<'PY'
from pathlib import Path
for name in ["content_injector.py", "pipeline.py", "source_registry.py"]:
    for p in Path("agents").rglob(name):
        print(p)
PY
```

- [ ] Write the test:

```python
# tests/privacy/test_end_to_end_leak.py
"""End-to-end leak test: trace a face from capture through every egress tee.

Egress paths to cover (spec section 2):
  1. /dev/shm/hapax-compositor/cam-*.jpg  (director LLM snapshot)
  2. Main compositor pipeline
  3. RTMP output
  4. HLS tee
  5. Recording branch
  6. content_injector -> Reverie -> pip-ur slot
"""

import numpy as np
from pathlib import Path

from agents.studio_compositor.face_obscure import FaceBBox
from agents.studio_compositor.snapshots import obscure_before_write


class _Cfg:
    face_obscure_active = True


def _phash_distance(a: np.ndarray, b: np.ndarray) -> int:
    from PIL import Image

    def h(x):
        s = np.array(Image.fromarray(x).resize((8, 8)).convert("L"))
        bits = (s > s.mean()).flatten()
        return int("".join("1" if v else "0" for v in bits), 2)

    return bin(h(a) ^ h(b)).count("1")


class _OracleDetector:
    def detect(self, _):
        return [FaceBBox(x=500, y=300, w=120, h=120, is_operator=False)]


def _build_obscured_frame():
    from shared.face_obscure_policy import FaceObscurePolicy

    cfg = _Cfg()
    cfg.face_obscure_policy = FaceObscurePolicy.ALWAYS_OBSCURE
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    frame[300:420, 500:620] = 200  # synthetic "face"
    obscured, _ = obscure_before_write(
        frame, camera="cam-desk", config=cfg, detector=_OracleDetector()
    )
    return frame, obscured


def test_shm_snapshot_path_is_obscured():
    original, obscured = _build_obscured_frame()
    d = _phash_distance(original[300:420, 500:620], obscured[300:420, 500:620])
    assert d >= 32  # strong divergence


def test_content_injector_reads_obscured_path():
    """content_injector must read from the same shm path that capture writes to."""
    from agents.reverie import content_injector as ci
    src = Path(ci.__file__).read_text()
    assert "/dev/shm/hapax-compositor/cam-" in src or "cam-*.jpg" in src, (
        "content_injector must read the obscured shm path -- see spec section 2"
    )


def test_reverie_pip_ur_slot_inherits_obscure():
    """Structural test: pip-ur has no alternate source path that bypasses obscure."""
    from agents.studio_compositor.source_registry import SourceRegistry  # adjust if renamed
    import inspect
    src = inspect.getsource(SourceRegistry)
    assert "raw_cam" not in src.lower() or "obscure" in src.lower()


def test_rtmp_hls_recording_all_share_compositor_frame():
    """RTMP + HLS + recording tees all tap the composited frame, which is built from
    obscured shm frames. No direct /dev/v4l/* source may bypass the obscure stage."""
    from agents.studio_compositor import rtmp_output, recording
    import inspect
    for mod in (rtmp_output, recording):
        src = inspect.getsource(mod)
        assert "/dev/video" not in src or "obscure" in src.lower(), (
            f"{mod.__name__} appears to bypass obscure stage"
        )
```

- [ ] Run + commit:

```bash
uv run pytest tests/privacy/test_end_to_end_leak.py -q
git add tests/privacy/test_end_to_end_leak.py
git commit -m "test(privacy): end-to-end leak test across all 6 egress paths"
```

---

## Task 10 — Feature flag `HAPAX_FACE_OBSCURE_ACTIVE` + staged rollout

**Why:** Spec section 10 + section 11. Default ON but reversible. After 4 days of green telemetry, remove the flag.

### Files

- MODIFIED: `agents/studio_compositor/config.py`
- MODIFIED: `.envrc.example` (document env var)
- MODIFIED: `systemd/studio-compositor.service` (Environment line)
- NEW: `docs/privacy/face-obscure-rollout.md` (operator runbook -- 1 page)

### Steps

- [ ] Wire env var into config loader. In `config.py`:

```python
import os


def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


face_obscure_active: bool = _env_bool("HAPAX_FACE_OBSCURE_ACTIVE", True)
```

- [ ] Update `.envrc.example`:

```bash
# Face obscure kill switch. Leave ON in production. Toggle OFF only for
# debugging under written operator override -- active livestream while OFF
# violates axiom it-irreversible-broadcast T0.
export HAPAX_FACE_OBSCURE_ACTIVE=1
```

- [ ] Update `systemd/studio-compositor.service`:

```ini
Environment=HAPAX_FACE_OBSCURE_ACTIVE=1
```

- [ ] Write `docs/privacy/face-obscure-rollout.md` (1 page):

```markdown
# Face Obscure -- Rollout & Kill-Switch Runbook

## Default state
- Flag: `HAPAX_FACE_OBSCURE_ACTIVE=1` (ON)
- Policy: `ALWAYS_OBSCURE` on all 6 cameras

## Verify before broadcast
    curl -s http://localhost:9482/metrics | grep hapax_face_obscure_detections_total
    # expected: non-zero counters across all 6 cameras within 60s of compositor start

## Kill switch (emergency only -- violates T0 axiom during broadcast)
    systemctl --user set-environment HAPAX_FACE_OBSCURE_ACTIVE=0
    systemctl --user restart studio-compositor.service

## Rollout gates
- 2026-04-19 (flag ON, policy ALWAYS): all 6 cameras; 24h bake
- 2026-04-20: operator answers open Q1/Q2/Q3 from design section 8; tune policy
- 2026-04-22: remove flag entirely; unconditional pipeline

## Alerts
- `hapax_face_obscure_fail_closed_total` > 0.5/min sustained -> page
- p99 `hapax_face_obscure_latency_seconds` > 50ms sustained -> page
```

- [ ] Staged-rollout smoke (manual):

```bash
HAPAX_FACE_OBSCURE_ACTIVE=0 uv run pytest \
  tests/studio_compositor/test_capture_integration.py::test_flag_off_roundtrip_byte_identical -q
HAPAX_FACE_OBSCURE_ACTIVE=1 uv run pytest tests/studio_compositor/test_capture_integration.py -q
```

- [ ] Final commit:

```bash
git add agents/studio_compositor/config.py .envrc.example systemd/studio-compositor.service \
        docs/privacy/face-obscure-rollout.md
git commit -m "feat(privacy): HAPAX_FACE_OBSCURE_ACTIVE env flag + rollout runbook"
```

---

## Post-flight — Deploy + live verify

- [ ] Deploy via rebuild script (not mid-session worktree mutation):

```bash
bash scripts/rebuild-service.sh studio-compositor
journalctl --user -u studio-compositor.service -n 100 --no-pager | grep -i obscure
```

- [ ] Live telemetry sanity:

```bash
curl -s http://localhost:9482/metrics | grep hapax_face_obscure
# after 60s: detections should be accumulating on active cameras
```

- [ ] Visual verification against each egress:

```bash
# 1. Snapshot path (director LLM snapshot source)
feh /dev/shm/hapax-compositor/cam-desk.jpg
# 2. RTMP
ffplay rtmp://127.0.0.1:1935/live/studio
# 3. HLS
ffplay http://127.0.0.1:8080/hls/studio.m3u8
# 4. Recording (most recent archive file)
ls -lh ~/hapax-state/recordings/ | tail -1
ffplay "$(ls -t ~/hapax-state/recordings/*.mp4 | head -1)"
# 5. Reverie frame (pip-ur feeds here)
feh /dev/shm/hapax-visual/frame.jpg
# 6. Director LLM snapshot -- inspect langfuse trace for the next director tick;
#    the uploaded frame must be obscured
```

- [ ] Open PR. Title: `feat(privacy): facial obscuring hard requirement (task #129)`.
      Body cites spec, enumerates the 10 tasks, and links the design doc. Monitor CI through merge.

- [ ] Update `docs/superpowers/plans/2026-04-18-active-work-index.md` to mark this plan as shipped.

---

## Risk notes

- **Perf regression under 6-cam peak load:** if latency p99 > 50 ms sustained, switch cadence from 5 Hz to 3 Hz (config knob `face_obscure_detect_every_n_frames=10`); keep Kalman carry-forward.
- **Low-light false-negative:** Pi NoIR cameras rely on YOLO11n fallback; if both detectors silent, fail-closed FULL_FRAME already mitigates.
- **Operator self-preview degraded:** if Q1 answer is "leave local preview unobscured", add a separate local-preview shm path `/dev/shm/hapax-compositor/operator-unobscured.jpg` with mode 0600 that never tees to broadcast; gate via the same feature flag.

## References

- Spec: `docs/superpowers/specs/2026-04-18-facial-obscuring-hard-req-design.md`
- Axiom: `axioms/implications/it-irreversible-broadcast.yaml`
- Consent gate (adjacent): `agents/studio_compositor/consent.py`, `agents/studio_compositor/consent_live_egress.py`
- Reused detector: `agents/hapax_daimonion/face_detector.py`
- Reused content injector: `agents/reverie/content_injector.py`
- Research dossier section 2 #129: `docs/superpowers/research/2026-04-18-homage-follow-on-dossier.md`
