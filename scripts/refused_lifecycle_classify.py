#!/usr/bin/env python3
"""Per-slug classification pass for the refused-lifecycle substrate.

Populates each currently-REFUSED cc-task's `evaluation_trigger`,
`evaluation_probe`, and `next_evaluation_at` from the hand-curated
classification table per spec §6. Idempotent — re-running on already-
classified files is a no-op.

Searches both `active/` and `closed/` subdirectories of the vault base
because most refusal-cc-tasks moved to closed/ when their refusal-briefs
shipped, but the constitutional refusal persists indefinitely.

Usage::

    uv run python scripts/refused_lifecycle_classify.py [--vault-base PATH]

Requires the schema-extension migration (#1609) to have run first so the
target frontmatter shape exists.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.sdlc_filesystem_transaction import (  # noqa: E402
    TaskNoteSnapshot,
    read_task_note_snapshot,
    replace_task_note_transactionally,
    task_note_transaction_context,
)

log = logging.getLogger(__name__)

DEFAULT_VAULT_BASE = Path.home() / "Documents/Personal/20-projects/hapax-cc-tasks"
SUBDIRS = ("active", "closed")

# Memory file used for constitutional probes (axiom + feedback registry).
_MEMORY_PATH = "~/.claude/projects/-home-hapax-projects/memory/MEMORY.md"
_AXIOM_REGISTRY_PATH = "~/projects/hapax-constitution/axioms/registry.yaml"


def _probe(
    *,
    url: str | None = None,
    conditional_path: str | None = None,
    depends_on_slug: str | None = None,
    lift_keywords: list[str] | None = None,
    lift_polarity: str = "present",
) -> dict:
    """Build a fully-populated evaluation_probe dict (all 8 keys present)."""
    return {
        "url": url,
        "conditional_path": conditional_path,
        "depends_on_slug": depends_on_slug,
        "lift_keywords": lift_keywords or [],
        "lift_polarity": lift_polarity,
        "last_etag": None,
        "last_lm": None,
        "last_fingerprint": None,
    }


# Hand-curated classification table per spec §6. Each entry encodes the
# trigger taxonomy, probe target, and lift-evaluation cadence for one
# REFUSED cc-task.
CLASSIFICATIONS: dict[str, dict] = {
    # ── Type-A (structural; weekly cadence) ────────────────────────────
    "pub-bus-bandcamp-upload-REFUSED": {
        "evaluation_trigger": ["structural"],
        "evaluation_probe": _probe(
            url="https://bandcamp.com/developer",
            lift_keywords=["upload", "POST /releases", "submission API"],
        ),
        "next_evaluation_offset_days": 7,
    },
    "pub-bus-discogs-submission-REFUSED": {
        "evaluation_trigger": ["structural"],
        "evaluation_probe": _probe(
            url="https://www.discogs.com/developers/",
            lift_keywords=["submission API", "automated"],
        ),
        "next_evaluation_offset_days": 7,
    },
    "pub-bus-rym-submission-REFUSED": {
        "evaluation_trigger": ["structural"],
        "evaluation_probe": _probe(
            url="https://rateyourmusic.com/development",
            lift_keywords=["api", "submission", "developer"],
        ),
        "next_evaluation_offset_days": 7,
    },
    "pub-bus-crossref-event-data-REFUSED": {
        "evaluation_trigger": ["structural"],
        "evaluation_probe": _probe(
            url="https://www.crossref.org/services/event-data/",
            lift_keywords=["available", "restored", "successor", "event-data v2"],
        ),
        "next_evaluation_offset_days": 7,
    },
    # ── Type-B (constitutional; monthly cadence) ──────────────────────
    "repo-pres-code-of-conduct-REFUSED": {
        "evaluation_trigger": ["constitutional"],
        "evaluation_probe": _probe(
            conditional_path=_AXIOM_REGISTRY_PATH,
            lift_keywords=["single_user"],
            lift_polarity="absent",
        ),
        "next_evaluation_offset_days": 30,
    },
    "cold-contact-email-last-resort": {
        "evaluation_trigger": ["constitutional"],
        "evaluation_probe": _probe(
            conditional_path=_MEMORY_PATH,
            lift_keywords=["feedback_full_automation_or_no_engagement"],
            lift_polarity="absent",
        ),
        "next_evaluation_offset_days": 30,
    },
    "cold-contact-public-archive-listserv": {
        "evaluation_trigger": ["constitutional"],
        "evaluation_probe": _probe(
            conditional_path=_MEMORY_PATH,
            lift_keywords=["feedback_full_automation_or_no_engagement"],
            lift_polarity="absent",
        ),
        "next_evaluation_offset_days": 30,
    },
    "awareness-refused-acknowledge-mark-read-affordances": {
        "evaluation_trigger": ["constitutional"],
        "evaluation_probe": _probe(
            conditional_path=_MEMORY_PATH,
            lift_keywords=["feedback_full_automation_or_no_engagement", "no_HITL"],
            lift_polarity="absent",
        ),
        "next_evaluation_offset_days": 30,
    },
    "awareness-refused-calendar-reminder-injection": {
        "evaluation_trigger": ["constitutional"],
        "evaluation_probe": _probe(
            conditional_path=_MEMORY_PATH,
            lift_keywords=["feedback_full_automation_or_no_engagement"],
            lift_polarity="absent",
        ),
        "next_evaluation_offset_days": 30,
    },
    "awareness-refused-email-digest-with-links": {
        "evaluation_trigger": ["constitutional"],
        "evaluation_probe": _probe(
            conditional_path=_MEMORY_PATH,
            lift_keywords=["feedback_full_automation_or_no_engagement"],
            lift_polarity="absent",
        ),
        "next_evaluation_offset_days": 30,
    },
    "awareness-refused-ntfy-action-buttons": {
        "evaluation_trigger": ["constitutional"],
        "evaluation_probe": _probe(
            conditional_path=_MEMORY_PATH,
            lift_keywords=["feedback_full_automation_or_no_engagement"],
            lift_polarity="absent",
        ),
        "next_evaluation_offset_days": 30,
    },
    "awareness-refused-operator-curated-filters": {
        "evaluation_trigger": ["constitutional"],
        "evaluation_probe": _probe(
            conditional_path=_MEMORY_PATH,
            lift_keywords=["feedback_full_automation_or_no_engagement"],
            lift_polarity="absent",
        ),
        "next_evaluation_offset_days": 30,
    },
    "awareness-refused-pending-review-inboxes": {
        "evaluation_trigger": ["constitutional"],
        "evaluation_probe": _probe(
            conditional_path=_MEMORY_PATH,
            lift_keywords=["feedback_no_operator_approval_waits"],
            lift_polarity="absent",
        ),
        "next_evaluation_offset_days": 30,
    },
    "awareness-refused-public-marketing-dashboards": {
        "evaluation_trigger": ["constitutional"],
        "evaluation_probe": _probe(
            conditional_path=_MEMORY_PATH,
            lift_keywords=[
                "project_academic_spectacle_strategy",
                "feedback_full_automation_or_no_engagement",
            ],
            lift_polarity="absent",
        ),
        "next_evaluation_offset_days": 30,
    },
    "awareness-refused-scheduled-summary-cadence": {
        "evaluation_trigger": ["constitutional"],
        "evaluation_probe": _probe(
            conditional_path=_MEMORY_PATH,
            lift_keywords=["feedback_no_operator_approval_waits"],
            lift_polarity="absent",
        ),
        "next_evaluation_offset_days": 30,
    },
    "awareness-refused-slack-discord-dm-bots": {
        "evaluation_trigger": ["constitutional"],
        "evaluation_probe": _probe(
            conditional_path=_MEMORY_PATH,
            lift_keywords=["feedback_full_automation_or_no_engagement"],
            lift_polarity="absent",
        ),
        "next_evaluation_offset_days": 30,
    },
    "awareness-refused-tile-tap-action": {
        "evaluation_trigger": ["constitutional"],
        "evaluation_probe": _probe(
            conditional_path=_MEMORY_PATH,
            lift_keywords=["feedback_full_automation_or_no_engagement"],
            lift_polarity="absent",
        ),
        "next_evaluation_offset_days": 30,
    },
    # ── Type-A+B (multi-classified) ───────────────────────────────────
    "cold-contact-alphaxiv-comments": {
        "evaluation_trigger": ["structural", "constitutional"],
        "evaluation_probe": _probe(
            url="https://www.alphaxiv.org/community-guidelines",
            conditional_path=_MEMORY_PATH,
            lift_keywords=["LLM-generated", "disallowed"],
            lift_polarity="present",
        ),
        "next_evaluation_offset_days": 7,
    },
}


def _split_frontmatter(text: str) -> tuple[dict, str] | None:
    if not text.startswith("---\n"):
        return None
    rest = text[4:]
    end = rest.find("\n---\n")
    if end == -1:
        return None
    fm = yaml.safe_load(rest[:end]) or {}
    body = rest[end + len("\n---\n") :]
    return fm, body


def _transactional_write(path: Path, fm: dict, body: str, snapshot: TaskNoteSnapshot) -> None:
    text = "---\n" + yaml.safe_dump(fm, sort_keys=False) + "---\n" + body
    vault_root, cache_dir = task_note_transaction_context(path)
    replace_task_note_transactionally(
        path,
        expected_content=snapshot.content,
        content=text.encode("utf-8"),
        expected_mode=snapshot.mode,
        cache_dir=cache_dir,
        vault_root=vault_root,
    )


def _find_slug(vault_base: Path, slug: str) -> Path | None:
    """Locate a slug's cc-task file in active/ or closed/."""
    for sub in SUBDIRS:
        candidate = vault_base / sub / f"{slug}.md"
        if candidate.exists():
            return candidate
    return None


def _classification_matches(fm: dict, classification: dict, now: datetime) -> bool:
    """Idempotency check: is the file already classified per the table?"""
    if fm.get("evaluation_trigger") != classification["evaluation_trigger"]:
        return False
    expected_probe = classification["evaluation_probe"]
    actual_probe = fm.get("evaluation_probe") or {}
    for key in ("url", "conditional_path", "lift_keywords", "lift_polarity"):
        if actual_probe.get(key) != expected_probe.get(key):
            return False
    return True


def classify(vault_base: Path, now: datetime) -> list[Path]:
    """Apply classification to every slug in the table; return modified paths."""
    modified: list[Path] = []
    for slug, classification in CLASSIFICATIONS.items():
        path = _find_slug(vault_base, slug)
        if path is None:
            log.warning("Classification target missing: %s", slug)
            continue

        try:
            snapshot = read_task_note_snapshot(path)
            text = snapshot.content.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            log.warning("Could not read %s", path)
            continue

        split = _split_frontmatter(text)
        if split is None:
            log.warning("Malformed frontmatter: %s", path)
            continue
        fm, body = split

        if _classification_matches(fm, classification, now):
            continue  # already classified; idempotent skip

        fm["evaluation_trigger"] = classification["evaluation_trigger"]
        fm["evaluation_probe"] = classification["evaluation_probe"]
        next_eval = now + timedelta(days=classification["next_evaluation_offset_days"])
        fm["next_evaluation_at"] = next_eval.isoformat()

        _transactional_write(path, fm, body, snapshot)
        modified.append(path)

    return modified


def _print_census() -> None:
    type_a = sum(1 for c in CLASSIFICATIONS.values() if c["evaluation_trigger"] == ["structural"])
    type_b = sum(
        1 for c in CLASSIFICATIONS.values() if c["evaluation_trigger"] == ["constitutional"]
    )
    type_ab = sum(
        1
        for c in CLASSIFICATIONS.values()
        if set(c["evaluation_trigger"]) == {"structural", "constitutional"}
    )
    probe_urls = sum(
        1 for c in CLASSIFICATIONS.values() if c["evaluation_probe"]["url"] is not None
    )
    constitutional_paths = {
        c["evaluation_probe"]["conditional_path"]
        for c in CLASSIFICATIONS.values()
        if c["evaluation_probe"]["conditional_path"] is not None
    }
    print(f"Type-A (structural):              {type_a:>3} slugs")
    print(f"Type-B (constitutional):          {type_b:>3} slugs")
    print(f"Type-A+B (multi-classified):      {type_ab:>3} slugs")
    print(f"Total:                            {len(CLASSIFICATIONS):>3} slugs")
    print(f"Probe URLs configured:            {probe_urls:>3}")
    print(f"Constitutional paths watched:     {len(constitutional_paths):>3}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault-base", type=Path, default=DEFAULT_VAULT_BASE)
    args = parser.parse_args(argv)

    now = datetime.now(UTC)
    modified = classify(args.vault_base, now)
    print(f"Classified: {len(modified):>3} files")
    _print_census()
    return 0


if __name__ == "__main__":
    sys.exit(main())
