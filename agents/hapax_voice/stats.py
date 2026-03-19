"""Bayesian analysis functions for conversational continuity proofs.

Pure functions for sequential hypothesis testing and correlation analysis
across SCED experiment phases. Uses scipy.special for Beta CDF to avoid
the scipy.stats init crash with torch (scipy 1.17 + torch compatibility issue).
"""

from __future__ import annotations

import math

import numpy as np
from scipy.special import betainc


def _beta_cdf(x: float, a: float, b: float) -> float:
    """CDF of Beta(a, b) at x, using regularized incomplete beta function."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    return float(betainc(a, b, x))


def _norm_pdf(x: float, loc: float = 0.0, scale: float = 1.0) -> float:
    """PDF of Normal(loc, scale) at x."""
    z = (x - loc) / scale
    return float(np.exp(-0.5 * z * z) / (scale * math.sqrt(2 * math.pi)))


def _pearsonr(x: list[float], y: list[float]) -> float:
    """Pearson correlation coefficient."""
    ax = np.array(x, dtype=np.float64)
    ay = np.array(y, dtype=np.float64)
    ax_m = ax - ax.mean()
    ay_m = ay - ay.mean()
    num = float(np.sum(ax_m * ay_m))
    den = float(np.sqrt(np.sum(ax_m**2) * np.sum(ay_m**2)))
    if den < 1e-12:
        return 0.0
    return num / den


def bayes_factor(
    successes: int,
    trials: int,
    prior_a: float = 2.0,
    prior_b: float = 2.0,
    rope_low: float = 0.45,
    rope_high: float = 0.55,
) -> float:
    """Beta-binomial Bayes Factor: mass outside ROPE / mass inside ROPE.

    Posterior = Beta(prior_a + successes, prior_b + failures).
    BF = P(theta outside ROPE | data) / P(theta inside ROPE | data).
    """
    failures = trials - successes
    post_a = prior_a + successes
    post_b = prior_b + failures

    mass_inside = _beta_cdf(rope_high, post_a, post_b) - _beta_cdf(rope_low, post_a, post_b)
    mass_outside = 1.0 - mass_inside

    if mass_inside < 1e-12:
        return float("inf")
    return mass_outside / mass_inside


def sequential_check(
    bf: float,
    n: int,
    max_n: int,
    bf_threshold: float = 10.0,
) -> str:
    """Sequential stopping rule for Bayesian SCED.

    Returns "continue", "stop_h1", "stop_h0", or "stop_max".
    """
    if n >= max_n:
        return "stop_max"
    if bf >= bf_threshold:
        return "stop_h1"
    if bf <= 1.0 / bf_threshold:
        return "stop_h0"
    return "continue"


def rope_check(
    successes: int,
    trials: int,
    prior_a: float = 2.0,
    prior_b: float = 2.0,
    rope_low: float = 0.45,
    rope_high: float = 0.55,
) -> dict[str, float]:
    """Posterior mass inside and outside ROPE.

    Returns {"inside": float, "outside": float}.
    """
    failures = trials - successes
    post_a = prior_a + successes
    post_b = prior_b + failures

    mass_inside = _beta_cdf(rope_high, post_a, post_b) - _beta_cdf(rope_low, post_a, post_b)
    return {"inside": mass_inside, "outside": 1.0 - mass_inside}


def bayes_correlation(
    x: list[float],
    y: list[float],
    prior_mu: float = 0.0,
    prior_sigma: float = 1.0,
) -> dict[str, float]:
    """Bayesian correlation: Pearson r → Fisher z → Normal prior update.

    Returns {"r", "posterior_mu", "posterior_sigma", "bf", "ci_95"}.
    """
    n = len(x)
    r = _pearsonr(x, y)

    # Fisher z-transform
    z_obs = math.atanh(max(-0.9999, min(0.9999, r)))
    se = 1.0 / math.sqrt(n - 3) if n > 3 else 1.0

    # Normal-Normal conjugate update
    prior_prec = 1.0 / (prior_sigma**2)
    data_prec = 1.0 / (se**2)
    post_prec = prior_prec + data_prec
    post_sigma = math.sqrt(1.0 / post_prec)
    post_mu = (prior_prec * math.atanh(prior_mu) + data_prec * z_obs) / post_prec

    # Back-transform posterior mean to r scale
    post_r = math.tanh(post_mu)

    # 95% CI in z-space, back-transformed
    ci_z_low = post_mu - 1.96 * post_sigma
    ci_z_high = post_mu + 1.96 * post_sigma
    ci_95 = (math.tanh(ci_z_low), math.tanh(ci_z_high))

    # Savage-Dickey BF at r=0 (z=0)
    prior_density_at_0 = _norm_pdf(0, loc=math.atanh(prior_mu), scale=prior_sigma)
    post_density_at_0 = _norm_pdf(0, loc=post_mu, scale=post_sigma)
    bf = prior_density_at_0 / post_density_at_0 if post_density_at_0 > 1e-12 else float("inf")

    return {
        "r": r,
        "posterior_mu": post_r,
        "posterior_sigma": post_sigma,
        "bf": bf,
        "ci_95": ci_95,
    }
