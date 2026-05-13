"""PastebinArtifactPublisher — chronicle digest + programme-plan publisher.

Phase A (#1306): chronicle.weekly_digest category.
Phase B (this PR): programme.completed_plan category.
Phase C (follow-on): axiom.precedent_operator_authority.
Phase D (follow-on): research.corpus_excerpt.

The publisher class carries one method per category; each category
is backed by a ``build_<category>_digest`` / ``build_<category>_slug``
pair plus a source-loader callback injected at construction.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
import unicodedata
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from agents.publication_bus.omg_pastebin_publisher import OmgLolPastebinPublisher
from agents.publication_bus.publisher_kit import PublisherPayload
from shared.governance.omg_referent import OperatorNameLeak, safe_render
from shared.governance.publication_allowlist import check as allowlist_check


def _content_sha_excluding_compiled_stamp(content: str) -> str:
    """SHA-256 of digest content with the ``_digest compiled:`` line stripped.

    Closes the idempotency-flake bug surfaced by epsilon's inflection
    20260426T034000Z. Each ``build_*_digest`` builder appends a
    ``_digest compiled: <real-time-now>_`` metadata line; if two
    consecutive ``publish_*`` calls straddle a second boundary (CI is
    typically slower than local), the SHAs differ and the
    "already published" short-circuit fails to fire — the second call
    re-publishes instead of returning ``"unchanged"``.

    Stripping the line before hashing keeps the SHA stable across
    second-boundary calls without changing the published content (the
    timestamp metadata is still rendered into the posted paste).
    """
    body = "\n".join(
        line for line in content.splitlines() if not line.lstrip().startswith("_digest compiled:")
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


log = logging.getLogger(__name__)

SURFACE = "omg-lol-pastebin"
DEFAULT_ADDRESS = "hapax"
DEFAULT_CHRONICLE_FILE = Path("/dev/shm/hapax-chronicle/events.jsonl")
DEFAULT_PROGRAMMES_DIR = Path.home() / "hapax-state" / "programmes"
DEFAULT_STATE_FILE = Path.home() / ".cache" / "hapax" / "hapax-omg-pastebin" / "state.json"


def _publish_pastebin(client: Any, *, address: str, slug: str, content: str) -> bool:
    result = OmgLolPastebinPublisher(client=client).publish(
        PublisherPayload(
            target=address,
            text=content,
            metadata={"title": slug, "listed": True},
        )
    )
    return result.ok


try:
    from prometheus_client import Counter

    _PUBLISH_TOTAL = Counter(
        "hapax_broadcast_omg_pastebin_publishes_total",
        "omg.lol pastebin artifact publishes by category + outcome.",
        ["category", "result"],
    )

    def _record(category: str, outcome: str) -> None:
        _PUBLISH_TOTAL.labels(category=category, result=outcome).inc()
except ImportError:

    def _record(category: str, outcome: str) -> None:
        log.debug("prometheus_client unavailable; metric dropped")


# ── Chronicle digest ────────────────────────────────────────────────────


def build_chronicle_slug(week_start: date) -> str:
    """Deterministic slug for a chronicle weekly digest.

    ISO week numbers; same week always produces the same slug so
    re-publish is idempotent.
    """
    iso_year, iso_week, _ = week_start.isocalendar()
    return f"chronicle-{iso_year}-w{iso_week:02d}"


def build_chronicle_digest(
    *,
    events: list[dict[str, Any]],
    week_start: date,
    min_salience: float = 0.7,
) -> str:
    """Render a plain-text digest of high-salience chronicle events for
    the given ISO week. Returns empty string when no events qualify."""
    window_start = datetime.combine(week_start, datetime.min.time(), tzinfo=UTC)
    window_end = window_start + timedelta(days=7)

    filtered = []
    for ev in events:
        ts_str = ev.get("ts", "")
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        salience = ev.get("salience", 0.0)
        if not isinstance(salience, (int, float)) or salience < min_salience:
            continue
        if not (window_start <= ts < window_end):
            continue
        filtered.append((ts, ev))

    if not filtered:
        return ""

    filtered.sort(key=lambda pair: pair[0])
    iso_year, iso_week, _ = week_start.isocalendar()

    lines = [
        f"# hapax chronicle — {iso_year} week {iso_week:02d}",
        "",
        f"{len(filtered)} high-salience moments ({min_salience:.2f} threshold).",
        "",
    ]
    for ts, ev in filtered:
        stamp = ts.strftime("%Y-%m-%d %H:%M")
        summary = ev.get("summary") or ev.get("narrative") or "(untitled)"
        source = ev.get("source", "unknown")
        lines.append(f"- {stamp} — [{source}] {summary}")

    lines.append("")
    lines.append(f"_digest compiled: {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}_")
    return "\n".join(lines) + "\n"


def _load_events(path: Path) -> list[dict[str, Any]]:
    """Soft-read JSONL event log; skip malformed lines."""
    try:
        raw = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return []
    out: list[dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


# ── Programme-plan digest (Phase B) ───────────────────────────────────────


def _slug_sanitise(raw: str) -> str:
    """Lowercase, ASCII-only, kebab-cased slug fragment."""
    ascii_str = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
    lowered = ascii_str.lower()
    kebab = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return kebab or "untitled"


def build_programme_slug(programme_id: str) -> str:
    """Deterministic slug for a completed programme plan."""
    return f"programme-{_slug_sanitise(programme_id)}"


def build_programme_digest(*, programme: dict[str, Any]) -> str:
    """Render a completed programme plan as a plain-text digest.

    Returns empty string when the programme is not marked completed —
    the contract is that only completed plans publish (active plans
    are ephemeral).

    Accepts an optional ``sections`` list under programme keys; each
    entry with ``title`` and ``body`` renders as ``## title`` + body.
    """
    if programme.get("status") != "completed":
        return ""

    title = programme.get("title", "Untitled programme")
    summary = programme.get("summary", "")
    completed_at = programme.get("completed_at", "")
    sections = programme.get("sections") or []

    lines: list[str] = [f"# {title}", ""]
    if completed_at:
        # Accept ISO datetime; render the date portion.
        stamp = completed_at.split("T", 1)[0] if "T" in completed_at else completed_at
        lines.append(f"_completed: {stamp}_")
        lines.append("")
    if summary:
        lines.append(summary)
        lines.append("")
    for section in sections:
        if not isinstance(section, dict):
            continue
        s_title = section.get("title")
        s_body = section.get("body", "")
        if not s_title:
            continue
        lines.append(f"## {s_title}")
        lines.append("")
        if s_body:
            lines.append(str(s_body))
            lines.append("")
    lines.append(f"_digest compiled: {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}_")
    return "\n".join(lines) + "\n"


# ── Axiom-precedent digest (Phase C) ──────────────────────────────────────


def build_precedent_slug(precedent_id: str) -> str:
    """Deterministic slug for an axiom-precedent paste."""
    return f"precedent-{_slug_sanitise(precedent_id)}"


def build_precedent_digest(*, precedent: dict[str, Any]) -> str:
    """Render an axiom-precedent record as a plain-text digest.

    Returns empty string when the precedent lacks a ``precedent_id``
    (the addressable identity is required for any responsible publish).
    Other fields are rendered if present; absent fields are skipped.

    Source files are expected to be authored impersonal (see
    ``axioms/precedents/sp-hsea-mg-001.yaml`` for the canonical
    shape) — string-content redaction is NOT applied at the
    publisher layer; PII-free authoring is the contract.
    """
    precedent_id = precedent.get("precedent_id")
    if not precedent_id:
        return ""

    short_name = precedent.get("short_name", "")
    axiom_id = precedent.get("axiom_id", "")
    secondary = precedent.get("secondary_axioms") or []
    version = precedent.get("version")
    situation = precedent.get("situation", "")
    decision = precedent.get("decision", "")
    reasoning = precedent.get("reasoning", "")

    title_bits = [precedent_id]
    if short_name:
        title_bits.append(short_name)
    title = " — ".join(title_bits)

    lines: list[str] = [f"# {title}", ""]
    meta_bits: list[str] = []
    if axiom_id:
        meta_bits.append(f"axiom: `{axiom_id}`")
    if secondary:
        meta_bits.append(f"secondary: {', '.join(f'`{a}`' for a in secondary)}")
    if version is not None:
        meta_bits.append(f"v{version}")
    if meta_bits:
        lines.append("_" + " · ".join(meta_bits) + "_")
        lines.append("")
    if situation:
        lines.append("## Situation")
        lines.append("")
        lines.append(str(situation).rstrip())
        lines.append("")
    if decision:
        lines.append("## Decision")
        lines.append("")
        lines.append(str(decision).rstrip())
        lines.append("")
    if reasoning:
        lines.append("## Reasoning")
        lines.append("")
        lines.append(str(reasoning).rstrip())
        lines.append("")
    lines.append(f"_digest compiled: {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}_")
    return "\n".join(lines) + "\n"


# ── Research-corpus digest (Phase D) ──────────────────────────────────────


def build_research_slug(research_id: str) -> str:
    """Deterministic slug for a research-corpus paste."""
    return f"research-{_slug_sanitise(research_id)}"


def build_research_digest(*, research: dict[str, Any]) -> str:
    """Render a research-corpus excerpt as a plain-text digest.

    Default-deny gate: returns empty string unless the research dict
    explicitly carries ``publish: True``. Operator authors set the flag
    per-document; pre-attribution drafts (publication contract redaction
    ``research.pre_attribution``) stay unpublished by default.

    Returns empty string if ``research_id`` missing.
    """
    if not research.get("publish"):
        return ""
    research_id = research.get("research_id")
    if not research_id:
        return ""

    title = research.get("title", research_id)
    body = research.get("body", "")
    extracted_date = research.get("extracted_date", "")

    lines: list[str] = [f"# {title}", ""]
    if extracted_date:
        lines.append(f"_extracted: {extracted_date}_")
        lines.append("")
    if body:
        lines.append(str(body).rstrip())
        lines.append("")
    lines.append(f"_digest compiled: {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}_")
    return "\n".join(lines) + "\n"


def read_research_from_dir(directory: Path) -> list[dict[str, Any]]:
    """Soft-read research markdown files with YAML frontmatter.

    Treats the body (after the closing ``---``) as the document
    content; assigns it to the ``body`` key in the parsed dict.
    Documents without parseable frontmatter are skipped.
    """
    if not directory.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if not text.startswith("---\n"):
            continue
        end = text.find("\n---\n", 4)
        if end == -1:
            continue
        try:
            frontmatter = yaml.safe_load(text[4:end])
        except yaml.YAMLError:
            continue
        if not isinstance(frontmatter, dict):
            continue
        body = text[end + len("\n---\n") :].strip()
        record = {**frontmatter, "body": body}
        out.append(record)
    return out


def read_precedents_from_dir(directory: Path) -> list[dict[str, Any]]:
    """Soft-read top-level ``*.yaml`` precedent files.

    Excludes any subdirectories (notably ``seed/`` which holds
    templates). Missing directory → empty list. Malformed files are
    silently skipped.
    """
    if not directory.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.yaml")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
            data = yaml.safe_load(text)
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(data, dict):
            out.append(data)
    return out


def read_programmes_from_dir(directory: Path) -> list[dict[str, Any]]:
    """Soft-read ``{programme}.md`` files with YAML frontmatter.

    Missing directory → empty list. Files without parseable frontmatter
    are skipped silently — matches the "graceful source" pattern used
    by the weblog composer.
    """
    if not directory.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for md_path in sorted(directory.glob("*.md")):
        try:
            text = md_path.read_text(encoding="utf-8")
        except OSError:
            continue
        if not text.startswith("---\n"):
            continue
        end = text.find("\n---\n", 4)
        if end == -1:
            continue
        try:
            frontmatter = yaml.safe_load(text[4:end])
        except yaml.YAMLError:
            continue
        if isinstance(frontmatter, dict):
            out.append(frontmatter)
    return out


class PastebinArtifactPublisher:
    """Publish chronicle-weekly-digest pastes to omg.lol.

    Parameters:
        client:                  OmgLolClient (may be disabled)
        state_file:              per-publish state (idempotence tracking)
        read_events:             callable returning list[dict] events
        now_fn:                  callable returning current UTC datetime
        address:                 omg.lol address (default ``hapax``)
        min_salience:            event threshold for inclusion (default 0.7)
    """

    CATEGORY_CHRONICLE = "chronicle.weekly_digest"
    CATEGORY_PROGRAMME = "programme.completed_plan"
    CATEGORY_PRECEDENT = "axiom.precedent_operator_authority"
    CATEGORY_RESEARCH = "research.corpus_excerpt"

    def __init__(
        self,
        *,
        client: Any,
        state_file: Path,
        read_events: Callable[[], list[dict[str, Any]]],
        now_fn: Callable[[], datetime],
        address: str = DEFAULT_ADDRESS,
        min_salience: float = 0.7,
        read_programmes: Callable[[], list[dict[str, Any]]] | None = None,
        read_precedents: Callable[[], list[dict[str, Any]]] | None = None,
        read_research: Callable[[], list[dict[str, Any]]] | None = None,
    ) -> None:
        self.client = client
        self.state_file = state_file
        self._read_events = read_events
        self._now_fn = now_fn
        self.address = address
        self.min_salience = min_salience
        # Default loaders are empty-list so existing call sites keep
        # working without adjustment. Each new category adds an optional
        # loader; call sites that want a category pass their own loader.
        self._read_programmes: Callable[[], list[dict[str, Any]]] = read_programmes or (lambda: [])
        self._read_precedents: Callable[[], list[dict[str, Any]]] = read_precedents or (lambda: [])
        self._read_research: Callable[[], list[dict[str, Any]]] = read_research or (lambda: [])

    def _read_state(self) -> dict:
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _write_state(self, state: dict) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_name(f"{self.state_file.name}.tmp.{uuid.uuid4().hex}")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(self.state_file)

    def _safe_render_or_drop(self, content: str, slug: str, category: str) -> str | None:
        """AUDIT-05: scan content for legal-name leak + substitute
        ``{operator}`` token before publish.

        Returns redacted content, or ``None`` if a leak was detected
        (caller bails with ``"legal-name-leak"`` outcome).
        """
        try:
            return safe_render(content, segment_id=slug)
        except OperatorNameLeak:
            log.warning("omg-pastebin: legal-name leak detected — DROPPING (%s)", slug)
            _record(category, "legal-name-leak")
            return None

    def publish_chronicle_week(self, week_start: date, *, dry_run: bool = False) -> str:
        """Compose + publish (or update) the digest for the given ISO week.

        Returns one of ``"published"`` | ``"unchanged"`` | ``"empty"`` |
        ``"allowlist-denied"`` | ``"client-disabled"`` | ``"dry-run"`` |
        ``"failed"``.
        """
        events = self._read_events()
        content = build_chronicle_digest(
            events=events, week_start=week_start, min_salience=self.min_salience
        )
        if not content:
            _record(self.CATEGORY_CHRONICLE, "empty")
            return "empty"

        slug = build_chronicle_slug(week_start)

        allow = allowlist_check(
            SURFACE,
            self.CATEGORY_CHRONICLE,
            {"summary": f"{slug}: {len(events)} events", "events": events},
        )
        if allow.decision == "deny":
            log.info("omg-pastebin: allowlist denied chronicle digest (%s)", allow.reason)
            _record(self.CATEGORY_CHRONICLE, "allowlist-denied")
            return "allowlist-denied"

        state_key = f"digest_sha_{slug}"

        content_sha = _content_sha_excluding_compiled_stamp(content)
        persisted = self._read_state()
        if persisted.get(state_key) == content_sha:
            _record(self.CATEGORY_CHRONICLE, "unchanged")
            return "unchanged"

        if dry_run:
            log.info(
                "omg-pastebin: dry-run — chronicle digest %s (sha %s…)",
                slug,
                content_sha[:8],
            )
            _record(self.CATEGORY_CHRONICLE, "dry-run")
            return "dry-run"

        if not getattr(self.client, "enabled", False):
            log.warning("omg-pastebin: client disabled — skipping publish")
            _record(self.CATEGORY_CHRONICLE, "client-disabled")
            return "client-disabled"

        redacted = self._safe_render_or_drop(content, slug, self.CATEGORY_CHRONICLE)
        if redacted is None:
            return "legal-name-leak"
        if not _publish_pastebin(self.client, address=self.address, slug=slug, content=redacted):
            log.warning("omg-pastebin: set_paste returned None (%s)", slug)
            _record(self.CATEGORY_CHRONICLE, "failed")
            return "failed"

        persisted[state_key] = content_sha
        self._write_state(persisted)
        log.info("omg-pastebin: published chronicle digest %s", slug)
        _record(self.CATEGORY_CHRONICLE, "published")
        return "published"

    def publish_current_week(self, *, dry_run: bool = False) -> str:
        """Convenience: publish digest for the ISO week containing now."""
        now = self._now_fn()
        iso_year, iso_week, _ = now.isocalendar()
        # Monday of the ISO week.
        week_start = date.fromisocalendar(iso_year, iso_week, 1)
        return self.publish_chronicle_week(week_start, dry_run=dry_run)

    def publish_programme(self, programme_id: str, *, dry_run: bool = False) -> str:
        """Compose + publish (or update) the digest for a completed programme.

        Returns one of the same outcome codes as
        :meth:`publish_chronicle_week`. ``"empty"`` covers both
        "programme not found" and "programme is not completed" (the
        contract is that only completed plans publish).
        """
        programmes = self._read_programmes()
        match = next(
            (p for p in programmes if p.get("programme_id") == programme_id),
            None,
        )
        if match is None:
            _record(self.CATEGORY_PROGRAMME, "empty")
            return "empty"

        content = build_programme_digest(programme=match)
        if not content:
            _record(self.CATEGORY_PROGRAMME, "empty")
            return "empty"

        slug = build_programme_slug(programme_id)

        allow = allowlist_check(
            SURFACE,
            self.CATEGORY_PROGRAMME,
            {"summary": f"{slug}: {match.get('title', '')}", "programme": match},
        )
        if allow.decision == "deny":
            log.info("omg-pastebin: allowlist denied programme digest (%s)", allow.reason)
            _record(self.CATEGORY_PROGRAMME, "allowlist-denied")
            return "allowlist-denied"

        state_key = f"digest_sha_{slug}"

        content_sha = _content_sha_excluding_compiled_stamp(content)
        persisted = self._read_state()
        if persisted.get(state_key) == content_sha:
            _record(self.CATEGORY_PROGRAMME, "unchanged")
            return "unchanged"

        if dry_run:
            log.info(
                "omg-pastebin: dry-run — programme digest %s (sha %s…)",
                slug,
                content_sha[:8],
            )
            _record(self.CATEGORY_PROGRAMME, "dry-run")
            return "dry-run"

        if not getattr(self.client, "enabled", False):
            log.warning("omg-pastebin: client disabled — skipping publish")
            _record(self.CATEGORY_PROGRAMME, "client-disabled")
            return "client-disabled"

        redacted = self._safe_render_or_drop(content, slug, self.CATEGORY_PROGRAMME)
        if redacted is None:
            return "legal-name-leak"
        if not _publish_pastebin(self.client, address=self.address, slug=slug, content=redacted):
            log.warning("omg-pastebin: set_paste returned None (%s)", slug)
            _record(self.CATEGORY_PROGRAMME, "failed")
            return "failed"

        persisted[state_key] = content_sha
        self._write_state(persisted)
        log.info("omg-pastebin: published programme digest %s", slug)
        _record(self.CATEGORY_PROGRAMME, "published")
        return "published"

    def publish_precedent(self, precedent_id: str, *, dry_run: bool = False) -> str:
        """Compose + publish (or update) the digest for an axiom precedent.

        Same outcome contract as the other publish_* methods.
        """
        precedents = self._read_precedents()
        match = next(
            (p for p in precedents if p.get("precedent_id") == precedent_id),
            None,
        )
        if match is None:
            _record(self.CATEGORY_PRECEDENT, "empty")
            return "empty"

        content = build_precedent_digest(precedent=match)
        if not content:
            _record(self.CATEGORY_PRECEDENT, "empty")
            return "empty"

        slug = build_precedent_slug(precedent_id)

        allow = allowlist_check(
            SURFACE,
            self.CATEGORY_PRECEDENT,
            {"summary": f"{slug}: {match.get('short_name', '')}", "precedent": match},
        )
        if allow.decision == "deny":
            log.info("omg-pastebin: allowlist denied precedent digest (%s)", allow.reason)
            _record(self.CATEGORY_PRECEDENT, "allowlist-denied")
            return "allowlist-denied"

        state_key = f"digest_sha_{slug}"

        content_sha = _content_sha_excluding_compiled_stamp(content)
        persisted = self._read_state()
        if persisted.get(state_key) == content_sha:
            _record(self.CATEGORY_PRECEDENT, "unchanged")
            return "unchanged"

        if dry_run:
            log.info(
                "omg-pastebin: dry-run — precedent digest %s (sha %s…)",
                slug,
                content_sha[:8],
            )
            _record(self.CATEGORY_PRECEDENT, "dry-run")
            return "dry-run"

        if not getattr(self.client, "enabled", False):
            log.warning("omg-pastebin: client disabled — skipping publish")
            _record(self.CATEGORY_PRECEDENT, "client-disabled")
            return "client-disabled"

        redacted = self._safe_render_or_drop(content, slug, self.CATEGORY_PRECEDENT)
        if redacted is None:
            return "legal-name-leak"
        if not _publish_pastebin(self.client, address=self.address, slug=slug, content=redacted):
            log.warning("omg-pastebin: set_paste returned None (%s)", slug)
            _record(self.CATEGORY_PRECEDENT, "failed")
            return "failed"

        persisted[state_key] = content_sha
        self._write_state(persisted)
        log.info("omg-pastebin: published precedent digest %s", slug)
        _record(self.CATEGORY_PRECEDENT, "published")
        return "published"

    def publish_research(self, research_id: str, *, dry_run: bool = False) -> str:
        """Compose + publish (or update) the digest for a research-corpus excerpt.

        Default-deny gate: the underlying ``build_research_digest`` returns
        empty string unless the source dict carries ``publish: True``.
        """
        research = self._read_research()
        match = next(
            (r for r in research if r.get("research_id") == research_id),
            None,
        )
        if match is None:
            _record(self.CATEGORY_RESEARCH, "empty")
            return "empty"

        content = build_research_digest(research=match)
        if not content:
            _record(self.CATEGORY_RESEARCH, "empty")
            return "empty"

        slug = build_research_slug(research_id)

        allow = allowlist_check(
            SURFACE,
            self.CATEGORY_RESEARCH,
            {"summary": f"{slug}: {match.get('title', '')}", "research": match},
        )
        if allow.decision == "deny":
            log.info("omg-pastebin: allowlist denied research digest (%s)", allow.reason)
            _record(self.CATEGORY_RESEARCH, "allowlist-denied")
            return "allowlist-denied"

        state_key = f"digest_sha_{slug}"

        content_sha = _content_sha_excluding_compiled_stamp(content)
        persisted = self._read_state()
        if persisted.get(state_key) == content_sha:
            _record(self.CATEGORY_RESEARCH, "unchanged")
            return "unchanged"

        if dry_run:
            log.info(
                "omg-pastebin: dry-run — research digest %s (sha %s…)",
                slug,
                content_sha[:8],
            )
            _record(self.CATEGORY_RESEARCH, "dry-run")
            return "dry-run"

        if not getattr(self.client, "enabled", False):
            log.warning("omg-pastebin: client disabled — skipping publish")
            _record(self.CATEGORY_RESEARCH, "client-disabled")
            return "client-disabled"

        redacted = self._safe_render_or_drop(content, slug, self.CATEGORY_RESEARCH)
        if redacted is None:
            return "legal-name-leak"
        if not _publish_pastebin(self.client, address=self.address, slug=slug, content=redacted):
            log.warning("omg-pastebin: set_paste returned None (%s)", slug)
            _record(self.CATEGORY_RESEARCH, "failed")
            return "failed"

        persisted[state_key] = content_sha
        self._write_state(persisted)
        log.info("omg-pastebin: published research digest %s", slug)
        _record(self.CATEGORY_RESEARCH, "published")
        return "published"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--week", help="ISO week-start date YYYY-MM-DD; defaults to current week")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--address", default=DEFAULT_ADDRESS)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    from shared.omg_lol_client import OmgLolClient

    publisher = PastebinArtifactPublisher(
        client=OmgLolClient(address=args.address),
        state_file=DEFAULT_STATE_FILE,
        read_events=lambda: _load_events(DEFAULT_CHRONICLE_FILE),
        now_fn=lambda: datetime.now(UTC),
        address=args.address,
    )

    if args.week:
        week_start = date.fromisoformat(args.week)
        outcome = publisher.publish_chronicle_week(week_start, dry_run=args.dry_run)
    else:
        outcome = publisher.publish_current_week(dry_run=args.dry_run)

    print(outcome)
    return 0


if __name__ == "__main__":
    sys.exit(main())
