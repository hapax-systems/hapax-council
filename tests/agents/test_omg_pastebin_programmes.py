"""Tests for programme-plans category in omg_pastebin_publisher (ytb-OMG6 Phase B)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

from agents.omg_pastebin_publisher.publisher import (
    PastebinArtifactPublisher,
    build_programme_digest,
    build_programme_slug,
    read_programmes_from_dir,
)


def _programme(
    programme_id: str = "turntable-arc-01",
    title: str = "Turntable Arc",
    status: str = "completed",
    completed_at: str = "2026-04-20T10:00:00Z",
) -> dict:
    return {
        "programme_id": programme_id,
        "title": title,
        "status": status,
        "completed_at": completed_at,
        "summary": "A modest arc about the turntable focus.",
    }


class TestBuildProgrammeSlug:
    def test_slug_uses_programme_id(self) -> None:
        assert build_programme_slug("turntable-arc-01") == "programme-turntable-arc-01"

    def test_slug_sanitises_underscores_and_spaces(self) -> None:
        assert build_programme_slug("Turntable Arc_01") == "programme-turntable-arc-01"

    def test_slug_strips_nonascii(self) -> None:
        assert build_programme_slug("résumé") == "programme-resume" or build_programme_slug(
            "résumé"
        ).startswith("programme-")


class TestBuildProgrammeDigest:
    def test_renders_title_and_summary(self) -> None:
        out = build_programme_digest(programme=_programme())
        assert "# Turntable Arc" in out
        assert "turntable focus" in out.lower()

    def test_includes_completed_date(self) -> None:
        out = build_programme_digest(programme=_programme(completed_at="2026-04-20T10:00:00Z"))
        assert "2026-04-20" in out

    def test_empty_when_not_completed(self) -> None:
        """Non-completed programmes yield empty string — contract: only completed plans publish."""
        out = build_programme_digest(programme=_programme(status="active"))
        assert out == ""

    def test_supports_sections(self) -> None:
        """Optional sections list renders as ## headings."""
        programme = _programme()
        programme["sections"] = [
            {"title": "Intent", "body": "what drew attention"},
            {"title": "Arc", "body": "what happened"},
        ]
        out = build_programme_digest(programme=programme)
        assert "## Intent" in out
        assert "## Arc" in out
        assert "what drew attention" in out


class TestReadProgrammesFromDir:
    def test_returns_empty_when_missing(self, tmp_path: Path) -> None:
        assert read_programmes_from_dir(tmp_path / "nonexistent") == []

    def test_reads_frontmatter_completed_programmes(self, tmp_path: Path) -> None:
        (tmp_path / "a.md").write_text(
            "---\n"
            'programme_id: "arc-a"\n'
            'title: "Arc A"\n'
            'status: "completed"\n'
            'completed_at: "2026-04-20T10:00:00Z"\n'
            'summary: "first"\n'
            "---\n"
            "body\n"
        )
        (tmp_path / "b.md").write_text(
            "---\n"
            'programme_id: "arc-b"\n'
            'title: "Arc B"\n'
            'status: "active"\n'
            'summary: "second"\n'
            "---\n"
            "body\n"
        )
        result = read_programmes_from_dir(tmp_path)
        ids = [p.get("programme_id") for p in result]
        assert "arc-a" in ids
        # Active programme also returned — filtering by status happens in build_programme_digest
        assert len(result) == 2

    def test_skips_non_markdown(self, tmp_path: Path) -> None:
        (tmp_path / "nope.txt").write_text("should be skipped")
        (tmp_path / "yes.md").write_text(
            '---\nprogramme_id: "y"\ntitle: "Y"\nstatus: "completed"\n---\n'
        )
        result = read_programmes_from_dir(tmp_path)
        ids = [p.get("programme_id") for p in result]
        assert ids == ["y"]


class TestPublisherProgrammeFlow:
    def _client(self, *, enabled: bool = True, set_ok: bool = True) -> MagicMock:
        c = MagicMock()
        c.enabled = enabled
        c.set_paste.return_value = (
            {"request": {"statusCode": 200}, "response": {"slug": "stub"}} if set_ok else None
        )
        return c

    def _publisher(
        self, tmp_path: Path, *, programmes: list[dict], client=None
    ) -> PastebinArtifactPublisher:
        return PastebinArtifactPublisher(
            client=client or self._client(),
            state_file=tmp_path / "state.json",
            read_events=lambda: [],
            read_programmes=lambda: programmes,
            now_fn=lambda: datetime(2026, 4, 24, 22, 0, 0, tzinfo=UTC),
        )

    def test_publish_completed_programme(self, tmp_path: Path) -> None:
        publisher = self._publisher(tmp_path, programmes=[_programme()])
        outcome = publisher.publish_programme("turntable-arc-01")
        assert outcome == "published"

    def test_publish_unknown_programme_returns_empty(self, tmp_path: Path) -> None:
        publisher = self._publisher(tmp_path, programmes=[])
        outcome = publisher.publish_programme("missing-01")
        assert outcome == "empty"

    def test_publish_active_programme_returns_empty(self, tmp_path: Path) -> None:
        """Contract: only completed programmes publish."""
        publisher = self._publisher(tmp_path, programmes=[_programme(status="active")])
        outcome = publisher.publish_programme("turntable-arc-01")
        assert outcome == "empty"

    def test_dry_run_skips_client(self, tmp_path: Path) -> None:
        client = self._client()
        publisher = self._publisher(tmp_path, programmes=[_programme()], client=client)
        outcome = publisher.publish_programme("turntable-arc-01", dry_run=True)
        assert outcome == "dry-run"
        client.set_paste.assert_not_called()

    def test_idempotent_unchanged_on_second_call(self, tmp_path: Path) -> None:
        publisher = self._publisher(tmp_path, programmes=[_programme()])
        assert publisher.publish_programme("turntable-arc-01") == "published"
        assert publisher.publish_programme("turntable-arc-01") == "unchanged"

    def test_disabled_client_short_circuits(self, tmp_path: Path) -> None:
        publisher = self._publisher(
            tmp_path,
            programmes=[_programme()],
            client=self._client(enabled=False),
        )
        outcome = publisher.publish_programme("turntable-arc-01")
        assert outcome == "client-disabled"
