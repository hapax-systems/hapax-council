"""Tests for axiom-precedent category in omg_pastebin_publisher (ytb-OMG6 Phase C)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

from agents.omg_pastebin_publisher.publisher import (
    PastebinArtifactPublisher,
    build_precedent_digest,
    build_precedent_slug,
    read_precedents_from_dir,
)


def _precedent(
    precedent_id: str = "sp-hsea-mg-001",
    short_name: str = "drafting-as-content",
    axiom_id: str = "management_governance",
    version: int = 1,
) -> dict:
    return {
        "precedent_id": precedent_id,
        "short_name": short_name,
        "axiom_id": axiom_id,
        "secondary_axioms": ["interpersonal_transparency"],
        "version": version,
        "situation": "Some situation.",
        "decision": "Some decision.",
        "reasoning": "Some reasoning.",
    }


class TestBuildPrecedentSlug:
    def test_slug_uses_precedent_id(self) -> None:
        assert build_precedent_slug("sp-hsea-mg-001") == "precedent-sp-hsea-mg-001"

    def test_slug_lowercases(self) -> None:
        assert build_precedent_slug("SP-HSEA-MG-001") == "precedent-sp-hsea-mg-001"

    def test_slug_strips_nonascii(self) -> None:
        out = build_precedent_slug("résumé-001")
        assert out.startswith("precedent-")
        assert "é" not in out


class TestBuildPrecedentDigest:
    def test_renders_short_name_and_axiom(self) -> None:
        out = build_precedent_digest(precedent=_precedent())
        assert "drafting-as-content" in out
        assert "management_governance" in out

    def test_renders_situation_decision_reasoning(self) -> None:
        out = build_precedent_digest(precedent=_precedent())
        assert "Situation" in out or "## " in out
        assert "Some situation." in out
        assert "Some decision." in out
        assert "Some reasoning." in out

    def test_includes_version(self) -> None:
        out = build_precedent_digest(precedent=_precedent(version=3))
        assert "v3" in out or "version" in out.lower()

    def test_includes_secondary_axioms(self) -> None:
        out = build_precedent_digest(precedent=_precedent())
        assert "interpersonal_transparency" in out

    def test_empty_when_missing_required_fields(self) -> None:
        """Precedents without precedent_id can't safely publish."""
        out = build_precedent_digest(precedent={"short_name": "x"})
        assert out == ""


class TestReadPrecedentsFromDir:
    def test_returns_empty_when_missing(self, tmp_path: Path) -> None:
        assert read_precedents_from_dir(tmp_path / "missing") == []

    def test_reads_yaml_files(self, tmp_path: Path) -> None:
        (tmp_path / "p1.yaml").write_text(
            "precedent_id: p-001\n"
            "axiom_id: management_governance\n"
            "short_name: test\n"
            "version: 1\n"
            "situation: a\n"
            "decision: b\n"
            "reasoning: c\n"
        )
        (tmp_path / "p2.yaml").write_text(
            "precedent_id: p-002\n"
            "axiom_id: single_user\n"
            "short_name: test2\n"
            "version: 1\n"
            "situation: x\n"
            "decision: y\n"
            "reasoning: z\n"
        )
        result = read_precedents_from_dir(tmp_path)
        ids = [p.get("precedent_id") for p in result]
        assert "p-001" in ids
        assert "p-002" in ids

    def test_skips_seed_subdir(self, tmp_path: Path) -> None:
        """``seed/`` subdir contains seed templates — exclude from publish."""
        (tmp_path / "p.yaml").write_text(
            "precedent_id: p-real\n"
            "axiom_id: m\n"
            "short_name: r\n"
            "version: 1\n"
            "situation: s\n"
            "decision: d\n"
            "reasoning: r\n"
        )
        seed_dir = tmp_path / "seed"
        seed_dir.mkdir()
        (seed_dir / "should-not-publish.yaml").write_text(
            "precedent_id: seed-template\n"
            "axiom_id: m\n"
            "short_name: x\n"
            "version: 0\n"
            "situation: \n"
            "decision: \n"
            "reasoning: \n"
        )
        result = read_precedents_from_dir(tmp_path)
        ids = [p.get("precedent_id") for p in result]
        assert ids == ["p-real"]


class TestPublisherPrecedentFlow:
    def _client(self, *, enabled: bool = True, set_ok: bool = True) -> MagicMock:
        c = MagicMock()
        c.enabled = enabled
        c.set_paste.return_value = (
            {"request": {"statusCode": 200}, "response": {"slug": "stub"}} if set_ok else None
        )
        return c

    def _publisher(
        self, tmp_path: Path, *, precedents: list[dict], client=None
    ) -> PastebinArtifactPublisher:
        return PastebinArtifactPublisher(
            client=client or self._client(),
            state_file=tmp_path / "state.json",
            read_events=lambda: [],
            read_precedents=lambda: precedents,
            now_fn=lambda: datetime(2026, 4, 24, 22, 0, 0, tzinfo=UTC),
        )

    def test_publish_precedent(self, tmp_path: Path) -> None:
        publisher = self._publisher(tmp_path, precedents=[_precedent()])
        outcome = publisher.publish_precedent("sp-hsea-mg-001")
        assert outcome == "published"

    def test_publish_unknown_returns_empty(self, tmp_path: Path) -> None:
        publisher = self._publisher(tmp_path, precedents=[])
        outcome = publisher.publish_precedent("missing-001")
        assert outcome == "empty"

    def test_dry_run_skips_client(self, tmp_path: Path) -> None:
        client = self._client()
        publisher = self._publisher(tmp_path, precedents=[_precedent()], client=client)
        outcome = publisher.publish_precedent("sp-hsea-mg-001", dry_run=True)
        assert outcome == "dry-run"
        client.set_paste.assert_not_called()

    def test_idempotent_unchanged_on_second_call(self, tmp_path: Path) -> None:
        publisher = self._publisher(tmp_path, precedents=[_precedent()])
        assert publisher.publish_precedent("sp-hsea-mg-001") == "published"
        assert publisher.publish_precedent("sp-hsea-mg-001") == "unchanged"

    def test_disabled_client_short_circuits(self, tmp_path: Path) -> None:
        publisher = self._publisher(
            tmp_path,
            precedents=[_precedent()],
            client=self._client(enabled=False),
        )
        outcome = publisher.publish_precedent("sp-hsea-mg-001")
        assert outcome == "client-disabled"
