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
import re
import signal as _signal
import threading
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import ClassVar

import yaml
from prometheus_client import REGISTRY, CollectorRegistry, Counter

from agents.publication_bus.surface_registry import dispatch_registry
from shared.preprint_artifact import (
    INBOX_DIR_NAME,
    ApprovalState,
    PreprintArtifact,
)
from shared.public_gate_receipts import public_gate_receipt_value_present
from shared.publication_artifact_public_event import (
    PublicationArtifactEventStage,
    build_publication_artifact_public_event,
)
from shared.publication_hardening.egress_safety import (
    EgressDecision,
    EgressSafetyEnvelope,
)
from shared.publication_hardening.gate import (
    PublicationGateChildResult,
    PublicationGateDecision,
    PublicationGateResult,
    PublicationHardeningGate,
    publication_gate_fingerprint,
)
from shared.publication_hardening.review import ReviewPass
from shared.research_vehicle_public_event import ResearchVehiclePublicEvent

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TICK_S = 30.0
METRICS_PORT_DEFAULT = 9510
FANOUT_SURFACE_IDS = frozenset({"omg-lol-weblog-bearer-fanout"})
PUBLICATION_BASELINE_REQUIRED_GATES = (
    "source_artifact_public_safe",
    "source_refs_present",
    "rights_privacy_redaction_pass",
    "target_surface_allowlist_pass",
    "claim_review_current",
    "no_direct_public_egress",
)
PUBLICATION_FANOUT_REQUIRED_GATES = (
    *PUBLICATION_BASELINE_REQUIRED_GATES,
    "fanout_loop_prevention_present",
)
PUBLIC_GATE_RECEIPT_ROOTS = (
    Path.home() / ".cache" / "hapax" / "relay" / "receipts",
    REPO_ROOT / "docs" / "research" / "evidence",
)
PUBLICATION_SAFE_SEGMENT_RE = re.compile(r"\A[a-z0-9][a-z0-9_.-]{0,119}\Z")
PUBLICATION_SOURCE_PATH_ROOTS = (
    Path.home() / "Documents" / "Personal",
    REPO_ROOT / "docs",
)
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
    publication_gate_decision: str | None = None
    publication_gate_fingerprint: str | None = None

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
        if self.publication_gate_decision is not None:
            payload["publication_gate_decision"] = self.publication_gate_decision
        if self.publication_gate_fingerprint is not None:
            payload["publication_gate_fingerprint"] = self.publication_gate_fingerprint
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
        hardening_gate: PublicationHardeningGate | None = None,
        egress_envelope: EgressSafetyEnvelope | None = None,
        public_gate_receipt_roots: tuple[Path, ...] | None = None,
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
        self._hardening_gate = (
            hardening_gate
            if hardening_gate is not None
            else PublicationHardeningGate(review_pass=self._review_pass)
        )
        self._egress_envelope = egress_envelope or EgressSafetyEnvelope()
        self._public_gate_receipt_roots = (
            tuple(public_gate_receipt_roots)
            if public_gate_receipt_roots is not None
            else (self._state_root / "public-gate-receipts", *PUBLIC_GATE_RECEIPT_ROOTS)
        )
        self._source_path_roots = tuple(
            root.expanduser().resolve()
            for root in (self._state_root, *PUBLICATION_SOURCE_PATH_ROOTS)
        )
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
        egress_check = self._egress_envelope.check()
        if egress_check.decision == EgressDecision.KILL_SWITCHED:
            log.warning("egress kill switch active; skipping tick")
            self.dispatches_total.labels(surface="__egress__", result="kill_switched").inc()
            return 0
        if egress_check.decision == EgressDecision.RATE_LIMITED:
            log.info(
                "egress rate limited (%d/%d); deferring",
                egress_check.rate_window_count,
                egress_check.rate_limit,
            )
            self.dispatches_total.labels(surface="__egress__", result="rate_limited").inc()
            return 0

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
                envelope_findings = self._inbox_artifact_envelope_findings(artifact)
                if envelope_findings:
                    self._quarantine_invalid_inbox_artifact(path, artifact, envelope_findings)
                    handled += 1
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

        receipt_gate_result = self._public_gate_receipts_gate_result(artifact)
        receipt_child = receipt_gate_result.child_results[0]
        if receipt_gate_result.decision != PublicationGateDecision.PASS:
            artifact.publication_gate_result = receipt_gate_result.to_frontmatter()
            artifact.publication_review = None
            self._attach_gate_frontmatter(artifact)
            self._withhold_for_gate(artifact, receipt_gate_result)
            return

        gate_result = self._hardening_gate.evaluate(artifact)
        gate_result = self._with_public_gate_receipts_child(
            artifact,
            gate_result,
            receipt_child=receipt_child,
        )
        artifact.publication_gate_result = gate_result.to_frontmatter()
        artifact.publication_review = gate_result.review_report
        self._attach_gate_frontmatter(artifact)
        if gate_result.decision == PublicationGateDecision.HOLD:
            self._withhold_for_gate(artifact, gate_result)
            return
        if gate_result.decision == PublicationGateDecision.REJECT:
            self._reject_for_gate(artifact, gate_result)
            return

        gate_fingerprint = publication_gate_fingerprint(gate_result)
        self._record_gate_result(
            artifact,
            gate_result,
            result="operator_overridden_hold"
            if gate_result.decision == PublicationGateDecision.OPERATOR_OVERRIDDEN_HOLD
            else "ok",
        )
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
                publication_gate_decision=gate_result.decision.value,
                publication_gate_fingerprint=gate_fingerprint,
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

    def _with_public_gate_receipts_child(
        self,
        artifact: PreprintArtifact,
        gate_result: PublicationGateResult,
        *,
        receipt_child: PublicationGateChildResult | None = None,
    ) -> PublicationGateResult:
        receipt_child = receipt_child or self._public_gate_receipts_child(artifact)
        child_results = (*gate_result.child_results, receipt_child)
        decision = gate_result.decision
        override = gate_result.override
        flagged_issues = gate_result.flagged_issues
        if receipt_child.decision != PublicationGateDecision.PASS:
            flagged_issues = (
                *flagged_issues,
                *(f"{receipt_child.name}: {finding}" for finding in receipt_child.findings),
            )
            if decision != PublicationGateDecision.REJECT:
                decision = PublicationGateDecision.HOLD
                override = None

        return PublicationGateResult(
            decision=decision,
            generated_at=gate_result.generated_at,
            child_results=child_results,
            flagged_issues=flagged_issues,
            override=override
            if decision == PublicationGateDecision.OPERATOR_OVERRIDDEN_HOLD
            else None,
            review_report=gate_result.review_report,
        )

    def _public_gate_receipts_child(
        self,
        artifact: PreprintArtifact,
    ) -> PublicationGateChildResult:
        required = _required_publication_gate_receipts(artifact.surfaces_targeted)
        receipts, error = _artifact_publication_gate_receipts(artifact)
        bindings = _publication_gate_receipt_bindings(artifact)
        findings = (error,) if error is not None else ()
        missing = tuple(
            gate
            for gate in required
            if not public_gate_receipt_value_present(
                receipts.get(gate),
                expected_gate=gate,
                roots=self._public_gate_receipt_roots,
                bindings=bindings,
            )
        )
        if missing:
            findings = (
                *findings,
                "publication_gate_receipts missing or invalid required receipt refs: "
                + ", ".join(missing)
                + "; next action: hold the artifact until durable public-gate receipt refs "
                "bound to artifact_slug, artifact_fingerprint, and target_surfaces are recorded",
            )

        if findings:
            return PublicationGateChildResult(
                name="public_gate_receipts",
                decision=PublicationGateDecision.HOLD,
                findings=findings,
            )

        return PublicationGateChildResult(
            name="public_gate_receipts",
            decision=PublicationGateDecision.PASS,
            evidence_refs=tuple(str(receipts[gate]) for gate in required),
        )

    def _public_gate_receipts_gate_result(
        self,
        artifact: PreprintArtifact,
    ) -> PublicationGateResult:
        receipt_child = self._public_gate_receipts_child(artifact)
        decision = PublicationGateDecision.PASS
        flagged_issues: tuple[str, ...] = ()
        if receipt_child.decision != PublicationGateDecision.PASS:
            decision = PublicationGateDecision.HOLD
            flagged_issues = tuple(
                f"{receipt_child.name}: {finding}" for finding in receipt_child.findings
            )
        return PublicationGateResult(
            decision=decision,
            generated_at=datetime.now(UTC).isoformat(),
            child_results=(receipt_child,),
            flagged_issues=flagged_issues,
        )

    def _withhold_for_gate(
        self,
        artifact: PreprintArtifact,
        gate_result: PublicationGateResult,
    ) -> None:
        artifact.approval = ApprovalState.WITHHELD
        artifact.publication_gate_result = gate_result.to_frontmatter()
        draft = artifact.draft_path(state_root=self._state_root)
        inbox = artifact.inbox_path(state_root=self._state_root)
        draft.parent.mkdir(parents=True, exist_ok=True)
        draft.write_text(artifact.model_dump_json(indent=2))
        try:
            inbox.unlink()
        except FileNotFoundError:
            pass
        self._record_gate_result(artifact, gate_result, result="operator_hold")
        self.dispatches_total.labels(
            surface="publication-hardening-gate", result="operator_hold"
        ).inc()
        log.warning(
            "publication hardening gate held %s: %s",
            artifact.slug,
            "; ".join(gate_result.flagged_issues),
        )

    def _reject_for_gate(
        self,
        artifact: PreprintArtifact,
        gate_result: PublicationGateResult,
    ) -> None:
        artifact.mark_failed()
        artifact.publication_gate_result = gate_result.to_frontmatter()
        failed = artifact.failed_path(state_root=self._state_root)
        inbox = artifact.inbox_path(state_root=self._state_root)
        failed.parent.mkdir(parents=True, exist_ok=True)
        failed.write_text(artifact.model_dump_json(indent=2))
        try:
            inbox.unlink()
        except FileNotFoundError:
            pass
        self._record_gate_result(artifact, gate_result, result="rejected")
        self.dispatches_total.labels(surface="publication-hardening-gate", result="rejected").inc()
        log.warning(
            "publication hardening gate rejected %s: %s",
            artifact.slug,
            "; ".join(gate_result.flagged_issues),
        )

    def _attach_gate_frontmatter(self, artifact: PreprintArtifact) -> None:
        if not artifact.source_path:
            return
        source_path = Path(artifact.source_path).expanduser()
        if source_path.suffix.lower() not in {".md", ".markdown"}:
            return
        try:
            text = source_path.read_text(encoding="utf-8")
            if not text.startswith("---\n"):
                return
            end = text.find("\n---", 4)
            if end == -1:
                return
            frontmatter_text = text[4:end]
            body = text[end + 4 :]
            frontmatter = yaml.safe_load(frontmatter_text) or {}
            if not isinstance(frontmatter, dict):
                return
            if artifact.publication_review is not None:
                frontmatter["publication_review"] = artifact.publication_review
            if artifact.publication_gate_result is not None:
                frontmatter["publication_gate_result"] = artifact.publication_gate_result
            rendered = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---" + body
            tmp = source_path.with_suffix(source_path.suffix + ".tmp")
            tmp.write_text(rendered, encoding="utf-8")
            tmp.replace(source_path)
        except Exception:  # noqa: BLE001
            log.warning(
                "publication gate frontmatter write failed for %s",
                source_path,
                exc_info=True,
            )

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
        publication_gate_decision: str | None = None,
        publication_gate_fingerprint: str | None = None,
    ) -> None:
        log_path = artifact.log_path(surface, state_root=self._state_root)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        record = SurfaceResult(
            slug=artifact.slug,
            surface=surface,
            result=result,
            timestamp=datetime.now(UTC).isoformat(),
            artifact_fingerprint=artifact_fingerprint,
            publication_gate_decision=publication_gate_decision,
            publication_gate_fingerprint=publication_gate_fingerprint,
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

    def _record_gate_result(
        self,
        artifact: PreprintArtifact,
        gate_result: PublicationGateResult,
        *,
        result: str,
    ) -> None:
        log_path = (
            self._state_root
            / "publish"
            / "log"
            / f"{artifact.slug}.publication-hardening-gate.json"
        )
        log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "slug": artifact.slug,
            "surface": "publication-hardening-gate",
            "result": result,
            "timestamp": datetime.now(UTC).isoformat(),
            "publication_gate_decision": gate_result.decision.value,
            "publication_gate_fingerprint": publication_gate_fingerprint(gate_result),
            "flagged_issues": list(gate_result.flagged_issues),
            "child_results": [child.model_dump(mode="json") for child in gate_result.child_results],
        }
        log_path.write_text(json.dumps(record, sort_keys=True))

    def _load_artifact(self, path: Path) -> PreprintArtifact:
        return PreprintArtifact.model_validate_json(path.read_text())

    def _inbox_artifact_envelope_findings(self, artifact: PreprintArtifact) -> tuple[str, ...]:
        findings: list[str] = []
        if not _safe_publication_segment(artifact.slug):
            findings.append(
                "artifact slug must be a single safe path segment; next action: "
                "regenerate the artifact with a lowercase URL/file-safe slug"
            )
        unsafe_surfaces = [
            surface
            for surface in artifact.surfaces_targeted
            if not _safe_publication_segment(surface)
        ]
        if unsafe_surfaces:
            findings.append(
                "surfaces_targeted contains unsafe path segments: "
                + ", ".join(sorted(unsafe_surfaces))
                + "; next action: target registered publication surface ids only"
            )
        if artifact.source_path and not self._source_path_allowed(artifact.source_path):
            findings.append(
                "source_path must stay under the publish state root, Obsidian vault, "
                "or repository docs tree; next action: drop a vault/docs-backed artifact"
            )
        return tuple(findings)

    def _source_path_allowed(self, raw_path: str) -> bool:
        source_path = Path(raw_path).expanduser().resolve()
        return any(source_path.is_relative_to(root) for root in self._source_path_roots)

    def _quarantine_invalid_inbox_artifact(
        self,
        inbox_path: Path,
        artifact: PreprintArtifact,
        findings: tuple[str, ...],
    ) -> None:
        quarantine_slug = _quarantine_slug_for_path(inbox_path)
        child = PublicationGateChildResult(
            name="artifact_envelope",
            decision=PublicationGateDecision.REJECT,
            findings=findings,
        )
        gate_result = PublicationGateResult(
            decision=PublicationGateDecision.REJECT,
            generated_at=datetime.now(UTC).isoformat(),
            child_results=(child,),
            flagged_issues=tuple(f"{child.name}: {finding}" for finding in findings),
        )
        payload = artifact.model_dump(mode="json")
        payload["approval"] = ApprovalState.FAILED.value
        payload["publication_gate_result"] = gate_result.to_frontmatter()
        failed = self._state_root / "publish" / "failed" / f"{quarantine_slug}.json"
        failed.parent.mkdir(parents=True, exist_ok=True)
        failed.write_text(json.dumps(payload, indent=2, sort_keys=True))
        try:
            inbox_path.unlink()
        except FileNotFoundError:
            pass
        self._record_quarantine_gate_result(quarantine_slug, gate_result, result="rejected")
        self.dispatches_total.labels(surface="publication-hardening-gate", result="rejected").inc()
        log.warning(
            "publication inbox artifact quarantined at %s: %s",
            failed,
            "; ".join(gate_result.flagged_issues),
        )

    def _record_quarantine_gate_result(
        self,
        quarantine_slug: str,
        gate_result: PublicationGateResult,
        *,
        result: str,
    ) -> None:
        log_path = (
            self._state_root
            / "publish"
            / "log"
            / f"{quarantine_slug}.publication-hardening-gate.json"
        )
        log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "slug": quarantine_slug,
            "surface": "publication-hardening-gate",
            "result": result,
            "timestamp": datetime.now(UTC).isoformat(),
            "publication_gate_decision": gate_result.decision.value,
            "publication_gate_fingerprint": publication_gate_fingerprint(gate_result),
            "flagged_issues": list(gate_result.flagged_issues),
            "child_results": [child.model_dump(mode="json") for child in gate_result.child_results],
        }
        log_path.write_text(json.dumps(record, sort_keys=True))

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


def _required_publication_gate_receipts(surfaces: list[str]) -> tuple[str, ...]:
    selected = set(surfaces)
    if selected.intersection(FANOUT_SURFACE_IDS):
        return PUBLICATION_FANOUT_REQUIRED_GATES
    return PUBLICATION_BASELINE_REQUIRED_GATES


def _artifact_publication_gate_receipts(
    artifact: PreprintArtifact,
) -> tuple[dict[str, object], str | None]:
    context = artifact.publication_gate_context
    if not isinstance(context, Mapping):
        return (
            {},
            "publication_gate_context.publication_gate_receipts missing; next action: "
            "provide durable public-gate receipt refs keyed by gate id",
        )

    raw_receipts = context.get("publication_gate_receipts")
    if raw_receipts is None:
        return (
            {},
            "publication_gate_context.publication_gate_receipts missing; next action: "
            "provide durable public-gate receipt refs keyed by gate id",
        )
    if not isinstance(raw_receipts, Mapping):
        return (
            {},
            "publication_gate_context.publication_gate_receipts must be a mapping of gate "
            "id to receipt refs; next action: provide durable public-gate receipt refs "
            "keyed by gate id",
        )
    return {str(key): value for key, value in raw_receipts.items()}, None


def _publication_gate_receipt_bindings(artifact: PreprintArtifact) -> dict[str, object]:
    return {
        "artifact_slug": artifact.slug,
        "artifact_fingerprint": _artifact_fingerprint(artifact),
        "target_surfaces": tuple(sorted(artifact.surfaces_targeted)),
    }


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


def _safe_publication_segment(value: object) -> bool:
    return isinstance(value, str) and bool(PUBLICATION_SAFE_SEGMENT_RE.fullmatch(value))


def _quarantine_slug_for_path(path: Path) -> str:
    digest = sha256(str(path).encode()).hexdigest()[:16]
    return f"invalid-artifact-{digest}"


__all__ = [
    "DEFAULT_TICK_S",
    "METRICS_PORT_DEFAULT",
    "Orchestrator",
    "PUBLIC_EVENT_PATH",
    "PUBLIC_GATE_RECEIPT_ROOTS",
    "PUBLICATION_BASELINE_REQUIRED_GATES",
    "PUBLICATION_FANOUT_REQUIRED_GATES",
    "SURFACE_REGISTRY",
    "SurfaceResult",
    "_artifact_fingerprint",
]
