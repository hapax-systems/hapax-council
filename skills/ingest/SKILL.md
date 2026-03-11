---
name: ingest
description: Check RAG ingestion pipeline status. Use when the user asks about RAG, document ingestion, Qdrant indexing, or runs /ingest.
---

Check RAG ingestion pipeline:

1. Systemd service status: `systemctl --user status rag-ingest`
2. Recent journal logs: `journalctl --user -u rag-ingest --since '1 hour ago' --no-pager`
3. Qdrant collection stats: `curl http://localhost:6333/collections/documents`
4. Count of documents in watched directories
5. Any errors or warnings in the pipeline
