#!/usr/bin/env python3
"""Dawid-Skene EM over the review-dossier corpus: recover per-reviewer confusion
matrices from agreement patterns alone, with no ground truth.

Dawid, A. P., & Skene, A. M. (1979). "Maximum Likelihood Estimation of Observer
Error-Rates Using the EM Algorithm." Applied Statistics 28(1), 20-28.

The estate's review corpus (``~/.cache/hapax/coord/review-receipts.json``) is
exactly the input format the 1979 paper assumes: many items, each judged by a
subset of a small fixed panel, on a small ordinal label set, with no adjudicated
truth anywhere. DS treats the true label of each item as a latent variable and
alternates:

  E-step  posterior over each item's latent class given current error rates
  M-step  per-rater confusion matrices and class prior given current posteriors

WHAT THIS ESTABLISHES AND WHAT IT DOES NOT
------------------------------------------
DS recovers a *consistency structure*: which raters' verdicts are predictable
functions of a shared latent variable, and how each rater distorts it. The
latent variable is whatever the panel co-varies on. It is NOT correctness. If
every rater shares a bias, DS recovers the consensus bias as "truth" and scores
the one dissenter as unreliable. Read every number below as "agreement with the
panel's shared signal", never as "accuracy".

Labels
------
Latent and primary-observed alphabet is the ordinal verdict scale:

    0 block, 1 accept-with-findings, 2 accept

``invalid-output`` and ``quota-wall`` are harness failures, not judgements. The
primary model drops them. ``--nonresponse emit`` instead models them as a fourth
*observed* emission with no latent counterpart, which is the honest treatment
when non-response correlates with item difficulty (it does: oversized diffs get
truncated and score invalid-output).

Usage
-----
    uv run python scripts/dawid_skene_review_corpus.py
    uv run python scripts/dawid_skene_review_corpus.py --bootstrap 400 --json out.json
    uv run python scripts/dawid_skene_review_corpus.py --nonresponse emit

Pure standard library; no numpy required (the problem is 209 x 4 x 3).
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import random
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CORPUS = Path.home() / ".cache/hapax/coord/review-receipts.json"

# Ordinal verdict scale. Index is the ordinal value; strictness decreases rightward.
LATENT_LABELS = ("block", "accept-with-findings", "accept")
# Emissions that are harness failures rather than judgements about the item.
NONRESPONSE_LABELS = ("invalid-output", "quota-wall")
NONRESPONSE_EMISSION = "no-response"

Triple = tuple[str, str, int]  # (item_id, rater, observed label index)


# --------------------------------------------------------------------------
# corpus extraction
# --------------------------------------------------------------------------


@dataclass
class Corpus:
    """Extracted (item, rater, verdict) triples plus provenance."""

    triples: list[Triple]
    observed_labels: tuple[str, ...]
    items: list[str] = field(default_factory=list)
    raters: list[str] = field(default_factory=list)
    generated_at: str | None = None
    source: str | None = None
    dropped_nonresponse: int = 0

    def __post_init__(self) -> None:
        if not self.items:
            self.items = sorted({i for i, _, _ in self.triples})
        if not self.raters:
            self.raters = sorted({r for _, r, _ in self.triples})

    @property
    def n_latent(self) -> int:
        return len(LATENT_LABELS)

    @property
    def n_observed(self) -> int:
        return len(self.observed_labels)

    def by_item(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = defaultdict(dict)
        for item, rater, label in self.triples:
            out[item][rater] = label
        return {item: out[item] for item in self.items}

    def coverage(self) -> dict[str, int]:
        return dict(Counter(r for _, r, _ in self.triples))

    def pair_overlap(self) -> dict[tuple[str, str], int]:
        counts: Counter[tuple[str, str]] = Counter()
        for raters in self.by_item().values():
            for a, b in itertools.combinations(sorted(raters), 2):
                counts[(a, b)] += 1
        return dict(counts)


def load_corpus(path: Path, *, nonresponse: str = "drop") -> Corpus:
    """Extract (item, rater, verdict) triples from a review-receipts.json file.

    nonresponse: "drop" removes invalid-output/quota-wall seats entirely;
    "emit" keeps them as a single extra observed emission.
    """
    if nonresponse not in {"drop", "emit"}:
        raise ValueError(f"nonresponse must be 'drop' or 'emit', got {nonresponse!r}")

    payload = json.loads(path.read_text())
    dossiers = payload.get("dossiers", [])

    observed = list(LATENT_LABELS)
    if nonresponse == "emit":
        observed.append(NONRESPONSE_EMISSION)
    index = {label: i for i, label in enumerate(observed)}

    triples: list[Triple] = []
    dropped = 0
    for dossier in dossiers:
        # task_id is unique per dossier in this corpus, but pair it with head_sha
        # so a re-review of the same task at a new head is a distinct item.
        item = f"{dossier.get('task_id')}@{dossier.get('head_sha')}"
        for rater, verdict in (dossier.get("reviewer_verdicts") or {}).items():
            if verdict in NONRESPONSE_LABELS:
                if nonresponse == "drop":
                    dropped += 1
                    continue
                triples.append((item, rater, index[NONRESPONSE_EMISSION]))
                continue
            if verdict not in index:
                raise ValueError(f"unknown verdict {verdict!r} on {item}")
            triples.append((item, rater, index[verdict]))

    return Corpus(
        triples=triples,
        observed_labels=tuple(observed),
        generated_at=payload.get("generated_at"),
        source=str(path),
        dropped_nonresponse=dropped,
    )


# --------------------------------------------------------------------------
# Dawid-Skene EM
# --------------------------------------------------------------------------


@dataclass
class DSFit:
    priors: list[float]
    confusions: dict[str, list[list[float]]]  # rater -> latent x observed
    posteriors: dict[str, list[float]]  # item -> latent posterior
    loglik: float
    loglik_trace: list[float]
    iterations: int
    converged: bool
    items: list[str]
    raters: list[str]
    observed_labels: tuple[str, ...]


def _logsumexp(values: list[float]) -> float:
    hi = max(values)
    if hi == -math.inf:
        return -math.inf
    return hi + math.log(sum(math.exp(v - hi) for v in values))


def _majority_vote_init(
    by_item: dict[str, dict[str, int]], items: list[str], n_latent: int
) -> dict[str, list[float]]:
    """Initialise item posteriors from majority vote, ties split evenly.

    Observed labels beyond the latent alphabet (i.e. no-response) carry no vote.
    """
    posteriors: dict[str, list[float]] = {}
    for item in items:
        votes = Counter(label for label in by_item[item].values() if label < n_latent)
        if not votes:
            posteriors[item] = [1.0 / n_latent] * n_latent
            continue
        total = sum(votes.values())
        posteriors[item] = [votes.get(k, 0) / total for k in range(n_latent)]
    return posteriors


def _random_init(items: list[str], n_latent: int, rng: random.Random) -> dict[str, list[float]]:
    posteriors: dict[str, list[float]] = {}
    for item in items:
        draw = [rng.gammavariate(1.0, 1.0) for _ in range(n_latent)]
        total = sum(draw)
        posteriors[item] = [d / total for d in draw]
    return posteriors


def _m_step(
    by_item: dict[str, dict[str, int]],
    posteriors: dict[str, list[float]],
    raters: list[str],
    n_latent: int,
    n_observed: int,
    alpha: float,
) -> tuple[list[float], dict[str, list[list[float]]]]:
    n_items = len(posteriors)
    priors = [sum(posteriors[i][k] for i in posteriors) / n_items for k in range(n_latent)]

    tally: dict[str, list[list[float]]] = {
        r: [[0.0] * n_observed for _ in range(n_latent)] for r in raters
    }
    for item, ratings in by_item.items():
        post = posteriors[item]
        for rater, label in ratings.items():
            row = tally[rater]
            for k in range(n_latent):
                row[k][label] += post[k]

    confusions: dict[str, list[list[float]]] = {}
    for rater in raters:
        matrix = []
        for k in range(n_latent):
            row = tally[rater][k]
            denom = sum(row) + alpha * n_observed
            if denom <= 0.0:
                # Rater never plausibly saw this latent class: uninformative row.
                matrix.append([1.0 / n_observed] * n_observed)
                continue
            matrix.append([(c + alpha) / denom for c in row])
        confusions[rater] = matrix
    return priors, confusions


def _e_step(
    by_item: dict[str, dict[str, int]],
    priors: list[float],
    confusions: dict[str, list[list[float]]],
    n_latent: int,
) -> tuple[dict[str, list[float]], float]:
    posteriors: dict[str, list[float]] = {}
    loglik = 0.0
    log_prior = [math.log(p) if p > 0 else -math.inf for p in priors]
    for item, ratings in by_item.items():
        logs = list(log_prior)
        for rater, label in ratings.items():
            matrix = confusions[rater]
            for k in range(n_latent):
                p = matrix[k][label]
                logs[k] += math.log(p) if p > 0 else -math.inf
        norm = _logsumexp(logs)
        loglik += norm
        posteriors[item] = [math.exp(v - norm) for v in logs]
    return posteriors, loglik


def dawid_skene(
    corpus: Corpus,
    *,
    alpha: float = 0.1,
    max_iter: int = 500,
    tol: float = 1e-10,
    init: dict[str, list[float]] | None = None,
    align: bool = True,
) -> DSFit:
    """Fit the Dawid-Skene model.

    ``alpha`` is a Laplace pseudo-count on confusion rows, which keeps sparse
    cells (glm has 5 blocks in 121 seats) from pinning the likelihood at a
    boundary. alpha=0 is textbook DS.
    """
    by_item = corpus.by_item()
    items = corpus.items
    raters = corpus.raters
    n_latent = corpus.n_latent
    n_observed = corpus.n_observed

    posteriors = init or _majority_vote_init(by_item, items, n_latent)
    priors: list[float] = [1.0 / n_latent] * n_latent
    confusions: dict[str, list[list[float]]] = {}
    prev = -math.inf
    loglik = -math.inf
    trace: list[float] = []
    converged = False

    while len(trace) < max_iter:
        priors, confusions = _m_step(by_item, posteriors, raters, n_latent, n_observed, alpha)
        posteriors, loglik = _e_step(by_item, priors, confusions, n_latent)
        trace.append(loglik)
        if abs(loglik - prev) < tol:
            converged = True
            break
        prev = loglik

    fit = DSFit(
        priors=priors,
        confusions=confusions,
        posteriors=posteriors,
        loglik=loglik,
        loglik_trace=trace,
        iterations=len(trace),
        converged=converged,
        items=items,
        raters=raters,
        observed_labels=corpus.observed_labels,
    )
    return align_latent_classes(fit, corpus) if align else fit


def align_latent_classes(fit: DSFit, corpus: Corpus) -> DSFit:
    """DS latent classes are unlabelled. Permute them so latent class k means
    observed verdict k, choosing the permutation that maximises coverage-weighted
    pooled diagonal mass."""
    n_latent = len(fit.priors)
    coverage = corpus.coverage()

    best_perm = tuple(range(n_latent))
    best_score = -math.inf
    for perm in itertools.permutations(range(n_latent)):
        # perm[k] = current latent index that should be relabelled to k
        score = 0.0
        for rater, matrix in fit.confusions.items():
            w = coverage.get(rater, 0)
            score += w * sum(matrix[perm[k]][k] for k in range(n_latent))
        if score > best_score:
            best_score = score
            best_perm = perm

    if best_perm == tuple(range(n_latent)):
        return fit

    fit.priors = [fit.priors[best_perm[k]] for k in range(n_latent)]
    fit.confusions = {
        r: [m[best_perm[k]] for k in range(n_latent)] for r, m in fit.confusions.items()
    }
    fit.posteriors = {
        i: [p[best_perm[k]] for k in range(n_latent)] for i, p in fit.posteriors.items()
    }
    return fit


# --------------------------------------------------------------------------
# reliability metrics derived from the fit
# --------------------------------------------------------------------------


def rater_metrics(fit: DSFit, corpus: Corpus) -> dict[str, dict[str, float]]:
    """Per-rater reliability summaries.

    raw_agreement       P(rater emits the latent class's own label) - the DS
                        diagonal. Penalises systematic shift.
    decoded_accuracy    Bayes-optimal single-rater decode of the latent class,
                        i.e. accuracy AFTER correcting the rater's systematic
                        shift. This is the routing-relevant number: how much of
                        the panel signal is recoverable from this rater alone.
    mutual_information  bits shared between latent class and this rater's
                        emission. Bias-invariant: a perfectly shifted but
                        deterministic rater scores maximally.
    leniency            E[observed ordinal] - E[latent ordinal] over responded
                        emissions, in scale units. Positive = more permissive
                        than the latent class it is reporting on.
    n_eff_*             posterior mass of each latent class among the items this
                        rater actually judged - the effective sample size behind
                        that confusion row.
    """
    n_latent = len(fit.priors)
    coverage = corpus.coverage()
    n_response = len(LATENT_LABELS)
    by_item = corpus.by_item()

    metrics: dict[str, dict[str, float]] = {}
    for rater, matrix in fit.confusions.items():
        n_obs = len(matrix[0])
        raw = sum(fit.priors[k] * matrix[k][k] for k in range(n_latent))

        joint = [[fit.priors[k] * matrix[k][l] for l in range(n_obs)] for k in range(n_latent)]
        marg_obs = [sum(joint[k][l] for k in range(n_latent)) for l in range(n_obs)]

        decoded = sum(max(joint[k][l] for k in range(n_latent)) for l in range(n_obs))

        mi = 0.0
        for k in range(n_latent):
            for l in range(n_obs):
                pkl = joint[k][l]
                if pkl <= 0 or fit.priors[k] <= 0 or marg_obs[l] <= 0:
                    continue
                mi += pkl * math.log2(pkl / (fit.priors[k] * marg_obs[l]))

        responded = sum(joint[k][l] for k in range(n_latent) for l in range(n_response))
        if responded > 0:
            e_obs = (
                sum(l * joint[k][l] for k in range(n_latent) for l in range(n_response)) / responded
            )
            e_lat = (
                sum(k * joint[k][l] for k in range(n_latent) for l in range(n_response)) / responded
            )
            leniency = e_obs - e_lat
        else:
            leniency = 0.0

        n_eff = [0.0] * n_latent
        for item, ratings in by_item.items():
            if rater in ratings:
                for k in range(n_latent):
                    n_eff[k] += fit.posteriors[item][k]

        metrics[rater] = {
            "coverage": float(coverage.get(rater, 0)),
            "raw_agreement": raw,
            "decoded_accuracy": decoded,
            "mutual_information_bits": mi,
            "leniency": leniency,
            "n_eff_block": n_eff[0],
            "n_eff_findings": n_eff[1],
            "n_eff_accept": n_eff[2],
        }
    return metrics


def majority_class_baseline(fit: DSFit) -> float:
    return max(fit.priors)


def pairwise_strictness(corpus: Corpus) -> dict[str, dict[str, int]]:
    """Raw directional disagreement counts, for sanity-checking DS against the
    already-published finding (glm stricter than gemini on nearly every non-tie)."""
    n_response = len(LATENT_LABELS)
    out: dict[str, dict[str, int]] = {}
    for ratings in corpus.by_item().values():
        usable = {r: v for r, v in ratings.items() if v < n_response}
        for a, b in itertools.combinations(sorted(usable), 2):
            key = f"{a}/{b}"
            rec = out.setdefault(key, {"n": 0, "ties": 0, f"{a}_stricter": 0, f"{b}_stricter": 0})
            rec["n"] += 1
            if usable[a] < usable[b]:
                rec[f"{a}_stricter"] += 1
            elif usable[a] > usable[b]:
                rec[f"{b}_stricter"] += 1
            else:
                rec["ties"] += 1
    return out


# --------------------------------------------------------------------------
# identifiability diagnostics
# --------------------------------------------------------------------------


def restart_stability(
    corpus: Corpus, *, alpha: float, restarts: int, seed: int
) -> dict[str, object]:
    """Refit from random initialisations. If DS is identified on this corpus the
    likelihood surface should have one dominant mode and every restart should
    land on it."""
    rng = random.Random(seed)
    base = dawid_skene(corpus, alpha=alpha)
    logliks = [base.loglik]
    max_dev = 0.0
    for _ in range(restarts):
        init = _random_init(corpus.items, corpus.n_latent, rng)
        fit = dawid_skene(corpus, alpha=alpha, init=init)
        logliks.append(fit.loglik)
        for rater in corpus.raters:
            for k in range(corpus.n_latent):
                for l in range(corpus.n_observed):
                    dev = abs(fit.confusions[rater][k][l] - base.confusions[rater][k][l])
                    max_dev = max(max_dev, dev)
    return {
        "restarts": restarts,
        "loglik_best": max(logliks),
        "loglik_worst": min(logliks),
        "loglik_spread": max(logliks) - min(logliks),
        "max_confusion_deviation_from_mv_init": max_dev,
    }


def bootstrap_ci(
    corpus: Corpus, *, alpha: float, reps: int, seed: int
) -> dict[str, dict[str, list[float]]]:
    """Item-level nonparametric bootstrap. Items are the independent unit; the
    seats within an item are not."""
    rng = random.Random(seed)
    draws: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    keys = ("raw_agreement", "decoded_accuracy", "mutual_information_bits", "leniency")
    by_item = corpus.by_item()

    for _ in range(reps):
        sampled = [rng.choice(corpus.items) for _ in corpus.items]
        # Re-key duplicated draws so each resampled copy is an independent item.
        triples: list[Triple] = []
        for n, item in enumerate(sampled):
            for rater, label in by_item[item].items():
                triples.append((f"{item}#{n}", rater, label))
        replicate = Corpus(triples=triples, observed_labels=corpus.observed_labels)
        fit = dawid_skene(replicate, alpha=alpha)
        met = rater_metrics(fit, replicate)
        for rater, values in met.items():
            for key in keys:
                draws[rater][key].append(values[key])

    out: dict[str, dict[str, list[float]]] = {}
    for rater, per_key in draws.items():
        out[rater] = {}
        for key, values in per_key.items():
            if not values:
                continue
            values.sort()
            lo = values[max(0, int(0.025 * len(values)) - 1)]
            hi = values[min(len(values) - 1, int(0.975 * len(values)))]
            out[rater][key] = [lo, hi]
    return out


def posterior_confidence(fit: DSFit) -> dict[str, float]:
    """How decided the latent labels actually are. A corpus whose posteriors sit
    near the class prior has not been resolved by the data; it has been resolved
    by the prior."""
    maxes = [max(p) for p in fit.posteriors.values()]
    n = len(maxes)
    return {
        "mean_max_posterior": sum(maxes) / n,
        "fraction_above_0.90": sum(1 for m in maxes if m >= 0.90) / n,
        "fraction_above_0.99": sum(1 for m in maxes if m >= 0.99) / n,
        "fraction_below_0.60": sum(1 for m in maxes if m < 0.60) / n,
    }


def parameter_budget(corpus: Corpus) -> dict[str, float]:
    """Free parameters vs observations. DS needs each (rater, latent class) row
    to be backed by enough items; the global ratio is necessary, not sufficient."""
    k, m = corpus.n_latent, corpus.n_observed
    free = len(corpus.raters) * k * (m - 1) + (k - 1)
    return {
        "free_parameters": float(free),
        "observations": float(len(corpus.triples)),
        "observations_per_parameter": len(corpus.triples) / free,
    }


def vote_influence(fit: DSFit, corpus: Corpus) -> dict[str, dict[str, float]]:
    """How much does each rater's ballot move the recovered label?

    This is the check for the DS degeneracy that matters here: if one rater's
    confusion matrix is near-identity, the latent variable may simply BE that
    rater's verdict, and every other rater's "reliability" is then agreement with
    one rater rather than with a panel signal.

    The measurement holds the fitted priors and confusion matrices FIXED and
    re-runs only the E-step with the rater's likelihood term removed. That
    isolates the rater's influence on the labels.

    A leave-one-out *refit* cannot do this. Removing a rater from a panel of n
    also shrinks the panel to n-1, and DS is badly under-identified at n=2: on a
    synthetic 3-rater panel, refitting without one weak rater collapses the
    remaining near-perfect rater's recovered diagonal from 0.97 to 0.61. A refit
    therefore mixes "this rater defined the labels" with "the model got worse",
    and the two are not separable from the refit alone.
    """
    n_latent = corpus.n_latent
    log_prior = [math.log(p) if p > 0 else -math.inf for p in fit.priors]

    out: dict[str, dict[str, float]] = {}
    for rater in corpus.raters:
        flips = 0
        rated = 0
        l1_total = 0.0
        for item, ratings in corpus.by_item().items():
            if rater not in ratings:
                continue
            rated += 1
            logs = list(log_prior)
            for other, label in ratings.items():
                if other == rater:
                    continue
                matrix = fit.confusions[other]
                for k in range(n_latent):
                    p = matrix[k][label]
                    logs[k] += math.log(p) if p > 0 else -math.inf
            norm = _logsumexp(logs)
            without = [math.exp(v - norm) for v in logs]
            full_post = fit.posteriors[item]
            l1_total += sum(abs(without[k] - full_post[k]) for k in range(n_latent))
            if max(range(n_latent), key=lambda k: without[k]) != max(
                range(n_latent), key=lambda k: full_post[k]
            ):
                flips += 1
        out[rater] = {
            "items_rated": float(rated),
            "map_flip_rate_without_this_vote": flips / rated if rated else 0.0,
            "mean_posterior_l1_shift": l1_total / rated if rated else 0.0,
        }
    return out


def smoothing_sensitivity(corpus: Corpus, alphas: list[float]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for alpha in alphas:
        fit = dawid_skene(corpus, alpha=alpha)
        met = rater_metrics(fit, corpus)
        out[f"alpha={alpha}"] = {r: round(v["decoded_accuracy"], 4) for r, v in sorted(met.items())}
    return out


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------


SHORT_LABELS = {
    "block": "block",
    "accept-with-findings": "findings",
    "accept": "accept",
    NONRESPONSE_EMISSION: "no-resp",
}


def _fmt_matrix(matrix: list[list[float]], observed: tuple[str, ...]) -> list[str]:
    lines = ["          " + "".join(f"{SHORT_LABELS[lab]:>11}" for lab in observed)]
    for k, label in enumerate(LATENT_LABELS):
        cells = "".join(f"{matrix[k][l]:>11.3f}" for l in range(len(observed)))
        lines.append(f"  {SHORT_LABELS[label]:<8}{cells}")
    return lines


def build_report(
    corpus: Corpus,
    fit: DSFit,
    metrics: dict[str, dict[str, float]],
    *,
    bootstrap: dict | None = None,
    stability: dict | None = None,
    sensitivity: dict | None = None,
) -> dict:
    return {
        "posterior_confidence": posterior_confidence(fit),
        "parameter_budget": parameter_budget(corpus),
        "vote_influence": vote_influence(fit, corpus),
        "source": corpus.source,
        "corpus_generated_at": corpus.generated_at,
        "n_items": len(corpus.items),
        "n_raters": len(corpus.raters),
        "n_triples": len(corpus.triples),
        "dropped_nonresponse_seats": corpus.dropped_nonresponse,
        "observed_labels": list(corpus.observed_labels),
        "latent_labels": list(LATENT_LABELS),
        "coverage": corpus.coverage(),
        "pair_overlap": {f"{a}/{b}": n for (a, b), n in sorted(corpus.pair_overlap().items())},
        "converged": fit.converged,
        "iterations": fit.iterations,
        "loglik": fit.loglik,
        "latent_class_prior": {LATENT_LABELS[k]: fit.priors[k] for k in range(len(fit.priors))},
        "majority_class_baseline": majority_class_baseline(fit),
        "confusion_matrices": {
            r: {
                LATENT_LABELS[k]: {
                    corpus.observed_labels[l]: fit.confusions[r][k][l]
                    for l in range(corpus.n_observed)
                }
                for k in range(corpus.n_latent)
            }
            for r in corpus.raters
        },
        "rater_metrics": metrics,
        "pairwise_strictness": pairwise_strictness(corpus),
        "bootstrap_ci_95": bootstrap,
        "restart_stability": stability,
        "smoothing_sensitivity": sensitivity,
    }


def print_report(report: dict, fit: DSFit, corpus: Corpus) -> None:
    w = sys.stdout.write
    w("=" * 78 + "\n")
    w("DAWID-SKENE (1979) OVER THE REVIEW-DOSSIER CORPUS\n")
    w("=" * 78 + "\n")
    w(f"source              {report['source']}\n")
    w(f"corpus generated_at {report['corpus_generated_at']}\n")
    w(
        f"items {report['n_items']}   raters {report['n_raters']}   "
        f"seat-verdicts used {report['n_triples']}   "
        f"non-response seats dropped {report['dropped_nonresponse_seats']}\n"
    )
    w(f"observed alphabet   {report['observed_labels']}\n")
    w(
        f"EM                  converged={report['converged']} "
        f"iters={report['iterations']} loglik={report['loglik']:.4f}\n"
    )

    w("\nCOVERAGE (items each rater actually judged)\n")
    for rater, n in sorted(report["coverage"].items(), key=lambda kv: -kv[1]):
        w(f"  {rater:<8} {n:>4} / {report['n_items']}  ({n / report['n_items']:.1%})\n")
    w("\nPAIRWISE OVERLAP (items judged by both)\n")
    for pair, n in sorted(report["pair_overlap"].items(), key=lambda kv: -kv[1]):
        w(f"  {pair:<20} {n:>4}\n")

    w("\nLATENT CLASS PRIOR (what DS thinks the panel is tracking)\n")
    for label, p in report["latent_class_prior"].items():
        w(f"  {label:<22} {p:.4f}\n")
    w(f"  majority-class baseline {report['majority_class_baseline']:.4f}\n")

    w("\nPER-RATER CONFUSION MATRICES  P(observed | latent)\n")
    for rater in sorted(corpus.raters):
        w(f"\n  {rater}   (rows = latent class, columns = what {rater} says)\n")
        for line in _fmt_matrix(fit.confusions[rater], corpus.observed_labels):
            w("  " + line + "\n")

    w("\nRELIABILITY (all relative to the panel's shared signal, not to truth)\n")
    header = (
        f"  {'rater':<8}{'cov':>5}{'raw':>8}{'decoded':>9}{'MI bits':>9}"
        f"{'leniency':>10}{'n_eff blk':>11}{'n_eff fnd':>11}{'n_eff acc':>11}\n"
    )
    w(header)
    w("  " + "-" * (len(header) - 3) + "\n")
    ordered = sorted(report["rater_metrics"].items(), key=lambda kv: -kv[1]["decoded_accuracy"])
    for rater, m in ordered:
        w(
            f"  {rater:<8}{int(m['coverage']):>5}{m['raw_agreement']:>8.3f}"
            f"{m['decoded_accuracy']:>9.3f}{m['mutual_information_bits']:>9.3f}"
            f"{m['leniency']:>+10.3f}{m['n_eff_block']:>11.1f}"
            f"{m['n_eff_findings']:>11.1f}{m['n_eff_accept']:>11.1f}\n"
        )

    if report.get("bootstrap_ci_95"):
        w("\nBOOTSTRAP 95% CI (item-level resampling)\n")
        for rater, cis in sorted(report["bootstrap_ci_95"].items()):
            parts = ", ".join(f"{k}=[{lo:.3f}, {hi:.3f}]" for k, (lo, hi) in sorted(cis.items()))
            w(f"  {rater:<8} {parts}\n")

    w("\nIDENTIFIABILITY\n")
    budget = report["parameter_budget"]
    w(
        f"  free parameters {int(budget['free_parameters'])}   "
        f"observations {int(budget['observations'])}   "
        f"obs/param {budget['observations_per_parameter']:.1f}\n"
    )
    conf = report["posterior_confidence"]
    w(
        f"  latent labels decided: mean max posterior {conf['mean_max_posterior']:.3f}, "
        f">=0.90 on {conf['fraction_above_0.90']:.1%}, "
        f"<0.60 on {conf['fraction_below_0.60']:.1%} of items\n"
    )
    if report.get("restart_stability"):
        s = report["restart_stability"]
        w(
            f"  {s['restarts']} random restarts: loglik spread {s['loglik_spread']:.6f}, "
            f"max |delta confusion| vs majority-vote init "
            f"{s['max_confusion_deviation_from_mv_init']:.4f}\n"
        )
    w("  vote influence (does one rater DEFINE the labels?  model held fixed)\n")
    for rater, rec in sorted(
        report["vote_influence"].items(),
        key=lambda kv: -kv[1]["map_flip_rate_without_this_vote"],
    ):
        w(
            f"    {rater:<8} removing its ballot flips the label on "
            f"{rec['map_flip_rate_without_this_vote']:.1%} of the "
            f"{int(rec['items_rated'])} items it rated   "
            f"mean posterior L1 shift {rec['mean_posterior_l1_shift']:.3f}\n"
        )

    if report.get("smoothing_sensitivity"):
        w("\nSMOOTHING SENSITIVITY (decoded accuracy vs Laplace alpha)\n")
        for alpha, per_rater in report["smoothing_sensitivity"].items():
            parts = "  ".join(f"{r}={v:.3f}" for r, v in per_rater.items())
            w(f"  {alpha:<12} {parts}\n")

    w("\nSANITY CHECK vs PUBLISHED DIRECTIONAL FINDING\n")
    for pair, rec in sorted(report["pairwise_strictness"].items()):
        a, b = pair.split("/")
        nonties = rec[f"{a}_stricter"] + rec[f"{b}_stricter"]
        w(
            f"  {pair:<20} n={rec['n']:>4} non-ties={nonties:>3}  "
            f"{a} stricter {rec[f'{a}_stricter']:>3}   {b} stricter {rec[f'{b}_stricter']:>3}\n"
        )
    len_order = sorted(report["rater_metrics"].items(), key=lambda kv: kv[1]["leniency"])
    w(
        "  DS leniency ordering (strict -> lenient): "
        + " < ".join(f"{r}({m['leniency']:+.3f})" for r, m in len_order)
        + "\n"
    )

    w("\nWHAT THIS DOES AND DOES NOT ESTABLISH\n")
    w(
        "  DOES: recovers a consistency structure - a latent variable the panel\n"
        "  co-varies on, and each rater's systematic distortion of it.\n"
        "  DOES NOT: establish correctness. No ground truth is joined to this\n"
        "  corpus. If all raters share a bias, DS recovers the consensus bias as\n"
        "  'truth' and scores the lone dissenter as unreliable. Read every number\n"
        "  as agreement-with-panel-signal.\n"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    ap.add_argument("--alpha", type=float, default=0.1, help="Laplace pseudo-count")
    ap.add_argument(
        "--nonresponse",
        choices=("drop", "emit"),
        default="drop",
        help="invalid-output/quota-wall: drop the seat, or model as a 4th emission",
    )
    ap.add_argument("--bootstrap", type=int, default=0, help="bootstrap replicates")
    ap.add_argument("--restarts", type=int, default=25)
    ap.add_argument("--seed", type=int, default=20260810)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args(argv)

    if not args.corpus.exists():
        print(f"corpus not found: {args.corpus}", file=sys.stderr)
        return 1

    corpus = load_corpus(args.corpus, nonresponse=args.nonresponse)
    if not corpus.triples:
        print("corpus contains no usable seat-verdicts", file=sys.stderr)
        return 1

    fit = dawid_skene(corpus, alpha=args.alpha)
    metrics = rater_metrics(fit, corpus)

    stability = (
        restart_stability(corpus, alpha=args.alpha, restarts=args.restarts, seed=args.seed)
        if args.restarts
        else None
    )
    boot = (
        bootstrap_ci(corpus, alpha=args.alpha, reps=args.bootstrap, seed=args.seed)
        if args.bootstrap
        else None
    )
    sensitivity = smoothing_sensitivity(corpus, [0.0, 0.1, 0.5, 1.0])

    report = build_report(
        corpus, fit, metrics, bootstrap=boot, stability=stability, sensitivity=sensitivity
    )
    print_report(report, fit, corpus)

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2, sort_keys=True))
        print(f"\nJSON written to {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
