"""Itch.io PWYW research-artifact bundle — Phase 1.

Per cc-task ``leverage-money-itch-pwyw-bundle`` and drop-leverage:
Pay-What-You-Want bundle on Itch.io combining velocity report +
arXiv preprint + dataset corpus + 4 PyPI methodology packages.

Day 31-60 milestone per the 90-day leverage strategy. Butler CLI is
programmatic; the GH Actions release workflow handles the upload on
``velocity-report-*`` tag.

Phase 1 (this module) ships:

  - :class:`BundleArtifact` — typed artifact in the bundle (paper /
    dataset / wheel)
  - :class:`BundleManifest` — frozen manifest enumerating every
    artifact + its source
  - :func:`scan_local_artifacts` — discovers bundle inputs from the
    local filesystem (paper PDF, dataset zip, dist/ wheels)
  - :func:`render_butler_command` — formats the ``butler push``
    invocation per artifact
  - :func:`render_dry_run_report` — markdown enumeration without
    actually pushing

Phase 2.5 (deferred until ``itch/butler-token`` cred lands):
  - GH Actions workflow ``itch-bundle-release.yml`` (tag-triggered)
  - Receipt poller via Itch.io API → monetization block
  - ``hapax_leverage_itch_bundle_downloads_total{tier}`` Prometheus
    counter

Constitutional posture: co-publishing — Hapax + Claude Code as
co-authors with unsettled-contribution note. Anti-anthropomorphization
— bundle is structured artefact (paper + corpus + packages), not a
"product launch."
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

DEFAULT_ITCH_USER: Final[str] = "oudepode"
"""Operator's Itch.io username (one-time bootstrap)."""

DEFAULT_BUNDLE_SLUG: Final[str] = "hapax-velocity-bundle"
"""Itch.io project slug for the PWYW bundle.

Full target string: ``{user}/{slug}:{channel}``. The ``channel`` is
the artifact role (paper / dataset / wheels).
"""

ARTIFACT_PAPER: Final[str] = "paper"
ARTIFACT_DATASET: Final[str] = "dataset"
ARTIFACT_WHEEL: Final[str] = "wheel"
"""Bundle artifact roles. Maps 1:1 to butler channel names."""

DEFAULT_PAPER_PATH: Final[Path] = (
    Path.home() / "hapax-state" / "publications" / "velocity-report.pdf"
)
"""Local path of the velocity-report PDF (per
``leverage-mktg-velocity-report-publish``)."""

DEFAULT_DATASET_PATH: Final[Path] = (
    Path.home() / "hapax-state" / "publications" / "velocity-corpus.zip"
)
"""Local path of the dataset corpus zip."""

DEFAULT_DIST_DIR: Final[Path] = Path.home() / "projects" / "hapax-council" / "dist"
"""PyPI wheel build output (4 leverage-workflow methodology packages)."""


@dataclass(frozen=True)
class BundleArtifact:
    """One artifact in the Itch.io PWYW bundle.

    ``role`` is one of ``ARTIFACT_PAPER`` / ``ARTIFACT_DATASET`` /
    ``ARTIFACT_WHEEL``. ``channel`` is the butler channel string
    (defaults to ``role``).
    """

    role: str
    source_path: Path
    channel: str
    bytes: int

    def exists(self) -> bool:
        return self.source_path.exists()


@dataclass(frozen=True)
class BundleManifest:
    """Complete enumeration of the bundle's artifact set.

    A manifest with ``artifacts == ()`` indicates no artifacts were
    discovered locally (deps not yet shipped); the dry-run report
    surfaces this as a no-op rather than failing.
    """

    user: str
    slug: str
    artifacts: tuple[BundleArtifact, ...]

    def target(self, role: str) -> str:
        """Itch.io target string ``{user}/{slug}:{channel}``."""
        return f"{self.user}/{self.slug}:{role}"


def scan_local_artifacts(
    paper_path: Path = DEFAULT_PAPER_PATH,
    dataset_path: Path = DEFAULT_DATASET_PATH,
    dist_dir: Path = DEFAULT_DIST_DIR,
    user: str = DEFAULT_ITCH_USER,
    slug: str = DEFAULT_BUNDLE_SLUG,
) -> BundleManifest:
    """Discover artifacts from the local filesystem.

    Missing files are silently skipped — the dry-run report will
    surface the gap as ``(missing)``. Wheels are matched by
    ``*.whl`` suffix; one artifact entry per wheel file (separate
    butler channels per wheel name keep individual upload diffs
    clean).
    """
    artifacts: list[BundleArtifact] = []
    if paper_path.exists():
        artifacts.append(
            BundleArtifact(
                role=ARTIFACT_PAPER,
                source_path=paper_path,
                channel=ARTIFACT_PAPER,
                bytes=paper_path.stat().st_size,
            )
        )
    if dataset_path.exists():
        artifacts.append(
            BundleArtifact(
                role=ARTIFACT_DATASET,
                source_path=dataset_path,
                channel=ARTIFACT_DATASET,
                bytes=dataset_path.stat().st_size,
            )
        )
    if dist_dir.exists():
        for whl in sorted(dist_dir.glob("*.whl")):
            channel = f"{ARTIFACT_WHEEL}-{whl.stem.split('-')[0]}"
            artifacts.append(
                BundleArtifact(
                    role=ARTIFACT_WHEEL,
                    source_path=whl,
                    channel=channel,
                    bytes=whl.stat().st_size,
                )
            )
    return BundleManifest(user=user, slug=slug, artifacts=tuple(artifacts))


def render_butler_command(manifest: BundleManifest, artifact: BundleArtifact) -> list[str]:
    """Format the ``butler push`` invocation per artifact.

    Returns the argv list (not a shell-string) so the caller can
    subprocess it directly. The token is sourced from
    ``$BUTLER_API_KEY`` at run time; it is NOT included here.
    """
    return [
        "butler",
        "push",
        str(artifact.source_path),
        manifest.target(artifact.channel),
    ]


def render_dry_run_report(manifest: BundleManifest) -> str:
    """Render the dry-run report markdown.

    Output enumerates per-artifact target string, source path,
    file size, and a ``(missing)`` marker for absent files. The
    actual ``butler push`` command is also surfaced for operator
    inspection ahead of the Phase 2.5 minting loop.
    """
    lines = [
        f"# Itch.io PWYW bundle dry-run — {manifest.user}/{manifest.slug}",
        "",
        f"Artifacts discovered: **{len(manifest.artifacts)}**",
        "",
        "## Per-artifact upload plan",
        "",
    ]
    if not manifest.artifacts:
        lines.extend(
            [
                "_(no artifacts discovered — deps may not yet be shipped)_",
                "",
                "Re-run after `leverage-mktg-velocity-report-publish` and",
                "`leverage-workflow-*-pypi` Phase 2.5 minting completes.",
                "",
            ]
        )
        return "\n".join(lines)
    for artifact in manifest.artifacts:
        present = "" if artifact.exists() else " _(missing)_"
        cmd = " ".join(render_butler_command(manifest, artifact))
        lines.extend(
            [
                f"### {artifact.role} — {artifact.channel}{present}",
                f"- target:      {manifest.target(artifact.channel)}",
                f"- source_path: {artifact.source_path}",
                f"- bytes:       {artifact.bytes}",
                f"- command:     `{cmd}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Re-run with --commit",
            "",
            "Re-run with `--commit` after the operator runs",
            "`pass insert itch/butler-token` (one-time bootstrap).",
            "",
        ]
    )
    return "\n".join(lines)


__all__ = [
    "DEFAULT_ITCH_USER",
    "DEFAULT_BUNDLE_SLUG",
    "ARTIFACT_PAPER",
    "ARTIFACT_DATASET",
    "ARTIFACT_WHEEL",
    "DEFAULT_PAPER_PATH",
    "DEFAULT_DATASET_PATH",
    "DEFAULT_DIST_DIR",
    "BundleArtifact",
    "BundleManifest",
    "scan_local_artifacts",
    "render_butler_command",
    "render_dry_run_report",
]
