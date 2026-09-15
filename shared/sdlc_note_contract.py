"""How a cc-task note's frontmatter is READ and WRITTEN — one grammar, one writer.

Every surface that decides something from a task note parses it here, and both
surfaces that rewrite one write through here. That is the point of the module:
the estate had four parsers and two writers, they disagreed about which lines
are fences, and the disagreements were silent — a review demand that one surface
saw and another did not, and a close that recorded a stage it had not written.

**A leaf on purpose: stdlib and PyYAML only.** ``scripts/cc-close`` runs the
close gate under a bare ``python3``, so nothing on this path may reach pydantic
or AGENTGOV. ``shared/frontmatter.py`` — the canonical parser, which does reach
``shared.governance.consent_label`` — depends on this module rather than the
other way round, and that direction is pinned by test, not left to be re-derived.

**Why these definitions are not in** :mod:`shared.sdlc_lifecycle`, where they
used to live. That module is a **Gate 0A canon byte-hashed source**: its sha256
is a member of ``_SOURCE_HASH_REFS`` in ``shared/session_context_canon.py``, so
any edit to it — a comment included — moves ``bundle_hash``, then
``position_ref``, then ``frame_hash``, and fails
``tests/shared/test_session_context_canon.py::test_contract_semantic_supersession_binds_current_and_predecessor``
against the frozen fixtures in ``packages/hapax-context-canon/tests/fixtures/``.
Re-freezing those is a supersession ceremony whose checkpoint manifest carries
an operator authority binding, so corrections land outside the hashed surface
until Gate 0B folds them back in — the practice ``shared/release_gate.py:816``
already records for the release mitigation map.

**The consequence, stated rather than left to be discovered.** The canon module
still defines ``frontmatter_from_text``, ``requires_acceptance_receipt``,
``acceptance_receipt_blockers`` and ``apply_release_auto_arm`` with their
pre-correction behaviour. **Those copies are frozen, not current, and nothing
may import them** — ``tests/shared/test_sdlc_note_contract.py`` fails if anything
does. Import the names from here.

One correction this module does not reach: ``task_closure_validity`` stays in
the canon module and still calls the parser next to it, so a dependency task
whose note carries a legal ``---extra:`` key is still read with the old grammar
there. Unchanged from ``main`` — a missed improvement rather than a regression —
and tracked as ``sdlc-task-closure-validity-old-fence-grammar-20260914`` for the
Gate 0B fold-back.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import yaml

from shared.sdlc_lifecycle import (
    ACCEPTANCE_RECEIPT_ACCEPTED_VERDICTS,
    ACCEPTANCE_RECEIPT_REQUIRED_FIELDS,
    ACCEPTANCE_RECEIPT_SUFFIX,
    REVIEW_FLOOR_QUALITY_FLOOR,
    _acceptance_receipt_validity_blockers,
    _frontmatter_non_null_scalar,
    _frontmatter_scalar,
    _stage_below_s7,
    acceptance_receipt_path,
)

__all__ = [
    "ACCEPTANCE_RECEIPT_ACCEPTED_VERDICTS",
    "ACCEPTANCE_RECEIPT_REQUIRED_FIELDS",
    "ACCEPTANCE_RECEIPT_SUFFIX",
    "FRONTMATTER_ABSENT",
    "FRONTMATTER_EMPTY_BLOCK",
    "FRONTMATTER_INVALID_OPENING_FENCE",
    "FRONTMATTER_NOT_A_MAPPING",
    "FRONTMATTER_OK",
    "FRONTMATTER_PARSE_ERROR",
    "FRONTMATTER_UNREADABLE_STATES",
    "FRONTMATTER_UNTERMINATED",
    "RECEIPT_TRIGGER_INDEPENDENT_REVIEW",
    "RECEIPT_TRIGGER_MALFORMED_CONTAINER",
    "RECEIPT_TRIGGER_MALFORMED_REVIEW",
    "RECEIPT_TRIGGER_REVIEW_FLOOR",
    "REVIEW_FLOOR_QUALITY_FLOOR",
    "WRITE_COLLATERAL",
    "WRITE_INEFFECTIVE",
    "WRITE_POSTIMAGE_UNREADABLE",
    "WRITE_PREIMAGE_UNREADABLE",
    "WRITE_VALUE_UNREPRESENTABLE",
    "acceptance_receipt_blockers",
    "acceptance_receipt_path",
    "acceptance_receipt_triggers",
    "apply_release_auto_arm",
    "frontmatter_block_text",
    "frontmatter_from_text",
    "frontmatter_render_value",
    "frontmatter_set_exactly",
    "frontmatter_state_from_text",
    "frontmatter_write_partition",
    "is_frontmatter_fence",
    "requires_acceptance_receipt",
]


# ── Reading ──────────────────────────────────────────────────────────────────

#: Outcomes of reading a note's frontmatter. ``ok``, ``absent`` and
#: ``empty_block`` all yield a mapping that can be trusted; the rest mean the
#: mapping is empty because parsing FAILED, not because nothing was declared.
FRONTMATTER_OK = "ok"
FRONTMATTER_ABSENT = "absent"
#: A well-formed fence pair enclosing nothing (``---\n---``, or a block whose
#: YAML is only comments). Separate from ABSENT, which means there was no
#: opening fence at all: callers that must tell "declared an empty block" from
#: "declared nothing" were re-deriving it by re-reading the first line, which is
#: a second reading of a fact the walk already knows.
FRONTMATTER_EMPTY_BLOCK = "empty_block"
FRONTMATTER_UNTERMINATED = "unterminated"
FRONTMATTER_PARSE_ERROR = "parse_error"
FRONTMATTER_NOT_A_MAPPING = "not_a_mapping"
#: The first line tried to be a fence and is not one (``---extra: [``, ``----``).
#: Distinct from ABSENT: the note visibly attempted to declare frontmatter, so
#: reading it as "declares nothing" disarms enforcement on a broken note.
FRONTMATTER_INVALID_OPENING_FENCE = "invalid_opening_fence"

#: States where the returned mapping is empty because the document could not be
#: read, so its emptiness carries no information about what the note declares.
FRONTMATTER_UNREADABLE_STATES: Final[frozenset[str]] = frozenset(
    {
        FRONTMATTER_UNTERMINATED,
        FRONTMATTER_PARSE_ERROR,
        FRONTMATTER_NOT_A_MAPPING,
        FRONTMATTER_INVALID_OPENING_FENCE,
    }
)


def is_frontmatter_fence(line: str) -> bool:
    """True when ``line`` is a YAML document marker usable as a frontmatter fence.

    The grammar, stated once rather than approximated: ``---`` at **column 0**,
    followed by end-of-line or whitespace. Everything else is content.

        ---                     fence
        ---␣                    fence (trailing whitespace)
        --- # task metadata     fence (a comment after the marker is legal YAML)
        ---extra: abc           NOT a fence — a legal mapping key
        ␣␣---                   NOT a fence — indented, so it is scalar content
        ----                    NOT a fence

    Three successive review rounds each corrected one of those rows by adjusting
    a predicate — ``startswith`` admitted the key, ``strip()`` admitted the
    indented line, ``rstrip() == "---"`` rejected the comment — and each
    correction reopened or broke a different row. They are not four rules; they
    are one rule the approximations kept missing. The gate reads frontmatter to
    decide whether review is required, so a mis-detected fence silently truncates
    a task's declarations.
    """

    # A trailing CR is stripped so the helper is correct for callers that split
    # raw text on "\n" themselves. Both in-tree parsers normalize per line before
    # calling, so this is the helper's own standalone contract rather than the
    # load-bearing CRLF fix — pinned directly in the fence-grammar table.
    line = line.rstrip("\r")
    if not line.startswith("---"):
        return False
    rest = line[3:]
    return rest == "" or rest[0] in " \t"


def frontmatter_block_text(text: str) -> tuple[str, str]:
    """The raw YAML region of a note's frontmatter, and why it is what it is.

    Returns ``(raw, state)``. ``raw`` is meaningful only when ``state`` is
    ``FRONTMATTER_OK``; otherwise it is empty and the state says what went wrong.

    Exposed so callers that must inspect the frontmatter region *without*
    parsing it — the ANSI-escape check in ``cc-pr-autoqueue``, which has to scan
    the block and not the markdown body — consume the same walk the parser uses
    instead of restating it. The region checked is then the region parsed *by
    construction*: two copies of this walk agreeing only because both happened to
    call the same predicate is how the estate's parsers came to disagree in the
    first place.

    The remainder of the opening line is part of the region:
    ``--- {task_id: x, quality_floor: frontier_review_required}`` is a valid
    document whose mapping sits on the marker line, and dropping it discarded
    whole declarations while still reporting a clean parse.
    """

    # No per-line CR normalization here: ``is_frontmatter_fence`` tolerates a
    # trailing CR and PyYAML accepts CRLF, so stripping here was a SECOND guard
    # for one hazard — and being redundant, nothing could fail when it was
    # removed. Deleted rather than given a test, because the guard that remains
    # is the one with an oracle (the fence-grammar table's CR rows). Keeping the
    # raw lines also stops the canonical parser silently rewriting a CRLF body
    # to LF on success while preserving it on failure.
    lines = text.split("\n")
    if not is_frontmatter_fence(lines[0]):
        if lines[0].startswith("---"):
            # Tried to open frontmatter and failed. Not ABSENT: a note that
            # visibly attempted a declaration must not read as declaring
            # nothing, or a broken note disarms the gate.
            return "", FRONTMATTER_INVALID_OPENING_FENCE
        return "", FRONTMATTER_ABSENT
    for index in range(1, len(lines)):
        if is_frontmatter_fence(lines[index]):
            # An empty region is a legitimate OK result: the fences were found
            # and enclose nothing. Classifying THAT as :data:`FRONTMATTER_EMPTY_BLOCK`
            # belongs to the parser, which reaches the same verdict through
            # ``yaml.safe_load`` returning ``None`` — and has to, because a
            # comment-only block has a non-empty region and still declares
            # nothing. Returning the state from here as well was a second guard
            # for one hazard: mutating it reddened nothing, because the parser's
            # branch covered it. The parser's is the one with an oracle.
            return "\n".join([lines[0][3:], *lines[1:index]]).strip(), FRONTMATTER_OK
    return "", FRONTMATTER_UNTERMINATED


def frontmatter_write_partition(text: str) -> tuple[str, str, str]:
    """Split a note for EDITING: ``(head, tail, state)``.

    ``head`` is everything before the closing fence line; ``tail`` begins at that
    line. ``head + tail`` reproduces ``text`` exactly, so a caller may rewrite or
    append fields inside ``head`` and rejoin without disturbing the body. Both
    are empty unless ``state`` is :data:`FRONTMATTER_OK`.

    Exists because readers and writers were using different fence rules, and the
    asymmetry was worse than either being wrong alone. Once the parser learned
    that ``---extra: abc`` is a mapping key rather than a fence, a writer still
    treating it as the fence inserted its updates ABOVE that line while the
    original fields stayed below — and YAML's last-key-wins meant the note parsed
    back with the OLD values. Terminal close then projected that note into
    ``closed/`` and cleared the claim, recording a stage it had not actually
    written. Before the reader improved, the same note was simply refused.

    A capability added to one side of a read/write pair is a defect until the
    other side has it.
    """

    lines = text.split("\n")
    if not is_frontmatter_fence(lines[0]):
        if lines[0].startswith("---"):
            return "", "", FRONTMATTER_INVALID_OPENING_FENCE
        return "", "", FRONTMATTER_ABSENT
    for index in range(1, len(lines)):
        if is_frontmatter_fence(lines[index]):
            head = "\n".join(lines[:index])
            tail = "\n" + "\n".join(lines[index:])
            return head, tail, FRONTMATTER_OK
    return "", "", FRONTMATTER_UNTERMINATED


def frontmatter_state_from_text(text: str) -> tuple[dict[str, Any], str]:
    """Frontmatter plus WHY it is what it is.

    ``frontmatter_from_text`` collapses every failure to ``{}``, which makes a
    note whose YAML does not parse indistinguishable from a note that declares
    nothing. For a gate that arms on declarations, those are opposite meanings:
    the first is "I cannot tell what this note requires", the second is "it
    requires nothing". Callers that must not treat the former as the latter use
    this and check :data:`FRONTMATTER_UNREADABLE_STATES`.

    This is the outermost instance of the rule the receipt triggers already
    apply at every inner level — a present-but-unreadable container may not read
    as absent. The document itself is just the outermost container.
    """

    # Fences are matched as COMPLETE lines, never as a prefix. A substring scan
    # for "\n---" also matches ``---extra: abc``, which is a legal YAML key: the
    # block was truncated at that line and the remainder — including a review
    # demand below it — silently vanished while the state still reported ``ok``.
    # That is worse than the earlier failures, which at least declared
    # themselves unreadable; this one hid a declaration behind a confident
    # success. Line-based matching also makes ``---\n---`` and ``---\n\n---``
    # agree: both are an empty block, where the offset scan called the first
    # unterminated and the second absent.
    raw, region_state = frontmatter_block_text(text)
    if region_state != FRONTMATTER_OK:
        return {}, region_state
    try:
        loaded = yaml.safe_load(raw)
    except yaml.YAMLError:
        return {}, FRONTMATTER_PARSE_ERROR
    if isinstance(loaded, dict):
        return loaded, FRONTMATTER_OK
    if loaded is None:
        # Fenced, non-empty, and yields nothing: a comment-only block.
        return {}, FRONTMATTER_EMPTY_BLOCK
    return {}, FRONTMATTER_NOT_A_MAPPING


def frontmatter_from_text(text: str) -> dict[str, Any]:
    """Return YAML frontmatter from a markdown note, or an empty mapping.

    Lossy by design and kept that way for its many callers: every failure mode
    collapses to ``{}``. Callers that must distinguish "declares nothing" from
    "could not be parsed" use :func:`frontmatter_state_from_text`.
    """

    return frontmatter_state_from_text(text)[0]


# ── Writing ──────────────────────────────────────────────────────────────────

#: Outcomes of WRITING one frontmatter key. ``FRONTMATTER_OK`` means the note
#: now parses with that key set and nothing else moved; every other value means
#: the postimage was rejected and the caller was handed its input back.
WRITE_PREIMAGE_UNREADABLE = "preimage_unreadable"
WRITE_POSTIMAGE_UNREADABLE = "postimage_unreadable"
WRITE_VALUE_UNREPRESENTABLE = "value_unrepresentable"
WRITE_INEFFECTIVE = "write_ineffective"
WRITE_COLLATERAL = "write_collateral"

_ABSENT = object()


def frontmatter_render_value(value: object) -> str:
    """Render ``value`` as the value half of one ``key: value`` frontmatter line.

    Through the YAML emitter, so a value that needs quoting gets it. Dumped as a
    mapping and split rather than dumped bare, because the emitter terminates a
    bare scalar document with ``\\n...`` — which would render a second line and
    be refused by :func:`frontmatter_set_exactly` as not one mapping entry.
    """

    return yaml.safe_dump({"value": value}, sort_keys=False).strip().split(":", 1)[1].strip()


def frontmatter_set_exactly(
    text: str,
    key: str,
    rendered_value: str,
) -> tuple[str, str, str]:
    """Set one frontmatter key by line edit. Returns ``(text, state, detail)``.

    On any state other than :data:`FRONTMATTER_OK` the returned text is the
    INPUT, unchanged — the edit is all-or-nothing, and the caller decides
    whether an unapplied edit is a refusal, a retry, or an error. ``detail`` is
    the caller's material for saying *why*; discarding it turns a diagnosable
    refusal into a silent no-op.

    Line-editing rather than re-serialising the mapping is deliberate: task
    notes are hand-written and hand-read, and a round trip through the YAML
    emitter would discard their comments, key order and quoting. But a line
    edit is an *approximation* of a semantic edit, so it is checked against the
    meaning it stands for:

        after the write the frontmatter parses equal to the frontmatter before
        it with ``key`` set to the intended value — exactly.

    One equality, stated over the parsed mapping rather than over the text. That
    is what makes it cover shapes nobody enumerated, and it is why this lives
    here rather than in each writer: the estate had two of them, and both were
    wrong in four of the same ways. Measured on their predecessors —

    * a legal ``---extra: abc`` mapping key read as the closing fence, so the
      update landed ABOVE the real fields and YAML's last-key-wins returned the
      OLD values. Terminal close projected such a note into ``closed/`` and
      deleted its claim leases; release auto-arm reported success and appended
      an audit line on every retry while nothing advanced;
    * a duplicated key rewritten with ``count=1``, which YAML then resolves to
      the untouched last occurrence;
    * ``^key:\\s*.*$``, whose ``\\s*`` crosses the newline, so an empty-valued
      key consumed the line beneath it (closing with ``--pr`` dropped
      ``implementation_authorized``);
    * the value substituted as a regex REPLACEMENT, so a backreference in it
      raised out of a governed path.

    A capability added to one side of a read/write pair is a defect until the
    other side has it.
    """

    line = f"{key}: {rendered_value}"
    try:
        intent = yaml.safe_load(line)
    except yaml.YAMLError as exc:
        return text, WRITE_VALUE_UNREPRESENTABLE, str(exc).replace("\n", " ")
    if not isinstance(intent, dict) or set(intent) != {key}:
        # Exactly one entry, for this key. A value carrying a newline renders a
        # second declaration; one that restates a key already in the note passes
        # a value comparison while leaving a contradicting line in the text.
        return (
            text,
            WRITE_VALUE_UNREPRESENTABLE,
            f"{line!r} does not render as exactly one mapping entry",
        )

    before, before_state = frontmatter_state_from_text(text)
    if before_state != FRONTMATTER_OK:
        return text, WRITE_PREIMAGE_UNREADABLE, before_state

    head, tail, partition_state = frontmatter_write_partition(text)
    if partition_state != FRONTMATTER_OK:  # pragma: no cover - implied by before_state
        return text, WRITE_PREIMAGE_UNREADABLE, partition_state

    # Excluding CR from the match is what keeps a CRLF note CRLF on the rewrite
    # path: the line's own ending is never part of the replaced span.
    pattern = rf"(?m)^{re.escape(key)}:[^\r\n]*"
    if re.search(pattern, head):
        # EVERY occurrence, and through a function so the value is never read as
        # a backreference.
        head = re.sub(pattern, lambda _match: line, head)
    else:
        # The append path carries the ending itself; head ends with CR exactly
        # when the last frontmatter line did.
        head += "\n" + line + ("\r" if head.endswith("\r") else "")

    postimage = head + tail
    after, after_state = frontmatter_state_from_text(postimage)
    if after_state != FRONTMATTER_OK:
        return text, WRITE_POSTIMAGE_UNREADABLE, after_state
    if after.get(key, _ABSENT) != intent[key]:
        return (
            text,
            WRITE_INEFFECTIVE,
            f"{key} still parses as {after.get(key, _ABSENT)!r} after the write",
        )
    collateral = sorted(
        str(name)
        for name in set(before) | set(after)
        if name != key and before.get(name, _ABSENT) != after.get(name, _ABSENT)
    )
    if collateral:
        return text, WRITE_COLLATERAL, ", ".join(collateral)
    return postimage, FRONTMATTER_OK, ""


def apply_release_auto_arm(
    note_text: str,
    *,
    now_iso: str,
    role: str = "autoqueue-system",
    head_sha: str | None = None,
    head_ref: str | None = None,
) -> tuple[str, str]:
    """Apply the system release-arming. Returns ``(note_text, refusal_reason)``.

    Sets ``release_authorized: true``, advances ``stage`` to ``S7_RELEASE`` when
    it is below S7 or absent, records the authorized PR head when supplied,
    refreshes ``updated_at``, and appends a single audit line to the body. Pure
    text transform — file IO and the authority-case ledger append are the
    caller's responsibility.

    ``refusal_reason`` is empty on success. When it is not, the returned text is
    the INPUT unchanged and the reason names the field and the repair, because
    the caller's alternative vocabulary for "nothing came back" is
    ``note_unchanged`` — which it also uses for an already-armed note, so a
    genuine refusal would be indistinguishable from a no-op success.

    Every field goes through :func:`frontmatter_set_exactly`, so the arming is
    applied only if the note comes back parsing with it, and the audit line is
    appended only once all of them did. Before that, this writer found its
    boundary with its own ``find("\\n---", 4)`` prefix scan — so a note carrying
    a legal ``---extra: abc`` key had the arming inserted ABOVE its real fields,
    parsed back as ``release_authorized: false`` at the original stage, and every
    retry appended another success audit line while nothing advanced. An audit
    trail that records work that did not happen is worse than a refusal.
    """

    updates: list[tuple[str, str]] = [("release_authorized", "true")]
    for key, value in (
        ("release_authorized_head_sha", head_sha),
        ("release_authorized_head_ref", head_ref),
    ):
        if value:
            updates.append((key, frontmatter_render_value(value)))

    frontmatter, state = frontmatter_state_from_text(note_text)
    if state != FRONTMATTER_OK:
        return note_text, f"note_frontmatter_{state}:repair the task note frontmatter"
    declared_stage = frontmatter.get("stage")
    if declared_stage is None or _stage_below_s7(_frontmatter_scalar(declared_stage)):
        updates.append(("stage", "S7_RELEASE"))
    updates.append(("updated_at", now_iso))

    armed = note_text
    for key, rendered in updates:
        armed, write_state, detail = frontmatter_set_exactly(armed, key, rendered)
        if write_state != FRONTMATTER_OK:
            return note_text, f"{key}:{write_state}:{detail}"

    log_line = (
        f"- {now_iso} {role}: release auto-arm (system) — "
        "release_authorized -> true, stage -> S7_RELEASE."
    )
    ending = "\r\n" if armed.endswith("\r\n") else "\n"
    return armed.rstrip("\r\n") + ending + log_line + ending, ""


# ── What arms the acceptance-receipt gate ────────────────────────────────────

#: Declaration names reported when the acceptance-receipt gate arms.
RECEIPT_TRIGGER_REVIEW_FLOOR = f"quality_floor:{REVIEW_FLOOR_QUALITY_FLOOR}"
RECEIPT_TRIGGER_INDEPENDENT_REVIEW = "review_requirement.independent_review_required"
RECEIPT_TRIGGER_MALFORMED_REVIEW = "review_requirement.independent_review_required:malformed"
#: The flag may be perfectly valid while the container holding it is the wrong
#: shape; the refusal must say which, or it sends the operator to fix a value
#: that is already correct.
RECEIPT_TRIGGER_MALFORMED_CONTAINER = "review_requirement:malformed_container"

#: Scalar spellings the route schema coerces to ``True`` / ``False`` for
#: ``ReviewRequirement.independent_review_required``. Enumerated from the model
#: itself rather than assumed, so frontmatter read as raw text is judged by the
#: same semantics as frontmatter read through the schema.
#:
#: These tables are a REIMPLEMENTATION, not the source of truth — the model is.
#: Their agreement is pinned by test, not by inspection; if pydantic's accepted
#: spellings change on upgrade, that test fails rather than this gate silently
#: reopening. Recheck:
#:   uv run pytest tests/shared/test_sdlc_note_contract.py::TestSchemaParity -q
_INDEPENDENT_REVIEW_TRUTHY = frozenset({"true", "yes", "y", "on", "t", "1"})
_INDEPENDENT_REVIEW_FALSY = frozenset({"false", "no", "n", "off", "f", "0"})

#: Per-block verdicts for ``independent_review_required``.
_REVIEW_ABSENT = "absent"
_REVIEW_DEMANDED = "demanded"
_REVIEW_DECLINED = "declined"
_REVIEW_MALFORMED = "malformed"  # flag value the schema rejects
_REVIEW_MALFORMED_CONTAINER = "malformed_container"  # container is not a mapping


def _schema_bool(raw: object) -> bool | None:
    """``ReviewRequirement``'s boolean coercion; ``None`` when the schema rejects.

    Reimplemented rather than imported: this module is consumed by the close
    gate, which ``scripts/cc-close`` runs under a bare ``python3``, so pulling
    pydantic onto that path would add a runtime dependency to a gate. The
    duplication is therefore *pinned by test* — ``TestSchemaParity`` round-trips
    every case through the real model, so a pydantic upgrade that changed the
    accepted spellings fails CI instead of silently reopening the parser-boundary
    fail-open this classifier exists to close.

    Deliberately does **not** strip quotes or whitespace: the schema rejects
    ``'"false"'`` and ``"  true  "``, so accepting either here would admit a
    declaration the schema calls invalid — in the ``"false"`` case silently
    disarming the gate.
    """

    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        if raw == 1:
            return True
        if raw == 0:
            return False
        return None
    if isinstance(raw, (str, bytes)):
        if isinstance(raw, bytes):
            try:
                raw = raw.decode("utf-8")
            except UnicodeDecodeError:
                return None
        token = raw.lower()
        if token in _INDEPENDENT_REVIEW_TRUTHY:
            return True
        if token in _INDEPENDENT_REVIEW_FALSY:
            return False
    return None


def _independent_review_state(container: Mapping[str, Any]) -> str:
    """Classify one container's ``review_requirement`` independent-review flag.

    Four outcomes, and the distinction between the last two is the whole point:

    - ``absent`` — no ``review_requirement`` key, or a block that simply does not
      mention ``independent_review_required``. Nothing is being claimed.
    - ``demanded`` / ``declined`` — the schema reads a boolean.
    - ``malformed`` — a ``review_requirement`` that is present but **not a
      mapping** (a list, a string, an empty key), or a flag whose value the
      schema rejects. The row is saying *something* about review that cannot be
      read.

    A present-but-unreadable declaration must never collapse into ``absent``:
    that is how ``review_requirement: [{independent_review_required: true}]``
    silently disarmed the gate while ``assess_route_metadata`` rejected the very
    same row. Unknown intent arms; only an explicit, schema-valid ``false``
    declines.
    """

    if "review_requirement" not in container:
        return _REVIEW_ABSENT
    block = container["review_requirement"]
    if not isinstance(block, Mapping):
        return _REVIEW_MALFORMED_CONTAINER
    if "independent_review_required" not in block:
        return _REVIEW_ABSENT
    verdict = _schema_bool(block["independent_review_required"])
    if verdict is None:
        return _REVIEW_MALFORMED
    return _REVIEW_DEMANDED if verdict else _REVIEW_DECLINED


def _independent_review_states(frontmatter: Mapping[str, Any]) -> tuple[str, ...]:
    """States of the top-level block and the ``route_metadata`` mirror.

    Each container in the lookup chain is classified independently, so a demand
    or an unreadable declaration in *either* arms the gate (fail-closed on
    disagreement) exactly as the floor lookup treats its own mirror.

    **Every level of the chain is checked for shape, not just the innermost.**
    A present-but-non-mapping container is ``malformed_container``, never
    skipped: skipping it discards whatever it holds. This bit twice — first a
    non-mapping ``review_requirement`` classified as absent, then a non-mapping
    ``route_metadata`` skipped outright, which silently discarded a review
    demand nested inside it. Both are the same error (treating "wrong shape" as
    "not present") at different depths, so the rule is stated once and applied
    at every level rather than patched per level.
    """

    states = [_independent_review_state(frontmatter)]
    if "route_metadata" in frontmatter:
        route_metadata = frontmatter["route_metadata"]
        if isinstance(route_metadata, Mapping):
            states.append(_independent_review_state(route_metadata))
        else:
            # Present but unreadable: the mirror cannot be consulted at all, so
            # anything it declares is invisible. Arm rather than assume it was
            # empty — assess_route_metadata rejects this shape outright.
            states.append(_REVIEW_MALFORMED_CONTAINER)
    return tuple(states)


def acceptance_receipt_triggers(frontmatter: Mapping[str, Any]) -> tuple[str, ...]:
    """Which declarations arm the acceptance-receipt gate; empty = not armed.

    Two independent triggers, either sufficient:

    - ``quality_floor: frontier_review_required`` (top-level or the
      ``route_metadata`` mirror), and
    - ``review_requirement.independent_review_required`` demanding review
      (likewise mirrored). The flag is normalized with the route schema's own
      boolean spellings — ``"true"``, ``"yes"``, ``"y"``, ``"on"``, ``"t"``,
      ``"1"``, ``1`` all demand — because this gate reads raw frontmatter while
      the schema reads a coercing ``bool`` field, and an identity test against
      Python ``True`` let a schema-valid demand spelled ``"true"`` disarm the
      gate entirely. A present-but-unrecognized value is reported as
      ``…:malformed`` and *also* arms: the schema rejects such values, so their
      intent is unknown, and an unknown review requirement may not read as no
      requirement.

    The second exists because the floor alone was not enough. Measured
    2026-09-13T21:53Z: a row carrying ``quality_floor: verification_receipt``
    *and* ``independent_review_required: true`` closed on the first plain
    ``cc-close`` with no receipt and no review — the block read as protective
    and was not load-bearing. A row may declare independent review mandatory
    under any floor, so the gate keys on the declaration, not only the floor.

    Returned as an ordered tuple rather than a bool so refusals can name the
    declaration that armed them (``executive_function``: a lane must be able to
    tell a misfire from its own row's demand). ``requires_acceptance_receipt``
    derives from this, so there is exactly one definition of "armed".
    """

    triggers: list[str] = []
    floors = {_frontmatter_scalar(frontmatter.get("quality_floor")).lower()}
    route_metadata = frontmatter.get("route_metadata")
    if isinstance(route_metadata, Mapping):
        floors.add(_frontmatter_scalar(route_metadata.get("quality_floor")).lower())
    if REVIEW_FLOOR_QUALITY_FLOOR in floors:
        triggers.append(RECEIPT_TRIGGER_REVIEW_FLOOR)
    states = _independent_review_states(frontmatter)
    # Both states are reported when both occur. A demand in one metadata location
    # does not excuse an unreadable declaration in the other: the gate would arm
    # either way, but suppressing the malformed state loses the very
    # reconstructability the malformed trigger exists to provide, and hides mirror
    # drift that assess_route_metadata would reject.
    if _REVIEW_DEMANDED in states:
        triggers.append(RECEIPT_TRIGGER_INDEPENDENT_REVIEW)
    if _REVIEW_MALFORMED in states:
        triggers.append(RECEIPT_TRIGGER_MALFORMED_REVIEW)
    if _REVIEW_MALFORMED_CONTAINER in states:
        triggers.append(RECEIPT_TRIGGER_MALFORMED_CONTAINER)
    return tuple(triggers)


def requires_acceptance_receipt(frontmatter: Mapping[str, Any]) -> bool:
    """True when the task's declarations demand a signed acceptance receipt.

    Thin derivation of :func:`acceptance_receipt_triggers` — see there for the
    triggers and why the review-floor test alone was insufficient. Kept as the
    boolean predicate because every close/dispatch caller asks only "armed?";
    callers that must *explain* the refusal use the trigger list directly.
    """

    return bool(acceptance_receipt_triggers(frontmatter))


def acceptance_receipt_blockers(frontmatter: Mapping[str, Any], note_path: Path) -> tuple[str, ...]:
    """Receipt blockers for a receipt-armed task; empty when the gate is unarmed.

    "Armed" is :func:`acceptance_receipt_triggers` — the review floor **or** a
    declared ``independent_review_required`` (see there). Not floor-only: a row
    may demand independent review under any quality floor.

    An armed note without a resolvable ``task_id`` fails closed with
    ``missing_acceptance_receipt`` — the receipt is keyed by task_id, so an
    anonymous note can never present one.
    """

    if not requires_acceptance_receipt(frontmatter):
        return ()
    task_id = _frontmatter_non_null_scalar(frontmatter.get("task_id"))
    if not task_id:
        return ("missing_acceptance_receipt",)
    return _acceptance_receipt_validity_blockers(acceptance_receipt_path(note_path, task_id))
