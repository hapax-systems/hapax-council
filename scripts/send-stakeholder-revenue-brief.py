#!/usr/bin/env python3
"""Generate and optionally send the stakeholder revenue brief as a DOCX."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = (
    Path.home() / "Documents/Personal/20-projects/hapax-research/briefs/"
    "2026-04-29-hapax-monetary-revenue-stakeholder-brief.md"
)
DEFAULT_GENERATED_DIR = (
    Path.home() / "Documents/Personal/20-projects/hapax-research/briefs/stakeholder-revenue"
)
DEFAULT_STATE_DIR = Path.home() / ".local/state/hapax/stakeholder-revenue-brief"
DEFAULT_SUBJECT = "Updated Hapax monetary/revenue brief (DOCX attached)"


@dataclass(frozen=True)
class BriefConfig:
    source_path: Path
    generated_dir: Path
    state_dir: Path
    timezone: ZoneInfo
    send: bool
    force: bool
    min_hours_between: float
    sender: str | None
    recipients: tuple[str, ...]
    cc: tuple[str, ...]
    recipient_name: str
    subject: str
    delivery_note: str | None
    summary_lines: tuple[str, ...]


def _split_csv(values: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    if not values:
        return ()
    result: list[str] = []
    for value in values:
        result.extend(part.strip() for part in value.split(",") if part.strip())
    return tuple(result)


def _env_csv(name: str) -> tuple[str, ...]:
    return _split_csv([os.environ[name]]) if os.environ.get(name) else ()


def _strip_frontmatter(text: str) -> tuple[list[str] | None, str]:
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return None, text
    frontmatter = text[4:end].splitlines()
    body = text[end + len("\n---\n") :].lstrip()
    return frontmatter, body


def _without_leading_h1(markdown: str) -> str:
    return re.sub(r"\A# .+\n+", "", markdown, count=1).lstrip()


def _content_hash(text: str) -> str:
    normalized = "\n".join(line.rstrip() for line in text.strip().splitlines())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _last_send_inside_window(
    *,
    state: dict[str, Any],
    now: datetime,
    timezone: ZoneInfo,
    min_hours_between: float,
) -> tuple[bool, str | None]:
    value = state.get("last_sent_at")
    if not isinstance(value, str) or not value:
        return False, None
    try:
        last_sent_at = datetime.fromisoformat(value)
    except ValueError:
        return False, None
    if last_sent_at.tzinfo is None:
        last_sent_at = last_sent_at.replace(tzinfo=timezone)
    normalized = last_sent_at.astimezone(timezone)
    elapsed_hours = (now - normalized).total_seconds() / 3600
    return elapsed_hours < min_hours_between, normalized.isoformat()


def _section_map(markdown: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current = "Opening"
    sections[current] = []
    for line in markdown.splitlines():
        match = re.match(r"^(#{1,3})\s+(.+?)\s*$", line)
        if match:
            current = match.group(2).strip()
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return {heading: "\n".join(lines).strip() for heading, lines in sections.items()}


def _summarize_changes(previous: str | None, current: str) -> list[str]:
    if not previous:
        return [
            "This is the first tracked DOCX dispatch; it converts the source "
            "brief into an attachment-ready Word document.",
        ]

    if _content_hash(previous) == _content_hash(current):
        return ["No material content changes since the last sent brief."]

    previous_sections = _section_map(previous)
    current_sections = _section_map(current)
    previous_headings = set(previous_sections)
    current_headings = set(current_sections)

    summary: list[str] = []
    added = sorted(current_headings - previous_headings)
    removed = sorted(previous_headings - current_headings)
    changed = sorted(
        heading
        for heading in current_headings & previous_headings
        if _content_hash(current_sections[heading]) != _content_hash(previous_sections[heading])
    )

    if added:
        suffix = "." if len(added) <= 6 else ", ..."
        summary.append("New sections: " + ", ".join(added[:6]) + suffix)
    if changed:
        suffix = "." if len(changed) <= 8 else ", ..."
        summary.append("Updated sections: " + ", ".join(changed[:8]) + suffix)
    if removed:
        suffix = "." if len(removed) <= 6 else ", ..."
        summary.append("Removed sections: " + ", ".join(removed[:6]) + suffix)

    return summary or ["The source brief changed, but the change was too small to classify."]


def _build_markdown(
    *,
    body: str,
    summary_lines: list[str],
    generated_at: datetime,
    delivery_note: str | None,
    recipient_name: str,
) -> str:
    pretty_date = generated_at.strftime("%B %-d, %Y")
    generated_stamp = generated_at.strftime("%Y-%m-%d %H:%M %Z")
    summary = "\n".join(f"- {line}" for line in summary_lines)
    note = f"\n\n{delivery_note.strip()}\n" if delivery_note else ""
    brief_body = _without_leading_h1(body)
    return f"""---
title: "Hapax Monetary And Revenue Stakeholder Brief"
subtitle: "Updated {pretty_date}"
author: "Hapax"
date: "{pretty_date}"
---

Prepared for {recipient_name}. Generated {generated_stamp}.{note}

# Changes Since Last Brief

{summary}

# Current Brief

{brief_body}
"""


def _assert_not_repo_output(path: Path, *, label: str) -> None:
    resolved = path.expanduser().resolve()
    repo = REPO_ROOT.resolve()
    if resolved == repo or repo in resolved.parents:
        raise RuntimeError(f"{label} must be outside the repository: {resolved}")


def _run_pandoc(markdown_path: Path, docx_path: Path) -> None:
    subprocess.run(
        [
            "pandoc",
            "--from",
            "markdown+pipe_tables+yaml_metadata_block",
            "--to",
            "docx",
            "--standalone",
            "--output",
            str(docx_path),
            str(markdown_path),
        ],
        check=True,
    )


def _write_docx(
    *,
    markdown: str,
    generated_at: datetime,
    generated_dir: Path,
) -> tuple[Path, Path]:
    _assert_not_repo_output(generated_dir, label="generated_dir")
    generated_dir.mkdir(parents=True, exist_ok=True)
    stamp = generated_at.strftime("%Y-%m-%d-%H%M")
    markdown_path = generated_dir / f"hapax-stakeholder-revenue-brief-{stamp}.md"
    docx_path = generated_dir / f"hapax-stakeholder-revenue-brief-{stamp}.docx"
    markdown_path.write_text(markdown, encoding="utf-8")
    _run_pandoc(markdown_path, docx_path)
    return markdown_path, docx_path


def _build_gmail_service_from_pass() -> Any:
    from agents.mail_monitor.oauth import build_gmail_service, load_credentials

    creds = load_credentials()
    return build_gmail_service(creds=creds)


def _send_email(
    *,
    config: BriefConfig,
    docx_path: Path,
    summary_lines: list[str],
    generated_at: datetime,
) -> str:
    service = _build_gmail_service_from_pass()
    if service is None:
        raise RuntimeError("could not build Gmail service from pass-backed credentials")

    profile = service.users().getProfile(userId="me").execute()
    from_addr = str(profile.get("emailAddress", ""))
    expected_sender = config.sender or ""
    if from_addr.lower() != expected_sender.lower():
        raise RuntimeError(f"Gmail credential is for {from_addr!r}, expected {expected_sender!r}")

    summary = "\n".join(f"- {line}" for line in summary_lines)
    generated_stamp = generated_at.strftime("%Y-%m-%d %H:%M %Z")
    body = f"""Attached is the updated Hapax monetary/revenue stakeholder brief as a formatted Word document.

Changes since the last brief:
{summary}

The projections remain gross revenue planning scenarios before taxes, model/API spend, storage,
hardware, payment fees, and normal business costs.

Generated {generated_stamp}.
"""
    message = EmailMessage()
    message["To"] = ", ".join(config.recipients)
    if config.cc:
        message["Cc"] = ", ".join(config.cc)
    message["From"] = from_addr
    message["Subject"] = config.subject
    message.set_content(body)
    message.add_attachment(
        docx_path.read_bytes(),
        maintype="application",
        subtype="vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=docx_path.name,
    )

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    message_id = sent.get("id")
    if not message_id:
        raise RuntimeError(f"Gmail send returned no message id: {sent!r}")
    return str(message_id)


def _update_source_frontmatter(path: Path, fields: dict[str, str]) -> None:
    text = path.read_text(encoding="utf-8")
    frontmatter, body = _strip_frontmatter(text)
    if frontmatter is None:
        return

    pending = dict(fields)
    updated: list[str] = []
    for line in frontmatter:
        key = line.split(":", 1)[0].strip() if ":" in line and not line.startswith(" ") else None
        if key in pending:
            updated.append(f"{key}: {pending.pop(key)}")
        else:
            updated.append(line)

    updated.extend(f"{key}: {value}" for key, value in pending.items())
    path.write_text("---\n" + "\n".join(updated) + "\n---\n" + body, encoding="utf-8")


def _save_state(
    *,
    config: BriefConfig,
    state_path: Path,
    source_body: str,
    source_hash: str,
    generated_markdown: Path,
    docx_path: Path,
    message_id: str,
    sent_at: datetime,
) -> None:
    _assert_not_repo_output(config.state_dir, label="state_dir")
    config.state_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = config.state_dir / "last-source-snapshot.md"
    snapshot_path.write_text(source_body, encoding="utf-8")
    state = {
        "last_sent_at": sent_at.isoformat(),
        "last_source_hash": source_hash,
        "last_source_snapshot": str(snapshot_path),
        "last_generated_markdown": str(generated_markdown),
        "last_docx": str(docx_path),
        "last_gmail_message_id": message_id,
        "sender": config.sender,
        "to": list(config.recipients),
        "cc": list(config.cc),
    }
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run(config: BriefConfig, *, now: datetime | None = None) -> dict[str, Any]:
    generated_at = now or datetime.now(config.timezone)
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=config.timezone)
    generated_at = generated_at.astimezone(config.timezone)

    state_path = config.state_dir / "state.json"
    state = _load_json(state_path)
    if config.send and not config.force:
        should_skip, last_sent_at = _last_send_inside_window(
            state=state,
            now=generated_at,
            timezone=config.timezone,
            min_hours_between=config.min_hours_between,
        )
        if should_skip:
            return {
                "skipped": True,
                "reason": "recently_sent",
                "last_sent_at": last_sent_at,
                "min_hours_between": config.min_hours_between,
            }

    source_text = config.source_path.read_text(encoding="utf-8")
    _, source_body = _strip_frontmatter(source_text)
    source_body = source_body.strip() + "\n"
    source_hash = _content_hash(source_body)
    previous_snapshot_value = str(state.get("last_source_snapshot", ""))
    previous_snapshot_path = Path(previous_snapshot_value) if previous_snapshot_value else None
    previous_snapshot = (
        previous_snapshot_path.read_text(encoding="utf-8")
        if previous_snapshot_path is not None and previous_snapshot_path.exists()
        else None
    )

    summary_lines = list(config.summary_lines) + _summarize_changes(
        previous_snapshot,
        source_body,
    )
    generated_markdown = _build_markdown(
        body=source_body,
        summary_lines=summary_lines,
        generated_at=generated_at,
        delivery_note=config.delivery_note,
        recipient_name=config.recipient_name,
    )
    generated_md, docx_path = _write_docx(
        markdown=generated_markdown,
        generated_at=generated_at,
        generated_dir=config.generated_dir,
    )

    if not config.send:
        return {
            "sent": False,
            "generated_markdown": str(generated_md),
            "docx": str(docx_path),
        }

    message_id = _send_email(
        config=config,
        docx_path=docx_path,
        summary_lines=summary_lines,
        generated_at=generated_at,
    )
    _save_state(
        config=config,
        state_path=state_path,
        source_body=source_body,
        source_hash=source_hash,
        generated_markdown=generated_md,
        docx_path=docx_path,
        message_id=message_id,
        sent_at=generated_at,
    )
    _update_source_frontmatter(
        config.source_path,
        {
            "status": "sent-to-stakeholder",
            "last_docx_sent_at": generated_at.isoformat(),
            "last_docx_gmail_message_id": message_id,
            "last_docx_path": str(docx_path),
        },
    )
    return {
        "sent": True,
        "sent_to": list(config.recipients),
        "cc": list(config.cc),
        "gmail_message_id": message_id,
        "docx": str(docx_path),
        "generated_markdown": str(generated_md),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(os.environ.get("HAPAX_STAKEHOLDER_REVENUE_BRIEF_SOURCE", DEFAULT_SOURCE)),
        help="Source markdown brief.",
    )
    parser.add_argument(
        "--generated-dir",
        type=Path,
        default=Path(
            os.environ.get(
                "HAPAX_STAKEHOLDER_REVENUE_BRIEF_GENERATED_DIR",
                DEFAULT_GENERATED_DIR,
            )
        ),
        help="Vault directory for generated markdown and DOCX outputs.",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path(
            os.environ.get("HAPAX_STAKEHOLDER_REVENUE_BRIEF_STATE_DIR", DEFAULT_STATE_DIR)
        ),
        help="State directory for send history and source snapshots.",
    )
    parser.add_argument("--send", action="store_true", help="Actually send the generated DOCX.")
    parser.add_argument(
        "--no-send",
        action="store_true",
        help="Compatibility no-op; generation without sending is the default.",
    )
    parser.add_argument("--force", action="store_true", help="Ignore recent-send suppression.")
    parser.add_argument(
        "--min-hours-between",
        type=float,
        default=float(os.environ.get("HAPAX_STAKEHOLDER_REVENUE_BRIEF_MIN_HOURS", "23")),
        help="Minimum hours between non-forced sends.",
    )
    parser.add_argument(
        "--sender",
        default=os.environ.get("HAPAX_STAKEHOLDER_REVENUE_BRIEF_SENDER"),
        help="Expected Gmail sender address. Required with --send.",
    )
    parser.add_argument(
        "--to",
        action="append",
        default=list(_env_csv("HAPAX_STAKEHOLDER_REVENUE_BRIEF_TO")),
        help="Recipient address. May be repeated or comma-separated. Required with --send.",
    )
    parser.add_argument(
        "--cc",
        action="append",
        default=list(_env_csv("HAPAX_STAKEHOLDER_REVENUE_BRIEF_CC")),
        help="CC address. May be repeated or comma-separated.",
    )
    parser.add_argument(
        "--recipient-name",
        default=os.environ.get(
            "HAPAX_STAKEHOLDER_REVENUE_BRIEF_RECIPIENT_NAME",
            "the stakeholder",
        ),
        help="Display name used in generated document metadata.",
    )
    parser.add_argument(
        "--subject",
        default=os.environ.get("HAPAX_STAKEHOLDER_REVENUE_BRIEF_SUBJECT", DEFAULT_SUBJECT),
        help="Email subject used only with --send.",
    )
    parser.add_argument(
        "--timezone",
        default=os.environ.get("HAPAX_TIMEZONE", "America/Chicago"),
        help="IANA timezone for generated timestamps.",
    )
    parser.add_argument(
        "--summary-line",
        action="append",
        default=[],
        help="Explicit change-summary bullet to prepend. May be repeated.",
    )
    parser.add_argument(
        "--delivery-note",
        help="Optional note included near the top of the generated document.",
    )
    return parser


def _config_from_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> BriefConfig:
    recipients = _split_csv(args.to)
    cc = _split_csv(args.cc)
    send = bool(args.send and not args.no_send)
    if send and not recipients:
        parser.error("--send requires --to or HAPAX_STAKEHOLDER_REVENUE_BRIEF_TO")
    if send and not args.sender:
        parser.error("--send requires --sender or HAPAX_STAKEHOLDER_REVENUE_BRIEF_SENDER")

    try:
        timezone = ZoneInfo(args.timezone)
    except Exception as exc:
        parser.error(f"invalid timezone {args.timezone!r}: {exc}")

    return BriefConfig(
        source_path=args.source,
        generated_dir=args.generated_dir,
        state_dir=args.state_dir,
        timezone=timezone,
        send=send,
        force=args.force,
        min_hours_between=args.min_hours_between,
        sender=args.sender,
        recipients=recipients,
        cc=cc,
        recipient_name=args.recipient_name,
        subject=args.subject,
        delivery_note=args.delivery_note,
        summary_lines=tuple(args.summary_line),
    )


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    config = _config_from_args(args, parser)
    result = run(config)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
