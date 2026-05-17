"""Information Density Field — universal perception-to-automation primitive.

Computes per-source information density scores from three complementary
signals: Bayesian surprise (KL divergence), BOCPD novelty (change-point
probability), Shannon entropy (activity level), and mutual information
(contextual relevance).

The density field is a shared-memory structure that consumers (stimmung,
director, cognitive system, impingement emission) READ but never WRITE
back to. Bad density scores cause bad decisions, not state corruption.

Every source participates. No source is excluded by design — information
density determines value, not curation. A source with zero density
contributes nothing and costs almost nothing to compute.

Theoretical foundation: the density field IS the Varelian gradient.
Sense-making is response to information gradients. Thompson sampling
IS active inference. The affordance pipeline IS the sense-making loop.
"""

from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DENSITY_FIELD_SHM = Path("/dev/shm/hapax-density-field/state.json")

W_SURPRISE = 0.3
W_NOVELTY = 0.3
W_ACTIVITY = 0.2
W_RELEVANCE = 0.2


@dataclass
class SourceDensity:
    source_id: str
    density: float = 0.0
    surprise: float = 0.0
    novelty: float = 0.0
    activity: float = 0.0
    relevance: float = 0.0
    trend: float = 0.0
    confidence: float = 0.0
    timestamp: float = 0.0

    def compute_density(self) -> float:
        self.density = (
            W_SURPRISE * self.surprise
            + W_NOVELTY * self.novelty
            + W_ACTIVITY * self.activity
            + W_RELEVANCE * self.relevance
        )
        return self.density

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "density": round(self.density, 4),
            "surprise": round(self.surprise, 4),
            "novelty": round(self.novelty, 4),
            "activity": round(self.activity, 4),
            "relevance": round(self.relevance, 4),
            "trend": round(self.trend, 4),
            "confidence": round(self.confidence, 4),
            "timestamp": self.timestamp,
        }


@dataclass
class BayesianSurpriseModel:
    """Normal-Inverse-Gamma online model for Bayesian surprise.

    Maintains sufficient statistics for a Gaussian observation model.
    Surprise = KL divergence between posterior and prior after each
    observation. Normalized to [0, 1] via sigmoid squash.
    """

    mu: float = 0.0
    kappa: float = 1.0
    alpha: float = 1.0
    beta: float = 1.0
    lambda_sigmoid: float = 1.0
    forgetting_factor: float = 0.999

    def update(self, observation: float) -> float:
        """Update model with observation, return surprise in [0, 1]."""
        kappa_new = self.kappa + 1
        mu_new = (self.kappa * self.mu + observation) / kappa_new
        alpha_new = self.alpha + 0.5
        beta_new = self.beta + self.kappa * (observation - self.mu) ** 2 / (2 * kappa_new)

        kl = _kl_nig(
            mu_new,
            kappa_new,
            alpha_new,
            beta_new,
            self.mu,
            self.kappa,
            self.alpha,
            self.beta,
        )

        self.mu = mu_new
        self.kappa = kappa_new * self.forgetting_factor
        self.alpha = alpha_new
        self.beta = beta_new

        return 1.0 - math.exp(-self.lambda_sigmoid * max(0.0, kl))


@dataclass
class BOCPDModel:
    """Bayesian Online Change Point Detection (Adams & MacKay 2007).

    Maintains a distribution over run lengths. Returns the change-point
    probability P(r_t = 0) at each step — naturally in [0, 1].
    """

    hazard: float = 1 / 200
    max_run_lengths: int = 200
    run_length_probs: list[float] = field(default_factory=lambda: [1.0])
    nig_params: list[tuple[float, float, float, float]] = field(
        default_factory=lambda: [(0.0, 1.0, 1.0, 1.0)]
    )

    def update(self, observation: float) -> float:
        """Update with observation, return change-point probability."""
        n = len(self.run_length_probs)
        pred_probs = []
        for i in range(n):
            mu, kappa, alpha, beta = self.nig_params[i]
            pred_probs.append(_student_t_pdf(observation, mu, kappa, alpha, beta))

        growth_probs = []
        for i in range(n):
            growth_probs.append(self.run_length_probs[i] * pred_probs[i] * (1 - self.hazard))

        cp_prob = sum(self.run_length_probs[i] * pred_probs[i] * self.hazard for i in range(n))

        new_probs = [cp_prob] + growth_probs
        total = sum(new_probs)
        if total > 0:
            new_probs = [p / total for p in new_probs]

        new_nig = [(0.0, 1.0, 1.0, 1.0)]
        for i in range(n):
            mu, kappa, alpha, beta = self.nig_params[i]
            kappa_new = kappa + 1
            mu_new = (kappa * mu + observation) / kappa_new
            alpha_new = alpha + 0.5
            beta_new = beta + kappa * (observation - mu) ** 2 / (2 * kappa_new)
            new_nig.append((mu_new, kappa_new, alpha_new, beta_new))

        if len(new_probs) > self.max_run_lengths:
            new_probs = new_probs[: self.max_run_lengths]
            new_nig = new_nig[: self.max_run_lengths]
            total = sum(new_probs)
            if total > 0:
                new_probs = [p / total for p in new_probs]

        self.run_length_probs = new_probs
        self.nig_params = new_nig

        return new_probs[0] if new_probs else 0.0


@dataclass
class EntropyModel:
    """Rolling histogram for Shannon entropy computation."""

    bins: int = 64
    histogram: list[float] = field(default_factory=list)
    decay: float = 0.95

    def __post_init__(self) -> None:
        if not self.histogram:
            self.histogram = [0.0] * self.bins

    def update(self, observation: float, obs_min: float = -1.0, obs_max: float = 1.0) -> float:
        """Update histogram, return normalized entropy in [0, 1]."""
        self.histogram = [h * self.decay for h in self.histogram]
        idx = int((observation - obs_min) / max(obs_max - obs_min, 1e-10) * (self.bins - 1))
        idx = max(0, min(self.bins - 1, idx))
        self.histogram[idx] += 1.0

        total = sum(self.histogram)
        if total < 1e-10:
            return 0.0

        entropy = 0.0
        log_bins = math.log2(self.bins) if self.bins > 1 else 1.0
        for h in self.histogram:
            p = h / total
            if p > 1e-10:
                entropy -= p * math.log2(p)

        return entropy / log_bins


@dataclass
class SourceModel:
    """Complete density model for a single information source."""

    source_id: str
    surprise_model: BayesianSurpriseModel = field(default_factory=BayesianSurpriseModel)
    bocpd_model: BOCPDModel = field(default_factory=BOCPDModel)
    entropy_model: EntropyModel = field(default_factory=EntropyModel)
    last_density: SourceDensity = field(default_factory=lambda: SourceDensity(source_id=""))
    obs_min: float = -1.0
    obs_max: float = 1.0

    def __post_init__(self) -> None:
        self.last_density = SourceDensity(source_id=self.source_id)

    def update(self, observation: float, relevance: float = 0.0) -> SourceDensity:
        """Update all models with a new observation, return density."""
        surprise = self.surprise_model.update(observation)
        novelty = self.bocpd_model.update(observation)
        activity = self.entropy_model.update(observation, self.obs_min, self.obs_max)

        prev = self.last_density.density
        density = SourceDensity(
            source_id=self.source_id,
            surprise=surprise,
            novelty=novelty,
            activity=activity,
            relevance=relevance,
            confidence=1.0,
            timestamp=time.time(),
        )
        density.compute_density()
        density.trend = density.density - prev
        self.last_density = density
        return density


class InformationDensityField:
    """The global information density field.

    Maintains per-source SourceModels, updates them with observations,
    and writes the aggregate state to SHM for consumers.
    """

    def __init__(self) -> None:
        self._sources: dict[str, SourceModel] = {}
        self._last_write: float = 0.0

    def register_source(
        self,
        source_id: str,
        *,
        obs_min: float = -1.0,
        obs_max: float = 1.0,
        hazard: float = 1 / 200,
        sigmoid_lambda: float = 1.0,
    ) -> None:
        self._sources[source_id] = SourceModel(
            source_id=source_id,
            surprise_model=BayesianSurpriseModel(lambda_sigmoid=sigmoid_lambda),
            bocpd_model=BOCPDModel(hazard=hazard),
            obs_min=obs_min,
            obs_max=obs_max,
        )

    def update(self, source_id: str, observation: float, relevance: float = 0.0) -> SourceDensity:
        if source_id not in self._sources:
            self.register_source(source_id)
        return self._sources[source_id].update(observation, relevance)

    def get_density(self, source_id: str) -> SourceDensity | None:
        model = self._sources.get(source_id)
        return model.last_density if model else None

    def all_densities(self) -> dict[str, SourceDensity]:
        return {sid: m.last_density for sid, m in self._sources.items()}

    def aggregate_density(self) -> float:
        densities = [m.last_density.density for m in self._sources.values()]
        return sum(densities) / max(len(densities), 1)

    def top_sources(self, n: int = 5) -> list[SourceDensity]:
        return sorted(
            (m.last_density for m in self._sources.values()),
            key=lambda d: d.density,
            reverse=True,
        )[:n]

    def write_shm(self) -> None:
        now = time.time()
        payload = {
            "timestamp": now,
            "aggregate_density": round(self.aggregate_density(), 4),
            "source_count": len(self._sources),
            "sources": {sid: d.to_dict() for sid, d in self.all_densities().items()},
            "top_5": [d.to_dict() for d in self.top_sources(5)],
        }
        try:
            DENSITY_FIELD_SHM.parent.mkdir(parents=True, exist_ok=True)
            tmp = DENSITY_FIELD_SHM.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
            tmp.replace(DENSITY_FIELD_SHM)
            self._last_write = now
        except OSError:
            log.debug("density field SHM write failed", exc_info=True)

    @staticmethod
    def read_shm() -> dict[str, Any] | None:
        try:
            return json.loads(DENSITY_FIELD_SHM.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None


def _digamma(x: float) -> float:
    """Digamma function approximation (Bernardo 1976)."""
    if x <= 0:
        return 0.0
    result = 0.0
    while x < 6:
        result -= 1.0 / x
        x += 1.0
    result += math.log(x) - 0.5 / x
    x2 = 1.0 / (x * x)
    result -= x2 * (1.0 / 12 - x2 * (1.0 / 120 - x2 / 252))
    return result


def _kl_nig(
    mu1: float,
    kappa1: float,
    alpha1: float,
    beta1: float,
    mu0: float,
    kappa0: float,
    alpha0: float,
    beta0: float,
) -> float:
    """KL divergence between two Normal-Inverse-Gamma distributions."""
    if alpha0 <= 0 or alpha1 <= 0 or beta0 <= 0 or beta1 <= 0:
        return 0.0
    if kappa0 <= 0 or kappa1 <= 0:
        return 0.0
    try:
        t1 = 0.5 * math.log(kappa0 / kappa1)
        t2 = alpha1 * math.log(beta0 / beta1) if beta0 > 0 and beta1 > 0 else 0.0
        t3 = math.lgamma(alpha1) - math.lgamma(alpha0)
        t4 = (alpha0 - alpha1) * _digamma(alpha0)
        t5 = alpha0 * (beta1 - beta0) / beta0
        t6 = alpha0 * kappa1 * (mu1 - mu0) ** 2 / (2 * beta0)
        t7 = 0.5 * (kappa1 / kappa0 - 1)
        return max(0.0, t1 + t2 + t3 + t4 + t5 + t6 + t7)
    except (ValueError, OverflowError, ZeroDivisionError):
        return 0.0


def _student_t_pdf(x: float, mu: float, kappa: float, alpha: float, beta: float) -> float:
    """Predictive probability under NIG model (Student-t)."""
    if alpha <= 0 or beta <= 0 or kappa <= 0:
        return 1e-10
    try:
        nu = 2 * alpha
        sigma2 = beta * (kappa + 1) / (alpha * kappa)
        if sigma2 <= 0:
            return 1e-10
        z = (x - mu) ** 2 / sigma2
        coeff = math.lgamma((nu + 1) / 2) - math.lgamma(nu / 2)
        coeff -= 0.5 * math.log(nu * math.pi * sigma2)
        coeff -= ((nu + 1) / 2) * math.log(1 + z / nu)
        return max(1e-10, math.exp(coeff))
    except (ValueError, OverflowError, ZeroDivisionError):
        return 1e-10
