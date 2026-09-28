"""Recompute the ENCOUNTERED-MACHINERY roll-up index and evaluate the disposition ladder.

Operator, 2026-09-25 ~01:20Z: "establish a trigger that goes like this: ENCOUNTERED-MACHINERY gains
property X or fulfills test Y -> Do something about it. The reason we have this document is to
reduce accidental complexity. We need to make sure that happens in a methodical way were the pile
gets smaller."

The ladder already exists (``MECHANISM-DISPOSITION-THRESHOLDS-20260914.md``, adopted 09-14):
count 2 means a disposition is owed, count 3 means a same-day repair row with a change of shape,
and an unclaimed row escalates after 24 h. Its §Enforcement names this auditor as "a row to mint
(small)". Nobody minted it, and the coordinator seat stopped hand-maintaining the index for
M75–M115. A representation with no enforcement degrades into a record.

This module is pure. It parses two authored documents and evaluates T1–T9 over them, and it
performs no I/O. ``scripts/hapax-encountered-machinery-audit`` owns reading, minting, posting and
writing, and ``hapax-determine`` owns the cadence and witnesses each run.

- **The catalogue** holds entries and statuses. It has many writers and uses several entry shapes:
  headings, line-start prose, bullets, and two kinds of table. Statuses are read append-only: the
  latest ``status`` cell for an id wins, in document order.
- **The class ledger** is a table in the thresholds document. It holds the class, its members and
  weights, the disposition and the row. It is authored judgment, because a hazard class is a
  failure shape and cannot be derived from text.

Every ambiguity resolves toward a *larger* pile, never a smaller one:

- an unknown or missing status counts as OPEN;
- LIVE without a readback stays in the pile as FIX-IN-FLIGHT;
- an ambiguous update is applied to no entry.

A metric that can be lowered by writing vaguer statuses would be gamed by exactly the drift it
measures.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import yaml

STATUS_VOCAB: tuple[str, ...] = ("FIX-IN-FLIGHT", "OPEN", "LIVE", "RETIRED", "ACCEPTED")
#: Statuses that take an entry out of the pile. LIVE leaves only with a readback (T6).
TERMINAL_STATUSES = frozenset({"RETIRED", "ACCEPTED"})
#: Tokens that count as activation readback evidence on a LIVE status row.
READBACK_RE = re.compile(r"read ?-?back|measured passing", re.IGNORECASE)
#: A readback token that is negated ("no activation readback recorded", "without readback",
#: "readback missing") is evidence of its ABSENCE. These clauses are removed before searching.
NEGATED_READBACK_RE = re.compile(
    r"\b(?:no|not|without|lacks?|lacking|missing)\b[^.;|]*?read ?-?back"
    r"|read ?-?back\s+(?:missing|absent|pending|owed|not\b)",
    re.IGNORECASE,
)
#: The ledger class outside the ladder and the pile.
RETAINED_CLASS = "retained"
#: Essential/accidental judgment (operator, 2026-09-25 ~01:50Z: "pile is reshaped and reconstituted
#: until it only contains what ought to be ... essential vs accident"). Made with the catalogue's
#: own 08-21 test: is the intention valid; if so, what is its fundamental expression and proper
#: placement; if not, what follows from removal?
#:   RETAIN        essential, already in its fundamental form; the justification must be written
#:   RECONSTITUTE  essential intention in an accidental form; rebuild it rightly placed
#:   REMOVE        accidental; retire it (archive, never delete)
JUDGMENT_VOCAB: tuple[str, ...] = ("RECONSTITUTE", "REMOVE", "RETAIN")
#: T8: an entry older than this with no judgment goes to the seat.
JUDGMENT_OWED_AFTER = timedelta(days=7)

DISPOSITION_ABSENT_RE = re.compile(r"^\s*(?:|—|-|tbd|owed\b.*)\s*$", re.IGNORECASE | re.DOTALL)
TASK_ID_RE = re.compile(r"\b[a-z0-9]+(?:-[a-z0-9]+)*-20\d{6}\b")
PR_RE = re.compile(r"#\d+\b")
_ID_CELL_RE = re.compile(r"^M(\d+)([a-z]?)(.*)$", re.DOTALL)
_UNNUMBERED_RE = re.compile(r"^\(new,\s*([A-Za-z0-9_-]+)\)")
_MEMBER_RE = re.compile(r"^(M\d+[a-z]?|new-[A-Za-z0-9_-]+)\s*(?:[×x]\s*(\d+))?$")
_FULL_DATE_RE = re.compile(r"(20\d\d)-(\d\d)-(\d\d)")
_ENCOUNTERED_RE = re.compile(r"encountered (\d\d)-(\d\d)")
_PROSE_DEF_RES = (
    re.compile(r"^### M(\d+)\b"),
    re.compile(r"^- M(\d+) \(encountered"),
    re.compile(r"^M(\d+) \S"),
)

#: Ladder thresholds (MECHANISM-DISPOSITION-THRESHOLDS §Quantitative ladder).
SMELL_COUNT = 2
PROOF_COUNT = 3
CONCENTRATION_OPEN = 3
OWNER_ROW_STALE = timedelta(hours=24)
IN_FLIGHT_OWNER_STATUSES = frozenset({"claimed", "in_progress"})


class LedgerError(ValueError):
    """The class ledger cannot be read. The message names the next action."""


def canonical_id(raw: str) -> str:
    """``M1``/``M01`` → ``M01``; ``M104b`` → ``M104b``; ``new-x`` unchanged."""
    m = re.match(r"^M0*(\d+)([a-z]?)$", raw)
    if not m:
        return raw
    return f"M{int(m.group(1)):02d}{m.group(2)}"


def split_cells(line: str) -> list[str]:
    """Split a markdown table row on pipes outside backtick spans."""
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    cells: list[str] = []
    buf: list[str] = []
    in_code = False
    for ch in body:
        if ch == "`":
            in_code = not in_code
        if ch == "|" and not in_code:
            cells.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    cells.append("".join(buf).strip())
    return cells


def _is_separator(line: str) -> bool:
    cells = split_cells(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", c) for c in cells)


def normalize_status(raw: str | None) -> str | None:
    return _normalize(raw, STATUS_VOCAB)


def normalize_judgment(raw: str | None) -> str | None:
    return _normalize(raw, JUDGMENT_VOCAB)


def _normalize(raw: str | None, vocab: tuple[str, ...]) -> str | None:
    if not raw:
        return None
    text = raw.strip()
    for word in vocab:
        if text == word or re.match(rf"^{re.escape(word)}(?=[\s(,;.:]|$)", text):
            return word
    return None


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end < 0:
        return {}, text
    try:
        data = yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError:
        data = {}
    return (data if isinstance(data, dict) else {}), text[end + 4 :].lstrip("\n")


# ---------------------------------------------------------------------------------------------
# Catalogue


@dataclass
class Entry:
    id: str
    line: int
    shape: str  # table | prose | unnumbered
    encountered: datetime | None
    status_raw: str | None = None
    status_evidence: str = ""
    status_line: int | None = None
    witness: str | None = None
    owner: str | None = None
    judgment_raw: str | None = None
    justification: str = ""
    walls: tuple[str, ...] = ()


@dataclass
class Catalogue:
    entries: dict[str, Entry]
    hygiene: list[tuple[str, str]] = field(default_factory=list)  # (subject, detail)


@dataclass
class _Record:
    kind: str  # def | update
    raw_id: str
    line: int
    status: str | None
    evidence: str
    witness: str | None
    owner: str | None
    encountered: datetime | None
    shape: str
    judgment: str | None = None
    justification: str = ""
    walls: tuple[str, ...] = ()


def _walls_of(cell: str | None) -> tuple[str, ...]:
    """Wall ids cited by a judgment (the wall catalogue owns their names; none invented here)."""
    if not cell:
        return ()
    return tuple(t for t in (x.strip().strip("`") for x in re.split(r"[,\s]+", cell)) if t)


def _date_of(text: str, context: datetime | None) -> datetime | None:
    m = _FULL_DATE_RE.search(text)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=UTC)
        except ValueError:
            return context
    m = _ENCOUNTERED_RE.search(text)
    if m and context is not None:
        try:
            return datetime(context.year, int(m.group(1)), int(m.group(2)), tzinfo=UTC)
        except ValueError:
            return context
    return context


def parse_catalogue(text: str) -> Catalogue:
    records: list[_Record] = []
    hygiene: list[tuple[str, str]] = []
    headers: list[list[str]] = []  # headers seen in the current `##` section
    context_date: datetime | None = None
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        lineno = idx + 1
        stripped = line.strip()
        if line.startswith("## "):
            headers = []
        if line.startswith("#") or line.startswith("**") or line.startswith("- 20"):
            context_date = _date_of(line, context_date)
        if stripped.startswith("|"):
            if _is_separator(stripped):
                continue
            nxt = lines[idx + 1].strip() if idx + 1 < len(lines) else ""
            if nxt.startswith("|") and _is_separator(nxt):
                headers.append([c.lower() for c in split_cells(stripped)])
                continue
            cells = split_cells(stripped)
            header = next((h for h in reversed(headers) if len(h) == len(cells)), None)
            if header is None:
                continue
            rec = _table_record(cells, header, lineno, context_date)
            if rec is not None:
                records.append(rec)
            continue
        for rx in _PROSE_DEF_RES:
            m = rx.match(line)
            if m:
                records.append(
                    _Record(
                        kind="def",
                        raw_id=canonical_id(f"M{m.group(1)}"),
                        line=lineno,
                        status=None,
                        evidence="",
                        witness=None,
                        owner=None,
                        encountered=_date_of(line, context_date),
                        shape="prose",
                    )
                )
                break
    return _resolve(records, hygiene)


def _table_record(
    cells: list[str], header: list[str], lineno: int, context: datetime | None
) -> _Record | None:
    first_head = header[0]
    col = {name: i for i, name in enumerate(header)}
    first = cells[0]
    status_i = col.get("status")
    status = cells[status_i] if status_i is not None else None
    if first_head == "m":
        m = _ID_CELL_RE.match(first)
        if not m:
            return None
        ev_i = col.get("evidence")
        judg_i = col.get("judgment")
        just_i = col.get("justification", ev_i)
        return _Record(
            kind="update",
            raw_id=canonical_id(f"M{m.group(1)}{m.group(2)}"),
            line=lineno,
            status=status,
            evidence=cells[ev_i] if ev_i is not None else "",
            witness=None,
            owner=None,
            encountered=None,
            shape="table",
            judgment=cells[judg_i] if judg_i is not None else None,
            justification=cells[just_i] if just_i is not None else "",
            walls=_walls_of(cells[col["walls"]]) if "walls" in col else (),
        )
    if first_head not in {"#", "id / binding"}:
        return None
    witness = cells[col["witness"]] if "witness" in col else None
    owner = cells[col["owner / disposition"]] if "owner / disposition" in col else None
    encountered = _date_of(" ".join(cells), context)
    un = _UNNUMBERED_RE.match(first)
    if un:
        return _Record(
            "def",
            f"new-{un.group(1)}",
            lineno,
            status,
            "",
            witness,
            owner,
            encountered,
            "unnumbered",
        )
    m = _ID_CELL_RE.match(first)
    if not m:
        return None
    rid = canonical_id(f"M{m.group(1)}{m.group(2)}")
    kind = "update" if m.group(3).strip().startswith("(") else "def"
    return _Record(kind, rid, lineno, status, "", witness, owner, encountered, "table")


def _resolve(records: list[_Record], hygiene: list[tuple[str, str]]) -> Catalogue:
    # Duplicate ids are counted among table definitions only; prose re-mentions are follow-ups.
    table_defs: dict[str, list[_Record]] = {}
    for r in records:
        if r.kind == "def" and r.shape == "table":
            table_defs.setdefault(r.raw_id, []).append(r)
    rename: dict[int, str] = {}
    duplicated: set[str] = set()
    for rid, defs in table_defs.items():
        if len(defs) > 1:
            duplicated.add(rid)
            lines = ", ".join(str(d.line) for d in defs)
            hygiene.append((rid, f"id defined twice: table rows at lines {lines}; cite with a/b"))
            for n, d in enumerate(defs):
                rename[d.line] = f"{rid}{chr(ord('a') + n)}"

    entries: dict[str, Entry] = {}
    for r in records:
        if r.kind != "def":
            continue
        eid = rename.get(r.line, r.raw_id)
        if eid in entries:
            continue  # prose follow-up, or a prose definition later tabled
        entries[eid] = Entry(
            id=eid,
            line=r.line,
            shape=r.shape,
            encountered=r.encountered,
            witness=r.witness,
            owner=r.owner,
        )
        if r.shape == "unnumbered":
            hygiene.append((eid, "no M-number: the seat mints the number"))

    for r in records:
        if r.status is None and r.judgment is None:
            continue
        if r.kind == "def":
            target = rename.get(r.line, r.raw_id)
        else:
            target = r.raw_id
            if target in duplicated:
                hygiene.append((target, f"ambiguous status update at line {r.line}: cite a or b"))
                continue
        entry = entries.get(target)
        if entry is None:
            hygiene.append((target, f"status update at line {r.line} for an undefined entry"))
            continue
        if r.status is not None and r.status.strip():
            entry.status_raw = r.status
            entry.status_evidence = r.evidence
            entry.status_line = r.line
        if r.judgment is not None and r.judgment.strip():
            entry.judgment_raw = r.judgment
            entry.justification = r.justification
            entry.walls = r.walls
    for entry in entries.values():
        if entry.shape in {"table", "unnumbered"} and entry.witness is not None:
            if not entry.witness.strip():
                hygiene.append((entry.id, "no witness"))
            if entry.owner is not None and not entry.owner.strip():
                hygiene.append((entry.id, "no owner"))
    return Catalogue(entries=entries, hygiene=hygiene)


# ---------------------------------------------------------------------------------------------
# Class ledger


@dataclass(frozen=True)
class LedgerClass:
    key: str
    title: str
    members: tuple[tuple[str, int], ...]
    disposition: str
    rows: tuple[str, ...]
    prs: tuple[str, ...]
    bad_members: tuple[str, ...] = ()

    @property
    def disposition_named(self) -> bool:
        return not DISPOSITION_ABSENT_RE.match(self.disposition)

    @property
    def has_row(self) -> bool:
        return bool(self.rows or self.prs)


def parse_ledger(text: str) -> list[LedgerClass]:
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.startswith("## Class ledger")), None)
    if start is None:
        raise LedgerError(
            "no '## Class ledger' section; next action: restore the ledger table in "
            "MECHANISM-DISPOSITION-THRESHOLDS-20260914.md"
        )
    header: list[str] | None = None
    classes: list[LedgerClass] = []
    for i in range(start + 1, len(lines)):
        ln = lines[i].strip()
        if lines[i].startswith("## "):
            break
        if not ln.startswith("|"):
            if header is not None and classes:
                break
            continue
        if _is_separator(ln):
            continue
        cells = split_cells(ln)
        if header is None:
            header = [c.lower() for c in cells]
            if not {"class", "members", "disposition", "row"} <= set(header):
                raise LedgerError(
                    f"ledger header {header} lacks class/members/disposition/row; next action: "
                    "restore the four-column ledger header"
                )
            continue
        col = {name: n for n, name in enumerate(header)}
        if len(cells) != len(header):
            raise LedgerError(
                f"ledger row {i + 1} has {len(cells)} cells, expected {len(header)}; next action: "
                "give the row one cell per header column (class | members | disposition | row), "
                "escaping any literal '|' inside a cell"
            )
        klass = cells[col["class"]]
        km = re.search(r"`([^`]+)`", klass)
        if not km:
            raise LedgerError(
                f"ledger row {i + 1}: class cell has no backticked key; next action: start the "
                "class cell with the class key in backticks, e.g. `gate-predicate-reads-proxy`: …"
            )
        members: list[tuple[str, int]] = []
        bad: list[str] = []
        for tok in (t.strip() for t in cells[col["members"]].split(",")):
            if not tok:
                continue
            mm = _MEMBER_RE.match(tok)
            if not mm:
                bad.append(tok)
                continue
            members.append((canonical_id(mm.group(1)), int(mm.group(2) or 1)))
        row_cell = cells[col["row"]]
        classes.append(
            LedgerClass(
                key=km.group(1),
                title=klass,
                members=tuple(members),
                disposition=cells[col["disposition"]],
                rows=tuple(dict.fromkeys(TASK_ID_RE.findall(row_cell))),
                prs=tuple(dict.fromkeys(PR_RE.findall(row_cell))),
                bad_members=tuple(bad),
            )
        )
    if not classes:
        raise LedgerError("class ledger table is empty; next action: restore its rows")
    return classes


# ---------------------------------------------------------------------------------------------
# Evaluation


@dataclass(frozen=True)
class OwnerRow:
    task_id: str
    status: str | None
    created_at: datetime | None
    updated_at: datetime | None


@dataclass(frozen=True)
class TrendPoint:
    label: str
    share: float  # accidental share (the primary metric)
    pile: int  # weighted pile (secondary)
    entries: int
    live: int  # entries LIVE with a readback


@dataclass(frozen=True)
class Trend:
    """Points at −14 d, −7 d and now. Fewer than three points means unobserved."""

    points: tuple[TrendPoint, ...]
    note: str

    @classmethod
    def unobserved(cls, note: str) -> Trend:
        return cls(points=(), note=note)


@dataclass(frozen=True)
class Flag:
    trigger: str
    subject: str
    detail: str

    @property
    def key(self) -> str:
        return f"{self.trigger}|{self.subject}|{self.detail}"


@dataclass(frozen=True)
class EntryState:
    id: str
    klass: str | None
    weight: int
    status: str | None
    effective: str
    in_pile: bool
    encountered: datetime | None
    judgment: str | None = None
    accidental: bool = True  # unjudged, or judged REMOVE and not yet removed
    gone: bool = False  # judged REMOVE and RETIRED: it has left the pile


@dataclass
class ClassState:
    key: str
    weighted: int
    pile_weight: int
    open_ids: list[str]
    pile_ids: list[str]
    disposition: str
    disposition_named: bool
    rows: tuple[str, ...]
    prs: tuple[str, ...]
    oldest_open: datetime | None
    score: float
    next_threshold: str


@dataclass(frozen=True)
class MintCandidate:
    kind: str  # reduce | sweep
    subject: str
    triggers: tuple[str, ...]
    score: float


@dataclass
class Audit:
    entry_state: dict[str, EntryState]
    class_state: dict[str, ClassState]
    flags: list[Flag]
    mint_candidates: list[MintCandidate]
    weighted_pile: int
    counts: dict[str, int]
    age_buckets: dict[str, int]
    trend: Trend
    trend_verdict: str
    accidental_weight: int = 0
    total_weight: int = 0
    unjudged: int = 0
    unjudged_weight: int = 0
    awaiting_reconstitution: list[str] = field(default_factory=list)
    live_readback: int = 0
    entries: int = 0

    @property
    def accidental_share(self) -> float:
        return round(self.accidental_weight / self.total_weight, 4) if self.total_weight else 0.0

    def point(self, label: str) -> TrendPoint:
        return TrendPoint(
            label, self.accidental_share, self.weighted_pile, self.entries, self.live_readback
        )

    @property
    def flag_fingerprint(self) -> str:
        blob = "\n".join(sorted(f.key for f in self.flags))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _effective(entry: Entry) -> tuple[str | None, str, bool]:
    """(normalized status, effective status, readback present)."""
    status = normalize_status(entry.status_raw)
    if status is None:
        return None, "OPEN", False
    if status == "LIVE":
        evidence = NEGATED_READBACK_RE.sub(" ", f"{entry.status_raw} {entry.status_evidence}")
        if READBACK_RE.search(evidence):
            return status, "LIVE", True
        return status, "FIX-IN-FLIGHT", False
    return status, status, False


def evaluate(
    catalogue: Catalogue,
    ledger: Iterable[LedgerClass],
    *,
    now: datetime,
    owner_rows: Mapping[str, OwnerRow | None],
    trend: Trend,
    wall_judgments: Mapping[str, str | None] | None = None,
) -> Audit:
    """``wall_judgments`` maps wall id → RETAIN/RECONSTITUTE/REMOVE (or None when unjudged).
    The wall catalogue (row ``wall-catalogue-and-judgment-basis-20260925``) supplies it; until
    then it is None and T9 is not evaluated. Walls are never invented here."""
    ledger = list(ledger)
    flags: list[Flag] = [Flag("T7", s, d) for s, d in catalogue.hygiene]
    member_class: dict[str, tuple[str, int]] = {}
    for c in ledger:
        for bad in c.bad_members:
            flags.append(Flag("T7", c.key, f"unparseable ledger member {bad!r}"))
        for mid, weight in c.members:
            if mid in member_class:
                flags.append(Flag("T7", mid, f"in two classes: {member_class[mid][0]} and {c.key}"))
                continue
            member_class[mid] = (c.key, weight)
            if mid not in catalogue.entries:
                flags.append(Flag("T7", mid, f"ledger member not in catalogue: class {c.key}"))

    states: dict[str, EntryState] = {}
    for eid, entry in catalogue.entries.items():
        status, effective, _ = _effective(entry)
        klass, weight = member_class.get(eid, (None, 1))
        if klass is None:
            flags.append(Flag("T7", eid, "in no class: add it to the class ledger"))
        if entry.status_raw is None:
            flags.append(Flag("T7", eid, "no status: add a status row"))
        elif status is None:
            flags.append(
                Flag("T7", eid, f"status outside the vocabulary: {entry.status_raw[:60]!r}")
            )
        if status == "LIVE" and effective != "LIVE":
            flags.append(Flag("T6", eid, "LIVE with no readback: counted as FIX-IN-FLIGHT"))
        judgment = normalize_judgment(entry.judgment_raw)
        if entry.judgment_raw and judgment is None:
            flags.append(
                Flag("T7", eid, f"judgment outside the vocabulary: {entry.judgment_raw[:60]!r}")
            )
        if judgment == "RETAIN" and len(entry.justification.strip()) < 8:
            # "Each needs its justification written, never merely assumed."
            flags.append(Flag("T7", eid, "RETAIN with no written justification: counted unjudged"))
            judgment = None
        if judgment is not None:
            if not entry.walls:
                flags.append(Flag("T7", eid, "judgment cites no wall ids"))
            elif wall_judgments is not None:
                # T9: a judgment is only as sound as the walls it stands on.
                weak = [
                    w
                    for w in entry.walls
                    if normalize_judgment(wall_judgments.get(w)) not in {"RETAIN", "RECONSTITUTE"}
                ]
                if weak:
                    flags.append(
                        Flag(
                            "T9",
                            eid,
                            "judgment rests on unjudged, accidental or unknown walls: "
                            + ", ".join(weak),
                        )
                    )
        hazard = klass is not None and klass != RETAINED_CLASS
        in_pile = effective not in TERMINAL_STATUSES and effective != "LIVE"
        gone = judgment == "REMOVE" and effective == "RETIRED"
        states[eid] = EntryState(
            id=eid,
            klass=klass,
            weight=weight,
            status=status,
            effective=effective,
            in_pile=in_pile and (hazard or klass is None),
            encountered=entry.encountered,
            judgment=judgment,
            accidental=(judgment is None or judgment == "REMOVE") and not gone,
            gone=gone,
        )

    class_states: dict[str, ClassState] = {}
    candidates: list[MintCandidate] = []
    for c in ledger:
        if c.key == RETAINED_CLASS:
            continue
        present = [(mid, w) for mid, w in c.members if mid in states]
        weighted = sum(w for _, w in present)
        pile = [mid for mid, _ in present if states[mid].in_pile]
        open_ids = [mid for mid in pile if states[mid].effective == "OPEN"]
        pile_weight = sum(w for mid, w in present if states[mid].in_pile)
        dates: list[datetime] = [d for m in pile if (d := states[m].encountered) is not None]
        oldest = min(dates) if dates else None
        age_days = max((now - oldest).days, 1) if oldest else 1
        score = float(pile_weight * age_days)
        state = ClassState(
            key=c.key,
            weighted=weighted,
            pile_weight=pile_weight,
            open_ids=open_ids,
            pile_ids=pile,
            disposition=c.disposition,
            disposition_named=c.disposition_named,
            rows=c.rows,
            prs=c.prs,
            oldest_open=oldest,
            score=score,
            next_threshold=_next_threshold(weighted, c),
        )
        class_states[c.key] = state
        if not pile:
            continue
        triggers: list[str] = []
        if weighted >= SMELL_COUNT and not c.disposition_named:
            flags.append(Flag("T1", c.key, f"weighted {weighted}: disposition owed"))
        if weighted >= PROOF_COUNT and not c.has_row:
            flags.append(Flag("T2", c.key, f"weighted {weighted} with no repair row"))
            triggers.append("T2")
        if len(open_ids) >= CONCENTRATION_OPEN:
            flags.append(Flag("T4", c.key, f"{len(open_ids)} OPEN entries: {', '.join(open_ids)}"))
            triggers.append("T4")
        if open_ids:
            flags.extend(_owner_row_flags(c, owner_rows, now))
        if triggers:
            candidates.append(MintCandidate("reduce", c.key, tuple(triggers), score))

    # T8: judgment owed. Aggregated per class so the seat judges a class's entries together.
    owed: dict[str, list[str]] = {}
    for s in states.values():
        if s.judgment is not None or s.gone:
            continue
        if s.encountered is None or now - s.encountered > JUDGMENT_OWED_AFTER:
            owed.setdefault(s.klass or "unclassified", []).append(s.id)
    for klass, ids in sorted(owed.items()):
        flags.append(
            Flag(
                "T8",
                klass,
                f"{len(ids)} entries older than 7 d with no essential/accidental judgment: "
                + ", ".join(ids),
            )
        )

    # T5: the accidental share must fall. A shrinking pile of accidents is still failure.
    verdict = "unobserved"
    if len(trend.points) >= 3:
        a, b, c3 = (p.share for p in trend.points[-3:])
        if c3 == 0:
            verdict = "at_zero"
        elif b >= a and c3 >= b:
            verdict = "not_falling"
            flags.append(
                Flag(
                    "T5",
                    "pile",
                    f"accidental share has not fallen for two windows: {a:.0%} → {b:.0%} → "
                    f"{c3:.0%}",
                )
            )
            week = now.isocalendar()
            candidates.append(
                MintCandidate("sweep", f"{week.year}w{week.week:02d}", ("T5",), c3 * 1000)
            )
        elif c3 < b:
            verdict = "falling"
        else:
            verdict = "mixed"

    universe = [s for s in states.values() if not s.gone]
    pile_states = [s for s in states.values() if s.in_pile]
    counts: dict[str, int] = {}
    for s in states.values():
        if s.klass == RETAINED_CLASS:
            counts["retained"] = counts.get("retained", 0) + 1
            continue
        counts[s.effective] = counts.get(s.effective, 0) + 1
    ages = {"<1d": 0, "1-7d": 0, "7-14d": 0, ">14d": 0, "undated": 0}
    for s in pile_states:
        if s.encountered is None:
            ages["undated"] += 1
            continue
        d = (now - s.encountered).days
        ages["<1d" if d < 1 else "1-7d" if d < 7 else "7-14d" if d < 14 else ">14d"] += 1
    candidates.sort(key=lambda m: (-m.score, m.kind, m.subject))
    return Audit(
        entry_state=states,
        class_state=class_states,
        flags=flags,
        mint_candidates=candidates,
        weighted_pile=sum(s.weight for s in pile_states),
        counts=counts,
        age_buckets=ages,
        trend=trend,
        trend_verdict=verdict,
        accidental_weight=sum(s.weight for s in universe if s.accidental),
        total_weight=sum(s.weight for s in universe),
        unjudged=sum(1 for s in universe if s.judgment is None),
        unjudged_weight=sum(s.weight for s in universe if s.judgment is None),
        awaiting_reconstitution=sorted(
            s.id for s in universe if s.judgment == "RECONSTITUTE" and s.effective != "LIVE"
        ),
        live_readback=sum(1 for s in states.values() if s.effective == "LIVE"),
        entries=len(states),
    )


def _owner_row_flags(
    c: LedgerClass, owner_rows: Mapping[str, OwnerRow | None], now: datetime
) -> list[Flag]:
    out: list[Flag] = []
    for task_id in c.rows:
        row = owner_rows.get(task_id)
        if row is None:
            out.append(Flag("T3", c.key, f"owner row {task_id} not in the task store"))
            continue
        status = (row.status or "").lower()
        created = row.created_at or _date_from_task_id(task_id)
        if status == "offered" and created is not None and now - created > OWNER_ROW_STALE:
            hours = int((now - created).total_seconds() // 3600)
            out.append(
                Flag(
                    "T3",
                    c.key,
                    f"owner row {task_id} offered and unclaimed for {hours} h: escalate to p1 "
                    "and re-route (one lossiness instance)",
                )
            )
        elif status in IN_FLIGHT_OWNER_STATUSES:
            touched = row.updated_at or created
            if touched is not None and now - touched > OWNER_ROW_STALE:
                hours = int((now - touched).total_seconds() // 3600)
                out.append(
                    Flag(
                        "T3",
                        c.key,
                        f"owner row {task_id} {status} with no note change for {hours} h: "
                        "escalate to p1 and re-route (one lossiness instance)",
                    )
                )
    return out


def _date_from_task_id(task_id: str) -> datetime | None:
    m = re.search(r"-(20\d\d)(\d\d)(\d\d)$", task_id)
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=UTC)
    except ValueError:
        return None


def _next_threshold(weighted: int, c: LedgerClass) -> str:
    if weighted < SMELL_COUNT:
        return "count 2: disposition owed"
    if weighted < PROOF_COUNT:
        return (
            "count 3: repair row owed same day" if c.disposition_named else "disposition owed now"
        )
    if not c.has_row:
        return "repair row owed now (shape must change)"
    return "row must change the shape; a further encounter is proof it did not"


# ---------------------------------------------------------------------------------------------
# Rendering


def render_pile_status(
    audit: Audit,
    *,
    auto_rows: Iterable[str],
    posted_fingerprint: str,
    sources: Mapping[str, str],
) -> str:
    """The derived block embedded at the top of the catalogue. Deterministic for equal inputs.

    No run timestamp appears in the body: hapax-determine's ledger witnesses runs, and a body that
    changes every hour would rewrite an NFS file and mint a vault commit for nothing.
    """
    front = {
        "type": "derived",
        "generated_by": "scripts/hapax-encountered-machinery-audit",
        "do_not_edit": True,
        "flag_fingerprint": audit.flag_fingerprint,
        "posted_flag_fingerprint": posted_fingerprint,
        "accidental_share": audit.accidental_share,
        "weighted_pile": audit.weighted_pile,
        "trend": audit.trend_verdict,
    }
    lines = ["---", yaml.safe_dump(front, sort_keys=False).strip(), "---", ""]
    conversions = ""
    if len(audit.trend.points) >= 2:
        prev, cur = audit.trend.points[-2], audit.trend.points[-1]
        conversions = (
            f" · last 7 d: {cur.live - prev.live} converted to LIVE-with-readback against "
            f"{cur.entries - prev.entries} new entries"
        )
    lines += [
        "> [!summary] Pile status (derived; regenerated by the auditor, never hand-edited)",
        "> The pile is reshaped and reconstituted until it contains only what ought to be: "
        "essential vs accident. Target: accidental share 0.",
        f"> **Accidental share: {audit.accidental_share:.0%}** ({audit.accidental_weight} of "
        f"{audit.total_weight} weighted: unjudged, or judged REMOVE and not yet removed). "
        f"Trend: {audit.trend_verdict}"
        + (f" ({_trend_text(audit.trend)})" if audit.trend.points else f" ({audit.trend.note})"),
        f"> Unjudged: {audit.unjudged} entries (weight {audit.unjudged_weight}) · essentials "
        f"awaiting reconstitution: {len(audit.awaiting_reconstitution)}"
        + (
            f" ({', '.join(audit.awaiting_reconstitution)})"
            if audit.awaiting_reconstitution
            else ""
        )
        + f" · LIVE with readback: {audit.live_readback} of {audit.entries} entries{conversions}",
        f"> Secondary: weighted OPEN pile {audit.weighted_pile} · "
        + " · ".join(f"{k} {v}" for k, v in sorted(audit.counts.items())),
        "> Pile age: " + " · ".join(f"{k} {v}" for k, v in audit.age_buckets.items()),
        f"> Sources: catalogue `{sources.get('catalogue', '')}`; ledger "
        f"`{sources.get('ledger', '')}`",
        "",
        "| class | weighted | pile (weight) | OPEN | disposition | row | next threshold |",
        "|---|---|---|---|---|---|---|",
    ]
    for cs in sorted(audit.class_state.values(), key=lambda s: (-s.score, s.key)):
        rows = " ".join([*cs.rows, *cs.prs]) or "—"
        disp = cs.disposition if cs.disposition_named else "**owed**"
        lines.append(
            f"| `{cs.key}` | {cs.weighted} | {len(cs.pile_ids)} ({cs.pile_weight}) | "
            f"{len(cs.open_ids)} | {_cell(disp)} | {_cell(rows)} | {cs.next_threshold} |"
        )
    lines += ["", f"**Flags ({len(audit.flags)}):**", ""]
    for trig in ("T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "T9"):
        group = [f for f in audit.flags if f.trigger == trig]
        if group:
            lines.append(
                f"- **{trig}** ({len(group)}): "
                + "; ".join(f"`{f.subject}` {f.detail}" for f in group)
            )
    auto = list(auto_rows)
    lines += ["", "**Open auto-minted rows:** " + (", ".join(f"`{r}`" for r in auto) or "none")]
    return "\n".join(lines) + "\n"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _trend_text(trend: Trend) -> str:
    return " → ".join(f"{p.label} {p.share:.0%} (pile {p.pile})" for p in trend.points)


def render_reduction_row(
    candidate: MintCandidate,
    audit: Audit,
    *,
    task_id: str,
    now: datetime,
    parent_spec: str,
    catalogue_ref: str,
) -> str:
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    if candidate.kind == "sweep":
        title = (
            f"Pile reconstitution sweep {candidate.subject}: the ENCOUNTERED-MACHINERY accidental "
            "share has not fallen for two windows"
        )
        ranked = sorted(audit.class_state.values(), key=lambda s: (-s.score, s.key))
        evidence = [
            f"- `{cs.key}`: pile weight {cs.pile_weight}, score {cs.score:.0f}, entries "
            f"{', '.join(cs.pile_ids)}"
            for cs in ranked
            if cs.pile_ids
        ]
        objective = (
            f"Accidental share is {audit.accidental_share:.0%} ({audit.unjudged} entries unjudged). "
            "Drive it toward zero: judge each entry essential or accidental with the catalogue's "
            "08-21 test, then reconstitute, remove, or retain it with a written justification. "
            "Work the classes in the ranked order below (weighted count × age)."
        )
    else:
        cs = audit.class_state[candidate.subject]
        title = (
            f"Reconstitute or remove hazard class `{cs.key}`: judge essential vs accident, then "
            "change the shape rather than patch it"
        )
        evidence = [
            f"- {mid}: {audit.entry_state[mid].effective}, weight {audit.entry_state[mid].weight}, "
            f"judgment {audit.entry_state[mid].judgment or 'none'}"
            for mid in cs.pile_ids
        ]
        objective = (
            f"Class `{cs.key}` fired {', '.join(candidate.triggers)} (weighted {cs.weighted}, "
            f"{len(cs.open_ids)} OPEN, pile weight {cs.pile_weight}). Apply the 08-21 test to the "
            "shared mechanism behind its entries. Is the intention valid? If so, reconstitute it "
            "as its fundamental expression, rightly placed. If not, remove it (archive, never "
            "delete) and account for what follows."
        )
    front: dict[str, Any] = {
        "type": "cc-task",
        "task_id": task_id,
        "title": title,
        "status": "offered",
        "assigned_to": "unassigned",
        "blocked_reason": None,
        "priority": "p1",
        "wsjf": 13,
        "effort_class": "medium",
        "kind": "build",
        "risk_tier": "T2",
        "quality_floor": "frontier_review_required",
        "authority_level": "support_non_authoritative",
        "mutation_surface": "source",
        "depends_on": [],
        "blocks": [],
        "related": ["encountered-machinery-auditor-trigger-20260925"],
        "branch": None,
        "pr": None,
        "created_at": stamp,
        "updated_at": stamp,
        "claimed_at": None,
        "completed_at": None,
        "parent_request": None,
        "parent_spec": parent_spec,
        "authority_case": None,
        "stage": "S2_INTAKE",
        "implementation_authorized": False,
        "source_mutation_authorized": False,
        "docs_mutation_authorized": False,
        "runtime_mutation_authorized": False,
        "release_authorized": False,
        "mutation_scope_refs": [],
        "encountered_machinery_trigger": list(candidate.triggers),
        "encountered_machinery_subject": candidate.subject,
        "tags": ["cc-task", "encountered-machinery", "auto-minted", candidate.kind],
    }
    body = [
        f"# {title}",
        "",
        "## Objective",
        "",
        objective,
        "",
        "## Evidence (derived at mint time)",
        "",
        *evidence,
        "",
        f"Catalogue: `{catalogue_ref}`. Ladder and class ledger: `{parent_spec}`.",
        "",
        "## Exit predicate",
        "",
        "- Every listed entry carries a judgment row in the catalogue (RETAIN with a written",
        "  justification, RECONSTITUTE, or REMOVE).",
        "- REMOVE entries are RETIRED; RECONSTITUTE entries are LIVE with an activation readback.",
        "- Same shape again is prohibited: another hand-application of an existing mitigation does not",
        "  satisfy this row (the zeta rule: two mitigations for one hazard is a smell, three is proof).",
        "- A further encounter of this class after close is evidence that the shape did not change.",
        "",
        "## Authority",
        "",
        "Minted by the auditor with authority unset. The coordinator seat grants scope and authority.",
        "",
        "## Session log",
        "",
        f"- {stamp} encountered-machinery-audit: minted on {', '.join(candidate.triggers)}.",
    ]
    return (
        "---\n"
        + yaml.safe_dump(front, sort_keys=False, allow_unicode=True)
        + "---\n\n"
        + "\n".join(body)
        + "\n"
    )


def render_flag_drop(
    audit: Audit,
    *,
    sender: str,
    recipient: str,
    now: datetime,
    minted: Iterable[str],
    deferred: Iterable[str],
    status_ref: str,
) -> str:
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        "---",
        f"from: {sender}",
        f"to: {recipient}",
        f"created_at: {stamp}",
        "thread: encountered-machinery-audit",
        "kind: flags",
        "ack: false",
        "---",
        "",
        f"# Encountered-machinery audit: {len(audit.flags)} flags, accidental share "
        f"{audit.accidental_share:.0%} ({audit.trend_verdict}), weighted pile {audit.weighted_pile}",
        "",
        f"The flag set changed (fingerprint `{audit.flag_fingerprint}`). The pile status is at "
        f"`{status_ref}`.",
        "",
    ]
    for trig in ("T3", "T2", "T4", "T5", "T8", "T9", "T1", "T6", "T7"):
        group = [f for f in audit.flags if f.trigger == trig]
        if not group:
            continue
        lines.append(f"## {trig} ({len(group)})")
        lines.append("")
        lines += [f"- `{f.subject}`: {f.detail}" for f in group]
        lines.append("")
    minted = list(minted)
    deferred = list(deferred)
    lines.append("## Rows")
    lines.append("")
    lines.append(
        "Minted offered with authority unset, for you to grant: "
        + (", ".join(f"`{m}`" for m in minted) or "none")
    )
    lines.append("")
    lines.append("Deferred by the WIP cap: " + (", ".join(f"`{d}`" for d in deferred) or "none"))
    lines.append("")
    lines.append(
        "T3 escalations are requests: the auditor does not edit other lanes' rows. Apply p1 "
        "where you agree."
    )
    return "\n".join(lines) + "\n"
