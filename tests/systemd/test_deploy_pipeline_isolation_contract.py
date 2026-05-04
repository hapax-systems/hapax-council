"""Contract tests for deploy-pipeline canonical worktree isolation."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REBUILD_UNIT = REPO_ROOT / "systemd" / "units" / "hapax-rebuild-services.service"
POST_MERGE_PATH = REPO_ROOT / "systemd" / "units" / "hapax-post-merge-deploy.path"
POST_MERGE_SERVICE = REPO_ROOT / "systemd" / "units" / "hapax-post-merge-deploy.service"

DEDICATED_REPO = "%h/.cache/hapax/rebuild/worktree"
CANONICAL_REPO = "%h/projects/hapax-council"


def _active_execstarts() -> list[str]:
    lines = []
    for raw in REBUILD_UNIT.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if stripped.startswith("ExecStart="):
            lines.append(stripped)
    return lines


def test_council_rebuild_entries_use_dedicated_rebuild_worktree() -> None:
    """Council deploy entries must not depend on the operator worktree branch."""
    offenders = [
        line
        for line in _active_execstarts()
        if "scripts/rebuild-service.sh" in line and f"--repo {CANONICAL_REPO}" in line
    ]
    assert offenders == [], (
        "hapax-council rebuild entries must use the dedicated rebuild worktree, "
        f"not the canonical operator checkout: {offenders}"
    )

    council_entries = [
        line
        for line in _active_execstarts()
        if "scripts/rebuild-service.sh" in line
        and "hapax-officium" not in line
        and "hapax-mcp" not in line
    ]
    assert council_entries, "expected at least one council rebuild entry"
    assert all(f"--repo {DEDICATED_REPO}" in line for line in council_entries)
    assert all(f"{DEDICATED_REPO}/scripts/rebuild-service.sh" in line for line in council_entries)


def test_audio_touching_rebuild_entries_are_present_but_operator_gated() -> None:
    """The two audit-identified audio services are documented but not auto-enabled."""
    text = REBUILD_UNIT.read_text(encoding="utf-8")
    assert "Operator-gated audio-touching services" in text
    assert "operator must explicitly" in text

    for service in ("hapax-broadcast-orchestrator.service", "hapax-audio-ducker.service"):
        matching = [line for line in text.splitlines() if service in line and "ExecStart=" in line]
        assert matching, f"missing operator-gated entry for {service}"
        assert all(line.lstrip().startswith("# ExecStart=") for line in matching), (
            f"{service} must remain commented until the operator greenlights audio auto-restarts"
        )
        assert all(f"--repo {DEDICATED_REPO}" in line for line in matching)


def test_post_merge_deploy_units_are_in_canonical_systemd_units_directory() -> None:
    """The deploy trigger itself must be deployable by hapax-post-merge-deploy."""
    assert POST_MERGE_PATH.is_file()
    assert POST_MERGE_SERVICE.is_file()
    assert POST_MERGE_PATH.parent == REPO_ROOT / "systemd" / "units"
    assert POST_MERGE_SERVICE.parent == REPO_ROOT / "systemd" / "units"
