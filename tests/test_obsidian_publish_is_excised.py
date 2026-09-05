"""Prevent the withdrawn Publish exposure from returning to current source."""

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WITHDRAWAL_RUNBOOK = Path("docs/runbooks/obsidian-publish-sync.md")
PUBLISH_TOKENS = (b"publish.obsidian.md", b"hapax-obsidian-publish-sync")
WITHDRAWN_SECTION_START = b"## Withdrawn 2026-09-05\n"
WITHDRAWN_SECTION_END = b"<!-- end: withdrawn 2026-09-05 -->\n"


def current_text_outside_withdrawn_section(content: bytes) -> bytes:
    """Return the runbook with exactly one bounded withdrawn section removed.

    The exemption is bounded on both sides: it starts at the dated ``##`` heading and
    ends at the explicit end marker. Both must occur exactly once, in that order, and no
    other ``##`` heading may sit inside the bounded section (the historical procedure is
    nested as ``###`` and deeper). Anything outside the bounds is current text and is
    checked like every other file.
    """
    assert content.count(WITHDRAWN_SECTION_START) == 1, "one dated withdrawn heading"
    assert content.count(WITHDRAWN_SECTION_END) == 1, "one withdrawn end marker"
    start = content.index(WITHDRAWN_SECTION_START)
    end = content.index(WITHDRAWN_SECTION_END)
    assert start < end, "the end marker must follow the withdrawn heading"
    inside = content[start + len(WITHDRAWN_SECTION_START) : end]
    assert not re.search(rb"(?m)^## ", inside), "no second top-level section inside the bounds"
    return content[:start] + content[end + len(WITHDRAWN_SECTION_END) :]


def active_obsidian_publish_surfaces(registry: dict) -> list[str]:
    """Every registry surface that is about Obsidian Publish and is not withdrawn."""
    active = []
    for surface in registry.get("surfaces", []):
        blob = yaml.safe_dump(surface).lower()
        is_obsidian = (
            surface.get("surface_type") == "obsidian_publish"
            or "publish.obsidian.md" in blob
            or "obsidian" in str(surface.get("surface_id", "")).lower()
        )
        if is_obsidian and not surface.get("withdrawn"):
            active.append(str(surface.get("surface_id")))
    return active


def test_current_sources_have_no_publish_references() -> None:
    violations = []
    for directory in ("scripts", "systemd", "config", "agents", "hooks", "docs/runbooks"):
        for path in sorted((REPO_ROOT / directory).rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            content = path.read_bytes()
            relative = path.relative_to(REPO_ROOT)
            if relative == WITHDRAWAL_RUNBOOK:
                content = current_text_outside_withdrawn_section(content)
            for token in PUBLISH_TOKENS:
                if token in content.lower():
                    violations.append(f"{relative}: {token.decode()}")
    assert not violations, "\n".join(violations)


def test_withdrawal_exemption_is_bounded_on_both_sides() -> None:
    bounded = (
        b"# Runbook\n\n"
        + WITHDRAWN_SECTION_START
        + b"\nhistory: https://publish.obsidian.md/x\n\n### Historical procedure\n\n"
        + b"hapax-obsidian-publish-sync\n"
        + WITHDRAWN_SECTION_END
        + b"\n## Current\n\nnothing here\n"
    )
    outside = current_text_outside_withdrawn_section(bounded)
    assert not any(token in outside.lower() for token in PUBLISH_TOKENS)
    assert b"## Current" in outside

    trailing = bounded + b"\nsee publish.obsidian.md/x again\n"
    assert b"publish.obsidian.md" in current_text_outside_withdrawn_section(trailing).lower()

    unbounded = bounded.replace(WITHDRAWN_SECTION_END, b"")
    try:
        current_text_outside_withdrawn_section(unbounded)
    except AssertionError as refused:
        assert "end marker" in str(refused)
    else:
        raise AssertionError("a withdrawn section without its end marker must be refused")

    nested_second_section = bounded.replace(b"### Historical procedure", b"## Historical procedure")
    try:
        current_text_outside_withdrawn_section(nested_second_section)
    except AssertionError as refused:
        assert "top-level" in str(refused)
    else:
        raise AssertionError("a second top-level section inside the bounds must be refused")


def test_registry_has_no_active_obsidian_publish_surface() -> None:
    registry = yaml.safe_load(
        (REPO_ROOT / "docs/repo-pres/public-surface-registry.yaml").read_text(encoding="utf-8")
    )
    assert active_obsidian_publish_surfaces(registry) == []


def test_second_active_obsidian_entry_is_detected() -> None:
    registry = {
        "surfaces": [
            {
                "surface_id": "obsidian.publish.home",
                "surface_type": "obsidian_publish",
                "withdrawn": "2026-09-05",
            },
            {"surface_id": "obsidian.publish.research", "surface_type": "obsidian_publish"},
            {"surface_id": "weblog.home", "surface_type": "weblog", "path_globs": ["docs/x.md"]},
            {
                "surface_id": "notes.mirror",
                "surface_type": "static",
                "source_refs": ["https://publish.obsidian.md/y"],
            },
        ]
    }
    assert active_obsidian_publish_surfaces(registry) == [
        "obsidian.publish.research",
        "notes.mirror",
    ]


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
