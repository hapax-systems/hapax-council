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
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from agents._frontmatter import parse_frontmatter

# Self-contained config (no shared.config import — this module runs in an
# isolated venv without pydantic-ai due to docling/huggingface-hub conflict).
_HAPAX_HOME = Path(os.environ.get("HAPAX_HOME", str(Path.home())))
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "nomic-embed-cpu")
DEFAULT_DOCUMENTS_COLLECTION = "documents"
RAG_SOURCES_DIR = _HAPAX_HOME / "documents" / "rag-sources"
RAG_INGEST_STATE_DIR = _HAPAX_HOME / ".cache" / "rag-ingest"
HAPAX_PROJECTS_DIR = _HAPAX_HOME / "projects"
PLAIN_TEXT_SOURCE_EXTENSIONS = {".html", ".md", ".py", ".txt"}

from agents._log_setup import configure_logging

configure_logging(agent="ingest")
log = logging.getLogger("rag-ingest")

try:
    from opentelemetry import trace

    from agents import _langfuse_config  # noqa: F401

    _tracer = trace.get_tracer(__name__)
except ImportError:
    from contextlib import nullcontext

    class _NullTracer:
        def start_as_current_span(self, *a, **kw):
            return nullcontext()

    _tracer = _NullTracer()  # type: ignore


# ── Configuration ────────────────────────────────────────────────────────────


def resolve_documents_collection(env: dict[str, str] | None = None) -> str:
    """Resolve the Qdrant documents collection without changing the default."""
    source = env if env is not None else os.environ
    return (
        source.get("HAPAX_RAG_COLLECTION")
        or source.get("RAG_DOCUMENTS_COLLECTION")
        or DEFAULT_DOCUMENTS_COLLECTION
    )


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
            ".py",
            ".txt",
        }
    )
    qdrant_url: str = QDRANT_URL
    collection: str = field(default_factory=resolve_documents_collection)
    embedding_model: str = EMBEDDING_MODEL
    chunk_max_tokens: int = 1024
    chunk_tokenizer: str = "Qwen/Qwen2.5-7B-Instruct"
    debounce_seconds: float = 2.0  # Wait before processing (avoid partial writes)


CFG = Config()


# ── Retry configuration ─────────────────────────────────────────────────────

RETRY_QUEUE = RAG_INGEST_STATE_DIR / "retry-queue.jsonl"
DEAD_LETTER_PATH = RAG_INGEST_STATE_DIR / "dead-letter.jsonl"
MAX_RETRIES = 5
BACKOFF_SCHEDULE = [30, 120, 600, 3600, 3600]  # 30s, 2m, 10m, 1h, 1h


@dataclass
class RetryEntry:
    path: str
    error: str
    attempts: int
    next_retry: float  # unix timestamp
    first_failed: float  # unix timestamp


@dataclass(frozen=True)
class TextChunk:
    text: str


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


def plain_text_chunks(text: str, *, max_chars: int = 4096) -> list[TextChunk]:
    """Chunk source-like text without Docling so common RAG paths stay lightweight."""
    chunks: list[str] = []
    current: list[str] = []
    current_size = 0
    for line in text.splitlines(keepends=True):
        line_size = len(line)
        if current and current_size + line_size > max_chars:
            chunks.append("".join(current).strip())
            current = []
            current_size = 0
        if line_size > max_chars:
            chunks.extend(
                line[index : index + max_chars].strip()
                for index in range(0, line_size, max_chars)
                if line[index : index + max_chars].strip()
            )
            continue
        current.append(line)
        current_size += line_size
    if current:
        chunks.append("".join(current).strip())
    return [TextChunk(text=chunk) for chunk in chunks if chunk]


def extract_chunks(path: Path) -> list[TextChunk]:
    if path.suffix.lower() in PLAIN_TEXT_SOURCE_EXTENSIONS:
        return plain_text_chunks(
            path.read_text(encoding="utf-8", errors="replace"),
            max_chars=CFG.chunk_max_tokens * 4,
        )
    result = get_converter().convert(str(path))
    return [TextChunk(text=chunk.text) for chunk in get_chunker().chunk(result.document)]


_qclient = None
_qclient_url: str | None = None


def get_qdrant():
    global _qclient, _qclient_url
    if _qclient is None or _qclient_url != CFG.qdrant_url:
        from qdrant_client import QdrantClient

        _qclient = QdrantClient(CFG.qdrant_url)
        _qclient_url = CFG.qdrant_url
        log.info(f"Qdrant connected: {CFG.qdrant_url}")
    return _qclient


# ── Core functions ───────────────────────────────────────────────────────────


def embedding_dimensions() -> int:
    """Return vector dimensions from the currently selected embedding model."""
    return len(embed("hapax rag collection schema probe", prefix="search_document"))


def _collection_exists(client, collection: str) -> bool:
    collections = client.get_collections().collections
    return any(getattr(item, "name", None) == collection for item in collections)


def ensure_collection(
    collection: str | None = None,
    *,
    vector_size: int | None = None,
    client=None,
) -> bool:
    """Create a documents-compatible Qdrant collection if it is missing.

    Returns True when the collection was created, False when it already existed.
    """
    target = collection or CFG.collection
    qdrant = client or get_qdrant()
    if _collection_exists(qdrant, target):
        return False
    if vector_size is None:
        vector_size = embedding_dimensions()

    from qdrant_client.models import Distance, VectorParams

    qdrant.create_collection(
        collection_name=target,
        vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
    )
    log.info("Created Qdrant collection %s (%d-dim, cosine)", target, vector_size)
    return True


def embed(text: str, prefix: str = "search_document") -> list[float]:
    """Generate embedding via Ollama with nomic prefix."""
    return embed_batch([text], prefix=prefix)[0]


def embed_batch(texts: list[str], prefix: str = "search_document") -> list[list[float]]:
    """Generate embeddings for multiple texts in a single Ollama call."""
    import ollama

    prefixed = [f"{prefix}: {t}" if prefix else t for t in texts]
    result = ollama.embed(model=CFG.embedding_model, input=prefixed)
    return result["embeddings"]


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


def _dead_letter(path: Path, error: str, attempts: int) -> None:
    """Record a permanently failed file so it can be resurfaced later."""
    DEAD_LETTER_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "path": str(path.resolve()),
        "error": error,
        "attempts": attempts,
        "failed_at": datetime.now().isoformat(),
    }
    with open(DEAD_LETTER_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")
    log.error(
        f"  ✗ Permanent failure after {attempts} retries: {path.name} — {error}"
        f" (recorded in dead-letter queue)"
    )


def queue_retry(path: Path, error: str, attempts: int = 0):
    """Append a failed file to the retry queue with exponential backoff."""
    attempts += 1
    if attempts > MAX_RETRIES:
        _dead_letter(path, error, attempts)
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
                _dead_letter(path, error, new_attempts)
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
        "content_tier",
        "is_metadata_only",
        "location",
        "gdrive_folder",
        "provenance",  # DD-20: why-provenance contract IDs
        "retrieval_eligible",
    }

    # DD-11: Extract consent label from frontmatter if present
    from agents._frontmatter import extract_consent_label, extract_provenance

    consent_label = extract_consent_label(frontmatter)
    if consent_label is not None:
        # Serialize as list of dicts for Qdrant JSON payload
        base_payload["consent_label"] = [
            {"owner": owner, "readers": sorted(readers)}
            for owner, readers in consent_label.policies
        ]

    provenance = extract_provenance(frontmatter)
    if provenance:
        base_payload["provenance"] = sorted(provenance)

    for key in enrichment_keys:
        if key in frontmatter:
            value = frontmatter[key]
            # Normalize key names for consistency in Qdrant
            if key == "platform":
                base_payload.setdefault("source_platform", value)
            elif key == "service":
                base_payload.setdefault("source_service", value)
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
    """Load the dedup tracker from disk.

    Validates the JSON root is a mapping. The tracker is consumed by
    ``_should_skip(file, tracker)`` and ``tracker[str(path)] = {...}``
    — both crash on non-dict roots. A writer producing valid JSON
    whose root is null, a list, a string, or a number previously
    raised AttributeError or TypeError out of the bulk-ingest loop.
    Same shape as the other recent SHM-read fixes.
    """
    if DEDUP_PATH.exists():
        try:
            data = json.loads(DEDUP_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
        if isinstance(data, dict):
            return data
    return {}


def _save_dedup_tracker(tracker: dict) -> None:
    """Persist the dedup tracker atomically (tmp file + rename)."""
    DEDUP_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=DEDUP_PATH.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(tracker, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.rename(tmp_path, DEDUP_PATH)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _file_hash(path: Path) -> str:
    """Compute SHA256 hash of a file's contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _dedup_key(path: Path, collection: str | None = None) -> str:
    """Return the dedup key, preserving the legacy key for `documents`."""
    target = collection or CFG.collection
    raw_path = str(path)
    if target == DEFAULT_DOCUMENTS_COLLECTION:
        return raw_path
    return f"{target}:{raw_path}"


def _should_skip(path: Path, tracker: dict, collection: str | None = None) -> bool:
    """Check if a file has already been ingested (same hash and mtime)."""
    key = _dedup_key(path, collection)
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


def _record_ingested(path: Path, tracker: dict, collection: str | None = None) -> None:
    """Record a file as successfully ingested."""
    tracker[_dedup_key(path, collection)] = {
        "hash": _file_hash(path),
        "mtime": path.stat().st_mtime,
        "ingested_at": datetime.now().isoformat(),
    }


def _check_consent_for_ingest(payload: dict) -> bool:
    """Check if all persons in payload have active consent contracts.

    Returns True if safe to ingest, False if unconsented persons present.
    Degrades gracefully — if the consent registry is unavailable, allows
    ingestion (sync agents already filter upstream).
    """
    people = payload.get("people", [])
    if not people:
        return True  # No persons — safe

    try:
        from shared.governance.consent import ConsentRegistry

        registry = ConsentRegistry()
        registry.load()
    except Exception:
        return True  # Registry unavailable — degrade gracefully

    source_service = payload.get("source_service", "document")
    return all(registry.contract_check(str(person), source_service) for person in people)


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
        # Parse document or source-like text.
        chunks = extract_chunks(path)

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

        # Embed and upsert
        from qdrant_client import models

        points = []
        # Batch embed all chunks in a single Ollama call
        chunk_texts = [c.text for c in chunks]
        try:
            vectors = embed_batch(chunk_texts)
        except Exception as e:
            log.error(f"  Batch embedding failed: {e}")
            vectors = None

        if vectors and len(vectors) == len(chunks):
            now = time.time()
            for i, (chunk, vec) in enumerate(zip(chunks, vectors, strict=True)):
                payload = {
                    "text": chunk.text,
                    "source": str(path.resolve()),
                    "filename": path.name,
                    "extension": path.suffix.lower(),
                    "chunk_index": i,
                    "chunk_count": len(chunks),
                    "ingested_at": now,
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

        # Consent check: skip if unconsented persons in any chunk payload
        if points and not _check_consent_for_ingest(points[0].payload):
            log.info("Consent: skipping %s — unconsented persons in payload", path.name)
            return (True, "consent_skipped")

        if points:
            ensure_collection(CFG.collection, vector_size=len(points[0].vector))
            # Delete existing points for this file after embedding succeeds so
            # transient embedding failures cannot erase the previous index.
            delete_file_points(path)
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


class IngestHandler:
    """Debounced file system event handler."""

    def __init__(self):
        self._pending: dict[str, float] = {}

    def dispatch(self, event):
        """Minimal watchdog-compatible dispatcher for created/modified files."""
        event_type = getattr(event, "event_type", "")
        if event_type == "created":
            self.on_created(event)
        elif event_type == "modified":
            self.on_modified(event)

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


def bulk_ingest(
    force: bool = False,
    *,
    max_files: int | None = None,
    dry_run: bool = False,
    source_files: list[Path] | None = None,
    process_retry_queue: bool = True,
):
    """Initial scan of all watched directories."""
    tracker = {} if force else _load_dedup_tracker()
    skipped = 0
    total = 0
    if source_files is not None:
        files = sorted(
            {
                f
                for f in source_files
                if f.is_file() and f.suffix.lower() in CFG.supported_extensions
            }
        )
        log.info("Bulk ingesting %d explicit source files", len(files))
        for f in files:
            if max_files is not None and total >= max_files:
                break
            if not force and _should_skip(f, tracker, collection=CFG.collection):
                skipped += 1
                continue
            if dry_run:
                log.info("DRY RUN: would ingest %s into %s", f, CFG.collection)
                total += 1
                continue
            success, error = ingest_file(f)
            if success:
                _record_ingested(f, tracker, collection=CFG.collection)
            else:
                queue_retry(f, error)
            total += 1
        if not force and not dry_run:
            _save_dedup_tracker(tracker)
        if skipped:
            log.info("Skipped %d unchanged files (use --force to re-ingest)", skipped)
        return total

    for d in CFG.watch_dirs:
        if max_files is not None and total >= max_files:
            break
        if not d.exists():
            log.info(f"Creating watch directory: {d}")
            if not dry_run:
                d.mkdir(parents=True, exist_ok=True)
            continue
        files = [
            f for f in d.rglob("*") if f.is_file() and f.suffix.lower() in CFG.supported_extensions
        ]
        log.info(f"Bulk ingesting {len(files)} files from {d}")
        for f in sorted(files):
            if max_files is not None and total >= max_files:
                break
            if not force and _should_skip(f, tracker, collection=CFG.collection):
                skipped += 1
                continue
            if dry_run:
                log.info("DRY RUN: would ingest %s into %s", f, CFG.collection)
                total += 1
                continue
            success, error = ingest_file(f)
            if success:
                _record_ingested(f, tracker, collection=CFG.collection)
            else:
                queue_retry(f, error)
            total += 1
    if not force and not dry_run:
        _save_dedup_tracker(tracker)
    if skipped:
        log.info("Skipped %d unchanged files (use --force to re-ingest)", skipped)
    # Process any retries from previous runs
    if not dry_run and process_retry_queue:
        process_retries()
    return total


def watch():
    """Start file system watcher."""
    from watchdog.observers import Observer

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
        "--collection",
        default=CFG.collection,
        help=(
            "Qdrant collection to write. Defaults to HAPAX_RAG_COLLECTION, "
            "RAG_DOCUMENTS_COLLECTION, then documents."
        ),
    )
    parser.add_argument("--qdrant-url", default=CFG.qdrant_url)
    parser.add_argument("--embedding-model", default=CFG.embedding_model)
    parser.add_argument(
        "--watch-dir",
        action="append",
        type=Path,
        default=[],
        help="Override watched/source directory. May be repeated.",
    )
    parser.add_argument(
        "--source-file",
        action="append",
        type=Path,
        default=[],
        help="Explicit file to ingest instead of scanning watch directories. May be repeated.",
    )
    parser.add_argument(
        "--source-file-list",
        action="append",
        type=Path,
        default=[],
        help="Text file containing one source path per line. Blank lines and # comments ignored.",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Maximum number of non-skipped files to process in this run.",
    )
    parser.add_argument("--dry-run", action="store_true", help="List files that would be ingested.")
    parser.add_argument(
        "--create-collection",
        action="store_true",
        help="Create the configured collection from the selected embedding model and exit.",
    )
    parser.add_argument(
        "--force", action="store_true", help="Bypass dedup tracking, re-ingest all files"
    )
    parser.add_argument(
        "--skip-retries",
        action="store_true",
        help="Do not process the global retry queue after this bulk run.",
    )
    args = parser.parse_args()
    if args.dry_run:
        args.bulk_only = True
    if args.source_file or args.source_file_list:
        args.bulk_only = True

    CFG.collection = args.collection
    CFG.qdrant_url = args.qdrant_url
    CFG.embedding_model = args.embedding_model
    if args.watch_dir:
        CFG.watch_dirs = args.watch_dir
    source_files = list(args.source_file)
    for list_path in args.source_file_list:
        for line in list_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                source_files.append(Path(stripped))

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

    if args.create_collection:
        created = ensure_collection(CFG.collection)
        status = "created" if created else "already exists"
        print(f"{CFG.collection}: {status}")
        raise SystemExit(0)

    if not args.watch_only:
        with _tracer.start_as_current_span(
            "ingest.bulk",
            attributes={
                "agent.name": "ingest",
                "agent.repo": "hapax-council",
                "rag.collection": CFG.collection,
            },
        ):
            count = bulk_ingest(
                force=args.force,
                max_files=args.max_files,
                dry_run=args.dry_run,
                source_files=source_files or None,
                process_retry_queue=not args.skip_retries and not source_files,
            )
            log.info(f"Bulk ingest complete: {count} files processed")

    if not args.bulk_only:
        with _tracer.start_as_current_span(
            "ingest.watch",
            attributes={
                "agent.name": "ingest",
                "agent.repo": "hapax-council",
                "rag.collection": CFG.collection,
            },
        ):
            watch()
