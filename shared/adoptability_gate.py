"""Adoptability teeth: typed refusals for garage-door rows and artifact releases.

ADOPTABILITY-DETERMINATION-20260916 §7 turned five determinations into gates. This
module is the single predicate every gate consults, so a rule lands in one place and
returns from one place:

* **lint** (A5) — a row tagged ``garage-door`` carries an ``adoptability:`` block with
  both receipt paths and the eleven acceptance fields; every row's frontmatter parses
  and its lists carry no unquoted ``key: value`` accident (the autoqueue and dispatcher
  skip unparseable rows silently, so unparseable is a refusal here, not a skip).
* **stage** (A2) — a ``garage-door`` row cannot leave ``offered`` / S1 without a
  prior-art receipt (two differently-shaped searches, BACKED/UNBACKED named) and a
  demand receipt naming who asked. BACKED-and-usable prior art converts the row to
  ``kind: contribution``.
* **release** (A1/A3/A4) — a ``garage-door`` row cannot release without a fresh,
  signed, passing adoptability receipt, and never with an install surface that binds
  an estate noun.

Every refusal is a string from :data:`REFUSAL_VOCABULARY` (optionally followed by a
``:<detail>`` suffix); callers print them verbatim so the reason a gate closed is the
same word everywhere it is read.

Writers of the stage transition (``scripts/cc-claim``, ``scripts/cc-stage-advance``,
the ``cc-task-gate`` hook's Edit/Write path) and of the release verdict
(``scripts/avsdlc-release-precheck.py``, ``scripts/cc-pr-autoqueue.py``) each call in
here once; none re-derives the rule. Delete-the-estate restatement: a tagged work item
cannot advance without two receipts and cannot release without a third; the tag, the
receipt paths and the refusal words are the only bindings.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from shared.frontmatter import parse_frontmatter_with_diagnostics
from shared.public_gate_receipts import (
    PUBLIC_GATE_AUTHORITY_SECRET_ENV,
    _mapping_has_trusted_authority_signature,
)

GARAGE_DOOR_TAG = "garage-door"
ADOPTABILITY_BLOCK_KEY = "adoptability"
CONTRIBUTION_KIND = "contribution"
OFFERED_STAGE_NUMBER = 1
OFFERED_STATUSES = frozenset({"offered", "ready", "draft", "proposed"})

#: Receipt paths the block must carry (A2 — demand + prior art before selection).
RECEIPT_FIELDS: tuple[str, ...] = ("prior_art_receipt", "demand_receipt")

#: The nine A3 acceptance checks as eleven row fields: (i) install_line + platforms,
#: (ii) zero_config, (iii) ttfv_seconds, (iv) replaces_nothing, (v) api,
#: (vi) compare_page, (vii) licence + repo_open, (viii) release_notes,
#: (ix) operator_voice_post.
ACCEPTANCE_FIELDS: tuple[str, ...] = (
    "install_line",
    "platforms",
    "zero_config",
    "ttfv_seconds",
    "replaces_nothing",
    "api",
    "licence",
    "repo_open",
    "release_notes",
    "compare_page",
    "operator_voice_post",
)

#: Row fields whose text is an install surface — where an estate noun is a binding.
INSTALL_SURFACE_FIELDS: tuple[str, ...] = ("install_line", "platforms", "api", "install_surface")

#: The estate's own nouns. An artifact whose install surface names one of these is the
#: the estate in a costume, not an artifact (A1/A4). Short nouns carry word boundaries
#: (letters, digits, ``_`` and ``-``) so ``reinstall`` and ``reins-free`` are not ``reins``.
ESTATE_NOUN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (label, re.compile(pattern, re.IGNORECASE))
    for label, pattern in (
        ("vault_path", r"Documents/Personal"),
        ("cc_task_rows", r"hapax-cc-tasks"),
        ("cc_task_tooling", r"(?<![A-Za-z0-9])cc-(?:task|claim|close|stage-advance|scope-widen)"),
        ("reins", r"(?<![A-Za-z0-9_-])reins(?![A-Za-z0-9_-])"),
        ("hapax_council_checkout", r"hapax-council"),
        ("hapax_cache", r"\.cache/hapax"),
        ("lanebus", r"(?<![A-Za-z0-9_-])lanebus(?![A-Za-z0-9_-])"),
        ("hapax_env", r"(?<![A-Za-z0-9_])HAPAX_[A-Z0-9_]+"),
        ("hapax_secret", r"hapax-secret(?![A-Za-z0-9_-])"),
        ("methodology_dispatch", r"hapax-methodology-dispatch"),
    )
)

#: Fields whose items are always scalars (paths, ids, tags): any mapping inside them is the
#: ``- path (note: text)`` authoring accident, whatever its key looks like.
SCALAR_LIST_FIELDS: frozenset[str] = frozenset(
    {"mutation_scope_refs", "tags", "depends_on", "blocks"}
)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")

#: Incident-only, LEDGERED emergency bypass (the SDLC gate-composition charter requires one).
ADOPTABILITY_TEETH_OFF_ENV = "HAPAX_ADOPTABILITY_TEETH_OFF"
METHODOLOGY_LEDGER_ENV = "HAPAX_METHODOLOGY_LEDGER"
DEFAULT_METHODOLOGY_LEDGER = Path.home() / ".cache" / "hapax" / "methodology-emergency-ledger.jsonl"
KILLSWITCH_LEDGER_KIND = "adoptability_teeth_off_bypass"

RECEIPT_ROOTS_ENV = "HAPAX_ADOPTABILITY_RECEIPT_ROOTS"
DEFAULT_RECEIPT_ROOTS: tuple[Path, ...] = (Path.home() / "Documents" / "Personal",)
RECEIPT_EXTENSIONS = frozenset({".json", ".md", ".yaml", ".yml"})
DEFAULT_RECEIPT_TTL_SECONDS = 24 * 3600
PRIOR_ART_VERDICTS = frozenset({"BACKED", "UNBACKED"})
MIN_SEARCH_SHAPES = 2
ADOPTABILITY_GATE_NAME = "adoptability"

# ── refusal vocabulary (closed; pinned by tests) ─────────────────────────────

ROW_REFUSED_BLOCK_MISSING = "row_refused:adoptability_block_missing"
ROW_REFUSED_FIELD_MISSING = "row_refused:adoptability_field_missing"  # + ":<field>"
ROW_REFUSED_UNPARSEABLE = "row_refused:frontmatter_unparseable"  # + ":<field|yaml|...>"
STAGE_REFUSED_PRIOR_ART_ABSENT = "stage_refused:prior_art_receipt_absent"
STAGE_REFUSED_DEMAND_ABSENT = "stage_refused:demand_receipt_absent"
STAGE_REFUSED_TAG_REMOVED = "stage_refused:garage_door_tag_removed"
ROW_CONVERTED_CONTRIBUTION = "row_converted:contribution"
RELEASE_REFUSED_RECEIPT_ABSENT = "release_refused:adoptability_receipt_absent"
RELEASE_REFUSED_RECEIPT_UNSIGNED = "release_refused:adoptability_receipt_unsigned"
RELEASE_REFUSED_RECEIPT_STALE = "release_refused:adoptability_receipt_stale"
RELEASE_REFUSED_RECEIPT_MISMATCH = "release_refused:adoptability_receipt_mismatch"
RELEASE_REFUSED_FAILED = "release_refused:adoptability_failed"  # + ":<check>"
RELEASE_REFUSED_ESTATE_BINDING = "release_refused:estate_binding_in_install_surface"

REFUSAL_VOCABULARY: frozenset[str] = frozenset(
    {
        ROW_REFUSED_BLOCK_MISSING,
        ROW_REFUSED_FIELD_MISSING,
        ROW_REFUSED_UNPARSEABLE,
        STAGE_REFUSED_PRIOR_ART_ABSENT,
        STAGE_REFUSED_DEMAND_ABSENT,
        STAGE_REFUSED_TAG_REMOVED,
        ROW_CONVERTED_CONTRIBUTION,
        RELEASE_REFUSED_RECEIPT_ABSENT,
        RELEASE_REFUSED_RECEIPT_UNSIGNED,
        RELEASE_REFUSED_RECEIPT_STALE,
        RELEASE_REFUSED_RECEIPT_MISMATCH,
        RELEASE_REFUSED_FAILED,
        RELEASE_REFUSED_ESTATE_BINDING,
    }
)


# ── frontmatter helpers ──────────────────────────────────────────────────────


def _as_str_list(value: Any) -> list[str]:
    if value is None or isinstance(value, Mapping):
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, Iterable):
        return [str(item).strip() for item in value if item is not None]
    return [str(value).strip()]


def is_garage_door(frontmatter: Mapping[str, Any]) -> bool:
    """A row is garage-door when its ``tags`` name the tag."""
    tags = {tag.casefold() for tag in _as_str_list(frontmatter.get("tags"))}
    return GARAGE_DOOR_TAG in tags


def stage_number(stage: Any) -> int | None:
    match = re.match(r"^S(\d{1,2})(?:_|$)", str(stage or "").strip())
    return int(match.group(1)) if match else None


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, str | int | float | bool)


def list_item_is_accident(field: str, item: Any) -> bool:
    """True for the unquoted ``key: value`` authoring accident inside a block sequence.

    Structured lists are legitimate row content: ``required_tools``, ``refusal_history``,
    ``source_touch_conflicts`` and friends hold identifier-keyed mappings (1,522 of them
    across the vault on 2026-09-16, none an error). The accident is a one-key mapping
    whose sole key is not an identifier — ``- config/ (row schema: adoptability block)``
    parses as ``{"config/ (row schema": "adoptability block)"}`` and the autoqueue then
    skips the row. Inside a declared scalar-list field any mapping is the accident.
    """
    if _is_scalar(item):
        return False
    if field in SCALAR_LIST_FIELDS:
        return True
    if isinstance(item, Mapping):
        keys = list(item)
        return len(keys) == 1 and not _IDENTIFIER_RE.match(str(keys[0]))
    return False


def lint_frontmatter_text(text: str) -> tuple[dict[str, Any] | None, list[str]]:
    """Parse one row and return ``(frontmatter, refusals)``.

    Unparseable frontmatter and the unquoted ``key: value`` accident inside a list
    (see :func:`list_item_is_accident`) are refusals
    (``row_refused:frontmatter_unparseable:<what>``), because the consumers that would
    otherwise meet them skip the row silently. Garage-door rows must carry the
    ``adoptability:`` block with every receipt and acceptance field.
    """
    result = parse_frontmatter_with_diagnostics(text)
    if not result.ok or result.frontmatter is None:
        return None, [f"{ROW_REFUSED_UNPARSEABLE}:{result.error_kind or 'yaml'}"]
    frontmatter = result.frontmatter
    refusals: list[str] = []
    for key, value in frontmatter.items():
        if isinstance(value, list) and any(list_item_is_accident(key, item) for item in value):
            refusals.append(f"{ROW_REFUSED_UNPARSEABLE}:{key}")
    if is_garage_door(frontmatter):
        refusals.extend(adoptability_block_refusals(frontmatter))
    return frontmatter, refusals


def lint_row(path: Path) -> list[str]:
    """Lint one row file; an unreadable file is an unparseable row."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"{ROW_REFUSED_UNPARSEABLE}:read_error:{exc.__class__.__name__}"]
    _, refusals = lint_frontmatter_text(text)
    return refusals


def adoptability_block_refusals(frontmatter: Mapping[str, Any]) -> list[str]:
    """Refusals for a garage-door row's ``adoptability:`` block (presence + fields)."""
    block = frontmatter.get(ADOPTABILITY_BLOCK_KEY)
    if not isinstance(block, Mapping):
        return [ROW_REFUSED_BLOCK_MISSING]
    refusals: list[str] = []
    for field in (*RECEIPT_FIELDS, *ACCEPTANCE_FIELDS):
        value = block.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            refusals.append(f"{ROW_REFUSED_FIELD_MISSING}:{field}")
    return refusals


# ── receipts (prior art, demand, adoptability) ───────────────────────────────


def receipt_roots() -> tuple[Path, ...]:
    raw = os.environ.get(RECEIPT_ROOTS_ENV, "").strip()
    if not raw:
        return DEFAULT_RECEIPT_ROOTS
    roots = tuple(Path(part).expanduser() for part in raw.split(os.pathsep) if part.strip())
    return roots or DEFAULT_RECEIPT_ROOTS


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def resolve_receipt_path(ref: Any, *, roots: Sequence[Path] | None = None) -> Path | None:
    """Resolve a receipt reference to an existing file under one of the roots.

    Relative refs are joined to each root in order; absolute refs must lie inside a
    root. Anything else — blank, ``..`` escapes, unknown extension, missing file —
    resolves to ``None`` and reads as *absent*.
    """
    if not isinstance(ref, str) or not ref.strip():
        return None
    resolved_roots = tuple(roots) if roots is not None else receipt_roots()
    raw = Path(ref.strip()).expanduser()
    candidates = [raw] if raw.is_absolute() else [root / raw for root in resolved_roots]
    for candidate in candidates:
        if candidate.suffix.casefold() not in RECEIPT_EXTENSIONS or not candidate.is_file():
            continue
        if any(_inside(candidate, root) for root in resolved_roots):
            return candidate
    return None


def load_receipt(path: Path) -> Mapping[str, Any] | None:
    """Load a YAML/JSON receipt, or a markdown receipt's frontmatter, as a mapping."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if path.suffix.casefold() == ".md":
        result = parse_frontmatter_with_diagnostics(text)
        return result.frontmatter if result.ok else None
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    return data if isinstance(data, Mapping) else None


def _nonblank(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def prior_art_receipt_status(receipt: Mapping[str, Any] | None) -> str:
    """Classify a prior-art receipt.

    Returns ``absent`` (no mapping), ``invalid`` (fewer than two differently-shaped
    searches, no BACKED/UNBACKED verdict, or BACKED without tier/source/usable),
    ``unbacked``, ``backed_unusable`` or ``backed_usable``. :data:`MIN_SEARCH_SHAPES`
    is standing epistemic rule 2: one grep's silence is a fact about the grep.
    """
    if not isinstance(receipt, Mapping):
        return "absent"
    shapes_raw = receipt.get("search_shapes")
    shapes = (
        [item for item in shapes_raw if isinstance(item, Mapping)]
        if isinstance(shapes_raw, list)
        else []
    )
    distinct = {
        str(item.get("shape", "")).strip().casefold()
        for item in shapes
        if _nonblank(item.get("shape")) and _nonblank(item.get("query"))
    }
    if len(distinct) < MIN_SEARCH_SHAPES:
        return "invalid"
    verdict = str(receipt.get("verdict", "")).strip().upper()
    if verdict not in PRIOR_ART_VERDICTS:
        return "invalid"
    if verdict == "UNBACKED":
        return "unbacked"
    if not (_nonblank(receipt.get("tier")) and _nonblank(receipt.get("source"))):
        return "invalid"
    usable = receipt.get("usable")
    if not isinstance(usable, bool):
        return "invalid"
    return "backed_usable" if usable else "backed_unusable"


def demand_receipt_status(receipt: Mapping[str, Any] | None) -> str:
    """``present`` when the receipt names who asked, else ``absent``.

    Who asked is either a non-empty ``asked_by`` list (issue threads, requests, named
    people) or a ``probe`` with ``asked >= 1`` and non-empty ``answers``.
    """
    if not isinstance(receipt, Mapping):
        return "absent"
    if [item for item in _as_str_list(receipt.get("asked_by")) if item]:
        return "present"
    probe = receipt.get("probe")
    if isinstance(probe, Mapping):
        asked = probe.get("asked")
        answers = probe.get("answers")
        if isinstance(asked, int) and asked >= 1 and isinstance(answers, list) and answers:
            return "present"
    return "absent"


def _block(frontmatter: Mapping[str, Any]) -> Mapping[str, Any]:
    block = frontmatter.get(ADOPTABILITY_BLOCK_KEY)
    return block if isinstance(block, Mapping) else {}


def _receipt_from_block(
    frontmatter: Mapping[str, Any], field: str, roots: Sequence[Path] | None
) -> Mapping[str, Any] | None:
    path = resolve_receipt_path(_block(frontmatter).get(field), roots=roots)
    return load_receipt(path) if path is not None else None


# ── killswitch ───────────────────────────────────────────────────────────────


def _actor() -> str:
    for key in ("HAPAX_AGENT_ROLE", "HAPAX_AGENT_NAME", "CODEX_ROLE", "CLAUDE_ROLE"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return "unknown"


def killswitch_engaged(surface: str) -> bool:
    """``HAPAX_ADOPTABILITY_TEETH_OFF=1`` empties every stage and release refusal — LEDGERED.

    The SDLC gate-composition charter requires an emergency bypass; this is it, in the
    estate's existing shape (cf. ``HAPAX_CC_TASK_GATE_OFF``): incident-only and never
    silent — one stderr line and one ledger row per bypassed evaluation, so the
    methodology digest counts it. It exists for the case the charter names: the receipt
    producer or every container runtime failing globally, which would otherwise block
    every garage-door release. It does not touch the lint or the producer. Prefer a
    scoped, signed escape (``scripts/coord-grant-mint --scope adoptability-teeth``) when
    the incident allows one. Exactly ``1`` engages it; nothing else does.
    """
    if os.environ.get(ADOPTABILITY_TEETH_OFF_ENV, "").strip() != "1":
        return False
    ledger = Path(os.environ.get(METHODOLOGY_LEDGER_ENV, "").strip() or DEFAULT_METHODOLOGY_LEDGER)
    row = {
        "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "kind": KILLSWITCH_LEDGER_KIND,
        "role": _actor(),
        "surface": surface,
    }
    ledgered = "LEDGERED"
    try:
        ledger.expanduser().parent.mkdir(parents=True, exist_ok=True)
        with ledger.expanduser().open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    except OSError as exc:
        ledgered = f"LEDGER UNWRITABLE ({exc.__class__.__name__}: {ledger})"
    print(
        f"adoptability teeth: {ADOPTABILITY_TEETH_OFF_ENV} bypass used on {surface} — {ledgered}. "
        "Incident-only; prefer scripts/coord-grant-mint --scope adoptability-teeth.",
        file=sys.stderr,
    )
    return True


# ── stage gate (A2) ──────────────────────────────────────────────────────────


def _norm(value: Any) -> str:
    return str(value or "").strip().casefold()


def leaves_offered(
    *,
    from_stage: Any,
    from_status: Any,
    to_stage: Any = None,
    to_status: Any = None,
) -> bool:
    """True when the transition moves a row past S1 / out of ``offered``.

    A row that already left ``offered`` (status past offered, or stage past S1) is
    not judged again — the tooth is the S1 boundary, not every later step.
    """
    from_number = stage_number(from_stage)
    before_status = _norm(from_status)
    already_left = (before_status and before_status not in OFFERED_STATUSES) or (
        from_number is not None and from_number > OFFERED_STAGE_NUMBER
    )
    if already_left:
        return False
    to_number = stage_number(to_stage) if to_stage is not None else None
    if to_number is not None and to_number > OFFERED_STAGE_NUMBER:
        return True
    after_status = _norm(to_status) if to_status is not None else ""
    return bool(after_status) and after_status not in OFFERED_STATUSES


def stage_advance_refusals(
    frontmatter: Mapping[str, Any],
    *,
    to_stage: Any = None,
    to_status: Any = None,
    from_stage: Any = None,
    from_status: Any = None,
    roots: Sequence[Path] | None = None,
) -> list[str]:
    """Refusals for advancing a row to ``to_stage`` / ``to_status``.

    ``from_*`` default to the row's own current values; a hook judging a proposed
    edit passes the pre-edit values and the post-edit frontmatter. Non-garage-door
    rows and transitions that stay in ``offered`` return nothing. A garage-door row
    leaving ``offered`` needs a valid prior-art receipt and a demand receipt;
    BACKED-and-usable prior art on a row that is not yet ``kind: contribution``
    returns :data:`ROW_CONVERTED_CONTRIBUTION` — the writer converts the row (or
    refuses the edit until the row says contribution). The row's own block refusals
    ride along: a row without its block cannot advance either.
    """
    if not is_garage_door(frontmatter):
        return []
    if killswitch_engaged("stage"):
        return []
    if not leaves_offered(
        from_stage=frontmatter.get("stage") if from_stage is None else from_stage,
        from_status=frontmatter.get("status") if from_status is None else from_status,
        to_stage=to_stage,
        to_status=to_status,
    ):
        return []
    refusals = adoptability_block_refusals(frontmatter)
    prior_art = prior_art_receipt_status(
        _receipt_from_block(frontmatter, "prior_art_receipt", roots)
    )
    if prior_art in {"absent", "invalid"}:
        refusals.append(STAGE_REFUSED_PRIOR_ART_ABSENT)
    if (
        demand_receipt_status(_receipt_from_block(frontmatter, "demand_receipt", roots))
        != "present"
    ):
        refusals.append(STAGE_REFUSED_DEMAND_ABSENT)
    if prior_art == "backed_usable" and _norm(frontmatter.get("kind")) != CONTRIBUTION_KIND:
        refusals.append(ROW_CONVERTED_CONTRIBUTION)
    return refusals


def convert_to_contribution(text: str, *, actor: str, now: str) -> str:
    """Rewrite ``kind:`` to ``contribution`` inside the frontmatter and log it."""
    end = text.find("\n---", 4)
    if not text.startswith("---") or end < 0:
        raise ValueError("row has no closed frontmatter")
    front, body = text[: end + 1], text[end + 1 :]
    if re.search(r"(?m)^kind:", front):
        front = re.sub(r"(?m)^kind:\s*.*$", f"kind: {CONTRIBUTION_KIND}", front, count=1)
    else:
        front = front.rstrip("\n") + f"\nkind: {CONTRIBUTION_KIND}\n"
    log = (
        f"- {now} {actor}: {ROW_CONVERTED_CONTRIBUTION} — prior-art receipt is BACKED and "
        "usable; the row builds a contribution to the existing artifact, not a competitor."
    )
    return front + body.rstrip("\n") + "\n" + log + "\n"


# ── hook: Edit/Write post-condition ──────────────────────────────────────────


def apply_tool_edit(current: str, tool_name: str, tool_input: Mapping[str, Any]) -> str | None:
    """Compute the text an Edit/Write/MultiEdit call would leave on disk.

    Returns ``None`` when the tool is not one of those (nothing to judge). A
    non-matching ``old_string`` leaves the text unchanged — the harness refuses
    that edit itself.
    """
    if tool_name == "Write":
        content = tool_input.get("content")
        return content if isinstance(content, str) else None
    if tool_name == "Edit":
        edits: list[Mapping[str, Any]] = [tool_input]
    elif tool_name == "MultiEdit":
        raw = tool_input.get("edits")
        edits = [item for item in raw if isinstance(item, Mapping)] if isinstance(raw, list) else []
    else:
        return None
    text = current
    for edit in edits:
        old = edit.get("old_string")
        new = edit.get("new_string")
        if not isinstance(old, str) or not isinstance(new, str) or not old:
            continue
        text = text.replace(old, new) if edit.get("replace_all") else text.replace(old, new, 1)
    return text


def hook_edit_refusals(
    current_text: str,
    proposed_text: str,
    *,
    roots: Sequence[Path] | None = None,
) -> list[str]:
    """Refusals for a proposed row edit, judged on the row's post-edit state.

    Only garage-door rows are judged. Removing the tag in the same edit is itself a
    refusal (an escape is not a transition). Receipts added by the same edit count —
    the post-edit frontmatter is what is judged.
    """
    before, _ = lint_frontmatter_text(current_text) if current_text else (None, [])
    after, after_refusals = lint_frontmatter_text(proposed_text)
    before_gd = before is not None and is_garage_door(before)
    if after is None:
        # An unparseable result is judged before anything else: a garage-door row
        # that stops parsing is not "no longer garage-door", it is refused as unparseable.
        return after_refusals if before_gd else []
    after_gd = is_garage_door(after)
    if not before_gd and not after_gd:
        return []
    if killswitch_engaged("hook-edit"):
        return []
    if before_gd and not after_gd:
        return [STAGE_REFUSED_TAG_REMOVED]
    refusals = list(after_refusals)
    for reason in stage_advance_refusals(
        after,
        to_stage=after.get("stage"),
        to_status=after.get("status"),
        from_stage=before.get("stage") if before else "",
        from_status=before.get("status") if before else "",
        roots=roots,
    ):
        if reason not in refusals:
            refusals.append(reason)
    return refusals


# ── release gate (A1 / A3 / A4) ──────────────────────────────────────────────


def estate_bindings(frontmatter: Mapping[str, Any]) -> list[str]:
    """Labels of estate nouns found in the row's install surface fields."""
    block = _block(frontmatter)
    parts: list[str] = []
    for field in INSTALL_SURFACE_FIELDS:
        value = block.get(field)
        parts.extend([value] if isinstance(value, str) else _as_str_list(value))
    text = " ".join(parts)
    return [label for label, pattern in ESTATE_NOUN_PATTERNS if pattern.search(text)]


def _epoch(value: Any) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def install_line_digest(install_line: Any) -> str:
    return hashlib.sha256(str(install_line or "").strip().encode("utf-8")).hexdigest()


def artifact_repo(frontmatter: Mapping[str, Any]) -> str:
    """The artifact repository the block names (``repo``, else ``repo_open``)."""
    block = _block(frontmatter)
    return _norm(block.get("repo") or block.get("repo_open"))


def adoptability_receipt_refusals(
    receipt: Mapping[str, Any] | None,
    *,
    frontmatter: Mapping[str, Any],
    now: float,
    secret: str,
) -> list[str]:
    """Refusals derived from an adoptability receipt against its row.

    Absent → absent; wrong gate or another artifact (repo, install-line digest) →
    mismatch; signature not trusted → unsigned; past ``stale_after`` (or
    ``observed_at`` + TTL) → stale; each failed check → ``adoptability_failed:<check>``.
    """
    if not isinstance(receipt, Mapping):
        return [RELEASE_REFUSED_RECEIPT_ABSENT]
    if _norm(receipt.get("gate")) != ADOPTABILITY_GATE_NAME:
        return [RELEASE_REFUSED_RECEIPT_MISMATCH]
    if not _mapping_has_trusted_authority_signature(receipt, secret):
        return [RELEASE_REFUSED_RECEIPT_UNSIGNED]
    refusals: list[str] = []
    stale_after = _epoch(receipt.get("stale_after"))
    observed_at = _epoch(receipt.get("observed_at"))
    if stale_after is None and observed_at is not None:
        stale_after = observed_at + DEFAULT_RECEIPT_TTL_SECONDS
    if stale_after is None or now > stale_after:
        refusals.append(RELEASE_REFUSED_RECEIPT_STALE)
    row_repo = artifact_repo(frontmatter)
    if _norm(receipt.get("repo")) != row_repo or receipt.get(
        "install_line_sha256"
    ) != install_line_digest(_block(frontmatter).get("install_line")):
        refusals.append(RELEASE_REFUSED_RECEIPT_MISMATCH)
    checks = receipt.get("checks")
    if not isinstance(checks, Mapping) or not checks:
        refusals.append(f"{RELEASE_REFUSED_FAILED}:no_checks")
    else:
        for name, check in checks.items():
            passed = check.get("passed") if isinstance(check, Mapping) else check
            if passed is not True:
                refusals.append(f"{RELEASE_REFUSED_FAILED}:{name}")
    if _norm(receipt.get("outcome")) != "pass" and not any(
        reason.startswith(RELEASE_REFUSED_FAILED) for reason in refusals
    ):
        refusals.append(f"{RELEASE_REFUSED_FAILED}:outcome")
    return refusals


def release_refusals(
    frontmatter: Mapping[str, Any],
    *,
    now: float | None = None,
    roots: Sequence[Path] | None = None,
    secret: str | None = None,
) -> list[str]:
    """Release blockers for a garage-door row; empty for every other row.

    The estate-binding refusal is independent of the receipt: an install surface
    that names the estate is refused even beside a passing receipt.
    """
    if not is_garage_door(frontmatter):
        return []
    if killswitch_engaged("release"):
        return []
    refusals: list[str] = []
    if estate_bindings(frontmatter):
        refusals.append(RELEASE_REFUSED_ESTATE_BINDING)
    timestamp = datetime.now(UTC).timestamp() if now is None else now
    authority_secret = (
        secret
        if secret is not None
        else os.environ.get(PUBLIC_GATE_AUTHORITY_SECRET_ENV, "").strip()
    )
    receipt = _receipt_from_block(frontmatter, "receipt", roots)
    refusals.extend(
        adoptability_receipt_refusals(
            receipt, frontmatter=frontmatter, now=timestamp, secret=authority_secret
        )
    )
    return refusals


def adoptability_release_blockers(
    frontmatter: Mapping[str, Any], *, now: float | None = None
) -> list[str]:
    """Consumer-facing name used by the release precheck and the autoqueue."""
    return release_refusals(frontmatter, now=now)


# ── CLI (used by the cc-task-gate hook and by operators) ─────────────────────

EXIT_OK = 0
EXIT_REFUSED = 2
EXIT_ERROR = 3


def _print_refusals(refusals: Iterable[str], *, label: str) -> int:
    reasons = list(refusals)
    for reason in reasons:
        print(f"{label}: {reason}", file=sys.stderr)
    return EXIT_REFUSED if reasons else EXIT_OK


def _cli_lint(paths: Sequence[str]) -> int:
    rc = EXIT_OK
    for raw in paths:
        path = Path(raw)
        files = sorted(path.glob("*.md")) if path.is_dir() else [path]
        for file in files:
            refusals = lint_row(file)
            if refusals:
                rc = EXIT_REFUSED
                for reason in refusals:
                    print(f"{file}: {reason}", file=sys.stderr)
    return rc


def _cli_stage_check(note: str, to_stage: str | None, to_status: str | None) -> int:
    path = Path(note)
    if not path.is_file():
        print(f"adoptability-gate: note not found: {path}", file=sys.stderr)
        return EXIT_ERROR
    frontmatter, lint = lint_frontmatter_text(path.read_text(encoding="utf-8"))
    if frontmatter is None:
        return _print_refusals(lint, label=str(path))
    return _print_refusals(
        stage_advance_refusals(frontmatter, to_stage=to_stage, to_status=to_status),
        label=str(path),
    )


def _cli_hook_edit(note: str) -> int:
    path = Path(note)
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(f"adoptability-gate: tool input is not JSON: {exc}", file=sys.stderr)
        return EXIT_ERROR
    if not isinstance(payload, Mapping):
        return EXIT_ERROR
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, Mapping):
        return EXIT_OK
    current = path.read_text(encoding="utf-8") if path.is_file() else ""
    proposed = apply_tool_edit(current, str(payload.get("tool_name", "")), tool_input)
    if proposed is None:
        return EXIT_OK
    return _print_refusals(hook_edit_refusals(current, proposed), label=str(path))


def _cli_release_check(note: str) -> int:
    path = Path(note)
    if not path.is_file():
        print(f"adoptability-gate: note not found: {path}", file=sys.stderr)
        return EXIT_ERROR
    result = parse_frontmatter_with_diagnostics(path)
    if not result.ok or result.frontmatter is None:
        print(f"{path}: {ROW_REFUSED_UNPARSEABLE}:{result.error_kind}", file=sys.stderr)
        return EXIT_REFUSED
    for label in estate_bindings(result.frontmatter):
        print(f"{path}: estate noun in install surface: {label}", file=sys.stderr)
    return _print_refusals(release_refusals(result.frontmatter), label=str(path))


def _flag_value(args: Sequence[str], flag: str) -> str | None:
    if flag in args:
        index = args.index(flag)
        if index + 1 < len(args):
            return args[index + 1]
    return None


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(
            "usage: adoptability_gate lint <row|dir>... | stage-check <row> [--to-stage S] "
            "[--to-status STATUS] | hook-edit <row> (tool JSON on stdin) | release-check <row>",
            file=sys.stderr,
        )
        return EXIT_ERROR
    command, rest = args[0], args[1:]
    if command == "lint" and rest:
        return _cli_lint(rest)
    if command == "stage-check" and rest:
        return _cli_stage_check(
            rest[0], _flag_value(rest, "--to-stage"), _flag_value(rest, "--to-status")
        )
    if command == "hook-edit" and rest:
        return _cli_hook_edit(rest[0])
    if command == "release-check" and rest:
        return _cli_release_check(rest[0])
    print(f"adoptability-gate: unknown or incomplete command {command!r}", file=sys.stderr)
    return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
