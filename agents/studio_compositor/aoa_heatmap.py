"""AoA impingement-recruitment heatmap — maps live system activity to 340 panes.

Reads impingements from /dev/shm/hapax-dmn/impingements.jsonl, accumulates
per-pane heat with exponential decay, writes a flat f32 array to SHM for
the Rust renderer to consume.

Mapping hierarchy (depth → abstraction):
  Depth 0 (4 panes): macro-domains
    Face 0 (abd): Composition — camera, composition, attention, transition
    Face 1 (bcd): Modulation — mood, intensity, pace, silence
    Face 2 (cad): Surface — ward, homage, overlay, chrome
    Face 3 (acb): Programme — gem, preset, youtube, programme

  Depth 1 (16 panes): individual intent families within each domain
  Depth 2 (64 panes): per-family × material (void/air/water/earth/fire)
  Depth 3 (256 panes): per-family × dimension temporal heat

Each pane stores: heat (0-1), hue (0-1), saturation (0-1).
Heat decays exponentially with a configurable half-life.
"""

from __future__ import annotations

import json
import logging
import math
import os
import struct
import time
from pathlib import Path

log = logging.getLogger(__name__)

HEATMAP_PATH = Path("/dev/shm/hapax-imagination/aoa-heatmap.bin")
IMPINGEMENT_PATH = Path("/dev/shm/hapax-dmn/impingements.jsonl")
RECRUITMENT_PATH = Path(
    os.environ.get(
        "HAPAX_RECRUITMENT_LOG",
        str(Path.home() / "hapax-state" / "affordance" / "recruitment-log.jsonl"),
    )
)
RECRUITMENT_BOOST = 0.7

PANE_COUNT = 340
HEAT_HALF_LIFE_S = 20.0
DECAY_RATE = math.log(2) / HEAT_HALF_LIFE_S
TICK_HZ = 10

DOMAIN_FAMILIES: dict[int, list[str]] = {
    0: [
        "camera.hero",
        "composition.reframe",
        "attention.refocus",
        "attention.winner",
        "transition.fade",
        "transition.cut",
        "novelty.shift",
        "stream_mode.transition",
    ],
    1: [
        "mood.tone_pivot",
        "intensity.surge",
        "pace.tempo_shift",
        "silence.invitation",
        "preset.bias",
        "chrome.density",
        "narrative.autonomous_speech",
        "voice.register_shift",
    ],
    2: [
        "ward.size",
        "ward.position",
        "ward.staging",
        "ward.highlight",
        "ward.appearance",
        "ward.cadence",
        "ward.choreography",
        "overlay.emphasis",
        "overlay.foreground",
        "structural.emphasis",
    ],
    3: [
        "gem.emphasis",
        "gem.composition",
        "gem.spawn",
        "homage.rotation",
        "homage.emergence",
        "homage.swap",
        "homage.cycle",
        "homage.recede",
        "homage.expand",
        "youtube.direction",
        "youtube.telemetry",
        "programme.beat_advance",
    ],
}

FAMILY_TO_DOMAIN: dict[str, int] = {}
FAMILY_INDEX: dict[str, int] = {}
for domain_idx, families in DOMAIN_FAMILIES.items():
    for i, fam in enumerate(families):
        FAMILY_TO_DOMAIN[fam] = domain_idx
        FAMILY_INDEX[fam] = i

MATERIAL_INDEX = {"void": 0, "air": 1, "water": 2, "earth": 3, "fire": 4}

DIMENSION_NAMES = [
    "intensity",
    "tension",
    "depth",
    "coherence",
    "spectral_color",
    "temporal_distortion",
    "degradation",
    "pitch_displacement",
    "diffusion",
]

DOMAIN_HUES = {0: 0.52, 1: 0.83, 2: 0.12, 3: 0.35}


def _pane_ordinal_depth0(face_idx: int) -> int:
    return face_idx


def _pane_ordinal_depth1(domain: int, family_slot: int) -> int:
    return 4 + domain * 4 + (family_slot % 4)


def _pane_ordinal_depth2(domain: int, family_slot: int, material: int) -> int:
    base = 20
    slot = domain * 16 + family_slot * 4 + (material % 4)
    return base + (slot % 64)


def _pane_ordinal_depth3(domain: int, family_slot: int, dim_idx: int) -> int:
    base = 84
    slot = domain * 64 + family_slot * 9 + dim_idx
    return base + (slot % 256)


class AoaHeatmap:
    def __init__(self) -> None:
        self._heat = [0.0] * PANE_COUNT
        self._hue = [0.0] * PANE_COUNT
        self._sat = [0.5] * PANE_COUNT
        self._last_tick = time.monotonic()
        self._cursor = 0
        self._recruit_cursor = 0
        self._init_base_hues()

    def _init_base_hues(self) -> None:
        for domain_idx, hue in DOMAIN_HUES.items():
            p0 = _pane_ordinal_depth0(domain_idx)
            self._hue[p0] = hue
            families = DOMAIN_FAMILIES[domain_idx]
            for fi in range(min(len(families), 4)):
                p1 = _pane_ordinal_depth1(domain_idx, fi)
                if p1 < PANE_COUNT:
                    self._hue[p1] = hue + fi * 0.04
            for fi in range(len(families)):
                for mi in range(5):
                    p2 = _pane_ordinal_depth2(domain_idx, fi, mi)
                    if p2 < PANE_COUNT:
                        self._hue[p2] = hue + fi * 0.02 + mi * 0.01
                for di in range(9):
                    p3 = _pane_ordinal_depth3(domain_idx, fi, di)
                    if p3 < PANE_COUNT:
                        self._hue[p3] = hue + fi * 0.015 + di * 0.008

    def ingest_impingement(self, imp: dict) -> None:
        content = imp.get("content", {})
        family = content.get("intent_family", "")
        material = content.get("material", "void")
        salience = imp.get("strength", 0.0) or content.get("salience", 0.5)
        dims = content.get("dimensions", {})

        domain = FAMILY_TO_DOMAIN.get(family)
        if domain is None:
            domain = hash(family) % 4
        fi = FAMILY_INDEX.get(family, hash(family) % 8)
        mi = MATERIAL_INDEX.get(material, 0)

        p0 = _pane_ordinal_depth0(domain)
        self._heat[p0] = min(1.0, self._heat[p0] + salience * 0.8)

        p1 = _pane_ordinal_depth1(domain, fi)
        if p1 < PANE_COUNT:
            self._heat[p1] = min(1.0, self._heat[p1] + salience * 0.6)

        p2 = _pane_ordinal_depth2(domain, fi, mi)
        if p2 < PANE_COUNT:
            self._heat[p2] = min(1.0, self._heat[p2] + salience * 0.5)
            self._sat[p2] = min(1.0, 0.4 + salience * 0.6)

        for di, dname in enumerate(DIMENSION_NAMES):
            dval = dims.get(dname, 0.0)
            if dval > 0.01:
                p3 = _pane_ordinal_depth3(domain, fi, di)
                if p3 < PANE_COUNT:
                    self._heat[p3] = min(1.0, self._heat[p3] + dval * salience * 0.4)

    def decay(self, dt: float) -> None:
        factor = math.exp(-DECAY_RATE * dt)
        for i in range(PANE_COUNT):
            self._heat[i] *= factor
            self._heat[i] = max(self._heat[i], 0.03)

    def ingest_recruitment(self, rec: dict) -> None:
        family = rec.get("intent_family", "") or rec.get("impingement_source", "")
        score = rec.get("combined", 0.0) or rec.get("similarity", 0.3)
        domain = FAMILY_TO_DOMAIN.get(family)
        if domain is None:
            domain = hash(family) % 4
        fi = FAMILY_INDEX.get(family, hash(family) % 8)
        p0 = _pane_ordinal_depth0(domain)
        self._heat[p0] = min(1.0, self._heat[p0] + score * RECRUITMENT_BOOST)
        p1 = _pane_ordinal_depth1(domain, fi)
        if p1 < PANE_COUNT:
            self._heat[p1] = min(1.0, self._heat[p1] + score * RECRUITMENT_BOOST * 0.8)

    def tick(self) -> None:
        now = time.monotonic()
        dt = now - self._last_tick
        self._last_tick = now

        for imp in self._read_new_impingements():
            self.ingest_impingement(imp)
        for rec in self._read_new_recruitments():
            self.ingest_recruitment(rec)
        self.decay(dt)
        self._write_heatmap()

    def _read_new_impingements(self) -> list[dict]:
        if not IMPINGEMENT_PATH.exists():
            return []
        try:
            with open(IMPINGEMENT_PATH) as f:
                f.seek(self._cursor)
                lines = f.readlines()
                self._cursor = f.tell()
            imps = []
            for line in lines:
                line = line.strip()
                if line:
                    try:
                        imps.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
            return imps
        except OSError:
            return []

    def _read_new_recruitments(self) -> list[dict]:
        if not RECRUITMENT_PATH.exists():
            return []
        try:
            with open(RECRUITMENT_PATH) as f:
                f.seek(self._recruit_cursor)
                lines = f.readlines()
                self._recruit_cursor = f.tell()
            recs = []
            for line in lines:
                line = line.strip()
                if line:
                    try:
                        recs.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
            return recs
        except OSError:
            return []

    def _write_heatmap(self) -> None:
        data = bytearray(PANE_COUNT * 12)
        for i in range(PANE_COUNT):
            offset = i * 12
            struct.pack_into("<fff", data, offset, self._heat[i], self._hue[i] % 1.0, self._sat[i])
        tmp = HEATMAP_PATH.with_suffix(".tmp")
        try:
            tmp.write_bytes(bytes(data))
            tmp.rename(HEATMAP_PATH)
        except OSError:
            pass


def run_heatmap_loop() -> None:
    hm = AoaHeatmap()
    interval = 1.0 / TICK_HZ
    while True:
        try:
            hm.tick()
        except Exception:
            log.exception("heatmap tick failed")
        time.sleep(interval)
