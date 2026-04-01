"""Measure 3.3 — Surprise flagging impact on model reasoning.

Paired design: send 20 perception snapshots to Claude, each in two conditions:
  A) With surprise markup (surprise="0.72" expected="idle")
  B) Without surprise markup (plain XML tags)

For each pair, score whether the model mentions the surprised field.
If surprise markup helps, condition A should reference surprised fields
more often than condition B.

Run: uv run pytest tests/research/test_surprise_impact.py -m llm -v
"""

from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass

import pytest

# ── Synthetic perception snapshots ──────────────────────────────────────────


@dataclass
class SyntheticSnapshot:
    """A perception snapshot with one surprised field."""

    impression: dict[str, str]
    surprised_field: str
    surprise_value: float
    expected_value: str


def _generate_snapshots(n: int = 20, seed: int = 42) -> list[SyntheticSnapshot]:
    """Generate n synthetic perception snapshots with one surprise each."""
    rng = random.Random(seed)

    activities = ["coding", "browsing", "reading", "idle", "music_production"]
    flow_states = ["active", "warming", "idle"]
    presences = ["present", "away", "approaching"]
    emotions = ["focused", "relaxed", "frustrated", "neutral", "excited"]
    postures = ["upright", "leaning", "slouched"]

    fields_and_values = {
        "activity": activities,
        "flow_state": flow_states,
        "presence": presences,
        "emotion": emotions,
        "posture": postures,
    }

    snapshots = []
    for _ in range(n):
        field = rng.choice(list(fields_and_values.keys()))
        values = fields_and_values[field]
        observed = rng.choice(values)
        expected = rng.choice([v for v in values if v != observed] or values)
        surprise = round(rng.uniform(0.4, 0.95), 2)

        impression = {}
        for k, vs in fields_and_values.items():
            impression[k] = rng.choice(vs)
        impression[field] = observed

        snapshots.append(
            SyntheticSnapshot(
                impression=impression,
                surprised_field=field,
                surprise_value=surprise,
                expected_value=expected,
            )
        )
    return snapshots


def _format_xml_with_surprise(snap: SyntheticSnapshot) -> str:
    """Format impression XML with surprise markup on the surprised field."""
    parts = ["<temporal_context>", "  <impression>"]
    for key, val in snap.impression.items():
        if key == snap.surprised_field:
            parts.append(
                f'    <{key} surprise="{snap.surprise_value:.2f}" '
                f'expected="{snap.expected_value}">{val}</{key}>'
            )
        else:
            parts.append(f"    <{key}>{val}</{key}>")
    parts.append("  </impression>")
    parts.append("</temporal_context>")
    return "\n".join(parts)


def _format_xml_without_surprise(snap: SyntheticSnapshot) -> str:
    """Format impression XML without any surprise markup."""
    parts = ["<temporal_context>", "  <impression>"]
    for key, val in snap.impression.items():
        parts.append(f"    <{key}>{val}</{key}>")
    parts.append("  </impression>")
    parts.append("</temporal_context>")
    return "\n".join(parts)


# ── LLM evaluation ─────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are observing the operator's current state. Given the perception data below, "
    "describe what you notice in 2-3 sentences. Focus on anything notable or unexpected. "
    "Be specific about which aspects of the state you find interesting."
)


async def _ask_model(perception_xml: str) -> str:
    """Send perception XML to Claude and get response."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        base_url="http://localhost:4000",
        api_key=os.environ.get("LITELLM_API_KEY", "sk-dummy"),
    )
    resp = await client.chat.completions.create(
        model="claude-haiku",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Current perception state:\n\n{perception_xml}"},
        ],
        temperature=0.3,
        max_tokens=150,
    )
    return resp.choices[0].message.content.strip()


def _mentions_field(response: str, field: str, expected: str) -> bool:
    """Check if the response mentions the surprised field or its expected value."""
    lower = response.lower()
    # Check for field name mention
    if field.replace("_", " ") in lower or field in lower:
        # Check for surprise-related language
        surprise_words = [
            "surpris",
            "unexpected",
            "notably",
            "interesting",
            "unusual",
            "changed",
            "shifted",
            "contrast",
            "despite",
            "whereas",
            expected.lower(),
        ]
        return any(w in lower for w in surprise_words)
    return False


# ── Test ────────────────────────────────────────────────────────────────────


@pytest.mark.llm
@pytest.mark.asyncio
async def test_surprise_flagging_impact():
    """Paired comparison: does surprise markup increase model attention to surprised fields?

    20 snapshots x 2 conditions = 40 LLM calls.
    """
    snapshots = _generate_snapshots(20)
    results = []

    for i, snap in enumerate(snapshots):
        xml_with = _format_xml_with_surprise(snap)
        xml_without = _format_xml_without_surprise(snap)

        resp_with = await _ask_model(xml_with)
        resp_without = await _ask_model(xml_without)

        mentions_with = _mentions_field(resp_with, snap.surprised_field, snap.expected_value)
        mentions_without = _mentions_field(resp_without, snap.surprised_field, snap.expected_value)

        results.append(
            {
                "snapshot": i,
                "field": snap.surprised_field,
                "surprise": snap.surprise_value,
                "with_markup": mentions_with,
                "without_markup": mentions_without,
            }
        )

    # Compute effect
    with_count = sum(1 for r in results if r["with_markup"])
    without_count = sum(1 for r in results if r["without_markup"])
    both_count = sum(1 for r in results if r["with_markup"] and r["without_markup"])
    neither_count = sum(1 for r in results if not r["with_markup"] and not r["without_markup"])
    only_with = sum(1 for r in results if r["with_markup"] and not r["without_markup"])
    only_without = sum(1 for r in results if not r["with_markup"] and r["without_markup"])

    # Report
    print(f"\n{'=' * 60}")
    print("SURPRISE FLAGGING IMPACT (Measure 3.3)")
    print(f"{'=' * 60}")
    print(f"Snapshots: {len(results)}")
    print(f"With markup mentions surprised field: {with_count}/{len(results)}")
    print(f"Without markup mentions surprised field: {without_count}/{len(results)}")
    print(f"Both mention: {both_count}")
    print(f"Neither mention: {neither_count}")
    print(f"Only with markup: {only_with}")
    print(f"Only without markup: {only_without}")
    print(f"Effect (with - without): {with_count - without_count}")
    print(f"{'=' * 60}")

    # Save results
    output = {
        "measure": "3.3",
        "snapshots": len(results),
        "with_markup_mentions": with_count,
        "without_markup_mentions": without_count,
        "effect": with_count - without_count,
        "pairs": results,
    }
    output_path = "docs/research/surprise-flagging-results.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Results saved to {output_path}")

    # No hard assertion — this is exploratory
    # But flag if surprise markup has zero or negative effect
    if with_count <= without_count:
        print("WARNING: Surprise markup did not increase field attention")


# ── Harness validation (runs without LLM) ──────────────────────────────────


def test_snapshot_generation():
    """Verify synthetic snapshots are well-formed."""
    snaps = _generate_snapshots(5)
    assert len(snaps) == 5
    for s in snaps:
        assert s.surprised_field in s.impression
        assert 0.3 < s.surprise_value < 1.0
        assert s.expected_value != s.impression[s.surprised_field] or len(s.impression) > 0


def test_xml_formatting():
    """Verify XML with/without surprise markup differs only in surprise attributes."""
    snap = _generate_snapshots(1)[0]
    xml_with = _format_xml_with_surprise(snap)
    xml_without = _format_xml_without_surprise(snap)

    assert 'surprise="' in xml_with
    assert 'expected="' in xml_with
    assert 'surprise="' not in xml_without
    assert 'expected="' not in xml_without
    # Both should contain the same field values
    assert snap.impression[snap.surprised_field] in xml_with
    assert snap.impression[snap.surprised_field] in xml_without


def test_mentions_detection():
    """Verify _mentions_field catches relevant language."""
    assert _mentions_field("The flow state is surprisingly active", "flow_state", "idle")
    assert _mentions_field("I notice the flow_state has shifted unexpectedly", "flow_state", "idle")
    assert not _mentions_field("Everything looks normal", "flow_state", "idle")
