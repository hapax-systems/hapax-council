"""Relay sync rule — tracks in-flight file edits and PR events across sessions."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from agents.session_conductor.rules import HookEvent, HookResponse, RuleBase
from agents.session_conductor.state import SessionState
from agents.session_conductor.topology import TopologyConfig

log = logging.getLogger(__name__)

DEFAULT_RELAY_DIR = Path.home() / ".cache" / "hapax" / "relay"

_PR_URL_RE = re.compile(r"https://github\.com/\S+/pull/(\d+)", re.IGNORECASE)
_PR_MERGE_RE = re.compile(r"Pull request #(\d+) merged", re.IGNORECASE)

_EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})

RELAY_SYNC_INTERVAL = timedelta(minutes=30)


def detect_pr_event(output: str) -> dict[str, Any] | None:
    """Detect PR create or merge events in tool output.

    Returns a dict with keys 'type' ('create' | 'merge') and 'pr_number', or None.
    """
    m = _PR_MERGE_RE.search(output)
    if m:
        return {"type": "merge", "pr_number": int(m.group(1))}
    m = _PR_URL_RE.search(output)
    if m:
        return {"type": "create", "pr_number": int(m.group(1))}
    return None


class RelayRule(RuleBase):
    """Track in-flight file edits, PR events, and periodic relay state syncs."""

    def __init__(
        self,
        topology: TopologyConfig,
        state: SessionState,
        relay_dir: Path | None = None,
        role: str = "alpha",
    ) -> None:
        super().__init__(topology)
        self._state = state
        self.relay_dir = relay_dir or DEFAULT_RELAY_DIR
        self.role = role
        self.relay_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def write_relay_status(
        self,
        event_type: str = "sync",
        pr_event: dict[str, Any] | None = None,
    ) -> None:
        """Write the current relay status YAML for peer sessions to read."""
        status: dict[str, Any] = {
            "session_id": self._state.session_id,
            "role": self.role,
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,
            "in_flight_files": sorted(self._state.in_flight_files),
        }
        if pr_event:
            status["pr_event"] = pr_event
        status_path = self.relay_dir / f"{self.role}-status.yaml"
        try:
            status_path.write_text(yaml.dump(status, default_flow_style=False))
            self._state.last_relay_sync = datetime.now()
            log.debug("RelayRule: wrote relay status (%s)", event_type)
        except OSError:
            log.exception("RelayRule: failed to write relay status")

    def write_final_status(self) -> None:
        """Write a shutdown relay status (called on conductor exit)."""
        self.write_relay_status(event_type="shutdown")

    def check_peer_conflicts(self) -> list[str]:
        """Read peer YAML files and return file paths that overlap with in-flight files."""
        conflicts: list[str] = []
        if not self._state.in_flight_files:
            return conflicts

        for yaml_path in self.relay_dir.glob("*-status.yaml"):
            # Skip our own status file
            if yaml_path.name == f"{self.role}-status.yaml":
                continue
            try:
                raw = yaml.safe_load(yaml_path.read_text()) or {}
            except (OSError, yaml.YAMLError):
                log.debug("RelayRule: could not parse peer status %s", yaml_path.name)
                continue

            peer_files: set[str] = set(raw.get("in_flight_files", []))
            overlaps = self._state.in_flight_files & peer_files
            conflicts.extend(overlaps)

        return sorted(set(conflicts))

    # ------------------------------------------------------------------
    # RuleBase interface
    # ------------------------------------------------------------------

    def on_pre_tool_use(self, event: HookEvent) -> HookResponse | None:
        return None

    def on_post_tool_use(self, event: HookEvent) -> HookResponse | None:
        # Track in-flight files from edit/write tools
        if event.tool_name in _EDIT_TOOLS:
            file_path: str = event.tool_input.get("file_path", "")
            if file_path:
                self._state.in_flight_files.add(file_path)
                log.debug("RelayRule: tracking in-flight file %s", file_path)

        # Detect PR events in Bash output
        if event.tool_name == "Bash":
            output: str = event.user_message or ""
            pr_event = detect_pr_event(output)
            if pr_event:
                log.info(
                    "RelayRule: PR event detected — %s #%d",
                    pr_event["type"],
                    pr_event["pr_number"],
                )
                self.write_relay_status(event_type=f"pr_{pr_event['type']}", pr_event=pr_event)
                return None

        # Periodic sync — every 30 minutes
        if self._state.last_relay_sync is None or (
            datetime.now() - self._state.last_relay_sync >= RELAY_SYNC_INTERVAL
        ):
            self.write_relay_status(event_type="periodic")

        return None
