"""Tests for scripts/compute_inter_rater_kappa.py — kappa computation logic."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from compute_inter_rater_kappa import (
    cohens_kappa,
    compute_kappa_report,
    percent_agreement,
)


def test_perfect_agreement_kappa() -> None:
    a = [1, 2, 3, 4, 5, 1, 2, 3, 4, 5]
    b = [1, 2, 3, 4, 5, 1, 2, 3, 4, 5]
    assert cohens_kappa(a, b, weights="none") == 1.0
    assert cohens_kappa(a, b, weights="quadratic") == 1.0


def test_no_agreement_kappa() -> None:
    a = [1, 1, 1, 1, 1]
    b = [5, 5, 5, 5, 5]
    k = cohens_kappa(a, b, weights="none")
    assert k <= 0.0  # no agreement beyond chance


def test_moderate_agreement_kappa() -> None:
    a = [1, 2, 3, 4, 5, 2, 3, 4, 3, 2]
    b = [1, 2, 3, 4, 5, 3, 3, 3, 3, 2]
    k = cohens_kappa(a, b, weights="quadratic")
    assert 0.4 < k < 1.0  # moderate to substantial


def test_percent_agreement_exact() -> None:
    a = [1, 2, 3, 4, 5]
    b = [1, 2, 3, 4, 5]
    assert percent_agreement(a, b, tolerance=0) == 1.0


def test_percent_agreement_within_one() -> None:
    a = [1, 2, 3, 4, 5]
    b = [2, 3, 4, 5, 4]
    assert percent_agreement(a, b, tolerance=1) == 1.0
    assert percent_agreement(a, b, tolerance=0) == 0.0


def test_compute_kappa_report_matched() -> None:
    cctv = {
        "FAB-1": {
            "counter_evidence_resilience": 1,
            "evidence_adequacy": 1,
            "falsifiability": 4,
            "scope_honesty": 2,
        },
        "FAB-2": {
            "counter_evidence_resilience": 1,
            "evidence_adequacy": 1,
            "falsifiability": 3,
            "scope_honesty": 2,
        },
        "OVR-1": {
            "counter_evidence_resilience": 3,
            "evidence_adequacy": 4,
            "falsifiability": 3,
            "scope_honesty": 3,
        },
    }
    perplexity = {
        "FAB-1": {
            "counter_evidence_resilience": 1,
            "evidence_adequacy": 2,
            "falsifiability": 4,
            "scope_honesty": 2,
        },
        "FAB-2": {
            "counter_evidence_resilience": 2,
            "evidence_adequacy": 1,
            "falsifiability": 3,
            "scope_honesty": 3,
        },
        "OVR-1": {
            "counter_evidence_resilience": 3,
            "evidence_adequacy": 3,
            "falsifiability": 3,
            "scope_honesty": 3,
        },
    }
    report = compute_kappa_report(cctv, perplexity)
    assert report["aggregate"]["n_matched_probes"] == 3
    assert report["aggregate"]["n_total_pairs"] == 12
    assert "kappa_quadratic_weighted" in report["aggregate"]


def test_compute_kappa_report_no_match() -> None:
    cctv = {"A": {"falsifiability": 3}}
    perplexity = {"B": {"falsifiability": 3}}
    report = compute_kappa_report(cctv, perplexity)
    assert "error" in report


def test_empty_ratings_kappa() -> None:
    assert cohens_kappa([], [], weights="none") == 0.0
