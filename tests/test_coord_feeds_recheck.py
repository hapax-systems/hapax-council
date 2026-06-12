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
import struct
import subprocess
import sys
import threading
import time
import types
import zlib
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "scripts" / "hapax-coord-feeds-recheck"
_DEPLOY_SCRIPT = _REPO / "scripts" / "hapax-coord-deploy"


def _load(env: dict[str, str]):
    """Load a fresh module instance under the given HAPAX_RECHECK_* env."""
    old = {k: os.environ.get(k) for k in {*env, "PLAYWRIGHT_BROWSERS_PATH"}}
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
    coord_activation = tmp_path / "coord-activation" / "worktree"
    coord_activation.mkdir(parents=True)
    coord_source_repo = tmp_path / "hapax-coord"
    coord_source_repo.mkdir()
    coord = tmp_path / "coord"
    browser_root = tmp_path / "source-activation" / "playwright-browsers"
    coord.mkdir()
    unit_names = (
        "hapax-coord.service",
        "hapax-sdlc-vocab-export.service",
        "hapax-sdlc-vocab-export.timer",
        "hapax-review-receipts-export.service",
        "hapax-review-receipts-export.timer",
        "hapax-rails-event-log.service",
        "hapax-rails-event-log.timer",
        "hapax-coord-rebuild.service",
        "hapax-coord-rebuild.timer",
        "studio-camera-reconfigure@.service",
    )
    for u in unit_names:
        if u == "hapax-coord.service":
            text = (
                "[Unit]\n"
                "Description=Hapax SBCL+CLOG coordination dashboard (source-only)\n"
                f"ConditionPathExists={coord_activation}/scripts/run-dev.sh\n\n"
                "[Service]\n"
                f"Environment=HAPAX_COORD_ROOT={coord_activation}\n"
                "Type=simple\n"
                f"WorkingDirectory={coord_activation}\n"
                f"ExecStart={coord_activation}/scripts/run-dev.sh --daemon\n"
                "Restart=on-failure\n"
            )
        else:
            text = f"[Unit]\nDescription={u}\n"
        (units_repo / u).write_text(text)
        (installed / u).write_text(text)
    run_dev = coord_activation / "scripts/run-dev.sh"
    run_dev.parent.mkdir(parents=True)
    run_dev.write_text("#!/usr/bin/env bash\n")
    run_dev.chmod(0o755)
    deploy_text = _DEPLOY_SCRIPT.read_text()
    for rel in (
        "scripts/hapax-sdlc-vocab-export",
        "scripts/hapax-review-receipts-export",
        "scripts/hapax-rails-event-log",
        "scripts/hapax-playwright-chromium-prestage",
        "scripts/hapax-coord-feeds-recheck",
        "scripts/hapax-coord-deploy",
        "systemd/units/studio-camera-reconfigure.sh",
        "shared/rails_event_log.py",
    ):
        for root in (repo, activation):
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("#!/usr/bin/env python3\n")
            if rel == "scripts/hapax-coord-deploy":
                p.write_text(deploy_text)
                p.chmod(0o755)
    browser = browser_root / "chromium_headless_shell-999" / "chrome-headless-shell-linux64"
    browser.mkdir(parents=True)
    executable = browser / "chrome-headless-shell"
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o755)
    vocab = {
        "ladder_tokens": ["S0", "S5", "S6", "S7"],
        "pseudo_stages": ["BLOCKED"],
        "observed_stages": {"S5_REVIEW_GATE": {"count": 3, "ladder_token": "S5"}},
    }
    (coord / "sdlc-vocab.json").write_text(json.dumps(vocab))
    receipts = {
        "schema": 1,
        "dossiers": [{"task_id": "t1", "verdict": "blocked"}],
        "acceptances": [],
    }
    (coord / "review-receipts.json").write_text(json.dumps(receipts))
    (coord / "sdlc-events.jsonl").write_text(
        json.dumps(
            {
                "event_id": "evt-t1-stage",
                "item_id": "t1",
                "kind": "stage",
                "stage_to": "S5_REVIEW_GATE",
                "ts": "2026-06-12T00:00:00+00:00",
            }
        )
        + "\n"
    )
    (tmp_path / ".deployed-sha").write_text("abc123def4567890\n")
    return {
        "HAPAX_RECHECK_REPO": str(repo),
        "HAPAX_RECHECK_COORD_DIR": str(coord),
        "HAPAX_RECHECK_USER_UNITS": str(installed),
        "HAPAX_RECHECK_ACTIVATION": str(activation),
        "HAPAX_RECHECK_COORD_ACTIVATION": str(coord_activation),
        "HAPAX_RECHECK_COORD_SOURCE_REPO": str(coord_source_repo),
        "HAPAX_RECHECK_COORD_DEPLOY_SCRIPT": str(activation / "scripts/hapax-coord-deploy"),
        "HAPAX_RECHECK_PLAYWRIGHT_BROWSERS": str(browser_root),
        "HAPAX_RECHECK_DEPLOY_SHA": str(tmp_path / ".deployed-sha"),
        "HAPAX_RECHECK_COORD_URL": "http://127.0.0.1:1",  # unreachable by default
    }


def _by_check(results):
    return {r["check"]: r for r in results}


def _cmd(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> str:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def _deploy_fixture_commit(repo: Path, marker: str) -> str:
    (repo / "README.md").write_text(f"{marker}\n")
    _cmd(["git", "-C", str(repo), "add", "README.md"])
    _cmd(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Hapax Test",
            "-c",
            "user.email=test@hapax.local",
            "commit",
            "-m",
            f"fixture {marker}",
        ],
        env={
            **os.environ,
            "GIT_AUTHOR_DATE": "2026-06-12T00:00:00+0000",
            "GIT_COMMITTER_DATE": "2026-06-12T00:00:00+0000",
        },
    )
    return _cmd(["git", "-C", str(repo), "rev-parse", "HEAD"])


def _browser_ok(mod):
    return lambda _url: mod.BrowserSurfaceWitness(
        ok=True,
        detail="test browser witness",
        elapsed=0.35,
        last_good_seen=True,
        last_good_elapsed=0.050,
        last_good_visible_seen=True,
        last_good_content_seen=True,
        last_good_rect_area=4096,
        fresh_yard_seen=True,
        fresh_yard_elapsed=0.250,
        fresh_yard_visible_seen=True,
        fresh_yard_rect_area=4096,
        fresh_yard_chip_count=3,
        fresh_yard_text="YARD abc123def vocab 13 blocked",
        dashboard_seen=True,
        dark_paint_seen=True,
        white_paint_seen=False,
        pixel_sample_count=64,
        pixel_white_ratio=0.0,
        pixel_nonwhite_ratio=1.0,
        rendered_blocked_seen=True,
        rendered_receipt_seen=True,
        rendered_review_seen=True,
        rendered_verdict_detail="13 blocked | 6 receipts",
        rendered_verdict_text="t1 review blocked",
    )


def _run(mod, *, browser_probe=None):
    return mod.run_checks(
        skip_systemctl=True,
        browser_probe=browser_probe or _browser_ok(mod),
    )


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + b"\0\0\0\0"


def _png_bytes(width: int, height: int, color_type: int, raw_scanlines: bytes) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(raw_scanlines))
        + _png_chunk(b"IEND", b"")
    )


def _filtered_png_row(filter_type: int, decoded: bytes, previous: bytes, channels: int) -> bytes:
    raw = bytearray()
    for idx, value in enumerate(decoded):
        left = decoded[idx - channels] if idx >= channels else 0
        up = previous[idx]
        up_left = previous[idx - channels] if idx >= channels else 0
        if filter_type == 1:
            predictor = left
        elif filter_type == 2:
            predictor = up
        elif filter_type == 3:
            predictor = (left + up) // 2
        elif filter_type == 4:
            predictor = mod_paeth(left, up, up_left)
        else:
            predictor = 0
        raw.append((value - predictor) & 0xFF)
    return bytes([filter_type]) + bytes(raw)


def mod_paeth(left: int, up: int, up_left: int) -> int:
    p = left + up - up_left
    pa = abs(p - left)
    pb = abs(p - up)
    pc = abs(p - up_left)
    if pa <= pb and pa <= pc:
        return left
    if pb <= pc:
        return up
    return up_left


def test_png_surface_summary_decodes_png_filters_and_ratios(tmp_path):
    mod = _load(_scaffold(tmp_path))
    channels = 3
    previous = bytes(2 * channels)
    decoded_rows = [
        bytes([255, 255, 255, 0, 0, 0]),
        bytes([255, 255, 255, 0, 0, 0]),
        bytes([255, 255, 255, 0, 0, 0]),
        bytes([255, 255, 255, 0, 0, 0]),
        bytes([255, 255, 255, 0, 0, 0]),
    ]
    raw = bytearray()
    for filter_type, decoded in enumerate(decoded_rows):
        raw.extend(_filtered_png_row(filter_type, decoded, previous, channels))
        previous = decoded

    png = _png_bytes(2, len(decoded_rows), 2, bytes(raw))

    assert mod._png_surface_summary(png) == (10, 0.5, 0.5)


def test_png_surface_summary_skips_transparent_alpha_pixels(tmp_path):
    mod = _load(_scaffold(tmp_path))
    raw = bytes(
        [
            0,
            255,
            255,
            255,
            0,
            0,
            0,
            0,
            255,
        ]
    )
    png = _png_bytes(2, 1, 6, raw)

    assert mod._png_surface_summary(png) == (1, 0.0, 1.0)


def test_browser_live_surface_exercises_playwright_path(tmp_path, monkeypatch):
    mod = _load(_scaffold(tmp_path))
    calls = {"init_scripts": [], "waits": [], "launches": [], "screenshots": []}

    class FakeTimeoutError(Exception):
        pass

    class FakePage:
        def add_init_script(self, script):
            calls["init_scripts"].append(script)

        def goto(self, url, wait_until, timeout):
            assert url == "http://coord.test"
            assert wait_until == "domcontentloaded"
            assert timeout == 10_000

        def wait_for_function(self, predicate, timeout):
            calls["waits"].append((predicate, timeout))

        def wait_for_timeout(self, timeout):
            assert timeout == 100

        def screenshot(self, **kwargs):
            calls["screenshots"].append(kwargs)
            return b"fake-png"

        def evaluate(self, _expr):
            return {
                "first": {"lastGood": 80, "freshYard": 750, "dashboard": 700},
                "freshYardChipCount": 2,
                "freshYardText": "YARD abc123def vocab",
                "darkPaintSeen": True,
                "whitePaintSeen": False,
                "lastGoodVisibleSeen": True,
                "lastGoodContentSeen": True,
                "lastGoodRectArea": 4096,
                "freshYardVisibleSeen": True,
                "freshYardRectArea": 8192,
                "renderedBlockedSeen": True,
                "renderedReceiptSeen": True,
                "renderedReviewSeen": True,
                "renderedVerdictDetail": "13 blocked | 6 receipts",
                "renderedVerdictText": "t1 review blocked",
            }

    class FakeContext:
        def new_page(self):
            return FakePage()

        def close(self):
            pass

    class FakeBrowser:
        def new_context(self, **kwargs):
            assert kwargs["viewport"] == {"width": 1440, "height": 1000}
            return FakeContext()

        def close(self):
            pass

    class FakeChromium:
        def launch(self, **kwargs):
            calls["launches"].append(kwargs)
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.TimeoutError = FakeTimeoutError
    sync_api.sync_playwright = lambda: FakePlaywright()
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)
    monkeypatch.setattr(mod, "_png_surface_summary", lambda _png: (64, 0.0, 1.0))
    monkeypatch.setenv("HAPAX_RECHECK_BROWSER_ATTEMPTS", "1")

    witness = mod._browser_live_surface("http://coord.test", "abc123def4567890")

    assert witness.ok
    assert witness.last_good_seen
    assert witness.last_good_elapsed == 0.08
    assert witness.last_good_visible_seen
    assert witness.last_good_content_seen
    assert witness.last_good_rect_area == 4096
    assert witness.fresh_yard_seen
    assert witness.fresh_yard_elapsed == 0.75
    assert witness.fresh_yard_visible_seen
    assert witness.fresh_yard_rect_area == 8192
    assert witness.fresh_yard_chip_count == 2
    assert witness.fresh_yard_text == "YARD abc123def vocab"
    assert witness.dark_paint_seen
    assert not witness.white_paint_seen
    assert witness.pixel_sample_count == 64
    assert witness.pixel_white_ratio == 0.0
    assert witness.pixel_nonwhite_ratio == 1.0
    assert witness.rendered_blocked_seen
    assert witness.rendered_receipt_seen
    assert witness.rendered_review_seen
    assert witness.rendered_verdict_text == "t1 review blocked"
    assert "#yard-status" in calls["init_scripts"][0]
    assert 'querySelectorAll("#yard-status")' in calls["init_scripts"][0]
    assert "freshYardText" in calls["init_scripts"][0]
    assert "freshYardVisibleSeen" in calls["init_scripts"][0]
    assert "visibleTextWithoutYard" in calls["init_scripts"][0]
    assert "#last-good-replay" in calls["init_scripts"][0]
    assert "addedNodes" in calls["init_scripts"][0]
    assert any("freshYard" in predicate for predicate, _timeout in calls["waits"])
    assert any("abc123def" in predicate for predicate, _timeout in calls["waits"])
    assert calls["launches"] == [{"headless": True, "args": ["--no-sandbox"]}]
    assert calls["screenshots"] == [{"full_page": False, "timeout": 2_000}]


def test_launch_chromium_requires_prestaged_browser(tmp_path, monkeypatch):
    mod = _load(_scaffold(tmp_path))

    class FakeChromium:
        def launch(self, **_kwargs):
            raise RuntimeError("browser executable missing")

    class FakePlaywright:
        chromium = FakeChromium()

    monkeypatch.setattr(mod, "_staged_chromium_executable", lambda: None)

    try:
        mod._launch_chromium(FakePlaywright())
    except RuntimeError as exc:
        assert "pre-stage Playwright Chromium" in str(exc)
        assert "hapax-playwright-chromium-prestage" in str(exc)
    else:
        raise AssertionError("missing staged browser must fail without installing")


def test_launch_chromium_uses_staged_executable_after_default_launch_fails(tmp_path, monkeypatch):
    mod = _load(_scaffold(tmp_path))

    class FakeChromium:
        def __init__(self):
            self.calls = 0
            self.kwargs = []

        def launch(self, **kwargs):
            self.calls += 1
            self.kwargs.append(kwargs)
            if self.calls == 1:
                raise RuntimeError("default browser missing")
            return "browser"

    class FakePlaywright:
        chromium = FakeChromium()

    monkeypatch.setattr(mod, "_staged_chromium_executable", lambda: "/stage/chrome")

    assert mod._launch_chromium(FakePlaywright()) == "browser"
    assert FakePlaywright.chromium.kwargs[1]["executable_path"] == "/stage/chrome"


def test_launch_chromium_fails_after_staged_executable_fails(tmp_path, monkeypatch):
    mod = _load(_scaffold(tmp_path))

    class FakeChromium:
        def __init__(self):
            self.kwargs = []

        def launch(self, **kwargs):
            self.kwargs.append(kwargs)
            raise RuntimeError(f"launch failed {len(self.kwargs)}: {kwargs}")

    class FakePlaywright:
        chromium = FakeChromium()

    monkeypatch.setattr(mod, "_staged_chromium_executable", lambda: "/stage/chrome")

    try:
        mod._launch_chromium(FakePlaywright())
    except RuntimeError as exc:
        assert "staged executable /stage/chrome also failed" in str(exc)
        assert "pre-stage Playwright Chromium" in str(exc)
    else:
        raise AssertionError("bad staged browser must fail without installing")
    assert FakePlaywright.chromium.kwargs[1]["executable_path"] == "/stage/chrome"


def test_green_world_disk_checks_pass(tmp_path):
    mod = _load(_scaffold(tmp_path))
    res = _by_check(_run(mod))
    assert all(
        r["state"] == "OK"
        for k, r in res.items()
        if k.startswith(("units-tracked", "scripts-tracked", "feed-fresh"))
    )
    assert res["vocab-parity"]["state"] == "OK"
    assert res["units-template-name:studio-camera-reconfigure"]["state"] == "OK"
    assert res["units-git-index-names:camera-template"]["state"] == "OK"
    assert res["units-pr-diff-path-shapes:systemd"]["state"] == "OK"
    assert res["units-pr-diff-camera-template"]["state"] == "OK"
    assert res["playwright-browser-staged:chromium"]["state"] == "OK"
    assert res["coord-service-root"]["state"] == "OK"
    assert res["coord-deploy-script"]["state"] == "OK"


def test_missing_staged_browser_fails_with_next_action(tmp_path):
    env = _scaffold(tmp_path)
    browser_root = Path(env["HAPAX_RECHECK_PLAYWRIGHT_BROWSERS"])
    for path in sorted(browser_root.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            path.rmdir()
    mod = _load(env)
    res = _by_check(_run(mod))
    r = res["playwright-browser-staged:chromium"]
    assert r["state"] == "FAIL"
    assert "hapax-playwright-chromium-prestage" in r["detail"]


def test_coord_deploy_helper_fetches_writes_sha_and_is_idempotent(tmp_path):
    origin = tmp_path / "origin.git"
    source = tmp_path / "source"
    writer = tmp_path / "writer"
    act_root = tmp_path / "coord-activation"
    fakebin = tmp_path / "bin"
    restart_log = tmp_path / "systemctl.log"
    fakebin.mkdir()
    systemctl = fakebin / "systemctl"
    systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "$*" >> "${HAPAX_COORD_DEPLOY_SYSTEMCTL_LOG:?}"\n'
        'if [ "${HAPAX_COORD_DEPLOY_FAIL_RESTART:-}" = "1" ]; then\n'
        "  exit 42\n"
        "fi\n"
    )
    systemctl.chmod(0o755)

    _cmd(["git", "init", "--bare", str(origin)])
    _cmd(["git", "init", str(source)])
    _cmd(["git", "-C", str(source), "checkout", "-b", "main"])
    first_sha = _deploy_fixture_commit(source, "first")
    _cmd(["git", "-C", str(source), "remote", "add", "origin", str(origin)])
    _cmd(["git", "-C", str(source), "push", "-u", "origin", "main"])

    env = {
        **os.environ,
        "HAPAX_COORD_DEPLOY_REPO": str(source),
        "HAPAX_COORD_DEPLOY_ACT_ROOT": str(act_root),
        "HAPAX_COORD_DEPLOY_SYSTEMCTL_LOG": str(restart_log),
        "PATH": f"{fakebin}:{os.environ.get('PATH', '')}",
    }
    _cmd([str(_DEPLOY_SCRIPT)], env=env)
    worktree = act_root / "worktree"
    assert (worktree / ".deployed-sha").read_text().strip() == first_sha
    assert _cmd(["git", "-C", str(worktree), "rev-parse", "HEAD"]) == first_sha
    assert restart_log.read_text().splitlines() == ["--user restart hapax-coord.service"]

    _cmd([str(_DEPLOY_SCRIPT)], env=env)
    assert restart_log.read_text().splitlines() == ["--user restart hapax-coord.service"]

    _cmd(["git", "clone", "-b", "main", str(origin), str(writer)])
    second_sha = _deploy_fixture_commit(writer, "second")
    _cmd(["git", "-C", str(writer), "push", "origin", "main"])
    assert _cmd(["git", "-C", str(source), "rev-parse", "origin/main"]) == first_sha
    failed = subprocess.run(
        [str(_DEPLOY_SCRIPT)],
        env={**env, "HAPAX_COORD_DEPLOY_FAIL_RESTART": "1"},
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert failed.returncode == 42
    assert (worktree / ".deployed-sha").read_text().strip() == first_sha
    assert _cmd(["git", "-C", str(worktree), "rev-parse", "HEAD"]) == second_sha
    assert restart_log.read_text().splitlines() == [
        "--user restart hapax-coord.service",
        "--user restart hapax-coord.service",
    ]

    _cmd([str(_DEPLOY_SCRIPT)], env=env)
    assert _cmd(["git", "-C", str(source), "rev-parse", "origin/main"]) == second_sha
    assert (worktree / ".deployed-sha").read_text().strip() == second_sha
    assert _cmd(["git", "-C", str(worktree), "rev-parse", "HEAD"]) == second_sha
    assert restart_log.read_text().splitlines() == [
        "--user restart hapax-coord.service",
        "--user restart hapax-coord.service",
        "--user restart hapax-coord.service",
    ]


def test_coord_rebuild_timer_checked_when_systemctl_enabled(tmp_path):
    env = _scaffold(tmp_path)
    mod = _load(env)

    def fake_systemctl(*args):
        verb = args[0]
        if verb == "show":
            return env["HAPAX_RECHECK_COORD_ACTIVATION"]
        unit = args[1]
        assert verb in {"is-enabled", "is-active"}
        if unit == "hapax-coord.service":
            return "active"
        if unit == "hapax-coord-rebuild.timer":
            return "enabled" if verb == "is-enabled" else "active"
        if unit.endswith(".timer"):
            return "enabled" if verb == "is-enabled" else "active"
        return "unknown"

    mod._systemctl = fake_systemctl
    res = _by_check(mod.run_checks(browser_probe=_browser_ok(mod)))
    assert res["units-active:hapax-coord-rebuild.timer"]["state"] == "OK"
    assert res["units-active:hapax-coord.service"]["state"] == "OK"
    assert res["coord-deploy-exercise"]["state"] == "OK"


def test_missing_tracked_coord_rebuild_timer_fails(tmp_path):
    env = _scaffold(tmp_path)
    (Path(env["HAPAX_RECHECK_REPO"]) / "systemd/units/hapax-coord-rebuild.timer").unlink()
    mod = _load(env)
    res = _by_check(_run(mod))
    r = res["units-tracked:hapax-coord-rebuild.timer"]
    assert r["state"] == "FAIL"
    assert "unit missing from repo" in r["detail"]


def test_coord_service_mutable_workdir_fails_deploy_root_check(tmp_path):
    env = _scaffold(tmp_path)
    stale = (
        "[Unit]\n"
        "Description=Hapax SBCL+CLOG coordination dashboard (source-only)\n"
        f"ConditionPathExists={env['HAPAX_RECHECK_COORD_ACTIVATION']}/scripts/run-dev.sh\n\n"
        "[Service]\n"
        f"Environment=HAPAX_COORD_ROOT={env['HAPAX_RECHECK_COORD_ACTIVATION']}\n"
        "Type=simple\n"
        f"WorkingDirectory={env['HAPAX_RECHECK_COORD_SOURCE_REPO']}\n"
        f"ExecStart={env['HAPAX_RECHECK_COORD_ACTIVATION']}/scripts/run-dev.sh --daemon\n"
    )
    for target in (
        Path(env["HAPAX_RECHECK_REPO"]) / "systemd/units/hapax-coord.service",
        Path(env["HAPAX_RECHECK_USER_UNITS"]) / "hapax-coord.service",
    ):
        target.write_text(stale)
    mod = _load(env)
    res = _by_check(_run(mod))
    r = res["coord-service-root"]
    assert r["state"] == "FAIL"
    assert "WorkingDirectory" in r["detail"]


def test_coord_deploy_runtime_drift_fails(tmp_path):
    env = _scaffold(tmp_path)
    deploy = Path(env["HAPAX_RECHECK_COORD_DEPLOY_SCRIPT"])
    deploy.write_text(deploy.read_text() + "\n# unreviewed runtime drift\n")
    mod = _load(env)
    res = _by_check(_run(mod))
    r = res["coord-deploy-script"]
    assert r["state"] == "FAIL"
    assert "differs from tracked" in r["detail"]


def test_coord_deploy_contract_without_sha_write_fails(tmp_path):
    env = _scaffold(tmp_path)
    bad_contract = '"writes_deployed_sha":true'
    for deploy in (
        Path(env["HAPAX_RECHECK_REPO"]) / "scripts/hapax-coord-deploy",
        Path(env["HAPAX_RECHECK_COORD_DEPLOY_SCRIPT"]),
    ):
        deploy.write_text(deploy.read_text().replace(bad_contract, '"writes_deployed_sha":false'))
    mod = _load(env)
    res = _by_check(_run(mod))
    r = res["coord-deploy-script"]
    assert r["state"] == "FAIL"
    assert "writes_deployed_sha" in r["detail"]


def test_differing_installed_unit_fails_with_next_action(tmp_path):
    env = _scaffold(tmp_path)
    drifted = Path(env["HAPAX_RECHECK_USER_UNITS"]) / "hapax-rails-event-log.service"
    drifted.write_text("[Unit]\nDescription=drifted\n")
    mod = _load(env)
    res = _by_check(_run(mod))
    r = res["units-tracked:hapax-rails-event-log.service"]
    assert r["state"] == "FAIL"
    assert "next:" in r["detail"]
    assert "daemon-reload" in r["detail"]
    assert "enable --now hapax-rails-event-log.timer" in r["detail"]
    assert "enable --now hapax-rails-event-log.service" not in r["detail"]


def test_explicit_premerge_bridge_warns_on_service_unit_drift(tmp_path):
    env = _scaffold(tmp_path)
    env["HAPAX_RECHECK_PREMERGE_BRIDGE"] = "1"
    tracked = Path(env["HAPAX_RECHECK_REPO"]) / "systemd/units/hapax-rails-event-log.service"
    installed = Path(env["HAPAX_RECHECK_USER_UNITS"]) / "hapax-rails-event-log.service"
    tracked.write_text(
        "# Hapax-Auto-Enable: true\n"
        "[Unit]\nDescription=Fold SDLC feeds into the rails event log\n\n"
        "[Service]\nType=oneshot\n"
        "ExecStart=%h/.cache/hapax/source-activation/worktree/.venv/bin/python "
        "%h/.cache/hapax/source-activation/worktree/scripts/hapax-rails-event-log\n"
    )
    installed.write_text(
        "# Hapax-Auto-Enable: true\n"
        "# BRIDGE INSTALL 2026-06-12: versioned copy rides council PR #4100.\n"
        "[Unit]\nDescription=Fold SDLC feeds into the rails event log\n\n"
        "[Service]\nType=oneshot\n"
        "ExecStart=%h/.cache/hapax/source-activation/worktree/.venv/bin/python "
        f"{env['HAPAX_RECHECK_ACTIVATION']}/scripts/hapax-rails-event-log\n"
    )
    mod = _load(env)
    res = _by_check(_run(mod))
    r = res["units-tracked:hapax-rails-event-log.service"]
    assert r["state"] == "WARN"
    assert "expected explicit pre-merge bridge" in r["detail"]


def test_explicit_premerge_bridge_does_not_hide_arbitrary_producer_drift(tmp_path):
    env = _scaffold(tmp_path)
    env["HAPAX_RECHECK_PREMERGE_BRIDGE"] = "1"
    drifted = Path(env["HAPAX_RECHECK_USER_UNITS"]) / "hapax-rails-event-log.service"
    drifted.write_text("[Unit]\nDescription=arbitrary broken producer drift\n")
    mod = _load(env)
    res = _by_check(_run(mod))
    r = res["units-tracked:hapax-rails-event-log.service"]
    assert r["state"] == "FAIL"
    assert "beyond the expected pre-merge bridge" in r["detail"]


def test_explicit_premerge_bridge_does_not_hide_camera_unit_drift(tmp_path):
    env = _scaffold(tmp_path)
    env["HAPAX_RECHECK_PREMERGE_BRIDGE"] = "1"
    drifted = Path(env["HAPAX_RECHECK_USER_UNITS"]) / "studio-camera-reconfigure@.service"
    drifted.write_text("[Unit]\nDescription=mutable checkout drift\n")
    mod = _load(env)
    res = _by_check(_run(mod))
    r = res["units-tracked:studio-camera-reconfigure@.service"]
    assert r["state"] == "FAIL"
    assert "template/static service" in r["detail"]


def test_corrupted_camera_template_filename_fails(tmp_path):
    env = _scaffold(tmp_path)
    bad_name = "studio-camera-reconfigure" + chr(32) + "@.service"
    bad = Path(env["HAPAX_RECHECK_REPO"]) / "systemd/units" / bad_name
    bad.write_text("[Unit]\nDescription=bad template filename\n")
    mod = _load(env)
    res = _by_check(_run(mod))
    r = res["units-template-name:studio-camera-reconfigure"]
    diff_shape = res["units-pr-diff-path-shapes:systemd"]
    assert r["state"] == "FAIL"
    assert diff_shape["state"] == "FAIL"
    assert bad_name in r["detail"]
    assert "forbidden_systemd_paths" in diff_shape["detail"]


def test_nested_composite_camera_template_filename_fails(tmp_path):
    env = _scaffold(tmp_path)
    bad_dir = "studio-camera-reconfigure" + chr(32) + "@systemd"
    bad = Path(env["HAPAX_RECHECK_REPO"]) / "systemd/units" / bad_dir / "units" / "bad.service"
    bad.parent.mkdir(parents=True)
    bad.write_text("[Unit]\nDescription=bad nested template filename\n")
    mod = _load(env)
    res = _by_check(_run(mod))
    template = res["units-template-name:studio-camera-reconfigure"]
    index = res["units-git-index-names:camera-template"]
    diff_shape = res["units-pr-diff-path-shapes:systemd"]
    pr_diff = res["units-pr-diff-camera-template"]
    assert template["state"] == "FAIL"
    assert index["state"] == "FAIL"
    assert diff_shape["state"] == "FAIL"
    assert pr_diff["state"] == "FAIL"
    assert "invalid_camera_service_paths" in template["detail"]
    assert "forbidden_composites" in index["detail"]
    assert "forbidden_systemd_paths" in diff_shape["detail"]
    assert "forbidden_changed_composites" in pr_diff["detail"]


def test_missing_installed_unit_fails(tmp_path):
    env = _scaffold(tmp_path)
    (Path(env["HAPAX_RECHECK_USER_UNITS"]) / "hapax-sdlc-vocab-export.timer").unlink()
    mod = _load(env)
    res = _by_check(_run(mod))
    assert res["units-tracked:hapax-sdlc-vocab-export.timer"]["state"] == "FAIL"


def test_drifted_activation_script_fails(tmp_path):
    env = _scaffold(tmp_path)
    p = Path(env["HAPAX_RECHECK_ACTIVATION"]) / "scripts/hapax-sdlc-vocab-export"
    p.write_text("#!/usr/bin/env python3\n# drifted\n")
    mod = _load(env)
    res = _by_check(_run(mod))
    r = res["scripts-tracked:scripts/hapax-sdlc-vocab-export"]
    assert r["state"] == "FAIL"
    assert "next:" in r["detail"]


def test_drifted_camera_activation_helper_fails(tmp_path):
    env = _scaffold(tmp_path)
    p = Path(env["HAPAX_RECHECK_ACTIVATION"]) / "systemd/units/studio-camera-reconfigure.sh"
    p.write_text("#!/bin/sh\n# drifted\n")
    mod = _load(env)
    res = _by_check(_run(mod))
    r = res["scripts-tracked:systemd/units/studio-camera-reconfigure.sh"]
    assert r["state"] == "FAIL"
    assert "activation copy differs" in r["detail"]


def test_missing_feed_fails_with_producer_hint(tmp_path):
    env = _scaffold(tmp_path)
    (Path(env["HAPAX_RECHECK_COORD_DIR"]) / "review-receipts.json").unlink()
    mod = _load(env)
    res = _by_check(_run(mod))
    r = res["feed-fresh:review-receipts"]
    assert r["state"] == "FAIL"
    assert "hapax-review-receipts-export" in r["detail"]


def test_stale_feed_fails(tmp_path):
    env = _scaffold(tmp_path)
    p = Path(env["HAPAX_RECHECK_COORD_DIR"]) / "sdlc-vocab.json"
    old = time.time() - 10 * 600
    os.utime(p, (old, old))
    mod = _load(env)
    res = _by_check(_run(mod))
    assert res["feed-fresh:sdlc-vocab"]["state"] == "FAIL"


def test_malformed_vocab_json_fails(tmp_path):
    env = _scaffold(tmp_path)
    (Path(env["HAPAX_RECHECK_COORD_DIR"]) / "sdlc-vocab.json").write_text("{not json")
    mod = _load(env)
    res = _by_check(_run(mod))
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
    res = _by_check(_run(mod))
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
    res = _by_check(_run(mod))
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
            body = (
                b'<!doctype HTML><HTML style="background: hsl(210 20% 8%);">'
                b'<script src="/js/boot.js"></script>'
                b"<body>HAPAX COORDINATION connecting to the yard</body></HTML>"
            )
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
            "stations": ["S0", "S5", "S6", "S7"],
            "items": [
                {"id": "t1", "station": "S5", "review": "blocked"},
                {"id": "t2", "station": "unstaged", "review": None},
            ],
        },
    )
    try:
        env["HAPAX_RECHECK_COORD_URL"] = f"http://127.0.0.1:{srv.server_address[1]}"
        mod = _load(env)
        res = _by_check(_run(mod))
        assert res["coord-live"]["state"] == "OK"
        assert res["coord-provenance"]["state"] == "OK"
        assert res["coord-boot-shell"]["state"] == "OK"
        assert res["coord-last-good-paint"]["state"] == "OK"
        assert res["coord-yard-status-strip"]["state"] == "OK"
        assert res["coord-rails-consumed"]["state"] == "OK"
        assert res["coord-verdicts-visible"]["state"] == "OK"
        assert "1 review receipt(s)" in res["coord-verdicts-visible"]["detail"]
        assert "1 blocked" in res["coord-verdicts-visible"]["detail"]
    finally:
        srv.shutdown()


def test_verdict_feed_matches_but_missing_rendered_text_fails_visibility(tmp_path):
    env = _scaffold(tmp_path)
    srv = _stub_server(
        version={"deployed_sha": "abc123def4567890"},
        rails={
            "feed_state": "live",
            "stations": ["S0", "S5", "S6", "S7"],
            "items": [{"id": "t1", "station": "S5", "review": "blocked"}],
        },
    )

    def no_rendered_verdicts(_url):
        return mod.BrowserSurfaceWitness(
            ok=True,
            detail="test browser witness without rendered verdict text",
            elapsed=0.35,
            last_good_seen=True,
            last_good_elapsed=0.050,
            last_good_visible_seen=True,
            last_good_content_seen=True,
            last_good_rect_area=4096,
            fresh_yard_seen=True,
            fresh_yard_elapsed=0.250,
            fresh_yard_visible_seen=True,
            fresh_yard_rect_area=4096,
            fresh_yard_chip_count=3,
            fresh_yard_text="YARD abc123def vocab 13 blocked",
            dashboard_seen=True,
            dark_paint_seen=True,
            white_paint_seen=False,
            rendered_blocked_seen=False,
            rendered_receipt_seen=False,
            rendered_review_seen=False,
        )

    try:
        env["HAPAX_RECHECK_COORD_URL"] = f"http://127.0.0.1:{srv.server_address[1]}"
        mod = _load(env)
        res = _by_check(_run(mod, browser_probe=no_rendered_verdicts))
        assert res["coord-verdicts-visible"]["state"] == "FAIL"
        assert "rendered_blocked=False" in res["coord-verdicts-visible"]["detail"]
        assert "rendered_receipt=False" in res["coord-verdicts-visible"]["detail"]
        assert "rendered_review=False" in res["coord-verdicts-visible"]["detail"]
    finally:
        srv.shutdown()


def test_yard_summary_alone_does_not_satisfy_verdict_visibility(tmp_path):
    env = _scaffold(tmp_path)
    receipts = {
        "schema": 1,
        "dossiers": [{"task_id": "t1", "verdict": "blocked"}],
        "acceptances": [{"task_id": "t1", "verdict": "accepted"}],
    }
    (Path(env["HAPAX_RECHECK_COORD_DIR"]) / "review-receipts.json").write_text(json.dumps(receipts))
    srv = _stub_server(
        version={"deployed_sha": "abc123def4567890"},
        rails={
            "feed_state": "live",
            "stations": ["S0", "S5", "S6", "S7"],
            "items": [{"id": "t1", "station": "S5", "review": "blocked", "receipt": "accepted"}],
        },
    )

    def yard_summary_only(_url):
        return mod.BrowserSurfaceWitness(
            ok=True,
            detail="test browser witness with only yard verdict summary",
            elapsed=0.35,
            last_good_seen=True,
            last_good_elapsed=0.050,
            last_good_visible_seen=True,
            last_good_content_seen=True,
            last_good_rect_area=4096,
            fresh_yard_seen=True,
            fresh_yard_elapsed=0.250,
            fresh_yard_visible_seen=True,
            fresh_yard_rect_area=4096,
            fresh_yard_chip_count=3,
            fresh_yard_text="YARD abc123def vocab 13 blocked 6 receipts",
            dashboard_seen=True,
            dark_paint_seen=True,
            white_paint_seen=False,
            pixel_sample_count=64,
            pixel_white_ratio=0.0,
            pixel_nonwhite_ratio=1.0,
            rendered_blocked_seen=True,
            rendered_receipt_seen=True,
            rendered_review_seen=True,
            rendered_verdict_detail="YARD abc123def vocab 13 blocked 6 receipts",
            rendered_verdict_text="YARD abc123def vocab 13 blocked 6 receipts",
        )

    try:
        env["HAPAX_RECHECK_COORD_URL"] = f"http://127.0.0.1:{srv.server_address[1]}"
        mod = _load(env)
        res = _by_check(_run(mod, browser_probe=yard_summary_only))
        assert res["coord-verdicts-visible"]["state"] == "FAIL"
        assert "rendered_blocked=True" in res["coord-verdicts-visible"]["detail"]
        assert "rendered_receipt=True" in res["coord-verdicts-visible"]["detail"]
        assert "rendered_blocked_ids=[]" in res["coord-verdicts-visible"]["detail"]
        assert "rendered_receipt_ids=[]" in res["coord-verdicts-visible"]["detail"]
    finally:
        srv.shutdown()


def test_white_pixel_sample_fails_last_good_paint(tmp_path):
    env = _scaffold(tmp_path)
    srv = _stub_server(
        version={"deployed_sha": "abc123def4567890"},
        rails={
            "feed_state": "live",
            "stations": ["S0", "S5", "S6", "S7"],
            "items": [{"id": "t1", "station": "S5", "review": "blocked"}],
        },
    )

    def white_pixels(_url):
        return mod.BrowserSurfaceWitness(
            ok=True,
            detail="test browser witness with white screenshot pixels",
            elapsed=0.35,
            last_good_seen=True,
            last_good_elapsed=0.050,
            last_good_visible_seen=True,
            last_good_content_seen=True,
            last_good_rect_area=4096,
            fresh_yard_seen=True,
            fresh_yard_elapsed=0.250,
            fresh_yard_visible_seen=True,
            fresh_yard_rect_area=4096,
            fresh_yard_chip_count=3,
            fresh_yard_text="YARD abc123def vocab 13 blocked",
            dashboard_seen=True,
            dark_paint_seen=True,
            white_paint_seen=True,
            pixel_sample_count=64,
            pixel_white_ratio=1.0,
            pixel_nonwhite_ratio=0.0,
            rendered_blocked_seen=True,
            rendered_receipt_seen=True,
            rendered_review_seen=True,
            rendered_verdict_text="t1 review blocked",
        )

    try:
        env["HAPAX_RECHECK_COORD_URL"] = f"http://127.0.0.1:{srv.server_address[1]}"
        mod = _load(env)
        res = _by_check(_run(mod, browser_probe=white_pixels))
        assert res["coord-last-good-paint"]["state"] == "FAIL"
        assert "pixel_white_ratio=1.0" in res["coord-last-good-paint"]["detail"]
    finally:
        srv.shutdown()


def test_mostly_white_pixel_sample_fails_last_good_paint(tmp_path):
    env = _scaffold(tmp_path)
    srv = _stub_server(
        version={"deployed_sha": "abc123def4567890"},
        rails={
            "feed_state": "live",
            "stations": ["S0", "S5", "S6", "S7"],
            "items": [{"id": "t1", "station": "S5", "review": "blocked"}],
        },
    )

    def mostly_white_pixels(_url):
        return mod.BrowserSurfaceWitness(
            ok=True,
            detail="test browser witness with mostly white screenshot pixels",
            elapsed=0.35,
            last_good_seen=True,
            last_good_elapsed=0.050,
            last_good_visible_seen=True,
            last_good_content_seen=True,
            last_good_rect_area=4096,
            fresh_yard_seen=True,
            fresh_yard_elapsed=0.250,
            fresh_yard_visible_seen=True,
            fresh_yard_rect_area=4096,
            fresh_yard_chip_count=3,
            fresh_yard_text="YARD abc123def vocab 13 blocked",
            dashboard_seen=True,
            dark_paint_seen=True,
            white_paint_seen=False,
            pixel_sample_count=64,
            pixel_white_ratio=0.89,
            pixel_nonwhite_ratio=0.11,
            rendered_blocked_seen=True,
            rendered_receipt_seen=True,
            rendered_review_seen=True,
            rendered_verdict_text="t1 review blocked",
        )

    try:
        env["HAPAX_RECHECK_COORD_URL"] = f"http://127.0.0.1:{srv.server_address[1]}"
        mod = _load(env)
        res = _by_check(_run(mod, browser_probe=mostly_white_pixels))
        assert res["coord-last-good-paint"]["state"] == "FAIL"
        assert "pixel_white_ratio=0.89" in res["coord-last-good-paint"]["detail"]
    finally:
        srv.shutdown()


def test_rails_stations_must_match_exported_vocab(tmp_path):
    env = _scaffold(tmp_path)
    srv = _stub_server(
        version={"deployed_sha": "abc123def4567890"},
        rails={
            "feed_state": "live",
            "stations": ["S0", "HARDCODED", "S6", "S7"],
            "items": [{"id": "t1", "station": "S5", "review": "blocked"}],
        },
    )
    try:
        env["HAPAX_RECHECK_COORD_URL"] = f"http://127.0.0.1:{srv.server_address[1]}"
        mod = _load(env)
        res = _by_check(_run(mod))
        assert res["coord-rails-consumed"]["state"] == "FAIL"
        assert "outside_vocab=['HARDCODED']" in res["coord-rails-consumed"]["detail"]
    finally:
        srv.shutdown()


def test_rails_stations_must_match_exported_ladder_not_valid_subset(tmp_path):
    env = _scaffold(tmp_path)
    srv = _stub_server(
        version={"deployed_sha": "abc123def4567890"},
        rails={
            "feed_state": "live",
            "stations": ["S0", "S5"],
            "items": [{"id": "t1", "station": "S5", "review": "blocked"}],
        },
    )
    try:
        env["HAPAX_RECHECK_COORD_URL"] = f"http://127.0.0.1:{srv.server_address[1]}"
        mod = _load(env)
        res = _by_check(_run(mod))
        assert res["coord-rails-consumed"]["state"] == "FAIL"
        assert "station_order_matches=False" in res["coord-rails-consumed"]["detail"]
    finally:
        srv.shutdown()


def test_rails_item_station_must_match_event_log_via_exported_vocab(tmp_path):
    env = _scaffold(tmp_path)
    srv = _stub_server(
        version={"deployed_sha": "abc123def4567890"},
        rails={
            "feed_state": "live",
            "stations": ["S0", "S5", "S6", "S7"],
            "items": [{"id": "t1", "station": "S0", "review": "blocked"}],
        },
    )
    try:
        env["HAPAX_RECHECK_COORD_URL"] = f"http://127.0.0.1:{srv.server_address[1]}"
        mod = _load(env)
        res = _by_check(_run(mod))
        assert res["coord-rails-consumed"]["state"] == "FAIL"
        assert "station_mismatches=['t1:S0!=S5']" in res["coord-rails-consumed"]["detail"]
    finally:
        srv.shutdown()


def test_rails_unknown_stage_passthrough_warns_not_fails(tmp_path):
    env = _scaffold(tmp_path)
    coord = Path(env["HAPAX_RECHECK_COORD_DIR"])
    vocab = {
        "ladder_tokens": ["S0", "S5", "S6", "S7"],
        "pseudo_stages": [],
        "observed_stages": {"WEIRD_STAGE": {"count": 1, "ladder_token": "unknown"}},
    }
    (coord / "sdlc-vocab.json").write_text(json.dumps(vocab))
    (coord / "sdlc-events.jsonl").write_text(
        json.dumps(
            {
                "event_id": "evt-weird-stage",
                "item_id": "t1",
                "kind": "stage",
                "stage_to": "WEIRD_STAGE",
                "ts": "2026-06-12T00:00:00+00:00",
            }
        )
        + "\n"
    )
    srv = _stub_server(
        version={"deployed_sha": "abc123def4567890"},
        rails={
            "feed_state": "live",
            "stations": ["S0", "S5", "S6", "S7"],
            "items": [{"id": "t1", "station": "unstaged", "review": "blocked"}],
        },
    )
    try:
        env["HAPAX_RECHECK_COORD_URL"] = f"http://127.0.0.1:{srv.server_address[1]}"
        mod = _load(env)
        res = _by_check(_run(mod))
        assert res["vocab-parity"]["state"] == "WARN"
        assert res["coord-rails-consumed"]["state"] == "WARN"
        assert "honest unknown passthrough" in res["coord-rails-consumed"]["detail"]
    finally:
        srv.shutdown()


def test_verdictless_rails_fails_visibility(tmp_path):
    env = _scaffold(tmp_path)
    srv = _stub_server(
        version={"deployed_sha": "abc123def4567890"},
        rails={
            "feed_state": "live",
            "stations": ["S0", "S5", "S6", "S7"],
            "items": [{"id": "t1", "station": "S5"}],
        },
    )
    try:
        env["HAPAX_RECHECK_COORD_URL"] = f"http://127.0.0.1:{srv.server_address[1]}"
        mod = _load(env)
        res = _by_check(_run(mod))
        assert res["coord-verdicts-visible"]["state"] == "FAIL"
        assert "review_mismatches=['t1:None!=blocked']" in res["coord-verdicts-visible"]["detail"]
    finally:
        srv.shutdown()


def test_rails_verdicts_must_match_review_receipts_feed(tmp_path):
    env = _scaffold(tmp_path)
    srv = _stub_server(
        version={"deployed_sha": "abc123def4567890"},
        rails={
            "feed_state": "live",
            "stations": ["S0", "S5", "S6", "S7"],
            "items": [{"id": "t1", "station": "S5", "review": "quorum-accept"}],
        },
    )
    try:
        env["HAPAX_RECHECK_COORD_URL"] = f"http://127.0.0.1:{srv.server_address[1]}"
        mod = _load(env)
        res = _by_check(_run(mod))
        assert res["coord-verdicts-visible"]["state"] == "FAIL"
        assert (
            "review_mismatches=['t1:quorum-accept!=blocked']"
            in res["coord-verdicts-visible"]["detail"]
        )
    finally:
        srv.shutdown()


def test_hardcoded_block_without_review_receipts_feed_fails_visibility(tmp_path):
    env = _scaffold(tmp_path)
    (Path(env["HAPAX_RECHECK_COORD_DIR"]) / "review-receipts.json").write_text("{}")
    srv = _stub_server(
        version={"deployed_sha": "abc123def4567890"},
        rails={
            "feed_state": "live",
            "stations": ["S0", "S5", "S6", "S7"],
            "items": [{"id": "t1", "station": "S5", "review": "blocked"}],
        },
    )
    try:
        env["HAPAX_RECHECK_COORD_URL"] = f"http://127.0.0.1:{srv.server_address[1]}"
        mod = _load(env)
        res = _by_check(_run(mod))
        assert res["coord-verdicts-visible"]["state"] == "FAIL"
        assert "no parseable dossier verdict rows" in res["coord-verdicts-visible"]["detail"]
    finally:
        srv.shutdown()


def test_rails_receipts_must_match_acceptance_feed(tmp_path):
    env = _scaffold(tmp_path)
    receipts = {
        "schema": 1,
        "dossiers": [{"task_id": "t1", "verdict": "blocked"}],
        "acceptances": [{"task_id": "t1", "verdict": "accepted"}],
    }
    (Path(env["HAPAX_RECHECK_COORD_DIR"]) / "review-receipts.json").write_text(json.dumps(receipts))
    srv = _stub_server(
        version={"deployed_sha": "abc123def4567890"},
        rails={
            "feed_state": "live",
            "stations": ["S0", "S5", "S6", "S7"],
            "items": [{"id": "t1", "station": "S5", "review": "blocked", "receipt": None}],
        },
    )
    try:
        env["HAPAX_RECHECK_COORD_URL"] = f"http://127.0.0.1:{srv.server_address[1]}"
        mod = _load(env)
        res = _by_check(_run(mod))
        assert res["coord-verdicts-visible"]["state"] == "FAIL"
        assert "receipt_mismatches=['t1:None!=accepted']" in res["coord-verdicts-visible"]["detail"]
    finally:
        srv.shutdown()


def test_unreachable_coord_fails_with_next_action(tmp_path):
    mod = _load(_scaffold(tmp_path))  # COORD_URL points at port 1
    res = _by_check(_run(mod))
    assert res["coord-live"]["state"] == "FAIL"
    assert "next:" in res["coord-live"]["detail"]


def test_provenance_mismatch_fails(tmp_path):
    env = _scaffold(tmp_path)
    Path(env["HAPAX_RECHECK_DEPLOY_SHA"]).write_text("ffff999988887777\n")
    srv = _stub_server(
        version={"deployed_sha": "abc123def4567890"},
        rails={
            "feed_state": "live",
            "stations": ["S0", "S5", "S6", "S7"],
            "items": [{"id": "t1", "station": "S5"}],
        },
    )
    try:
        env["HAPAX_RECHECK_COORD_URL"] = f"http://127.0.0.1:{srv.server_address[1]}"
        mod = _load(env)
        res = _by_check(_run(mod))
        assert res["coord-provenance"]["state"] == "FAIL"
    finally:
        srv.shutdown()


def test_empty_deployed_sha_fails_provenance(tmp_path):
    env = _scaffold(tmp_path)
    Path(env["HAPAX_RECHECK_DEPLOY_SHA"]).write_text("")
    srv = _stub_server(
        version={"deployed_sha": "abc123def4567890"},
        rails={
            "feed_state": "live",
            "stations": ["S0", "S5", "S6", "S7"],
            "items": [{"id": "t1", "station": "S5"}],
        },
    )
    try:
        env["HAPAX_RECHECK_COORD_URL"] = f"http://127.0.0.1:{srv.server_address[1]}"
        mod = _load(env)
        res = _by_check(_run(mod))
        assert res["coord-provenance"]["state"] == "FAIL"
        assert "empty" in res["coord-provenance"]["detail"]
    finally:
        srv.shutdown()


def test_fresh_dashboard_paint_does_not_satisfy_last_good_check_without_replay(tmp_path):
    mod = _load(_scaffold(tmp_path))

    def no_replay(_url):
        return mod.BrowserSurfaceWitness(
            ok=True,
            detail="test browser witness",
            elapsed=0.3,
            last_good_seen=False,
            last_good_elapsed=None,
            fresh_yard_seen=True,
            fresh_yard_elapsed=0.2,
            fresh_yard_visible_seen=True,
            fresh_yard_rect_area=4096,
            fresh_yard_chip_count=2,
            fresh_yard_text="YARD abc123def vocab 13 blocked",
            dashboard_seen=True,
            dark_paint_seen=True,
            white_paint_seen=False,
            pixel_sample_count=64,
            pixel_white_ratio=0.0,
            pixel_nonwhite_ratio=1.0,
        )

    res = _by_check(_run(mod, browser_probe=no_replay))
    assert res["coord-last-good-paint"]["state"] == "FAIL"
    assert "last_good_seen=False" in res["coord-last-good-paint"]["detail"]
    assert "paint_source=missing" in res["coord-last-good-paint"]["detail"]
    assert res["coord-yard-status-strip"]["state"] == "OK"


def test_no_replay_or_fresh_dashboard_paint_fails_last_good_check(tmp_path):
    mod = _load(_scaffold(tmp_path))

    def no_surface(_url):
        return mod.BrowserSurfaceWitness(
            ok=True,
            detail="test browser witness",
            elapsed=0.3,
            last_good_seen=False,
            last_good_elapsed=None,
            fresh_yard_seen=False,
            fresh_yard_elapsed=None,
            fresh_yard_chip_count=0,
            dashboard_seen=False,
            dark_paint_seen=True,
            white_paint_seen=False,
        )

    res = _by_check(_run(mod, browser_probe=no_surface))
    assert res["coord-last-good-paint"]["state"] == "FAIL"
    assert "paint_source=missing" in res["coord-last-good-paint"]["detail"]


def test_hidden_or_empty_replay_marker_fails_last_good_paint(tmp_path):
    mod = _load(_scaffold(tmp_path))

    for visible, content, area, expected_detail in (
        (False, True, 0, "last_good_visible=False"),
        (True, False, 4096, "last_good_content=False"),
    ):

        def unpainted_replay(_url, *, visible=visible, content=content, area=area):
            return mod.BrowserSurfaceWitness(
                ok=True,
                detail="test browser witness",
                elapsed=0.3,
                last_good_seen=True,
                last_good_elapsed=0.05,
                last_good_visible_seen=visible,
                last_good_content_seen=content,
                last_good_rect_area=area,
                fresh_yard_seen=True,
                fresh_yard_elapsed=0.2,
                fresh_yard_visible_seen=True,
                fresh_yard_rect_area=4096,
                fresh_yard_chip_count=2,
                fresh_yard_text="YARD abc123def vocab 13 blocked",
                dashboard_seen=True,
                dark_paint_seen=True,
                white_paint_seen=False,
                pixel_sample_count=64,
                pixel_white_ratio=0.0,
                pixel_nonwhite_ratio=1.0,
            )

        res = _by_check(_run(mod, browser_probe=unpainted_replay))
        assert res["coord-last-good-paint"]["state"] == "FAIL"
        assert expected_detail in res["coord-last-good-paint"]["detail"]


def test_white_first_paint_fails_last_good_even_with_replay(tmp_path):
    mod = _load(_scaffold(tmp_path))

    def white_paint(_url):
        return mod.BrowserSurfaceWitness(
            ok=True,
            detail="test browser witness",
            elapsed=0.3,
            last_good_seen=True,
            last_good_elapsed=0.05,
            last_good_visible_seen=True,
            last_good_content_seen=True,
            last_good_rect_area=4096,
            fresh_yard_seen=True,
            fresh_yard_elapsed=0.2,
            fresh_yard_visible_seen=True,
            fresh_yard_rect_area=4096,
            fresh_yard_chip_count=2,
            fresh_yard_text="YARD abc123def vocab 13 blocked",
            dashboard_seen=True,
            dark_paint_seen=True,
            white_paint_seen=True,
            pixel_sample_count=64,
            pixel_white_ratio=1.0,
            pixel_nonwhite_ratio=0.0,
        )

    res = _by_check(_run(mod, browser_probe=white_paint))
    assert res["coord-last-good-paint"]["state"] == "FAIL"
    assert "white_paint=True" in res["coord-last-good-paint"]["detail"]


def test_stale_replay_yard_does_not_satisfy_fresh_strip(tmp_path):
    mod = _load(_scaffold(tmp_path))

    def stale_only(_url):
        return mod.BrowserSurfaceWitness(
            ok=True,
            detail="test browser witness",
            elapsed=0.3,
            last_good_seen=True,
            last_good_elapsed=0.05,
            last_good_visible_seen=True,
            last_good_content_seen=True,
            last_good_rect_area=4096,
            fresh_yard_seen=False,
            fresh_yard_elapsed=None,
            fresh_yard_chip_count=0,
            dashboard_seen=True,
            dark_paint_seen=True,
            white_paint_seen=False,
            pixel_sample_count=64,
            pixel_white_ratio=0.0,
            pixel_nonwhite_ratio=1.0,
        )

    res = _by_check(_run(mod, browser_probe=stale_only))
    assert res["coord-last-good-paint"]["state"] == "OK"
    assert res["coord-yard-status-strip"]["state"] == "FAIL"


def test_hidden_or_offscreen_yard_status_fails_strip(tmp_path):
    mod = _load(_scaffold(tmp_path))

    for detail, area in (
        ("test browser witness with hidden yard strip", 0),
        ("test browser witness with offscreen yard strip", 4096),
    ):

        def hidden_yard(_url, *, detail=detail, area=area):
            return mod.BrowserSurfaceWitness(
                ok=True,
                detail=detail,
                elapsed=0.3,
                last_good_seen=True,
                last_good_elapsed=0.05,
                last_good_visible_seen=True,
                last_good_content_seen=True,
                last_good_rect_area=4096,
                fresh_yard_seen=True,
                fresh_yard_elapsed=0.2,
                fresh_yard_visible_seen=False,
                fresh_yard_rect_area=area,
                fresh_yard_chip_count=2,
                fresh_yard_text="YARD abc123def vocab 13 blocked",
                dashboard_seen=True,
                dark_paint_seen=True,
                white_paint_seen=False,
                pixel_sample_count=64,
                pixel_white_ratio=0.0,
                pixel_nonwhite_ratio=1.0,
            )

        res = _by_check(_run(mod, browser_probe=hidden_yard))
        assert res["coord-last-good-paint"]["state"] == "OK"
        assert res["coord-yard-status-strip"]["state"] == "FAIL"
        assert "fresh_yard_visible=False" in res["coord-yard-status-strip"]["detail"]
        assert f"fresh_yard_rect_area={area}" in res["coord-yard-status-strip"]["detail"]


def test_fresh_yard_status_without_deployed_sha_fails_strip(tmp_path):
    env = _scaffold(tmp_path)
    srv = _stub_server(
        version={"deployed_sha": "abc123def4567890"},
        rails={
            "feed_state": "live",
            "stations": ["S0", "S5", "S6", "S7"],
            "items": [{"id": "t1", "station": "S5", "review": "blocked"}],
        },
    )

    def missing_sha(_url):
        return mod.BrowserSurfaceWitness(
            ok=True,
            detail="test browser witness",
            elapsed=0.3,
            last_good_seen=True,
            last_good_elapsed=0.05,
            last_good_visible_seen=True,
            last_good_content_seen=True,
            last_good_rect_area=4096,
            fresh_yard_seen=True,
            fresh_yard_elapsed=0.2,
            fresh_yard_visible_seen=True,
            fresh_yard_rect_area=4096,
            fresh_yard_chip_count=2,
            fresh_yard_text="YARD vocab 13 blocked",
            dashboard_seen=True,
            dark_paint_seen=True,
            white_paint_seen=False,
            pixel_sample_count=64,
            pixel_white_ratio=0.0,
            pixel_nonwhite_ratio=1.0,
        )

    try:
        env["HAPAX_RECHECK_COORD_URL"] = f"http://127.0.0.1:{srv.server_address[1]}"
        mod = _load(env)
        res = _by_check(_run(mod, browser_probe=missing_sha))
        assert res["coord-last-good-paint"]["state"] == "OK"
        assert res["coord-yard-status-strip"]["state"] == "FAIL"
        assert "yard_sha_prefix=abc123def" in res["coord-yard-status-strip"]["detail"]
        assert "yard_sha_visible=False" in res["coord-yard-status-strip"]["detail"]
        assert "yard_text='YARD vocab 13 blocked'" in res["coord-yard-status-strip"]["detail"]
    finally:
        srv.shutdown()


def test_slow_live_yard_status_fails_strip(tmp_path):
    mod = _load(_scaffold(tmp_path))

    def slow_yard(_url):
        return mod.BrowserSurfaceWitness(
            ok=True,
            detail="test browser witness",
            elapsed=2.8,
            last_good_seen=True,
            last_good_elapsed=0.05,
            last_good_visible_seen=True,
            last_good_content_seen=True,
            last_good_rect_area=4096,
            fresh_yard_seen=True,
            fresh_yard_elapsed=2.2,
            fresh_yard_visible_seen=True,
            fresh_yard_rect_area=4096,
            fresh_yard_chip_count=2,
            fresh_yard_text="YARD abc123def vocab 13 blocked",
            dashboard_seen=True,
            dark_paint_seen=True,
            white_paint_seen=False,
            pixel_sample_count=64,
            pixel_white_ratio=0.0,
            pixel_nonwhite_ratio=1.0,
        )

    res = _by_check(_run(mod, browser_probe=slow_yard))
    assert res["coord-yard-status-strip"]["state"] == "FAIL"
    assert "fresh_yard_elapsed=2.200s" in res["coord-yard-status-strip"]["detail"]


def test_published_event_feed_uses_rails_timer_budget(tmp_path):
    env = _scaffold(tmp_path)
    p = Path(env["HAPAX_RECHECK_COORD_DIR"]) / "sdlc-events.jsonl"
    old = time.time() - 120
    os.utime(p, (old, old))
    mod = _load(env)
    res = _by_check(_run(mod))
    assert res["feed-fresh:sdlc-events"]["state"] == "FAIL"
    assert "budget=90s" in res["feed-fresh:sdlc-events"]["detail"]


def test_missing_published_event_feed_fails_even_if_shadow_exists(tmp_path):
    env = _scaffold(tmp_path)
    coord = Path(env["HAPAX_RECHECK_COORD_DIR"])
    (coord / "sdlc-events.jsonl").unlink()
    (coord / "sdlc-events.shadow.json").write_text("{}")
    mod = _load(env)
    res = _by_check(_run(mod))
    assert res["feed-fresh:sdlc-events"]["state"] == "FAIL"
    assert "sdlc-events.jsonl" in res["feed-fresh:sdlc-events"]["detail"]
