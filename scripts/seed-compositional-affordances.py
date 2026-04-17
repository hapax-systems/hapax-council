"""Seed the compositional capability catalog into Qdrant `affordances`.

Idempotent: if the catalog names already exist in Qdrant (by deterministic
id derived from the capability name), upserts overwrite in place without
duplicating embeddings.

Run via uv after adding/changing entries in
``shared/compositional_affordances.py``:

    uv run scripts/seed-compositional-affordances.py

Prereq: the council stack must be up (Qdrant on :6333 via docker compose,
Ollama on :11434 for the embedding model).

Phase 3b of the volitional-grounded-director epic (PR #1017, spec §5).
"""

from __future__ import annotations

import logging
import sys

log = logging.getLogger("seed-compositional")


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    try:
        from shared.compositional_affordances import COMPOSITIONAL_CAPABILITIES
    except Exception:
        log.exception("failed to import compositional catalog")
        return 1

    try:
        # Prefer the daimonion pipeline — it's the canonical indexer. This
        # is a compile-time import; at runtime we construct a pipeline
        # instance just for indexing (no daemon state).
        from agents._affordance_pipeline import AffordancePipeline
    except Exception:
        log.exception("AffordancePipeline not importable")
        return 1

    pipeline = AffordancePipeline()
    log.info(
        "indexing %d compositional capabilities into Qdrant affordances…",
        len(COMPOSITIONAL_CAPABILITIES),
    )
    try:
        indexed = pipeline.index_capabilities_batch(COMPOSITIONAL_CAPABILITIES)
    except Exception:
        log.exception("index_capabilities_batch failed")
        return 1

    log.info("indexed: %s", indexed if isinstance(indexed, int) else "done")
    log.info("catalog seeded. Director-side impingement wiring lands in Phase 3c.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
