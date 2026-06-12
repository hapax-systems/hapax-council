"""Tests for the coord feed-plane recheck (PR #4100's durable exit-predicate
witness). Decision paths pinned: unit parity, script parity, feed freshness,
vocab parity incl. the invented-token case, WARN-vs-FAIL, and the coord HTTP
probes against a local stub server. Self-contained per testing conventions."""

from __future__ import annotations

import http.server
import importlib.machinery
import importlib.util
import json
import os
import sys
import threading
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "scripts" / "hapax-coord-feeds-recheck"


def _load(env: dict[str, str]):
    """Load a fresh module instance under the given HAPAX_RECHECK_* env."""
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        # the script has no .py extension: load via an explicit source loader
        loader = importlib.machinery.SourceFileLoader("coord_recheck_test", str(_SCRIPT))
        spec = importlib.util.spec_from_loader("coord_recheck_test", loader)
        assert spec
        mod = importlib.util.module_from_spec(spec)
        sys.modules["coord_recheck_test"] = mod
        loader.exec_module(mod)
        return mod
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _scaffold(tmp_path: Path) -> dict[str, str]:
    """A fully-green on-disk world (HTTP checks excluded)."""
    repo = tmp_path / "repo"
    units_repo = repo / "systemd/units"
    units_repo.mkdir(parents=True)
    installed = tmp_path / "user-units"
    installed.mkdir()
    activation = tmp_path / "activation"
    coord = tmp_path / "coord"
    coord.mkdir()
    unit_names = (
        "hapax-sdlc-vocab-export.service",
        "hapax-sdlc-vocab-export.timer",
        "hapax-review-receipts-export.service",
        "hapax-review-receipts-export.timer",
        "hapax-rails-event-log.service",
        "hapax-rails-event-log.timer",
    )
    for u in unit_names:
        (units_repo / u).write_text(f"[Unit]\nDescription={u}\n")
        (installed / u).write_text(f"[Unit]\nDescription={u}\n")
    for rel in (
        "scripts/hapax-sdlc-vocab-export",
        "scripts/hapax-review-receipts-export",
        "scripts/hapax-rails-event-log",
        "scripts/hapax-coord-feeds-recheck",
    ):
        for root in (repo, activation):
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("#!/usr/bin/env python3\n")
    vocab = {
        "ladder_tokens": ["S0", "S5", "S6", "S7"],
        "pseudo_stages": ["BLOCKED"],
        "observed_stages": {"S5_REVIEW_GATE": {"count": 3, "ladder_token": "S5"}},
    }
    (coord / "sdlc-vocab.json").write_text(json.dumps(vocab))
    (coord / "review-receipts.json").write_text("{}")
    (coord / "sdlc-events.shadow.json").write_text("{}")
    (tmp_path / ".deployed-sha").write_text("abc123def4567890\n")
    return {
        "HAPAX_RECHECK_REPO": str(repo),
        "HAPAX_RECHECK_COORD_DIR": str(coord),
        "HAPAX_RECHECK_USER_UNITS": str(installed),
        "HAPAX_RECHECK_ACTIVATION": str(activation),
        "HAPAX_RECHECK_DEPLOY_SHA": str(tmp_path / ".deployed-sha"),
        "HAPAX_RECHECK_COORD_URL": "http://127.0.0.1:1",  # unreachable by default
    }


def _by_check(results):
    return {r["check"]: r for r in results}


def test_green_world_disk_checks_pass(tmp_path):
    mod = _load(_scaffold(tmp_path))
    res = _by_check(mod.run_checks(skip_systemctl=True))
    assert all(
        r["state"] == "OK"
        for k, r in res.items()
        if k.startswith(("units-tracked", "scripts-tracked", "feed-fresh"))
    )
    assert res["vocab-parity"]["state"] == "OK"


def test_differing_installed_unit_fails_with_next_action(tmp_path):
    env = _scaffold(tmp_path)
    drifted = Path(env["HAPAX_RECHECK_USER_UNITS"]) / "hapax-rails-event-log.service"
    drifted.write_text("[Unit]\nDescription=drifted\n")
    mod = _load(env)
    res = _by_check(mod.run_checks(skip_systemctl=True))
    r = res["units-tracked:hapax-rails-event-log.service"]
    assert r["state"] == "FAIL"
    assert "next:" in r["detail"]


def test_missing_installed_unit_fails(tmp_path):
    env = _scaffold(tmp_path)
    (Path(env["HAPAX_RECHECK_USER_UNITS"]) / "hapax-sdlc-vocab-export.timer").unlink()
    mod = _load(env)
    res = _by_check(mod.run_checks(skip_systemctl=True))
    assert res["units-tracked:hapax-sdlc-vocab-export.timer"]["state"] == "FAIL"


def test_drifted_activation_script_fails(tmp_path):
    env = _scaffold(tmp_path)
    p = Path(env["HAPAX_RECHECK_ACTIVATION"]) / "scripts/hapax-sdlc-vocab-export"
    p.write_text("#!/usr/bin/env python3\n# drifted\n")
    mod = _load(env)
    res = _by_check(mod.run_checks(skip_systemctl=True))
    r = res["scripts-tracked:scripts/hapax-sdlc-vocab-export"]
    assert r["state"] == "FAIL"
    assert "next:" in r["detail"]


def test_missing_feed_fails_with_producer_hint(tmp_path):
    env = _scaffold(tmp_path)
    (Path(env["HAPAX_RECHECK_COORD_DIR"]) / "review-receipts.json").unlink()
    mod = _load(env)
    res = _by_check(mod.run_checks(skip_systemctl=True))
    r = res["feed-fresh:review-receipts"]
    assert r["state"] == "FAIL"
    assert "hapax-review-receipts-export" in r["detail"]


def test_stale_feed_fails(tmp_path):
    env = _scaffold(tmp_path)
    p = Path(env["HAPAX_RECHECK_COORD_DIR"]) / "sdlc-vocab.json"
    old = time.time() - 10 * 600
    os.utime(p, (old, old))
    mod = _load(env)
    res = _by_check(mod.run_checks(skip_systemctl=True))
    assert res["feed-fresh:sdlc-vocab"]["state"] == "FAIL"


def test_malformed_vocab_json_fails(tmp_path):
    env = _scaffold(tmp_path)
    (Path(env["HAPAX_RECHECK_COORD_DIR"]) / "sdlc-vocab.json").write_text("{not json")
    mod = _load(env)
    res = _by_check(mod.run_checks(skip_systemctl=True))
    assert res["vocab-parity"]["state"] == "FAIL"


def test_unknown_passthrough_warns_not_fails(tmp_path):
    env = _scaffold(tmp_path)
    vocab = {
        "ladder_tokens": ["S5"],
        "pseudo_stages": [],
        "observed_stages": {
            "S5_REVIEW_GATE": {"count": 1, "ladder_token": "S5"},
            "WEIRD_STAGE": {"count": 1, "ladder_token": "unknown"},
        },
    }
    (Path(env["HAPAX_RECHECK_COORD_DIR"]) / "sdlc-vocab.json").write_text(json.dumps(vocab))
    mod = _load(env)
    res = _by_check(mod.run_checks(skip_systemctl=True))
    assert res["vocab-parity"]["state"] == "WARN"


def test_invented_token_counts_as_unknown(tmp_path):
    # round-2 review finding: a ladder_token OUTSIDE the ladder must not
    # count as mapped even though it isn't the literal string "unknown"
    env = _scaffold(tmp_path)
    vocab = {
        "ladder_tokens": ["S5"],
        "pseudo_stages": [],
        "observed_stages": {"S13_FOO": {"count": 1, "ladder_token": "S13"}},
    }
    (Path(env["HAPAX_RECHECK_COORD_DIR"]) / "sdlc-vocab.json").write_text(json.dumps(vocab))
    mod = _load(env)
    res = _by_check(mod.run_checks(skip_systemctl=True))
    assert res["vocab-parity"]["state"] == "WARN"
    assert "S13_FOO" in res["vocab-parity"]["detail"]


class _StubCoord(http.server.BaseHTTPRequestHandler):
    rails: dict = {}
    version: dict = {}

    def do_GET(self):  # noqa: N802 — BaseHTTPRequestHandler API
        if self.path == "/api/coord/version":
            body = json.dumps(self.version).encode()
            ctype = "application/json"
        elif self.path == "/api/coord/rails":
            body = json.dumps(self.rails).encode()
            ctype = "application/json"
        else:
            body = b'<!doctype HTML><HTML style="background: hsl(210 20% 8%);"></HTML>'
            ctype = "text/html"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # quiet
        pass


def _stub_server(version: dict, rails: dict):
    _StubCoord.version = version
    _StubCoord.rails = rails
    srv = http.server.HTTPServer(("127.0.0.1", 0), _StubCoord)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_live_coord_probes_pass_against_stub(tmp_path):
    env = _scaffold(tmp_path)
    srv = _stub_server(
        version={"deployed_sha": "abc123def4567890"},
        rails={
            "feed_state": "live",
            "stations": ["S0", "S5"],
            "items": [{"id": "t1", "review": "blocked"}, {"id": "t2", "review": None}],
        },
    )
    try:
        env["HAPAX_RECHECK_COORD_URL"] = f"http://127.0.0.1:{srv.server_address[1]}"
        mod = _load(env)
        res = _by_check(mod.run_checks(skip_systemctl=True))
        assert res["coord-live"]["state"] == "OK"
        assert res["coord-provenance"]["state"] == "OK"
        assert res["coord-boot-shell"]["state"] == "OK"
        assert res["coord-rails-consumed"]["state"] == "OK"
        assert res["coord-verdicts-visible"]["state"] == "OK"
        assert "1 blocked" in res["coord-verdicts-visible"]["detail"]
    finally:
        srv.shutdown()


def test_verdictless_rails_fails_visibility(tmp_path):
    env = _scaffold(tmp_path)
    srv = _stub_server(
        version={"deployed_sha": "abc123def4567890"},
        rails={"feed_state": "live", "stations": ["S0"], "items": [{"id": "t1"}]},
    )
    try:
        env["HAPAX_RECHECK_COORD_URL"] = f"http://127.0.0.1:{srv.server_address[1]}"
        mod = _load(env)
        res = _by_check(mod.run_checks(skip_systemctl=True))
        assert res["coord-verdicts-visible"]["state"] == "FAIL"
    finally:
        srv.shutdown()


def test_unreachable_coord_fails_with_next_action(tmp_path):
    mod = _load(_scaffold(tmp_path))  # COORD_URL points at port 1
    res = _by_check(mod.run_checks(skip_systemctl=True))
    assert res["coord-live"]["state"] == "FAIL"
    assert "next:" in res["coord-live"]["detail"]


def test_provenance_mismatch_fails(tmp_path):
    env = _scaffold(tmp_path)
    Path(env["HAPAX_RECHECK_DEPLOY_SHA"]).write_text("ffff999988887777\n")
    srv = _stub_server(
        version={"deployed_sha": "abc123def4567890"},
        rails={"feed_state": "live", "stations": ["S0"], "items": []},
    )
    try:
        env["HAPAX_RECHECK_COORD_URL"] = f"http://127.0.0.1:{srv.server_address[1]}"
        mod = _load(env)
        res = _by_check(mod.run_checks(skip_systemctl=True))
        assert res["coord-provenance"]["state"] == "FAIL"
    finally:
        srv.shutdown()
