"""Tests for ``agents.publication_bus.wire_status``.

R-5 audit follow-up: every V5 publisher class must have an explicit
wire-or-delete decision recorded in ``PUBLISHER_WIRE_REGISTRY``. The
audit pin here scans the filesystem for ``*_publisher.py`` modules and
asserts each is catalogued.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import patch

from agents.publication_bus.surface_registry import SURFACE_REGISTRY
from agents.publication_bus.wire_status import (
    PUBLISHER_WIRE_REGISTRY,
    WireEntry,
    cred_blocked_pass_keys,
    credential_readiness,
    overdue_reviews,
    status_summary,
)

_PUBLICATION_BUS_DIR = Path(__file__).resolve().parents[3] / "agents/publication_bus"
_ATTRIBUTION_DIR = Path(__file__).resolve().parents[3] / "agents/attribution"


def test_all_v5_publishers_catalogued():
    """Audit pin: every `*_publisher.py` module under publication_bus/ must
    appear in PUBLISHER_WIRE_REGISTRY. Catches drift when a new publisher
    is added without a wire-or-delete decision.
    """
    discovered = {f.stem for f in _PUBLICATION_BUS_DIR.glob("*_publisher.py")}
    catalogued = {
        m.split(".")[-1] for m in PUBLISHER_WIRE_REGISTRY if m.startswith("agents.publication_bus.")
    }
    missing = discovered - catalogued
    assert not missing, f"Publishers without wire-decision: {missing}"


def test_crossref_depositor_catalogued():
    # Lives under agents/attribution but routed via R-5 alongside V5
    assert (_ATTRIBUTION_DIR / "crossref_depositor.py").exists()
    assert "agents.attribution.crossref_depositor" in PUBLISHER_WIRE_REGISTRY


def test_status_summary_returns_int_counts():
    summary = status_summary()
    assert set(summary.keys()) == {"WIRED", "CRED_BLOCKED", "DELETE"}
    assert all(isinstance(v, int) for v in summary.values())
    assert sum(summary.values()) == len(PUBLISHER_WIRE_REGISTRY)


def test_at_least_one_wired():
    # omg_weblog_publisher must be WIRED — it's the only one with prod callers
    summary = status_summary()
    assert summary["WIRED"] >= 1


def test_omg_weblog_is_wired():
    entry = PUBLISHER_WIRE_REGISTRY["agents.publication_bus.omg_weblog_publisher"]
    assert entry.status == "WIRED"


def test_cred_blocked_majority():
    # Per beta's R-5 inflection: "mostly delete given the cred-arrival gates"
    # — but our decision is to keep them as CRED_BLOCKED rather than delete.
    # Confirm the registry reflects that majority status.
    summary = status_summary()
    assert summary["CRED_BLOCKED"] >= summary["DELETE"]


def test_cred_blocked_pass_keys_returns_sorted_unique():
    keys = cred_blocked_pass_keys()
    assert keys == sorted(set(keys))
    assert len(keys) > 0  # at least some surfaces have explicit pass keys


def test_no_delete_status_yet():
    # If a publisher is later determined to be DELETE-status, this test
    # surfaces the change explicitly. Initial registry: all live entries
    # are either WIRED or CRED_BLOCKED.
    summary = status_summary()
    assert summary["DELETE"] == 0


def test_each_entry_has_surface_slug():
    for module, entry in PUBLISHER_WIRE_REGISTRY.items():
        assert entry.surface_slug, f"{module} missing surface_slug"
        assert isinstance(entry, WireEntry)
        assert entry.surface_slug in SURFACE_REGISTRY, (
            f"{module} references unknown surface_slug {entry.surface_slug!r}"
        )


def test_each_cred_blocked_entry_has_rationale():
    for module, entry in PUBLISHER_WIRE_REGISTRY.items():
        if entry.status == "CRED_BLOCKED":
            assert entry.rationale, f"{module} CRED_BLOCKED but no rationale"


def test_each_cred_blocked_entry_documents_disposition():
    """CRED_BLOCKED is a dormant-by-default state. Per cc-task
    ``crossref-credential-bootstrap-pipeline`` (and aligned with the
    operator's ``never stall, no dormant default`` posture): every
    CRED_BLOCKED entry must explicitly document **what operator action
    unblocks it** AND **when the surface should be re-evaluated**.

    The check is rationale-text-based on purpose: the WireEntry shape
    stays minimal (no schema migration) but new CRED_BLOCKED additions
    that omit either signal fail CI before merging. Two regression pins:

    * The rationale references the operator action explicitly — at
      minimum a literal pass-store insert command (``pass insert
      <key>``) or the phrase ``operator-action`` so a future auditor
      can grep the codebase for who-needs-to-do-what.
    * The rationale carries a review-by ISO-8601 date so a perpetual
      CRED_BLOCKED state surfaces audit pressure when the date passes.
    """
    import re

    iso_date = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
    for module, entry in PUBLISHER_WIRE_REGISTRY.items():
        if entry.status != "CRED_BLOCKED":
            continue
        rationale_lc = entry.rationale.lower()
        assert "operator-action" in rationale_lc or "pass insert" in rationale_lc, (
            f"{module}: CRED_BLOCKED rationale must reference the operator "
            f"action (e.g. 'operator-action: pass insert <key>') so "
            f"who-unblocks-this is greppable. Got: {entry.rationale!r}"
        )
        assert iso_date.search(entry.rationale), (
            f"{module}: CRED_BLOCKED rationale must carry a review-by "
            f"ISO-8601 date (YYYY-MM-DD) so a perpetual hold surfaces "
            f"audit pressure when the date passes. Got: {entry.rationale!r}"
        )


def test_graph_publisher_slug_matches_surface_registry():
    entry = PUBLISHER_WIRE_REGISTRY["agents.publication_bus.graph_publisher"]
    assert entry.surface_slug == "datacite-graphql-mirror"


def test_crossref_depositor_is_cred_blocked():
    entry = PUBLISHER_WIRE_REGISTRY["agents.attribution.crossref_depositor"]
    assert entry.status == "CRED_BLOCKED"
    assert entry.pass_key_required == "crossref/depositor-credentials"
    assert "review-by 2026-08-01" in entry.rationale


def test_crossref_depositor_pass_key_in_queue():
    keys = cred_blocked_pass_keys()
    assert "crossref/depositor-credentials" in keys


def test_credential_readiness_probes_pass():
    with patch("agents.publication_bus.wire_status.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 1
        result = credential_readiness()
        assert isinstance(result, dict)
        for key in cred_blocked_pass_keys():
            assert key in result
            assert result[key] is False
        assert mock_run.call_count == len(cred_blocked_pass_keys())


def test_credential_readiness_reports_present_creds():
    with patch("agents.publication_bus.wire_status.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        result = credential_readiness()
        for key in cred_blocked_pass_keys():
            assert result[key] is True


def test_overdue_reviews_empty_before_deadline():
    overdue = overdue_reviews(today=date(2026, 5, 8))
    assert overdue == []


def test_overdue_reviews_surfaces_past_deadline():
    overdue = overdue_reviews(today=date(2026, 9, 1))
    modules = [m for m, _, _ in overdue]
    assert "agents.attribution.crossref_depositor" in modules


def test_overdue_reviews_returns_correct_date():
    overdue = overdue_reviews(today=date(2027, 1, 1))
    crossref = [o for o in overdue if o[0] == "agents.attribution.crossref_depositor"]
    assert len(crossref) == 1
    _, pass_key, review_date = crossref[0]
    assert pass_key == "crossref/depositor-credentials"
    assert review_date == date(2026, 8, 1)
