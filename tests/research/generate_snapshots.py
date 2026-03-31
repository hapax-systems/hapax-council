"""Generate diverse synthetic perception snapshots for A/B validation.

Produces 50 snapshots with realistic variance across flow, activity,
presence, biometrics, and audio dimensions. Each snapshot has a 'scenario'
tag describing the intended temporal pattern.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

ACTIVITIES = ["coding", "email", "browsing", "idle", "meeting", "music_production"]
GENRES = ["", "ambient", "lo-fi", "hip-hop", "focus"]


def generate_snapshots(n: int = 50, seed: int = 42) -> list[dict]:
    """Generate n synthetic perception snapshots with temporal continuity."""
    rng = random.Random(seed)
    snapshots: list[dict] = []

    # State machine for realistic temporal patterns
    activity = "coding"
    flow_score = 0.5
    hr = 72
    presence = 0.9
    genre = "lo-fi"

    for i in range(n):
        ts = 1000000.0 + i * 2.5

        # Evolve state with small perturbations + occasional transitions
        if rng.random() < 0.15:
            activity = rng.choice(ACTIVITIES)
        if rng.random() < 0.1:
            genre = rng.choice(GENRES)

        # Flow evolves smoothly
        flow_delta = rng.gauss(0, 0.05)
        if activity == "coding":
            flow_delta += 0.02
        elif activity in ("browsing", "idle"):
            flow_delta -= 0.03
        flow_score = max(0.0, min(1.0, flow_score + flow_delta))

        # HR correlates with flow and stress
        hr_delta = rng.gauss(0, 2)
        if flow_score > 0.7:
            hr_delta += 1
        hr = max(55, min(110, hr + hr_delta))

        # Presence occasionally dips
        if rng.random() < 0.05:
            presence = max(0.1, presence - 0.4)
        else:
            presence = min(1.0, presence + rng.gauss(0.02, 0.05))

        audio = max(0.0, rng.gauss(0.02, 0.015)) if genre else 0.001

        snapshots.append(
            {
                "ts": ts,
                "flow_score": round(flow_score, 3),
                "production_activity": activity,
                "audio_energy_rms": round(audio, 4),
                "heart_rate_bpm": int(hr),
                "music_genre": genre,
                "presence_probability": round(max(0.0, min(1.0, presence)), 3),
                "consent_phase": "no_guest",
            }
        )

    return snapshots


def main() -> None:
    snapshots = generate_snapshots(50)
    out = Path(__file__).parent / "fixtures" / "perception_snapshots_50.jsonl"
    with out.open("w") as f:
        for s in snapshots:
            f.write(json.dumps(s) + "\n")
    print(f"Wrote {len(snapshots)} snapshots to {out}")


if __name__ == "__main__":
    main()
