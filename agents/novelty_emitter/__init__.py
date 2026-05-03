"""Novelty-shift impingement emitter (cc-task u3).

Watches the daimonion grounding-quality signal (`gqi`) and the visual-
chain recency-cluster similarity. When either surfaces a sustained
shift in novelty (gqi rises above ``GQI_HIGH_THRESHOLD`` after a
period below, or the recency cluster suddenly de-clusters), emits a
``novelty.shift`` impingement onto the canonical impingement bus so
the AffordancePipeline can route the recruitment.

Pre-this-emitter, the ``novelty.shift`` capability in
``shared.compositional_affordances`` was declared but no producer
emitted impingements that scored against it directly — recruitment
only landed when the AffordancePipeline's own
``_maybe_emit_perceptual_distance_impingement`` fired the
``content.too-similar-recently`` family. This emitter closes audit
underutilization U3 by adding a direct, time-series-driven emitter.

Phase 0 scope (this module):
  * Read gqi from ``/dev/shm/hapax-daimonion/grounding-quality.json``
  * Track previous tick's gqi value
  * Emit on rising-edge: previous < LOW threshold AND current > HIGH threshold
  * Append impingement payload to ``/dev/shm/hapax-dmn/impingements.jsonl``
  * Prometheus counter at ``/var/lib/node_exporter/textfile_collector/``
  * 1s tick cadence via systemd timer

Phase 1 (separate cc-task):
  * Per-camera novelty integration with ``visual_layer_aggregator``
  * Adaptive threshold based on rolling baseline
"""

from __future__ import annotations

__all__ = [
    "GQI_HIGH_THRESHOLD",
    "GQI_LOW_THRESHOLD",
    "NoveltyShiftEmitter",
    "NoveltyShiftReading",
    "build_impingement_payload",
    "emit_if_shifted",
]

from agents.novelty_emitter._emitter import (
    GQI_HIGH_THRESHOLD,
    GQI_LOW_THRESHOLD,
    NoveltyShiftEmitter,
    NoveltyShiftReading,
    build_impingement_payload,
    emit_if_shifted,
)
