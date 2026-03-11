"""shared.takeout — Multi-modal Google Takeout ingestion pipeline.

Parses Google Takeout ZIP exports into NormalizedRecord streams,
routes them through dual data paths (structured/unstructured),
and outputs markdown + JSONL for downstream consumption by
the RAG pipeline and profiler.
"""
