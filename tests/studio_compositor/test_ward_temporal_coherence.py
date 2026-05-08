"""Ward temporal coherence tests (ARI L4 — common fate).

Sources sharing a functional tag group must share the same update rate
so they form a perceptual unit. Tags that are super-categories (homage,
ward, instrument) are exempt — they span multiple temporal bands by
design.

Rate bands documented for L5 (Pragnanz range):
  0.5 Hz — slow lore/research (lore-ext, research-poster)
  1.0 Hz — governance/programme (egress, programme, segment)
  2.0 Hz — operational (legibility, hothouse, authorship, chat, pressure, audience)
  6.0 Hz — animated expression (durf, reveal, displacement)
 15.0 Hz — fast instrument (oscilloscope)
 24.0 Hz — substrate animation (gem expression)
 always  — frame-rate bound (raw video/shader surfaces)
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

LAYOUT_PATH = Path(__file__).resolve().parents[2] / "config" / "compositor-layouts" / "default.json"

TEMPORAL_GROUP_TAGS = {
    "authorship",
    "pressure",
    "audience",
    "legibility",
    "governance",
    "programme",
    "chat",
    "research-poster",
    "oscilloscope",
    "displacement",
    "reveal",
    "chronicle",
}

SUPER_CATEGORY_TAGS = {
    "homage",
    "ward",
    "instrument",
    "m8",
    "hothouse",
    "cbip",
    "bitchx",
    "lore-ext",
}


def _load_source_rates() -> list[dict]:
    raw = json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))
    return raw.get("sources", [])


def test_functional_tags_share_update_rate() -> None:
    sources = _load_source_rates()
    tag_rates: dict[str, set[str]] = defaultdict(set)
    tag_sources: dict[str, list[str]] = defaultdict(list)

    for s in sources:
        rate = s.get("rate_hz")
        cadence = s.get("update_cadence", "?")
        effective = str(rate) if cadence == "rate" else cadence
        for tag in s.get("tags", []):
            if tag in TEMPORAL_GROUP_TAGS:
                tag_rates[tag].add(effective)
                tag_sources[tag].append(f"{s['id']}={effective}")

    violations = []
    for tag in sorted(tag_rates):
        if len(tag_rates[tag]) > 1:
            violations.append(f"  {tag}: {tag_sources[tag]}")

    assert not violations, (
        "L4 temporal coherence violation — functional tags with mixed rates:\n"
        + "\n".join(violations)
    )


def test_rate_band_count_within_pragnanz_range() -> None:
    """L5: rate bands should be neither too few (boring) nor too many (chaotic)."""
    sources = _load_source_rates()
    rates: set[str] = set()
    for s in sources:
        cadence = s.get("update_cadence", "?")
        if cadence == "rate":
            rates.add(str(s.get("rate_hz")))
        elif cadence == "always":
            rates.add("always")

    assert 4 <= len(rates) <= 8, f"Expected 4-8 rate bands, got {len(rates)}: {sorted(rates)}"


def test_no_source_exceeds_30hz() -> None:
    """No ward should update faster than 30fps — diminishing returns."""
    sources = _load_source_rates()
    for s in sources:
        if s.get("update_cadence") == "rate" and s.get("rate_hz"):
            assert s["rate_hz"] <= 30.0, f"{s['id']} rate_hz={s['rate_hz']} exceeds 30Hz"
