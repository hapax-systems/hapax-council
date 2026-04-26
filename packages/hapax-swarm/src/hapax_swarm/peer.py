"""Per-session peer.yaml read/write.

Each session owns one ``{role}.yaml`` file in the relay directory and
writes the heartbeat schema documented in ``PROTOCOL.md``:

.. code-block:: yaml

    session: beta
    updated: "2026-04-25T12:00:00Z"
    workstream: "observability + relay-protocol"
    focus: "current task title"
    current_item: "001"
    currently_working_on:
      surface: "packages/hapax-swarm/"
      branch_target: "beta/hapax-swarm-pypi"
      claimed_at: "2026-04-25T12:00:00Z"
    completed:
      - "description (PR #N)"
    next: "what I'll do next"

The owner mutates in place; siblings only read.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import yaml

from hapax_swarm.atomic import atomic_write_yaml

if TYPE_CHECKING:
    from pathlib import Path


@dataclasses.dataclass
class PeerYaml:
    """A single session's heartbeat file.

    Construct via :meth:`RelayDir.peer` rather than directly so the
    ``path`` is always rooted in the relay directory.
    """

    role: str
    path: Path

    def exists(self) -> bool:
        return self.path.exists()

    def read(self) -> dict[str, Any]:
        """Read the yaml; return ``{}`` if the file does not exist."""
        if not self.path.exists():
            return {}
        text = self.path.read_text(encoding="utf-8")
        loaded = yaml.safe_load(text)
        if loaded is None:
            return {}
        if not isinstance(loaded, dict):
            raise ValueError(f"peer.yaml at {self.path} is not a mapping")
        return loaded

    def write(self, data: dict[str, Any]) -> None:
        """Atomically replace the yaml with ``data``.

        Always sets ``session: <role>`` and ``updated: <utc-now>`` so
        callers do not need to remember.
        """
        payload: dict[str, Any] = {"session": self.role}
        payload.update(data)
        payload["updated"] = _utc_now_iso()
        atomic_write_yaml(self.path, payload)

    def update(self, **fields: Any) -> dict[str, Any]:
        """Merge ``fields`` into the existing yaml and atomically write.

        Returns the post-write payload.
        """
        existing = self.read()
        existing.update(fields)
        self.write(existing)
        return self.read()

    @property
    def currently_working_on(self) -> dict[str, Any] | None:
        """Convenience accessor for the claim record."""
        record = self.read().get("currently_working_on")
        if record is None:
            return None
        if not isinstance(record, dict):
            raise ValueError(f"peer.yaml at {self.path} has non-mapping currently_working_on")
        return record


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
