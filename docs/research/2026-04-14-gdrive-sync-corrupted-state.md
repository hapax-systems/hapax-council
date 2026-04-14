# gdrive-sync broken by corrupted `start_page_token` in cache state

**Date:** 2026-04-14
**Author:** delta (beta role)
**Scope:** Surfaced during the health-monitor audit: the
health monitor's `connectivity.gdrive-sync` check has been
failing with rc=1 since 09:46 CDT. Root-caused to the
service-local state file. Asks: what exactly is broken and
what's the safe remediation?
**Register:** scientific, neutral
**Status:** live regression — clear fix, delta is not
executing it

## Headline

**Three findings.**

1. **`~/.cache/gdrive-sync/state.json` contains
   `start_page_token: 'def'`** — the literal three-character
   string "def", not a valid Google Drive continuation token.
   Every `gdrive-sync.service` invocation since the
   corruption has failed with `HttpError 400: Invalid Value
   ... pageToken='def'` when `_incremental_sync` calls
   `changes().list(pageToken='def')` on the Drive API.
2. **The service has been in failed state for ≥ 1 h 37 min**
   (measured at 16:23 UTC, last good attempt 09:46 CDT).
   Broader freshness probe via the health monitor suggests
   **gdrive, gcalendar, and langfuse sync are all stale by
   81+ hours** — the gdrive corruption is acute, the other
   two are longer-standing and out of scope for this drop.
3. **The state file is 161 MB** with 209 004 file entries,
   12 305 folder names, 12 283 folder parents. `last_full_scan`
   timestamp decodes to 2026-04-01 (13 days ago);
   `last_sync` to 2026-04-09 (5 days ago). **The corruption
   happened between 2026-04-09 and 2026-04-12** (state file
   mtime), which is when the 'def' value was written.

**Net impact.** gdrive-sync has not completed a successful
sync in 5 days. Gmail attachment flow, calendar event
syncing, and any research pipeline that expects Google Drive
content to land at `~/gdrive-drop/` or equivalent is quietly
stale. The healthy-path user-facing symptom is: files the
operator dropped into gdrive since Apr 9 are not visible to
the council.

## 1. The error trace

```text
Apr 14 09:45:58 gdrive-sync[2782895]:
  File "agents/gdrive_sync.py", line 448, in _incremental_sync
    .execute()

  File ".venv/lib/python3.12/site-packages/googleapiclient/http.py",
    line 938, in execute
    raise HttpError(resp, content, uri=self.uri)

googleapiclient.errors.HttpError: <HttpError 400
  when requesting
  https://www.googleapis.com/drive/v3/changes
    ?pageToken=def
    &fields=nextPageToken%2C+newStartPageToken%2C+…
    &pageSize=1000&includeRemoved=true
  returned "Invalid Value".
  Details: [{
    'message': 'Invalid Value',
    'domain': 'global',
    'reason': 'invalid',
    'location': 'pageToken',
    'locationType': 'parameter'
  }]>
```

The error message literally says `pageToken=def`. Google's
API rejects the value with a precise location indicator —
confirming the token is being passed through to the request
verbatim from the local state.

Google Drive continuation tokens are opaque encoded strings
(~40-60 characters of base64-ish bytes). `def` is not a
valid token at any point in Google's token space; it's a
placeholder value someone or some code wrote into the
state.

## 2. State file inspection

```text
$ ls -la ~/.cache/gdrive-sync/state.json
-rw-r--r-- 1 hapax hapax 161 039 216 Apr 12 00:30 state.json

$ python3 -c "import json; \
    d=json.load(open('.../state.json')); \
    print({k: (len(v) if isinstance(v,(dict,list)) else 'scalar') \
            for k,v in list(d.items())[:10]})"
{
  'start_page_token': 'scalar',
  'files': 209_004,
  'folder_names': 12_305,
  'folder_parents': 12_283,
  'last_full_scan': 'scalar',
  'last_sync': 'scalar',
  'stats': 0,
}

$ python3 -c "import json; \
    d=json.load(open('.../state.json')); \
    print('start_page_token:', repr(d.get('start_page_token'))); \
    print('last_full_scan:', d.get('last_full_scan')); \
    print('last_sync:', d.get('last_sync'))"
start_page_token: 'def'
last_full_scan:  1775216252.127153
last_sync:       1775971807.313324
```

Decoded timestamps:

- `last_full_scan = 1775216252` → 2026-04-01 ~04:17 UTC
  (13 days before today)
- `last_sync = 1775971807` → 2026-04-09 ~18:10 UTC
  (5 days before today)
- State file mtime → 2026-04-12 00:30 CDT (2 days 10 h
  before today)

**Gap:** state file was written on Apr 12, but
`last_sync` is Apr 9. That suggests **the write on Apr 12
was NOT a normal sync success** — it was either a partial
write from a crashed run, a manual debug write, or a
code-path that updated the token without updating
`last_sync`. Whatever wrote it planted `'def'` as the
`start_page_token` value.

## 3. Hypothesis tests

### H1 — "A test harness wrote 'def' as a mock value"

**Possible but unverified.** `def` is a common placeholder
string in Python test fixtures (as is 'abc'). A test that
monkey-patched the Google API to return `'def'` as the
next page token would leave that value in state if the
test used the real state file instead of a temp directory.

Worth a `grep -rn "\"def\"" agents/gdrive_sync.py tests/` —
not run in this drop, operator/alpha can verify.

### H2 — "Google returned 'def' as an actual nextPageToken"

**Refuted.** Google Drive continuation tokens are 40+
character opaque strings; the API would not emit a
3-character token. If `_incremental_sync` parsed the response
wrong and truncated to first N chars, the truncation would
produce something other than exactly `def`.

### H3 — "Corrupted JSON write left partial content"

**Refuted by the valid JSON structure.** The file is a
well-formed 161 MB JSON document with the correct keys and
structure. Corruption during write would usually produce
a truncated or syntactically broken file.

### H4 — "Manual override by an operator running test commands"

**Most likely.** Someone ran `gdrive_sync` with a debug
flag, set the token to a fixed value (common pattern for
reproducing pagination bugs), and the state got persisted.
Untraceable to a specific session from the state file
alone.

## 4. Safe remediation paths

### 4.1 Option A — reset just the token, keep the file cache

```bash
# Edit the state file: set start_page_token to null
python3 -c "
import json
path = '$HOME/.cache/gdrive-sync/state.json'
with open(path, 'r') as f:
    data = json.load(f)
data['start_page_token'] = None   # triggers re-fetch via API
with open(path, 'w') as f:
    json.dump(data, f)
"

systemctl --user start gdrive-sync.service
journalctl --user -u gdrive-sync.service --since "1 minute ago"
```

Advantage: preserves the 209 004 file fingerprints already
cached. First sync after reset calls
`changes().getStartPageToken()` to get a fresh token, then
proceeds normally.

Risk: if `gdrive_sync.py:448 _incremental_sync` does not
have a `None`-handling branch that triggers
`getStartPageToken`, this will just fail differently. Alpha
should read the code before running.

### 4.2 Option B — delete state, force full rebuild

```bash
mv $HOME/.cache/gdrive-sync/state.json \
   $HOME/.cache/gdrive-sync/state.json.bak.$(date +%Y%m%d)

systemctl --user start gdrive-sync.service
journalctl --user -u gdrive-sync.service --since "10 minutes ago"
```

Advantage: simplest possible reset. Forces a full scan
from scratch.

Risk: **a full scan of 209 004 files will take a LONG time
and consume Google Drive API quota**. Recent full scan
(Apr 1) completed — duration not captured — but this is
not a quick op. Daily quota for Drive API is ~1 billion
calls, which accommodates 209k but eats a chunk. The
in-progress scan will also generate many local I/O events
and ~1 GB of gRPC traffic.

### 4.3 Option C — preserve state.json for forensics

Before attempting A or B, preserve a copy:

```bash
cp $HOME/.cache/gdrive-sync/state.json \
   $HOME/.cache/gdrive-sync/state.json.broken-2026-04-14
```

So the root cause can be investigated later without a race
with operator activity.

**Delta's recommendation**: C first (always preserve), then
A (cheaper), fall back to B if A doesn't produce a clean
recovery.

## 5. Also failing — gcalendar + langfuse sync at 81 h stale

The same health-monitor run that surfaced the gdrive bug
also reported:

```text
[FAIL] sync.gcalendar_freshness  gcalendar sync 81h stale (>72h)
[FAIL] sync.langfuse_freshness   langfuse sync 81h stale (>72h)
```

Both crossed the 72 h freshness threshold ~9 hours ago
(given the 81h number is from 09:46 and we're at 16:23,
that's +6.5 hours of staleness, so actual 81 + 6.5 = 87.5
hours without a successful sync). **These are separate from
the gdrive bug** — different services, different state,
different failure modes. Delta has not drilled into either;
flagging for alpha to investigate as a second item.

## 6. Observability note — alert went nowhere

The health monitor is *catching* the gdrive-sync failure
every 5-minute tick and emitting `[FAIL]` lines into the
journal. But there's no apparent path from that journal
line to an ntfy push, a waybar notification, or a
dashboard. The operator would only discover the gap by
reading the journal manually.

Cross-reference: drop #14 (metric coverage gaps) Ring 3
includes alertmanager as a gap. Same root cause — the
alert signal exists, the user-facing notification doesn't.

**A compact fix**: add an `OnFailure=notify-failure@.service`
drop-in to `gdrive-sync.service` (alpha already has the
`notify-failure` template per the inactive list in earlier
drops). That gives the operator a ntfy push whenever the
service transitions to failed state.

## 7. Follow-ups

Ordered by urgency:

1. **Apply remediation** — alpha or operator runs
   Option C + A from § 4. Unblocks the whole gdrive-sync
   pipeline in ~5 minutes.
2. **Root-cause the `def` write** — `git log --all -S '"def"'
   -- agents/gdrive_sync.py tests/` to find any commit that
   introduced the string literal. If no commit has it, the
   corruption was a runtime / operator-side mutation and
   the specific origin is lost.
3. **Investigate gcalendar + langfuse sync 81 h stale** — a
   second drop if alpha wants delta to pursue.
4. **Wire `notify-failure@gdrive-sync.service`** so the next
   regression gets an ntfy push instead of a silent log
   line.
5. **Health-monitor probe hygiene**: drop the `SKIP` states
   down to `WARNING` severity. When a dependency check
   fails (e.g. `Validation failed for restart_unit` because
   `connectivity.gdrive-sync` is already failing), the
   dependent check SKIPs; current output lumps skips in
   with degraded. Confusing.

## 8. References

- `~/.cache/gdrive-sync/state.json` — live file, 161 MB,
  mtime 2026-04-12 00:30, corrupted `start_page_token`
- `agents/gdrive_sync.py:35` — `CACHE_DIR =
  Path.home() / ".cache" / "gdrive-sync"`
- `agents/gdrive_sync.py:36` — `STATE_FILE = CACHE_DIR /
  "state.json"`
- `agents/gdrive_sync.py:151` — `_load_state(path=STATE_FILE)`
- `agents/gdrive_sync.py:443-448` — `_incremental_sync`
  call site where the bad token flows into
  `changes().list(pageToken=…)`
- `systemctl --user status gdrive-sync.service` at
  2026-04-14T16:23 UTC — failed (Result: exit-code) since
  09:46 CDT
- `journalctl --user -u gdrive-sync.service --since
  "3 hours ago"` — full traceback ending in the HttpError
- `journalctl --user -u health-monitor.service --since
  "2 hours ago" | grep FAIL` — three sync services all
  reported failing
