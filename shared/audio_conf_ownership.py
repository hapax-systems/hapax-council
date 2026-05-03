"""Audio config-file ownership registry (cc-task audio-audit-E-audio-conf-mtime-watcher Phase 0).

Each config file the audio stack reads has an owning systemd user unit.
When the conf-watcher daemon (Phase 1) sees an mtime change on the file,
it validates the new content + runs ``systemctl --user reload-or-restart``
on the named unit.

Phase 0 (this module): the ownership schema + YAML loader + Prometheus
counter declaration. The inotify daemon + systemctl reload land in Phase 1.

Why factor it this way:
- The ownership table is the load-bearing claim ("editing X reloads Y").
  Pinning it standalone with a typed Pydantic model means a future
  ownership add/remove is a one-line YAML diff with full schema validation.
- The Prometheus counter labels (``file``, ``outcome``) are pinned now so
  Phase 1 can't quietly break Grafana dashboards.
- The ownership lookup helpers (``unit_for_path``, ``schema_for_path``)
  are the entry points the daemon will call per inotify event; testing
  them here keeps Phase 1 narrow.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from prometheus_client import Counter
from pydantic import BaseModel, ConfigDict, Field, field_validator

# Schema names the Phase 1 watcher knows how to validate before reload.
# "none" = pass-through (no pre-reload validation). Adding a schema here
# requires writing a Pydantic model on the validator side.
ConfSchemaName = Literal["audio_topology", "none"]
"""Schema selector for pre-reload validation.

Currently:
- ``audio_topology``: validates against ``shared.audio_topology.TopologyDescriptor``
- ``none``: pass-through (used for PipeWire-native ``.conf`` files which have
  no Pydantic counterpart yet; audit-E typed-params is the planned remediation)
"""


class ConfOwnership(BaseModel):
    """One config-file -> owning-systemd-unit mapping."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(min_length=1, description="Path to the config file")
    owning_unit: str = Field(
        min_length=1,
        description="systemd --user unit name (e.g., 'hapax-music-loudnorm.service')",
    )
    validator_schema: ConfSchemaName = Field(description="Pre-reload validator selector")
    description: str = Field(min_length=1, description="Human-readable purpose")

    @field_validator("owning_unit")
    @classmethod
    def _unit_must_have_systemd_suffix(cls, v: str) -> str:
        """Reject ownership entries that don't name a systemd unit. The
        Phase 1 watcher passes this string verbatim to ``systemctl --user``;
        a typo'd unit name would silently no-op."""
        if not (v.endswith(".service") or v.endswith(".target") or v.endswith(".timer")):
            raise ValueError(f"owning_unit {v!r} must end with .service, .target, or .timer")
        return v


class ConfOwnershipRegistry(BaseModel):
    """Top-level loaded ownership YAML."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = Field(ge=1)
    ownerships: tuple[ConfOwnership, ...]

    @field_validator("ownerships")
    @classmethod
    def _no_duplicate_paths(cls, v: tuple[ConfOwnership, ...]) -> tuple[ConfOwnership, ...]:
        """Two ownership entries claiming the same path is almost always a
        merge accident. Reject explicitly so the operator notices."""
        seen: set[str] = set()
        for entry in v:
            if entry.path in seen:
                raise ValueError(f"duplicate path in ownerships: {entry.path!r}")
            seen.add(entry.path)
        return v

    def unit_for_path(self, path: str) -> str | None:
        """Return the owning systemd unit for ``path``, or None if unowned.

        Phase 1 calls this on every inotify event; an unowned path is a
        no-op (no reload, but logged for operator awareness).
        """
        for entry in self.ownerships:
            if entry.path == path:
                return entry.owning_unit
        return None

    def schema_for_path(self, path: str) -> ConfSchemaName | None:
        """Return the validator schema for ``path``, or None if unowned."""
        for entry in self.ownerships:
            if entry.path == path:
                return entry.validator_schema
        return None


def load_conf_ownership(yaml_path: Path) -> ConfOwnershipRegistry:
    """Load + validate the ownership YAML.

    Raises ``pydantic.ValidationError`` with all violations on a malformed
    file, ``FileNotFoundError`` on missing path, ``yaml.YAMLError`` on
    parse failure. The Phase 1 daemon catches these and exits with an
    actionable error rather than starting in a broken state.
    """
    with yaml_path.open() as f:
        raw = yaml.safe_load(f)
    return ConfOwnershipRegistry.model_validate(raw)


# Phase 1 reload-event counter, labels pinned ahead of the daemon to avoid
# quiet dashboard breakage.
hapax_audio_conf_reload_total: Counter = Counter(
    "hapax_audio_conf_reload_total",
    "Audio config-file mtime-triggered reload outcomes",
    labelnames=("file", "outcome"),
)
"""Reload outcome counter.

``outcome`` label values (Phase 1 emits these):
- ``"success"``: validated + systemctl reload-or-restart returned 0
- ``"validation-failed"``: schema check rejected the new content;
  no reload attempted; ntfy alert sent
- ``"systemctl-failed"``: validation passed but systemctl reload-or-restart
  returned non-zero
- ``"unowned-path"``: inotify fired on a path with no ownership entry;
  no reload, logged
"""
