"""TSE (Target Speaker Extraction) benchmark for local hardware.

Two-stage architecture:
  1. Blind source separation — splits mixture into N channels
  2. Speaker channel identification — cosine similarity against enrolled embedding

Run: uv run python -m agents.hapax_voice.tse_benchmark
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class BenchmarkResult:
    model: str
    device: str
    frame_size_samples: int
    latency_p50_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    vram_delta_mb: float
    error: str | None = None


@dataclass
class BenchmarkReport:
    results: list[BenchmarkResult] = field(default_factory=list)
    go_recommendation: bool = False
    recommended_model: str = ""
    recommended_device: str = ""
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_vram_used_mb() -> float:
    """Current GPU VRAM usage in MB via nvidia-smi."""
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            text=True,
        )
        return float(out.strip().splitlines()[0])
    except Exception:
        return 0.0


def _get_vram_free_mb() -> float:
    """Free GPU VRAM in MB via nvidia-smi."""
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            text=True,
        )
        return float(out.strip().splitlines()[0])
    except Exception:
        return 0.0


def _make_test_mixture(n_samples: int, sample_rate: int = 16000) -> np.ndarray:
    """Synthetic tone + noise mixture as float32."""
    t = np.linspace(0, n_samples / sample_rate, n_samples, dtype=np.float32)
    tone = 0.5 * np.sin(2 * np.pi * 440 * t).astype(np.float32)
    noise = 0.3 * np.random.default_rng(42).standard_normal(n_samples).astype(np.float32)
    return tone + noise


def _measure_latency(
    fn: callable,  # type: ignore[valid-type]
    n_runs: int = 100,
) -> tuple[float, float, float]:
    """Run *fn* with warmup, return (p50, p95, p99) in milliseconds."""
    # Warmup
    for _ in range(3):
        fn()

    times: list[float] = []
    for _ in range(n_runs):
        start = time.perf_counter()
        fn()
        times.append((time.perf_counter() - start) * 1000.0)

    arr = np.array(times)
    return (
        float(np.percentile(arr, 50)),
        float(np.percentile(arr, 95)),
        float(np.percentile(arr, 99)),
    )


# ---------------------------------------------------------------------------
# Benchmarks
# ---------------------------------------------------------------------------

FRAME_DURATION_S = 0.5
SAMPLE_RATE_16K = 16000
SAMPLE_RATE_8K = 8000
FRAME_16K = int(FRAME_DURATION_S * SAMPLE_RATE_16K)  # 8000 samples
FRAME_8K = int(FRAME_DURATION_S * SAMPLE_RATE_8K)  # 4000 samples


def benchmark_speechbrain_sepformer(device: str) -> BenchmarkResult:
    """SpeechBrain SepFormer (WSJ0-2mix) — blind source separation."""
    try:
        import torch
        from speechbrain.inference.separation import SepformerSeparation

        vram_before = _get_vram_used_mb()

        model = SepformerSeparation.from_hparams(
            source="speechbrain/sepformer-wsj02mix",
            run_opts={"device": device},
        )

        # SepFormer expects 8 kHz — downsample from 16k
        mixture_16k = _make_test_mixture(FRAME_16K, SAMPLE_RATE_16K)
        mixture_8k = mixture_16k[::2]  # simple 2x downsample
        tensor = torch.tensor(mixture_8k, dtype=torch.float32).unsqueeze(0).to(device)

        def _run() -> None:
            model.separate_batch(tensor)

        p50, p95, p99 = _measure_latency(_run)
        vram_after = _get_vram_used_mb()

        return BenchmarkResult(
            model="speechbrain/sepformer-wsj02mix",
            device=device,
            frame_size_samples=FRAME_8K,
            latency_p50_ms=p50,
            latency_p95_ms=p95,
            latency_p99_ms=p99,
            vram_delta_mb=vram_after - vram_before,
        )
    except Exception as exc:
        return BenchmarkResult(
            model="speechbrain/sepformer-wsj02mix",
            device=device,
            frame_size_samples=FRAME_8K,
            latency_p50_ms=0.0,
            latency_p95_ms=0.0,
            latency_p99_ms=0.0,
            vram_delta_mb=0.0,
            error=str(exc),
        )


def benchmark_asteroid_convtasnet(device: str) -> BenchmarkResult:
    """Asteroid ConvTasNet (Libri2Mix) — blind source separation."""
    try:
        import torch
        from asteroid.models import ConvTasNet

        vram_before = _get_vram_used_mb()

        model = ConvTasNet.from_pretrained("JorisCos/ConvTasNet_Libri2Mix_sepclean_16k")
        model = model.to(device)
        model.eval()

        mixture = _make_test_mixture(FRAME_16K, SAMPLE_RATE_16K)
        tensor = torch.tensor(mixture, dtype=torch.float32).unsqueeze(0).to(device)

        def _run() -> None:
            with torch.no_grad():
                model(tensor)

        p50, p95, p99 = _measure_latency(_run)
        vram_after = _get_vram_used_mb()

        return BenchmarkResult(
            model="JorisCos/ConvTasNet_Libri2Mix_sepclean_16k",
            device=device,
            frame_size_samples=FRAME_16K,
            latency_p50_ms=p50,
            latency_p95_ms=p95,
            latency_p99_ms=p99,
            vram_delta_mb=vram_after - vram_before,
        )
    except Exception as exc:
        return BenchmarkResult(
            model="JorisCos/ConvTasNet_Libri2Mix_sepclean_16k",
            device=device,
            frame_size_samples=FRAME_16K,
            latency_p50_ms=0.0,
            latency_p95_ms=0.0,
            latency_p99_ms=0.0,
            vram_delta_mb=0.0,
            error=str(exc),
        )


def benchmark_ecapa_tdnn(device: str) -> BenchmarkResult:
    """SpeechBrain ECAPA-TDNN — speaker channel identification."""
    try:
        import torch
        from speechbrain.inference.speaker import EncoderClassifier

        vram_before = _get_vram_used_mb()

        model = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            run_opts={"device": device},
        )

        mixture = _make_test_mixture(FRAME_16K, SAMPLE_RATE_16K)
        tensor = torch.tensor(mixture, dtype=torch.float32).unsqueeze(0).to(device)

        def _run() -> None:
            model.encode_batch(tensor)

        p50, p95, p99 = _measure_latency(_run)
        vram_after = _get_vram_used_mb()

        return BenchmarkResult(
            model="speechbrain/spkrec-ecapa-voxceleb",
            device=device,
            frame_size_samples=FRAME_16K,
            latency_p50_ms=p50,
            latency_p95_ms=p95,
            latency_p99_ms=p99,
            vram_delta_mb=vram_after - vram_before,
        )
    except Exception as exc:
        return BenchmarkResult(
            model="speechbrain/spkrec-ecapa-voxceleb",
            device=device,
            frame_size_samples=FRAME_16K,
            latency_p50_ms=0.0,
            latency_p95_ms=0.0,
            latency_p99_ms=0.0,
            vram_delta_mb=0.0,
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

SEPARATION_MODELS = [benchmark_speechbrain_sepformer, benchmark_asteroid_convtasnet]
IDENTIFICATION_MODELS = [benchmark_ecapa_tdnn]
SEPARATION_MODEL_NAMES = {
    "speechbrain/sepformer-wsj02mix",
    "JorisCos/ConvTasNet_Libri2Mix_sepclean_16k",
}
IDENTIFICATION_MODEL_NAMES = {"speechbrain/spkrec-ecapa-voxceleb"}
P95_THRESHOLD_MS = 500.0
MIN_VRAM_FREE_MB = 4000.0


def main() -> None:
    """Run all benchmarks, produce GO/NO-GO recommendation, save report."""
    import torch

    report = BenchmarkReport()

    # Determine devices
    devices = ["cpu"]
    vram_free = _get_vram_free_mb()
    if torch.cuda.is_available():
        if vram_free >= MIN_VRAM_FREE_MB:
            devices.append("cuda")
            report.notes.append(f"GPU VRAM free: {vram_free:.0f} MB")
        else:
            report.notes.append(
                f"GPU skipped — only {vram_free:.0f} MB free (need {MIN_VRAM_FREE_MB:.0f})"
            )
    else:
        report.notes.append("CUDA not available — CPU only")

    # Run benchmarks
    all_benchmarks = SEPARATION_MODELS + IDENTIFICATION_MODELS
    for device in devices:
        for bench_fn in all_benchmarks:
            print(f"  [{device}] {bench_fn.__name__} ...", end=" ", flush=True)
            result = bench_fn(device)
            report.results.append(result)
            if result.error:
                print(f"ERROR: {result.error[:80]}")
            else:
                print(f"p95={result.latency_p95_ms:.1f}ms  vram_delta={result.vram_delta_mb:.0f}MB")

    # Find best separation model (lowest p95 that meets threshold)
    sep_results = [
        r for r in report.results if r.error is None and r.model in SEPARATION_MODEL_NAMES
    ]
    viable_sep = [r for r in sep_results if r.latency_p95_ms < P95_THRESHOLD_MS]

    # Find best identification model
    ident_results = [
        r for r in report.results if r.error is None and r.model in IDENTIFICATION_MODEL_NAMES
    ]
    viable_ident = [r for r in ident_results if r.latency_p95_ms < P95_THRESHOLD_MS]

    # GO/NO-GO
    if viable_sep and viable_ident:
        best_sep = min(viable_sep, key=lambda r: r.latency_p95_ms)
        best_ident = min(viable_ident, key=lambda r: r.latency_p95_ms)
        combined_p95 = best_sep.latency_p95_ms + best_ident.latency_p95_ms

        if combined_p95 < P95_THRESHOLD_MS:
            report.go_recommendation = True
            report.recommended_model = best_sep.model
            report.recommended_device = best_sep.device
            report.notes.append(
                f"GO — combined p95 {combined_p95:.1f}ms < {P95_THRESHOLD_MS:.0f}ms"
            )
        else:
            report.notes.append(
                f"NO-GO — combined p95 {combined_p95:.1f}ms >= {P95_THRESHOLD_MS:.0f}ms"
            )
    else:
        if not viable_sep:
            report.notes.append("NO-GO — no separation model meets latency threshold")
        if not viable_ident:
            report.notes.append("NO-GO — no identification model meets latency threshold")

    # Save report
    out_dir = Path.home() / ".local" / "share" / "hapax-voice"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "tse_benchmark_report.json"
    out_path.write_text(json.dumps(asdict(report), indent=2))

    # Print summary
    print("\n" + "=" * 60)
    print("TSE Benchmark Report")
    print("=" * 60)
    for r in report.results:
        status = "ERR" if r.error else "OK "
        print(
            f"  {status} {r.model:50s} [{r.device:4s}] "
            f"p50={r.latency_p50_ms:7.1f}  p95={r.latency_p95_ms:7.1f}  "
            f"p99={r.latency_p99_ms:7.1f}ms  vram={r.vram_delta_mb:+.0f}MB"
        )
    print()
    for note in report.notes:
        print(f"  * {note}")
    recommendation = "GO" if report.go_recommendation else "NO-GO"
    print(f"\n  Recommendation: {recommendation}")
    if report.recommended_model:
        print(f"  Model: {report.recommended_model} on {report.recommended_device}")
    print(f"\n  Report saved to {out_path}")


if __name__ == "__main__":
    main()
