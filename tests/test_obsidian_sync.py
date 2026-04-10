"""Tests for obsidian_sync — schemas, filtering, parsing, profiler facts."""

from __future__ import annotations


def test_vault_note_defaults():
    from agents.obsidian_sync import VaultNote

    n = VaultNote(
        relative_path="20-personal/some-note.md",
        title="Some Note",
        folder="20-personal",
        content_hash="abc123",
        size=100,
        mtime=1709000000.0,
    )
    assert n.tags == []
    assert n.links == []
    assert n.has_frontmatter is False


def test_obsidian_sync_state_empty():
    from agents.obsidian_sync import ObsidianSyncState

    s = ObsidianSyncState()
    assert s.notes == {}
    assert s.last_sync == 0.0
    assert s.stats == {}


def test_should_include_path():
    from agents.obsidian_sync import _should_include

    # Included directories (kebab-case INCLUDE_DIRS)
    assert _should_include("00-inbox/quick-note.md") is True
    assert _should_include("10-meta/fileclass.md") is True
    assert _should_include("20-personal/journal.md") is True
    assert _should_include("20-projects/my-project.md") is True
    assert _should_include("30-areas/some-area.md") is True
    assert _should_include("40-calendar/schedule.md") is True
    assert _should_include("50-resources/tool.md") is True

    # Root-level .md files always included
    assert _should_include("readme.md") is True
    assert _should_include("index.md") is True

    # Excluded directories
    assert _should_include("90-attachments/image.md") is False
    assert _should_include("50-templates/template.md") is False
    assert _should_include("Templates/daily.md") is False
    assert _should_include("60-archive/old-note.md") is False
    assert _should_include("60 Archives/old.md") is False
    assert _should_include(".obsidian/plugins/config.md") is False
    assert _should_include("smart-chats/chat.md") is False
    assert _should_include("textgenerator/output.md") is False
    assert _should_include("configs/settings.md") is False
    assert _should_include("docs/help.md") is False
    assert _should_include("scripts/run.md") is False
    assert _should_include("research/paper.md") is False

    # Non-.md files excluded
    assert _should_include("20-personal/image.png") is False

    # Unknown directories excluded
    assert _should_include("unknown-folder/note.md") is False


def test_extract_obsidian_metadata():
    from agents.obsidian_sync import _extract_metadata

    # Note with frontmatter, tags, and wikilinks
    content = """---
title: My Note
tags: [project, idea]
---

# My Great Note

This is a note about #coding and #python.
It links to [[Another Note]] and [[Some Concept|alias]].
Also has a #nested/tag here.
"""
    meta = _extract_metadata(content, "20-personal/my-note.md")
    assert meta["has_frontmatter"] is True
    assert "project" in meta["tags"]
    assert "idea" in meta["tags"]
    assert "coding" in meta["tags"]
    assert "python" in meta["tags"]
    assert "nested/tag" in meta["tags"]
    assert "Another Note" in meta["links"]
    assert "Some Concept" in meta["links"]
    assert meta["title"] == "My Great Note"

    # Note without frontmatter
    content_no_fm = """# Simple Note

Just some text with a [[Link]].
"""
    meta2 = _extract_metadata(content_no_fm, "00-inbox/simple.md")
    assert meta2["has_frontmatter"] is False
    assert "Link" in meta2["links"]
    assert meta2["title"] == "Simple Note"

    # Note with no H1 — title from filename
    content_no_h1 = "Just some text."
    meta3 = _extract_metadata(content_no_h1, "20-personal/my-file-name.md")
    assert meta3["title"] == "my-file-name"

    # Frontmatter tags as string (space or comma separated)
    content_str_tags = """---
tags: alpha, beta
---

Some content.
"""
    meta4 = _extract_metadata(content_str_tags, "note.md")
    assert "alpha" in meta4["tags"]
    assert "beta" in meta4["tags"]


def test_format_note_markdown():
    from agents.obsidian_sync import VaultNote, _format_note_markdown

    note = VaultNote(
        relative_path="30 Areas/33 Permanent notes/zettelkasten.md",
        title="Zettelkasten Method",
        folder="33 Permanent notes",
        content_hash="abc123",
        size=500,
        mtime=1709000000.0,
        has_frontmatter=True,
        tags=["pkm", "notes"],
        links=["Slip Box", "Niklas Luhmann"],
    )
    original_content = """---
title: Zettelkasten Method
tags: [pkm, notes]
---

# Zettelkasten Method

The Zettelkasten is a method of note-taking.
See also [[Slip Box]] and [[Niklas Luhmann]].
"""
    md = _format_note_markdown(note, original_content)

    # Check RAG frontmatter
    assert "platform: obsidian" in md
    assert "source_service: obsidian" in md
    assert "vault_folder: 33 Permanent notes" in md
    assert "pkm" in md
    assert "notes" in md
    assert "Slip Box" in md
    assert "Niklas Luhmann" in md

    # Body should contain the original content minus vault frontmatter
    assert "# Zettelkasten Method" in md
    assert "The Zettelkasten is a method" in md
    # Original YAML frontmatter should be stripped
    assert "title: Zettelkasten Method\ntags: [pkm, notes]" not in md


def test_generate_obsidian_profile_facts():
    from agents.obsidian_sync import (
        ObsidianSyncState,
        VaultNote,
        _generate_profile_facts,
    )

    state = ObsidianSyncState()
    state.notes = {
        "30 Areas/33 Permanent notes/a.md": VaultNote(
            relative_path="30 Areas/33 Permanent notes/a.md",
            title="Note A",
            folder="33 Permanent notes",
            content_hash="h1",
            size=200,
            mtime=1.0,
            tags=["pkm", "zettelkasten"],
        ),
        "30 Areas/33 Permanent notes/b.md": VaultNote(
            relative_path="30 Areas/33 Permanent notes/b.md",
            title="Note B",
            folder="33 Permanent notes",
            content_hash="h2",
            size=300,
            mtime=2.0,
            tags=["pkm", "writing"],
        ),
        "20-personal/c.md": VaultNote(
            relative_path="20-personal/c.md",
            title="Note C",
            folder="20-personal",
            content_hash="h3",
            size=150,
            mtime=3.0,
            tags=["music"],
        ),
    }

    facts = _generate_profile_facts(state)
    assert len(facts) > 0
    dims = {f["dimension"] for f in facts}
    assert "information_seeking" in dims
    keys = {f["key"] for f in facts}
    assert "obsidian_active_areas" in keys
    assert "obsidian_note_volume" in keys
    assert "obsidian_frequent_tags" in keys
