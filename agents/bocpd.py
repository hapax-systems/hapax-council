"""Bayesian Online Change Point Detection (Adams & MacKay, 2007).

Detects abrupt changes in classification time series — activity transitions,
context switches, behavioral shifts. Pure computation, no I/O.

Operates on scalar signals (flow_score, audio_energy, heart_rate, etc.)
and emits change-point probabilities that the temporal classification
system can use for transition detection.

Reference: Adams, R. P. & MacKay, D. J. C. (2007). Bayesian Online
Changepoint Detection. arXiv:0710.3742.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field


@dataclass
class ChangePoint:
    """A detected change point in the signal."""

    timestamp: float
    probability: float  # 0.0-1.0
    signal_name: str
    run_length_before: int  # how long the previous regime lasted


@dataclass
class BOCPDDetector:
    """Online Bayesian Change Point Detection for a single scalar signal.

    Uses a Gaussian conjugate prior (Normal-Inverse-Gamma) for the
    within-segment distribution. The hazard function is constant
    (geometric prior on run length).

    Args:
        hazard_lambda: Expected segment length (higher = fewer change points).
        threshold: Probability threshold to emit a change point.
        signal_name: Name of the signal being monitored.
    """

    hazard_lambda: float = 100.0
    threshold: float = 0.5
    signal_name: str = ""

    # Conjugate prior hyperparameters (Normal-Inverse-Gamma)
    _mu0: float = 0.0
    _kappa0: float = 1.0
    _alpha0: float = 1.0
    _beta0: float = 1.0

    # State
    _run_length_probs: list[float] = field(default_factory=lambda: [1.0])
    _mu: list[float] = field(default_factory=list)
    _kappa: list[float] = field(default_factory=list)
    _alpha: list[float] = field(default_factory=list)
    _beta: list[float] = field(default_factory=list)
    _t: int = 0
    _change_points: deque[ChangePoint] = field(default_factory=lambda: deque(maxlen=50))
    _last_cp_t: int = -10  # avoid duplicate detections

    def __post_init__(self) -> None:
        self._mu = [self._mu0]
        self._kappa = [self._kappa0]
        self._alpha = [self._alpha0]
        self._beta = [self._beta0]

    def update(self, x: float, timestamp: float = 0.0) -> ChangePoint | None:
        """Process one observation.

        Args:
            x: The observed value.
            timestamp: Optional timestamp for the change point record.

        Returns:
            ChangePoint if a change point was detected, else None.
        """
        self._t += 1

        # Evaluate log-predictive probability for each run length
        # Log-space avoids underflow when student-t PDF values are tiny
        log_pred: list[float] = []
        for i in range(len(self._run_length_probs)):
            var = self._beta[i] * (self._kappa[i] + 1) / (self._alpha[i] * self._kappa[i])
            nu = 2.0 * self._alpha[i]
            log_pred.append(self._student_t_logpdf(x, self._mu[i], var, nu))

        h = 1.0 / self.hazard_lambda
        log_h = math.log(h)
        log_1_h = math.log(1 - h)

        # Compute in log-space: log_joint[i] = log(p_i) + log_pred[i]
        log_joint: list[float] = []
        for i in range(len(self._run_length_probs)):
            p = self._run_length_probs[i]
            lj = (math.log(p) if p > 1e-300 else -700.0) + log_pred[i]
            log_joint.append(lj)

        # log of new unnormalized probabilities:
        # log_new[0] = logsumexp(log_joint + log_h)  (change point)
        # log_new[i+1] = log_joint[i] + log_1_h      (growth)
        log_new: list[float] = []

        # Change point term: logsumexp over all run lengths
        log_cp_terms = [lj + log_h for lj in log_joint]
        max_val = max(log_cp_terms)
        log_cp = max_val + math.log(sum(math.exp(t - max_val) for t in log_cp_terms))
        log_new.append(log_cp)

        # Growth terms
        for lj in log_joint:
            log_new.append(lj + log_1_h)

        # Normalize in log-space then convert
        max_log = max(log_new)
        exp_new = [math.exp(v - max_log) for v in log_new]
        total = sum(exp_new)
        if total > 0:
            new_probs = [v / total for v in exp_new]
        else:
            new_probs = [1.0] + [0.0] * len(log_joint)

        cp_prob = new_probs[0]

        self._run_length_probs = new_probs

        # Update sufficient statistics for each run length
        new_mu = [self._mu0]
        new_kappa = [self._kappa0]
        new_alpha = [self._alpha0]
        new_beta = [self._beta0]

        for i in range(len(self._mu)):
            k = self._kappa[i]
            m = self._mu[i]
            a = self._alpha[i]
            b = self._beta[i]

            new_k = k + 1
            new_m = (k * m + x) / new_k
            new_a = a + 0.5
            new_b = b + (k * (x - m) ** 2) / (2 * new_k)

            new_mu.append(new_m)
            new_kappa.append(new_k)
            new_alpha.append(new_a)
            new_beta.append(new_b)

        self._mu = new_mu
        self._kappa = new_kappa
        self._alpha = new_alpha
        self._beta = new_beta

        # Pruning: cap run length distribution to avoid unbounded growth
        max_len = 300
        if len(self._run_length_probs) > max_len:
            self._run_length_probs = self._run_length_probs[:max_len]
            self._mu = self._mu[:max_len]
            self._kappa = self._kappa[:max_len]
            self._alpha = self._alpha[:max_len]
            self._beta = self._beta[:max_len]

        # Detect change point
        if cp_prob >= self.threshold and (self._t - self._last_cp_t) >= 5:
            # Find the most probable run length before the change
            if len(self._run_length_probs) > 1:
                max_rl = max(
                    range(1, len(self._run_length_probs)), key=lambda i: self._run_length_probs[i]
                )
            else:
                max_rl = 0

            cp = ChangePoint(
                timestamp=timestamp,
                probability=cp_prob,
                signal_name=self.signal_name,
                run_length_before=max_rl,
            )
            self._change_points.append(cp)
            self._last_cp_t = self._t
            return cp

        return None

    @property
    def recent_change_points(self) -> list[ChangePoint]:
        """Return recent change points (last 50)."""
        return list(self._change_points)

    @property
    def current_run_length(self) -> int:
        """Most probable current run length (regime duration)."""
        if not self._run_length_probs:
            return 0
        return max(range(len(self._run_length_probs)), key=lambda i: self._run_length_probs[i])

    @staticmethod
    def _student_t_logpdf(x: float, mu: float, var: float, nu: float) -> float:
        """Log of unnormalized Student-t PDF. Log-space prevents underflow."""
        if var <= 0:
            return -700.0
        try:
            z = (x - mu) ** 2 / var
            return -(nu + 1) / 2 * math.log(1 + z / nu)
        except (OverflowError, ValueError):
            return -700.0

    def reset(self) -> None:
        """Reset detector state."""
        self._run_length_probs = [1.0]
        self._mu = [self._mu0]
        self._kappa = [self._kappa0]
        self._alpha = [self._alpha0]
        self._beta = [self._beta0]
        self._t = 0
        self._change_points.clear()
        self._last_cp_t = -10


@dataclass
class MultiSignalBOCPD:
    """Change point detection across multiple signals.

    Maintains independent BOCPD detectors per signal and combines
    their outputs for multi-dimensional change point detection.
    """

    signals: list[str] = field(default_factory=list)
    hazard_lambda: float = 100.0
    threshold: float = 0.5
    _detectors: dict[str, BOCPDDetector] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in self.signals:
            self._detectors[name] = BOCPDDetector(
                hazard_lambda=self.hazard_lambda,
                threshold=self.threshold,
                signal_name=name,
            )

    def update(self, values: dict[str, float], timestamp: float = 0.0) -> list[ChangePoint]:
        """Process one observation per signal.

        Args:
            values: Dict of signal_name → observed value.
            timestamp: Optional timestamp.

        Returns:
            List of detected change points (may be empty).
        """
        change_points: list[ChangePoint] = []
        for name, val in values.items():
            if name not in self._detectors:
                self._detectors[name] = BOCPDDetector(
                    hazard_lambda=self.hazard_lambda,
                    threshold=self.threshold,
                    signal_name=name,
                )
            cp = self._detectors[name].update(val, timestamp)
            if cp is not None:
                change_points.append(cp)
        return change_points

    @property
    def all_recent_change_points(self) -> list[ChangePoint]:
        """All recent change points across all signals, sorted by timestamp."""
        all_cps: list[ChangePoint] = []
        for det in self._detectors.values():
            all_cps.extend(det.recent_change_points)
        all_cps.sort(key=lambda cp: cp.timestamp)
        return all_cps

    def reset(self) -> None:
        """Reset all detectors."""
        for det in self._detectors.values():
            det.reset()
