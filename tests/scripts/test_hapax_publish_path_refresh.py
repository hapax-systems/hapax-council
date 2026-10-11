"""scripts/hapax-publish-path-refresh: publish-path services follow the activation.

Source activation moves the activation link to each new main head, but a long-running service keeps the
release it started on. On 2026-10-10 the publish orchestrator ran the release before #5095 until it was
restarted by hand. These tests pin when the refresh restarts a unit and, more importantly, when it must not.
"""

from __future__ import annotations

import configparser
import importlib.machinery
import importlib.util
import subprocess
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-publish-path-refresh"
UNITS_DIR = REPO_ROOT / "systemd" / "units"
OLD = "a" * 40
NEW = "b" * 40


def _load() -> types.ModuleType:
    loader = importlib.machinery.SourceFileLoader(
        "hapax_publish_path_refresh_under_test", str(SCRIPT)
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


class _Host:
    """A fake host: releases, an activation link, /proc cwd links, systemctl and git."""

    def __init__(
        self,
        tmp: Path,
        *,
        running: str | None,
        diff: str = "",
        diff_rc: int = 0,
        settle_polls: int | None = 0,
    ) -> None:
        self.releases = tmp / "releases"
        for sha in (OLD, NEW):
            (self.releases / sha).mkdir(parents=True)
        self.activation = tmp / "worktree"
        self.activation.symlink_to(self.releases / NEW)
        self.proc = tmp / "proc"
        self.inbox = tmp / "inbox"
        self.inbox.mkdir()
        self.pid = 100
        self.diff, self.diff_rc = diff, diff_rc
        self.restart_rc = 0
        self.show_rc = 0
        self.calls: list[list[str]] = []
        self.settle_polls = settle_polls
        self.now = 0.0
        self.reads = None
        if running is not None:
            self._point(self.pid, running)

    def _point(self, pid: int, sha: str) -> None:
        (self.proc / str(pid)).mkdir(parents=True, exist_ok=True)
        cwd = self.proc / str(pid) / "cwd"
        if cwd.is_symlink():
            cwd.unlink()
        cwd.symlink_to(self.releases / sha)

    def run(self, argv):  # noqa: ANN001 — the runner signature the script injects
        argv = list(argv)
        self.calls.append(argv)
        if argv[:3] == ["systemctl", "--user", "show"]:
            if self.reads is not None:
                self.reads += 1
                if self.settle_polls is not None and self.reads > self.settle_polls:
                    self._point(self.pid, NEW)
            pid = self.pid if (self.proc / str(self.pid)).exists() else 0
            stdout = f"{pid}\n" if self.show_rc == 0 else ""
            return subprocess.CompletedProcess(argv, self.show_rc, stdout=stdout, stderr="")
        if argv[:3] == ["systemctl", "--user", "restart"]:
            if self.restart_rc == 0:
                # A Type=simple restart returns once the child is forked, before it chdirs.
                self.pid += 1
                (self.proc / str(self.pid)).mkdir(parents=True, exist_ok=True)
                self.reads = 0
            return subprocess.CompletedProcess(argv, self.restart_rc, stdout="", stderr="")
        if argv[0] == "git":
            return subprocess.CompletedProcess(argv, self.diff_rc, stdout=self.diff, stderr="")
        raise AssertionError(f"unexpected command {argv}")

    def restarts(self) -> list[list[str]]:
        return [c for c in self.calls if c[:3] == ["systemctl", "--user", "restart"]]

    def doze(self, seconds: float) -> None:
        self.now += seconds

    def refresh(self, module: types.ModuleType, unit):  # noqa: ANN001
        return module.refresh(
            unit,
            run=self.run,
            activation=self.activation,
            inbox=self.inbox,
            proc_root=self.proc,
            clock=lambda: self.now,
            sleep=self.doze,
        )


@pytest.fixture
def module() -> types.ModuleType:
    return _load()


def _unit(module: types.ModuleType, name: str):  # noqa: ANN202
    return next(u for u in module.UNITS if u.name == name)


ORCH = "hapax-publish-orchestrator.service"
PRODUCER = "hapax-weblog-publish-public-event-producer.service"
BLUESKY = "hapax-bluesky-post.service"
MASTODON = "hapax-mastodon-post.service"
POSTER_WATCH = ("agents/cross_surface/", "agents/publication_bus/", "shared/")


def test_a_watched_change_restarts_the_unit_onto_the_activated_release(module, tmp_path) -> None:
    host = _Host(tmp_path, running=OLD, diff="agents/omg_weblog_publisher/publisher.py\n")

    result = host.refresh(module, _unit(module, ORCH))

    assert result["action"] == "restarted"
    assert result["verified"] is True
    assert result["running"] == NEW
    assert host.restarts() == [["systemctl", "--user", "restart", ORCH]]
    diff_call = next(c for c in host.calls if c[0] == "git")
    separator = diff_call.index("--")
    assert diff_call[separator - 2 : separator] == [OLD, NEW]
    assert diff_call[separator + 1 :] == list(_unit(module, ORCH).watch)


def test_an_unwatched_change_restarts_nothing(module, tmp_path) -> None:
    host = _Host(tmp_path, running=OLD, diff="")

    result = host.refresh(module, _unit(module, ORCH))

    assert result["action"] == "unchanged"
    assert host.restarts() == []


def test_the_same_release_restarts_nothing_and_skips_the_diff(module, tmp_path) -> None:
    host = _Host(tmp_path, running=NEW, diff="shared/x.py\n")

    result = host.refresh(module, _unit(module, ORCH))

    assert result["action"] == "current"
    assert host.restarts() == []
    assert not any(c[0] == "git" for c in host.calls)


def test_a_busy_inbox_defers_the_orchestrator(module, tmp_path) -> None:
    host = _Host(tmp_path, running=OLD, diff="shared/x.py\n")
    (host.inbox / "pending-artifact.json").write_text("{}", encoding="utf-8")

    result = host.refresh(module, _unit(module, ORCH))

    assert result["action"] == "deferred"
    assert host.restarts() == []


def test_the_producer_does_not_wait_on_the_publish_inbox(module, tmp_path) -> None:
    host = _Host(tmp_path, running=OLD, diff="shared/x.py\n")
    (host.inbox / "pending-artifact.json").write_text("{}", encoding="utf-8")

    result = host.refresh(module, _unit(module, PRODUCER))

    assert result["action"] == "restarted"
    assert host.restarts() == [["systemctl", "--user", "restart", PRODUCER]]


def test_a_unit_that_is_not_running_is_not_started(module, tmp_path) -> None:
    host = _Host(tmp_path, running=None, diff="shared/x.py\n")

    result = host.refresh(module, _unit(module, ORCH))

    assert result["action"] == "not_running"
    assert host.restarts() == []
    assert module.exit_code([result]) == 0


def test_a_broken_activation_link_is_unknown_and_fails_the_run(module, tmp_path) -> None:
    host = _Host(tmp_path, running=OLD, diff="shared/x.py\n")
    host.activation.unlink()
    host.activation.symlink_to(tmp_path / "releases" / "missing-release")

    result = host.refresh(module, _unit(module, ORCH))

    assert result["action"] == "unknown"
    assert result["next_action"]
    assert host.restarts() == []
    assert module.exit_code([result]) == 1


def test_systemctl_without_an_answer_is_unknown(module, tmp_path) -> None:
    host = _Host(tmp_path, running=OLD, diff="shared/x.py\n")
    host.show_rc = 1

    result = host.refresh(module, _unit(module, ORCH))

    assert result["action"] == "unknown"
    assert host.restarts() == []


def test_an_unreadable_inbox_defers_the_orchestrator(module, tmp_path, monkeypatch) -> None:
    host = _Host(tmp_path, running=OLD, diff="shared/x.py\n")

    def unreadable(self, pattern):  # noqa: ANN001, ANN202
        raise PermissionError(f"cannot list {self}")

    monkeypatch.setattr(Path, "glob", unreadable)

    result = host.refresh(module, _unit(module, ORCH))

    assert result["action"] == "deferred"
    assert host.restarts() == []


@pytest.mark.parametrize(
    ("result", "code"),
    [
        ({"action": "current"}, 0),
        ({"action": "unchanged"}, 0),
        ({"action": "deferred"}, 0),
        ({"action": "not_running"}, 0),
        ({"action": "restarted", "verified": True}, 0),
        ({"action": "restarted", "verified": False}, 1),
        ({"action": "restart_failed"}, 1),
        ({"action": "unknown"}, 1),
    ],
)
def test_the_run_fails_only_when_a_person_is_needed(module, result, code) -> None:
    assert module.exit_code([{"unit": "u", **result}]) == code


def test_main_returns_the_exit_code_of_its_results(module, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        module, "refresh", lambda unit, **_: {"unit": unit.name, "action": "unknown"}
    )

    assert module.main() == 1
    assert '"action": "unknown"' in capsys.readouterr().out


def test_a_failed_diff_restarts_nothing(module, tmp_path) -> None:
    host = _Host(tmp_path, running=OLD, diff="", diff_rc=128)

    result = host.refresh(module, _unit(module, ORCH))

    assert result["action"] == "unknown"
    assert result["next_action"]
    assert host.restarts() == []


def test_a_cwd_outside_the_releases_is_unknown(module, tmp_path) -> None:
    host = _Host(tmp_path, running=None)
    # A sha-shaped directory that is not under releases/ is still not a release.
    elsewhere = tmp_path / "elsewhere" / OLD
    elsewhere.mkdir(parents=True)
    (host.proc / str(host.pid)).mkdir(parents=True)
    (host.proc / str(host.pid) / "cwd").symlink_to(elsewhere)
    host.diff = "shared/x.py\n"

    result = host.refresh(module, _unit(module, ORCH))

    assert result["action"] == "unknown"
    assert host.restarts() == []


def test_a_restart_that_leaves_the_old_release_is_not_verified(module, tmp_path) -> None:
    host = _Host(tmp_path, running=OLD, diff="shared/x.py\n")
    original_point = host._point
    host._point = lambda pid, _sha: original_point(
        pid, OLD
    )  # the new process starts on the old release

    result = host.refresh(module, _unit(module, ORCH))

    assert result["action"] == "restarted"
    assert result["verified"] is False
    assert result["running"] == OLD


def test_a_release_that_appears_late_is_verified(module, tmp_path) -> None:
    """A Type=simple child enters its release after restart returns; the poll waits for it."""
    host = _Host(tmp_path, running=OLD, diff="shared/x.py\n", settle_polls=2)

    result = host.refresh(module, _unit(module, ORCH))

    assert result["action"] == "restarted"
    assert result["verified"] is True
    assert result["running"] == NEW
    assert host.restarts() == [["systemctl", "--user", "restart", ORCH]]


def test_a_release_that_never_appears_stays_unverified(module, tmp_path) -> None:
    host = _Host(tmp_path, running=OLD, diff="shared/x.py\n", settle_polls=None)

    result = host.refresh(module, _unit(module, ORCH))

    assert result["action"] == "restarted"
    assert result["verified"] is False
    assert result["running"] is None
    assert module.exit_code([result]) == 1


def test_a_failed_restart_is_reported(module, tmp_path) -> None:
    host = _Host(tmp_path, running=OLD, diff="shared/x.py\n")
    host.restart_rc = 1

    result = host.refresh(module, _unit(module, ORCH))

    assert result["action"] == "restart_failed"
    assert result["next_action"]


def test_only_the_publish_path_units_and_the_posters_are_ever_restarted(module) -> None:
    assert {u.name for u in module.UNITS} == {ORCH, PRODUCER, BLUESKY, MASTODON}
    assert [u.name for u in module.UNITS if u.needs_empty_inbox] == [ORCH]
    for unit in module.UNITS:
        assert not any("audio" in path for path in unit.watch)


@pytest.mark.parametrize("poster", [BLUESKY, MASTODON])
def test_each_poster_watches_its_code_and_shared(module, poster) -> None:
    assert _unit(module, poster).watch == POSTER_WATCH


@pytest.mark.parametrize(
    "changed",
    [
        "agents/publication_bus/bluesky_publisher.py\n",
        "agents/cross_surface/bluesky_post.py\n",
        "shared/research_vehicle_public_event.py\n",
    ],
)
def test_a_running_poster_follows_a_change_to_its_code(module, tmp_path, changed) -> None:
    host = _Host(tmp_path, running=OLD, diff=changed)
    # A poster tails a cursor, so a pending publish inbox is no reason to wait.
    (host.inbox / "pending-artifact.json").write_text("{}", encoding="utf-8")

    result = host.refresh(module, _unit(module, BLUESKY))

    assert result["action"] == "restarted"
    assert result["verified"] is True
    assert host.restarts() == [["systemctl", "--user", "restart", BLUESKY]]


def test_a_stopped_poster_is_never_started(module, tmp_path) -> None:
    """The Mastodon poster is disabled until its account is labelled; the refresh keeps it off."""
    host = _Host(tmp_path, running=None, diff="agents/cross_surface/mastodon_post.py\n")

    result = host.refresh(module, _unit(module, MASTODON))

    assert result["action"] == "not_running"
    assert host.restarts() == []


def _load_unit(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str
    parser.read(path, encoding="utf-8")
    return parser


def test_the_service_runs_the_script_from_the_activation() -> None:
    unit = _load_unit(UNITS_DIR / "hapax-publish-path-refresh.service")
    assert unit["Service"]["Type"] == "oneshot"
    exec_start = unit["Service"]["ExecStart"]
    assert "source-activation/worktree/scripts/hapax-publish-path-refresh" in exec_start


def test_the_timer_is_marked_for_auto_enable_and_installs() -> None:
    path = UNITS_DIR / "hapax-publish-path-refresh.timer"
    assert path.read_text(encoding="utf-8").startswith("# Hapax-Auto-Enable: true\n")
    unit = _load_unit(path)
    assert unit["Install"]["WantedBy"] == "timers.target"
    assert unit["Timer"]["Unit"] == "hapax-publish-path-refresh.service"
