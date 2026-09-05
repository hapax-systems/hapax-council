"""Prevent the withdrawn Publish exposure from returning to current source.

The scan covers the enumerated runtime/current surfaces (``scripts``, ``systemd``,
``config``, ``agents``, ``hooks`` and ``docs/runbooks``); historical documents elsewhere
are retained and not scanned.
"""

import re
from pathlib import Path

import pytest
import yaml

# The Markdown parser is the locked markdown-it-py (uv.lock, via rich/textual); a missing
# parser fails this module loudly at import, it is never skipped around.
from markdown_it import MarkdownIt

REPO_ROOT = Path(__file__).resolve().parents[1]
SCANNED_DIRECTORIES = ("scripts", "systemd", "config", "agents", "hooks", "docs/runbooks")
WITHDRAWAL_RUNBOOK = Path("docs/runbooks/obsidian-publish-sync.md")
PUBLISH_TOKENS = (b"publish.obsidian.md", b"hapax-obsidian-publish-sync")
WITHDRAWN_SECTION_START = b"## Withdrawn 2026-09-05\n"
WITHDRAWN_SECTION_END = b"<!-- end: withdrawn 2026-09-05 -->\n"


def current_text_outside_withdrawn_section(content: bytes) -> bytes:
    """Return the runbook with exactly one bounded withdrawn section removed.

    The exemption is bounded on both sides: it starts at the dated ``##`` heading and
    ends at the explicit end marker. Both must occur exactly once, in that order, and no
    heading of rank one or two may sit inside the bounded section (the historical
    procedure is nested as ``###`` and deeper). Headings are what the locked CommonMark
    parser says they are (ATX at any permitted indentation, Setext underlines); code,
    fenced or indented, is not a heading. Anything outside the bounds is current text
    and is checked like every other file.
    """
    assert content.count(WITHDRAWN_SECTION_START) == 1, "one dated withdrawn heading"
    assert content.count(WITHDRAWN_SECTION_END) == 1, "one withdrawn end marker"
    start = content.index(WITHDRAWN_SECTION_START)
    end = content.index(WITHDRAWN_SECTION_END)
    assert start < end, "the end marker must follow the withdrawn heading"
    inside = content[start + len(WITHDRAWN_SECTION_START) : end]
    # A heading at the withdrawn section's rank or higher (rank one or two) would start
    # current text inside the bounds and hide it from the scan; both ranks are refused.
    ranks = heading_ranks(inside)
    assert not any(rank <= 2 for rank in ranks), "no heading of rank one or two inside the bounds"
    return content[:start] + content[end + len(WITHDRAWN_SECTION_END) :]


def heading_ranks(markdown: bytes) -> list[int]:
    """Heading ranks in document order, from the locked CommonMark parser's tokens."""
    tokens = MarkdownIt("commonmark").parse(markdown.decode("utf-8", errors="replace"))
    return [int(token.tag[1]) for token in tokens if token.type == "heading_open"]


def current_publish_destinations(content: bytes) -> list[tuple[int, str]]:
    """Resolve the whole document, exempting destinations rendered wholly inside the bounds.

    Reference definitions are document-wide, so their location cannot determine
    whether a rendered link or image is current. Inline maps are zero-based,
    end-exclusive line spans; diagnostics name the first current line, one-based.
    """
    start = content.index(WITHDRAWN_SECTION_START)
    end = content.index(WITHDRAWN_SECTION_END) + len(WITHDRAWN_SECTION_END)
    start_line = content.count(b"\n", 0, start)
    end_line = content.count(b"\n", 0, end)
    violations = []
    tokens = MarkdownIt("commonmark").parse(content.decode("utf-8", errors="replace"))
    for inline in tokens:
        if inline.type != "inline" or inline.map is None:
            continue
        first, last = inline.map
        if start_line <= first and last <= end_line:
            continue
        current_line = first if first < start_line else max(first, end_line)
        for child in inline.children or []:
            attribute = {"link_open": "href", "image": "src"}.get(child.type)
            if attribute is None:
                continue
            destination = child.attrGet(attribute)
            if destination and any(
                token in destination.encode("utf-8").lower() for token in PUBLISH_TOKENS
            ):
                violations.append((current_line + 1, destination))
    return violations


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
    for directory in SCANNED_DIRECTORIES:
        for path in sorted((REPO_ROOT / directory).rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            content = path.read_bytes()
            relative = path.relative_to(REPO_ROOT)
            if (
                path.suffix.lower() == ".md"
                and WITHDRAWN_SECTION_START in content
                and WITHDRAWN_SECTION_END in content
            ):
                violations.extend(
                    f"{relative}:{line}: {destination}"
                    for line, destination in current_publish_destinations(content)
                )
            if relative == WITHDRAWAL_RUNBOOK:
                content = current_text_outside_withdrawn_section(content)
            for token in PUBLISH_TOKENS:
                if token in content.lower():
                    violations.append(f"{relative}: {token.decode()}")
    assert not violations, "\n".join(violations)


@pytest.fixture
def scan_runbook(monkeypatch: pytest.MonkeyPatch):
    """Exercise both repository scans with an in-memory replacement for the runbook."""
    original_read_bytes = Path.read_bytes

    def scan(content: bytes, relative: Path = WITHDRAWAL_RUNBOOK) -> None:
        def read_bytes(path: Path) -> bytes:
            if path == REPO_ROOT / relative:
                return content
            return original_read_bytes(path)

        monkeypatch.setattr(Path, "read_bytes", read_bytes)
        test_current_sources_have_no_publish_references()

    return scan


def test_current_reference_resolves_definition_inside_withdrawn_bounds(scan_runbook) -> None:
    bounded = (
        b"Current vault: [vault][retired-site]\n\n"
        + WITHDRAWN_SECTION_START
        + b"\n[retired-site]: https://publish.obsidian.md/hapax\n\n"
        + WITHDRAWN_SECTION_END
    )
    outside = current_text_outside_withdrawn_section(bounded)
    assert not any(token in outside.lower() for token in PUBLISH_TOKENS)
    with pytest.raises(
        AssertionError,
        match=re.escape(f"{WITHDRAWAL_RUNBOOK}:1: https://publish.obsidian.md/hapax"),
    ):
        scan_runbook(bounded)


def test_reference_used_only_inside_withdrawn_bounds_stays_exempt(scan_runbook) -> None:
    bounded = (
        b"Current vault: private\n\n"
        + WITHDRAWN_SECTION_START
        + b"\nHistorical vault: [vault][retired-site]\n\n"
        + b"[retired-site]: https://publish.obsidian.md/hapax\n\n"
        + WITHDRAWN_SECTION_END
    )
    scan_runbook(bounded)


def test_current_reference_without_a_definition_stays_literal(scan_runbook) -> None:
    bounded = (
        b"Current vault: [vault][retired-site]\n\n"
        + WITHDRAWN_SECTION_START
        + b"\nHistorical vault: private\n\n"
        + WITHDRAWN_SECTION_END
    )
    scan_runbook(bounded)


def test_current_reference_label_case_folding_is_refused(scan_runbook) -> None:
    bounded = (
        b"Current vault: [vault][Retired-Site]\n\n"
        + WITHDRAWN_SECTION_START
        + b"\n[retired-site]: https://publish.obsidian.md/hapax\n\n"
        + WITHDRAWN_SECTION_END
    )
    with pytest.raises(
        AssertionError,
        match=re.escape(f"{WITHDRAWAL_RUNBOOK}:1: https://publish.obsidian.md/hapax"),
    ):
        scan_runbook(bounded)


def test_current_image_reference_to_withdrawn_definition_is_refused(scan_runbook) -> None:
    bounded = (
        b"Current vault: ![vault][retired-site]\n\n"
        + WITHDRAWN_SECTION_START
        + b"\n[retired-site]: https://publish.obsidian.md/hapax\n\n"
        + WITHDRAWN_SECTION_END
    )
    with pytest.raises(
        AssertionError,
        match=re.escape(f"{WITHDRAWAL_RUNBOOK}:1: https://publish.obsidian.md/hapax"),
    ):
        scan_runbook(bounded)


def test_current_reference_definition_is_refused_by_both_scans(scan_runbook) -> None:
    bounded = (
        b"Current vault: [vault][retired-site]\n\n"
        + b"[retired-site]: https://publish.obsidian.md/hapax\n\n"
        + WITHDRAWN_SECTION_START
        + b"\nHistorical vault: private\n\n"
        + WITHDRAWN_SECTION_END
    )
    with pytest.raises(AssertionError) as refused:
        scan_runbook(bounded)
    assert [line.strip() for line in str(refused.value).splitlines()[:2]] == [
        f"{WITHDRAWAL_RUNBOOK}:1: https://publish.obsidian.md/hapax",
        f"{WITHDRAWAL_RUNBOOK}: publish.obsidian.md",
    ]


def test_current_reference_after_withdrawn_end_is_refused(scan_runbook) -> None:
    bounded = (
        WITHDRAWN_SECTION_START
        + b"\n[retired-site]: https://publish.obsidian.md/hapax\n\n"
        + WITHDRAWN_SECTION_END
        + b"Current vault: [vault][retired-site]\n"
    )
    with pytest.raises(
        AssertionError,
        match=re.escape(f"{WITHDRAWAL_RUNBOOK}:6: https://publish.obsidian.md/hapax"),
    ):
        scan_runbook(bounded)


def test_other_scanned_markdown_with_bounds_runs_both_scans(scan_runbook) -> None:
    relative = next(
        path.relative_to(REPO_ROOT)
        for path in sorted((REPO_ROOT / "docs/runbooks").glob("*.md"))
        if path.is_file() and not path.is_symlink() and path != REPO_ROOT / WITHDRAWAL_RUNBOOK
    )
    bounded = (
        b"Current vault: [vault][retired-site]\n\n"
        + WITHDRAWN_SECTION_START
        + b"\n[retired-site]: https://publish.obsidian.md/hapax\n\n"
        + WITHDRAWN_SECTION_END
    )
    with pytest.raises(AssertionError) as refused:
        scan_runbook(bounded, relative)
    assert [line.strip() for line in str(refused.value).splitlines()[:2]] == [
        f"{relative}:1: https://publish.obsidian.md/hapax",
        f"{relative}: publish.obsidian.md",
    ]


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

    for hidden_heading in (b"## Historical procedure", b"# Current"):
        hidden = bounded.replace(b"### Historical procedure", hidden_heading)
        try:
            current_text_outside_withdrawn_section(hidden)
        except AssertionError as refused:
            assert "rank one or two" in str(refused)
        else:
            raise AssertionError(f"{hidden_heading!r} inside the bounds must be refused")

    rank_one_current = (
        WITHDRAWN_SECTION_START
        + b"history\n# Current\nhttps://publish.obsidian.md/current\n"
        + WITHDRAWN_SECTION_END
    )
    try:
        current_text_outside_withdrawn_section(rank_one_current)
    except AssertionError as refused:
        assert "rank one or two" in str(refused)
    else:
        raise AssertionError("a rank-one heading inside the bounds must be refused")

    shell_comment_in_fence = (
        WITHDRAWN_SECTION_START
        + b"history\n```bash\n# expect 404\ncurl https://publish.obsidian.md/x\n```\n"
        + WITHDRAWN_SECTION_END
    )
    assert current_text_outside_withdrawn_section(shell_comment_in_fence) == b""

    heading_after_fence = shell_comment_in_fence.replace(
        b"```\n" + WITHDRAWN_SECTION_END,
        b"```\n# Current\nhttps://publish.obsidian.md/y\n" + WITHDRAWN_SECTION_END,
    )
    try:
        current_text_outside_withdrawn_section(heading_after_fence)
    except AssertionError as refused:
        assert "rank one or two" in str(refused)
    else:
        raise AssertionError("a rank-one heading outside a fence inside the bounds must be refused")


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


@pytest.mark.parametrize(
    "hidden_heading",
    [
        pytest.param(b" ## Current\n", id="indented-atx-h2"),
        pytest.param(b"   # Current\n", id="indented-atx-h1"),
        pytest.param(b"Current\n-------\n", id="setext-h2"),
        pytest.param(b"Current\n=======\n", id="setext-h1"),
    ],
)
def test_headings_the_parser_recognizes_are_refused_inside_the_bounds(
    hidden_heading: bytes,
) -> None:
    """Root's reproduction: indented ATX and Setext headings parse as h1/h2 and must not hide text."""
    bounded = (
        WITHDRAWN_SECTION_START
        + b"history\n"
        + hidden_heading
        + b"https://publish.obsidian.md/current\n"
        + WITHDRAWN_SECTION_END
    )
    assert [rank for rank in heading_ranks(bounded[len(WITHDRAWN_SECTION_START) :]) if rank <= 2]
    try:
        current_text_outside_withdrawn_section(bounded)
    except AssertionError as refused:
        assert "rank one or two" in str(refused)
    else:
        raise AssertionError(f"{hidden_heading!r} inside the bounds must be refused")


@pytest.mark.parametrize(
    "not_a_heading",
    [
        pytest.param(b"```bash\n# expect 404\n```\n", id="fenced-shell-comment"),
        pytest.param(b"    # indented code, not a heading\n", id="indented-code"),
        pytest.param(b"### Historical procedure\n", id="rank-three"),
        pytest.param(b"#hashtag without a space is text\n", id="no-space-after-hash"),
    ],
)
def test_code_and_deeper_headings_stay_exempt_inside_the_bounds(not_a_heading: bytes) -> None:
    bounded = WITHDRAWN_SECTION_START + b"history\n" + not_a_heading + WITHDRAWN_SECTION_END
    assert not [
        rank for rank in heading_ranks(bounded[len(WITHDRAWN_SECTION_START) :]) if rank <= 2
    ]
    assert current_text_outside_withdrawn_section(bounded) == b""
