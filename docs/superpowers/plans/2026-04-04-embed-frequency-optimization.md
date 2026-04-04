# Embed Frequency Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce Ollama nomic-embed-cpu CPU usage from ~380% to ~150-200% by batching startup capability indexing, caching embeddings to disk, and fixing the impingement embed cache key.

**Architecture:** Three changes to the affordance pipeline: (1) new `index_capabilities_batch()` method that calls `embed_batch()` once instead of N individual `embed()` calls, backed by (2) a disk-persisted embedding cache that eliminates re-embedding static capability descriptions across restarts, and (3) a cache key fix that deduplicates impingement embeddings by rendered text instead of raw sensor values.

**Tech Stack:** Python, Ollama API (nomic-embed-cpu), Qdrant, pydantic, pytest

**Spec:** `docs/superpowers/specs/2026-04-04-embed-frequency-optimization-design.md`

---

### Task 1: Create Disk Embedding Cache

**Files:**
- Create: `shared/embed_cache.py`
- Create: `tests/test_embed_cache.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_embed_cache.py
"""Tests for DiskEmbeddingCache."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.embed_cache import DiskEmbeddingCache


class TestDiskEmbeddingCache:
    def test_cache_miss_returns_none(self, tmp_path: Path):
        cache = DiskEmbeddingCache(cache_path=tmp_path / "cache.json", model="test", dimension=4)
        assert cache.get("hello world") is None

    def test_put_and_get_roundtrip(self, tmp_path: Path):
        cache = DiskEmbeddingCache(cache_path=tmp_path / "cache.json", model="test", dimension=4)
        vec = [0.1, 0.2, 0.3, 0.4]
        cache.put("hello world", vec)
        assert cache.get("hello world") == vec

    def test_save_and_load_persistence(self, tmp_path: Path):
        path = tmp_path / "cache.json"
        cache1 = DiskEmbeddingCache(cache_path=path, model="test", dimension=4)
        cache1.put("hello", [1.0, 2.0, 3.0, 4.0])
        cache1.save()

        cache2 = DiskEmbeddingCache(cache_path=path, model="test", dimension=4)
        assert cache2.get("hello") == [1.0, 2.0, 3.0, 4.0]

    def test_model_change_invalidates_cache(self, tmp_path: Path):
        path = tmp_path / "cache.json"
        cache1 = DiskEmbeddingCache(cache_path=path, model="model-a", dimension=4)
        cache1.put("hello", [1.0, 2.0, 3.0, 4.0])
        cache1.save()

        cache2 = DiskEmbeddingCache(cache_path=path, model="model-b", dimension=4)
        assert cache2.get("hello") is None

    def test_dimension_change_invalidates_cache(self, tmp_path: Path):
        path = tmp_path / "cache.json"
        cache1 = DiskEmbeddingCache(cache_path=path, model="test", dimension=4)
        cache1.put("hello", [1.0, 2.0, 3.0, 4.0])
        cache1.save()

        cache2 = DiskEmbeddingCache(cache_path=path, model="test", dimension=768)
        assert cache2.get("hello") is None

    def test_missing_file_starts_empty(self, tmp_path: Path):
        cache = DiskEmbeddingCache(
            cache_path=tmp_path / "nonexistent.json", model="test", dimension=4
        )
        assert cache.get("anything") is None

    def test_corrupt_file_starts_empty(self, tmp_path: Path):
        path = tmp_path / "cache.json"
        path.write_text("not valid json")
        cache = DiskEmbeddingCache(cache_path=path, model="test", dimension=4)
        assert cache.get("anything") is None

    def test_bulk_lookup_splits_hits_and_misses(self, tmp_path: Path):
        cache = DiskEmbeddingCache(cache_path=tmp_path / "cache.json", model="test", dimension=4)
        cache.put("a", [1.0, 2.0, 3.0, 4.0])
        cache.put("b", [5.0, 6.0, 7.0, 8.0])

        texts = ["a", "b", "c"]
        hits, miss_indices, miss_texts = cache.bulk_lookup(texts)
        assert hits == {0: [1.0, 2.0, 3.0, 4.0], 1: [5.0, 6.0, 7.0, 8.0]}
        assert miss_indices == [2]
        assert miss_texts == ["c"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_embed_cache.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'shared.embed_cache'`

- [ ] **Step 3: Implement DiskEmbeddingCache**

```python
# shared/embed_cache.py
"""Persistent embedding cache — avoids re-embedding static text across restarts.

Stores text->embedding mappings keyed by SHA-256 of the input text.
Invalidated when model name or dimension changes. File format is JSON
for debuggability (embeddings are 768-dim floats, ~6KB per entry,
~1MB for 150 capabilities).
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_DEFAULT_PATH = Path.home() / ".cache" / "hapax" / "embed-cache.json"


class DiskEmbeddingCache:
    """Persistent cache mapping text -> embedding vector."""

    def __init__(
        self,
        *,
        cache_path: Path = _DEFAULT_PATH,
        model: str,
        dimension: int,
    ) -> None:
        self._path = cache_path
        self._model = model
        self._dimension = dimension
        self._entries: dict[str, list[float]] = {}
        self._load()

    @staticmethod
    def _key(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    def get(self, text: str) -> list[float] | None:
        return self._entries.get(self._key(text))

    def put(self, text: str, embedding: list[float]) -> None:
        self._entries[self._key(text)] = embedding

    def bulk_lookup(
        self, texts: list[str]
    ) -> tuple[dict[int, list[float]], list[int], list[str]]:
        """Check cache for multiple texts at once.

        Returns:
            hits: {index: embedding} for texts found in cache
            miss_indices: indices of texts not in cache
            miss_texts: the texts not in cache
        """
        hits: dict[int, list[float]] = {}
        miss_indices: list[int] = []
        miss_texts: list[str] = []
        for i, text in enumerate(texts):
            vec = self.get(text)
            if vec is not None:
                hits[i] = vec
            else:
                miss_indices.append(i)
                miss_texts.append(text)
        return hits, miss_indices, miss_texts

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {
            "model": self._model,
            "dimension": self._dimension,
            "entries": self._entries,
        }
        self._path.write_text(json.dumps(data), encoding="utf-8")

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            log.warning("Corrupt embed cache at %s, starting fresh", self._path)
            return
        if data.get("model") != self._model or data.get("dimension") != self._dimension:
            log.info(
                "Embed cache invalidated (model/dim changed: %s/%s -> %s/%s)",
                data.get("model"),
                data.get("dimension"),
                self._model,
                self._dimension,
            )
            return
        self._entries = data.get("entries", {})
        log.info("Loaded %d cached embeddings from %s", len(self._entries), self._path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_embed_cache.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add shared/embed_cache.py tests/test_embed_cache.py
git commit -m "feat: add DiskEmbeddingCache for persistent capability embeddings"
```

---

### Task 2: Add `index_capabilities_batch()` to AffordancePipeline

**Files:**
- Modify: `shared/affordance_pipeline.py`
- Modify: `tests/test_affordance_pipeline.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_affordance_pipeline.py`:

```python
class TestBatchIndexing:
    def test_batch_indexes_all_capabilities(self):
        from unittest.mock import MagicMock, patch

        from shared.affordance import CapabilityRecord, OperationalProperties
        from shared.affordance_pipeline import AffordancePipeline

        records = [
            CapabilityRecord(
                name=f"cap_{i}",
                description=f"Capability {i} description",
                daemon="test",
                operational=OperationalProperties(),
            )
            for i in range(5)
        ]

        fake_embeddings = [[float(i)] * 768 for i in range(5)]

        with (
            patch("shared.affordance_pipeline.embed_batch_safe", return_value=fake_embeddings),
            patch("shared.affordance_pipeline.get_qdrant") as mock_qdrant,
        ):
            mock_client = MagicMock()
            mock_client.collection_exists.return_value = True
            mock_qdrant.return_value = mock_client

            pipeline = AffordancePipeline()
            count = pipeline.index_capabilities_batch(records)

        assert count == 5
        mock_client.upsert.assert_called_once()
        points = mock_client.upsert.call_args.kwargs["points"]
        assert len(points) == 5

    def test_batch_uses_disk_cache(self, tmp_path):
        from unittest.mock import MagicMock, patch

        from shared.affordance import CapabilityRecord, OperationalProperties
        from shared.affordance_pipeline import AffordancePipeline
        from shared.embed_cache import DiskEmbeddingCache

        records = [
            CapabilityRecord(
                name="cached_cap",
                description="Already cached description",
                daemon="test",
                operational=OperationalProperties(),
            ),
            CapabilityRecord(
                name="new_cap",
                description="Brand new description",
                daemon="test",
                operational=OperationalProperties(),
            ),
        ]

        # Pre-populate cache with one entry
        cache = DiskEmbeddingCache(
            cache_path=tmp_path / "cache.json", model="nomic-embed-cpu", dimension=768
        )
        cache.put("search_document: Already cached description", [0.5] * 768)
        cache.save()

        with (
            patch(
                "shared.affordance_pipeline.embed_batch_safe",
                return_value=[[0.9] * 768],
            ) as mock_embed,
            patch("shared.affordance_pipeline.get_qdrant") as mock_qdrant,
            patch(
                "shared.affordance_pipeline._DISK_CACHE_PATH",
                tmp_path / "cache.json",
            ),
        ):
            mock_client = MagicMock()
            mock_client.collection_exists.return_value = True
            mock_qdrant.return_value = mock_client

            pipeline = AffordancePipeline()
            count = pipeline.index_capabilities_batch(records)

        assert count == 2
        # Only the uncached description should have been embedded
        mock_embed.assert_called_once()
        embedded_texts = mock_embed.call_args.args[0]
        assert len(embedded_texts) == 1
        assert "Brand new" in embedded_texts[0]

    def test_batch_empty_list_returns_zero(self):
        from shared.affordance_pipeline import AffordancePipeline

        pipeline = AffordancePipeline()
        assert pipeline.index_capabilities_batch([]) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_affordance_pipeline.py::TestBatchIndexing -v`
Expected: FAIL — `AffordancePipeline has no attribute 'index_capabilities_batch'`

- [ ] **Step 3: Implement `index_capabilities_batch()`**

In `shared/affordance_pipeline.py`:

Add imports near top of file (after existing imports):

```python
from shared.embed_cache import DiskEmbeddingCache

_DISK_CACHE_PATH = Path.home() / ".cache" / "hapax" / "embed-cache.json"
```

Add top-level helper function (before the `AffordancePipeline` class):

```python
def embed_batch_safe(
    texts: list[str], prefix: str = "search_document"
) -> list[list[float]] | None:
    """Batch embed with graceful degradation."""
    try:
        from shared.config import embed_batch

        return embed_batch(texts, prefix=prefix)
    except RuntimeError:
        log.warning("embed_batch_safe: Ollama unavailable")
        return None
```

Add method to `AffordancePipeline` class, after `index_capability()` (after line 157):

```python
    def index_capabilities_batch(self, records: list[CapabilityRecord]) -> int:
        """Index multiple capabilities in a single embed + upsert operation.

        Uses disk cache to avoid re-embedding static descriptions across restarts.
        Calls embed_batch() once for cache misses. Upserts all points in one Qdrant call.
        """
        if not records:
            return 0

        from shared.config import EMBEDDING_MODEL, EXPECTED_EMBED_DIMENSIONS, get_qdrant

        prefix = "search_document"
        prefixed_texts = [f"{prefix}: {r.description}" for r in records]

        disk_cache = DiskEmbeddingCache(
            cache_path=_DISK_CACHE_PATH,
            model=EMBEDDING_MODEL,
            dimension=EXPECTED_EMBED_DIMENSIONS,
        )
        hits, miss_indices, miss_texts = disk_cache.bulk_lookup(prefixed_texts)

        if miss_texts:
            fresh = embed_batch_safe(miss_texts, prefix=prefix)
            if fresh is None:
                log.warning("Batch embed failed, falling back to individual indexing")
                return sum(1 for r in records if self.index_capability(r))
            for idx, vec in zip(miss_indices, fresh):
                hits[idx] = vec
                disk_cache.put(prefixed_texts[idx], vec)
            disk_cache.save()

        from qdrant_client.models import PointStruct

        points: list[PointStruct] = []
        for i, record in enumerate(records):
            embedding = hits.get(i)
            if embedding is None:
                continue
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, record.name))
            points.append(
                PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload={
                        "capability_name": record.name,
                        "description": record.description,
                        "daemon": record.daemon,
                        "requires_gpu": record.operational.requires_gpu,
                        "latency_class": record.operational.latency_class,
                        "consent_required": record.operational.consent_required,
                        "priority_floor": record.operational.priority_floor,
                        "medium": record.operational.medium,
                        "activation_summary": self._activation.get(
                            record.name, ActivationState()
                        ).to_summary(),
                        "available": True,
                    },
                )
            )

        if not points:
            return 0

        try:
            client = get_qdrant()
            self._ensure_collection(client, len(points[0].vector))
            client.upsert(collection_name=COLLECTION_NAME, points=points)
            self._index_breaker.record_success()
        except Exception:
            self._index_breaker.record_failure()
            log.warning("Batch Qdrant upsert failed", exc_info=True)
            return 0

        for record in records:
            if record.name not in self._activation:
                self._activation[record.name] = ActivationState()

        log.info(
            "Batch-indexed %d capabilities (%d cached, %d freshly embedded)",
            len(points),
            len(records) - len(miss_texts),
            len(miss_texts),
        )
        return len(points)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_affordance_pipeline.py::TestBatchIndexing -v`
Expected: 3 passed

- [ ] **Step 5: Run full pipeline test suite**

Run: `uv run pytest tests/test_affordance_pipeline.py -v`
Expected: All existing tests still pass

- [ ] **Step 6: Commit**

```bash
git add shared/affordance_pipeline.py tests/test_affordance_pipeline.py
git commit -m "feat: add index_capabilities_batch() with disk cache"
```

---

### Task 3: Fix Impingement Embed Cache Key

**Files:**
- Modify: `shared/affordance_pipeline.py`
- Modify: `tests/test_affordance_pipeline.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_affordance_pipeline.py`:

```python
class TestEmbeddingCacheTextKey:
    def test_same_text_hits_cache(self):
        from shared.affordance_pipeline import EmbeddingCache

        cache = EmbeddingCache()
        vec = [0.1, 0.2, 0.3]
        cache.put_by_text("source: dmn intent: stable", vec)
        assert cache.get_by_text("source: dmn intent: stable") == vec

    def test_different_text_misses_cache(self):
        from shared.affordance_pipeline import EmbeddingCache

        cache = EmbeddingCache()
        cache.put_by_text("source: dmn intent: stable", [0.1, 0.2, 0.3])
        assert cache.get_by_text("source: dmn intent: degrading") is None

    def test_lru_eviction_by_text(self):
        from shared.affordance_pipeline import EmbeddingCache

        cache = EmbeddingCache(max_size=2)
        cache.put_by_text("a", [1.0])
        cache.put_by_text("b", [2.0])
        cache.put_by_text("c", [3.0])  # evicts "a"
        assert cache.get_by_text("a") is None
        assert cache.get_by_text("b") == [2.0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_affordance_pipeline.py::TestEmbeddingCacheTextKey -v`
Expected: FAIL — `EmbeddingCache has no attribute 'put_by_text'`

- [ ] **Step 3: Add text-keyed methods to EmbeddingCache**

In `shared/affordance_pipeline.py`, add to the `EmbeddingCache` class (after the existing `put` method):

```python
    def _text_key(self, text: str) -> str:
        return hashlib.md5(text.encode(), usedforsecurity=False).hexdigest()

    def get_by_text(self, text: str) -> list[float] | None:
        key = self._text_key(text)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def put_by_text(self, text: str, embedding: list[float]) -> None:
        key = self._text_key(text)
        self._cache[key] = embedding
        self._cache.move_to_end(key)
        while len(self._cache) > self._max_size:
            self._cache.popitem(last=False)
```

- [ ] **Step 4: Update `_get_embedding()` to use text-keyed cache**

In `shared/affordance_pipeline.py`, replace the `_get_embedding()` method:

```python
    def _get_embedding(self, impingement: Impingement) -> list[float] | None:
        if impingement.embedding is not None:
            return impingement.embedding
        text = render_impingement_text(impingement)
        cached = self._embed_cache.get_by_text(text)
        if cached is not None:
            return cached
        from shared.config import embed_safe

        embedding = embed_safe(text, prefix="search_query")
        if embedding is not None:
            self._embed_cache.put_by_text(text, embedding)
        return embedding
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_affordance_pipeline.py -v`
Expected: All tests pass (new + existing)

- [ ] **Step 6: Commit**

```bash
git add shared/affordance_pipeline.py tests/test_affordance_pipeline.py
git commit -m "fix: cache impingement embeddings by rendered text, not raw sensor values"
```

---

### Task 4: Convert Daimonion Startup to Batch Indexing

**Files:**
- Modify: `agents/hapax_daimonion/init_pipeline.py`
- Modify: `agents/hapax_daimonion/tool_recruitment.py`

- [ ] **Step 1: Rewrite init_pipeline.py to collect records and batch-index**

Replace the body of `precompute_pipeline_deps()` from `# Affordance pipeline` (line 110) through end of function. Keep everything before line 110 unchanged. New code:

```python
    # Affordance pipeline
    from agents._affordance import CapabilityRecord, OperationalProperties
    from agents._affordance_pipeline import AffordancePipeline

    daemon._affordance_pipeline = AffordancePipeline()

    # Collect ALL capability records for batch indexing
    _all_records: list[CapabilityRecord] = []

    # Speech production
    _all_records.append(
        CapabilityRecord(
            name="speech_production",
            description=SPEECH_DESCRIPTION,
            daemon="hapax_daimonion",
            operational=OperationalProperties(requires_gpu=True, medium="auditory"),
        )
    )

    # Vocal chain: MIDI affordances for speech modulation
    from agents.hapax_daimonion.midi_output import MidiOutput
    from agents.hapax_daimonion.vocal_chain import VOCAL_CHAIN_RECORDS, VocalChainCapability

    daemon._midi_output = MidiOutput(port_name=daemon.cfg.midi_output_port)
    daemon._vocal_chain = VocalChainCapability(
        midi_output=daemon._midi_output,
        evil_pet_channel=daemon.cfg.midi_evil_pet_channel,
        s4_channel=daemon.cfg.midi_s4_channel,
    )
    _all_records.extend(VOCAL_CHAIN_RECORDS)

    # System awareness
    from agents.hapax_daimonion.system_awareness import (
        SYSTEM_AWARENESS_DESCRIPTION,
        SystemAwarenessCapability,
    )

    daemon._system_awareness = SystemAwarenessCapability()
    _all_records.append(
        CapabilityRecord(
            name="system_awareness",
            description=SYSTEM_AWARENESS_DESCRIPTION,
            daemon="hapax_daimonion",
        )
    )

    # Cross-modal expression coordinator
    from agents._expression import ExpressionCoordinator

    daemon._expression_coordinator = ExpressionCoordinator()

    # Novel capability discovery
    from agents.hapax_daimonion.discovery_affordance import (
        DISCOVERY_AFFORDANCE,
        CapabilityDiscoveryHandler,
    )

    _all_records.append(
        CapabilityRecord(
            name=DISCOVERY_AFFORDANCE[0],
            description=DISCOVERY_AFFORDANCE[1],
            daemon="hapax_daimonion",
            operational=OperationalProperties(
                latency_class="slow",
                requires_network=True,
                consent_required=True,
            ),
        )
    )
    daemon._discovery_handler = CapabilityDiscoveryHandler()

    # Tool recruitment: collect tool affordances
    from agents.hapax_daimonion.tool_affordances import TOOL_AFFORDANCES
    from agents.hapax_daimonion.tool_recruitment import ToolRecruitmentGate

    for name, desc in TOOL_AFFORDANCES:
        medium = "visual" if name in ToolRecruitmentGate._VISUAL_TOOLS else "textual"
        _all_records.append(
            CapabilityRecord(
                name=name,
                description=desc,
                daemon="hapax_daimonion",
                operational=OperationalProperties(latency_class="fast", medium=medium),
            )
        )
    tool_names = {name for name, _ in TOOL_AFFORDANCES}
    daemon._tool_recruitment_gate = ToolRecruitmentGate(daemon._affordance_pipeline, tool_names)

    # World affordances from shared registry
    from shared.affordance_registry import ALL_AFFORDANCES

    _all_records.extend(ALL_AFFORDANCES)

    # Batch-index everything in one Ollama + Qdrant call
    _indexed = daemon._affordance_pipeline.index_capabilities_batch(_all_records)

    # Register interrupt handlers (no embedding needed)
    daemon._affordance_pipeline.register_interrupt(
        "population_critical", "speech_production", "hapax_daimonion"
    )
    daemon._affordance_pipeline.register_interrupt(
        "operator_distress", "speech_production", "hapax_daimonion"
    )
    daemon._affordance_pipeline.register_interrupt(
        "system_critical", "system_awareness", "hapax_daimonion"
    )

    log.info(
        "Pipeline dependencies precomputed (batch-indexed %d capabilities)", _indexed
    )
```

- [ ] **Step 2: Update tool_recruitment.py register_tools to use batch**

In `agents/hapax_daimonion/tool_recruitment.py`, replace the `register_tools` static method:

```python
    @staticmethod
    def register_tools(pipeline, affordances: list[tuple[str, str]]) -> int:
        """Register all tool affordances into the pipeline's vector index.

        Returns the number of tools successfully indexed.
        """
        records = []
        for name, desc in affordances:
            medium = "visual" if name in ToolRecruitmentGate._VISUAL_TOOLS else "textual"
            records.append(
                CapabilityRecord(
                    name=name,
                    description=desc,
                    daemon="hapax_daimonion",
                    operational=OperationalProperties(latency_class="fast", medium=medium),
                )
            )
        registered = pipeline.index_capabilities_batch(records)
        log.info("Registered %d/%d tool affordances", registered, len(affordances))
        return registered
```

- [ ] **Step 3: Run existing tests**

Run: `uv run pytest tests/ -k "pipeline or tool_recruitment" -v --timeout=30`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add agents/hapax_daimonion/init_pipeline.py agents/hapax_daimonion/tool_recruitment.py
git commit -m "feat: daimonion startup uses batch capability indexing (142->1 Ollama call)"
```

---

### Task 5: Convert Reverie and Logos Engine to Batch Indexing

**Files:**
- Modify: `agents/reverie/_affordances.py`
- Modify: `logos/engine/__init__.py`

- [ ] **Step 1: Update reverie to use batch indexing**

Replace `build_reverie_pipeline()` in `agents/reverie/_affordances.py`:

```python
def build_reverie_pipeline():
    """Build the affordance pipeline with all system affordances registered in Qdrant."""
    from agents._affordance_pipeline import AffordancePipeline

    p = AffordancePipeline()
    records = build_reverie_pipeline_affordances()
    registered = p.index_capabilities_batch(records)
    log.info("Registered %d/%d affordances in Reverie pipeline", registered, len(records))
    return p
```

- [ ] **Step 2: Update logos engine to batch-index rules on first cascade**

In `logos/engine/__init__.py`, replace the rule indexing block (lines 466-479):

```python
                if not self._cascade_initialized:
                    rule_records = [
                        self._rule_capability_record_class(
                            name=rule.name,
                            description=self._generate_rule_description(rule),
                            daemon="logos_engine",
                        )
                        for rule in self._registry
                    ]
                    self._affordance_pipeline.index_capabilities_batch(rule_records)
                    self._cascade_initialized = True
                    _log.info(
                        "Affordance pipeline: %d rule capabilities indexed", len(self._registry)
                    )
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/ -k "reverie or engine" -v --timeout=30`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add agents/reverie/_affordances.py logos/engine/__init__.py
git commit -m "feat: reverie and logos engine use batch capability indexing"
```

---

### Task 6: Integration Verification

**Files:**
- No code changes — verification only

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest tests/ -q --timeout=60`
Expected: All pass, no regressions

- [ ] **Step 2: Run ruff**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: Clean

- [ ] **Step 3: Verify daimonion startup batch behavior**

```bash
systemctl --user restart hapax-daimonion
sleep 15
journalctl --user -u hapax-daimonion --since "15 sec ago" --no-pager | grep -i "batch-indexed\|cached\|embed"
```

Expected: Log line like `Batch-indexed 142 capabilities (0 cached, 142 freshly embedded)` on first run, then `(142 cached, 0 freshly embedded)` on subsequent restarts.

- [ ] **Step 4: Verify CPU impact**

```bash
sleep 30
journalctl -u ollama --since "30 sec ago" --no-pager | grep -c "POST.*embed"
uptime
```

Expected: Embed call count significantly reduced from pre-optimization baseline of ~100/30s. Load average lower.

- [ ] **Step 5: Commit any fixups**

```bash
git add -A
git commit -m "chore: integration verification lint fixes"
```
