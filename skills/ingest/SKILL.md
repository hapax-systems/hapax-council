---
name: ingest
description: Check RAG ingestion pipeline. Auto-run when: a query returns stale or missing results, after adding documents to watched directories, when qdrant errors appear (PostToolUse suggests it), or user asks about RAG/ingestion. Invoke proactively without asking.
---

Check RAG ingestion pipeline:

```bash
systemctl --user status rag-ingest --no-pager 2>/dev/null | head -8
```

```bash
journalctl --user -u rag-ingest --since '1 hour ago' --no-pager -n 20
```

```bash
curl -s http://localhost:6333/collections/documents | jq '{status: .result.status, points_count: .result.points_count, vectors_count: .result.vectors_count}'
```

```bash
find ~/projects/hapax-council/data/documents -type f -newer ~/.cache/hapax/last-ingest 2>/dev/null | wc -l && echo "documents newer than last ingest"
```

Review the output. Flag errors, stale indices, or pipeline stalls. If rag-ingest is failed, suggest restart.
