"""Autonomous YouTube Content-ID detection watcher.

Polls ``liveBroadcasts.list`` + ``videos.list`` against the operator's
sub-channel OAuth and surfaces any field change as a ``CompositionalImpingement``
on the daimonion bus, plus an ntfy alert for high-salience kinds.

Spec: ``~/Documents/Personal/20-projects/hapax-cc-tasks/active/ytb-006-content-id-watcher.md``
Decision (alpha A2): standalone daemon. Loose-couples to Ring 3 egress
kill-switch via the ``egress.youtube_*`` impingement family rather than
direct attachment.
"""

from agents.content_id_watcher.change_detector import ChangeEvent, detect_changes
from agents.content_id_watcher.salience import HIGH_SALIENCE_KINDS, SALIENCE_TABLE
from agents.content_id_watcher.state import WatcherState

__all__ = [
    "HIGH_SALIENCE_KINDS",
    "SALIENCE_TABLE",
    "ChangeEvent",
    "WatcherState",
    "detect_changes",
]
