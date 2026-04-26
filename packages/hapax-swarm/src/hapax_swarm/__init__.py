"""hapax-swarm — filesystem-as-bus multi-session coordination.

Public surface:

- :class:`RelayDir` — typed view over a relay directory tree.
- :class:`PeerYaml` — per-session ``{role}.yaml`` heartbeat file.
- :func:`claim_before_parallel_work` — atomic claim helper.
- :class:`CcTask` — markdown-with-frontmatter task SSOT.
- :func:`atomic_write_text` / :func:`atomic_write_yaml` — atomic writers.
"""

from __future__ import annotations

from hapax_swarm.atomic import atomic_write_text, atomic_write_yaml
from hapax_swarm.cc_task import CcTask, CcTaskStatus
from hapax_swarm.claim import ClaimConflict, claim_before_parallel_work
from hapax_swarm.peer import PeerYaml
from hapax_swarm.relay import RelayDir

__all__ = [
    "CcTask",
    "CcTaskStatus",
    "ClaimConflict",
    "PeerYaml",
    "RelayDir",
    "atomic_write_text",
    "atomic_write_yaml",
    "claim_before_parallel_work",
]

__version__ = "0.1.0"
