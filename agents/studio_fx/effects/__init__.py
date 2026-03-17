"""Effect registry — imports all concrete effects."""

from agents.studio_fx.effects.ascii_art import AsciiEffect
from agents.studio_fx.effects.classify import ClassifyEffect
from agents.studio_fx.effects.clean import CleanEffect
from agents.studio_fx.effects.datamosh import DatamoshEffect
from agents.studio_fx.effects.diff import DiffEffect
from agents.studio_fx.effects.feedback import FeedbackEffect
from agents.studio_fx.effects.ghost import GhostEffect
from agents.studio_fx.effects.glitchblocks import GlitchblocksEffect
from agents.studio_fx.effects.halftone import HalftoneEffect
from agents.studio_fx.effects.neon import NeonEffect
from agents.studio_fx.effects.pixsort import PixsortEffect
from agents.studio_fx.effects.screwed import ScrewedEffect
from agents.studio_fx.effects.slitscan import SlitscanEffect
from agents.studio_fx.effects.thermal import ThermalEffect
from agents.studio_fx.effects.trap import TrapEffect
from agents.studio_fx.effects.vhs import VhsEffect

ALL_EFFECTS = [
    CleanEffect,
    GhostEffect,
    DatamoshEffect,
    VhsEffect,
    NeonEffect,
    ScrewedEffect,
    TrapEffect,
    DiffEffect,
    PixsortEffect,
    SlitscanEffect,
    ThermalEffect,
    FeedbackEffect,
    HalftoneEffect,
    GlitchblocksEffect,
    AsciiEffect,
    ClassifyEffect,
]

__all__ = [
    "ALL_EFFECTS",
    "AsciiEffect",
    "ClassifyEffect",
    "CleanEffect",
    "DatamoshEffect",
    "DiffEffect",
    "FeedbackEffect",
    "GhostEffect",
    "GlitchblocksEffect",
    "HalftoneEffect",
    "NeonEffect",
    "PixsortEffect",
    "ScrewedEffect",
    "SlitscanEffect",
    "ThermalEffect",
    "TrapEffect",
    "VhsEffect",
]
