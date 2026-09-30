"""Raw traces remain the oracle when a quota read accelerator is uncertain."""

import json
import os
import runpy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from shared.quota_headroom import TraceReadError, read_codex_token_count

NOW = datetime(2026, 9, 30, 20, tzinfo=UTC)


def event(*, minutes=0, used=20, total=100, balance=90):
    return {
        "timestamp": (NOW - timedelta(minutes=minutes)).isoformat(),
        "payload": {
            "type": "token_count",
            "info": {"total_token_usage": {"total_tokens": total}},
            "rate_limits": {
                "primary": {
                    "used_percent": used,
                    "window_minutes": 10080,
                    "resets_at": int((NOW + timedelta(days=1)).timestamp()),
                },
                "credits": {"balance": balance},
            },
        },
    }


def line(value):
    return json.dumps(value).encode() + b"\n"


def fixture(tmp_path):
    root = tmp_path / "sessions"
    root.mkdir()
    path = root / "rollout-test.jsonl"
    path.write_bytes(line(event(minutes=40, used=10)) + line(event()))
    return root, path, tmp_path / "cache.json"


def read(root, cache=None, *, now=NOW):
    kwargs = {"cache_path": cache} if cache is not None else {}
    return read_codex_token_count(root, now=now, **kwargs)


@pytest.mark.parametrize("change", ["replace", "truncate", "rewrite", "rewrite_append"])
def test_changed_source_never_reuses_unverified_summary(tmp_path, change):
    root, path, cache = fixture(tmp_path)
    assert read(root, cache) == read(root)
    old_stat = path.stat()
    data = line(event(minutes=40, used=99)) + line(event(used=88))
    if change == "replace":
        other = path.with_suffix(".new")
        other.write_bytes(data)
        other.replace(path)
    elif change == "truncate":
        path.write_bytes(line(event(used=77)))
    else:
        path.write_bytes(data + (line(event(used=66)) if change.endswith("append") else b""))
    # mtime alone is never an identity/freshness witness.
    os.utime(path, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    assert read(root, cache) == read(root)
    assert read(root, cache)[0].quantity != 20


@pytest.mark.parametrize("suffix", [b'{"payload":{"type":"token_count"', line(event())[:-1]])
def test_partial_last_record_is_replayed_exactly_once(tmp_path, suffix):
    root, path, cache = fixture(tmp_path)
    with path.open("ab") as stream:
        stream.write(suffix)
    assert read(root, cache) == read(root)
    assert read(root, cache) == read(root)
    with path.open("ab") as stream:
        stream.write(b"}}\n" if suffix.endswith(b'"token_count"') else b"\n")
        stream.write(line(event(used=35, total=150)))
    assert read(root, cache) == read(root)


def test_corruption_after_warm_cache_is_not_hidden(tmp_path):
    root, path, cache = fixture(tmp_path)
    read(root, cache)
    with path.open("ab") as stream:
        stream.write(b'{"token_count": invalid}\n')
    with pytest.raises(TraceReadError):
        read(root, cache)


def test_missing_rotated_trace_is_not_evidence(tmp_path):
    root, path, cache = fixture(tmp_path)
    read(root, cache)
    path.rename(path.with_suffix(".old"))
    assert read(root, cache) == read(root)
    assert read(root, cache)[0].label == "unobserved"


def test_broken_cache_rereads_raw_and_cannot_invent_headroom(tmp_path):
    root, _, cache = fixture(tmp_path)
    read(root, cache)
    cache.write_bytes(b'{"version": 999, "entries": invalid}')
    assert read(root, cache) == read(root)


def test_append_future_events_burn_and_credit_attribution_match_full_scan(tmp_path):
    root, path, cache = fixture(tmp_path)
    read(root, cache)
    with path.open("ab") as stream:
        stream.write(line(event(minutes=-1, used=22, total=100, balance=80)))
        stream.write(line(event(minutes=-2, used=24, total=200, balance=70)))
    for now in (NOW, NOW + timedelta(minutes=1), NOW + timedelta(minutes=3)):
        assert read(root, cache, now=now) == read(root, now=now)
    rows = read(root, cache, now=NOW + timedelta(minutes=3))
    assert [r.quantity for r in rows if "unattributed" in r.capacity_id] == [10]
    assert any(r.capacity_id.endswith(".burn") for r in rows)


def test_cache_failure_narrows_to_raw_and_preserves_source_bytes(tmp_path):
    root, path, cache = fixture(tmp_path)
    before = path.read_bytes()
    cache.mkdir()  # storage failure; cache is optional
    assert read(root, cache) == read(root)
    assert path.read_bytes() == before


@pytest.mark.parametrize("alias_kind", ["direct", "symlink"])
def test_cache_path_cannot_replace_a_raw_trace(tmp_path, alias_kind):
    root, path, _ = fixture(tmp_path)
    alias = path
    if alias_kind == "symlink":
        alias = tmp_path / "cache-alias.json"
        alias.symlink_to(path)
    before = path.read_bytes()
    assert read(root, alias) == read(root)
    assert path.read_bytes() == before
    if alias_kind == "symlink":
        assert alias.is_symlink()


def test_memory_and_disk_cache_are_bounded_without_losing_readings(tmp_path, monkeypatch):
    from shared import quota_trace_cache as module
    from shared.quota_headroom import json_lines

    root, path, cache_path = fixture(tmp_path)
    monkeypatch.setattr(module, "MAX_FILES", 2)
    monkeypatch.setattr(module, "MAX_CACHE_BYTES", 6000)
    cache = module.QuotaTraceCache(cache_path)
    for i in range(12):
        source = root / f"rollout-{i}.jsonl"
        source.write_bytes(path.read_bytes())
        assert list(cache.records(source, json_lines))
        assert len(cache.entries) <= 2
        assert len(module._encoded(cache.entries)) <= module.MAX_CACHE_BYTES
    cache.save()
    assert cache_path.stat().st_size <= module.MAX_CACHE_BYTES
    assert read(root, cache_path) == read(root)


def test_warm_unchanged_trace_has_bounded_reads(tmp_path):
    from shared.quota_headroom import json_lines
    from shared.quota_trace_cache import PROBE_BYTES, QuotaTraceCache

    root, path, cache_path = fixture(tmp_path)
    with path.open("ab") as stream:
        stream.write(line({"prompt": "private-content-never-cache" * 1000}) * 80)
    read(root, cache_path)
    cache = QuotaTraceCache(cache_path)
    assert list(cache.records(path, json_lines))
    assert cache.hits == 1
    assert cache.bytes_read <= 4 * PROBE_BYTES
    assert cache.bytes_read < path.stat().st_size / 100
    assert b"private-content" not in cache_path.read_bytes()


def test_large_irrelevant_record_does_not_disable_acceleration(tmp_path):
    from shared.quota_headroom import json_lines
    from shared.quota_trace_cache import PROBE_BYTES, QuotaTraceCache

    root, path, cache_path = fixture(tmp_path)
    with path.open("ab") as stream:
        stream.write(line({"irrelevant": "x" * (3 * 1024 * 1024)}))
    read(root, cache_path)
    cache = QuotaTraceCache(cache_path)
    assert list(cache.records(path, json_lines))
    assert cache.bytes_read <= 4 * PROBE_BYTES
    assert cache.hits == 1


def test_middle_rewrite_plus_append_verifies_entire_prefix(tmp_path):
    root, path, cache = fixture(tmp_path)
    padding = line({"irrelevant": "x" * 20000})
    path.write_bytes(padding + line(event()) + padding)
    read(root, cache)
    path.write_bytes(padding + line(event(used=75)) + padding + line({"end": True}))
    assert read(root, cache) == read(root)
    assert read(root, cache)[0].quantity == 75


@pytest.mark.parametrize("field", ["parser", "checksum", "records"])
def test_cache_schema_or_content_uncertainty_requires_raw_reread(tmp_path, field):
    from shared.quota_trace_cache import _digest, _encoded

    root, _, cache = fixture(tmp_path)
    read(root, cache)
    data = json.loads(cache.read_bytes())
    if field == "parser":
        data["payload"]["parser"] = "previous-parser"
        entry = next(iter(data["payload"]["entries"].values()))
        entry["records"][-1]["payload"]["rate_limits"]["primary"]["used_percent"] = 0
        data["sha256"] = _digest(_encoded(data["payload"]))
    elif field == "records":
        entry = next(iter(data["payload"]["entries"].values()))
        entry["records"] = [{"unexpected": "schema"}]
        data["sha256"] = _digest(_encoded(data["payload"]))
    else:
        entry = next(iter(data["payload"]["entries"].values()))
        entry["records"][-1]["payload"]["rate_limits"]["primary"]["used_percent"] = 0
        data["sha256"] = "broken"
    cache.write_bytes(_encoded(data))
    assert read(root, cache) == read(root)


def test_racing_source_cannot_publish_a_cached_snapshot(tmp_path, monkeypatch):
    from shared.quota_trace_cache import QuotaTraceCache

    root, path, cache = fixture(tmp_path)
    read(root, cache)
    probe = QuotaTraceCache._probe

    def race(self, stream, extent):
        result = probe(self, stream, extent)
        path.write_bytes(line(event(used=55)))
        return result

    monkeypatch.setattr(QuotaTraceCache, "_probe", race)
    assert read(root, cache)[0].quantity == 55


def test_same_size_middle_rewrite_with_restored_mtime_is_detected(tmp_path):
    root, path, cache = fixture(tmp_path)
    padding = line({"irrelevant": "x" * 20000})
    path.write_bytes(padding + line(event()) + padding)
    read(root, cache)
    before = path.stat()
    path.write_bytes(padding + line(event(used=75)) + padding)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert read(root, cache)[0].quantity == 75


def test_replaced_identical_source_is_reparsed(tmp_path):
    from shared.quota_headroom import json_lines
    from shared.quota_trace_cache import QuotaTraceCache

    root, path, cache_path = fixture(tmp_path)
    read(root, cache_path)
    replacement = path.with_suffix(".new")
    replacement.write_bytes(path.read_bytes())
    replacement.replace(path)
    cache = QuotaTraceCache(cache_path)
    assert list(cache.records(path, json_lines)) == list(json_lines(path))
    assert cache.rereads == 1


def test_unfinished_valid_json_is_never_persisted_as_complete(tmp_path):
    root, path, cache = fixture(tmp_path)
    with path.open("ab") as stream:
        stream.write(line(event(used=70))[:-1])
    assert read(root, cache)[0].quantity == 70
    with path.open("ab") as stream:
        stream.write(b"invalid-suffix")
    assert read(root, cache)[0].quantity == 20


def test_cache_byte_budget_does_not_truncate_quota_history(tmp_path, monkeypatch):
    from shared import quota_trace_cache as module
    from shared.quota_headroom import json_lines

    root, path, cache_path = fixture(tmp_path)
    monkeypatch.setattr(module, "MAX_CACHE_BYTES", 4000)
    cache = module.QuotaTraceCache(cache_path)
    for i in range(15):
        source = root / f"rollout-{i}.jsonl"
        source.write_bytes(path.read_bytes())
        assert list(cache.records(source, json_lines))
        assert len(module._encoded(cache.entries)) <= module.MAX_CACHE_BYTES
    cache.save()
    assert read(root, cache_path) == read(root)


def test_corruption_narrows_collector_to_unobserved(tmp_path):
    from shared.quota_headroom import collect_measurements

    root = tmp_path / ".codex/sessions"
    root.mkdir(parents=True)
    path = root / "rollout-broken.jsonl"
    cache = tmp_path / "cache.json"
    path.write_bytes(line(event()))
    read(root, cache)
    with path.open("ab") as stream:
        stream.write(b'{"token_count": broken}\n')
    rows = collect_measurements(tmp_path, tmp_path / "receipts", now=NOW, trace_cache_path=cache)
    assert rows["codex"][0].label == "unobserved"
    assert rows["codex"][0].reason_code == "corrupt_or_unreadable_source"


def test_writer_check_does_not_create_a_trace_cache(tmp_path, capsys):
    root = tmp_path / ".codex/sessions"
    root.mkdir(parents=True)
    (root / "rollout-test.jsonl").write_bytes(line(event()))
    script = Path(__file__).resolve().parents[2] / "scripts/hapax-quota-telemetry-writer"
    writer = runpy.run_path(str(script))
    rc = writer["main"](
        [
            "--check",
            "--trace-home",
            str(tmp_path),
            "--now",
            NOW.isoformat(),
            "--relay-receipt-dir",
            str(tmp_path / "receipts"),
            "--out",
            str(tmp_path / "out.json"),
        ]
    )
    assert rc == 0
    assert not (tmp_path / ".cache").exists()
    assert not (tmp_path / "out.json").exists()
    capsys.readouterr()
