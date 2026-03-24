"""Structured game state models for Dwarf Fortress governance.

All models are frozen Pydantic v2 BaseModels representing the fortress state
consumed by governance chains. FastFortressState provides high-frequency polling
data; FullFortressState extends it with complete details emitted once per season.
FortressPosition maps game ticks to a temporal hierarchy analogous to
MusicalPosition in the studio domain.

See: agents/fortress/chains/ for governance chain consumers.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Discriminator, Tag

# ---------------------------------------------------------------------------
# Base types
# ---------------------------------------------------------------------------


class DwarfSkill(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    level: int  # 0-20 (Dabbling to Legendary+5)


class DwarfUnit(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    name: str
    profession: str
    skills: tuple[DwarfSkill, ...]
    stress: int  # higher = worse, 0 = ecstatic, >100000 = miserable
    mood: str  # "normal", "fey", "secretive", "possessed", "berserk", "insane", "melancholy"
    current_job: str
    military_squad_id: int | None = None


class MilitarySquad(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    name: str
    member_ids: tuple[int, ...]
    equipment_quality: float  # 0.0-1.0
    training_level: float  # 0.0-1.0


class StockpileSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    food: int = 0
    drink: int = 0
    wood: int = 0
    stone: int = 0
    metal_bars: int = 0
    cloth: int = 0
    thread: int = 0
    weapons: int = 0
    armor: int = 0
    ammo: int = 0
    mechanisms: int = 0
    seeds: int = 0
    gems: int = 0
    leather: int = 0
    bones: int = 0
    shells: int = 0
    crafts: int = 0
    furniture: int = 0


class Workshop(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: str
    x: int
    y: int
    z: int
    is_active: bool
    current_job: str


class BuildingSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    doors: int = 0
    beds: int = 0
    tables: int = 0
    chairs: int = 0
    statues: int = 0
    armor_stands: int = 0
    weapon_racks: int = 0
    coffins: int = 0
    trade_depot: int = 0


class WealthSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    created: int = 0
    exported: int = 0
    imported: int = 0


class MapSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    z_levels_explored: int = 0
    cavern_layers_breached: int = 0  # 0-3
    has_magma_access: bool = False
    has_water_source: bool = False
    aquifer_present: bool = False


class NoblePosition(BaseModel):
    model_config = ConfigDict(frozen=True)

    position: str
    holder_id: int | None = None
    demands: tuple[str, ...] = ()


class StrangeMood(BaseModel):
    model_config = ConfigDict(frozen=True)

    unit_id: int
    mood_type: str
    claimed_workshop: str | None = None
    materials_needed: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Event types (discriminated union)
# ---------------------------------------------------------------------------


class SiegeEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["siege"] = "siege"
    attacker_civ: str
    force_size: int


class MigrantEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["migrant"] = "migrant"
    count: int


class DeathEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["death"] = "death"
    unit_id: int
    unit_name: str
    cause: str


class MoodEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["mood"] = "mood"
    unit_id: int
    mood_type: str


class CaravanEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["caravan"] = "caravan"
    civ: str
    goods_value: int


class SeasonChangeEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["season_change"] = "season_change"
    new_season: int  # 0-3
    new_year: int


class CaveInEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["cave_in"] = "cave_in"
    z_level: int


class MandateEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["mandate"] = "mandate"
    noble: str
    item_type: str
    quantity: int


class MegabeastEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["megabeast"] = "megabeast"
    creature_type: str


FortressEvent = Annotated[
    Annotated[SiegeEvent, Tag("siege")]
    | Annotated[MigrantEvent, Tag("migrant")]
    | Annotated[DeathEvent, Tag("death")]
    | Annotated[MoodEvent, Tag("mood")]
    | Annotated[CaravanEvent, Tag("caravan")]
    | Annotated[SeasonChangeEvent, Tag("season_change")]
    | Annotated[CaveInEvent, Tag("cave_in")]
    | Annotated[MandateEvent, Tag("mandate")]
    | Annotated[MegabeastEvent, Tag("megabeast")],
    Discriminator("type"),
]


# ---------------------------------------------------------------------------
# Spatial types
# ---------------------------------------------------------------------------


class Building(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    type: str  # building type name
    x1: int
    y1: int
    x2: int
    y2: int
    z: int
    is_room: bool = False
    room_description: str = ""
    name: str = ""


class ActivityZone(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    type: str  # temple, library, tavern, guildhall, etc.
    x1: int
    y1: int
    x2: int
    y2: int
    z: int
    name: str = ""


# ---------------------------------------------------------------------------
# State models
# ---------------------------------------------------------------------------


class FastFortressState(BaseModel):
    model_config = ConfigDict(frozen=True)

    timestamp: float
    game_tick: int
    year: int
    season: int  # 0-3
    month: int  # 0-11
    day: int  # 0-27
    fortress_name: str
    paused: bool
    population: int
    food_count: int
    drink_count: int
    active_threats: int
    job_queue_length: int
    idle_dwarf_count: int
    most_stressed_value: int
    pending_events: tuple[FortressEvent, ...] = ()


class FullFortressState(FastFortressState):
    """Extended state with full details, emitted once per season."""

    units: tuple[DwarfUnit, ...] = ()
    squads: tuple[MilitarySquad, ...] = ()
    stockpiles: StockpileSummary = StockpileSummary()
    workshops: tuple[Workshop, ...] = ()
    buildings: BuildingSummary = BuildingSummary()
    buildings_list: tuple[Building, ...] = ()
    zones: tuple[ActivityZone, ...] = ()
    wealth: WealthSummary = WealthSummary()
    map_summary: MapSummary = MapSummary()
    nobles: tuple[NoblePosition, ...] = ()
    strange_moods: tuple[StrangeMood, ...] = ()


# ---------------------------------------------------------------------------
# Temporal position
# ---------------------------------------------------------------------------


class FortressPosition(BaseModel):
    """Temporal hierarchy for fortress governance decisions.

    Maps game ticks to day/month/season/year/era, analogous to
    MusicalPosition (beat/bar/phrase/section) in the studio domain.
    """

    model_config = ConfigDict(frozen=True)

    tick: int
    day: int  # 0-27
    month: int  # 0-11
    season: int  # 0-3
    year: int
    era: str  # founding/growth/establishment/prosperity/legendary

    @classmethod
    def from_tick(cls, tick: int, population: int = 0) -> FortressPosition:
        """Derive all temporal fields from game tick + population."""
        TICKS_PER_DAY = 1200
        DAYS_PER_MONTH = 28
        MONTHS_PER_YEAR = 12
        ticks_per_month = TICKS_PER_DAY * DAYS_PER_MONTH
        ticks_per_year = ticks_per_month * MONTHS_PER_YEAR

        year = tick // ticks_per_year
        remainder = tick % ticks_per_year
        month = remainder // ticks_per_month
        day_remainder = remainder % ticks_per_month
        day = day_remainder // TICKS_PER_DAY
        season = month // 3

        if population < 20:
            era = "founding"
        elif population < 50:
            era = "growth"
        elif population < 100:
            era = "establishment"
        elif population < 150:
            era = "prosperity"
        else:
            era = "legendary"

        return cls(tick=tick, day=day, month=month, season=season, year=year, era=era)
