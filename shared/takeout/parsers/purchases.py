"""purchases.py — Parser for Google Purchases/Transactions data.

Purchases Takeout can be JSON or HTML. Contains order/transaction records
with items, prices, dates, and merchants.
"""

from __future__ import annotations

import json
import logging
import re
import zipfile
from collections.abc import Iterator
from datetime import datetime

from shared.takeout.models import NormalizedRecord, ServiceConfig, make_record_id

log = logging.getLogger("takeout.purchases")


def parse(zf: zipfile.ZipFile, config: ServiceConfig) -> Iterator[NormalizedRecord]:
    """Parse purchase records from a Takeout ZIP."""
    prefix_options = [
        "Takeout/Purchases/",
        "Purchases/",
        "Takeout/Google Play Store/",
        "Google Play Store/",
    ]

    for name in sorted(zf.namelist()):
        matched = False
        for prefix in prefix_options:
            if name.startswith(prefix):
                matched = True
                break

        if not matched:
            continue

        if name.endswith(".json"):
            try:
                raw = zf.read(name)
                data = json.loads(raw)
            except (json.JSONDecodeError, KeyError):
                continue

            if isinstance(data, list):
                for item in data:
                    record = _purchase_to_record(item, name, config)
                    if record:
                        yield record
            elif isinstance(data, dict):
                record = _purchase_to_record(data, name, config)
                if record:
                    yield record

        elif name.endswith(".html"):
            try:
                raw = zf.read(name).decode("utf-8", errors="replace")
            except KeyError:
                continue
            yield from _parse_html_purchases(raw, name, config)


def _purchase_to_record(
    data: dict,
    source_path: str,
    config: ServiceConfig,
) -> NormalizedRecord | None:
    """Convert a purchase JSON object to a NormalizedRecord."""
    # Various possible fields across Google purchase formats
    title = (
        data.get("title", "")
        or data.get("name", "")
        or data.get("productName", "")
        or data.get("description", "")
    )
    if not title:
        return None

    # Price
    price = data.get("price", data.get("amount", ""))
    currency = data.get("currency", data.get("currencyCode", ""))

    # Merchant/store
    merchant = data.get("merchant", data.get("storeName", data.get("seller", "")))

    # Timestamp
    timestamp = None
    date_str = data.get("date", data.get("purchaseDate", data.get("timestamp", "")))
    if date_str:
        timestamp = _parse_purchase_date(date_str)

    # Build text
    text_parts = [title]
    if merchant:
        text_parts.append(f"From: {merchant}")
    if price:
        price_str = f"{price} {currency}" if currency else str(price)
        text_parts.append(f"Price: {price_str}")
    if timestamp:
        text_parts.append(f"Date: {timestamp.strftime('%Y-%m-%d')}")

    text = "\n".join(text_parts)

    source_key = f"{title}:{date_str}:{merchant}"
    record_id = make_record_id("google", "purchases", source_key)

    structured: dict = {}
    if price:
        structured["price"] = str(price)
    if currency:
        structured["currency"] = currency
    if merchant:
        structured["merchant"] = merchant

    # Categories from product type if available
    categories: list[str] = []
    cat = data.get("category", data.get("productType", ""))
    if cat:
        categories.append(cat)

    return NormalizedRecord(
        record_id=record_id,
        platform="google",
        service="purchases",
        title=title,
        text=text,
        content_type="purchase",
        timestamp=timestamp,
        modality_tags=list(config.modality_defaults),
        categories=categories,
        structured_fields=structured,
        data_path=config.data_path,
        source_path=source_path,
    )


def _parse_html_purchases(
    html: str,
    source_path: str,
    config: ServiceConfig,
) -> Iterator[NormalizedRecord]:
    """Basic HTML purchase extraction."""
    # Simple extraction of order items
    entries = re.split(r'<div class="[^"]*order[^"]*">', html, flags=re.IGNORECASE)

    for i, entry in enumerate(entries[1:], 1):
        # Extract text, strip tags
        text = re.sub(r"<[^>]+>", " ", entry)
        text = re.sub(r"\s+", " ", text).strip()

        if not text or len(text) < 10:
            continue

        title = text[:100] + "..." if len(text) > 100 else text
        source_key = f"html:{i}:{text[:50]}"
        record_id = make_record_id("google", "purchases", source_key)

        yield NormalizedRecord(
            record_id=record_id,
            platform="google",
            service="purchases",
            title=title,
            text=text,
            content_type="purchase",
            modality_tags=list(config.modality_defaults),
            data_path=config.data_path,
            source_path=source_path,
        )


def _parse_purchase_date(date_str: str) -> datetime | None:
    """Parse various purchase date formats."""
    if not date_str:
        return None

    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
        "%b %d, %Y",
        "%B %d, %Y",
    ):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None
