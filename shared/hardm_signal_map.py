"""HARDM signal-to-cell mapping — 256 independent channels.

Phase 0 of the HARDM redesign. Maps every cell in the 16×16 grid to a
unique signal source, eliminating the row-duplication that left 240/256
cells carrying zero independent information.

Signal families:
- Row 0-3: Speech/voice (64 cells: VAD, RMS bands, pitch, formants)
- Row 4-5: Stimmung (32 cells: 11 dimensions + stance + components)
- Row 6-7: Audio health (32 cells: LUFS, crest, xrun, topology, correlation)
- Row 8-9: Perception (32 cells: presence, gaze, hand zone, IR signals)
- Row 10-11: Density field (32 cells: per-source density, temporal mode)
- Row 12-13: MIDI/music (32 cells: note velocity, CC values, BPM, onset)
- Row 14: Eigenform (16 cells: eigenform state vector components)
- Row 15: System (16 cells: GPU, CPU, memory, network, disk, docker)

Spec: docs/research/2026-04-19-hardm-redesign.md
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SignalFamily(StrEnum):
    SPEECH = "speech"
    STIMMUNG = "stimmung"
    AUDIO_HEALTH = "audio_health"
    PERCEPTION = "perception"
    DENSITY = "density"
    MIDI = "midi"
    EIGENFORM = "eigenform"
    SYSTEM = "system"


@dataclass(frozen=True)
class CellSignal:
    row: int
    col: int
    family: SignalFamily
    source_key: str
    label: str
    min_val: float = 0.0
    max_val: float = 1.0
    update_hz: float = 15.0

    @property
    def cell_index(self) -> int:
        return self.row * 16 + self.col


def _speech_cells() -> list[CellSignal]:
    cells = []
    for col in range(16):
        cells.append(
            CellSignal(
                0,
                col,
                SignalFamily.SPEECH,
                f"speech.rms_band_{col}",
                f"RMS band {col}",
                update_hz=30.0,
            )
        )
    for col in range(16):
        cells.append(
            CellSignal(
                1,
                col,
                SignalFamily.SPEECH,
                f"speech.pitch_bin_{col}",
                f"Pitch bin {col}",
                update_hz=15.0,
            )
        )
    for col in range(8):
        cells.append(
            CellSignal(
                2,
                col,
                SignalFamily.SPEECH,
                f"speech.formant_{col}",
                f"Formant F{col}",
                update_hz=15.0,
            )
        )
    cells.append(CellSignal(2, 8, SignalFamily.SPEECH, "speech.vad", "VAD active", update_hz=30.0))
    cells.append(
        CellSignal(2, 9, SignalFamily.SPEECH, "speech.energy", "Speech energy", update_hz=30.0)
    )
    cells.append(
        CellSignal(2, 10, SignalFamily.SPEECH, "speech.zcr", "Zero crossing rate", update_hz=15.0)
    )
    cells.append(
        CellSignal(
            2,
            11,
            SignalFamily.SPEECH,
            "speech.spectral_centroid",
            "Spectral centroid",
            update_hz=15.0,
        )
    )
    for col in range(12, 16):
        cells.append(
            CellSignal(
                2,
                col,
                SignalFamily.SPEECH,
                f"speech.mfcc_{col - 12}",
                f"MFCC {col - 12}",
                update_hz=15.0,
            )
        )
    for col in range(16):
        cells.append(
            CellSignal(
                3,
                col,
                SignalFamily.SPEECH,
                f"speech.mel_band_{col}",
                f"Mel band {col}",
                update_hz=30.0,
            )
        )
    return cells


def _stimmung_cells() -> list[CellSignal]:
    dims = [
        "cognitive_load",
        "emotional_valence",
        "social_engagement",
        "creative_flow",
        "physical_arousal",
        "environmental_comfort",
        "temporal_pressure",
        "information_novelty",
        "aesthetic_resonance",
        "operator_stress",
        "production_momentum",
    ]
    cells = []
    for i, dim in enumerate(dims):
        cells.append(CellSignal(4, i, SignalFamily.STIMMUNG, f"stimmung.{dim}", dim, update_hz=2.0))
    cells.append(
        CellSignal(4, 11, SignalFamily.STIMMUNG, "stimmung.stance", "Stance", update_hz=2.0)
    )
    for col in range(12, 16):
        cells.append(
            CellSignal(
                4,
                col,
                SignalFamily.STIMMUNG,
                f"stimmung.component_{col - 12}",
                f"Component {col - 12}",
                update_hz=2.0,
            )
        )
    for col in range(16):
        cells.append(
            CellSignal(
                5,
                col,
                SignalFamily.STIMMUNG,
                f"stimmung.history_{col}",
                f"History {col}",
                update_hz=0.5,
            )
        )
    return cells


def _audio_health_cells() -> list[CellSignal]:
    cells = []
    monitors = [
        "lufs_s",
        "lufs_i",
        "crest_factor",
        "zcr",
        "spectral_flatness",
        "xrun_count",
        "buffer_underrun",
        "topology_drift",
        "channel_position",
        "l12_usb_continuity",
        "inter_stage_corr",
        "ducker_readback",
        "broadcast_safe",
        "stale_witness",
        "loudness_gate",
        "headroom_db",
    ]
    for i, m in enumerate(monitors):
        cells.append(CellSignal(6, i, SignalFamily.AUDIO_HEALTH, f"audio.{m}", m, update_hz=2.0))
    for col in range(16):
        cells.append(
            CellSignal(
                7,
                col,
                SignalFamily.AUDIO_HEALTH,
                f"audio.per_channel_{col}",
                f"Channel {col}",
                update_hz=2.0,
            )
        )
    return cells


def _perception_cells() -> list[CellSignal]:
    signals = [
        "presence_probability",
        "gaze_direction",
        "ir_hand_zone",
        "ir_hand_activity",
        "face_detected",
        "body_posture",
        "desk_activity",
        "keyboard_active",
        "mouse_active",
        "phone_ble_rssi",
        "kde_connect",
        "heart_rate_bpm",
        "hrv_rmssd",
        "skin_temp",
        "flow_score",
        "production_activity",
    ]
    cells = []
    for i, s in enumerate(signals):
        cells.append(CellSignal(8, i, SignalFamily.PERCEPTION, f"perception.{s}", s, update_hz=3.0))
    ir_cams = ["desk", "room", "overhead", "sentinel", "rag_edge", "sync"]
    for i, cam in enumerate(ir_cams):
        cells.append(
            CellSignal(
                9, i, SignalFamily.PERCEPTION, f"ir.{cam}.person", f"IR {cam} person", update_hz=3.0
            )
        )
        if i < 5:
            cells.append(
                CellSignal(
                    9,
                    6 + i,
                    SignalFamily.PERCEPTION,
                    f"ir.{cam}.confidence",
                    f"IR {cam} conf",
                    update_hz=3.0,
                )
            )
    cells.append(
        CellSignal(
            9, 11, SignalFamily.PERCEPTION, "camera.active_count", "Active cameras", update_hz=1.0
        )
    )
    for col in range(12, 16):
        cells.append(
            CellSignal(
                9,
                col,
                SignalFamily.PERCEPTION,
                f"perception.spare_{col}",
                f"Spare {col}",
                update_hz=1.0,
            )
        )
    return cells


def _density_cells() -> list[CellSignal]:
    cells = []
    sources = [
        "microphone",
        "keyboard",
        "mouse",
        "camera_desk",
        "camera_room",
        "camera_overhead",
        "heart_rate",
        "stimmung",
        "programme",
        "impingement",
        "chat",
        "vinyl",
        "midi",
        "imagination",
        "exploration",
        "affordance",
    ]
    for i, s in enumerate(sources):
        cells.append(CellSignal(10, i, SignalFamily.DENSITY, f"density.{s}", s, update_hz=2.0))
    cells.append(
        CellSignal(11, 0, SignalFamily.DENSITY, "density.aggregate", "Aggregate", update_hz=2.0)
    )
    cells.append(
        CellSignal(
            11, 1, SignalFamily.DENSITY, "density.temporal_mode", "Temporal mode", update_hz=2.0
        )
    )
    cells.append(CellSignal(11, 2, SignalFamily.DENSITY, "density.trend", "Trend", update_hz=2.0))
    for col in range(3, 16):
        cells.append(
            CellSignal(
                11,
                col,
                SignalFamily.DENSITY,
                f"density.history_{col}",
                f"History {col}",
                update_hz=0.5,
            )
        )
    return cells


def _midi_cells() -> list[CellSignal]:
    cells = []
    for col in range(12):
        cells.append(
            CellSignal(
                12,
                col,
                SignalFamily.MIDI,
                f"midi.pitch_class_{col}",
                f"Note {['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'][col]}",
                update_hz=30.0,
            )
        )
    cells.append(CellSignal(12, 12, SignalFamily.MIDI, "midi.velocity", "Velocity", update_hz=30.0))
    cells.append(CellSignal(12, 13, SignalFamily.MIDI, "midi.bpm", "BPM", update_hz=5.0))
    cells.append(CellSignal(12, 14, SignalFamily.MIDI, "midi.onset", "Onset", update_hz=30.0))
    cells.append(CellSignal(12, 15, SignalFamily.MIDI, "midi.sustain", "Sustain", update_hz=15.0))
    for col in range(16):
        cells.append(
            CellSignal(13, col, SignalFamily.MIDI, f"midi.cc_{col}", f"CC {col}", update_hz=15.0)
        )
    return cells


def _eigenform_cells() -> list[CellSignal]:
    components = [
        "presence",
        "flow_score",
        "audio_energy",
        "stimmung_stance",
        "imagination_salience",
        "visual_brightness",
        "heart_rate",
        "operator_stress",
        "activity",
        "e_mesh",
        "restriction_rms",
        "gqi",
        "exploration_score",
        "boredom",
        "curiosity",
        "fatigue",
    ]
    return [
        CellSignal(14, i, SignalFamily.EIGENFORM, f"eigenform.{c}", c, update_hz=2.0)
        for i, c in enumerate(components)
    ]


def _system_cells() -> list[CellSignal]:
    signals = [
        "gpu_util",
        "gpu_vram_pct",
        "gpu_temp",
        "gpu_power",
        "cpu_load_1m",
        "cpu_load_5m",
        "mem_used_pct",
        "memory_psi_some_avg10",
        "disk_root_pct",
        "disk_data_pct",
        "docker_running",
        "systemd_failed",
        "network_rx_mbps",
        "network_tx_mbps",
        "qdrant_health",
        "litellm_health",
    ]
    return [
        CellSignal(15, i, SignalFamily.SYSTEM, f"system.{s}", s, update_hz=1.0)
        for i, s in enumerate(signals)
    ]


def build_signal_map() -> list[CellSignal]:
    """Build the complete 256-cell signal map."""
    cells = (
        _speech_cells()
        + _stimmung_cells()
        + _audio_health_cells()
        + _perception_cells()
        + _density_cells()
        + _midi_cells()
        + _eigenform_cells()
        + _system_cells()
    )
    assert len(cells) == 256, f"Expected 256 cells, got {len(cells)}"
    return cells


SIGNAL_MAP: list[CellSignal] = build_signal_map()
SIGNAL_BY_KEY: dict[str, CellSignal] = {c.source_key: c for c in SIGNAL_MAP}
SIGNAL_BY_INDEX: dict[int, CellSignal] = {c.cell_index: c for c in SIGNAL_MAP}
