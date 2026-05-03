"""Audio-source-class taxonomy + private->public edge guard.

cc-task audio-audit-D-source-class-taxonomy Phase 0.

Audit Finding #1 was a private-to-L-12 leak from convention drift: the
``hapax-private-*`` naming convention was the only fence between operator-
private monitors and the public broadcast egress. A typo in a source name
or a copy-paste of a routing entry could route operator speech to the
livestream.

Auditor D's fix: declare each source's class explicitly in the topology
schema, and reject any edge from ``class="private"`` into ``class="public"``
at parse time AND at runtime (leak-guard daemon). This module ships the
typed taxonomy + the edge guard; Phase 1 wires it into
``shared/audio_topology.py`` and the leak-guard daemon.

Why factor it this way:
- The taxonomy itself is small (4 classes) and worth pinning standalone with
  exhaustive 4x4 edge tests.
- ``validate_no_private_to_public_edges`` is the load-bearing safety check;
  it must raise with explicit edge details (src class, src name, dst class,
  dst name) so a topology-yaml editor sees exactly which line offends.
- Phase 1 wraps this validator inside the Pydantic ``TopologyDescriptor``
  load path AND inside the leak-guard daemon's runtime check; the function
  itself is single-source-of-truth.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, get_args

AudioSourceClass = Literal["private", "public", "monitor", "unknown"]
"""The 4 audio-source classes.

- ``private``: operator-only signals that MUST NEVER reach public egress.
  Examples: room mic, contact mic, operator headset talkback.
- ``public``: signals safe to broadcast (music, narration TTS, public
  cuepoint stings).
- ``monitor``: derived monitor taps for telemetry/observability. Read-only;
  no edges OUT to anything except a metric collector.
- ``unknown``: classification not yet declared. Phase 1 migration sets this
  for any pre-existing source until each gets an explicit class. Edges
  involving ``unknown`` are flagged by the leak-guard daemon at runtime
  (refuse to broadcast through an unclassified source).
"""

ALL_AUDIO_SOURCE_CLASSES: tuple[AudioSourceClass, ...] = get_args(AudioSourceClass)
"""All values of ``AudioSourceClass`` for exhaustive tests + iteration."""


def is_private_to_public_edge(
    src_class: AudioSourceClass,
    dst_class: AudioSourceClass,
) -> bool:
    """Return True if the (src, dst) pair is the forbidden private->public
    leak. The leak-guard daemon and the parse-time validator both call this
    on every edge."""
    return src_class == "private" and dst_class == "public"


@dataclass(frozen=True)
class AudioEdgeRef:
    """Minimal edge reference passed to the validator.

    Phase 1's full-fat ``shared/audio_topology.Edge`` carries channel maps,
    timestamps, etc.; the validator only needs the four fields below to
    produce an actionable error message. The `Edge` model wraps this on
    its way to the validator.
    """

    src_name: str
    src_class: AudioSourceClass
    dst_name: str
    dst_class: AudioSourceClass


class PrivateToPublicEdgeError(ValueError):
    """Raised when an edge violates the private->public leak invariant.

    A distinct exception class lets the leak-guard daemon catch the runtime
    fence path without swallowing other ValueErrors from the validator.
    """


def validate_no_private_to_public_edges(edges: Iterable[AudioEdgeRef]) -> None:
    """Raise PrivateToPublicEdgeError on the first private->public edge.

    Phase 1 calls this from the Pydantic load path AND from the leak-guard
    daemon's runtime check. The error message names src_name + dst_name so
    a topology-yaml editor sees the exact offending pair.

    Iteration is single-pass: return after the first violation. Phase 1's
    leak-guard daemon may want to enumerate ALL violations in one error
    message; that's a small extension (collect into a list, raise at end)
    but Phase 0 keeps the simpler "fail loudly on first" semantic.
    """
    for edge in edges:
        if is_private_to_public_edge(edge.src_class, edge.dst_class):
            raise PrivateToPublicEdgeError(
                f"private->public leak: source {edge.src_name!r} (class=private) "
                f"-> sink {edge.dst_name!r} (class=public). "
                f"Per audit finding #1, private sources MUST NEVER edge into "
                f"public sinks. Reclassify the source, the sink, or remove the "
                f"edge."
            )
