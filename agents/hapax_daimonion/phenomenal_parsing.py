"""Temporal bands XML parser and JSON readers for phenomenal context.

Extracts structured data from /dev/shm temporal, apperception, and stimmung
files so the phenomenal context renderer works with dicts, not raw XML/JSON.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

# Staleness thresholds (seconds)
TEMPORAL_STALE_S = 30.0
APPERCEPTION_STALE_S = 30.0
STIMMUNG_STALE_S = 300.0


def read_json(path: Path) -> dict | None:
    """Read a JSON file, returning None on any error."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def parse_temporal_snapshot(raw: dict | None) -> dict | None:
    """Apply staleness check and XML parse to a raw temporal dict.

    Returns None if raw is None, stale, or missing XML.
    """
    if raw is None:
        return None
    if (time.time() - raw.get("timestamp", 0)) > TEMPORAL_STALE_S:
        return None
    xml = raw.get("xml", "")
    if not xml:
        return None
    return parse_temporal_xml(xml, raw)


def parse_temporal_xml(xml: str, raw: dict) -> dict:
    """Parse temporal bands XML into structured dict for rendering.

    Extracts retention, impression, protention, surprises into dicts
    so the renderers don't need to do XML parsing.
    """
    result: dict = {"retention": [], "impression": {}, "protention": [], "surprises": []}

    # Impression fields: <tag>value</tag> or <tag surprise="0.5" expected="foo">value</tag>
    # tolerate attrs on the opening tag (e.g. <impression scale="tick">)
    impression_match = re.search(r"<impression[^>]*>(.*?)</impression>", xml, re.DOTALL)
    if impression_match:
        imp_xml = impression_match.group(1)
        for m in re.finditer(r"<(\w+)([^>]*)>([^<]*)</\1>", imp_xml):
            tag, attrs, value = m.groups()
            result["impression"][tag] = value.strip()
            surprise_m = re.search(r'surprise="([^"]*)"', attrs)
            expected_m = re.search(r'expected="([^"]*)"', attrs)
            if surprise_m:
                surprise_val = float(surprise_m.group(1))
                if surprise_val > 0.3:
                    result["surprises"].append(
                        {
                            "field": tag,
                            "observed": value.strip(),
                            "expected": expected_m.group(1) if expected_m else "",
                            "surprise": surprise_val,
                        }
                    )

    # Retention: <memory age_s="5" flow="active" activity="coding" presence="present">summary</memory>
    for m in re.finditer(r"<memory([^>]*)>([^<]*)</memory>", xml):
        attrs, summary = m.groups()
        age_m = re.search(r'age_s="([^"]*)"', attrs)
        flow_m = re.search(r'flow="([^"]*)"', attrs)
        activity_m = re.search(r'activity="([^"]*)"', attrs)
        presence_m = re.search(r'presence="([^"]*)"', attrs)
        result["retention"].append(
            {
                "age_s": float(age_m.group(1)) if age_m else 0.0,
                "flow_state": flow_m.group(1) if flow_m else "",
                "activity": activity_m.group(1) if activity_m else "",
                "presence": presence_m.group(1) if presence_m else "",
                "summary": summary.strip(),
            }
        )

    # Protention: <prediction state="..." confidence="0.72" precision="0.40">basis</prediction>
    # precision is optional (back-compat with pre-band-tense XML).
    for m in re.finditer(
        r'<prediction\s+state="([^"]*)"\s+confidence="([^"]*)"'
        r'(?:\s+precision="([^"]*)")?>([^<]*)</prediction>',
        xml,
    ):
        state, confidence, precision, basis = m.groups()
        result["protention"].append(
            {
                "predicted_state": state,
                "confidence": float(confidence),
                "precision": float(precision) if precision is not None else 0.0,
                "basis": basis.strip(),
            }
        )

    # Add raw surprise data if not already captured from impression annotations
    max_surprise = raw.get("max_surprise", 0.0)
    if max_surprise > 0.3 and not result["surprises"]:
        for m in re.finditer(r'<surprise[^>]*observed="([^"]*)"', xml):
            result["surprises"].append(
                {
                    "field": "observation",
                    "observed": m.group(1),
                    "expected": "",
                    "surprise": max_surprise,
                }
            )

    return result
