#!/usr/bin/env python3
"""ingest.py — RAG document ingestion pipeline.

Watches directories for new/modified files, parses with Docling,
chunks with HybridChunker, embeds via Ollama, upserts to Qdrant.

Run directly or via systemd: systemctl --user start rag-ingest

Dependencies: uv add docling qdrant-client watchdog ollama pydantic
"""

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

# Self-contained config (no shared.config import — this module runs in an
# isolated venv without pydantic-ai due to docling/huggingface-hub conflict).
_HAPAX_HOME = Path(os.environ.get("HAPAX_HOME", str(Path.home())))
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
EMBEDDING_MODEL = "nomic-embed-text-v2-moe"
RAG_SOURCES_DIR = _HAPAX_HOME / "documents" / "rag-sources"
RAG_INGEST_STATE_DIR = _HAPAX_HOME / ".cache" / "rag-ingest"
HAPAX_PROJECTS_DIR = _HAPAX_HOME / "projects"

from shared.log_setup import configure_logging

configure_logging(agent="ingest")
log = logging.getLogger("rag-ingest")

try:
    from shared import langfuse_config  # noqa: F401
    from opentelemetry import trace

    _tracer = trace.get_tracer(__name__)
except ImportError:
    from contextlib import nullcontext

    class _NullTracer:
        def start_as_current_span(self, *a, **kw):
            return nullcontext()

    _tracer = _NullTracer()  # type: ignore


# ── Configuration ────────────────────────────────────────────────────────────


@dataclass
class Config:
    watch_dirs: list[Path] = field(
        default_factory=lambda: [
            RAG_SOURCES_DIR,
            HAPAX_PROJECTS_DIR / "docs",
        ]
    )
    supported_extensions: set[str] = field(
        default_factory=lambda: {
            ".pdf",
            ".docx",
            ".pptx",
            ".html",
            ".md",
            ".txt",
        }
    )
    qdrant_url: str = QDRANT_URL
    collection: str = "documents"
    embedding_model: str = EMBEDDING_MODEL
    chunk_max_tokens: int = 512
    chunk_tokenizer: str = "Qwen/Qwen2.5-7B-Instruct"
    debounce_seconds: float = 2.0  # Wait before processing (avoid partial writes)


CFG = Config()


# ── Retry configuration ─────────────────────────────────────────────────────

RETRY_QUEUE = RAG_INGEST_STATE_DIR / "retry-queue.jsonl"
MAX_RETRIES = 5
BACKOFF_SCHEDULE = [30, 120, 600, 3600, 3600]  # 30s, 2m, 10m, 1h, 1h


@dataclass
class RetryEntry:
    path: str
    error: str
    attempts: int
    next_retry: float  # unix timestamp
    first_failed: float  # unix timestamp


# ── Lazy imports (heavy deps loaded only when needed) ────────────────────────

_converter = None
_chunker = None


def get_converter():
    global _converter
    if _converter is None:
        from docling.document_converter import DocumentConverter

        _converter = DocumentConverter()
        log.info("Docling converter initialized")
    return _converter


def get_chunker():
    global _chunker
    if _chunker is None:
        from docling.chunking import HybridChunker

        _chunker = HybridChunker(
            tokenizer=CFG.chunk_tokenizer,
            max_tokens=CFG.chunk_max_tokens,
        )
        log.info(f"Chunker initialized: {CFG.chunk_max_tokens} max tokens")
    return _chunker


_qclient = None


def get_qdrant():
    global _qclient
    if _qclient is None:
        from qdrant_client import QdrantClient

        _qclient = QdrantClient(QDRANT_URL)
        log.info(f"Qdrant connected: {QDRANT_URL}")
    return _qclient


# ── Core functions ───────────────────────────────────────────────────────────


def embed(text: str, prefix: str = "search_document") -> list[float]:
    """Generate embedding via Ollama with nomic prefix."""
    import ollama

    prefixed = f"{prefix}: {text}" if prefix else text
    result = ollama.embed(model=EMBEDDING_MODEL, input=prefixed)
    return result["embeddings"][0]


def point_id(path: Path, chunk_index: int) -> int:
    """Deterministic point ID from file path + chunk index.
    Allows idempotent upserts — re-ingesting same file overwrites cleanly.
    """
    raw = f"{path.resolve()}:{chunk_index}"
    return int(hashlib.sha256(raw.encode()).hexdigest()[:16], 16)


def delete_file_points(path: Path):
    """Remove all points for a given source file before re-ingesting."""
    from qdrant_client import models

    try:
        get_qdrant().delete(
            CFG.collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="source",
                            match=models.MatchValue(value=str(path.resolve())),
                        )
                    ]
                )
            ),
        )
    except Exception:
        pass  # Collection may not have points yet


def queue_retry(path: Path, error: str, attempts: int = 0):
    """Append a failed file to the retry queue with exponential backoff."""
    attempts += 1
    if attempts > MAX_RETRIES:
        log.error(f"  ✗ Permanent failure after {MAX_RETRIES} retries: {path.name} — {error}")
        return

    delay = BACKOFF_SCHEDULE[min(attempts - 1, len(BACKOFF_SCHEDULE) - 1)]
    entry = RetryEntry(
        path=str(path.resolve()),
        error=error,
        attempts=attempts,
        next_retry=time.time() + delay,
        first_failed=time.time() if attempts == 1 else 0,
    )

    # If this is a re-queue (attempts > 1), preserve first_failed from existing entry
    if attempts > 1:
        for existing in load_retry_queue():
            if existing.path == entry.path:
                entry.first_failed = existing.first_failed
                break

    # Remove any existing entry for this path, then append the new one
    _remove_from_queue(entry.path)

    with open(RETRY_QUEUE, "a") as f:
        f.write(
            json.dumps(
                {
                    "path": entry.path,
                    "error": entry.error,
                    "attempts": entry.attempts,
                    "next_retry": entry.next_retry,
                    "first_failed": entry.first_failed,
                }
            )
            + "\n"
        )

    log.info(f"  ↻ Queued retry {attempts}/{MAX_RETRIES} for {path.name} (next in {delay}s)")


def load_retry_queue() -> list[RetryEntry]:
    """Read the retry queue from JSONL. Returns empty list if file missing."""
    if not RETRY_QUEUE.exists():
        return []
    entries = []
    for line in RETRY_QUEUE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
            entries.append(
                RetryEntry(
                    path=d["path"],
                    error=d["error"],
                    attempts=d["attempts"],
                    next_retry=d["next_retry"],
                    first_failed=d.get("first_failed", 0),
                )
            )
        except (json.JSONDecodeError, KeyError) as e:
            log.warning(f"Skipping corrupt retry queue entry: {e}")
    return entries


def _remove_from_queue(path_str: str):
    """Remove all entries for a given path from the retry queue."""
    if not RETRY_QUEUE.exists():
        return
    entries = [e for e in load_retry_queue() if e.path != path_str]
    _write_queue(entries)


def _write_queue(entries: list[RetryEntry]):
    """Rewrite the retry queue JSONL from a list of entries."""
    with open(RETRY_QUEUE, "w") as f:
        for e in entries:
            f.write(
                json.dumps(
                    {
                        "path": e.path,
                        "error": e.error,
                        "attempts": e.attempts,
                        "next_retry": e.next_retry,
                        "first_failed": e.first_failed,
                    }
                )
                + "\n"
            )


def process_retries():
    """Process due retry entries. Successful retries are removed from the queue."""
    entries = load_retry_queue()
    if not entries:
        return

    now = time.time()
    due = [e for e in entries if now >= e.next_retry]
    if not due:
        return

    log.info(f"Processing {len(due)} retry entries")
    remaining = [e for e in entries if now < e.next_retry]

    for entry in due:
        path = Path(entry.path)
        if not path.exists():
            log.warning(f"  Retry skipped (file gone): {path.name}")
            continue

        log.info(f"  Retrying ({entry.attempts}/{MAX_RETRIES}): {path.name}")
        success, error = ingest_file(path)
        if success:
            log.info(f"  ✓ Retry succeeded: {path.name}")
        else:
            # Re-queue with incremented attempts
            new_attempts = entry.attempts + 1
            if new_attempts > MAX_RETRIES:
                log.error(
                    f"  ✗ Permanent failure after {MAX_RETRIES} retries: {path.name} — {error}"
                )
            else:
                delay = BACKOFF_SCHEDULE[min(new_attempts - 1, len(BACKOFF_SCHEDULE) - 1)]
                remaining.append(
                    RetryEntry(
                        path=entry.path,
                        error=error,
                        attempts=new_attempts,
                        next_retry=time.time() + delay,
                        first_failed=entry.first_failed,
                    )
                )
                log.info(
                    f"  ↻ Re-queued retry {new_attempts}/{MAX_RETRIES} for {path.name} (next in {delay}s)"
                )

    _write_queue(remaining)


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown text.

    Returns (metadata_dict, remaining_text). If no frontmatter found,
    returns ({}, original_text).
    """
    if not text.startswith("---"):
        return {}, text

    # Find closing ---
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text

    front = text[3:end].strip()
    body = text[end + 4 :].strip()

    metadata: dict = {}
    for line in front.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()

        # Parse list values: [a, b, c]
        if value.startswith("[") and value.endswith("]"):
            items = [v.strip() for v in value[1:-1].split(",") if v.strip()]
            metadata[key] = items
        # Strip quotes
        elif value.startswith('"') and value.endswith('"'):
            metadata[key] = value[1:-1]
        else:
            metadata[key] = value

    return metadata, body


def enrich_payload(base_payload: dict, frontmatter: dict) -> dict:
    """Add frontmatter fields to the Qdrant payload if present.

    Only adds known takeout/llm-export fields — doesn't blindly
    copy everything from frontmatter.
    """
    enrichment_keys = {
        "content_type",
        "source_service",
        "source_platform",
        "timestamp",
        "modality_tags",
        "people",
        "platform",
        "service",  # takeout frontmatter uses these names
        "record_id",
        "categories",
        "location",
        "gdrive_folder",
    }

    for key in enrichment_keys:
        if key in frontmatter:
            value = frontmatter[key]
            # Normalize key names for consistency in Qdrant
            if key == "platform":
                base_payload["source_platform"] = value
            elif key == "service":
                base_payload["source_service"] = value
            else:
                base_payload[key] = value

    # Auto-detect source_service from file path if not set by frontmatter
    if "source_service" not in base_payload or not base_payload["source_service"]:
        source_path = base_payload.get("source", "")
        _SERVICE_PATH_PATTERNS = {
            "rag-sources/gdrive": "gdrive",
            "rag-sources/gcalendar": "gcalendar",
            "rag-sources/gmail": "gmail",
            "rag-sources/youtube": "youtube",
            "rag-sources/takeout": "takeout",
            "rag-sources/proton": "proton",
            "rag-sources/claude-code": "claude-code",
            "rag-sources/obsidian": "obsidian",
            "rag-sources/chrome": "chrome",
            "rag-sources/audio": "ambient-audio",
            "rag-sources/health-connect": "health_connect",
        }
        for pattern, service in _SERVICE_PATH_PATTERNS.items():
            if pattern in source_path:
                base_payload["source_service"] = service
                # Extract top-level subfolder for gdrive
                if service == "gdrive":
                    idx = source_path.find(pattern) + len(pattern) + 1
                    remainder = source_path[idx:]
                    top_folder = remainder.split("/")[0] if remainder else ""
                    if top_folder and top_folder != ".meta":
                        base_payload["gdrive_folder"] = top_folder
                break

    return base_payload


DEDUP_PATH = RAG_INGEST_STATE_DIR / "processed.json"


def _load_dedup_tracker() -> dict:
    """Load the dedup tracker from disk."""
    if DEDUP_PATH.exists():
        try:
            return json.loads(DEDUP_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_dedup_tracker(tracker: dict) -> None:
    """Persist the dedup tracker."""
    DEDUP_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEDUP_PATH.write_text(json.dumps(tracker, indent=2))


def _file_hash(path: Path) -> str:
    """Compute SHA256 hash of a file's contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _should_skip(path: Path, tracker: dict) -> bool:
    """Check if a file has already been ingested (same hash and mtime)."""
    key = str(path)
    if key not in tracker:
        return False
    entry = tracker[key]
    try:
        current_mtime = path.stat().st_mtime
        if entry.get("mtime") == current_mtime and entry.get("hash") == _file_hash(path):
            return True
    except OSError:
        pass
    return False


def _record_ingested(path: Path, tracker: dict) -> None:
    """Record a file as successfully ingested."""
    tracker[str(path)] = {
        "hash": _file_hash(path),
        "mtime": path.stat().st_mtime,
        "ingested_at": datetime.now().isoformat(),
    }


def ingest_file(path: Path) -> tuple[bool, str]:
    """Parse, chunk, embed, and upsert a single file.

    Returns (True, "") on success, (False, error_message) on failure.
    """
    if path.suffix.lower() not in CFG.supported_extensions:
        return (True, "")
    if not path.is_file():
        return (True, "")
    # Skip macOS resource forks and __MACOSX junk
    if path.name.startswith("._") or "/__MACOSX/" in str(path):
        return (True, "")
    # Skip binary files masquerading as text
    if path.suffix.lower() in (".txt", ".md") and path.stat().st_size < 1024:
        try:
            path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            log.debug(f"Skipping binary file with text extension: {path.name}")
            return (True, "")

    log.info(f"Ingesting: {path.name}")
    start = time.monotonic()

    try:
        # Parse document
        result = get_converter().convert(str(path))
        chunks = list(get_chunker().chunk(result.document))

        if not chunks:
            log.warning(f"  No chunks extracted from {path.name}")
            return (True, "")

        # Check for YAML frontmatter in markdown files
        frontmatter: dict = {}
        if path.suffix.lower() == ".md":
            try:
                raw_text = path.read_text(encoding="utf-8", errors="replace")
                frontmatter, _ = parse_frontmatter(raw_text)
            except Exception:
                pass  # Frontmatter parsing is best-effort

        # Delete existing points for this file (idempotent re-ingest)
        delete_file_points(path)

        # Embed and upsert
        from qdrant_client import models

        points = []
        for i, chunk in enumerate(chunks):
            try:
                vec = embed(chunk.text)
                payload = {
                    "text": chunk.text,
                    "source": str(path.resolve()),
                    "filename": path.name,
                    "extension": path.suffix.lower(),
                    "chunk_index": i,
                    "chunk_count": len(chunks),
                    "ingested_at": time.time(),
                }
                # Enrich with frontmatter metadata and path-based auto-detection
                payload = enrich_payload(payload, frontmatter)
                points.append(
                    models.PointStruct(
                        id=point_id(path, i),
                        vector=vec,
                        payload=payload,
                    )
                )
            except Exception as e:
                log.error(f"  Embedding failed for chunk {i}: {e}")

        if points:
            # Batch upsert (Qdrant handles batching internally)
            get_qdrant().upsert(CFG.collection, points, wait=True)
            elapsed = time.monotonic() - start
            log.info(f"  ✓ {len(points)} chunks in {elapsed:.1f}s")
        else:
            log.warning(f"  No points generated for {path.name}")

        return (True, "")

    except Exception as e:
        log.error(f"  ✗ Failed: {e}")
        return (False, str(e))


# ── File watcher ─────────────────────────────────────────────────────────────


class IngestHandler(FileSystemEventHandler):
    """Debounced file system event handler."""

    def __init__(self):
        self._pending: dict[str, float] = {}

    def _schedule(self, path: str):
        self._pending[path] = time.monotonic()

    def process_pending(self):
        """Process files that have been stable for debounce_seconds."""
        now = time.monotonic()
        ready = [p for p, t in self._pending.items() if now - t >= CFG.debounce_seconds]
        for path_str in ready:
            del self._pending[path_str]
            path = Path(path_str)
            success, error = ingest_file(path)
            if not success:
                queue_retry(path, error)

    def on_created(self, event):
        if not event.is_directory:
            self._schedule(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._schedule(event.src_path)


# ── Main ─────────────────────────────────────────────────────────────────────


def bulk_ingest(force: bool = False):
    """Initial scan of all watched directories."""
    tracker = {} if force else _load_dedup_tracker()
    skipped = 0
    total = 0
    for d in CFG.watch_dirs:
        if not d.exists():
            log.info(f"Creating watch directory: {d}")
            d.mkdir(parents=True, exist_ok=True)
            continue
        files = [
            f for f in d.rglob("*") if f.is_file() and f.suffix.lower() in CFG.supported_extensions
        ]
        log.info(f"Bulk ingesting {len(files)} files from {d}")
        for f in sorted(files):
            if not force and _should_skip(f, tracker):
                skipped += 1
                continue
            success, error = ingest_file(f)
            if success:
                _record_ingested(f, tracker)
            else:
                queue_retry(f, error)
            total += 1
    if not force:
        _save_dedup_tracker(tracker)
    if skipped:
        log.info("Skipped %d unchanged files (use --force to re-ingest)", skipped)
    # Process any retries from previous runs
    process_retries()
    return total


def watch():
    """Start file system watcher."""
    handler = IngestHandler()
    observer = Observer()

    for d in CFG.watch_dirs:
        d.mkdir(parents=True, exist_ok=True)
        observer.schedule(handler, str(d), recursive=True)
        log.info(f"Watching: {d}")

    observer.start()
    log.info("File watcher active. Press Ctrl+C to stop.")

    last_retry_check = 0.0
    try:
        while True:
            handler.process_pending()
            now = time.monotonic()
            if now - last_retry_check >= 30:
                process_retries()
                last_retry_check = now
            time.sleep(0.5)
    except KeyboardInterrupt:
        log.info("Shutting down...")
        observer.stop()
    observer.join()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="RAG document ingestion pipeline")
    parser.add_argument("--bulk-only", action="store_true", help="Ingest existing files and exit")
    parser.add_argument("--watch-only", action="store_true", help="Skip bulk ingest, only watch")
    parser.add_argument("--retry-status", action="store_true", help="Show retry queue and exit")
    parser.add_argument(
        "--force", action="store_true", help="Bypass dedup tracking, re-ingest all files"
    )
    args = parser.parse_args()

    if args.retry_status:
        from datetime import datetime

        entries = load_retry_queue()
        if not entries:
            print("Retry queue is empty.")
        else:
            print(f"Retry queue: {len(entries)} entries\n")
            for e in entries:
                next_dt = datetime.fromtimestamp(e.next_retry).strftime("%Y-%m-%d %H:%M:%S")
                failed_dt = (
                    datetime.fromtimestamp(e.first_failed).strftime("%Y-%m-%d %H:%M:%S")
                    if e.first_failed
                    else "unknown"
                )
                status = "DUE" if time.time() >= e.next_retry else "WAITING"
                print(f"  [{status}] {Path(e.path).name}")
                print(f"    Path:         {e.path}")
                print(f"    Attempts:     {e.attempts}/{MAX_RETRIES}")
                print(f"    First failed: {failed_dt}")
                print(f"    Next retry:   {next_dt}")
                print(f"    Error:        {e.error}")
                print()
        raise SystemExit(0)

    if not args.watch_only:
        with _tracer.start_as_current_span(
            "ingest.bulk",
            attributes={"agent.name": "ingest", "agent.repo": "hapax-council"},
        ):
            count = bulk_ingest(force=args.force)
            log.info(f"Bulk ingest complete: {count} files processed")

    if not args.bulk_only:
        with _tracer.start_as_current_span(
            "ingest.watch",
            attributes={"agent.name": "ingest", "agent.repo": "hapax-council"},
        ):
            watch()
