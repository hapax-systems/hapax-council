"""Phase 1 reactive rules — local GPU processing.

Includes: RAG source ingestion, audio archive sidecar, audio CLAP indexing.
"""

from __future__ import annotations

import asyncio
import logging

from logos.engine.models import Action, ChangeEvent
from logos.engine.rules import Rule

_log = logging.getLogger(__name__)


# ── RAG source ingestion ────────────────────────────────────────────────────


async def _handle_rag_ingest(*, path: str) -> str:
    """Ingest a new RAG source file. Runs in thread (sync function).

    NOTE: docling is installed in a separate venv (.venv-ingest) due to
    dependency conflicts with pydantic-ai.  The rag-ingest.service handles
    ingestion independently.  If docling is unavailable here, skip gracefully.
    """
    from pathlib import Path

    try:
        from agents.ingest import ingest_file
    except (ImportError, ModuleNotFoundError) as exc:
        _log.debug("Skipping reactive ingest (docling not in this venv): %s", exc)
        return f"skipped:{Path(path).name}"

    file_path = Path(path)
    success, error = await asyncio.to_thread(ingest_file, file_path)
    if success:
        _log.info("Ingested RAG source: %s", file_path.name)
        return f"ingested:{file_path.name}"
    else:
        _log.warning("Ingest failed for %s: %s", file_path.name, error)
        raise RuntimeError(f"Ingest failed: {error}")


def _rag_source_filter(event: ChangeEvent) -> bool:
    if event.event_type not in ("created", "modified"):
        return False
    return event.source_service is not None


def _rag_source_produce(event: ChangeEvent) -> list[Action]:
    return [
        Action(
            name=f"rag-ingest:{event.path}",
            handler=_handle_rag_ingest,
            args={"path": str(event.path)},
            phase=1,
            priority=50,
        )
    ]


RAG_SOURCE_RULE = Rule(
    name="rag-source-landed",
    description="Ingest new RAG source files via local GPU embeddings",
    trigger_filter=_rag_source_filter,
    produce=_rag_source_produce,
    phase=1,
    cooldown_s=0,
)


# ── Audio archive sidecar ───────────────────────────────────────────────────


async def _handle_audio_archive_sidecar(*, path: str) -> str:
    _log.info("Audio archive sidecar created: %s", path)
    return f"audio-sidecar:{path}"


def _audio_archive_sidecar_filter(event: ChangeEvent) -> bool:
    if event.event_type != "created":
        return False
    path_str = str(event.path)
    return "audio-recording/archive" in path_str and event.path.suffix == ".md"


def _audio_archive_sidecar_produce(event: ChangeEvent) -> list[Action]:
    return [
        Action(
            name=f"audio-archive-sidecar:{event.path.name}",
            handler=_handle_audio_archive_sidecar,
            args={"path": str(event.path)},
            phase=0,
            priority=15,
        )
    ]


AUDIO_ARCHIVE_SIDECAR_RULE = Rule(
    name="audio-archive-sidecar",
    description="Log new audio archive sidecars (Phase 0, deterministic)",
    trigger_filter=_audio_archive_sidecar_filter,
    produce=_audio_archive_sidecar_produce,
    phase=0,
    cooldown_s=0,
)


# ── Audio CLAP indexed ──────────────────────────────────────────────────────


async def _handle_audio_clap_indexed(*, path: str) -> str:
    from pathlib import Path as _Path

    try:
        from agents.ingest import ingest_file
    except (ImportError, ModuleNotFoundError) as exc:
        _log.debug("Skipping CLAP audio ingest (docling not in this venv): %s", exc)
        return f"skipped:{_Path(path).name}"

    file_path = _Path(path)
    success, error = await asyncio.to_thread(ingest_file, file_path)
    if success:
        _log.info("CLAP-indexed audio RAG ingested: %s", file_path.name)
        return f"clap-ingested:{file_path.name}"
    else:
        _log.warning("CLAP audio ingest failed for %s: %s", file_path.name, error)
        raise RuntimeError(f"CLAP audio ingest failed: {error}")


def _audio_clap_indexed_filter(event: ChangeEvent) -> bool:
    if event.event_type != "created":
        return False
    path_str = str(event.path)
    if "rag-sources/audio" not in path_str:
        return False
    name = event.path.name
    return name.startswith(("listening-", "sample-", "note-", "conv-"))


def _audio_clap_indexed_produce(event: ChangeEvent) -> list[Action]:
    return [
        Action(
            name=f"audio-clap-indexed:{event.path.name}",
            handler=_handle_audio_clap_indexed,
            args={"path": str(event.path)},
            phase=1,
            priority=55,
        )
    ]


AUDIO_CLAP_INDEXED_RULE = Rule(
    name="audio-clap-indexed",
    description="Ingest CLAP-indexed audio RAG documents via local GPU embeddings",
    trigger_filter=_audio_clap_indexed_filter,
    produce=_audio_clap_indexed_produce,
    phase=1,
    cooldown_s=0,
)
