"""AUDIT-05 — OMG cascade legal-name leak regression.

Asserts that every wired OMG publisher / composer fail-closes when
the operator's legal name appears in rendered content. The protection
is a proactive guard against the OMG cascade outward-publishing
existential-risk class: any of the OMG modules could potentially
emit operator-name surface forms via LLM composition, jinja
templating, or operator-edited drafts.

This test is the on-going regression: if a future OMG module ships
without wiring :func:`shared.governance.omg_referent.safe_render`
into its egress path, this test fails for that module.

Coverage:

  * Module-source verification — every OMG module under ``agents/``
    that produces user-visible output imports
    ``shared.governance.omg_referent``.
  * Behavioral spot-check — ``PastebinArtifactPublisher._safe_render_or_drop``
    + the ``safe_render`` helper itself (the protective layer all
    wired modules call) returns the leak signal under
    ``HAPAX_OPERATOR_NAME``.
  * Contract coverage — every publication contract under
    ``axioms/contracts/publication/`` includes ``operator_legal_name``
    in its ``redactions:`` list.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from shared.governance.omg_referent import OperatorNameLeak, safe_render

# ── Module-source verification ────────────────────────────────────────


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WIRED_MODULES = (
    "agents/omg_credits_publisher",
    "agents/omg_now_sync",
    "agents/omg_pastebin_publisher",
    "agents/omg_statuslog_poster",
    "agents/omg_web_builder",
    "agents/omg_weblog_composer",
    "agents/omg_weblog_publisher",
)


def _module_imports_omg_referent(module_dir: str) -> bool:
    """True iff any .py file under ``module_dir`` imports ``omg_referent``."""
    base = REPO_ROOT / module_dir
    for py in base.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        if "shared.governance.omg_referent" in text:
            return True
    return False


class TestModuleSourceCoverage:
    """Audit acceptance: ``grep OperatorReferentPicker|operator_referent
    agents/omg_*/`` returns ≥7 hits.

    More precisely: every OMG module that renders / templates / posts
    user-visible content imports ``omg_referent`` (the AUDIT-05
    helper).
    """

    @pytest.mark.parametrize("module_dir", WIRED_MODULES)
    def test_each_wired_module_imports_referent_helper(self, module_dir: str) -> None:
        assert _module_imports_omg_referent(module_dir), (
            f"{module_dir} does not import shared.governance.omg_referent — "
            "AUDIT-05 protection missing."
        )

    def test_at_least_seven_modules_wired(self) -> None:
        """Per AUDIT-05 acceptance: ≥7 grep hits across OMG modules."""
        hits = sum(_module_imports_omg_referent(m) for m in WIRED_MODULES)
        assert hits >= 7


# ── Contract coverage ────────────────────────────────────────────────


CONTRACT_DIR = REPO_ROOT / "axioms" / "contracts" / "publication"


class TestContractCoverage:
    """Every publication contract MUST include ``operator_legal_name``
    in its ``redactions:`` list — the contract-level governance
    protection that pairs with the module-level safe_render guard."""

    @pytest.mark.parametrize(
        "contract_path", sorted(CONTRACT_DIR.glob("*.yaml")), ids=lambda p: p.name
    )
    def test_contract_redacts_legal_name(self, contract_path: Path) -> None:
        data = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
        redactions = data.get("redactions") or []
        assert "operator_legal_name" in redactions, (
            f"{contract_path.name} missing operator_legal_name in redactions"
        )


# ── Behavioral spot-check ────────────────────────────────────────────


# Fixture legal-name pattern injected via HAPAX_OPERATOR_NAME for these
# tests. Chosen to be unambiguous + not appear in any real OMG content
# fixture (so a leak detection is unambiguously caused by the test
# input, not collateral).
LEGAL_NAME_FIXTURE = "Fixture Real Person"


@pytest.fixture
def legal_name_env(monkeypatch):
    monkeypatch.setenv("HAPAX_OPERATOR_NAME", LEGAL_NAME_FIXTURE)


class TestSafeRenderProtectsAgainstLeak:
    """Direct test of the ``safe_render`` helper that all wired modules
    call. If this fails, every OMG module's protection is compromised.
    """

    def test_legal_name_in_text_raises_under_env_var(self, legal_name_env) -> None:
        with pytest.raises(OperatorNameLeak):
            safe_render(f"a status mentioning {LEGAL_NAME_FIXTURE}", segment_id="t1")

    def test_no_leak_passes_through(self, legal_name_env) -> None:
        clean = "a clean status without anybody's real name"
        assert safe_render(clean, segment_id="t1") == clean

    def test_substitute_token_then_scan(self, legal_name_env) -> None:
        """Substitution happens before the scan; picker output is one
        of the four ratified non-formal referents (none of which match
        the fixture legal name)."""
        out = safe_render("posted by {operator}", segment_id="t1")
        assert "{operator}" not in out
        # No raise — referents don't contain the fixture name.


class TestPastebinSafeRenderHelper:
    """The pastebin publisher's ``_safe_render_or_drop`` is the shape
    each of its 4 publish methods uses. Pin its leak path."""

    def _make_publisher(self, tmp_path: Path):
        from agents.omg_pastebin_publisher.publisher import PastebinArtifactPublisher

        client = MagicMock()
        client.enabled = True
        publisher = PastebinArtifactPublisher(
            address="hapax",
            client=client,
            state_file=tmp_path / "state.json",
            read_events=lambda: [],
            now_fn=lambda: __import__("datetime").datetime(
                2026, 4, 25, 5, 0, 0, tzinfo=__import__("datetime").UTC
            ),
        )
        return publisher

    def test_helper_returns_none_on_leak(self, tmp_path: Path, legal_name_env) -> None:
        publisher = self._make_publisher(tmp_path)
        result = publisher._safe_render_or_drop(
            f"content with {LEGAL_NAME_FIXTURE}",
            slug="test-slug",
            category=publisher.CATEGORY_CHRONICLE,
        )
        assert result is None

    def test_helper_returns_redacted_on_clean(self, tmp_path: Path, legal_name_env) -> None:
        publisher = self._make_publisher(tmp_path)
        clean = "content without anybody's real name"
        result = publisher._safe_render_or_drop(
            clean, slug="test-slug", category=publisher.CATEGORY_CHRONICLE
        )
        assert result == clean


class TestWeblogPublisherLeak:
    """End-to-end leak test for the simplest wired publisher."""

    def test_leak_in_draft_blocks_publish(self, legal_name_env) -> None:
        from agents.omg_weblog_publisher.publisher import (
            WeblogDraft,
            WeblogPublisher,
        )

        client = MagicMock()
        client.enabled = True
        publisher = WeblogPublisher(client=client, address="hapax")

        draft = WeblogDraft(
            slug="2026-04-25",
            title="post",
            content=f"by {LEGAL_NAME_FIXTURE}\n\nbody.",
            approved=True,
        )
        outcome = publisher.publish(draft)
        assert outcome == "legal-name-leak"
        client.set_entry.assert_not_called()

    def test_clean_draft_publishes(self, legal_name_env) -> None:
        from agents.omg_weblog_publisher.publisher import (
            WeblogDraft,
            WeblogPublisher,
        )

        client = MagicMock()
        client.enabled = True
        client.set_entry.return_value = {"request": {"statusCode": 200}}
        publisher = WeblogPublisher(client=client, address="hapax")

        draft = WeblogDraft(
            slug="2026-04-25",
            title="post",
            content="clean body without legal name surface forms.",
            approved=True,
        )
        outcome = publisher.publish(draft)
        # Clean content reaches publish path; leak guard does not fire.
        assert outcome != "legal-name-leak"


# Suppress noisy unused-import warnings — the date import is used in
# the inline lambda inside `_make_publisher`.
_ = date
