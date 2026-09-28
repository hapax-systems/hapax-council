"""Research-desk request queue and lookup domain.

The estate mints typed **research requests** as rows in the cc-task vault; an
external, subscription-funded agent lists them, fetches one, and delivers an
answer. Delivery lands at the dominator the coordinator already reads — a lanebus
drop — and stamps the request row.

Delete-the-estate statement: a queue of typed questions, a read surface over it,
and a write surface that files exactly one answer per question at a place the
reader already watches, with a receipt. The vault, the lanebus and Perplexity are
**bindings**: swap the row store for any keyed document store and the drop
directory for any append-only inbox and nothing in this module's shape changes.

Two boundaries are enforced here rather than at the transport:

* **Untrusted content.** The markdown an external agent delivers is written into
  the operator's vault. It is length-capped, control-character-screened, and
  labelled ``content_trust: untrusted_external`` in the drop's own frontmatter so
  a later reader cannot mistake it for estate-authored text.
* **Identity.** A request id is a filename stem matched against a strict pattern
  and resolved only inside the active-requests directory. There is no path the
  caller can spell that escapes it.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from shared.frontmatter import parse_frontmatter_with_diagnostics

# --------------------------------------------------------------------------- #
# Contract constants
# --------------------------------------------------------------------------- #

REQUEST_KIND = "research_request"
REQUEST_ROUTE_FAMILY = "perplexity-desk"

#: A row is visible to ``list_open_research_requests`` only while it carries one of
#: these. This is a positive list on purpose: an unrecognised status means the row
#: is not ours to serve, and the alternative (serve anything not on a terminal
#: list) spends subscription credits on rows somebody deliberately took out of the
#: queue with a spelling this module has never heard of.
OPEN_STATUSES: frozenset[str] = frozenset(("offered", "open", "queued"))
DELIVERED_STATUS = "delivered"

DEFAULT_VAULT_ROOT = Path.home() / "Documents" / "Personal"
REQUESTS_SUBPATH = Path("20-projects") / "hapax-cc-tasks" / "active"
LANEBUS_SUBPATH = Path("30-areas") / "hapax" / "lanebus"
DEFAULT_DELIVERY_LANE = "cx-blue"

#: Local (never NFS) state root. Per-request delivery locks live here.
DEFAULT_STATE_ROOT = Path.home() / ".cache" / "hapax" / "research-desk"

MAX_LIST_LIMIT = 50
DEFAULT_LIST_LIMIT = 10
MAX_MARKDOWN_BYTES = 256 * 1024
MAX_MODEL_NOTES_BYTES = 8 * 1024
MAX_CITATIONS = 64
MAX_CITATION_URL_CHARS = 2048
MAX_CITATION_TITLE_CHARS = 512
MAX_REQUEST_BODY_BYTES = 128 * 1024

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_STATUS_LINE_RE = re.compile(r"^status:[ \t].*$|^status:$", re.MULTILINE)
#: Control characters that have no business in vault markdown. Tab, newline and
#: carriage return are excluded because they are ordinary markdown.
_FORBIDDEN_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_URL_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

#: Cheap byte screen before the YAML parse. ``active/`` holds >1200 engineering rows
#: on NFS; parsing every one of them to find a handful of desk rows costs a second
#: per list call. This is a PREFILTER, never the authority — a row that passes it is
#: still admitted only by :func:`_is_desk_row` on the parsed frontmatter.
_DESK_ROW_PREFILTER_RE = re.compile(
    rf"^route_family:\s*{re.escape(REQUEST_ROUTE_FAMILY)}\s*$", re.MULTILINE
)

_STAMP_FIELDS = ("delivered_at", "delivery_receipt", "delivery_drop", "delivery_citations")

#: The one URI-scheme allowlist the desk applies to every URI it writes, wherever it
#: appears — a citation, a markdown link, an image target. Citations refuse; body URIs
#: are neutralised instead, because refusing a whole answer over one stray `mailto:`
#: costs a research run and teaches the agent nothing.
ALLOWED_URI_SCHEMES: frozenset[str] = frozenset(("http", "https"))

#: A markdown destination, allowing one level of nested parentheses — ``alert(1)``,
#: ``..._(disambiguation)``. A target pattern that stops at the FIRST ``)`` truncates
#: those and leaves litter behind; worse, ``\(\s*`` is load-bearing, because CommonMark
#: permits whitespace between ``(`` and the destination and a pattern without it reads
#: the target as empty — which scores as "no scheme" and lets ``[x]( javascript:… )``
#: through as a live link. Both found by the tests below, not by inspection.
_MD_TARGET = r"(?:[^()\s]|\([^()\s]*\))*"
_MD_LABEL = r"(?:[^\[\]]|\[[^\[\]]*\])*"
_MD_IMAGE_DEST_RE = re.compile(rf"\(\s*(?P<target>{_MD_TARGET})(?P<rest>[^)]*)\)")
_MAX_IMAGE_LABEL_DEPTH = 16
_MD_LINK_RE = re.compile(
    rf"(?<!!)\[(?P<text>{_MD_LABEL})\]\(\s*(?P<target>{_MD_TARGET})(?P<rest>[^)]*)\)"
)
_RAW_IMG_RE = re.compile(r"<\s*img\b[^>]*>", re.IGNORECASE)
_AUTOLINK_RE = re.compile(r"<(?P<uri>[A-Za-z][A-Za-z0-9+.-]*:[^>\s]*)>")


# --------------------------------------------------------------------------- #
# Typed refusals
# --------------------------------------------------------------------------- #


class ResearchDeskError(RuntimeError):
    """A typed refusal carrying the next action, per the executive_function axiom."""

    def __init__(self, reason_code: str, repair_action: str, detail: str | None = None) -> None:
        self.reason_code = reason_code
        self.repair_action = repair_action
        self.detail = detail
        message = f"{reason_code}: {repair_action}"
        if detail:
            message += f" ({detail})"
        super().__init__(message)

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": False,
            "reason_code": self.reason_code,
            "next_action": self.repair_action,
            "detail": self.detail,
        }


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ResearchDeskConfig:
    """Where the desk reads requests and writes deliveries.

    Every root is injectable so the tests exercise the real code against a tmp
    tree rather than a mock of it.
    """

    vault_root: Path = DEFAULT_VAULT_ROOT
    state_root: Path = DEFAULT_STATE_ROOT
    delivery_lane: str = DEFAULT_DELIVERY_LANE

    @property
    def requests_dir(self) -> Path:
        return self.vault_root / REQUESTS_SUBPATH

    @property
    def lanebus_dir(self) -> Path:
        return self.vault_root / LANEBUS_SUBPATH / self.delivery_lane

    @property
    def lock_dir(self) -> Path:
        return self.state_root / "locks"

    @classmethod
    def from_env(cls, env: dict[str, str] | os._Environ[str] | None = None) -> ResearchDeskConfig:
        source = os.environ if env is None else env

        def _path(name: str, default: Path) -> Path:
            raw = source.get(name, "").strip()
            return Path(raw).expanduser() if raw else default

        lane = source.get("HAPAX_RESEARCH_DESK_LANE", "").strip() or DEFAULT_DELIVERY_LANE
        if "/" in lane or lane in {"", ".", ".."}:
            raise ResearchDeskError(
                "delivery_lane_invalid",
                "set HAPAX_RESEARCH_DESK_LANE to a single lanebus directory name, e.g. cx-blue",
                detail=f"got {lane!r}",
            )
        return cls(
            vault_root=_path("HAPAX_RESEARCH_DESK_VAULT_ROOT", DEFAULT_VAULT_ROOT),
            state_root=_path("HAPAX_RESEARCH_DESK_STATE_ROOT", DEFAULT_STATE_ROOT),
            delivery_lane=lane,
        )


# --------------------------------------------------------------------------- #
# Request model
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ResearchRequest:
    request_id: str
    path: Path
    status: str
    title: str
    question: str
    constraints: tuple[str, ...]
    deadline: str | None
    priority: str | None
    created_at: str | None
    brief: str
    frontmatter: dict[str, Any] = field(repr=False, default_factory=dict)

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES

    def summary(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "title": self.title,
            "question": self.question,
            "constraints": list(self.constraints),
            "deadline": self.deadline,
            "priority": self.priority,
            "status": self.status,
        }

    def full(self) -> dict[str, Any]:
        payload = self.summary()
        payload["created_at"] = self.created_at
        payload["brief"] = self.brief
        return payload


@dataclass(frozen=True)
class MalformedRequest:
    request_id: str
    reason_code: str
    detail: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "reason_code": self.reason_code,
            "detail": self.detail,
        }


# Queue helpers


def validate_request_id(request_id: str) -> str:
    """Return the id, or refuse. The only gate between a caller and the filesystem."""
    candidate = (request_id or "").strip()
    if not _REQUEST_ID_RE.match(candidate):
        raise ResearchDeskError(
            "request_id_invalid",
            "call list_open_research_requests and pass one of the request_id values it returns",
            detail=f"got {request_id!r}",
        )
    return candidate


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if str(item).strip())
    return (str(value),)


@dataclass(frozen=True)
class NeutralizedBody:
    """Delivered markdown with its active content removed, and a count of what went."""

    markdown: str
    images: int
    links: int

    @property
    def total(self) -> int:
        return self.images + self.links


def _display_target(target: str) -> str:
    """The destination as shown inside a defang marker.

    Angle brackets are stripped: a marker that still contained ``<scheme:…>`` would be
    re-matched by the autolink pass that runs after this one and defanged a second
    time, nesting the marker and double-counting what was withheld. Found by the
    angle-bracket destination case in the smuggling test.
    """
    return target.strip().strip("<>").strip()


def _scheme_of(target: str) -> str:
    candidate = _display_target(target)
    if candidate.startswith("#") or candidate.startswith("/") or candidate.startswith("."):
        return ""  # a fragment or a relative path carries no scheme and no active content
    parsed = urlparse(candidate)
    return parsed.scheme.lower()


def neutralize_markdown(body: str) -> NeutralizedBody:
    """Strip active content from delivered markdown. Total: never raises, never refuses.

    Two rules, one hazard each:

    * **Every image becomes a link.** An image target auto-loads when the drop is
      opened, which turns any URL the external agent chooses into a read receipt on
      the operator's vault — no click required. Demoting images to links removes the
      auto-load without losing the reference. This applies whatever the scheme,
      because the hazard is the auto-load, not the protocol.
    * **Every link whose scheme is not http/https is defanged to inert text.** Same
      allowlist the citations use — ``file:``, ``javascript:``, ``data:`` are not
      references, they are actions, and a vault reader renders them as live.

    Both rules only ever *remove* capability from the content, which is why they can
    be total: there is no input for which neutralising is unsafe, so there is no
    failure branch to get wrong. What survives is counted and reported in the drop's
    frontmatter, so the control is visible rather than silent.

    What this does NOT catch, stated rather than implied: raw HTML other than
    ``<img>``, and a plain http(s) URL written as bare text that a reader turns into
    a link. Neither auto-loads.
    """
    images = 0
    links = 0

    def _images(text: str) -> str:
        nonlocal images
        parts: list[str] = []
        cursor = 0
        while (start := text.find("![", cursor)) != -1:
            parts.append(text[cursor:start])
            depth = 1
            over_cap = False
            pos = start + 2
            while pos < len(text) and depth:
                if text[pos] == "[":
                    depth += 1
                    over_cap |= depth > _MAX_IMAGE_LABEL_DEPTH
                elif text[pos] == "]":
                    depth -= 1
                pos += 1
            destination = _MD_IMAGE_DEST_RE.match(text, pos) if depth == 0 else None
            if destination is None or over_cap:
                # A malformed or excessively nested label may still contain a
                # renderable image. Consume its entire apparent target, and never
                # copy attacker-controlled markdown back into the output.
                close = text.find(")", start + 2)
                cursor = len(text) if close == -1 else close + 1
                parts.append("`[image withheld]`")
            else:
                cursor = destination.end()
                target = destination.group("target")
                alt = text[start + 2 : pos - 1].strip()
                label = f"image withheld — {alt}" if alt and "[" not in alt else "image withheld"
                if _scheme_of(target) in ALLOWED_URI_SCHEMES:
                    parts.append(f"[{label}]({target})")
                else:
                    parts.append(f"`[{label}: {_display_target(target)}]`")
            images += 1
        parts.append(text[cursor:])
        return "".join(parts)

    def _raw_img(match: re.Match[str]) -> str:
        nonlocal images
        images += 1
        return f"`{match.group(0)}`"

    def _link(match: re.Match[str]) -> str:
        nonlocal links
        target = match.group("target")
        scheme = _scheme_of(target)
        if not scheme or scheme in ALLOWED_URI_SCHEMES:
            return match.group(0)
        links += 1
        return f"{match.group('text')} `[link withheld — {scheme}: {_display_target(target)}]`"

    def _autolink(match: re.Match[str]) -> str:
        nonlocal links
        uri = match.group("uri")
        if _scheme_of(uri) in ALLOWED_URI_SCHEMES:
            return match.group(0)
        links += 1
        return f"`[link withheld — {uri}]`"

    out = _images(body)
    out = _RAW_IMG_RE.sub(_raw_img, out)
    out = _MD_LINK_RE.sub(_link, out)
    out = _AUTOLINK_RE.sub(_autolink, out)
    return NeutralizedBody(markdown=out, images=images, links=links)


# --------------------------------------------------------------------------- #
# Reading the queue
# --------------------------------------------------------------------------- #


def _request_path(config: ResearchDeskConfig, request_id: str) -> Path:
    return config.requests_dir / f"{request_id}.md"


def _parse_request(path: Path, text: str | None = None) -> ResearchRequest | MalformedRequest:
    """Parse one candidate row through the canonical estate parser."""
    request_id = path.stem
    result = parse_frontmatter_with_diagnostics(path if text is None else text)
    if not result.ok or result.frontmatter is None:
        return MalformedRequest(
            request_id=request_id,
            reason_code=f"frontmatter_{result.error_kind or 'unreadable'}",
            detail=result.error_message or "frontmatter did not parse",
        )
    fm = result.frontmatter
    declared_id = str(fm.get("task_id") or fm.get("request_id") or request_id)
    if declared_id != request_id:
        return MalformedRequest(
            request_id=request_id,
            reason_code="request_id_mismatch",
            detail=f"frontmatter declares {declared_id!r} but the file is {request_id}.md",
        )
    question = str(fm.get("question") or "").strip()
    if not question:
        return MalformedRequest(
            request_id=request_id,
            reason_code="question_absent",
            detail="a research_request row must carry a non-empty `question:` in frontmatter",
        )
    status = str(fm.get("status") or "").strip()
    if not status:
        return MalformedRequest(
            request_id=request_id,
            reason_code="status_absent",
            detail="a research_request row must carry a `status:` line",
        )
    brief = result.body
    if len(brief.encode("utf-8")) > MAX_REQUEST_BODY_BYTES:
        brief = brief.encode("utf-8")[:MAX_REQUEST_BODY_BYTES].decode("utf-8", "ignore")
        brief += "\n\n[brief truncated by the research desk at 128 KiB]"
    return ResearchRequest(
        request_id=request_id,
        path=path,
        status=status,
        title=str(fm.get("title") or request_id),
        question=question,
        constraints=_as_str_tuple(fm.get("constraints")),
        deadline=(str(fm["deadline"]) if fm.get("deadline") else None),
        priority=(str(fm["priority"]) if fm.get("priority") else None),
        created_at=(str(fm["created_at"]) if fm.get("created_at") else None),
        brief=brief,
        frontmatter=fm,
    )


def _is_desk_row(fm: dict[str, Any]) -> bool:
    return (
        str(fm.get("kind") or "").strip() == REQUEST_KIND
        and str(fm.get("route_family") or "").strip() == REQUEST_ROUTE_FAMILY
    )


def iter_desk_rows(config: ResearchDeskConfig) -> list[ResearchRequest | MalformedRequest]:
    """Every ``research_request`` / ``perplexity-desk`` row under ``active/``.

    A row that fails the kind/route_family test is not ours and is skipped
    silently — that is the whole active-tasks directory, and reporting every
    engineering task as "malformed" would bury the signal. A row that IS ours and
    fails to parse is reported.
    """
    requests_dir = config.requests_dir
    if not requests_dir.is_dir():
        raise ResearchDeskError(
            "requests_dir_absent",
            f"create {requests_dir} or set HAPAX_RESEARCH_DESK_VAULT_ROOT to the vault root",
            detail=str(requests_dir),
        )
    found: list[ResearchRequest | MalformedRequest] = []
    for path in sorted(requests_dir.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if not _DESK_ROW_PREFILTER_RE.search(text):
            continue
        probe = parse_frontmatter_with_diagnostics(text)
        if not probe.ok or probe.frontmatter is None or not _is_desk_row(probe.frontmatter):
            continue
        found.append(_parse_request(path, text))
    return found


def list_open_requests(
    config: ResearchDeskConfig, limit: int = DEFAULT_LIST_LIMIT
) -> tuple[list[ResearchRequest], list[MalformedRequest]]:
    """Open requests, newest-priority-first, plus every desk row that failed to parse."""
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise ResearchDeskError(
            "limit_invalid", "pass limit as an integer between 1 and 50", detail=repr(limit)
        )
    if limit < 1 or limit > MAX_LIST_LIMIT:
        raise ResearchDeskError(
            "limit_out_of_range",
            f"pass limit between 1 and {MAX_LIST_LIMIT}",
            detail=f"got {limit}",
        )
    rows = iter_desk_rows(config)
    malformed = [row for row in rows if isinstance(row, MalformedRequest)]
    openable = [row for row in rows if isinstance(row, ResearchRequest) and row.is_open]
    openable.sort(key=lambda r: (_priority_rank(r.priority), r.created_at or "", r.request_id))
    return openable[:limit], malformed


def _priority_rank(priority: str | None) -> int:
    order = {"p0": 0, "p1": 1, "p2": 2, "p3": 3}
    return order.get((priority or "").strip().lower(), 9)


def get_request(config: ResearchDeskConfig, request_id: str) -> ResearchRequest:
    """One request by id, whatever its status. Read-only."""
    request_id = validate_request_id(request_id)
    path = _request_path(config, request_id)
    if not path.is_file():
        raise ResearchDeskError(
            "request_not_found",
            "call list_open_research_requests for the current ids",
            detail=f"no active research request {request_id!r}",
        )
    text = path.read_text(encoding="utf-8")
    probe = parse_frontmatter_with_diagnostics(text)
    if not probe.ok or probe.frontmatter is None or not _is_desk_row(probe.frontmatter):
        raise ResearchDeskError(
            "request_not_found",
            "call list_open_research_requests for the current ids",
            detail=(
                f"{request_id!r} exists but is not a {REQUEST_KIND} row "
                f"on route_family {REQUEST_ROUTE_FAMILY}"
            ),
        )
    parsed = _parse_request(path, text)
    if isinstance(parsed, MalformedRequest):
        raise ResearchDeskError(
            "request_malformed",
            "fix the request row in the vault, then retry",
            detail=f"{parsed.reason_code}: {parsed.detail}",
        )
    return parsed


# --------------------------------------------------------------------------- #
