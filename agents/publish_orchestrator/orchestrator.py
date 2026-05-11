"""Approval-gated inbox watcher + parallel surface fan-out.

Tail of ``~/hapax-state/publish/inbox/*.json``. Each ``PreprintArtifact``
JSON file represents one approved publication; ``surfaces_targeted``
enumerates the publisher slugs that should receive the artifact in
parallel.

Per-artifact-per-surface result lands at
``~/hapax-state/publish/log/{slug}.{surface}.json`` with one of:
``ok | denied | auth_error | no_credentials | rate_limited | deferred |
error | surface_unwired``. Once every surface reaches a terminal state,
the artifact moves to ``published/`` only when every surface returned
``ok``. Non-retryable failures (``denied``, ``auth_error``,
``no_credentials``, ``error``, ``dropped``, ``surface_unwired``) move
the artifact to ``failed/``; ``deferred`` and ``rate_limited`` stay in
``inbox/`` for retry.

``no_credentials`` is terminal but not published: missing env vars are
configuration state the publisher can't recover from itself; re-dispatching
every tick would loop forever. Operator sets the env var and re-drops a
fresh artifact if they want it published.

## Surface registry

A module-level dict maps surface slug → ``"module.path:entry_point"``.
Each Phase 1/2/3 surface ticket adds its entry. Missing entries are
treated as ``surface_unwired`` (logged + counter, not blocking).

## Concurrency

Per-tick, all surfaces of all artifacts dispatch via a single
``ThreadPoolExecutor(max_workers=8)``. Bounded; no per-artifact
fan-out.

## Constitutional alignment

Operator's role is to move a draft from ``draft/`` to ``inbox/`` once;
all dispatch is autonomous thereafter. The orchestrator never executes
operator-side actions (no email send, no manual login, no captcha
solve).
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import signal as _signal
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import ClassVar

from prometheus_client import REGISTRY, CollectorRegistry, Counter

from agents.publication_bus.surface_registry import dispatch_registry
from shared.preprint_artifact import (
    INBOX_DIR_NAME,
    ApprovalState,
    PreprintArtifact,
)
from shared.publication_artifact_public_event import (
    PublicationArtifactEventStage,
    build_publication_artifact_public_event,
)
from shared.publication_hardening.review import (
    ReviewPass,
    ReviewReport,
    attach_review_report_to_frontmatter,
)
from shared.research_vehicle_public_event import ResearchVehiclePublicEvent

log = logging.getLogger(__name__)

DEFAULT_TICK_S = 30.0
METRICS_PORT_DEFAULT = 9510
PUBLIC_EVENT_PATH = Path(
    os.environ.get(
        "HAPAX_RESEARCH_VEHICLE_PUBLIC_EVENT_PATH",
        "/dev/shm/hapax-public-events/events.jsonl",
    )
)

_SUCCESS_RESULTS = frozenset({"ok"})
"""Only these results count as a real publication."""

_TERMINAL_RESULTS = frozenset(
    {
        "ok",
        "denied",
        "auth_error",
        "no_credentials",
        "error",
        "dropped",
        "surface_unwired",
    }
)
"""Terminal states stop retry for a surface.

``deferred`` and ``rate_limited`` are NOT terminal. Terminal failure
states move the artifact to ``failed/``, never ``published/``.
"""


# ── Surface registry ────────────────────────────────────────────────

# CONSTITUTIONAL GATE — full-automation-or-no-engagement (operator
# directive 2026-04-25):
#
# Only register surfaces whose entire publication + post-publication
# engagement path is FULL-Hapax-automated end-to-end. Any surface
# requiring HUMAN intervention at ANY step — including post-publish
# reply cycles, captcha gates, peer-review human-loops, identity
# verification beyond a one-time bootstrap, in-person presentation,
# follow-back culture, or comment threads expecting authorial reply —
# is REFUSED, regardless of stated quality.
#
# "Operator just clicks once" = HUMAN_REQUIRED = REFUSE.
#
# Refused surfaces are not omissions; they are the dataset of the
# Refusal Brief (an Automation-Tractability Disclosure published as
# a standalone artifact). See:
#   - feedback_full_automation_or_no_engagement.md (auto-memory)
#   - feedback_co_publishing_auto_only_unsettled_contribution.md
#   - ~/Documents/Personal/30-areas/hapax/refusal-brief.md (Locus 2)
#   - ~/Documents/Personal/30-areas/hapax/manifesto.md §IV.5 (Locus 1)
#
# Before adding a new entry below, confirm the surface is FULL_AUTO
# per the 4-cluster audit (35 surfaces classified as of 2026-04-25,
# refresh on major-policy-event triggers). The audit dataset lives
# at ~/.cache/hapax/relay/inflections/20260425T17{0000,1500}Z-*.md.

SURFACE_REGISTRY: dict[str, str] = dispatch_registry()
"""Surface slug → ``"module.path:entry_point"`` import string.

The canonical authority is ``agents.publication_bus.surface_registry``.
REFUSED surfaces such as ``alphaxiv-comments`` have no dispatch entry
and therefore cannot be reached from the runtime orchestrator.

Each entry-point must be a callable
``(artifact: PreprintArtifact) -> str`` returning one of the result
strings (``ok | denied | auth_error | error | rate_limited | deferred
| dropped``).
"""


# ── Per-surface result ──────────────────────────────────────────────


@dataclass(frozen=True)
class SurfaceResult:
    """One per-surface dispatch outcome, persisted to
    ``~/hapax-state/publish/log/{slug}.{surface}.json``."""

    slug: str
    surface: str
    result: str
    timestamp: str
    artifact_fingerprint: str | None = None

    def is_terminal(self) -> bool:
        return self.result in _TERMINAL_RESULTS

    def to_dict(self) -> dict[str, str]:
        payload = {
            "slug": self.slug,
            "surface": self.surface,
            "result": self.result,
            "timestamp": self.timestamp,
        }
        if self.artifact_fingerprint is not None:
            payload["artifact_fingerprint"] = self.artifact_fingerprint
        return payload


# ── Orchestrator ────────────────────────────────────────────────────


class Orchestrator:
    """30s-tick approval-gated inbox watcher.

    Constructor parameters
    ----------------------
    state_root:
        Root of the ``publish/{inbox,draft,published,log}/`` layout.
        Defaults to ``$HAPAX_STATE`` env var or ``~/hapax-state``.
    surface_registry:
        Override for testing; production uses the module-level
        ``SURFACE_REGISTRY``.
    tick_s:
        Daemon-loop wakeup cadence. Defaults to 30s.
    max_workers:
        Thread-pool executor cap. Defaults to 8 (matches the
        capability-flesher spec).
    """

    METRIC_NAME: ClassVar[str] = "hapax_publish_orchestrator_dispatches_total"

    def __init__(
        self,
        *,
        state_root: Path | None = None,
        surface_registry: dict[str, str] | None = None,
        public_event_path: Path | None = PUBLIC_EVENT_PATH,
        review_pass: ReviewPass | None = None,
        registry: CollectorRegistry = REGISTRY,
        tick_s: float = DEFAULT_TICK_S,
        max_workers: int = 8,
    ) -> None:
        self._state_root = state_root or _default_state_root()
        self._surface_registry = (
            surface_registry if surface_registry is not None else SURFACE_REGISTRY
        )
        self._public_event_path = public_event_path
        self._review_pass = review_pass if review_pass is not None else ReviewPass()
        self._tick_s = max(1.0, tick_s)
        self._max_workers = max(1, max_workers)
        self._stop_evt = threading.Event()
        self._import_cache: dict[str, Callable[[PreprintArtifact], str]] = {}
        self._known_public_event_ids: set[str] | None = None

        self.dispatches_total = Counter(
            self.METRIC_NAME,
            "Per-artifact-per-surface dispatches, by outcome.",
            ["surface", "result"],
            registry=registry,
        )

    # ── Public API ────────────────────────────────────────────────

    def run_once(self) -> int:
        """Process all approved artifacts in inbox; return count handled."""
        inbox = self._state_root / INBOX_DIR_NAME
        if not inbox.exists():
            return 0
        handled = 0
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            for path in sorted(inbox.glob("*.json")):
                try:
                    artifact = self._load_artifact(path)
                except Exception:  # noqa: BLE001
                    log.exception("failed to load artifact at %s", path)
                    continue
                self._dispatch(artifact, pool=pool)
                handled += 1
        return handled

    def run_forever(self) -> None:
        for sig in (_signal.SIGTERM, _signal.SIGINT):
            try:
                _signal.signal(sig, lambda *_: self._stop_evt.set())
            except ValueError:
                pass

        log.info(
            "publish_orchestrator starting, state_root=%s tick=%.1fs max_workers=%d",
            self._state_root,
            self._tick_s,
            self._max_workers,
        )
        while not self._stop_evt.is_set():
            try:
                self.run_once()
            except Exception:  # noqa: BLE001
                log.exception("tick failed; continuing on next cadence")
            self._stop_evt.wait(self._tick_s)

    def stop(self) -> None:
        self._stop_evt.set()

    # ── Per-artifact dispatch ─────────────────────────────────────

    def _dispatch(self, artifact: PreprintArtifact, *, pool: ThreadPoolExecutor) -> None:
        """Fan out to every surface in ``artifact.surfaces_targeted``."""
        if not artifact.surfaces_targeted:
            log.warning("artifact %s has no surfaces_targeted; skipping", artifact.slug)
            return

        review = self._review_artifact(artifact)
        artifact.publication_review = review.to_frontmatter()
        self._attach_review_frontmatter(artifact, review)
        if not review.passes():
            self._withhold_for_review(artifact, review)
            return

        artifact_fingerprint = _artifact_fingerprint(artifact)
        self._record_public_event(
            artifact,
            artifact_fingerprint=artifact_fingerprint,
            stage="inbox",
        )

        # Existing log entries — preserve already-terminal results so
        # deferred re-runs only retry the deferred surfaces.
        prior_results: dict[str, str] = {}
        for surface in artifact.surfaces_targeted:
            log_path = artifact.log_path(surface, state_root=self._state_root)
            if log_path.exists():
                try:
                    record = json.loads(log_path.read_text())
                except (OSError, json.JSONDecodeError):
                    continue
                if record.get("artifact_fingerprint") == artifact_fingerprint:
                    result = record.get("result", "")
                    prior_results[surface] = result
                    if result in _TERMINAL_RESULTS:
                        self._record_public_event(
                            artifact,
                            artifact_fingerprint=artifact_fingerprint,
                            stage="surface_log",
                            surface=surface,
                            result=result,
                            source_path=log_path,
                            result_timestamp=_optional_str(record.get("timestamp")),
                        )

        # Dispatch only surfaces that are not already terminal.
        futures = {}
        for surface in artifact.surfaces_targeted:
            if prior_results.get(surface, "") in _TERMINAL_RESULTS:
                continue
            futures[surface] = pool.submit(self._dispatch_one, artifact, surface)

        # Collect results + persist log entries.
        for surface, future in futures.items():
            try:
                result = future.result(timeout=120.0)
            except Exception:  # noqa: BLE001
                log.exception("surface %s dispatch raised", surface)
                result = "error"
            self._record_result(
                artifact,
                surface,
                result,
                artifact_fingerprint=artifact_fingerprint,
            )

        # Final state check: did all surfaces reach terminal? If yes,
        # move the artifact to published/ only if every surface succeeded.
        all_terminal = True
        final_results: list[str] = []
        for surface in artifact.surfaces_targeted:
            log_path = artifact.log_path(surface, state_root=self._state_root)
            if not log_path.exists():
                all_terminal = False
                break
            try:
                record = json.loads(log_path.read_text())
            except (OSError, json.JSONDecodeError):
                all_terminal = False
                break
            if record.get("artifact_fingerprint") != artifact_fingerprint:
                all_terminal = False
                break
            result = record.get("result", "")
            final_results.append(result)
            if result not in _TERMINAL_RESULTS:
                all_terminal = False
                break

        if all_terminal:
            if all(result in _SUCCESS_RESULTS for result in final_results):
                self._move_to_published(artifact, artifact_fingerprint=artifact_fingerprint)
            else:
                self._move_to_failed(
                    artifact,
                    final_results,
                    artifact_fingerprint=artifact_fingerprint,
                )

    def _dispatch_one(self, artifact: PreprintArtifact, surface: str) -> str:
        """Resolve + invoke the publisher entry-point for ``surface``."""
        entry = self._resolve_entry_point(surface)
        if entry is None:
            return "surface_unwired"
        try:
            return entry(artifact)
        except Exception:  # noqa: BLE001
            log.exception("publisher %s raised for artifact %s", surface, artifact.slug)
            return "error"

    def _review_artifact(self, artifact: PreprintArtifact) -> ReviewReport:
        text = _artifact_review_text(artifact)
        return self._review_pass.review_text(
            text,
            author_model=_artifact_author_model(artifact),
            metadata={
                "slug": artifact.slug,
                "title": artifact.title,
                "source_path": artifact.source_path,
                "surfaces_targeted": artifact.surfaces_targeted,
            },
        )

    def _withhold_for_review(self, artifact: PreprintArtifact, review: ReviewReport) -> None:
        artifact.approval = ApprovalState.WITHHELD
        artifact.publication_review = review.to_frontmatter()
        draft = artifact.draft_path(state_root=self._state_root)
        inbox = artifact.inbox_path(state_root=self._state_root)
        draft.parent.mkdir(parents=True, exist_ok=True)
        draft.write_text(artifact.model_dump_json(indent=2))
        try:
            inbox.unlink()
        except FileNotFoundError:
            pass
        review_log = (
            self._state_root / "publish" / "log" / f"{artifact.slug}.cross-provider-review.json"
        )
        review_log.parent.mkdir(parents=True, exist_ok=True)
        review_log.write_text(
            json.dumps(
                {
                    "slug": artifact.slug,
                    "surface": "cross-provider-review",
                    "result": "operator_hold",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "overall_confidence": review.overall_confidence,
                    "flagged_issues": list(review.flagged_issues),
                },
                sort_keys=True,
            )
        )
        self.dispatches_total.labels(surface="cross-provider-review", result="operator_hold").inc()
        log.warning(
            "publication review held %s at %.2f: %s",
            artifact.slug,
            review.overall_confidence,
            "; ".join(review.flagged_issues),
        )

    def _attach_review_frontmatter(self, artifact: PreprintArtifact, review: ReviewReport) -> None:
        if not artifact.source_path:
            return
        source_path = Path(artifact.source_path).expanduser()
        if source_path.suffix.lower() not in {".md", ".markdown"}:
            return
        try:
            attached = attach_review_report_to_frontmatter(source_path, review)
        except Exception:  # noqa: BLE001 - frontmatter writeback must not block dispatch
            log.warning(
                "publication review frontmatter write failed for %s",
                source_path,
                exc_info=True,
            )
            return
        if not attached:
            log.warning("publication review frontmatter missing or malformed for %s", source_path)

    def _resolve_entry_point(self, surface: str) -> Callable[[PreprintArtifact], str] | None:
        """Cache imports per surface."""
        if surface in self._import_cache:
            return self._import_cache[surface]
        spec = self._surface_registry.get(surface)
        if spec is None:
            log.warning("surface %s not in registry — surface_unwired", surface)
            self._import_cache[surface] = None  # type: ignore[assignment]
            return None
        try:
            module_path, attr = spec.split(":", 1)
            module = importlib.import_module(module_path)
            entry = getattr(module, attr)
        except (ImportError, AttributeError, ValueError):
            log.exception("failed to resolve entry-point %s", spec)
            self._import_cache[surface] = None  # type: ignore[assignment]
            return None
        self._import_cache[surface] = entry
        return entry

    def _record_result(
        self,
        artifact: PreprintArtifact,
        surface: str,
        result: str,
        *,
        artifact_fingerprint: str,
    ) -> None:
        log_path = artifact.log_path(surface, state_root=self._state_root)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        record = SurfaceResult(
            slug=artifact.slug,
            surface=surface,
            result=result,
            timestamp=datetime.now(UTC).isoformat(),
            artifact_fingerprint=artifact_fingerprint,
        )
        log_path.write_text(json.dumps(record.to_dict()))
        self.dispatches_total.labels(surface=surface, result=result).inc()
        self._record_public_event(
            artifact,
            artifact_fingerprint=artifact_fingerprint,
            stage="surface_log",
            surface=surface,
            result=result,
            source_path=log_path,
            result_timestamp=record.timestamp,
        )

    def _load_artifact(self, path: Path) -> PreprintArtifact:
        return PreprintArtifact.model_validate_json(path.read_text())

    def _move_to_published(self, artifact: PreprintArtifact, *, artifact_fingerprint: str) -> None:
        artifact.mark_published()
        published = artifact.published_path(state_root=self._state_root)
        inbox = artifact.inbox_path(state_root=self._state_root)
        published.parent.mkdir(parents=True, exist_ok=True)
        published.write_text(artifact.model_dump_json(indent=2))
        try:
            inbox.unlink()
        except FileNotFoundError:
            pass
        log.info(
            "published %s; %d surfaces all-terminal",
            artifact.slug,
            len(artifact.surfaces_targeted),
        )
        self._record_public_event(
            artifact,
            artifact_fingerprint=artifact_fingerprint,
            stage="published",
            source_path=published,
        )

    def _move_to_failed(
        self,
        artifact: PreprintArtifact,
        results: list[str],
        *,
        artifact_fingerprint: str,
    ) -> None:
        artifact.mark_failed()
        failed = artifact.failed_path(state_root=self._state_root)
        inbox = artifact.inbox_path(state_root=self._state_root)
        failed.parent.mkdir(parents=True, exist_ok=True)
        failed.write_text(artifact.model_dump_json(indent=2))
        try:
            inbox.unlink()
        except FileNotFoundError:
            pass
        log.warning(
            "failed %s; terminal surface results=%s",
            artifact.slug,
            ",".join(results),
        )
        self._record_public_event(
            artifact,
            artifact_fingerprint=artifact_fingerprint,
            stage="failed",
            source_path=failed,
        )

    def _record_public_event(
        self,
        artifact: PreprintArtifact,
        *,
        artifact_fingerprint: str,
        stage: PublicationArtifactEventStage,
        surface: str | None = None,
        result: str | None = None,
        source_path: Path | None = None,
        result_timestamp: str | None = None,
    ) -> None:
        if self._public_event_path is None:
            return
        decision = build_publication_artifact_public_event(
            artifact,
            artifact_fingerprint=artifact_fingerprint,
            state_root=self._state_root,
            stage=stage,
            generated_at=datetime.now(UTC),
            source_path=source_path,
            surface=surface,
            result=result,
            result_timestamp=result_timestamp,
        )
        event = decision.public_event
        if event is None:
            log.warning(
                "publication artifact public-event refused for %s stage=%s: %s",
                artifact.slug,
                stage,
                ";".join(decision.notes),
            )
            return
        if self._public_event_already_written(event.event_id):
            return
        self._append_public_event(event)

    def _append_public_event(self, event: ResearchVehiclePublicEvent) -> None:
        if self._public_event_path is None:
            return
        try:
            self._public_event_path.parent.mkdir(parents=True, exist_ok=True)
            with self._public_event_path.open("a", encoding="utf-8") as fh:
                fh.write(event.to_json_line())
        except OSError:
            log.warning("publication artifact public-event write failed", exc_info=True)
            return
        if self._known_public_event_ids is not None:
            self._known_public_event_ids.add(event.event_id)

    def _public_event_already_written(self, event_id: str) -> bool:
        if self._public_event_path is None:
            return True
        if self._known_public_event_ids is None:
            self._known_public_event_ids = _load_public_event_ids(self._public_event_path)
        return event_id in self._known_public_event_ids


# ── Helpers ─────────────────────────────────────────────────────────


def _default_state_root() -> Path:
    """Resolve ``$HAPAX_STATE`` or fall back to ``~/hapax-state``."""
    env = os.environ.get("HAPAX_STATE")
    if env:
        return Path(env)
    return Path.home() / "hapax-state"


def _artifact_fingerprint(artifact: PreprintArtifact) -> str:
    """Fingerprint fields that define a surface publication attempt.

    The same slug can be intentionally republished after a correction.
    Approval timestamps are excluded so a no-content-change requeue can
    reuse terminal per-surface results, while title/body/metadata changes
    force a fresh dispatch.
    """

    payload = artifact.model_dump(mode="json")
    relevant = {
        key: payload.get(key)
        for key in (
            "slug",
            "title",
            "abstract",
            "body_md",
            "body_html",
            "doi",
            "co_authors",
            "surfaces_targeted",
            "attribution_block",
            "embed_image_url",
        )
    }
    encoded = json.dumps(relevant, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def _artifact_review_text(artifact: PreprintArtifact) -> str:
    return "\n\n".join(
        part
        for part in (
            f"# {artifact.title}",
            artifact.abstract,
            artifact.attribution_block,
            artifact.body_md,
            artifact.body_html,
        )
        if part
    )


def _artifact_author_model(artifact: PreprintArtifact) -> str | None:
    if artifact.author_model:
        return artifact.author_model
    names = {author.name.lower() for author in artifact.co_authors}
    aliases = {author.alias.lower() for author in artifact.co_authors if author.alias}
    if "claude code" in names or "claude-code" in aliases:
        return "claude-code"
    return None


def _load_public_event_ids(path: Path) -> set[str]:
    ids: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ids
    for raw in lines:
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and isinstance(item.get("event_id"), str):
            ids.add(item["event_id"])
    return ids


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


__all__ = [
    "DEFAULT_TICK_S",
    "METRICS_PORT_DEFAULT",
    "Orchestrator",
    "PUBLIC_EVENT_PATH",
    "SURFACE_REGISTRY",
    "SurfaceResult",
    "_artifact_fingerprint",
    "_artifact_review_text",
]
