"""Team capability metadata registry and freshness gate.

Tracks per-lane model, tooling, worktree, and claimed-task metadata.
Freshness is part of dispatch authority — stale metadata blocks lane
selection rather than producing a warning.

ISAP: SLICE-003A-TEAM-METADATA (CASE-SDLC-REFORM-001)
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

REGISTRY_DIR = Path.home() / ".cache" / "hapax" / "team-registry"

Platform = Literal["claude-code", "codex", "gemini-cli", "vibe", "antigrav"]
FreshnessResult = Literal["fresh", "stale", "unknown", "blocked"]


class LaneMetadata(BaseModel):
    """Metadata for a single session lane."""

    lane_id: str = Field(description="e.g. alpha, beta, cx-red, cx-amber")
    platform: Platform
    model_id: str = Field(description="e.g. claude-opus-4-6, o3, gemini-3-pro")
    context_window: int = Field(description="Token context window")
    tools_available: list[str] = Field(
        default_factory=list,
        description="Tool categories: Edit, Bash, MCP, etc.",
    )
    worktree: str | None = Field(default=None, description="Worktree path if active")
    branch: str | None = Field(default=None, description="Current branch")
    claimed_task: str | None = Field(default=None, description="cc-task or AuthorityCase id")
    off_limits: list[str] = Field(
        default_factory=list,
        description="Paths/surfaces this lane must not touch",
    )
    last_probe_utc: float = Field(default=0.0, description="Unix timestamp of last probe")
    freshness_ttl_s: float = Field(
        default=3600.0,
        description="Max age in seconds before metadata is stale",
    )
    notes: str = ""

    def freshness(self, now: float | None = None) -> FreshnessResult:
        ts = now if now is not None else time.time()
        if self.last_probe_utc <= 0:
            return "unknown"
        if (ts - self.last_probe_utc) <= self.freshness_ttl_s:
            return "fresh"
        return "stale"

    def age_seconds(self, now: float | None = None) -> float:
        ts = now if now is not None else time.time()
        if self.last_probe_utc <= 0:
            return float("inf")
        return ts - self.last_probe_utc


class FreshnessReceipt(BaseModel):
    """Machine-checkable receipt from a metadata freshness check."""

    lane_id: str
    platform: Platform
    model_id: str
    checked_at: float
    checked_by: str = Field(description="Session or script that probed")
    result: FreshnessResult
    stale_after: float = Field(description="Unix timestamp when this goes stale")
    blockers: list[str] = Field(default_factory=list)
    notes: str = ""


class TeamRegistry:
    """File-backed registry of lane metadata."""

    def __init__(self, registry_dir: Path | None = None) -> None:
        self._dir = registry_dir or REGISTRY_DIR
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, lane_id: str) -> Path:
        return self._dir / f"{lane_id}.json"

    def write(self, meta: LaneMetadata) -> Path:
        path = self._path(meta.lane_id)
        path.write_text(meta.model_dump_json(indent=2))
        return path

    def read(self, lane_id: str) -> LaneMetadata | None:
        path = self._path(lane_id)
        if not path.exists():
            return None
        try:
            return LaneMetadata.model_validate_json(path.read_text())
        except Exception:
            return None

    def all_lanes(self) -> list[LaneMetadata]:
        lanes = []
        for p in sorted(self._dir.glob("*.json")):
            try:
                lanes.append(LaneMetadata.model_validate_json(p.read_text()))
            except Exception:
                continue
        return lanes

    def fresh_lanes(self, now: float | None = None) -> list[LaneMetadata]:
        return [m for m in self.all_lanes() if m.freshness(now) == "fresh"]

    def stale_lanes(self, now: float | None = None) -> list[LaneMetadata]:
        return [m for m in self.all_lanes() if m.freshness(now) in ("stale", "unknown")]

    def check_freshness(
        self,
        lane_id: str,
        checked_by: str = "team-metadata-probe",
        now: float | None = None,
    ) -> FreshnessReceipt:
        ts = now if now is not None else time.time()
        meta = self.read(lane_id)
        if meta is None:
            return FreshnessReceipt(
                lane_id=lane_id,
                platform="claude-code",
                model_id="unknown",
                checked_at=ts,
                checked_by=checked_by,
                result="unknown",
                stale_after=ts,
                blockers=["no metadata file"],
            )
        result = meta.freshness(ts)
        return FreshnessReceipt(
            lane_id=lane_id,
            platform=meta.platform,
            model_id=meta.model_id,
            checked_at=ts,
            checked_by=checked_by,
            result=result,
            stale_after=meta.last_probe_utc + meta.freshness_ttl_s,
            blockers=(
                []
                if result == "fresh"
                else [f"age={meta.age_seconds(ts):.0f}s > ttl={meta.freshness_ttl_s:.0f}s"]
            ),
        )

    def remove(self, lane_id: str) -> bool:
        path = self._path(lane_id)
        if path.exists():
            path.unlink()
            return True
        return False


def freshness_gate(
    lane_id: str,
    registry: TeamRegistry | None = None,
    now: float | None = None,
) -> FreshnessReceipt:
    """Check if a lane's metadata is fresh enough for dispatch."""
    reg = registry or TeamRegistry()
    return reg.check_freshness(lane_id, now=now)
