"""Historical consent audit — scan for pre-gate person-adjacent data.

The audio processor was writing multi-speaker conversation transcripts
to rag-sources/audio/ before the consent gate was deployed (PR #102).
This script scans for those historical transcripts and flags them.

Actions:
- --scan: identify multi-speaker transcripts without consent backing
- --purge: delete flagged transcripts (requires explicit confirmation)
- --report: write audit results to profiles/consent-audit-report.json

No LLM calls. Pure filesystem + frontmatter inspection.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

RAG_AUDIO_DIR = Path.home() / "documents" / "rag-sources" / "audio"
REPORT_PATH = Path.home() / "projects" / "hapax-council" / "profiles" / "consent-audit-report.json"


@dataclass(frozen=True)
class FlaggedDocument:
    """A RAG document flagged as potentially lacking consent."""

    path: str
    content_type: str
    speaker_count: int
    timestamp: str
    reason: str


@dataclass
class AuditResult:
    """Complete audit of historical person-adjacent data."""

    scanned: int = 0
    flagged: int = 0
    clean: int = 0
    documents: list[FlaggedDocument] = field(default_factory=list)
    scan_timestamp: str = ""


def scan_historical_audio() -> AuditResult:
    """Scan rag-sources/audio/ for multi-speaker transcripts.

    Flags documents where:
    - content_type is "conversation"
    - speaker_count > 1
    - No consent_label in frontmatter
    - No provenance linking to a consent contract
    """
    result = AuditResult(scan_timestamp=datetime.now(UTC).isoformat())

    if not RAG_AUDIO_DIR.exists():
        return result

    for md_file in sorted(RAG_AUDIO_DIR.glob("*.md")):
        result.scanned += 1
        try:
            text = md_file.read_text(encoding="utf-8")
            if text.startswith("---"):
                parts = text.split("---", 2)
                fm = yaml.safe_load(parts[1]) if len(parts) >= 3 else {}
                _ = parts[2] if len(parts) >= 3 else ""  # body unused in scan
            else:
                fm = {}
                _ = text  # body unused in scan
            if fm is None:
                fm = {}

            content_type = fm.get("content_type", "")
            speaker_count = fm.get("speaker_count", 1)
            speakers = fm.get("speakers", [])
            has_consent = fm.get("consent_label") is not None
            has_provenance = bool(fm.get("provenance", []))

            # Flag multi-speaker content without consent backing
            if content_type == "conversation" and (speaker_count > 1 or len(speakers) > 1):
                if not has_consent and not has_provenance:
                    result.flagged += 1
                    result.documents.append(
                        FlaggedDocument(
                            path=str(md_file),
                            content_type=content_type,
                            speaker_count=max(speaker_count, len(speakers)),
                            timestamp=fm.get("timestamp", ""),
                            reason="Multi-speaker conversation without consent metadata",
                        )
                    )
                else:
                    result.clean += 1
            else:
                result.clean += 1

        except Exception:
            log.debug("Failed to parse %s", md_file, exc_info=True)

    return result


def purge_flagged(result: AuditResult, *, dry_run: bool = True) -> int:
    """Delete flagged documents from RAG sources.

    Args:
        result: AuditResult from scan_historical_audio()
        dry_run: If True, only log what would be deleted

    Returns:
        Number of documents deleted (or would be deleted)
    """
    deleted = 0
    for doc in result.documents:
        path = Path(doc.path)
        if path.exists():
            if dry_run:
                log.info("[DRY RUN] Would delete: %s", path)
            else:
                path.unlink()
                log.info("Deleted: %s", path)
            deleted += 1
    return deleted


def save_report(result: AuditResult) -> Path:
    """Save audit results to profiles/consent-audit-report.json."""
    report = {
        "scan_timestamp": result.scan_timestamp,
        "scanned": result.scanned,
        "flagged": result.flagged,
        "clean": result.clean,
        "flagged_documents": [
            {
                "path": d.path,
                "content_type": d.content_type,
                "speaker_count": d.speaker_count,
                "timestamp": d.timestamp,
                "reason": d.reason,
            }
            for d in result.documents
        ],
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    log.info("Saved audit report to %s", REPORT_PATH)
    return REPORT_PATH


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="Historical consent audit")
    parser.add_argument("--scan", action="store_true", help="Scan for flagged documents")
    parser.add_argument("--purge", action="store_true", help="Delete flagged documents")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Dry run (default)")
    parser.add_argument("--confirm", action="store_true", help="Actually delete (requires --purge)")
    parser.add_argument("--report", action="store_true", help="Save report to profiles/")
    args = parser.parse_args()

    result = scan_historical_audio()
    print(f"Scanned: {result.scanned}")
    print(f"Flagged: {result.flagged}")
    print(f"Clean:   {result.clean}")

    if result.flagged:
        print("\nFlagged documents:")
        for doc in result.documents:
            print(f"  {doc.path}")
            print(f"    {doc.reason} (speakers: {doc.speaker_count})")

    if args.purge:
        dry = not args.confirm
        deleted = purge_flagged(result, dry_run=dry)
        mode = "DRY RUN" if dry else "DELETED"
        print(f"\n{mode}: {deleted} documents")

    if args.report:
        path = save_report(result)
        print(f"\nReport saved to {path}")
