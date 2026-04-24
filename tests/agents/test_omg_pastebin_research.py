"""Tests for research-corpus category in omg_pastebin_publisher (ytb-OMG6 Phase D)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

from agents.omg_pastebin_publisher.publisher import (
    PastebinArtifactPublisher,
    build_research_digest,
    build_research_slug,
    read_research_from_dir,
)


def _research(
    research_id: str = "perception-fusion-2026-04",
    title: str = "Perception fusion notes",
    publish: bool = True,
    body: str = "Some research observations.",
) -> dict:
    return {
        "research_id": research_id,
        "title": title,
        "publish": publish,
        "body": body,
        "extracted_date": "2026-04-20",
    }


class TestBuildResearchSlug:
    def test_slug_uses_research_id(self) -> None:
        assert (
            build_research_slug("perception-fusion-2026-04") == "research-perception-fusion-2026-04"
        )

    def test_slug_lowercases_and_kebab(self) -> None:
        assert build_research_slug("Perception Fusion 04") == "research-perception-fusion-04"


class TestBuildResearchDigest:
    def test_renders_title_and_body(self) -> None:
        out = build_research_digest(research=_research())
        assert "# Perception fusion notes" in out
        assert "Some research observations." in out

    def test_includes_extracted_date(self) -> None:
        out = build_research_digest(research=_research(body="x"))
        assert "2026-04-20" in out

    def test_empty_when_publish_flag_false(self) -> None:
        """Default-deny: only research docs explicitly marked publish:true emit."""
        out = build_research_digest(research=_research(publish=False))
        assert out == ""

    def test_empty_when_research_id_missing(self) -> None:
        out = build_research_digest(research={"title": "x", "publish": True, "body": "x"})
        assert out == ""


class TestReadResearchFromDir:
    def test_returns_empty_when_missing(self, tmp_path: Path) -> None:
        assert read_research_from_dir(tmp_path / "missing") == []

    def test_reads_frontmatter_documents(self, tmp_path: Path) -> None:
        (tmp_path / "doc-a.md").write_text(
            "---\n"
            'research_id: "rd-a"\n'
            'title: "Research A"\n'
            "publish: true\n"
            'extracted_date: "2026-04-20"\n'
            "---\n"
            "Body A here\n"
        )
        (tmp_path / "doc-b.md").write_text(
            '---\nresearch_id: "rd-b"\ntitle: "Research B"\npublish: false\n---\nBody B (private)\n'
        )
        result = read_research_from_dir(tmp_path)
        ids = [p.get("research_id") for p in result]
        # Both returned; filtering by publish flag happens in build_research_digest.
        assert "rd-a" in ids
        assert "rd-b" in ids

    def test_body_extracted_into_dict(self, tmp_path: Path) -> None:
        (tmp_path / "x.md").write_text(
            '---\nresearch_id: "x-1"\ntitle: "X"\npublish: true\n---\nLine 1\nLine 2\n'
        )
        result = read_research_from_dir(tmp_path)
        assert len(result) == 1
        # Body lines are joined as the ``body`` key.
        assert "Line 1" in result[0].get("body", "")
        assert "Line 2" in result[0].get("body", "")


class TestPublisherResearchFlow:
    def _client(self, *, enabled: bool = True, set_ok: bool = True) -> MagicMock:
        c = MagicMock()
        c.enabled = enabled
        c.set_paste.return_value = (
            {"request": {"statusCode": 200}, "response": {"slug": "stub"}} if set_ok else None
        )
        return c

    def _publisher(
        self, tmp_path: Path, *, research: list[dict], client=None
    ) -> PastebinArtifactPublisher:
        return PastebinArtifactPublisher(
            client=client or self._client(),
            state_file=tmp_path / "state.json",
            read_events=lambda: [],
            read_research=lambda: research,
            now_fn=lambda: datetime(2026, 4, 24, 22, 0, 0, tzinfo=UTC),
        )

    def test_publish_research(self, tmp_path: Path) -> None:
        publisher = self._publisher(tmp_path, research=[_research()])
        outcome = publisher.publish_research("perception-fusion-2026-04")
        assert outcome == "published"

    def test_publish_unpublishable_returns_empty(self, tmp_path: Path) -> None:
        """publish: false → empty (default-deny gate)."""
        publisher = self._publisher(tmp_path, research=[_research(publish=False)])
        outcome = publisher.publish_research("perception-fusion-2026-04")
        assert outcome == "empty"

    def test_publish_unknown_returns_empty(self, tmp_path: Path) -> None:
        publisher = self._publisher(tmp_path, research=[])
        outcome = publisher.publish_research("missing")
        assert outcome == "empty"

    def test_dry_run_skips_client(self, tmp_path: Path) -> None:
        client = self._client()
        publisher = self._publisher(tmp_path, research=[_research()], client=client)
        outcome = publisher.publish_research("perception-fusion-2026-04", dry_run=True)
        assert outcome == "dry-run"
        client.set_paste.assert_not_called()

    def test_idempotent_unchanged_on_second_call(self, tmp_path: Path) -> None:
        publisher = self._publisher(tmp_path, research=[_research()])
        assert publisher.publish_research("perception-fusion-2026-04") == "published"
        assert publisher.publish_research("perception-fusion-2026-04") == "unchanged"

    def test_disabled_client_short_circuits(self, tmp_path: Path) -> None:
        publisher = self._publisher(
            tmp_path,
            research=[_research()],
            client=self._client(enabled=False),
        )
        outcome = publisher.publish_research("perception-fusion-2026-04")
        assert outcome == "client-disabled"
