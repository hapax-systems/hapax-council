"""Tests for DiskEmbeddingCache."""

from __future__ import annotations

from pathlib import Path

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
