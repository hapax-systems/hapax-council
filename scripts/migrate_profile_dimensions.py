"""One-time migration: remap profile facts from old 14 dimensions to new 12.

Usage:
    uv run python scripts/migrate_profile_dimensions.py [--dry-run]

Reads profiles/operator-profile.json, remaps dimensions, writes updated profile.
Dropped facts (e.g. hardware) go to profiles/migration-review.jsonl.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from shared.dimensions import get_dimension_names

# ── Key heuristics for dimensions that fan out ────────────────────────────────

_TOOL_KEYS = {"tool", "prefer", "editor", "ide", "cli", "shell", "terminal", "plugin", "extension"}
_SCHEDULE_KEYS = {
    "schedule",
    "cadence",
    "meeting",
    "time",
    "focus",
    "routine",
    "session",
    "daily",
    "weekly",
}
_AESTHETIC_KEYS = {"bpm", "aesthetic", "genre", "style", "taste", "vibe", "sound", "texture"}
_GEAR_KEYS = {
    "sp404",
    "mpc",
    "digitakt",
    "digitone",
    "oxi",
    "rytm",
    "sampler",
    "synth",
    "midi",
    "daw",
}


def _key_matches(key: str, keywords: set[str]) -> bool:
    key_lower = key.lower()
    return any(kw in key_lower for kw in keywords)


def remap_dimension(old_dim: str, key: str) -> str | None:
    """Map an old dimension + key to a new dimension name.

    Returns None if the fact should be dropped (e.g. hardware).
    """
    # Direct renames
    direct_map = {
        "identity": "identity",
        "neurocognitive_profile": "neurocognitive",
        "communication_style": "communication_style",
        "relationships": "relationships",
        "philosophy": "values",
        "team_leadership": "management",
        "management_practice": "management",
    }

    if old_dim in direct_map:
        return direct_map[old_dim]

    # Dropped dimensions
    if old_dim == "hardware":
        return None

    # Sync agent drift dimensions
    drift_map = {
        "interests": "information_seeking",
        "communication": "communication_patterns",
        "knowledge": "information_seeking",
    }
    if old_dim in drift_map:
        return drift_map[old_dim]

    # Fan-out dimensions (key heuristics)
    if old_dim == "workflow":
        if _key_matches(key, _TOOL_KEYS):
            return "tool_usage"
        return "work_patterns"

    if old_dim == "technical_skills":
        if _key_matches(key, _TOOL_KEYS):
            return "tool_usage"
        return "identity"

    if old_dim == "software_preferences":
        return "tool_usage"

    if old_dim == "music_production":
        if _key_matches(key, _AESTHETIC_KEYS):
            return "values"
        return "creative_process"

    if old_dim == "decision_patterns":
        return "values"

    if old_dim == "knowledge_domains":
        return "information_seeking"

    # Unknown dimension — check if it's already valid
    if old_dim in get_dimension_names():
        return old_dim

    return None


def migrate_profile(profile_path: Path) -> dict:
    """Read a profile, remap all facts, return the new profile dict.

    Dropped facts are written to migration-review.jsonl alongside the profile.
    """
    raw = json.loads(profile_path.read_text())
    review_path = profile_path.parent / "migration-review.jsonl"

    new_dims: dict[str, dict] = {}  # name -> {"name", "summary", "facts"}
    dropped: list[dict] = []

    for dim in raw.get("dimensions", []):
        old_name = dim["name"]
        for fact in dim.get("facts", []):
            new_name = remap_dimension(old_name, fact.get("key", ""))
            if new_name is None:
                dropped.append(
                    {
                        "old_dimension": old_name,
                        "fact": fact,
                        "reason": f"dimension '{old_name}' dropped from taxonomy",
                    }
                )
                continue

            fact["dimension"] = new_name
            if new_name not in new_dims:
                new_dims[new_name] = {"name": new_name, "summary": "", "facts": []}
            new_dims[new_name]["facts"].append(fact)

    # Write dropped facts for review
    if dropped:
        with open(review_path, "w", encoding="utf-8") as fh:
            for entry in dropped:
                fh.write(json.dumps(entry) + "\n")

    raw["dimensions"] = list(new_dims.values())
    raw["version"] = raw.get("version", 0) + 1
    return raw


def main():
    from shared.config import PROFILES_DIR

    dry_run = "--dry-run" in sys.argv
    profile_path = PROFILES_DIR / "operator-profile.json"

    if not profile_path.exists():
        print("No profile found at", profile_path)
        return

    result = migrate_profile(profile_path)

    if dry_run:
        dim_summary = {d["name"]: len(d["facts"]) for d in result["dimensions"]}
        print("Dry run — new dimensions:")
        for name, count in sorted(dim_summary.items()):
            print(f"  {name}: {count} facts")
        print(f"\nTotal: {sum(dim_summary.values())} facts across {len(dim_summary)} dimensions")
        review_path = profile_path.parent / "migration-review.jsonl"
        if review_path.exists():
            lines = review_path.read_text().strip().splitlines()
            print(f"Dropped: {len(lines)} facts (see {review_path})")
    else:
        import shutil

        backup_path = profile_path.with_suffix(".pre-migration.json")
        shutil.copy2(profile_path, backup_path)
        print(f"Backup: {backup_path}")

        profile_path.write_text(json.dumps(result, indent=2))
        print(f"Migrated profile: v{result['version']}, {len(result['dimensions'])} dimensions")


if __name__ == "__main__":
    main()
