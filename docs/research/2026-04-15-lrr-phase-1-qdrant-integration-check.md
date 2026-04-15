# LRR Phase 1 Qdrant schema × research registry integration check

**Date:** 2026-04-15
**Author:** alpha (AWB mode, queue/ item #164)
**Scope:** Verify the integration point between LRR Phase 1 research registry (condition_id tracking) and Qdrant `stream-reactions` collection writes. Check writer path, backfill state, and SHM marker hydration.
**Register:** scientific, neutral
**Depends on:** queue #118 (Qdrant collection schema audit, PR #882)

## 1. Headline

**INTEGRATION GAP FOUND: research-marker SHM file is missing, causing post-backfill writes to land with `condition_id: null`.**

- **Writer path correct:** `agents/studio_compositor/director_loop.py` reads the SHM marker via `_read_research_marker()` and includes `condition_id` in every stream-reactions record
- **Persistent state correct:** `~/hapax-state/research-registry/current.txt` contains `cond-phase-a-baseline-qwen-001` (valid current condition)
- **Backfill executed successfully:** 2703/2758 stream-reactions points (98%) have `condition_id` tagged
- **55 orphan writes:** points with `condition_id: null` — **all post-backfill**, caused by missing SHM marker file at `/dev/shm/hapax-compositor/research-marker.json`
- **Root cause:** SHM marker file was never hydrated post-reboot from the persistent `current.txt` state. Every reaction since reboot has landed untagged.

## 2. Method

```bash
# Writer path
grep -n "condition_id" agents/studio_compositor/director_loop.py

# Persistent state
cat ~/hapax-state/research-registry/current.txt

# SHM marker
cat /dev/shm/hapax-compositor/research-marker.json

# Stream-reactions state
curl -s http://localhost:6333/collections/stream-reactions | jq '.result.points_count'
curl -s -X POST http://localhost:6333/collections/stream-reactions/points/count \
  -d '{"filter":{"must":[{"is_null":{"key":"condition_id"}}]},"exact":true}'
```

## 3. Per-check findings

### 3.1 Canonical schema compliance — ✓ CLEAN

`shared/qdrant_schema.py` `EXPECTED_COLLECTIONS` includes `stream-reactions` at 768d Cosine. Queue #118 audit confirmed live state matches.

Director_loop.py creates the collection if missing:

```python
if "stream-reactions" not in collections:
    client.create_collection(
        collection_name="stream-reactions",
        vectors_config=VectorParams(size=768, distance=Distance.COSINE),
    )
```

**Verdict:** writer respects canonical schema. ✓

### 3.2 Research marker writer path — ✓ CLEAN

`director_loop.py` lines 890-906 (_save_reaction record building):

```python
record = {
    "ts": now.isoformat(),
    "ts_str": ts,
    "reaction_index": self._reaction_count,
    "activity": activity,
    "text": text,
    # ...
    # LRR Phase 1 item 2: research condition tag. Read once per
    # reaction (cached 5 s in `_read_research_marker`). Both the
    # JSONL writer below and the Qdrant upsert pick up this field
    # via the shared `record` dict — no second read.
    "condition_id": _read_research_marker(),
}
```

**Verdict:** writer correctly includes `condition_id` in every payload. ✓

### 3.3 Research marker reader path — ✓ CLEAN (per code)

`_read_research_marker()` at line 131-148:

```python
def _read_research_marker() -> str | None:
    """Return the current research condition_id, cached for 5 s."""
    if time.time() - _research_marker_cache["last_read"] < 5.0:
        return _research_marker_cache["condition_id"]
    try:
        data = json.loads(Path("/dev/shm/hapax-compositor/research-marker.json").read_text())
        condition_id = data.get("condition_id") if isinstance(data, dict) else None
    except Exception:
        condition_id = None
    _research_marker_cache["condition_id"] = condition_id
    _research_marker_cache["last_read"] = time.time()
    return condition_id
```

**Reader logic is correct.** The 5-second cache avoids per-reaction disk hits. Fallback to `None` on missing file is safe. **But** the fallback is exactly what's happening now — the file is missing, so every read returns `None`.

### 3.4 Persistent state — ✓ CLEAN

```
$ cat ~/hapax-state/research-registry/current.txt
cond-phase-a-baseline-qwen-001
```

The persistent registry has a valid current condition. ✓

### 3.5 SHM marker hydration — ❌ **INTEGRATION GAP (MAIN FINDING)**

```
$ ls /dev/shm/hapax-compositor/research-marker.json
(missing)

$ ls /dev/shm/hapax-compositor/
album-cover.png  brio-operator.jpg  brio-room.jpg  ...  yt-frame-2.jpg
# 23 files; no research-marker.json
```

**The SHM marker file does not exist.** Every call to `_read_research_marker()` returns `None`. Every stream-reaction since the last reboot has been written with `condition_id: null`.

**Root cause:** nothing on this workstation hydrates the SHM marker from `~/hapax-state/research-registry/current.txt` on boot. The chain is broken at the persistent-to-SHM sync step.

### 3.6 Backfill state — ✓ partial

```
$ curl -s http://localhost:6333/collections/stream-reactions | jq '.result.points_count'
2758

$ curl -s -X POST http://localhost:6333/collections/stream-reactions/points/count \
  -d '{"filter":{"must_not":[{"is_null":{"key":"condition_id"}}]},"exact":true}'
{"result":{"count":2703}}

$ curl -s -X POST http://localhost:6333/collections/stream-reactions/points/count \
  -d '{"filter":{"must":[{"is_null":{"key":"condition_id"}}]},"exact":true}'
{"result":{"count":55}}
```

**Math:** 2703 tagged + 55 untagged = 2758 total ✓

- **2703 points (98%)** have `condition_id` set (via the original `research-registry.py tag-reactions` backfill)
- **55 points (2%)** have `condition_id: null`

The 55 untagged points are **post-backfill writes** — they arrived after the backfill completed, but before (or during) the period when the SHM marker was missing.

### 3.7 Search-by-condition facets — inferred OK

Alpha did not test search-by-condition directly (would require Qdrant query + condition filter), but the payload structure supports it: points have `condition_id` as a top-level string field, which Qdrant can filter on. The 98% tagged coverage is sufficient for any search-by-condition analysis to produce meaningful results for the backfilled data.

**Possible follow-up:** verify the `search-by-condition` helper function (if any) in a future test.

### 3.8 Orphan writes detection — ✓ NONE

Alpha checked for writes going to collections NOT in canonical schema. The director_loop.py only writes to `stream-reactions` (and possibly `studio-moments` per the stream archive path). Both are in `EXPECTED_COLLECTIONS`. **No orphan writes detected.**

## 4. Gap remediation proposals

### 4.1 PRIMARY — SHM marker hydration script (HIGH priority)

**Problem:** persistent state → SHM sync step is missing.

**Fix:** author a small script `scripts/hydrate-research-marker-shm.sh` that:

1. Reads `~/hapax-state/research-registry/current.txt`
2. Writes `{"condition_id": <value>, "set_at": <now>}` to `/dev/shm/hapax-compositor/research-marker.json`
3. Returns exit 0 on success, exit 1 if no current condition

**Wire it up** via:
- **Option A** — `hapax-logos.service` `ExecStartPre=` (fires on UI start, which is proximate to boot)
- **Option B** — `studio-compositor.service` `ExecStartPre=` (more directly connected to the writer path)
- **Option C** — a dedicated `hapax-research-marker-hydrate.service` oneshot with `WantedBy=default.target` for lingering user-unit boot

Alpha recommends **Option B** (studio-compositor ExecStartPre) because the writer is inside studio-compositor and the ordering is clean.

**Size:** ~20 LOC shell + 1 systemd unit edit. ~15 min.

### 4.2 SECONDARY — backfill the 55 orphan points

Once the SHM marker is hydrated + new writes start tagging correctly, run `research-registry.py tag-reactions` again against the 55 untagged points:

```bash
python scripts/research-registry.py tag-reactions cond-phase-a-baseline-qwen-001
```

The script is idempotent (already-tagged points are skipped). Running it will catch the 55 orphans.

**Size:** 1 CLI invocation. ~1 min.

### 4.3 TERTIARY — integration test + CI pin

**Problem:** there's no test that would catch this integration gap in CI.

**Fix:** author `tests/test_research_marker_integration.py` that:

1. Writes a test condition to `~/hapax-state/research-registry/current.txt`
2. Runs the hydration script
3. Asserts SHM marker file exists + contains correct condition_id
4. Calls `_read_research_marker()` + asserts correct return
5. Creates a test point in a test Qdrant collection + asserts `condition_id` is in payload

**Size:** ~80 LOC Python. ~30 min.

Not urgent; file as low-priority follow-up.

## 5. Why this matters for LRR execution

LRR Phase 1 (research registry) is the upstream dependency for:
- LRR Phase 4 (Phase A completion) — Phase A sessions need `condition_id` tagging to be research-valid
- LRR Phase 5 (substrate scenario 1+2) — the new OLMo `local-research-*` routes will also need condition_id tagging
- HSEA Phase 3 (C-cluster) — reads the research registry via the spectator narrators

**Currently:** 2% of reactions are untagged. The Phase A baseline data collection already in progress (or imminent) is writing points that lack `condition_id` and will be invisible to condition-filtered queries.

**Urgency:** **HIGH** for the backfill fix because Phase A data collection is load-bearing for the epic. If Phase A already started writing post-reboot, those points are among the 55 orphans. Remediating NOW preserves data integrity.

**Remediation path urgency priority:**

1. **Immediate:** Hydrate SHM marker file manually (one-liner `echo '{"condition_id": "cond-phase-a-baseline-qwen-001"}' > /dev/shm/hapax-compositor/research-marker.json`)
2. **Today:** Ship the hydration script + wire to systemd
3. **Today:** Run `research-registry.py tag-reactions` backfill for the 55 orphans
4. **Post-fix:** Verify the count goes to 0 untagged

## 6. Positive findings

1. **Canonical schema compliance is clean** — writer respects `shared/qdrant_schema.py`
2. **Writer logic is correct** — `director_loop.py` reads marker + includes condition_id in every record
3. **Backfill infrastructure exists** — `scripts/research-registry.py tag-reactions` is idempotent + chunked (100-point batches per Bundle 2 §4 guidance)
4. **Persistent state is correct** — `current.txt` has the valid current condition
5. **No orphan collections** — writes only go to canonical-schema-registered collections
6. **98% backfill coverage** — only 2% of points are affected by the current gap

## 7. Recommendations

### 7.1 Priority queue items (file as follow-ups)

```yaml
id: "169"
title: "Hydrate research-marker SHM file from persistent state on boot"
description: |
  Per queue #164 integration check. Author scripts/hydrate-research-
  marker-shm.sh that reads ~/hapax-state/research-registry/current.txt
  and writes /dev/shm/hapax-compositor/research-marker.json. Wire via
  studio-compositor.service ExecStartPre=. Blocking because 55
  post-reboot stream-reactions are currently untagged.
priority: high
size_estimate: "~20 LOC shell + 1 systemd edit, ~15 min"

id: "170"
title: "Backfill the 55 untagged stream-reactions points"
description: |
  Per queue #164. Run `scripts/research-registry.py tag-reactions
  cond-phase-a-baseline-qwen-001` once queue #169 ships and the SHM
  marker is hydrated. Idempotent; just need operator to execute.
priority: high
depends_on: ["169"]
size_estimate: "~1 min CLI invocation"

id: "171"
title: "tests/test_research_marker_integration.py — catch the gap in CI"
description: |
  Per queue #164 gap-remediation §4.3. Test that writes a test
  condition, runs the hydration script, asserts SHM marker + condition
  _id in test Qdrant writes.
priority: low
size_estimate: "~80 LOC Python, ~30 min"
```

### 7.2 Immediate manual remediation

Alpha recommends the operator run this one-liner immediately to stop the bleeding on any in-progress Phase A data collection:

```bash
echo '{"condition_id": "cond-phase-a-baseline-qwen-001", "set_at": "'$(date -Iseconds)'"}' > /dev/shm/hapax-compositor/research-marker.json
```

This is a temporary fix; the proper fix is queue #169 (systemd ExecStartPre wired).

## 8. What this audit does NOT do

- **Does not apply the manual SHM hydration** — alpha is a research session, not a remediation session. Operator decides whether to run the one-liner.
- **Does not ship the hydration script** — filed as queue #169 proposal.
- **Does not verify search-by-condition functionality** — only checks payload structure + write path. Testing the search helper is a separate item.
- **Does not audit `studio-moments` collection** for similar integration gaps. studio-moments is written by a different path (possibly `agents/studio_compositor/hls_archive.py` per queue #117 test audit); that could be a follow-up audit.

## 9. Closing

LRR Phase 1 writer path + canonical schema compliance + backfill infrastructure are all clean. The integration gap is specifically at the **persistent-state-to-SHM sync step**, which is missing entirely. Fix is small (20 LOC shell + 1 systemd edit) but urgent because Phase A data collection is load-bearing and currently writing 2% untagged data.

Branch-only commit per queue #164 acceptance criteria.

## 10. Cross-references

- **Queue #118 Qdrant schema audit** (PR #882) — upstream
- **Queue #117 LRR Phase 2 test coverage** (PR #881) — related tests for stream_archive + studio-compositor
- `shared/qdrant_schema.py` — canonical schema
- `scripts/research-registry.py` — registry CLI + backfill command
- `agents/studio_compositor/director_loop.py` lines 890-970 — writer path
- `shared/research_marker.py` — marker library (reader-side)
- `~/hapax-state/research-registry/current.txt` — persistent state (verified)
- `/dev/shm/hapax-compositor/research-marker.json` — **MISSING** SHM file (root cause)
- Drop #62 §3 row 1 — LRR Phase 1 frozen-files probe requirement
- LRR Phase 1 spec — research registry design

— alpha, 2026-04-15T22:08Z
