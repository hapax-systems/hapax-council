"""Prevent the withdrawn Publish exposure from returning to current source."""

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WITHDRAWAL_RUNBOOK = Path("docs/runbooks/obsidian-publish-sync.md")


def test_current_sources_have_no_publish_references() -> None:
    violations = []
    for directory in ("scripts", "systemd", "config", "agents", "hooks", "docs/runbooks"):
        for path in sorted((REPO_ROOT / directory).rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            content = path.read_bytes()
            relative = path.relative_to(REPO_ROOT)
            if relative == WITHDRAWAL_RUNBOOK:
                # Only the dated withdrawal section (including its nested historical
                # procedure) is exempt; a later current section is still checked.
                content = re.sub(rb"(?ms)^## Withdrawn 2026-09-05\n.*?(?=^## |\Z)", b"", content)
            for token in (b"publish.obsidian.md", b"hapax-obsidian-publish-sync"):
                if token in content.lower():
                    violations.append(f"{relative}: {token.decode()}")
    assert not violations, "\n".join(violations)


def test_preset_has_no_obsidian_publish_line() -> None:
    preset = (REPO_ROOT / "systemd/user-preset.d/hapax.preset").read_text(encoding="utf-8")
    assert not re.search(r"obsidian.?publish", preset, re.IGNORECASE)


def test_landing_has_no_publish_link() -> None:
    landing = (REPO_ROOT / "agents/omg_web_builder/static/index.html").read_text(encoding="utf-8")
    assert "publish.obsidian.md" not in landing.lower()


def test_registry_retains_only_a_withdrawn_obsidian_surface() -> None:
    registry = yaml.safe_load(
        (REPO_ROOT / "docs/repo-pres/public-surface-registry.yaml").read_text(encoding="utf-8")
    )
    surfaces = [s for s in registry["surfaces"] if s["surface_id"] == "obsidian.publish.home"]
    assert len(surfaces) == 1
    surface = surfaces[0]
    assert str(surface.get("withdrawn")) == "2026-09-05"
    assert surface.get("withdrawal_reason") == (
        "get rid of obsidian publish exposure: we need another way to make a curated research "
        "basis available. that was an early way to do so but too much exposure\n"
        "we can deal with the research curation issue later, for now, just excise obsid pub"
    )
    assert surface.get("withdrawal_source") == (
        "Operator direction, verbatim, relayed by root at 2026-09-05T20:03:49Z "
        "(bus message filename label 20260905T2013Z, not the delivery time)"
    )
    assert surface.get("withdrawal_record") == WITHDRAWAL_RUNBOOK.as_posix()
    assert surface.get("path_globs") == [WITHDRAWAL_RUNBOOK.as_posix()]
