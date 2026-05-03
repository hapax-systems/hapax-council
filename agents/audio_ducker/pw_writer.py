"""PipeWire mixer-gain writer abstraction (cc-task audio-audit-C Phase 0).

Auditor C measured the audio-ducker daemon forking ``pw-cli set-param`` on
every tick (50 ms cadence = 20 forks/s). Phase 1 will replace the fork with
native pipewire-python bindings; this module is the Phase 0 substrate that
makes the swap mechanical:

- A ``MixerGainWriter`` Protocol pins the call signature both impls must honour.
- ``SubprocessPWWriter`` mirrors the current ``subprocess.run([pw-cli, ...])``
  path. It is functionally identical to ``__main__.write_mixer_gain`` and will
  remain available as the fallback when libpipewire bindings aren't installed.
- ``NativePWWriter`` is a Phase 1 placeholder. It raises ``NotImplementedError``
  with a docstring describing the libpipewire-0.3 binding signature so the
  swap PR has unambiguous landing instructions.
- ``MIXER_WRITE_LATENCY_SECONDS`` Histogram is registered now so the
  before/after p99 measurement (audit acceptance criterion) doesn't need a
  schema change at swap time.

Phase 0 deliberately does NOT modify ``agents/audio_ducker/__main__.py``.
Replacing the in-place subprocess.run with a writer-injection point is its own
PR with its own livestream-verification scope.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from prometheus_client import Histogram


@dataclass(frozen=True)
class MixerWriteOutcome:
    """Outcome of a single mixer-gain write.

    Mirrors ``agents.audio_ducker.__main__.MixerGainWriteResult`` shape so
    Phase 1 can swap the call site without dataclass marshalling. Distinct
    name (``...Outcome`` vs ``...Result``) keeps the legacy result type
    untouched until Phase 1 deletes it.
    """

    ok: bool
    error: str | None = None
    backend: str = ""

    @property
    def succeeded(self) -> bool:
        """Convenience accessor for telemetry call sites."""
        return self.ok and self.error is None


# Latency histogram shared by all writer implementations.
# Buckets target the operator's "snappier" perception: p50 < 1 ms, p99 < 5 ms
# is the Phase 1 success target.
MIXER_WRITE_LATENCY_SECONDS: Histogram = Histogram(
    "hapax_ducker_mixer_write_latency_seconds",
    "End-to-end latency of a PipeWire mixer-gain write, by backend",
    labelnames=("backend",),
    buckets=(0.0001, 0.00025, 0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)


@runtime_checkable
class MixerGainWriter(Protocol):
    """Contract every backend honours.

    The ducker FSM holds a ``MixerGainWriter`` reference and calls
    ``writer.write(node, gain)`` per tick. Phase 1 swaps the construction
    site (Subprocess vs Native) without touching the FSM.
    """

    backend_label: str

    def write(self, node_name: str, gain_lin: float) -> MixerWriteOutcome:
        """Write ``duck_l/r:Gain 1`` on ``node_name`` at linear gain ``gain_lin``.

        Implementations MUST observe the latency on
        ``MIXER_WRITE_LATENCY_SECONDS.labels(backend=self.backend_label)``.
        """
        ...


class SubprocessPWWriter:
    """Forks ``pw-cli set-param`` per write — the current Phase 0 behaviour.

    Kept as the fallback when ``NativePWWriter`` cannot load its bindings
    (CI, dev VMs, hosts without libpipewire-0.3 dev headers). Performance
    profile matches ``__main__.write_mixer_gain``: roughly 1 fork + 1 exec +
    1 wait per call (~2-5 ms typical).
    """

    backend_label = "subprocess"

    def __init__(self, *, timeout_s: float = 2.0) -> None:
        self._timeout_s = timeout_s

    def write(self, node_name: str, gain_lin: float) -> MixerWriteOutcome:
        with MIXER_WRITE_LATENCY_SECONDS.labels(backend=self.backend_label).time():
            try:
                subprocess.run(
                    [
                        "pw-cli",
                        "set-param",
                        node_name,
                        "Props",
                        (
                            "{ params = ["
                            f' "duck_l:Gain 1" {gain_lin:.4f}'
                            f' "duck_r:Gain 1" {gain_lin:.4f}'
                            " ] }"
                        ),
                    ],
                    check=True,
                    capture_output=True,
                    timeout=self._timeout_s,
                )
            except subprocess.CalledProcessError as exc:
                error = exc.stderr.decode(errors="replace") if exc.stderr else str(exc)
                return MixerWriteOutcome(ok=False, error=error, backend=self.backend_label)
            except subprocess.TimeoutExpired:
                return MixerWriteOutcome(
                    ok=False,
                    error="pw-cli set-param timed out",
                    backend=self.backend_label,
                )
            except FileNotFoundError as exc:
                return MixerWriteOutcome(ok=False, error=str(exc), backend=self.backend_label)
            return MixerWriteOutcome(ok=True, backend=self.backend_label)


class NativePWWriter:
    """Phase 1 placeholder for the libpipewire-0.3 native binding writer.

    Phase 1 lands a separate PR that:
      1. Imports ``pipewire`` (PyPI ``pipewire-python``) OR vends a small
         ctypes wrapper for ``pw_proxy_set_param`` on a long-lived connection.
      2. Holds the connection open for the daemon's lifetime — eliminating
         the per-tick fork-exec-wait round trip.
      3. Calls ``pw_proxy_set_param(node, SPA_PARAM_Props, props_pod)`` with
         a pre-built SPA POD payload encoding the same
         ``duck_l/r:Gain 1`` value pair.
      4. Observes latency on the same shared ``MIXER_WRITE_LATENCY_SECONDS``
         histogram (label ``backend="native"``) so the before/after p99
         comparison is a Grafana panel, not a script.

    Phase 0 raises ``NotImplementedError`` so a misconfigured caller fails
    loudly rather than silently falling back to subprocess.
    """

    backend_label = "native"

    def __init__(self, *, _placeholder: bool = True) -> None:
        self._placeholder = _placeholder

    def write(self, node_name: str, gain_lin: float) -> MixerWriteOutcome:
        raise NotImplementedError(
            "NativePWWriter is a Phase 1 placeholder. Wire the libpipewire-0.3 "
            "binding in cc-task audio-audit-C-pw-native-binding-eliminate-fork "
            "Phase 1; until then construct the ducker with SubprocessPWWriter."
        )
