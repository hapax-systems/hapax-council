"""Torso S-4 scene library (Phase B4 of evilpet-s4-dynamic-dual-processor-plan).

10 scenes, each a 5-slot configuration (Material / Granular / Filter /
Color / Space) with per-slot CC overrides. Paired with Evil Pet presets
via ``shared.evil_pet_presets.DEFAULT_PAIRINGS``.

Scene recall mechanism: MIDI program change (primary, <= 50 ms) OR
per-slot CC bursts (fallback, <= 200 ms). Sent via
``shared.s4_midi.emit_program_change`` / ``emit_cc`` when the S-4 is
USB-connected.

The scene CC values here are delta's initial draft per spec §4.2.
Operator ratifies aesthetic tuning in PR review; the spec explicitly
treats CC values as operator-aesthetic-authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

# S-4 slot device vocabulary (per manual).
Material = str  # one of: "Bypass", "Tape", "Poly"
GranularDev = str  # one of: "Mosaic", "None"
FilterDev = str  # one of: "Ring", "Peak", "None"
ColorDev = str  # one of: "Deform", "Mute", "None"
SpaceDev = str  # one of: "Vast", "None"


@dataclass(frozen=True)
class S4Scene:
    """A named S-4 track configuration.

    ``program_number`` corresponds to the S-4 patch slot index the
    scene is persisted into (operator writes this via the S-4 front
    panel after ratifying CC values). Used for ``emit_program_change``.

    ``ccs`` carries per-device CC overrides (CC number to value).
    Complete reference of S-4 CCs is in the Torso S-4 manual §CC map;
    values here follow the research doc §5 enhancement-family specs.
    """

    name: str
    description: str
    program_number: int
    material: Material
    granular: GranularDev
    filter: FilterDev
    color: ColorDev
    space: SpaceDev
    ccs: dict[int, int] = field(default_factory=dict)


SCENES: Final[dict[str, S4Scene]] = {
    "VOCAL-COMPANION": S4Scene(
        name="VOCAL-COMPANION",
        description=(
            "Subtle voice complement to Evil Pet T2 default. Ring "
            "resonant around 2 kHz, light Deform drive, bright Vast "
            "reverb. Pairs with hapax-broadcast-ghost for UC1."
        ),
        program_number=1,
        material="Bypass",
        granular="None",
        filter="Ring",
        color="Deform",
        space="Vast",
        ccs={
            # Filter (Ring): freq 2 kHz, Q 0.4, wet 35%
            79: 90,
            80: 50,
            81: 45,
            # Color (Deform): drive 20, compression 40
            95: 25,
            96: 50,
            # Space (Vast): size 30, tone bright, wet 40%
            112: 38,
            113: 85,
            114: 50,
        },
    ),
    "VOCAL-MOSAIC": S4Scene(
        name="VOCAL-MOSAIC",
        description=(
            "Textural voice for SEEKING stance. Mosaic granular at "
            "70% density with positional drift; Ring resonant at Q "
            "0.7; darker Vast. Pairs with hapax-underwater or "
            "hapax-granular-wash for UC3 cross-character swap."
        ),
        program_number=2,
        material="Bypass",
        granular="Mosaic",
        filter="Ring",
        color="Deform",
        space="Vast",
        ccs={
            # Granular (Mosaic): density 70, position drift 30, length 150 ms
            47: 90,
            48: 38,
            49: 65,
            # Filter (Ring): Q 0.7, wet 50%
            80: 90,
            81: 65,
            # Color (Deform): drive 15
            95: 20,
            # Space (Vast): tail 60%, dark tone
            114: 75,
            115: 40,
            116: 50,
        },
    ),
    "MUSIC-BED": S4Scene(
        name="MUSIC-BED",
        description=(
            "Low-impact music processing for UC2 default livestream. "
            "Peak filter gently brightens, Deform adds warmth, Vast "
            "provides neutral room. Pairs with hapax-bed-music."
        ),
        program_number=3,
        material="Bypass",
        granular="None",
        filter="Peak",
        color="Deform",
        space="Vast",
        ccs={
            # Filter (Peak): freq 1 kHz, Q 0.3, wet 20%
            79: 80,
            80: 40,
            81: 25,
            # Color (Deform): drive 10
            95: 12,
            # Space (Vast): wet 30%, neutral tone
            112: 40,
            113: 64,
            114: 38,
        },
    ),
    "MUSIC-DRONE": S4Scene(
        name="MUSIC-DRONE",
        description=(
            "Sustained granular music texture for ambient interludes. "
            "Mosaic at 40% density with longer grains; Peak filter; "
            "long dark Vast. Pairs with hapax-drone-loop."
        ),
        program_number=4,
        material="Bypass",
        granular="Mosaic",
        filter="Peak",
        color="Deform",
        space="Vast",
        ccs={
            # Granular (Mosaic): density 40, length 200 ms, rate drift
            47: 50,
            49: 100,
            50: 30,
            # Filter (Peak): wet 35%
            81: 45,
            # Color (Deform): drive 20
            95: 25,
            # Space (Vast): tail 70%, dark tone
            114: 90,
            115: 30,
            116: 50,
        },
    ),
    "MEMORY-COMPANION": S4Scene(
        name="MEMORY-COMPANION",
        description=(
            "Paired with Evil Pet T3 MEMORY. Peak filter narrow at "
            "1.2 kHz, vintage tape Deform, medium-tail dark Vast. "
            "UC9 impingement-driven tier-3 transitions."
        ),
        program_number=5,
        material="Bypass",
        granular="None",
        filter="Peak",
        color="Deform",
        space="Vast",
        ccs={
            # Filter (Peak): freq 1.2 kHz, Q 2.0, wet 30%
            79: 82,
            80: 100,
            81: 38,
            # Color (Deform): vintage tape saturation
            95: 35,
            96: 55,
            97: 70,
            # Space (Vast): medium tail, dark tone
            114: 55,
            115: 35,
        },
    ),
    "UNDERWATER-COMPANION": S4Scene(
        name="UNDERWATER-COMPANION",
        description=(
            "Paired with Evil Pet T4 UNDERWATER. LPF Ring at 800 Hz, "
            "soft Deform, long muffled Vast. Voice sounds submerged "
            "but intelligibility preserved per §9 governance."
        ),
        program_number=6,
        material="Bypass",
        granular="None",
        filter="Ring",
        color="Deform",
        space="Vast",
        ccs={
            # Filter (Ring, LPF mode): freq 800 Hz, Q 0.5, wet 70%
            79: 40,
            80: 60,
            81: 90,
            # Color (Deform): soft drive
            95: 15,
            # Space (Vast): long tail, muffled tone
            114: 80,
            115: 25,
        },
    ),
    "SONIC-RITUAL": S4Scene(
        name="SONIC-RITUAL",
        description=(
            "Dual-granular with Evil Pet T5 for UC10 programme-gated. "
            "REQUIRES dual_granular_simultaneous opt-in per §9.6. "
            "Mosaic 90% density, resonant Ring 60%, heavy bit-crush, "
            "huge 60% tail Vast. Monetization risk; WARD-gated."
        ),
        program_number=7,
        material="Bypass",
        granular="Mosaic",
        filter="Ring",
        color="Deform",
        space="Vast",
        ccs={
            # Granular (Mosaic): density 90, rate drift, length vary
            47: 115,
            49: 120,
            50: 60,
            # Filter (Ring): resonance 60%, wet 70%
            80: 75,
            81: 90,
            # Color (Deform): heavy bit-crush (governance-gated)
            95: 90,
            96: 100,
            97: 110,
            # Space (Vast): huge room, 60% tail
            112: 120,
            114: 75,
        },
    ),
    "BEAT-1": S4Scene(
        name="BEAT-1",
        description=(
            "Sample-based percussion sequencer. Material=Tape with "
            "kick/snare/hi-hat samples, HPF 150 Hz to cut rumble, "
            "light Deform drive. Pairs with UC5 live performance "
            "(Evil Pet on vinyl, TTS clean)."
        ),
        program_number=8,
        material="Tape",
        granular="None",
        filter="Peak",
        color="Deform",
        space="None",
        ccs={
            # Material (Tape): sampler params — operator programs on device
            # Filter (Peak, HPF): freq 150 Hz, wet 100%
            79: 18,
            81: 127,
            # Color (Deform): light drive
            95: 10,
        },
    ),
    "RECORD-DRY": S4Scene(
        name="RECORD-DRY",
        description=(
            "Record-only passthrough for UC6 research capture. "
            "Material=Tape in record mode captures clean stems to "
            "hapax-research/stems while Evil Pet applies broadcast "
            "character. No FX on the recording."
        ),
        program_number=9,
        material="Tape",
        granular="None",
        filter="None",
        color="None",
        space="None",
        ccs={
            # Material (Tape): record-enabled; other slots off
            73: 127,
        },
    ),
    "BYPASS": S4Scene(
        name="BYPASS",
        description=(
            "All slots off. UC7 emergency clean fallback. Always "
            "available, always allowed, never governance-gated. "
            "Recall via ``hapax-audio-reset-dry``."
        ),
        program_number=10,
        material="Bypass",
        granular="None",
        filter="None",
        color="None",
        space="None",
        ccs={},
    ),
    "VOICE-SELF-MOD": S4Scene(
        name="VOICE-SELF-MOD",
        description=(
            "Non-human intelligible voice via Mosaic granular + Ring filter. "
            "Self-modulation target: CC 69 (Mosaic wet) driven by information "
            "density. Baseline: 35% granular, 40% filter, 30% color. "
            "Intelligibility floor: 0.85. Importance drives processing "
            "REDUCTION — critical speech gets cleaner, ambient gets textural."
        ),
        program_number=11,
        material="Bypass",
        granular="Mosaic",
        filter="Ring",
        color="Deform",
        space="Vast",
        ccs={
            62: 58,  # Pitch: -2 semitones
            63: 50,  # Rate: moderate grain spawn
            64: 60,  # Size: ~30ms (phoneme-preserving)
            65: 64,  # Contour: neutral envelope
            67: 20,  # Spray: light positional randomization
            69: 45,  # Mosaic wet: 35%
            78: 90,  # Ring cutoff: ~2.2 kHz
            79: 40,  # Resonance: gentle metallic peak
            80: 25,  # Decay: short ring
            85: 50,  # Ring wet: 40%
            94: 20,  # Drive: subtle harmonic generation
            95: 50,  # Compress: moderate (flattens prosodic dynamics)
            96: 15,  # Crush: light bit-reduction
            101: 38,  # Deform wet: 30%
            112: 30,  # Reverb: moderate
            113: 25,  # Size: small room (mechanism interior)
            116: 40,  # Tone: dark
            117: 30,  # Decay: short tail
        },
    ),
}


def list_scenes() -> list[str]:
    """Return the list of scene names in registry order."""
    return list(SCENES.keys())


def get_scene(name: str) -> S4Scene:
    """Return the scene by name or raise KeyError.

    Called by the dynamic router (Phase B3) when emitting scene
    recalls via S-4 MIDI. The caller should handle KeyError as a
    programmer error (misspelled scene name) rather than user input.
    """
    try:
        return SCENES[name]
    except KeyError as exc:
        raise KeyError(f"unknown S-4 scene '{name}'; available: {', '.join(SCENES)}") from exc


def get_program_number(name: str) -> int:
    """Return the program number for a scene name."""
    return get_scene(name).program_number
