"""Regression pin: ingest chunk size must stay under the embedder's context window.

nomic-embed-cpu has a 512-token window; chunks larger than the window are silently
truncated by Ollama before embedding (the documents_v2 p@5 regression). These tests
guard against that recurring.
"""

from __future__ import annotations

from agents.ingest import (
    CFG,
    EMBED_CONTEXT_WINDOW,
    EMBEDDING_MODEL,
    embed_context_window,
    safe_chunk_max_tokens,
)


class TestEmbedContextWindow:
    def test_nomic_cpu_window_is_512(self):
        assert embed_context_window("nomic-embed-cpu") == 512

    def test_unknown_model_uses_conservative_512_fallback(self):
        assert embed_context_window("some-unrecognized-model") == 512


class TestSafeChunkMaxTokens:
    def test_nomic_cpu_chunk_under_window_with_headroom(self):
        model = "nomic-embed-cpu"
        chunk = safe_chunk_max_tokens(model)
        assert chunk <= embed_context_window(model)
        assert chunk < 512  # strictly under, headroom for prefix + tokenizer drift

    def test_larger_window_allows_bigger_but_capped(self):
        # nomic-embed-text has a 2048 window; we still cap at the requested 1024.
        assert safe_chunk_max_tokens("nomic-embed-text") == 1024


class TestDefaultConfig:
    def test_default_chunk_max_tokens_under_configured_window(self):
        window = embed_context_window(EMBEDDING_MODEL)
        assert CFG.chunk_max_tokens <= window, (
            f"chunk_max_tokens={CFG.chunk_max_tokens} exceeds {EMBEDDING_MODEL} "
            f"window {window} — chunks would be silently truncated before embedding"
        )

    def test_plain_text_char_bound_stays_under_window(self):
        # plain_text path uses chunk_max_tokens*3 chars; at >=3 chars/token (dense
        # code lower bound) that upper-bounds tokens at chunk_max_tokens <= window.
        approx_tokens_upper_bound = (CFG.chunk_max_tokens * 3) / 3
        assert approx_tokens_upper_bound <= embed_context_window(EMBEDDING_MODEL)

    def test_window_map_has_both_nomic_variants(self):
        assert "nomic-embed-cpu" in EMBED_CONTEXT_WINDOW
        assert "nomic-embed-text" in EMBED_CONTEXT_WINDOW
