"""Shared research-state snapshot for research-poster Cairo wards."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from agents.studio_compositor.research_instrument_dashboard_ward import CLAIMS_FILE, ClaimRow
from agents.studio_compositor.research_instrument_dashboard_ward import load_claims as _load_claims
from shared.research_marker import read_marker

FALSEY_ENV_VALUES = {"", "0", "false", "no", "off"}


@dataclass(frozen=True)
class ResearchPosterState:
    """Small, redaction-safe snapshot shared by all poster wards."""

    condition_id: str | None
    epoch: int | None
    claim_rows: tuple[ClaimRow, ...]

    @property
    def claim_count(self) -> int:
        return len(self.claim_rows)

    @property
    def passing_count(self) -> int:
        return self._status_count("passing")

    @property
    def failing_count(self) -> int:
        return self._status_count("failing")

    @property
    def unverified_count(self) -> int:
        return self._status_count("unverified")

    @property
    def passing_ratio(self) -> float:
        if not self.claim_rows:
            return 0.0
        return self.passing_count / len(self.claim_rows)

    @property
    def density_values(self) -> tuple[float, ...]:
        """Deterministic small-multiple values derived from claim statuses."""

        if not self.claim_rows:
            return (0.10, 0.16, 0.13, 0.22, 0.18, 0.24, 0.20, 0.28)
        mapping = {
            "passing": 0.82,
            "failing": 0.18,
            "unverified": 0.50,
        }
        return tuple(mapping.get(row.status, 0.35) for row in self.claim_rows[:24])

    @property
    def condition_label(self) -> str:
        return self.condition_id or "condition-unknown"

    def _status_count(self, status: str) -> int:
        return sum(1 for row in self.claim_rows if row.status == status)


def research_poster_feature_enabled(env_name: str) -> bool:
    """Read a default-off research-poster ward feature flag."""

    raw = os.environ.get(env_name, "0")
    return raw.strip().lower() not in FALSEY_ENV_VALUES


def read_research_poster_state(claims_path: Path = CLAIMS_FILE) -> ResearchPosterState:
    """Read active research marker and claim rows without raising."""

    try:
        marker = read_marker()
    except Exception:
        marker = None
    try:
        claims = tuple(_load_claims(claims_path))
    except Exception:
        claims = ()
    return ResearchPosterState(
        condition_id=marker.condition_id if marker else None,
        epoch=marker.epoch if marker else None,
        claim_rows=claims,
    )


__all__ = [
    "FALSEY_ENV_VALUES",
    "ResearchPosterState",
    "read_research_poster_state",
    "research_poster_feature_enabled",
]
