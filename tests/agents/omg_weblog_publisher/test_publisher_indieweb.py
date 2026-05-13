from dataclasses import dataclass

from agents.omg_weblog_publisher.publisher import _compose_artifact_content


@dataclass
class MockArtifact:
    title: str = ""
    slug: str = ""
    attribution_block: str = ""
    abstract: str = ""
    body_md: str = ""
    surfaces_targeted: list[str] | None = None


def test_compose_artifact_content_indieweb_markup():
    artifact = MockArtifact(
        title="Test Title",
        slug="test-title",
        body_md="# Test Title\n\nThis is the body.",
        surfaces_targeted=[
            "bluesky-atproto-multi-identity",
            "github-readme-profile-current-project-refresh",
        ],
    )

    result = _compose_artifact_content(artifact)

    assert "# Test Title" in result
    assert '<div class="h-entry">' in result
    assert '<a class="p-author h-card" href="https://hapax.omg.lol"' in result
    assert '<div class="e-content">' in result
    assert "This is the body." in result
    assert '<a class="u-syndication" href="https://bsky.app/profile/oudepode.bsky.social"' in result
    assert '<a class="u-syndication" href="https://github.com/hapax-systems"' in result
    assert "Mastodon" not in result


def test_compose_artifact_content_h1_first():
    artifact = MockArtifact(
        title="My Title",
        body_md="# My Title\n\nBody",
    )
    result = _compose_artifact_content(artifact)

    # Extract the actual content block (everything after Date: ...)
    content_lines = result.split("\n\n")[1:]
    first_content_line = content_lines[0]

    # omg.lol requires the first non-date line to be the H1
    assert first_content_line == "# My Title", "H1 must remain un-wrapped and at the very top"
