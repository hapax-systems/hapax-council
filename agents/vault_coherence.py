"""Vault Coherence Agent — density field knowledge zone + wikilink assertions.

Reads vault embeddings from Qdrant and the wikilink graph from obsidian_sync
state, then writes:
1. Two knowledge density signals to /dev/shm/hapax-density-field/
2. Wikilink assertions to Qdrant assertions collection

Run: uv run python -m agents.vault_coherence
Timer: hapax-vault-coherence.timer (15min)
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from qdrant_client import QdrantClient

log = logging.getLogger(__name__)

DENSITY_SHM_PATH = Path("/dev/shm/hapax-density-field/knowledge-signals.json")
HIGH_SIMILARITY_THRESHOLD = 0.65


def _load_wikilink_graph() -> dict[str, list[str]]:
    """Load the wikilink graph from obsidian_sync rag-sources output."""
    from shared.frontmatter import parse_frontmatter

    rag_dir = Path.home() / "documents" / "rag-sources" / "obsidian"
    graph: dict[str, list[str]] = {}
    if not rag_dir.is_dir():
        return graph

    for md_file in rag_dir.rglob("*.md"):
        try:
            raw = md_file.read_text(encoding="utf-8", errors="replace")
            fm, _ = parse_frontmatter(raw)
            if not fm:
                continue
            links = fm.get("links", [])
            filename = fm.get("filename") or md_file.name
            if isinstance(links, list) and links:
                graph[filename] = [str(link) for link in links]
        except Exception:
            continue
    return graph


def _compute_knowledge_signals(
    client: QdrantClient, graph: dict[str, list[str]]
) -> dict[str, float]:
    """Compute knowledge density signals via vectorized cosine on a sample."""
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    note_vectors: dict[str, list[float]] = {}
    note_links: dict[str, list[str]] = {}

    try:
        offset = None
        while True:
            batch, offset = client.scroll(
                "documents",
                scroll_filter=Filter(
                    must=[FieldCondition(key="source_service", match=MatchValue(value="obsidian"))]
                ),
                limit=256,
                offset=offset,
                with_vectors=True,
                with_payload=True,
            )
            for point in batch:
                p = point.payload or {}
                fn = p.get("filename", "")
                if not fn or fn in note_vectors:
                    continue
                if isinstance(point.vector, list):
                    note_vectors[fn] = point.vector
                note_links[fn] = p.get("links", []) or []
            if offset is None:
                break
    except Exception:
        log.warning("Qdrant scroll failed — returning default signals", exc_info=True)
        return {"link_deficit": 1.0, "hub_potential": 0.0}

    filenames = list(note_vectors.keys())
    if len(filenames) < 2:
        return {"link_deficit": 1.0, "hub_potential": 0.0}

    sample_size = min(len(filenames), 500)
    rng = np.random.default_rng(42)
    sample_indices = rng.choice(len(filenames), size=sample_size, replace=False)
    sample_fns = [filenames[i] for i in sample_indices]

    sample_vecs = np.array([note_vectors[fn] for fn in sample_fns], dtype=np.float32)
    norms = np.linalg.norm(sample_vecs, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    normalized = sample_vecs / norms
    sim_matrix = normalized @ normalized.T

    high_sim_pairs = 0
    linked_high_sim = 0
    hub_scores: dict[str, int] = {}

    for i, fn_a in enumerate(sample_fns):
        links_a = {link.lower() for link in note_links.get(fn_a, [])}
        stem_a = Path(fn_a).stem.lower()
        unlinked_sim_count = 0

        for j in range(i + 1, sample_size):
            cosine = float(sim_matrix[i, j])
            if cosine < HIGH_SIMILARITY_THRESHOLD:
                continue

            high_sim_pairs += 1
            fn_b = sample_fns[j]
            stem_b = Path(fn_b).stem.lower()
            links_b = {link.lower() for link in note_links.get(fn_b, [])}

            if stem_b in links_a or stem_a in links_b:
                linked_high_sim += 1
            else:
                unlinked_sim_count += 1

        hub_scores[fn_a] = max(0, unlinked_sim_count - len(links_a))

    link_deficit = 1.0 - (linked_high_sim / high_sim_pairs) if high_sim_pairs > 0 else 1.0
    max_hub = max(hub_scores.values()) if hub_scores else 0
    # Normalize relative to sample: 4% of sample having unlinked similarity = 1.0
    hub_potential = min(1.0, max_hub / max(sample_size * 0.04, 1.0))

    return {
        "link_deficit": round(link_deficit, 4),
        "hub_potential": round(hub_potential, 4),
    }


def _write_density_signals(signals: dict[str, float]) -> None:
    """Atomic write to density field SHM via tmp-replace."""
    try:
        DENSITY_SHM_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = DENSITY_SHM_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(signals), encoding="utf-8")
        tmp.replace(DENSITY_SHM_PATH)
        log.info("Wrote knowledge density signals: %s", signals)
    except Exception:
        log.warning("Failed to write density signals to SHM", exc_info=True)


def _upsert_wikilink_assertions(
    client: QdrantClient, graph: dict[str, list[str]], graph_hash: str
) -> int:
    """Upsert wikilink assertions. Skips if graph unchanged since last run."""
    from qdrant_client.models import PointStruct

    state_path = Path.home() / ".cache" / "hapax" / "vault-coherence-state.json"
    try:
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if state.get("graph_hash") == graph_hash:
                log.info("Wikilink graph unchanged — skipping assertion upsert")
                return 0
    except Exception:
        pass

    points = []
    now = time.time()
    for source, targets in graph.items():
        for target in targets:
            pid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"wikilink:{source}:{target}"))
            points.append(
                PointStruct(
                    id=pid,
                    vector=[0.0] * 768,
                    payload={
                        "source_type": "wikilink",
                        "source_note": source,
                        "target_note": target,
                        "provenance": "manual",
                        "confidence": 1.0,
                        "timestamp": now,
                    },
                )
            )

    if points:
        for i in range(0, len(points), 100):
            client.upsert("assertions", points[i : i + 100], wait=True)

    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps({"graph_hash": graph_hash, "updated_at": now}), encoding="utf-8"
    )
    log.info("Upserted %d wikilink assertions", len(points))
    return len(points)


def main() -> None:
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    from shared.config import get_qdrant

    client = get_qdrant()

    log.info("Loading wikilink graph...")
    graph = _load_wikilink_graph()
    log.info("Found %d notes with outgoing links", len(graph))

    graph_hash = hashlib.sha256(
        json.dumps(sorted((k, sorted(v)) for k, v in graph.items())).encode()
    ).hexdigest()[:16]

    log.info("Computing knowledge density signals...")
    signals = _compute_knowledge_signals(client, graph)

    from shared.grounding_ledger import GroundingLedger

    ledger = GroundingLedger()
    progress = ledger.progress()
    signals["grounding_deficit"] = progress.get("grounding_deficit", 1.0)

    if not args.dry_run:
        _write_density_signals(signals)
        try:
            count = _upsert_wikilink_assertions(client, graph, graph_hash)
            log.info("Done. %d assertions, signals: %s", count, signals)
        except Exception:
            log.warning("Assertion upsert failed (non-blocking)", exc_info=True)
            log.info("Done (assertions skipped). Signals: %s", signals)
    else:
        log.info("Dry run. Signals: %s", signals)


if __name__ == "__main__":
    main()
