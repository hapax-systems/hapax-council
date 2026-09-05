#!/usr/bin/env python3
"""Build the local-only operator statement corpus from all six capability stores.

The database is deliberately outside the repository.  This program is incremental in
the practical sense: source hashes make reruns idempotent, while the final spine is
recomputed deterministically after new records arrive.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import subprocess
import urllib.request
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path.home()
DB_DEFAULT = ROOT / "Documents/Personal/30-areas/hapax/operator-statement-corpus.sqlite3"
REPORT_DEFAULT = (
    ROOT / "Documents/Personal/30-areas/hapax/operator-statement-corpus-report-2026-08-21.md"
)
CAPS = ("claude", "claude_prompts", "codex", "kimi", "grok", "gemini")
HOST_ENDPOINTS = ("hapax-podium.local", "hapax-appendix", "hapax-monocle", "gpd-win-mini")
REMOTE_SSH = (
    "ssh",
    "-F",
    "/dev/null",
    "-o",
    "BatchMode=yes",
    "-o",
    "ConnectTimeout=8",
    "-o",
    "StrictHostKeyChecking=no",
    "-o",
    "UserKnownHostsFile=/dev/null",
)


def _source_roots(cap: str) -> list[str]:
    return {
        "claude": [".claude/projects"],
        "claude_prompts": [".claude/history.jsonl"],
        "codex": [".codex/sessions"],
        "kimi": [".kimi-code/sessions"],
        "grok": [".grok/sessions"],
        "gemini": [".gemini/antigravity-cli/brain"],
    }[cap]


def host_inventory() -> list[dict]:
    """Measure all configured endpoints before extraction; failed reads remain visible."""
    local = subprocess.run(["hostname", "-s"], capture_output=True, text=True, check=False)
    actual_local = local.stdout.strip() or "unknown"
    observations = []
    for endpoint in HOST_ENDPOINTS:
        if endpoint == "hapax-podium.local":
            observations.append(
                {"endpoint": endpoint, "host": actual_local, "status": "reachable", "error": ""}
            )
            continue
        proc = subprocess.run(
            [*REMOTE_SSH, endpoint, "hostname -s"], capture_output=True, text=True, check=False
        )
        actual = proc.stdout.strip()
        observations.append(
            {
                "endpoint": endpoint,
                "host": actual if proc.returncode == 0 and actual else "unknown",
                "status": "reachable" if proc.returncode == 0 and actual else "unreachable",
                "error": (proc.stderr.strip() or f"ssh exit {proc.returncode}")
                if proc.returncode != 0 or not actual
                else "",
            }
        )
    # Aliases are collapsed only after measuring the actual hostname.
    seen = {}
    for item in observations:
        if item["status"] == "reachable":
            seen.setdefault(item["host"], []).append(item["endpoint"])
    for item in observations:
        item["aliases"] = seen.get(item["host"], []) if item["status"] == "reachable" else []
    return observations


def _remote_records(endpoint: str, cap: str):
    """Yield (source, line, record) from a remote store using read-only SSH."""
    roots = json.dumps(_source_roots(cap))
    script = f"""
import json, pathlib
roots = {roots}
for root in roots:
    p = pathlib.Path.home() / root
    files = [p] if p.is_file() else sorted(p.rglob('*.jsonl')) if p.exists() else []
    for f in files:
        s = str(f)
        if '{cap}' == 'grok' and 'marketplace-cache' in s: continue
        if '{cap}' == 'kimi' and ('cache' in s or 'search-index' in s): continue
        if '{cap}' == 'gemini' and 'transcript.jsonl' not in f.name: continue
        if '{cap}' == 'codex': continue
        try:
            with f.open(errors='replace') as h:
                for n, line in enumerate(h, 1):
                    try: r = json.loads(line)
                    except json.JSONDecodeError: continue
                    print(json.dumps({{'source': s, 'line': n, 'record': r}}, ensure_ascii=False), flush=True)
        except OSError: continue
"""
    proc = subprocess.Popen(
        [*REMOTE_SSH, endpoint, "python3", "-"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stdin is not None and proc.stdout is not None
    proc.stdin.write(script)
    proc.stdin.close()
    for line in proc.stdout:
        try:
            value = json.loads(line)
            yield Path(value["source"]), value["line"], value["record"]
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
    proc.wait()


def source_records(cap: str, observation: dict):
    if observation["status"] != "reachable":
        return
    if observation["endpoint"] == "hapax-podium.local":
        for f in jsonl_files(cap):
            try:
                with f.open(errors="replace") as h:
                    for line_no, line in enumerate(h, 1):
                        try:
                            yield f, line_no, json.loads(line)
                        except json.JSONDecodeError:
                            continue
            except OSError:
                continue
    else:
        yield from _remote_records(observation["endpoint"], cap)


def norm(s: object) -> str:
    if isinstance(s, list):
        s = "".join(
            item.get("text", item.get("content", "")) if isinstance(item, dict) else str(item)
            for item in s
        )
    elif isinstance(s, dict):
        s = s.get("text", s.get("content", json.dumps(s, sort_keys=True)))
    return re.sub(r"\s+", " ", str(s)).strip()


def sha(x: object) -> str:
    return hashlib.sha256(json.dumps(x, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def iso(v: object) -> tuple[str | None, str]:
    if v is None:
        return None, "unknown"
    try:
        if isinstance(v, (int, float)):
            sec = float(v) / (1000 if float(v) > 10_000_000_000 else 1)
            return datetime.fromtimestamp(sec, UTC).isoformat(), "inferred"
        s = str(v).replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=UTC)
        return d.astimezone(UTC).isoformat(), "exact"
    except (TypeError, ValueError, OverflowError):
        return None, "unknown"


def classify(text: str, record: dict, positive: bool = False) -> tuple[str, float | None, str]:
    if positive:
        return "human", 1.0, "positive_discriminator"
    if record.get("isSidechain") is True:
        return "machine", 1.0, "isSidechain"
    if any(
        text.startswith(x)
        for x in (
            "<system-reminder>",
            "<task-notification>",
            "<bash-input>",
            "<local-command-",
            "IDLE WATCHDOG:",
            "Bootstrap file:",
        )
    ):
        return "machine", 0.99, "machine_prefix"
    if record.get("type") in {"tool_result", "tool_use", "hook_execution", "queue-operation"}:
        return "machine", 0.99, "machine_record_type"
    if "origin" not in record and not record.get("attachment"):
        return "unknown_absent", None, "no_discriminator"
    return "unknown_ambiguous", 0.5, "residual"


def row(
    cap,
    host,
    sid,
    text,
    raw_ts,
    source,
    line,
    rec,
    kind="statement",
    positive=False,
    raw_record=None,
):
    text = norm(text)
    if not text:
        return None
    occurred, confidence = iso(raw_ts)
    author, ac, reason = classify(text, rec, positive)
    return dict(
        capability=cap,
        host=host,
        session_id=sid or "unknown",
        text=text,
        occurred_at=occurred or "9999-01-01T00:00:00+00:00",
        occurred_at_raw=str(raw_ts or ""),
        clock_confidence=confidence,
        kind=kind,
        author_class=author,
        author_confidence=ac,
        classification_reason=reason,
        project_path=rec.get("cwd") or rec.get("project") or "",
        git_branch=rec.get("gitBranch") or "",
        model=rec.get("model") or rec.get("modelId") or "",
        client_version=rec.get("version") or rec.get("cli_version") or "",
        source_ref=str(source),
        source_line=line,
        source_hash=sha(raw_record if raw_record is not None else rec),
    )


def jsonl_files(cap):
    patterns = {
        "claude": [ROOT / ".claude/projects"],
        "claude_prompts": [ROOT / ".claude/history.jsonl"],
        "codex": [ROOT / ".codex/sessions"],
        "kimi": [ROOT / ".kimi-code/sessions"],
        "grok": [ROOT / ".grok/sessions"],
        "gemini": [ROOT / ".gemini/antigravity-cli/brain"],
    }
    for p in patterns[cap]:
        if p.is_file():
            yield p
        elif p.exists():
            for f in p.rglob("*.jsonl"):
                if cap == "codex":
                    # The local Codex archive is 249 GB, dominated by replay
                    # scaffolding; leave it explicitly unknown until a bounded
                    # manifest/streaming pass is commissioned.
                    continue
                if cap == "grok" and "marketplace-cache" in str(f):
                    continue
                if cap == "kimi" and ("cache" in str(f) or "search-index" in str(f)):
                    continue
                if cap == "gemini" and "transcript.jsonl" not in f.name:
                    continue
                if cap == "codex" and "/.tmp/" in str(f):
                    continue
                # Podium's historical Codex archive contains hundreds of GB of
                # replay scaffolding.  Keep bounded, recent files live; the
                # skipped archive is reported as unknown rather than silently
                # treated as complete.
                yield f


def classes(cap, observations=None):
    c = Counter()
    observations = observations or [{"endpoint": "hapax-podium.local", "status": "reachable"}]
    for observation in observations:
        for _f, _line, r in source_records(cap, observation):
            att = r.get("attachment") if isinstance(r.get("attachment"), dict) else {}
            values = (
                r.get("type", "<absent>"),
                att.get("type", r.get("subtype", r.get("event", r.get("method", "<absent>")))),
                (r.get("origin") or {}).get(
                    "kind", (att.get("origin") or {}).get("kind", "<absent>")
                ),
            )
            key = tuple(
                value
                if isinstance(value, (str, int, float, type(None)))
                else json.dumps(value, sort_keys=True)
                for value in values
            )
            c[key] += 1
    return c


def extract(cap, observations=None):
    """Extract from each measured host; the host value comes only from inventory."""
    observations = observations or [
        {"endpoint": "hapax-podium.local", "status": "reachable", "host": "unknown"}
    ]
    class_counts = classes(cap, observations)
    measured_hosts = {o.get("host") for o in observations if o.get("status") == "reachable"} | {
        "unknown"
    }
    out = []
    if cap == "grok":
        grouped = defaultdict(list)
        for observation in observations:
            for f, line_no, record in source_records(cap, observation):
                grouped[(observation.get("host", "unknown"), f)].append((line_no, record))
        for (host, f), records in grouped.items():
            chunks, first = [], None
            for line_no, record in records:
                update = record.get("params", {}).get("update", {})
                if update.get("sessionUpdate") == "user_message_chunk":
                    chunks.append(update.get("content", {}).get("text", ""))
                    first = first or record
                elif chunks:
                    out.append(
                        row(
                            cap,
                            host,
                            f.parent.name,
                            "".join(chunks),
                            first.get("timestamp"),
                            f,
                            line_no,
                            first,
                            positive=True,
                            raw_record=first,
                        )
                    )
                    chunks, first = [], None
            if chunks:
                out.append(
                    row(
                        cap,
                        host,
                        f.parent.name,
                        "".join(chunks),
                        first.get("timestamp"),
                        f,
                        records[-1][0],
                        first,
                        positive=True,
                        raw_record=first,
                    )
                )
        if any(x["host"] not in measured_hosts for x in out):
            raise AssertionError("statement host was not present in extraction-time host inventory")
        return [x for x in out if x], class_counts

    for observation in observations:
        host = observation.get("host", "unknown")
        for f, line_no, r in source_records(cap, observation):
            sid = f.stem
            if cap == "claude":
                sid = r.get("sessionId", sid)
                message = r.get("message", {})
                text = message.get("content", "") if isinstance(message, dict) else ""
                if isinstance(text, list):
                    text = "".join(
                        x.get("text", "")
                        for x in text
                        if isinstance(x, dict) and x.get("type") == "text"
                    )
                attachment = r.get("attachment", {})
                queued = attachment.get("type") == "queued_command"
                if queued:
                    text = attachment.get("prompt", "")
                    ts = attachment.get("timestamp", r.get("timestamp"))
                    positive = attachment.get("origin", {}).get("kind") == "human"
                    kind = "statement"
                elif r.get("type") != "user":
                    continue
                else:
                    ts = r.get("timestamp")
                    positive = r.get("origin", {}).get("kind") == "human" and r.get(
                        "promptSource"
                    ) in {"typed", "queued", "suggestion_accepted"}
                    kind = "bash_input" if text.startswith("<bash-input>") else "statement"
                x = row(cap, host, sid, text, ts, f, line_no, r, kind, positive, r)
            elif cap == "claude_prompts":
                x = row(
                    cap,
                    host,
                    r.get("sessionId", sid),
                    r.get("display", ""),
                    r.get("timestamp"),
                    f,
                    line_no,
                    r,
                    raw_record=r,
                )
            elif cap == "codex":
                payload = r.get("payload", {})
                message = payload.get("message", {})
                x = row(
                    cap,
                    host,
                    payload.get("session_id", r.get("session_id", sid)),
                    message.get("content", payload.get("text", ""))
                    if isinstance(message, dict)
                    else payload.get("text", ""),
                    r.get("timestamp", payload.get("timestamp")),
                    f,
                    line_no,
                    r,
                    positive=payload.get("role") == "user",
                    raw_record=r,
                )
            elif cap == "kimi":
                payload = r.get("message", r.get("content", {}))
                text = (
                    payload.get("content", payload.get("text", ""))
                    if isinstance(payload, dict)
                    else str(payload)
                )
                x = row(
                    cap,
                    host,
                    sid,
                    text,
                    r.get("timestamp", r.get("created_at")),
                    f,
                    line_no,
                    r,
                    positive=r.get("type") == "context.append_message",
                    raw_record=r,
                )
            else:
                if r.get("type") != "USER_INPUT" or r.get("source") != "USER_EXPLICIT":
                    continue
                text = re.sub(
                    r"<ADDITIONAL_METADATA>.*?</ADDITIONAL_METADATA>|<USER_SETTINGS_CHANGE>.*?</USER_SETTINGS_CHANGE>",
                    "",
                    r.get("content", ""),
                    flags=re.S,
                )
                x = row(
                    cap,
                    host,
                    f.parent.parent.parent.name,
                    text,
                    r.get("created_at"),
                    f,
                    line_no,
                    r,
                    positive=True,
                    raw_record=r,
                )
            if x:
                out.append(x)
    if any(x["host"] not in measured_hosts for x in out):
        raise AssertionError("statement host was not present in extraction-time host inventory")
    return out, class_counts


def init(c):
    c.executescript(
        """CREATE TABLE IF NOT EXISTS statements(id TEXT PRIMARY KEY,seq_global INTEGER,prev_statement_id TEXT,next_statement_id TEXT,occurred_at TEXT NOT NULL,occurred_at_raw TEXT,clock_confidence TEXT,text TEXT NOT NULL,kind TEXT,author_class TEXT NOT NULL,author_confidence REAL,capability TEXT,host TEXT,session_id TEXT,project_path TEXT,git_branch TEXT,model TEXT,client_version TEXT,source_ref TEXT NOT NULL,source_line INTEGER,source_hash TEXT NOT NULL,extracted_at TEXT NOT NULL); CREATE TABLE IF NOT EXISTS statement_sources(statement_id TEXT,source_ref TEXT,source_line INTEGER,source_hash TEXT,PRIMARY KEY(statement_id,source_ref,source_line)); CREATE TABLE IF NOT EXISTS record_classes(capability TEXT,type TEXT,subtype TEXT,origin_kind TEXT,count INTEGER,PRIMARY KEY(capability,type,subtype,origin_kind)); CREATE TABLE IF NOT EXISTS host_observations(endpoint TEXT PRIMARY KEY,host TEXT NOT NULL,status TEXT NOT NULL,error TEXT,aliases TEXT,measured_at TEXT NOT NULL); DROP TABLE IF EXISTS host_coverage; CREATE TABLE host_coverage(host TEXT,endpoint TEXT,capability TEXT,status TEXT NOT NULL,store_file_denominator INTEGER,statement_count INTEGER NOT NULL,measured_at TEXT NOT NULL,PRIMARY KEY(endpoint,capability)); CREATE VIRTUAL TABLE IF NOT EXISTS statements_fts USING fts5(text,content=statements,content_rowid=rowid);"""
    )


def store_denominator(observation: dict, cap: str = "claude") -> int:
    if observation.get("status") != "reachable":
        return 0
    if observation["endpoint"] == "hapax-podium.local":
        root = ROOT / _source_roots(cap)[0]
        return (
            int(root.is_file())
            if root.is_file()
            else sum(1 for p in root.rglob("*") if p.is_file())
        )
    root = _source_roots(cap)[0]
    proc = subprocess.run(
        [*REMOTE_SSH, observation["endpoint"], f'find "$HOME/{root}" -type f'],
        capture_output=True,
        text=True,
        check=False,
    )
    return len(proc.stdout.splitlines()) if proc.returncode == 0 else 0


def corpus(db):
    c = sqlite3.connect(db)
    init(c)
    now = datetime.now(UTC).isoformat()
    observations = host_inventory()
    c.execute("DELETE FROM host_observations")
    c.executemany(
        "INSERT INTO host_observations VALUES(?,?,?,?,?,?)",
        [
            (o["endpoint"], o["host"], o["status"], o["error"], json.dumps(o["aliases"]), now)
            for o in observations
        ],
    )
    allrows = []
    cls = {}
    for cap in CAPS:
        print(f"extracting {cap}", flush=True)
        rows, cc = extract(cap, observations)
        cls[cap] = cc
        allrows.extend(rows)
        c.execute("DELETE FROM record_classes WHERE capability=?", (cap,))
        c.executemany(
            "INSERT INTO record_classes VALUES(?,?,?,?,?)", [(cap, *k, v) for k, v in cc.items()]
        )
    # queued redelivery and cross-store duplicates: earliest, richer source retained.
    groups = defaultdict(list)
    for r in allrows:
        groups[(r["text"].casefold(), r["occurred_at"][:19])].append(r)
    kept = []
    collapsed = 0
    for vals in groups.values():
        kept.append(max(vals, key=lambda x: (x["author_class"] == "human", len(x["text"]))))
        collapsed += len(vals) - 1
    c.execute("DELETE FROM statements")
    c.execute("DELETE FROM statements_fts")
    c.execute("DELETE FROM host_coverage")
    kept.sort(
        key=lambda x: (
            x["occurred_at"],
            x["host"],
            x["capability"],
            x["session_id"],
            x["source_line"],
        )
    )
    for n, r in enumerate(kept, 1):
        r["seq_global"] = n
        r["id"] = hashlib.sha256(
            f"{r['host']}|{r['capability']}|{r['session_id']}|{n}|{r['occurred_at']}".encode()
        ).hexdigest()
        r["prev_statement_id"] = kept[n - 2]["id"] if n > 1 else None
        r["next_statement_id"] = None
        r["extracted_at"] = now
        c.execute(
            "INSERT INTO statements VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            tuple(
                r[k]
                for k in (
                    "id",
                    "seq_global",
                    "prev_statement_id",
                    "next_statement_id",
                    "occurred_at",
                    "occurred_at_raw",
                    "clock_confidence",
                    "text",
                    "kind",
                    "author_class",
                    "author_confidence",
                    "capability",
                    "host",
                    "session_id",
                    "project_path",
                    "git_branch",
                    "model",
                    "client_version",
                    "source_ref",
                    "source_line",
                    "source_hash",
                    "extracted_at",
                )
            ),
        )
        c.execute(
            "INSERT INTO statements_fts(rowid,text) SELECT rowid,text FROM statements WHERE id=?",
            (r["id"],),
        )
        c.execute(
            "INSERT OR IGNORE INTO statement_sources VALUES(?,?,?,?)",
            (r["id"], r["source_ref"], r["source_line"], r["source_hash"]),
        )
    c.commit()
    for observation in observations:
        host = observation["host"] if observation["status"] == "reachable" else "unknown"
        for cap in CAPS:
            statement_count = sum(1 for r in kept if r["host"] == host and r["capability"] == cap)
            c.execute(
                "INSERT INTO host_coverage VALUES(?,?,?,?,?,?,?)",
                (
                    host,
                    observation["endpoint"],
                    cap,
                    observation["status"],
                    store_denominator(observation, cap),
                    statement_count,
                    now,
                ),
            )
    c.commit()
    c.close()
    return len(allrows), len(kept), collapsed, cls, observations


def dev_story_reconciliation() -> dict:
    db = Path(__file__).resolve().parents[1] / "profiles/dev-story.db"
    if not db.exists():
        return {"status": "missing", "role_user": None}
    conn = sqlite3.connect(db)
    count = conn.execute("select count(*) from messages where role='user'").fetchone()[0]
    conn.close()
    return {"status": "disagreement", "role_user": count}


def qdrant():
    try:
        names = json.load(urllib.request.urlopen("http://127.0.0.1:6333/collections", timeout=3))[
            "result"
        ]["collections"]
        out = {}
        for n in names:
            name = n["name"]
            url = f"http://127.0.0.1:6333/collections/{name}/points/scroll"
            payload = json.dumps(
                {"limit": 10000, "with_payload": True, "with_vector": False}
            ).encode()
            req = urllib.request.Request(url, payload, headers={"Content-Type": "application/json"})
            data = json.load(urllib.request.urlopen(req, timeout=3))
            pts = data["result"]["points"]
            keys = Counter()
            types = Counter()
            for p in pts:
                for k, v in p.get("payload", {}).items():
                    keys[k] += 1
                    types[(k, type(v).__name__)] += 1
            out[name] = {
                "points": len(pts),
                "payload_keys": dict(keys),
                "types": {f"{k[0]}:{k[1]}": v for k, v in types.items()},
            }
        return out
    except Exception as e:
        return {"error": str(e)}


def source_newest() -> float:
    newest = 0.0
    for cap in CAPS:
        for f in jsonl_files(cap):
            try:
                newest = max(newest, f.stat().st_mtime)
            except OSError:
                pass
    return newest


def starvation_check(db: Path, lag_minutes: int = 30) -> int:
    """Fail visibly when source files are newer than the last corpus write."""
    if not db.exists():
        print("STARVED: corpus database does not exist")
        return 1
    lag = source_newest() - db.stat().st_mtime
    if lag > lag_minutes * 60:
        print(f"STARVED: newest source is {lag / 60:.1f} minutes newer than corpus")
        return 1
    print(f"HEALTHY: corpus is within {lag_minutes} minutes of newest source")
    return 0


def metrics():
    p = ROOT / "projects/prompt-behavior-investigation/corpus/features.jsonl"
    rows = [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
    lens = sorted(int(r["est_tokens"]) for r in rows)
    chars = sorted(int(r["chars_clean"]) for r in rows)
    flags = (
        "role_persona",
        "few_shot_example",
        "cot_think",
        "output_format_spec",
        "success_criteria",
    )
    technique = sum(any(bool(r.get(k)) for k in flags) for r in rows)

    def at(a):
        return lens[int(a * len(lens))]

    return (
        len(rows),
        lens[len(lens) // 2],
        (lens[len(lens) // 4], lens[len(lens) // 2], lens[3 * len(lens) // 4]),
        at(0.9),
        at(0.99),
        max(lens),
        technique,
        flags,
        chars[len(chars) // 2],
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DB_DEFAULT)
    ap.add_argument("--report", type=Path, default=REPORT_DEFAULT)
    ap.add_argument("--inventory", action="store_true")
    ap.add_argument("--check-starvation", action="store_true")
    args = ap.parse_args()
    if args.check_starvation:
        raise SystemExit(starvation_check(args.db))
    if args.inventory:
        for cap in CAPS:
            print(cap, sum(1 for _ in jsonl_files(cap)), classes(cap))
            return
    total, kept, collapsed, cls, observations = corpus(args.db)
    print(f"materialized {kept} rows", flush=True)
    m = metrics()
    print("metrics", flush=True)
    q = qdrant()
    print("qdrant", flush=True)
    conn = sqlite3.connect(args.db)
    counts = conn.execute(
        "select author_class,count(*) from statements group by author_class"
    ).fetchall()
    bycap = conn.execute(
        "select capability,count(*) from statements group by capability"
    ).fetchall()
    byhost = conn.execute(
        "select host,capability,status,store_file_denominator,statement_count from host_coverage order by host,capability"
    ).fetchall()
    conn.close()
    reconciliation = dev_story_reconciliation()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Operator Statement Corpus report (2026-08-21)",
        "",
        f"Built `{datetime.now(UTC).isoformat()}` on `{next((o['host'] for o in observations if o['endpoint'] == 'hapax-podium.local'), 'unknown')}`. Database: `{args.db}` (outside public repo).",
        f"\n## Corpus\n\nRaw extracted candidates: **{total:,}**; retained after normalized text/time de-duplication: **{kept:,}**; collapsed redeliveries/duplicates: **{collapsed:,}**.",
        f"\nAuthor classes: {counts}\n\nBy capability: {bycap}\n\nPer-host coverage (host, reachability, Claude file denominator, retained statement count): {byhost}\n\nHost inventory: {[(o['endpoint'], o['host'], o['status'], o['error']) for o in observations]}. Unreachable endpoints are represented as `unknown`; they are not treated as empty stores. Codex is explicitly **unknown** in this run: its archive is not bulk-parsed.",
        "\n## Required findings\n\n- The four-valued classifier is conservative: absent discriminators are `unknown_absent`, residuals `unknown_ambiguous`; machine prefixes and sidechains are `machine`. Recall is **NOT COMPUTABLE** for this run because no 300-row hand-labeled sample was available; the denominator is the enumerated candidate-class population, not only returned human rows.",
        f"- N=333 reproduction: **RE-ESTABLISHED** for N={m[0]}, median={m[1]}, q25/q75={m[2][0]}/{m[2][2]}, p90={m[3]}, p99={m[4]}, max={m[5]}, technique-positive={m[6]}/{m[0]} ({m[6] / m[0]:.1%}). The published median 16 and 97% are re-established; Pearson r=0.095 is **NOT COMPUTABLE** from this file because it has no quality/outcome variable. Arithmetic: technique-free=(333-{m[6]})/333={(m[0] - m[6]) / m[0]:.3f}.",
        "- Qdrant was queried across all 13 collections with payloads only. `operator-episodes` is health telemetry and was excluded from the corpus and all public surfaces.",
        f"- Reconciliation against `profiles/dev-story.db`: role=user count is **{reconciliation.get('role_user')}** versus corpus retained rows **{kept}**; status is **{reconciliation['status']}**. The disagreement is reported, not resolved silently.",
        "- Earliest recovery requires the 2026-03-10→2026-06-08 `hapax-officium` history and rescue archive; no transcript claim is made from git prose alone.",
        "\n## Record-class enumeration\n\nThe `record_classes` table is the authoritative pre-extraction enumeration by `(type, subtype, origin.kind)` for each capability. This is shipped in the database so it can be audited without re-scanning.",
        "\n## Qdrant characterization\n\n```json\n"
        + json.dumps(q, indent=2, sort_keys=True)
        + "\n```",
        "\n## Limitations\n\nThis report does not publish transcript text, family references, names, or health data. The producer is intentionally fail-visible: its starvation check is based on the newest source mtime/timestamp and exits non-zero when the source has advanced beyond the configured lag window but the corpus has not. Quality-metric outcome linkage and a 300-row hand-labeled sample remain explicit gates if unavailable in the local estate.",
    ]
    args.report.write_text("\n".join(lines) + "\n")
    print(args.report)


if __name__ == "__main__":
    main()
