"""Cross-run lesson accumulation for the demo eval pipeline.

Persists proven corrections (adjustments that led to passing runs) in a YAML
file so future runs start with better defaults.  No LLM calls, no Qdrant,
no Pydantic — pure stdlib + PyYAML.
"""

from __future__ import annotations

import copy
import os
import tempfile
from datetime import date
from pathlib import Path

import yaml
from typing_extensions import TypedDict

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


class Lesson(TypedDict):
    text: str  # imperative, prompt-ready string
    success_count: int  # how many passing runs confirmed this
    added: str  # ISO date


LessonStore = dict[str, list[Lesson]]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LESSONS_PATH: Path = (
    Path(__file__).resolve().parent.parent.parent / "profiles" / "demo-lessons.yaml"
)
MAX_LESSONS_PER_ARCHETYPE: int = 20
KNOWN_ARCHETYPES: tuple[str, ...] = (
    "family",
    "technical-peer",
    "leadership",
    "team-member",
)

_HEADER = "# Demo lesson store — auto-managed by demo_eval pipeline\n# Do not edit manually\n"

# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def _is_valid_lesson(obj: object) -> bool:
    """Return True if *obj* looks like a well-formed Lesson dict."""
    if not isinstance(obj, dict):
        return False
    return (
        isinstance(obj.get("text"), str)
        and isinstance(obj.get("success_count"), int)
        and isinstance(obj.get("added"), str)
    )


def load_lessons(path: Path | None = None) -> LessonStore:
    """Load the lesson store from *path* (default ``LESSONS_PATH``).

    Returns an empty dict when the file is missing or contains invalid YAML.
    Malformed individual entries are silently dropped.
    """
    target = path or LESSONS_PATH
    try:
        raw = target.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
        if not isinstance(data, dict):
            return {}
        # Validate structure — drop malformed entries
        store: LessonStore = {}
        for key, lessons in data.items():
            if not isinstance(key, str) or not isinstance(lessons, list):
                continue
            valid = [entry for entry in lessons if _is_valid_lesson(entry)]
            if valid:
                store[key] = valid
        return store
    except (OSError, yaml.YAMLError):
        return {}


def save_lessons(store: LessonStore, path: Path | None = None) -> None:
    """Atomically write *store* to *path* (default ``LESSONS_PATH``).

    Uses a temp file + ``os.replace`` so readers never see a partial write.
    """
    target = path or LESSONS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)

    body = yaml.dump(dict(store), default_flow_style=False, sort_keys=True)
    content = _HEADER + body

    fd = tempfile.NamedTemporaryFile(
        mode="w",
        dir=str(target.parent),
        suffix=".tmp",
        delete=False,
        encoding="utf-8",
    )
    try:
        fd.write(content)
        fd.flush()
        os.fsync(fd.fileno())
        fd.close()
        os.replace(fd.name, str(target))
    except BaseException:
        fd.close()
        try:
            os.unlink(fd.name)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def extract_lessons(result: DemoEvalResult) -> list[str]:  # noqa: F821 — forward ref
    """Return prompt-ready lesson strings from a *passing* eval result.

    Only results that needed more than one iteration (i.e. self-healing
    actually fired) produce lessons.  First-iteration passes and failing
    runs return ``[]``.
    """
    from agents.demo_models import DemoEvalResult  # local import — avoid circular

    if not isinstance(result, DemoEvalResult):
        return []
    if not result.passed:
        return []
    if result.iterations <= 1:
        return []

    raw = result.final_report.adjustments_applied or []
    return [line.strip() for line in raw if line and line.strip()]


# ---------------------------------------------------------------------------
# Accumulation (pure)
# ---------------------------------------------------------------------------


def accumulate_lessons(
    store: LessonStore,
    archetype: str,
    new_lessons: list[str],
) -> LessonStore:
    """Merge *new_lessons* into *store* for *archetype*, returning a **new** store.

    * Exact-text duplicates get their ``success_count`` bumped.
    * Genuinely new entries start at ``success_count=1``.
    * If the archetype exceeds ``MAX_LESSONS_PER_ARCHETYPE``, the oldest
      entries (by ``added`` date, then list position) are dropped.
    """
    out: LessonStore = copy.deepcopy(store)

    if not new_lessons:
        return out

    existing = out.get(archetype, [])
    text_index: dict[str, int] = {l["text"]: i for i, l in enumerate(existing)}

    today = date.today().isoformat()

    for text in new_lessons:
        text = text.strip()
        if not text:
            continue
        if text in text_index:
            existing[text_index[text]]["success_count"] += 1
        else:
            entry: Lesson = {
                "text": text,
                "success_count": 1,
                "added": today,
            }
            existing.append(entry)
            text_index[text] = len(existing) - 1

    # Prune to MAX_LESSONS_PER_ARCHETYPE — drop oldest first.
    if len(existing) > MAX_LESSONS_PER_ARCHETYPE:
        # Sort by (added date, original position) ascending to identify oldest.
        indexed = list(enumerate(existing))
        indexed.sort(key=lambda pair: (pair[1]["added"], pair[0]))
        # Keep only the newest MAX entries.
        keep_set = {pair[0] for pair in indexed[len(existing) - MAX_LESSONS_PER_ARCHETYPE :]}
        existing = [l for i, l in enumerate(existing) if i in keep_set]

    out[archetype] = existing
    return out


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_lessons_block(lessons: list[Lesson]) -> str:
    """Format *lessons* into a markdown block suitable for prompt injection.

    Returns ``""`` when *lessons* is empty.
    """
    if not lessons:
        return ""

    lines: list[str] = ["## LESSONS FROM PRIOR RUNS", ""]
    for lesson in lessons:
        suffix = f" (confirmed {lesson['success_count']}x)" if lesson["success_count"] > 1 else ""
        lines.append(f"- {lesson['text']}{suffix}")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------


def load_lessons_for_archetype(
    archetype: str,
    path: Path | None = None,
) -> list[Lesson]:
    """Load lessons and return only those for *archetype*."""
    return load_lessons(path).get(archetype, [])
