"""Static checks on the hapax-post-merge-deploy path/service unit pair.

These units close the gap surfaced by the
``deploy-pipeline-canonical-worktree-isolation`` audit: 25 systemd units
canonical-but-not-installed because nothing fired
``scripts/hapax-post-merge-deploy`` after merges. The .path unit watches
the canonical main ref; the .service unit re-resolves the latest SHA and
hands it to the deploy script.

The tests verify the static contract of the unit files (they are inert
text the operator manually enables), not their runtime behaviour, which
is exercised end-to-end by hapax-post-merge-deploy's own test suite.
"""

from __future__ import annotations

import configparser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS_DIR = REPO_ROOT / "systemd" / "units"
PATH_UNIT = UNITS_DIR / "hapax-post-merge-deploy.path"
SERVICE_UNIT = UNITS_DIR / "hapax-post-merge-deploy.service"
DEPLOY_SCRIPT = REPO_ROOT / "scripts" / "hapax-post-merge-deploy"


def _load_unit(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    # systemd unit files are case-sensitive.
    parser.optionxform = str  # type: ignore[assignment]
    parser.read(path, encoding="utf-8")
    return parser


def test_path_unit_exists() -> None:
    assert PATH_UNIT.is_file(), f"missing {PATH_UNIT}"


def test_service_unit_exists() -> None:
    assert SERVICE_UNIT.is_file(), f"missing {SERVICE_UNIT}"


def test_path_unit_watches_canonical_main_ref() -> None:
    """PathChanged must point at the shared local main ref under .git/refs/heads."""
    parser = _load_unit(PATH_UNIT)
    assert parser.has_section("Path"), "[Path] section missing"
    watched = parser.get("Path", "PathChanged")
    # Must be the canonical main ref file. Git worktrees share refs/heads/,
    # so this single path covers both the canonical worktree and the
    # rebuild-service dedicated worktree (alpha/rebuild-service-dedicated-worktree
    # follow-up). Any deviation breaks that invariant.
    assert watched.endswith("/.git/refs/heads/main"), (
        f"PathChanged must end with /.git/refs/heads/main, got: {watched!r}"
    )
    # And specifically anchored to the canonical hapax-council clone.
    assert "hapax-council" in watched, (
        f"PathChanged must reference the hapax-council repo, got: {watched!r}"
    )


def test_path_unit_targets_service() -> None:
    parser = _load_unit(PATH_UNIT)
    assert parser.get("Path", "Unit") == "hapax-post-merge-deploy.service"


def test_path_unit_install_target() -> None:
    parser = _load_unit(PATH_UNIT)
    assert parser.has_section("Install"), "[Install] section missing"
    assert parser.get("Install", "WantedBy") == "default.target"


def test_service_unit_invokes_deploy_script_with_resolved_sha() -> None:
    """ExecStart must resolve the live main SHA and hand it to the deploy script."""
    parser = _load_unit(SERVICE_UNIT)
    assert parser.has_section("Service"), "[Service] section missing"
    exec_start = parser.get("Service", "ExecStart")

    # Must call the deploy script under scripts/.
    assert "scripts/hapax-post-merge-deploy" in exec_start, (
        f"ExecStart must invoke scripts/hapax-post-merge-deploy, got: {exec_start!r}"
    )
    # Must compute the SHA at run time, not bake one in. The .path unit
    # fires AFTER refs/heads/main has advanced, so a static SHA would be
    # wrong on every fire.
    assert "rev-parse" in exec_start, (
        f"ExecStart must compute SHA via git rev-parse, got: {exec_start!r}"
    )
    assert "main" in exec_start, f"ExecStart must reference 'main' branch, got: {exec_start!r}"
    # And the resolved SHA must be quoted/expanded into the script call.
    assert '"$sha"' in exec_start or "${sha}" in exec_start or "$sha" in exec_start, (
        "ExecStart must pass the resolved SHA to the deploy script"
    )


def test_service_unit_is_oneshot() -> None:
    parser = _load_unit(SERVICE_UNIT)
    assert parser.get("Service", "Type") == "oneshot"


def test_service_unit_has_runaway_fire_guards() -> None:
    """StartLimitIntervalSec + StartLimitBurst MUST be on the [Unit] section.

    The .path unit's PathChanged trigger only fires on refs/heads/main mtime
    changes, which the deploy script itself cannot cause. But a future change
    could regress that — the StartLimit pair is the belt-and-braces guard
    that prevents a runaway-fire loop from doing real damage.

    Critical: these directives belong on [Unit], NOT [Service]. systemd
    silently ignores them when placed under [Service] (waybar hardening
    bug pinned 2026-05-02), defeating the entire guard.
    """
    parser = _load_unit(SERVICE_UNIT)
    interval = parser.get("Unit", "StartLimitIntervalSec", fallback=None)
    burst = parser.get("Unit", "StartLimitBurst", fallback=None)
    assert interval is not None, "StartLimitIntervalSec MUST be set on the [Unit] section"
    assert burst is not None, "StartLimitBurst MUST be set on the [Unit] section"
    # Regression: must NOT also be set on [Service] (silently ignored by systemd).
    assert parser.get("Service", "StartLimitIntervalSec", fallback=None) is None, (
        "StartLimitIntervalSec is silently ignored under [Service]; move it to [Unit]"
    )
    assert parser.get("Service", "StartLimitBurst", fallback=None) is None, (
        "StartLimitBurst is silently ignored under [Service]; move it to [Unit]"
    )
    # Sanity: the cap should be small. >10 fires/min defeats the point.
    assert int(burst) <= 10, f"StartLimitBurst too lax: {burst}"
    assert int(interval) >= 30, f"StartLimitIntervalSec too short to be meaningful: {interval}"


def test_service_unit_streams_to_journal() -> None:
    parser = _load_unit(SERVICE_UNIT)
    assert parser.get("Service", "StandardOutput") == "journal"
    assert parser.get("Service", "StandardError") == "journal"
    assert parser.get("Service", "SyslogIdentifier") == "hapax-post-merge-deploy"


def test_service_unit_has_failure_notifier() -> None:
    parser = _load_unit(SERVICE_UNIT)
    assert parser.has_section("Unit"), "[Unit] section missing"
    on_failure = parser.get("Unit", "OnFailure", fallback="")
    assert "notify-failure@" in on_failure, (
        f"OnFailure must wire notify-failure@%n.service, got: {on_failure!r}"
    )


def test_deploy_script_does_not_modify_main_ref() -> None:
    """The deploy script MUST NOT write to .git/refs/heads/main.

    If it did, the path unit would fire itself in a loop. This is a
    structural guard: scan the script source for any write to the watched
    ref. The script is allowed to read from git (cat-file, show, diff) but
    not push/update-ref/write into .git/refs.
    """
    source = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    forbidden_patterns = [
        "git update-ref",
        "git push",
        ".git/refs/heads/main",
        "refs/heads/main",
    ]
    for pattern in forbidden_patterns:
        assert pattern not in source, (
            f"hapax-post-merge-deploy must not touch the watched ref "
            f"(forbidden pattern {pattern!r} found in script source) — "
            f"this would create a path-unit fire loop."
        )
