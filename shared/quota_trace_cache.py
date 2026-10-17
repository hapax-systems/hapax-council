"""Disposable Codex quota read accelerator; raw JSONL remains the source.

This is private implementation state, not a ledger, receipt or admission input.
Only fields consumed by the quota reader are retained. Every reuse opens the raw
file: missing/replaced/truncated/changed sources cannot be supplied by the cache.
Unchanged local files are bound by device/inode/size/mtime/ctime and content probes.
Changed files require a hash of the ENTIRE cached prefix before tail reuse. There
is no append-only writer witness here, so active-file reads are still linear.
Kernel change stamps must be coherent; restoring mtime does not restore ctime.
This is not an adversarial filesystem or silent-media-corruption attestation.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path

MAX_CACHE_BYTES = 64 * 1024 * 1024
MAX_ENTRY_BYTES = 2 * 1024 * 1024
# A raw tool/output line can be much larger than its quota-only summary.
MAX_LINE_BYTES = 16 * 1024 * 1024
MAX_FILES = 16384
CHUNK_BYTES = 64 * 1024
PROBE_BYTES = 4096


class _Reread(Exception):
    """No verified acceleration is available; use the original source reader."""


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _stamp(value):
    if not stat.S_ISREG(value.st_mode) or value.st_ino <= 0 or value.st_ctime_ns <= 0:
        raise _Reread
    return [value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns]


def _mapping(value):
    value = value or {}
    if not isinstance(value, dict):
        raise _Reread
    return value


def _reset(value):
    # Keep the original scalar type: the burn-series key compares raw reset values.
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, str) and len(value) <= 80 and re.fullmatch(r"[0-9TtZz:+. eE-]*", value):
        return value
    raise _Reread


def _project(event):
    from shared.quota_headroom import instant, number

    payload = event.get("payload") or {}
    if not isinstance(payload, dict) or payload.get("type") != "token_count":
        return None
    at = instant(event.get("timestamp"))
    if at is None:
        return None
    info = _mapping(payload.get("info"))
    total = number(_mapping(info.get("total_token_usage")).get("total_tokens"))
    limits = _mapping(payload.get("rate_limits"))
    primary = _mapping(limits.get("primary"))
    used = number(primary.get("used_percent"))
    projected_limits = {}
    if used is not None and used >= 0 and limits.get("limit_id") in {None, "codex"}:
        for name in ("primary", "secondary"):
            window = _mapping(limits.get(name))
            projected_limits[name] = {
                "used_percent": number(window.get("used_percent")),
                "window_minutes": number(window.get("window_minutes")),
                "resets_at": _reset(window.get("resets_at")),
            }
        projected_limits["credits"] = {
            "balance": number(_mapping(limits.get("credits")).get("balance"))
        }
    return {
        "timestamp": at.isoformat(),
        "payload": {
            "type": "token_count",
            # A nonempty info with no total still witnesses unaccountable local activity.
            "info": {"total_token_usage": {"total_tokens": total}} if info else {},
            "rate_limits": projected_limits,
        },
    }


class QuotaTraceCache:
    def __init__(self, path: Path):
        self.path = path
        self.entries = {}
        self.seen = set()
        self.changed = False
        self.bytes_read = 0
        self.hits = 0
        self.appends = 0
        self.rereads = 0
        self.entry_bytes = 0
        # Any change to either parser invalidates this accelerator, including semantics.
        self.parser = _digest(
            Path(__file__).read_bytes() + Path(__file__).with_name("quota_headroom.py").read_bytes()
        )
        try:
            with path.open("rb") as stream:
                data = stream.read(MAX_CACHE_BYTES + 1)
            if len(data) > MAX_CACHE_BYTES:
                return
            envelope = json.loads(data)
            payload = envelope["payload"]
            if envelope["sha256"] != _digest(_encoded(payload)) or payload["parser"] != self.parser:
                return
            entries = payload["entries"]
            if not isinstance(entries, dict) or len(entries) > MAX_FILES:
                return
            self.entries = entries
            self.entry_bytes = len(_encoded(entries))
        except (OSError, ValueError, KeyError, TypeError, RecursionError):
            pass

    def _read(self, stream, size):
        data = stream.read(size)
        self.bytes_read += len(data)
        return data

    def _probe(self, stream, extent):
        stream.seek(0)
        first = self._read(stream, min(PROBE_BYTES, extent))
        stream.seek(max(0, extent - PROBE_BYTES))
        last = self._read(stream, min(PROBE_BYTES, extent))
        return _digest(first + last)

    def _prefix_hash(self, stream, extent):
        stream.seek(0)
        digest = hashlib.sha256()
        remaining = extent
        while remaining:
            data = self._read(stream, min(CHUNK_BYTES, remaining))
            if not data:
                raise _Reread
            digest.update(data)
            remaining -= len(data)
        return digest

    def _records(self, path):
        key = str(path.absolute())
        previous = self.entries.get(key)
        if previous is not None:
            self.seen.add(key)
        with path.open("rb") as stream:
            before = _stamp(os.fstat(stream.fileno()))
            records = []
            extent = 0
            digest = hashlib.sha256()
            if previous is not None:
                # Validate all cached input before it can affect quota output.
                if (
                    not isinstance(previous, dict)
                    or previous.get("source") != key
                    or not isinstance(previous.get("stamp"), list)
                    or len(previous["stamp"]) != 5
                    or not isinstance(previous.get("extent"), int)
                    or not 0 <= previous["extent"] <= before[2]
                    or previous["stamp"][:2] != before[:2]
                    or len(_encoded(previous)) > MAX_ENTRY_BYTES
                ):
                    raise _Reread
                extent = previous["extent"]
                records = previous["records"]
                if not isinstance(records, list) or any(_project(row) != row for row in records):
                    raise _Reread
                if previous["stamp"] == before:
                    if self._probe(stream, extent) != previous["probe"]:
                        raise _Reread
                    # No completed prefix changes; reuse its digest only while unchanged.
                    digest = None
                    self.hits += 1
                else:
                    digest = self._prefix_hash(stream, extent)
                    if digest.hexdigest() != previous["sha256"]:
                        raise _Reread
                    self.appends += 1
                records = list(records)
            stream.seek(extent)
            transient = []
            size = len(_encoded(records))
            while stream.tell() < before[2]:
                # Limit each allocation; an enormous line falls back to the legacy reader.
                line = stream.readline(min(MAX_LINE_BYTES + 1, before[2] - stream.tell()))
                self.bytes_read += len(line)
                if len(line) > MAX_LINE_BYTES:
                    raise _Reread
                complete = line.endswith(b"\n")
                if complete:
                    if digest is None:
                        # An unchanged snapshot can only have an unfinished suffix.
                        raise _Reread
                    digest.update(line)
                    extent = stream.tell()
                if b'"token_count"' in line and line.strip():
                    try:
                        event = json.loads(line)
                    except ValueError:
                        if complete:
                            raise _Reread from None
                        break
                    if not isinstance(event, dict):
                        raise _Reread
                    row = _project(event)
                    if row is not None:
                        size += len(_encoded(row))
                        if size > MAX_ENTRY_BYTES:
                            raise _Reread
                        (records if complete else transient).append(row)
                if not complete:
                    break
            probe = self._probe(stream, extent)
            if _stamp(os.fstat(stream.fileno())) != before or _stamp(path.stat()) != before:
                raise _Reread
            entry = {
                "source": key,
                "stamp": before,
                "extent": extent,
                "sha256": digest.hexdigest() if digest is not None else previous["sha256"],
                "probe": probe,
                "records": records,
            }
            if len(_encoded(entry)) > MAX_ENTRY_BYTES:
                raise _Reread
            entry_bytes = len(_encoded({key: entry}))
            old_bytes = len(_encoded({key: previous})) if previous is not None else 0
            if (
                entry != previous
                and (previous is not None or len(self.entries) < MAX_FILES)
                and self.entry_bytes - old_bytes + entry_bytes <= MAX_CACHE_BYTES - 1024
            ):
                self.entries[key] = entry
                self.seen.add(key)
                self.entry_bytes += entry_bytes - old_bytes
                self.changed = True
            return records + transient

    def records(self, path: Path, raw_reader):
        try:
            return self._records(path)
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError, _Reread):
            # Never supply an old summary after uncertainty. Rebuild only on a later scan.
            self.rereads += 1
            key = str(path.absolute())
            removed = self.entries.pop(key, None)
            if removed is not None:
                self.entry_bytes -= len(_encoded({key: removed}))
                self.changed = True
            return raw_reader(path, contains=b'"token_count"')

    def save(self):
        # Drop only disposable summaries. Missing files never become source evidence.
        entries = {key: value for key, value in self.entries.items() if key in self.seen}
        if not self.changed and len(entries) == len(self.entries):
            return
        bounded = {}
        size = 1024
        for key, value in sorted(entries.items()):
            size += len(_encoded({key: value}))
            if size > MAX_CACHE_BYTES - 1024 or len(bounded) >= MAX_FILES:
                break
            bounded[key] = value
        payload = {"parser": self.parser, "entries": bounded}
        data = _encoded({"payload": payload, "sha256": _digest(_encoded(payload))})
        if len(data) > MAX_CACHE_BYTES:
            return
        temp = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self.path.parent, delete=False) as stream:
                temp = Path(stream.name)
                stream.write(data)
            temp.replace(self.path)
        except OSError:
            pass  # Cache availability never changes quota evidence.
        finally:
            if temp is not None:
                try:
                    temp.unlink(missing_ok=True)
                except OSError:
                    pass
