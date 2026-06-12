"""Fortress narrative generation — DF chronicler style.

Generates 1-3 sentence narratives from fortress episodes.
LLM integration point — uses shared config for model routing.
"""

from __future__ import annotations

import json
import logging
import time

from agents._config import PROFILES_DIR
from agents.fortress.episodes import FortressEpisode
from agents.fortress.schema import FastFortressState

log = logging.getLogger(__name__)

CHRONICLE_PATH = PROFILES_DIR / "fortress-chronicle.jsonl"

STORYTELLER_SYSTEM = (
    "You are a dwarf fortress chronicler. Write 1-3 sentences describing what happened"
    " during this episode. Use a factual, slightly wry tone matching Dwarf Fortress's"
    " generated prose style. Do not mention AI, governance chains, or system internals."
    " Focus on what happened to the dwarves and the fortress."
)


def build_narrative_prompt(episode: FortressEpisode, state: FastFortressState) -> str:
    """Build the LLM prompt for narrative generation."""
    season_names = {0: "Early Spring", 1: "Mid Summer", 2: "Late Autumn", 3: "Deep Winter"}
    season_name = season_names.get(episode.season, f"Season {episode.season}")

    parts = [
        f"Fortress: {episode.fortress_name}",
        f"Time: {season_name}, Year {episode.year}",
        f"Trigger: {episode.trigger}",
        f"Population: {episode.population_start} → {episode.population_end}"
        f" ({episode.population_delta:+d})",
        f"Food: {episode.food_start} → {episode.food_end} ({episode.food_delta:+d})",
    ]

    if episode.events:
        parts.append("Events:")
        for event in episode.events[:5]:  # cap at 5 for token budget
            if hasattr(event, "type"):
                parts.append(f"  - {event.type}: {event.model_dump_json()}")

    return "\n".join(parts)


def format_narrative_fallback(episode: FortressEpisode) -> str:
    """Generate a simple narrative without LLM (fallback)."""
    season_names = {0: "Spring", 1: "Summer", 2: "Autumn", 3: "Winter"}
    season = season_names.get(episode.season, "")

    trigger_text = {
        "season_change": f"{season} has arrived in Year {episode.year}.",
        "siege": "A siege has begun!",
        "migrant": f"A migrant wave of {abs(episode.population_delta)} has arrived.",
        "death": "A citizen has perished.",
        "mood": "A dwarf has been taken by a mood.",
        "start": "The fortress has been founded.",
        "flush": "The chronicle pauses here.",
        "population_shift": f"The population has shifted by {episode.population_delta:+d}.",
    }.get(episode.trigger, f"Event: {episode.trigger}.")

    pop_text = f"Population: {episode.population_end}."
    food_text = f"Food stores: {episode.food_end}." if episode.food_delta != 0 else ""

    return " ".join(filter(None, [trigger_text, pop_text, food_text]))


def write_chronicle_entry(episode: FortressEpisode) -> None:
    """Append episode to the fortress chronicle JSONL."""
    entry = {
        "session_id": episode.session_id,
        "fortress_name": episode.fortress_name,
        "game_tick": episode.game_tick_end,
        "year": episode.year,
        "season": episode.season,
        "trigger": episode.trigger,
        "narrative": episode.narrative,
        "population": episode.population_end,
        "food": episode.food_end,
        "population_delta": episode.population_delta,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    CHRONICLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    # jsonl-rotation: exempt(registry candidate — consumer shrink-audit pending, see audit-w0 follow-up)
    with CHRONICLE_PATH.open("a") as f:
        f.write(json.dumps(entry) + "\n")
