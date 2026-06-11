"""Torso S-4 scene library.

Scenes are recalled by MIDI Program Change. The S-4's live PC behavior is
zero-based: program N recalls slot N+1. The device is write-only, so every
successful recall must be followed by the empirical post-recall gain ladder
from ``config/equipment/s4-gain-ladder-20260610.yaml``.

The prior per-scene CC dictionaries were derived from falsified charts. They
remain empty until a bench sweep validates expressive CCs against the live
analog insert.
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
class S4CcCommand:
    """One S-4 CC command.

    ``channel`` is the zero-indexed mido channel. For example, hardware MIDI
    channel 16 is ``channel=15``.
    """

    channel: int
    cc: int
    value: int
    note: str = ""


# Empirical S-4 gain ladder discovered closed-loop on 2026-06-10.
# Source of truth: config/equipment/s4-gain-ladder-20260610.yaml.
EMPIRICAL_S4_GAIN_LADDER: Final[tuple[S4CcCommand, ...]] = (
    S4CcCommand(channel=15, cc=48, value=127, note="ch16 CC48 empirical +11.3 dB"),
    S4CcCommand(channel=15, cc=49, value=127, note="ch16 CC49 empirical +3.3 dB"),
    S4CcCommand(channel=15, cc=58, value=127, note="ch16 CC58 empirical +13.1 dB"),
    S4CcCommand(channel=1, cc=46, value=127, note="ch2 CC46 empirical +15.7 dB"),
    S4CcCommand(channel=1, cc=47, value=127, note="ch2 CC47 empirical +7.9 dB"),
)


@dataclass(frozen=True)
class S4Scene:
    """A named S-4 track configuration.

    ``program_number`` is the zero-based MIDI Program Change value, not the
    front-panel slot number. Program 0 recalls slot 1.

    ``ccs`` is intentionally empty until new expressive S-4 controls are
    measured. ``post_recall_ccs`` carries the empirical gain ladder that must
    be reasserted after every scene recall because S-4 recalls wipe runtime
    CC state and the device has no MIDI save/readback path.
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
    post_recall_ccs: tuple[S4CcCommand, ...] = EMPIRICAL_S4_GAIN_LADDER


SCENES: Final[dict[str, S4Scene]] = {
    "VOCAL-COMPANION": S4Scene(
        name="VOCAL-COMPANION",
        description=(
            "Subtle voice complement to Evil Pet T2 default. Ring "
            "resonant around 2 kHz, light Deform drive, bright Vast "
            "reverb. Pairs with hapax-broadcast-ghost for UC1."
        ),
        program_number=0,
        material="Bypass",
        granular="None",
        filter="Ring",
        color="Deform",
        space="Vast",
    ),
    "VOCAL-MOSAIC": S4Scene(
        name="VOCAL-MOSAIC",
        description=(
            "Textural voice for SEEKING stance. Mosaic granular at "
            "70% density with positional drift; Ring resonant at Q "
            "0.7; darker Vast. Pairs with hapax-underwater or "
            "hapax-granular-wash for UC3 cross-character swap."
        ),
        program_number=1,
        material="Bypass",
        granular="Mosaic",
        filter="Ring",
        color="Deform",
        space="Vast",
    ),
    "MUSIC-BED": S4Scene(
        name="MUSIC-BED",
        description=(
            "Low-impact music processing for UC2 default livestream. "
            "Peak filter gently brightens, Deform adds warmth, Vast "
            "provides neutral room. Pairs with hapax-bed-music."
        ),
        program_number=2,
        material="Bypass",
        granular="None",
        filter="Peak",
        color="Deform",
        space="Vast",
    ),
    "MUSIC-DRONE": S4Scene(
        name="MUSIC-DRONE",
        description=(
            "Sustained granular music texture for ambient interludes. "
            "Mosaic at 40% density with longer grains; Peak filter; "
            "long dark Vast. Pairs with hapax-drone-loop."
        ),
        program_number=3,
        material="Bypass",
        granular="Mosaic",
        filter="Peak",
        color="Deform",
        space="Vast",
    ),
    "MEMORY-COMPANION": S4Scene(
        name="MEMORY-COMPANION",
        description=(
            "Paired with Evil Pet T3 MEMORY. Peak filter narrow at "
            "1.2 kHz, vintage tape Deform, medium-tail dark Vast. "
            "UC9 impingement-driven tier-3 transitions."
        ),
        program_number=4,
        material="Bypass",
        granular="None",
        filter="Peak",
        color="Deform",
        space="Vast",
    ),
    "UNDERWATER-COMPANION": S4Scene(
        name="UNDERWATER-COMPANION",
        description=(
            "Paired with Evil Pet T4 UNDERWATER. LPF Ring at 800 Hz, "
            "soft Deform, long muffled Vast. Voice sounds submerged "
            "but intelligibility preserved per §9 governance."
        ),
        program_number=5,
        material="Bypass",
        granular="None",
        filter="Ring",
        color="Deform",
        space="Vast",
    ),
    "SONIC-RITUAL": S4Scene(
        name="SONIC-RITUAL",
        description=(
            "Dual-granular with Evil Pet T5 for UC10 programme-gated. "
            "REQUIRES dual_granular_simultaneous opt-in per §9.6. "
            "Mosaic 90% density, resonant Ring 60%, heavy bit-crush, "
            "huge 60% tail Vast. Monetization risk; WARD-gated."
        ),
        program_number=6,
        material="Bypass",
        granular="Mosaic",
        filter="Ring",
        color="Deform",
        space="Vast",
    ),
    "BEAT-1": S4Scene(
        name="BEAT-1",
        description=(
            "Sample-based percussion sequencer. Material=Tape with "
            "kick/snare/hi-hat samples, HPF 150 Hz to cut rumble, "
            "light Deform drive. Pairs with UC5 live performance "
            "(Evil Pet on vinyl, TTS clean)."
        ),
        program_number=7,
        material="Tape",
        granular="None",
        filter="Peak",
        color="Deform",
        space="None",
    ),
    "RECORD-DRY": S4Scene(
        name="RECORD-DRY",
        description=(
            "Record-only passthrough for UC6 research capture. "
            "Material=Tape in record mode captures clean stems to "
            "hapax-research/stems while Evil Pet applies broadcast "
            "character. No FX on the recording."
        ),
        program_number=8,
        material="Tape",
        granular="None",
        filter="None",
        color="None",
        space="None",
    ),
    "VOICE-SELF-MOD": S4Scene(
        name="VOICE-SELF-MOD",
        description=(
            "Non-anthropomorphic voice self-modulation for interview segments. "
            "Mosaic 35% wet for grain texture, Ring 40% for resonant "
            "formant shifting, Deform 30% for timbral density, small-room "
            "Vast. Chatterbox output as raw material; S-4 transforms it "
            "into Hapax's own voice. Importance drives processing "
            "REDUCTION (more important = less processing). "
            "Intelligibility floor: processing never obscures speech content."
        ),
        program_number=11,
        material="Bypass",
        granular="Mosaic",
        filter="Ring",
        color="Deform",
        space="Vast",
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


def get_post_recall_ccs(name: str) -> tuple[S4CcCommand, ...]:
    """Return the CC commands to reassert after a successful scene recall."""
    return get_scene(name).post_recall_ccs
