"""Tests for scripts/dawid_skene_review_corpus.py.

The load-bearing test is ``test_recovers_known_confusion_matrices``: it generates
data from confusion matrices we choose, then checks EM recovers them. Break the
M-step or the E-step and that test goes red — it is verification, not
documentation. The extraction tests pin the contract with the real
review-receipts.json shape.
"""

from __future__ import annotations

import importlib.util
import json
import math
import random
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "dawid_skene_review_corpus.py"

_spec = importlib.util.spec_from_file_location("dawid_skene_review_corpus", SCRIPT)
assert _spec and _spec.loader
ds = importlib.util.module_from_spec(_spec)
# @dataclass resolves annotations through sys.modules, so register before exec.
sys.modules[_spec.name] = ds
_spec.loader.exec_module(ds)


# --------------------------------------------------------------------------
# corpus extraction
# --------------------------------------------------------------------------


def _write_corpus(tmp_path: Path, dossiers: list[dict]) -> Path:
    path = tmp_path / "review-receipts.json"
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "generated_at": "2026-06-28T16:24:41.619147+00:00",
                "dossiers": dossiers,
                "acceptances": [],
                "counts": {"dossiers": len(dossiers)},
            }
        )
    )
    return path


FIXTURE = [
    {
        "task_id": "t1",
        "pr": 1,
        "head_sha": "aaa",
        "reviewer_verdicts": {"claude": "accept-with-findings", "gemini": "accept"},
    },
    {
        "task_id": "t2",
        "pr": 2,
        "head_sha": "bbb",
        "reviewer_verdicts": {"claude": "block", "gemini": "invalid-output", "glm": "block"},
    },
    {
        "task_id": "t3",
        "pr": 3,
        "head_sha": "ccc",
        "reviewer_verdicts": {"codex": "quota-wall", "glm": "accept-with-findings"},
    },
]


def test_extraction_drops_nonresponse_by_default(tmp_path: Path) -> None:
    corpus = ds.load_corpus(_write_corpus(tmp_path, FIXTURE))
    assert corpus.dropped_nonresponse == 2
    assert ("t1@aaa", "claude", 1) in corpus.triples
    assert ("t1@aaa", "gemini", 2) in corpus.triples
    assert ("t2@bbb", "claude", 0) in corpus.triples
    assert not [t for t in corpus.triples if t[0] == "t3@ccc" and t[1] == "codex"]
    assert corpus.observed_labels == ("block", "accept-with-findings", "accept")
    assert corpus.raters == ["claude", "codex", "gemini", "glm"] or corpus.raters == [
        "claude",
        "gemini",
        "glm",
    ]


def test_extraction_can_emit_nonresponse_as_fourth_symbol(tmp_path: Path) -> None:
    corpus = ds.load_corpus(_write_corpus(tmp_path, FIXTURE), nonresponse="emit")
    assert corpus.dropped_nonresponse == 0
    assert corpus.observed_labels[3] == "no-response"
    assert ("t2@bbb", "gemini", 3) in corpus.triples
    assert ("t3@ccc", "codex", 3) in corpus.triples


def test_items_are_keyed_by_task_and_head_sha(tmp_path: Path) -> None:
    dossiers = [
        {"task_id": "t", "head_sha": "old", "reviewer_verdicts": {"claude": "block"}},
        {"task_id": "t", "head_sha": "new", "reviewer_verdicts": {"claude": "accept"}},
    ]
    corpus = ds.load_corpus(_write_corpus(tmp_path, dossiers))
    assert corpus.items == ["t@new", "t@old"]


def test_unknown_verdict_is_refused_not_silently_dropped(tmp_path: Path) -> None:
    dossiers = [{"task_id": "t", "head_sha": "a", "reviewer_verdicts": {"claude": "maybe"}}]
    with pytest.raises(ValueError, match="unknown verdict"):
        ds.load_corpus(_write_corpus(tmp_path, dossiers))


def test_coverage_and_pair_overlap(tmp_path: Path) -> None:
    corpus = ds.load_corpus(_write_corpus(tmp_path, FIXTURE))
    assert corpus.coverage() == {"claude": 2, "gemini": 1, "glm": 2}
    assert corpus.pair_overlap() == {
        ("claude", "gemini"): 1,
        ("claude", "glm"): 1,
    }


# --------------------------------------------------------------------------
# EM correctness
# --------------------------------------------------------------------------


def _synthesise(
    confusions: dict[str, list[list[float]]],
    priors: list[float],
    n_items: int,
    seed: int,
    *,
    coverage: dict[str, float] | None = None,
) -> tuple[ds.Corpus, list[int]]:
    rng = random.Random(seed)
    triples: list[ds.Triple] = []
    truth: list[int] = []
    for i in range(n_items):
        k = rng.choices(range(len(priors)), weights=priors)[0]
        truth.append(k)
        for rater, matrix in confusions.items():
            if coverage is not None and rng.random() > coverage.get(rater, 1.0):
                continue
            label = rng.choices(range(len(matrix[k])), weights=matrix[k])[0]
            triples.append((f"item{i:05d}", rater, label))
    return ds.Corpus(triples=triples, observed_labels=ds.LATENT_LABELS), truth


TRUE_CONFUSIONS = {
    # a near-perfect rater
    "sharp": [[0.90, 0.08, 0.02], [0.05, 0.90, 0.05], [0.02, 0.08, 0.90]],
    # systematically lenient: shifts one step toward accept
    "lenient": [[0.55, 0.40, 0.05], [0.05, 0.50, 0.45], [0.02, 0.13, 0.85]],
    # systematically strict
    "strict": [[0.92, 0.08, 0.00], [0.35, 0.62, 0.03], [0.05, 0.60, 0.35]],
    # nearly uninformative
    "noisy": [[0.40, 0.32, 0.28], [0.33, 0.34, 0.33], [0.30, 0.32, 0.38]],
}
TRUE_PRIORS = [0.25, 0.45, 0.30]


def test_recovers_known_confusion_matrices() -> None:
    """Generate from known error rates, check EM recovers them.

    This is the mutation-verified core: corrupt _m_step or _e_step and the
    assertion below fails.
    """
    corpus, _ = _synthesise(TRUE_CONFUSIONS, TRUE_PRIORS, n_items=6000, seed=7)
    fit = ds.dawid_skene(corpus, alpha=0.0)
    assert fit.converged

    for k in range(3):
        assert abs(fit.priors[k] - TRUE_PRIORS[k]) < 0.05, (k, fit.priors)

    for rater, true_matrix in TRUE_CONFUSIONS.items():
        for k in range(3):
            for label in range(3):
                got = fit.confusions[rater][k][label]
                want = true_matrix[k][label]
                assert abs(got - want) < 0.06, (rater, k, label, got, want)


def test_recovers_latent_classes_better_than_majority_vote() -> None:
    corpus, truth = _synthesise(TRUE_CONFUSIONS, TRUE_PRIORS, n_items=3000, seed=11)
    fit = ds.dawid_skene(corpus, alpha=0.0)

    by_item = corpus.by_item()
    ds_hits = 0
    mv_hits = 0
    for idx, item in enumerate(sorted(by_item)):
        post = fit.posteriors[item]
        ds_pred = max(range(3), key=lambda k: post[k])
        votes = [0, 0, 0]
        for label in by_item[item].values():
            votes[label] += 1
        mv_pred = max(range(3), key=lambda k: votes[k])
        ds_hits += ds_pred == truth[idx]
        mv_hits += mv_pred == truth[idx]

    assert ds_hits > mv_hits, (ds_hits, mv_hits)


def test_loglikelihood_is_monotone_nondecreasing() -> None:
    corpus, _ = _synthesise(TRUE_CONFUSIONS, TRUE_PRIORS, n_items=500, seed=3)
    fit = ds.dawid_skene(corpus, alpha=0.0)
    trace = fit.loglik_trace
    assert len(trace) > 2
    for prev, cur in zip(trace, trace[1:], strict=False):
        assert cur >= prev - 1e-9, (prev, cur)


def test_label_alignment_survives_random_initialisation() -> None:
    """DS latent classes are unlabelled; a random init can converge to a
    permuted labelling. align_latent_classes must undo it."""
    corpus, _ = _synthesise(TRUE_CONFUSIONS, TRUE_PRIORS, n_items=4000, seed=5)
    rng = random.Random(99)
    baseline = ds.dawid_skene(corpus, alpha=0.0)
    for _ in range(6):
        init = ds._random_init(corpus.items, 3, rng)
        fit = ds.dawid_skene(corpus, alpha=0.0, init=init)
        for rater in corpus.raters:
            for k in range(3):
                for label in range(3):
                    assert (
                        abs(fit.confusions[rater][k][label] - baseline.confusions[rater][k][label])
                        < 0.02
                    ), (rater, k, label)


def test_alignment_is_actually_applied_when_classes_are_permuted() -> None:
    """Directly exercise align_latent_classes on a deliberately permuted fit."""
    corpus, _ = _synthesise(TRUE_CONFUSIONS, TRUE_PRIORS, n_items=800, seed=13)
    fit = ds.dawid_skene(corpus, alpha=0.0)
    good = {r: [row[:] for row in m] for r, m in fit.confusions.items()}

    perm = (2, 0, 1)
    fit.confusions = {r: [m[p] for p in perm] for r, m in fit.confusions.items()}
    fit.priors = [fit.priors[p] for p in perm]
    fit.posteriors = {i: [p[j] for j in perm] for i, p in fit.posteriors.items()}

    ds.align_latent_classes(fit, corpus)
    for rater in corpus.raters:
        for k in range(3):
            for label in range(3):
                assert abs(fit.confusions[rater][k][label] - good[rater][k][label]) < 1e-12


# --------------------------------------------------------------------------
# derived metrics
# --------------------------------------------------------------------------


def test_metrics_rank_sharp_above_noisy_and_order_leniency_correctly() -> None:
    corpus, _ = _synthesise(TRUE_CONFUSIONS, TRUE_PRIORS, n_items=6000, seed=17)
    fit = ds.dawid_skene(corpus, alpha=0.0)
    met = ds.rater_metrics(fit, corpus)

    assert met["sharp"]["decoded_accuracy"] > met["lenient"]["decoded_accuracy"]
    assert met["sharp"]["decoded_accuracy"] > met["noisy"]["decoded_accuracy"]
    assert met["sharp"]["mutual_information_bits"] > met["noisy"]["mutual_information_bits"]
    assert met["noisy"]["mutual_information_bits"] < 0.05

    assert met["strict"]["leniency"] < 0 < met["lenient"]["leniency"]
    assert met["strict"]["leniency"] < met["sharp"]["leniency"] < met["lenient"]["leniency"]


def test_decoded_accuracy_ignores_pure_relabelling() -> None:
    """A rater that deterministically permutes the labels carries the full
    signal: raw agreement 0, decoded accuracy 1. This is the exact distinction
    the routing calculus depends on, so pin it directly.
    """
    confusions = dict(TRUE_CONFUSIONS)
    # emits (k + 1) mod 3 with certainty
    confusions["shifted"] = [[0.0, 1.0, 0.0], [0.0, 0.0, 1.0], [1.0, 0.0, 0.0]]
    corpus, _ = _synthesise(confusions, TRUE_PRIORS, n_items=4000, seed=53)
    fit = ds.dawid_skene(corpus, alpha=0.0)
    met = ds.rater_metrics(fit, corpus)

    assert met["shifted"]["raw_agreement"] < 0.05
    assert met["shifted"]["decoded_accuracy"] > 0.98
    assert met["shifted"]["decoded_accuracy"] > met["sharp"]["decoded_accuracy"]
    assert met["shifted"]["mutual_information_bits"] > met["sharp"]["mutual_information_bits"]


def test_decoded_accuracy_is_at_least_raw_agreement() -> None:
    """A Bayes decode can only improve on reading the rater's label literally."""
    corpus, _ = _synthesise(TRUE_CONFUSIONS, TRUE_PRIORS, n_items=2000, seed=23)
    fit = ds.dawid_skene(corpus, alpha=0.0)
    met = ds.rater_metrics(fit, corpus)
    for rater, values in met.items():
        assert values["decoded_accuracy"] >= values["raw_agreement"] - 1e-9, rater


def test_mutual_information_is_zero_for_a_rater_ignoring_the_item() -> None:
    confusions = dict(TRUE_CONFUSIONS)
    confusions["constant"] = [[0.1, 0.3, 0.6]] * 3  # emission independent of truth
    corpus, _ = _synthesise(confusions, TRUE_PRIORS, n_items=6000, seed=29)
    fit = ds.dawid_skene(corpus, alpha=0.0)
    met = ds.rater_metrics(fit, corpus)
    assert met["constant"]["mutual_information_bits"] < 0.01
    assert met["constant"]["decoded_accuracy"] == pytest.approx(max(fit.priors), abs=0.03)


def test_n_eff_rows_sum_to_rater_coverage() -> None:
    corpus, _ = _synthesise(
        TRUE_CONFUSIONS,
        TRUE_PRIORS,
        n_items=1500,
        seed=31,
        coverage={"sharp": 1.0, "lenient": 0.6, "strict": 0.4, "noisy": 0.8},
    )
    fit = ds.dawid_skene(corpus, alpha=0.0)
    met = ds.rater_metrics(fit, corpus)
    for rater, values in met.items():
        total = values["n_eff_block"] + values["n_eff_findings"] + values["n_eff_accept"]
        assert total == pytest.approx(values["coverage"], abs=1e-6), rater


def test_confusion_rows_are_probability_distributions() -> None:
    corpus, _ = _synthesise(TRUE_CONFUSIONS, TRUE_PRIORS, n_items=400, seed=37)
    for alpha in (0.0, 0.1, 1.0):
        fit = ds.dawid_skene(corpus, alpha=alpha)
        assert math.isclose(sum(fit.priors), 1.0, abs_tol=1e-9)
        for matrix in fit.confusions.values():
            for row in matrix:
                assert math.isclose(sum(row), 1.0, abs_tol=1e-9)
                assert all(p >= 0 for p in row)


# --------------------------------------------------------------------------
# diagnostics
# --------------------------------------------------------------------------


def test_pairwise_strictness_counts_direction() -> None:
    triples = [
        ("i1", "a", 0),
        ("i1", "b", 2),  # a stricter
        ("i2", "a", 2),
        ("i2", "b", 1),  # b stricter
        ("i3", "a", 1),
        ("i3", "b", 1),  # tie
    ]
    corpus = ds.Corpus(triples=triples, observed_labels=ds.LATENT_LABELS)
    rec = ds.pairwise_strictness(corpus)["a/b"]
    assert rec == {"n": 3, "ties": 1, "a_stricter": 1, "b_stricter": 1}


def test_restart_stability_reports_a_single_mode_on_clean_data() -> None:
    corpus, _ = _synthesise(TRUE_CONFUSIONS, TRUE_PRIORS, n_items=1200, seed=41)
    out = ds.restart_stability(corpus, alpha=0.0, restarts=5, seed=2)
    assert out["loglik_spread"] < 1e-3
    assert out["max_confusion_deviation_from_mv_init"] < 0.02


def test_bootstrap_ci_brackets_the_point_estimate() -> None:
    corpus, _ = _synthesise(TRUE_CONFUSIONS, TRUE_PRIORS, n_items=400, seed=43)
    fit = ds.dawid_skene(corpus, alpha=0.1)
    met = ds.rater_metrics(fit, corpus)
    cis = ds.bootstrap_ci(corpus, alpha=0.1, reps=40, seed=5)
    for rater, values in cis.items():
        lo, hi = values["decoded_accuracy"]
        assert lo <= met[rater]["decoded_accuracy"] <= hi, (rater, lo, hi)


def test_parameter_budget_counts_free_parameters() -> None:
    corpus, _ = _synthesise(TRUE_CONFUSIONS, TRUE_PRIORS, n_items=100, seed=59)
    budget = ds.parameter_budget(corpus)
    # 4 raters x 3 latent classes x (3 observed - 1) + (3 classes - 1) = 26
    assert budget["free_parameters"] == 26
    assert budget["observations"] == len(corpus.triples)


def test_posterior_confidence_separates_decided_from_undecided() -> None:
    sharp_only = {"x": TRUE_CONFUSIONS["sharp"], "y": TRUE_CONFUSIONS["sharp"]}
    noisy_only = {"x": TRUE_CONFUSIONS["noisy"], "y": TRUE_CONFUSIONS["noisy"]}
    good, _ = _synthesise(sharp_only, TRUE_PRIORS, n_items=600, seed=63)
    bad, _ = _synthesise(noisy_only, TRUE_PRIORS, n_items=600, seed=63)

    conf_good = ds.posterior_confidence(ds.dawid_skene(good, alpha=0.0))
    conf_bad = ds.posterior_confidence(ds.dawid_skene(bad, alpha=0.0))
    assert conf_good["mean_max_posterior"] > conf_bad["mean_max_posterior"]
    assert conf_good["fraction_above_0.90"] > conf_bad["fraction_above_0.90"]


def test_vote_influence_identifies_the_rater_that_defines_the_labels() -> None:
    """One near-perfect anchor plus two weakly informative raters: removing the
    anchor's ballot must flip far more labels than removing a weak one."""
    weak = [[0.50, 0.30, 0.20], [0.25, 0.50, 0.25], [0.20, 0.30, 0.50]]
    confusions = {
        "anchor": [[0.97, 0.02, 0.01], [0.02, 0.96, 0.02], [0.01, 0.02, 0.97]],
        "weak1": weak,
        "weak2": weak,
    }
    corpus, _ = _synthesise(confusions, TRUE_PRIORS, n_items=1500, seed=67)
    fit = ds.dawid_skene(corpus, alpha=0.0)
    influence = ds.vote_influence(fit, corpus)

    anchor = influence["anchor"]["map_flip_rate_without_this_vote"]
    assert anchor > influence["weak1"]["map_flip_rate_without_this_vote"]
    assert anchor > influence["weak2"]["map_flip_rate_without_this_vote"]
    assert (
        influence["anchor"]["mean_posterior_l1_shift"]
        > (influence["weak1"]["mean_posterior_l1_shift"])
    )
    for rec in influence.values():
        assert rec["items_rated"] == 1500


def test_vote_influence_is_symmetric_when_raters_are_equivalent() -> None:
    confusions = {name: TRUE_CONFUSIONS["sharp"] for name in ("r1", "r2", "r3", "r4")}
    corpus, _ = _synthesise(confusions, TRUE_PRIORS, n_items=1000, seed=71)
    fit = ds.dawid_skene(corpus, alpha=0.0)
    influence = ds.vote_influence(fit, corpus)
    rates = [r["map_flip_rate_without_this_vote"] for r in influence.values()]
    assert max(rates) - min(rates) < 0.05, influence


def test_vote_influence_is_near_zero_for_an_uninformative_rater() -> None:
    confusions = dict(TRUE_CONFUSIONS)
    confusions["constant"] = [[0.1, 0.3, 0.6]] * 3
    corpus, _ = _synthesise(confusions, TRUE_PRIORS, n_items=2000, seed=73)
    fit = ds.dawid_skene(corpus, alpha=0.0)
    influence = ds.vote_influence(fit, corpus)
    assert influence["constant"]["map_flip_rate_without_this_vote"] < 0.02
    assert (
        influence["constant"]["mean_posterior_l1_shift"]
        < (influence["sharp"]["mean_posterior_l1_shift"])
    )


def test_smoothing_sensitivity_covers_every_alpha() -> None:
    corpus, _ = _synthesise(TRUE_CONFUSIONS, TRUE_PRIORS, n_items=300, seed=47)
    out = ds.smoothing_sensitivity(corpus, [0.0, 0.5])
    assert set(out) == {"alpha=0.0", "alpha=0.5"}
    assert set(out["alpha=0.0"]) == set(corpus.raters)


# --------------------------------------------------------------------------
# CLI end-to-end
# --------------------------------------------------------------------------


def test_main_runs_end_to_end_and_writes_json(tmp_path: Path, capsys) -> None:
    dossiers = []
    rng = random.Random(101)
    for i in range(120):
        k = rng.choices([0, 1, 2], weights=TRUE_PRIORS)[0]
        verdicts = {}
        for rater, matrix in TRUE_CONFUSIONS.items():
            if rng.random() < 0.25:
                continue
            label = rng.choices([0, 1, 2], weights=matrix[k])[0]
            verdicts[rater] = ds.LATENT_LABELS[label]
        if len(verdicts) < 2:
            continue
        dossiers.append({"task_id": f"t{i}", "head_sha": f"h{i}", "reviewer_verdicts": verdicts})

    corpus_path = _write_corpus(tmp_path, dossiers)
    out = tmp_path / "report.json"
    rc = ds.main(
        [
            "--corpus",
            str(corpus_path),
            "--restarts",
            "3",
            "--bootstrap",
            "5",
            "--json",
            str(out),
        ]
    )
    assert rc == 0
    report = json.loads(out.read_text())
    assert report["n_raters"] == 4
    assert set(report["confusion_matrices"]) == set(TRUE_CONFUSIONS)
    assert report["restart_stability"]["restarts"] == 3
    assert report["bootstrap_ci_95"]["sharp"]["decoded_accuracy"]
    stdout = capsys.readouterr().out
    assert "DAWID-SKENE" in stdout
    assert "WHAT THIS DOES AND DOES NOT ESTABLISH" in stdout


def test_matrix_rows_are_distinctly_labelled() -> None:
    """'accept-with-findings'[:6] == 'accept' - a naive truncation renders two
    different latent classes with the same row label."""
    matrix = [[0.7, 0.2, 0.1], [0.1, 0.8, 0.1], [0.0, 0.3, 0.7]]
    lines = ds._fmt_matrix(matrix, ds.LATENT_LABELS)
    row_labels = [line.strip().split()[0] for line in lines[1:]]
    assert len(set(row_labels)) == 3, row_labels

    lines4 = ds._fmt_matrix(
        [row + [0.0] for row in matrix], (*ds.LATENT_LABELS, ds.NONRESPONSE_EMISSION)
    )
    assert len(lines4[0].split()) == 4


def test_main_reports_missing_corpus(tmp_path: Path, capsys) -> None:
    rc = ds.main(["--corpus", str(tmp_path / "nope.json")])
    assert rc == 1
    assert "corpus not found" in capsys.readouterr().err
