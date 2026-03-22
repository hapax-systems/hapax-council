"""System readiness gate — ensures system is presentable before demo generation."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


def _run_async(coro):
    """Run an async coroutine, handling both fresh and existing event loops."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # We're inside an existing event loop — create a new thread to run it
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    else:
        return asyncio.run(coro)


@dataclass
class ReadinessResult:
    """Result of the system readiness check."""

    ready: bool
    health_score: str = ""  # e.g., "74/75"
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    health_report: object | None = None  # HealthReport if available
    briefing_summary: str = ""


def check_readiness(
    require_tts: bool = False,
    auto_fix: bool = True,
    on_progress: Callable[[str], None] | None = None,
) -> ReadinessResult:
    """Run system readiness checks. Returns ReadinessResult.

    Checks:
    1. Health monitor (with run_fixes if auto_fix=True)
    2. Logos API (:8051) reachable
    3. hapax-logos web (:5173) reachable
    4. TTS service (Chatterbox :4123 or Kokoro local) if require_tts=True
    5. Voice sample exists if require_tts=True (Chatterbox only)
    """

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)
        else:
            log.info(msg)

    issues: list[str] = []
    warnings: list[str] = []
    health_score = ""
    health_report = None

    # 1. Health monitor — run_checks() is async, so we need an event loop
    try:
        from agents.health_monitor import run_checks, run_fixes

        progress("Running health checks...")
        report = _run_async(run_checks())
        health_report = report
        health_score = f"{report.healthy_count}/{report.total_checks}"
        progress(f"Health: {health_score}")

        if report.failed_count > 0:
            if auto_fix:
                progress("Attempting auto-fix...")
                _run_async(run_fixes(report, yes=True))
                # Re-check after fixes
                report = _run_async(run_checks())
                health_report = report
                health_score = f"{report.healthy_count}/{report.total_checks}"
                progress(f"Health after fix: {health_score}")

            if report.failed_count > 0:
                # Health failures are warnings, not blockers — the demo only
                # needs LiteLLM, Qdrant, logos, and TTS (checked separately)
                warnings.append(
                    f"Health monitor: {report.failed_count} failed checks (non-blocking)"
                )
    except Exception as e:
        warnings.append(f"Health monitor unavailable: {e}")

    # 2. Logos API
    try:
        import urllib.request

        from shared.config import LOGOS_API_URL

        urllib.request.urlopen(f"{LOGOS_API_URL}/health", timeout=5)
        progress("Logos API: OK")
    except Exception:
        issues.append(
            "Logos API (:8051) not reachable — start with: "
            "cd ~/projects/hapax-council && uv run logos-api"
        )

    # 3. hapax-logos web
    try:
        import urllib.request

        urllib.request.urlopen("http://localhost:5173", timeout=5)
        progress("hapax-logos web: OK")
    except Exception:
        issues.append(
            "hapax-logos web (:5173) not reachable — start with: "
            "cd ~/projects/hapax-council/hapax-logos && npm run dev"
        )

    # 4 & 5. TTS (only if required)
    if require_tts:
        chatterbox_ok = False
        kokoro_ok = False

        # Try Chatterbox first
        try:
            import urllib.request

            urllib.request.urlopen("http://localhost:4123/docs", timeout=5)
            chatterbox_ok = True
            progress("TTS service (Chatterbox): OK")
        except Exception:
            pass

        # Try Kokoro as fallback
        if not chatterbox_ok:
            try:
                from agents.demo_pipeline.voice import check_kokoro_available

                kokoro_ok = check_kokoro_available()
                if kokoro_ok:
                    progress("TTS service (Kokoro local): OK")
            except Exception:
                pass

        if not chatterbox_ok and not kokoro_ok:
            issues.append(
                "No TTS backend available — either start Chatterbox "
                "(cd ~/llm-stack && docker compose --profile tts up -d chatterbox) "
                "or install kokoro (uv pip install kokoro)"
            )

        # Voice sample (only relevant for Chatterbox cloning)
        if chatterbox_ok:
            from shared.config import PROFILES_DIR

            voice_sample = PROFILES_DIR / "voice-sample.wav"
            if not voice_sample.exists():
                warnings.append(
                    f"Voice sample not found at {voice_sample} (Chatterbox will use default voice)"
                )
            else:
                progress("Voice sample: OK")

    ready = len(issues) == 0
    return ReadinessResult(
        ready=ready,
        health_score=health_score,
        issues=issues,
        warnings=warnings,
        health_report=health_report,
    )
