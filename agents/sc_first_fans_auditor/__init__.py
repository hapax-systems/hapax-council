"""SoundCloud First-Fans cohort audit — Phase 1.

Per cc-task ``sc-cohort-first-fans`` and drop-1: SoundCloud's
"First Fans" / early-listener cohort surface is bot-injectable. This
module ships the auto-flagging heuristics that examine a First-Fans
cohort and flag any cohort whose retention < 20% or like-ratio < 1%
— both diagnostic of bot-injection or Amplify-push patterns.

Constitutional posture (per drop-1 + ``project_academic_spectacle_strategy``):
operator-private path. Cohort identifiers are user data per
single-operator transparency norms — the audit log lands in vault,
not on omg.lol or any public surface. The aggregate metric counters
(no PII) are the only externalised signal.

Phase 1 (this module) ships:

  - :class:`FirstFanRecord` — single cohort member's metrics
  - :class:`FirstFansCohort` — per-track cohort aggregate
  - :func:`flag_low_retention` / :func:`flag_low_like_ratio`
  - :func:`audit_cohort` — returns flag set per cohort
  - :func:`render_audit_log` — vault-private markdown writer

Phase 2 will wire:
  - SoundCloud public-cohort scraper (no API key per spec-2026-04-18)
  - Daily systemd timer (06:30 UTC after attestation publisher)
  - Vault writer (operator-private path)
  - ``hapax_sc_first_fans_flags_total{flag_type}`` Prometheus counter

Refusal lineage: this audit refuses the bot-flatterable surface
(raw cohort size) and surfaces the truth-shaped metric (retention +
like-ratio). Twin to ``sc_attestation_publisher`` for cohort variance.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

DEFAULT_AUDIT_DIR: Final[Path] = Path.home() / "Documents" / "Personal" / "30-areas" / "sc-audits"
"""Operator-private audit log landing zone (PARA convention).

Audits land here as ``{iso-date}-first-fans-audit.md``. NEVER
published to omg.lol or any public surface — cohort IDs are user
data per single-operator transparency norms.
"""

RETENTION_FLAG_THRESHOLD: Final[float] = 0.20
"""Retention < 20% flagged. Organic 30s-retention floors at ~25-30%
per public SC analytics; below 20% is diagnostic of bot listens
that drop after tier-1 thresholds (hence the 30s anchor)."""

LIKE_RATIO_FLAG_THRESHOLD: Final[float] = 0.01
"""Like-ratio < 1% flagged. Organic baseline is 2-8% (twin to
``sc_attestation_publisher``'s cohort-variance threshold). Below
1% is diagnostic of bot-injected plays — bot farms inflate play
counts without inflating likes."""


@dataclass(frozen=True)
class FirstFanRecord:
    """One First-Fan cohort member's public-surface metrics.

    Per spec-2026-04-18-soundcloud's REFUSE on SC API credential
    bootstrap: ``listener_handle`` is a stable opaque string (the
    cohort ID surfaced in the public First-Fans listing), NOT a
    SC user ID. The handle is hashed before vault write.
    """

    listener_handle: str
    play_count: int
    retention_30s_flag: bool
    liked: bool


@dataclass(frozen=True)
class FirstFansCohort:
    """Per-track First-Fans cohort aggregate.

    A track's cohort is its top N early-listener slots (typically
    20). Bot-injection signal manifests at the cohort level, not
    the per-track level — hence we audit cohorts, not tracks.
    """

    track_url: str
    track_title: str
    cohort_size: int
    members: list[FirstFanRecord]

    def retention_rate(self) -> float:
        """Fraction of cohort members who retained past 30s.

        Returns 0.0 when ``cohort_size == 0``. Per drop-1: <20%
        is the auto-flag threshold.
        """
        if self.cohort_size == 0:
            return 0.0
        return sum(1 for m in self.members if m.retention_30s_flag) / self.cohort_size

    def like_ratio(self) -> float:
        """Fraction of cohort members who liked the track.

        Returns 0.0 when ``cohort_size == 0``. Per drop-1: <1% is
        the auto-flag threshold (organic baseline 2-8%).
        """
        if self.cohort_size == 0:
            return 0.0
        return sum(1 for m in self.members if m.liked) / self.cohort_size


def flag_low_retention(cohort: FirstFansCohort) -> bool:
    """Return True iff cohort retention < ``RETENTION_FLAG_THRESHOLD``.

    Empty cohorts (``cohort_size == 0``) return False — there is
    no diagnostic signal in absent data; absence is its own data
    point handled by the cohort-presence audit, not this one.
    """
    if cohort.cohort_size == 0:
        return False
    return cohort.retention_rate() < RETENTION_FLAG_THRESHOLD


def flag_low_like_ratio(cohort: FirstFansCohort) -> bool:
    """Return True iff cohort like-ratio < ``LIKE_RATIO_FLAG_THRESHOLD``.

    Empty cohorts return False (see :func:`flag_low_retention`).
    """
    if cohort.cohort_size == 0:
        return False
    return cohort.like_ratio() < LIKE_RATIO_FLAG_THRESHOLD


@dataclass(frozen=True)
class CohortAuditResult:
    """One cohort's audit verdict.

    ``flags`` is a frozenset of strings: ``"low_retention"``,
    ``"low_like_ratio"``, or both. Empty frozenset means clean.
    """

    track_url: str
    track_title: str
    cohort_size: int
    retention_rate: float
    like_ratio: float
    flags: frozenset[str]


def audit_cohort(cohort: FirstFansCohort) -> CohortAuditResult:
    """Run all heuristics on ``cohort`` and return the verdict."""
    flags: set[str] = set()
    if flag_low_retention(cohort):
        flags.add("low_retention")
    if flag_low_like_ratio(cohort):
        flags.add("low_like_ratio")
    return CohortAuditResult(
        track_url=cohort.track_url,
        track_title=cohort.track_title,
        cohort_size=cohort.cohort_size,
        retention_rate=cohort.retention_rate(),
        like_ratio=cohort.like_ratio(),
        flags=frozenset(flags),
    )


def render_audit_log(audit_date: datetime, results: list[CohortAuditResult]) -> str:
    """Render the daily audit log markdown.

    The output is operator-private — cohort IDs are NOT included,
    only aggregate counts and flag-set per track. The markdown is
    written to vault under ``DEFAULT_AUDIT_DIR``.
    """
    flagged = [r for r in results if r.flags]
    clean = [r for r in results if not r.flags]
    iso_date = audit_date.strftime("%Y-%m-%d")
    lines = [
        f"# SC First-Fans audit — {iso_date}",
        "",
        f"Cohorts examined: **{len(results)}**",
        f"Cohorts flagged: **{len(flagged)}**",
        f"Cohorts clean:   **{len(clean)}**",
        "",
        "## Flagged cohorts",
        "",
    ]
    if not flagged:
        lines.append("_(none)_")
    for r in flagged:
        flag_str = ", ".join(sorted(r.flags))
        lines.extend(
            [
                f"### {r.track_title}",
                f"- url: {r.track_url}",
                f"- cohort_size: {r.cohort_size}",
                f"- retention_rate: {r.retention_rate:.3f}",
                f"- like_ratio:     {r.like_ratio:.3f}",
                f"- flags:          {flag_str}",
                "",
            ]
        )
    lines.extend(
        [
            "## Clean cohorts (count only — no per-track listing)",
            "",
            f"_{len(clean)} cohorts passed both heuristics_",
            "",
        ]
    )
    return "\n".join(lines)


__all__ = [
    "DEFAULT_AUDIT_DIR",
    "RETENTION_FLAG_THRESHOLD",
    "LIKE_RATIO_FLAG_THRESHOLD",
    "FirstFanRecord",
    "FirstFansCohort",
    "CohortAuditResult",
    "flag_low_retention",
    "flag_low_like_ratio",
    "audit_cohort",
    "render_audit_log",
]
