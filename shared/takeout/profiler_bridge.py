"""profiler_bridge.py — Deterministic mapping from structured records to ProfileFacts.

This is Path B of the dual-path architecture: structured Takeout data
gets mapped directly to profile facts without LLM involvement.

Zero LLM cost, deterministic output, high confidence (0.95).
"""

from __future__ import annotations

import json
import logging
import os
from collections import Counter
from datetime import datetime
from pathlib import Path

log = logging.getLogger("takeout.profiler_bridge")

# Import ProfileFact at function level to avoid circular imports
# since profiler.py is in agents/ and this is in shared/
STRUCTURED_JSONL = (
    Path(__file__).resolve().parent.parent.parent / "profiles" / "takeout-structured.jsonl"
)
FACTS_OUTPUT = (
    Path(__file__).resolve().parent.parent.parent / "profiles" / "takeout-structured-facts.json"
)


def _make_fact(dimension: str, key: str, value: str, source: str, evidence: str) -> dict:
    """Create a ProfileFact-compatible dict."""
    return {
        "dimension": dimension,
        "key": key,
        "value": value,
        "confidence": 0.95,
        "source": source,
        "evidence": evidence,
    }


def structured_to_facts(
    jsonl_path: Path = STRUCTURED_JSONL,
) -> list[dict]:
    """Read structured JSONL and produce ProfileFact-compatible dicts.

    Aggregates records by service and produces summary facts.
    This is deterministic — same input always produces same output.

    Uses incremental aggregation: streams records one-by-one and updates
    per-service accumulators (Counters/lists of bounded size) instead of
    accumulating full record lists. Memory is O(unique_values) not O(records).
    """
    if not jsonl_path.exists():
        return []

    # Incremental accumulators per service
    acc = _ServiceAccumulators()
    record_count = 0

    with open(jsonl_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            acc.ingest(record)
            record_count += 1

    if not record_count:
        return []

    source = f"takeout-structured:{jsonl_path.name}"
    return acc.to_facts(source)


class _ServiceAccumulators:
    """Incremental accumulators for all services.

    Instead of accumulating full record lists, we maintain only the
    aggregate counters needed to produce facts. Memory usage is
    O(unique domains + unique queries + ...) rather than O(records).
    """

    def __init__(self) -> None:
        # Chrome
        self.chrome_domain_visits: Counter[str] = Counter()
        self.chrome_url_count = 0

        # Search
        self.search_queries: list[str] = []
        self._search_query_limit = 50

        # YouTube
        self.youtube_channel_watches: Counter[str] = Counter()
        self.youtube_watch_count = 0
        self.youtube_titles: list[str] = []
        self._youtube_title_limit = 50
        self.youtube_search_queries: list[str] = []
        self._youtube_search_limit = 30
        self.youtube_subscriptions: list[str] = []
        self._youtube_sub_limit = 50
        self.youtube_playlists: Counter[str] = Counter()

        # Calendar
        self.calendar_recurring: set[str] = set()
        self.calendar_event_count = 0

        # Contacts
        self.contacts_orgs: Counter[str] = Counter()
        self.contacts_count = 0

        # Location
        self.location_places: Counter[str] = Counter()

        # Purchases
        self.purchase_titles: list[str] = []
        self._purchase_title_limit = 20

        # Proton Mail
        self.proton_contact_counts: Counter[str] = Counter()
        self.proton_timestamps: list[str] = []
        self.proton_sent_count = 0
        self.proton_received_count = 0
        self.proton_label_counts: Counter[str] = Counter()
        self.proton_total = 0

        # Track which services have data
        self._services_seen: set[str] = set()

    def ingest(self, record: dict) -> None:
        """Process a single record incrementally."""
        svc = record.get("service", "unknown")
        platform = record.get("platform", "")
        self._services_seen.add(svc)

        if svc == "chrome":
            url = record.get("structured_fields", {}).get("url", "")
            count = record.get("structured_fields", {}).get("visit_count", 1)
            domain = _extract_domain(url)
            if domain:
                self.chrome_domain_visits[domain] += count
            self.chrome_url_count += 1

        elif svc == "search":
            if len(self.search_queries) < self._search_query_limit:
                title = record.get("title", "")
                q = title
                for prefix in ("Searched for ", "searched for "):
                    if q.startswith(prefix):
                        q = q[len(prefix) :]
                        break
                if q:
                    self.search_queries.append(q)

        elif svc in ("youtube", "youtube_full"):
            content_type = record.get("content_type", "")
            sf = record.get("structured_fields", {})

            if content_type == "video_watch":
                self.youtube_watch_count += 1
                channel = sf.get("channel", "")
                if channel:
                    self.youtube_channel_watches[channel] += 1
                if len(self.youtube_titles) < self._youtube_title_limit:
                    title = record.get("title", "")
                    for prefix in ("Watched: ", "Watched ", "watched "):
                        if title.startswith(prefix):
                            title = title[len(prefix) :]
                            break
                    if title:
                        self.youtube_titles.append(title)

            elif content_type == "search_query":
                if len(self.youtube_search_queries) < self._youtube_search_limit:
                    query = sf.get("query", "")
                    if query:
                        self.youtube_search_queries.append(query)

            elif content_type == "subscription":
                if len(self.youtube_subscriptions) < self._youtube_sub_limit:
                    channel_title = sf.get("channel_title", "")
                    if channel_title:
                        self.youtube_subscriptions.append(channel_title)

            elif content_type == "playlist_item":
                playlist = sf.get("playlist", "")
                if playlist:
                    self.youtube_playlists[playlist] += 1

            else:
                # Legacy/activity-based youtube records (no content_type)
                if len(self.youtube_titles) < self._youtube_title_limit:
                    title = record.get("title", "")
                    for prefix in ("Watched ", "watched "):
                        if title.startswith(prefix):
                            title = title[len(prefix) :]
                            break
                    if title:
                        self.youtube_titles.append(title)

        elif svc == "calendar":
            title = record.get("title", "")
            if title:
                self.calendar_event_count += 1
            sf = record.get("structured_fields", {})
            if sf.get("recurring") and title:
                self.calendar_recurring.add(title)

        elif svc == "contacts":
            self.contacts_count += 1
            org = record.get("structured_fields", {}).get("organization", "")
            if org:
                self.contacts_orgs[org] += 1

        elif svc == "maps":
            loc = record.get("location", "")
            if loc:
                self.location_places[loc] += 1

        elif svc == "purchases":
            if len(self.purchase_titles) < self._purchase_title_limit:
                title = record.get("title", "")
                if title:
                    self.purchase_titles.append(title)

        elif svc == "mail" and platform == "proton":
            self.proton_total += 1
            direction = record.get("structured_fields", {}).get("direction", "")
            if direction == "sent":
                self.proton_sent_count += 1
            elif direction == "received":
                self.proton_received_count += 1
            for person in record.get("people", []):
                self.proton_contact_counts[person] += 1
            ts = record.get("timestamp")
            if ts:
                self.proton_timestamps.append(ts)
            for lid in record.get("structured_fields", {}).get("label_ids", []):
                self.proton_label_counts[lid] += 1

    def to_facts(self, source: str) -> list[dict]:
        """Produce all facts from accumulated data."""
        facts: list[dict] = []

        if "chrome" in self._services_seen and self.chrome_domain_visits:
            top = self.chrome_domain_visits.most_common(15)
            value = ", ".join(f"{d} ({c})" for d, c in top)
            evidence = f"Aggregated from {self.chrome_url_count} unique URLs, {sum(self.chrome_domain_visits.values())} total visits"
            facts.append(
                _make_fact("knowledge_domains", "frequent_websites", value, source, evidence)
            )

        if "search" in self._services_seen and self.search_queries:
            value = "; ".join(self.search_queries)
            evidence = f"{len(self.search_queries)} search queries found"
            facts.append(_make_fact("knowledge_domains", "search_topics", value, source, evidence))

        if self._services_seen & {"youtube", "youtube_full"}:
            if self.youtube_titles:
                value = "; ".join(self.youtube_titles)
                total_label = (
                    f" (of {self.youtube_watch_count} total)"
                    if self.youtube_watch_count > len(self.youtube_titles)
                    else ""
                )
                evidence = f"{len(self.youtube_titles)} videos watched{total_label}"
                facts.append(
                    _make_fact("knowledge_domains", "video_topics", value, source, evidence)
                )

            if self.youtube_channel_watches:
                top = self.youtube_channel_watches.most_common(20)
                value = ", ".join(f"{ch} ({c})" for ch, c in top)
                evidence = f"Top channels from {self.youtube_watch_count} video watches"
                facts.append(
                    _make_fact("knowledge_domains", "youtube_channels", value, source, evidence)
                )

            if self.youtube_search_queries:
                value = "; ".join(self.youtube_search_queries)
                evidence = f"{len(self.youtube_search_queries)} YouTube search queries"
                facts.append(
                    _make_fact(
                        "knowledge_domains", "youtube_search_topics", value, source, evidence
                    )
                )

            if self.youtube_subscriptions:
                value = ", ".join(self.youtube_subscriptions)
                evidence = f"{len(self.youtube_subscriptions)} YouTube channel subscriptions"
                facts.append(
                    _make_fact(
                        "knowledge_domains", "youtube_subscriptions", value, source, evidence
                    )
                )

            if self.youtube_playlists:
                top = self.youtube_playlists.most_common(10)
                value = ", ".join(f"{p} ({c} videos)" for p, c in top)
                evidence = f"{len(self.youtube_playlists)} playlists with {sum(self.youtube_playlists.values())} total videos"
                facts.append(_make_fact("workflow", "youtube_playlists", value, source, evidence))

        if "calendar" in self._services_seen:
            if self.calendar_recurring:
                value = "; ".join(self.calendar_recurring)
                evidence = f"{len(self.calendar_recurring)} recurring events found"
                facts.append(
                    _make_fact("workflow", "recurring_commitments", value, source, evidence)
                )
            if self.calendar_event_count:
                evidence = f"{self.calendar_event_count} total calendar events"
                facts.append(
                    _make_fact(
                        "workflow",
                        "calendar_event_count",
                        str(self.calendar_event_count),
                        source,
                        evidence,
                    )
                )

        if "contacts" in self._services_seen:
            if self.contacts_count:
                facts.append(
                    _make_fact(
                        "identity",
                        "contact_network_size",
                        str(self.contacts_count),
                        source,
                        f"{self.contacts_count} contacts in Google Contacts",
                    )
                )
            if self.contacts_orgs:
                top_orgs = self.contacts_orgs.most_common(10)
                value = ", ".join(f"{o} ({c})" for o, c in top_orgs)
                facts.append(
                    _make_fact(
                        "identity",
                        "organizational_connections",
                        value,
                        source,
                        f"Organizations from {sum(self.contacts_orgs.values())} contacts",
                    )
                )

        if "maps" in self._services_seen and self.location_places:
            top = self.location_places.most_common(10)
            value = ", ".join(f"{p} ({c})" for p, c in top)
            evidence = f"Top places from {sum(self.location_places.values())} location records"
            facts.append(_make_fact("workflow", "regular_locations", value, source, evidence))

        if "purchases" in self._services_seen and self.purchase_titles:
            value = "; ".join(self.purchase_titles)
            evidence = f"{len(self.purchase_titles)} purchases found"
            facts.append(_make_fact("workflow", "purchase_history", value, source, evidence))

        if self.proton_total > 0:
            facts.extend(self._proton_facts(source))

        return facts

    def _proton_facts(self, source: str) -> list[dict]:
        """Generate Proton Mail facts from accumulated data."""
        facts: list[dict] = []

        if self.proton_contact_counts:
            top = self.proton_contact_counts.most_common(20)
            value = ", ".join(f"{addr} ({c})" for addr, c in top)
            evidence = f"Aggregated from {self.proton_total} Proton Mail messages"
            facts.append(_make_fact("identity", "proton_top_contacts", value, source, evidence))

        if len(self.proton_timestamps) >= 2:
            try:
                parsed = sorted(datetime.fromisoformat(ts) for ts in self.proton_timestamps if ts)
                if len(parsed) >= 2:
                    span_days = (parsed[-1] - parsed[0]).days or 1
                    per_day = len(parsed) / span_days
                    per_week = per_day * 7
                    value = f"{per_day:.1f} emails/day ({per_week:.0f}/week)"
                    evidence = f"{len(parsed)} emails over {span_days} days"
                    facts.append(
                        _make_fact("workflow", "proton_email_cadence", value, source, evidence)
                    )
            except (ValueError, TypeError):
                pass

        if self.proton_sent_count or self.proton_received_count:
            total = self.proton_sent_count + self.proton_received_count
            sent_pct = 100 * self.proton_sent_count / total if total else 0
            value = f"{self.proton_sent_count} sent, {self.proton_received_count} received ({sent_pct:.0f}% sent)"
            evidence = f"{total} total Proton Mail messages analyzed"
            facts.append(
                _make_fact("workflow", "proton_email_direction_ratio", value, source, evidence)
            )

        if self.proton_label_counts:
            from shared.proton.labels import SYSTEM_LABELS

            named: list[str] = []
            for lid, count in self.proton_label_counts.most_common(10):
                name = SYSTEM_LABELS.get(lid, f"custom:{lid}")
                named.append(f"{name} ({count})")
            value = ", ".join(named)
            evidence = f"Label distribution across {self.proton_total} messages"
            facts.append(
                _make_fact("workflow", "proton_email_organization", value, source, evidence)
            )

        return facts


def _extract_domain(url: str) -> str:
    """Extract domain from URL."""
    if not url:
        return ""
    # Strip protocol
    url = url.split("://", 1)[-1]
    # Strip path
    domain = url.split("/", 1)[0]
    # Strip port
    domain = domain.split(":", 1)[0]
    # Strip www.
    if domain.startswith("www."):
        domain = domain[4:]
    return domain.lower()


def generate_facts(
    jsonl_path: Path = STRUCTURED_JSONL,
    output_path: Path = FACTS_OUTPUT,
) -> int:
    """Generate structured facts and write to JSON file.

    Returns the number of facts generated.
    """
    facts = structured_to_facts(jsonl_path)
    if not facts:
        log.info("No structured records to process")
        return 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    import tempfile

    tmp_fd, tmp_path = tempfile.mkstemp(dir=output_path.parent, suffix=".tmp")
    try:
        os.write(tmp_fd, json.dumps(facts, indent=2).encode("utf-8"))
        os.close(tmp_fd)
        os.replace(tmp_path, output_path)
    except BaseException:
        os.close(tmp_fd)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    log.info("Wrote %d facts to %s", len(facts), output_path)
    return len(facts)
