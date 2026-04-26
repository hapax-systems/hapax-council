"""Runner — parse cc-task frontmatter, dispatch decisions, atomically rewrite.

Orchestration layer: pulls REFUSED tasks from the active vault directory,
calls the pure evaluator, then commits the transition by rewriting
frontmatter via tmp+rename. Body of the cc-task markdown is preserved
verbatim — the runner only mutates the YAML header.

Refusal-brief integration is a stub here: ``_to_refusal_event`` adapts a
TransitionEvent to a RefusalEvent shape, ready to be wired into
``agents.refusal_brief.writer.append`` once the integration cc-task ships
the schema extension. Until then the stub returns the adapter dict, the
caller can opt in.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path

import yaml
from prometheus_client import Counter

from agents.refusal_brief import writer as refusal_brief_writer
from agents.refusal_brief.writer import REASON_MAX_CHARS, RefusalEvent
from agents.refused_lifecycle.evaluator import decide_transition  # re-exported
from agents.refused_lifecycle.state import (
    ProbeResult,
    RefusalHistoryEntry,
    RefusalTask,
    TransitionEvent,
)

log = logging.getLogger(__name__)

# Default vault location for active cc-task notes. Tests pass tmp_path.
DEFAULT_ACTIVE_DIR = Path(
    os.environ.get(
        "HAPAX_CC_TASK_ACTIVE_DIR",
        str(Path.home() / "Documents/Personal/20-projects/hapax-cc-tasks/active"),
    )
)

# Refusal cc-tasks live in BOTH active/ and closed/. When a refusal-brief
# ships, the cc-task moves to closed/ (status: done), but the constitutional
# refusal persists indefinitely — the substrate must continue evaluating it.
# Mirror SUBDIRS = ("active", "closed") from scripts/refused_lifecycle_classify.py.
_VAULT_SUBDIRS = ("active", "closed")


# Per-transition counter labelled with from_state, to_state, slug. Slug
# label is high-cardinality but bounded by the active cc-task set (~20).
transitions_total = Counter(
    "hapax_refused_lifecycle_transitions_total",
    "Refused-lifecycle state-machine transitions emitted by the runner.",
    ["from_state", "to_state", "slug"],
)


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Split a YAML-frontmatter markdown file into (metadata, body)."""
    if not text.startswith("---\n"):
        raise ValueError("missing opening --- frontmatter delimiter")
    rest = text[4:]
    end = rest.find("\n---\n")
    if end == -1:
        raise ValueError("missing closing --- frontmatter delimiter")
    fm_text = rest[:end]
    body = rest[end + len("\n---\n") :]
    metadata = yaml.safe_load(fm_text) or {}
    return metadata, body


def parse_frontmatter(path: Path) -> RefusalTask:
    """Parse a cc-task markdown file into a RefusalTask."""
    text = path.read_text(encoding="utf-8")
    metadata, _ = _split_frontmatter(text)

    history_raw = metadata.get("refusal_history") or []
    history = [RefusalHistoryEntry(**entry) for entry in history_raw]

    # Default to empty string when missing — `iter_refused_tasks` filters by
    # exact "REFUSED" match, so missing-status tasks are correctly excluded
    # from the substrate's evaluation set. Defaulting to "REFUSED" would mass-
    # mutate every legacy task that lacks the field.
    return RefusalTask(
        slug=path.stem,
        path=str(path),
        automation_status=metadata.get("automation_status", ""),
        refusal_reason=metadata.get("refusal_reason", ""),
        last_evaluated_at=metadata.get("last_evaluated_at"),
        next_evaluation_at=metadata.get("next_evaluation_at"),
        evaluation_trigger=metadata.get("evaluation_trigger") or [],
        evaluation_probe=metadata.get("evaluation_probe") or {},
        refusal_history=history,
        superseded_by=metadata.get("superseded_by"),
        acceptance_evidence=metadata.get("acceptance_evidence"),
    )


def _resolve_scan_dirs(scan_root: Path) -> list[Path]:
    """Return the list of directories to glob for cc-task markdown files.

    If ``scan_root`` is itself a vault-base (contains ``active/`` subdir),
    walk both ``active/`` and ``closed/`` so the substrate sees REFUSED
    cc-tasks regardless of whether their refusal-brief already shipped.
    Otherwise treat ``scan_root`` as a single dir of markdown files (used
    by tests + the legacy single-dir caller shape).
    """
    if (scan_root / "active").is_dir():
        return [scan_root / sub for sub in _VAULT_SUBDIRS if (scan_root / sub).is_dir()]
    return [scan_root]


def iter_refused_tasks(scan_root: Path = DEFAULT_ACTIVE_DIR) -> Iterator[RefusalTask]:
    """Yield REFUSED-status cc-tasks from the vault.

    ``scan_root`` may be either a vault base containing ``active/`` and
    ``closed/`` subdirs (production shape — both walked), or a single dir
    of markdown files (test shape). When the caller passes the legacy
    DEFAULT_ACTIVE_DIR pointing directly at ``active/``, the function
    auto-promotes to the vault base (parent dir) so closed/ is scanned
    too — this fixes the substrate-92%-dead bug where 39 closed REFUSED
    tasks were invisible.
    """
    if scan_root.name == "active" and scan_root.parent.is_dir():
        scan_root = scan_root.parent

    if not scan_root.exists():
        return

    for scan_dir in _resolve_scan_dirs(scan_root):
        for path in sorted(scan_dir.glob("*.md")):
            try:
                task = parse_frontmatter(path)
            except (ValueError, yaml.YAMLError) as exc:
                log.warning("skipping %s: %s", path, exc)
                continue
            if task.automation_status == "REFUSED":
                yield task


_PUBLIC_SAFE_PREFIXES = ("pub-bus-", "repo-pres-", "awareness-refused-")
_PRIVATE_PREFIXES = ("cold-contact-",)


def is_public_safe(slug: str) -> bool:
    """Classify a refusal-brief surface as safe for omg.lol weblog fanout.

    Cold-contact surfaces touch operator-personal-mail context and are
    always private. Pub-bus / repo-pres / awareness-refused surfaces are
    public per Refusal Brief Tier-3 policy. Conservative default: any
    unrecognised slug is treated as private.
    """
    if not slug:
        return False
    if any(slug.startswith(p) for p in _PRIVATE_PREFIXES):
        return False
    return any(slug.startswith(p) for p in _PUBLIC_SAFE_PREFIXES)


def _to_refusal_event(transition_event: TransitionEvent) -> RefusalEvent:
    """Adapt a TransitionEvent into the canonical RefusalEvent log shape."""
    return RefusalEvent(
        timestamp=transition_event.timestamp,
        axiom=", ".join(transition_event.trigger),
        surface=f"refused-lifecycle:{transition_event.cc_task_slug}",
        reason=transition_event.reason[:REASON_MAX_CHARS],
        public=is_public_safe(transition_event.cc_task_slug),
        transition=transition_event.transition,
        evidence_url=transition_event.evidence_url,
        cc_task_slug=transition_event.cc_task_slug,
    )


def apply_transition(
    path: Path,
    task: RefusalTask,
    event: TransitionEvent,
    now: datetime,
    *,
    refusal_log_path: Path | None = None,
) -> None:
    """Atomically commit a transition by rewriting frontmatter.

    Body after the closing ``---`` delimiter is preserved verbatim. Mutation
    rules per transition:

    - re-affirmed: append history, bump ``last_evaluated_at``, status unchanged
    - accepted: status → OFFERED, populate ``acceptance_evidence``, append history
    - regressed: status → REFUSED, preserve prior ``acceptance_evidence``,
      append history
    - removed: status → REMOVED, populate ``removed_reason``, append history
    """
    text = path.read_text(encoding="utf-8")
    metadata, body = _split_frontmatter(text)

    history = metadata.get("refusal_history") or []
    history.append(
        {
            "date": event.timestamp,
            "transition": event.transition,
            "reason": event.reason,
            "evidence_url": event.evidence_url,
        }
    )
    metadata["refusal_history"] = history
    metadata["last_evaluated_at"] = now

    # Round-trip evaluation_probe so watcher mutations (etag / last_lm /
    # last_fingerprint persisted by the structural watcher's
    # _persist_probe_state) survive the YAML rewrite. Without this the
    # next probe burns a full GET every cycle instead of a 304 fast-path.
    if task.evaluation_probe:
        metadata["evaluation_probe"] = task.evaluation_probe

    if event.transition == "accepted":
        metadata["automation_status"] = "OFFERED"
        metadata["acceptance_evidence"] = {
            "evidence_url": event.evidence_url,
            "accepted_at": now,
            "reason": event.reason,
        }
    elif event.transition == "regressed":
        metadata["automation_status"] = "REFUSED"
    elif event.transition == "removed":
        metadata["automation_status"] = "REMOVED"
        metadata["removed_reason"] = event.reason
    # re-affirmed: status unchanged

    new_text = "---\n" + yaml.safe_dump(metadata, sort_keys=False) + "---\n" + body
    tmp = path.with_suffix(f".md.tmp.{os.getpid()}")
    try:
        tmp.write_text(new_text, encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise

    transitions_total.labels(
        from_state=event.from_state, to_state=event.to_state, slug=task.slug
    ).inc()

    # Emit to the canonical refusal-brief log so transitions become first-
    # class log rows alongside axiom violations. Failures are logged and
    # swallowed inside the writer — refusal emission must never break the
    # transition-commit path.
    log_path = refusal_log_path or refusal_brief_writer.DEFAULT_LOG_PATH
    refusal_brief_writer.append(_to_refusal_event(event), log_path=log_path)


def tick(
    now: datetime,
    *,
    active_dir: Path = DEFAULT_ACTIVE_DIR,
    dispatch_probes: Callable[[RefusalTask], list[ProbeResult]] | None = None,
) -> list[TransitionEvent]:
    """One orchestration tick — iterate REFUSED tasks, dispatch, apply.

    ``dispatch_probes`` is the seam where Phase 3 watchers plug in. When
    None, all tasks re-affirm (no probes → conservative default per the
    evaluator).
    """
    events: list[TransitionEvent] = []
    for task in iter_refused_tasks(active_dir):
        if task.next_evaluation_at and task.next_evaluation_at > now:
            continue
        probes = dispatch_probes(task) if dispatch_probes else []
        event = decide_transition(task, probes)
        apply_transition(Path(task.path), task, event, now)
        events.append(event)
    return events


__all__ = [
    "DEFAULT_ACTIVE_DIR",
    "_to_refusal_event",
    "apply_transition",
    "decide_transition",
    "is_public_safe",
    "iter_refused_tasks",
    "parse_frontmatter",
    "tick",
    "transitions_total",
]
