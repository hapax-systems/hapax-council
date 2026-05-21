---
title: "Eigenform sensing design spec"
date: 2026-05-21
author: epsilon
status: draft
cc_task: 202605181733-hapax-perspective-phase0-research-eigenform-sensing
authority_case: CASE-202605181733-HAPAX-P
---

# Eigenform Sensing Design Spec

## 1. Concept

Eigenform sensing detects when the coupled operator–system state converges to a
fixed point of the iteration `T(x) = x`, where `T` is the system's response
function and `x` is the state vector. Convergence indicates the operator and
system have settled into a stable mode; divergence or orbit indicates transition.

## 2. Data model

### State vector (10 dimensions)

Defined in `shared/eigenform_analysis.py:NUMERIC_FIELDS`:

| Dimension | Source | Range | Update Hz |
|-----------|--------|-------|-----------|
| `presence` | IR/face detection | [0, 1] | ~2.5 |
| `flow_score` | Activity classifier | [0, 1] | ~2.5 |
| `audio_energy` | Audio RMS | [0, 1] | ~15 |
| `imagination_salience` | Imagination daemon `/dev/shm` | [0, 1] | ~1 |
| `visual_brightness` | Compositor frame mean luma | [0, 1] | ~30 |
| `heart_rate` | Watch biometrics (sensitive) | [40, 200] | ~0.1 |
| `operator_stress` | Stimmung dimension | [0, 1] | ~2.5 |
| `e_mesh` | Eigenform mesh energy | [0, 1] | ~2.5 |
| `restriction_residual_rms` | Governance restriction residual | [0, 1] | ~2.5 |
| `stimmung_stance` | Categorical → numeric via STANCE_MAP | {0.0, 0.1, 0.25, 0.5, 1.0} | ~2.5 |

### EigenformEntry (log record)

Written by `shared/eigenform_logger.py` to `/dev/shm/hapax-eigenform/state-log.jsonl`:

```python
{
    "ts": float,                    # time.time()
    "presence": float,
    "flow_score": float,
    "audio_energy": float,
    "imagination_salience": float,
    "visual_brightness": float,
    "heart_rate": float,            # sensitive — redacted in shm, kept in persistent log
    "operator_stress": float,       # sensitive — redacted in shm
    "stimmung_stance": str,         # "nominal" | "seeking" | "cautious" | "degraded" | "critical"
    "e_mesh": float,
    "restriction_residual_rms": float
}
```

### Storage

| Path | Retention | Max entries | Purpose |
|------|-----------|-------------|---------|
| `/dev/shm/hapax-eigenform/state-log.jsonl` | Volatile (RAM) | 500 | Real-time analysis window |
| `~/hapax-state/research/eigenform-log.jsonl` | Persistent (disk) | 50,000 | CHI 2027 evidence, offline analysis |

Sensitive fields (`heart_rate`, `operator_stress`) are redacted from the shm
log but retained in the persistent log (operator-only access).

## 3. Sensing loop interface

### Logger: `shared/eigenform_logger.py`

```python
def log_eigenform_state(
    perception_state: dict,
    *,
    path: Path = EIGENFORM_LOG,
    persistent_path: Path = PERSISTENT_LOG,
) -> None
```

Called by `agents/hapax_daimonion/_perception_state_writer.py` at each
perception tick (~2.5s). Extracts state vector from the perception state dict,
validates labels against allowed sets, writes to both ring buffers.

### Analyzer: `shared/eigenform_analysis.py`

```python
def analyze_convergence(
    *,
    path: Path = EIGENFORM_LOG,
    window: int = 10,
    threshold: float = 0.05,
) -> dict
```

Returns:
- `converged: bool` — L2 norm of consecutive state differences below threshold
  for `window` consecutive ticks
- `orbit: bool` — norm oscillates within bounded range without convergence
- `norm_history: list[float]` — recent T(x)-x norms for visualization
- `mean_norm: float` — average norm over window

## 4. Integration contract with perspective layer

### Upstream (data sources → eigenform logger)

The perception state writer (`_perception_state_writer.py`) calls
`log_eigenform_state()` with the full perception state dict. Each source
dimension is populated by its respective daemon or agent:

| Dimension | Populator | State file |
|-----------|-----------|------------|
| presence | IR fleet + face detection | `/dev/shm/hapax-perception/state.json` |
| flow_score | Activity classifier | `/dev/shm/hapax-perception/state.json` |
| audio_energy | Audio RMS probe | `/dev/shm/hapax-audio-health/` |
| imagination_salience | Imagination daemon | `/dev/shm/hapax-imagination/current.json` |
| visual_brightness | Compositor frame probe | `/dev/shm/hapax-compositor/` |
| heart_rate | Watch receiver | Logos API POST |
| operator_stress | Stimmung analyzer | `/dev/shm/hapax-stimmung/` |
| stimmung_stance | Stimmung analyzer | `/dev/shm/hapax-stimmung/` |

### Downstream (eigenform → consumers)

| Consumer | Reads | Purpose |
|----------|-------|---------|
| `shared/eigenform_analysis.py` | shm JSONL | Real-time convergence detection |
| CHI evidence pipeline | Persistent JSONL | Episode segmentation, T(x) analysis |
| HARDM ward (row 14) | shm state | 16-cell eigenform visualization |
| Stimmung stance transitions | Analysis output | Mode-change detection |

## 5. Pre-existing research

| Document | Contribution |
|----------|-------------|
| `docs/superpowers/plans/2026-05-17-hapax-perspective-implementation.md` | Track A tasks (REQ-01/02): eigenform fix + persist |
| `docs/research/2026-05-21-chi-evidence-pipeline-investigation.md` | Confirms eigenform logger exists and is functional |
| Memory: `project_hapax_apperception.md` | Self-band architecture context |
| Memory: `project_phenomenological_engineering.md` | Pre-reflective structure framing |
