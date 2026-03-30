"""Demo evaluation agent — generates, evaluates, and iteratively improves demos."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

from agents.demo_models import DemoEvalDimension, DemoEvalReport, DemoEvalResult

try:
    from agents import _langfuse_config  # noqa: F401
except ImportError:
    pass
from opentelemetry import trace

_tracer = trace.get_tracer(__name__)

log = logging.getLogger(__name__)

DEFAULT_SCENARIO = "the system for my partner"
DEFAULT_FORMAT = "slides"
DEFAULT_DURATION = "3m"
DEFAULT_MAX_ITERATIONS = 3
DEFAULT_PASS_THRESHOLD = 0.8


async def evaluate_demo_output(
    demo_dir: Path,
    expected_audience: str | None = None,
    target_seconds: int = 180,
) -> DemoEvalReport:
    """Evaluate a demo output directory. Returns evaluation report."""
    from agents.demo_pipeline.eval_rubrics import (
        run_structural_checks,
        run_text_evaluation,
        run_visual_evaluation,
    )
    from agents.demo_pipeline.narrative import load_style_guide, load_voice_examples

    script_data = json.loads((demo_dir / "script.json").read_text())
    style_guide = load_style_guide()
    voice_examples = load_voice_examples()

    structural_dims = run_structural_checks(demo_dir, expected_audience)
    text_dims = await run_text_evaluation(
        script_data, style_guide, target_seconds, voice_examples=voice_examples
    )
    visual_dims = await run_visual_evaluation(demo_dir, script_data)

    all_dims = structural_dims + text_dims + visual_dims

    # Weighted score: structural 0.2, text 0.4, visual 0.4
    weights = {"structural": 0.2, "text": 0.4, "visual": 0.4}
    weighted_sum = 0.0
    weight_total = 0.0
    for dim in all_dims:
        w = weights.get(dim.category, 0.33)
        weighted_sum += dim.score * w
        weight_total += w

    overall_score = weighted_sum / weight_total if weight_total > 0 else 0.0
    overall_pass = overall_score >= DEFAULT_PASS_THRESHOLD and all(
        d.passed for d in all_dims if d.category == "structural"
    )

    return DemoEvalReport(
        dimensions=all_dims,
        overall_pass=overall_pass,
        overall_score=round(overall_score, 3),
    )


async def run_eval_loop(
    scenario: str = DEFAULT_SCENARIO,
    format: str = DEFAULT_FORMAT,
    duration: str = DEFAULT_DURATION,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    pass_threshold: float = DEFAULT_PASS_THRESHOLD,
    on_progress: callable | None = None,
) -> DemoEvalResult:
    """Run the full generate -> evaluate -> heal loop."""
    from agents.demo import generate_demo, parse_duration, parse_request, resolve_audience
    from agents.demo_models import load_personas
    from agents.demo_pipeline.eval_rubrics import diagnose_failures
    from agents.demo_pipeline.narrative import load_style_guide

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)
        else:
            log.info(msg)

    start_time = time.time()
    style_guide = load_style_guide()
    _, audience_text = parse_request(scenario)
    personas = load_personas()
    archetype, _ = resolve_audience(audience_text, personas)
    target_seconds = parse_duration(duration, archetype)

    from agents.demo_pipeline.lessons import format_lessons_block, load_lessons_for_archetype

    prior_lessons = load_lessons_for_archetype(archetype)
    lessons_block = format_lessons_block(prior_lessons)
    if lessons_block:
        progress(f"Loaded {len(prior_lessons)} prior lessons for {archetype}")

    history: list[DemoEvalReport] = []
    planning_overrides = ""
    demo_dir: Path | None = None

    for iteration in range(1, max_iterations + 1):
        progress(f"\n{'=' * 60}")
        progress(f"ITERATION {iteration}/{max_iterations}")
        progress(f"{'=' * 60}")

        # Generate
        progress("Generating demo...")
        try:
            demo_dir = await generate_demo(
                request=scenario,
                format=format,
                duration=duration,
                on_progress=progress,
                lesson_context=lessons_block if lessons_block else None,
                planning_overrides=planning_overrides if planning_overrides else None,
            )
        except Exception as e:
            progress(f"Generation failed: {e}")
            report = DemoEvalReport(
                dimensions=[
                    DemoEvalDimension(
                        name="generation_error",
                        category="structural",
                        passed=False,
                        score=0.0,
                        issues=[str(e)],
                    )
                ],
                overall_pass=False,
                overall_score=0.0,
                iteration=iteration,
                adjustments_applied=planning_overrides.split("\n") if planning_overrides else [],
            )
            history.append(report)
            continue

        # Evaluate
        progress("Evaluating output...")
        report = await evaluate_demo_output(
            demo_dir,
            expected_audience=archetype,
            target_seconds=target_seconds,
        )
        report.iteration = iteration
        if planning_overrides:
            report.adjustments_applied = [
                line.strip() for line in planning_overrides.split("\n") if line.strip()
            ]
        history.append(report)

        # Report scores
        progress(f"\nEvaluation scores (iteration {iteration}):")
        for dim in report.dimensions:
            status = "PASS" if dim.passed else "FAIL"
            progress(f"  [{status}] {dim.name}: {dim.score:.2f}")
            for issue in dim.issues:
                progress(f"         -> {issue}")
        progress(
            f"\n  Overall: {report.overall_score:.2f} ({'PASS' if report.overall_pass else 'FAIL'})"
        )

        if report.overall_pass:
            progress(f"\nDemo PASSED evaluation on iteration {iteration}")
            break

        # Diagnose and plan fixes
        if iteration < max_iterations:
            progress("\nDiagnosing failures...")
            script_data = json.loads((demo_dir / "script.json").read_text())
            persona = personas.get(archetype)
            diagnosis = await diagnose_failures(
                report.dimensions,
                script_data,
                style_guide,
                iteration,
                forbidden_terms=persona.forbidden_terms if persona else None,
            )
            progress(f"Root causes: {'; '.join(diagnosis.root_causes)}")
            progress(f"Adjustments: {'; '.join(diagnosis.adjustments_summary)}")
            # Replace overrides each iteration (diagnosis sees full context)
            planning_overrides = diagnosis.planning_overrides
            # Cap at ~2000 chars to prevent prompt bloat
            if len(planning_overrides) > 2000:
                planning_overrides = planning_overrides[:2000].rsplit(" ", 1)[0]

    elapsed = time.time() - start_time
    final_report = (
        history[-1]
        if history
        else DemoEvalReport(
            dimensions=[],
            overall_pass=False,
            overall_score=0.0,
        )
    )

    result = DemoEvalResult(
        scenario=scenario,
        passed=final_report.overall_pass,
        iterations=len(history),
        final_report=final_report,
        history=history,
        demo_dir=str(demo_dir) if demo_dir else "",
        total_duration_seconds=round(elapsed, 1),
    )

    # Save result
    if demo_dir and demo_dir.exists():
        (demo_dir / "eval_result.json").write_text(result.model_dump_json(indent=2))
        progress(f"\nEvaluation result saved to {demo_dir / 'eval_result.json'}")

    # Save lessons from passing multi-iteration runs
    if result.passed and result.iterations > 1:
        from agents.demo_pipeline.lessons import (
            accumulate_lessons,
            extract_lessons,
            load_lessons,
            save_lessons,
        )

        new_lesson_texts = extract_lessons(result)
        if new_lesson_texts:
            store = load_lessons()
            store = accumulate_lessons(store, archetype, new_lesson_texts)
            save_lessons(store)
            progress(f"Saved {len(new_lesson_texts)} lessons for {archetype}")

    return result


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate demo output quality with LLM-as-judge",
        prog="python -m agents.demo_eval",
    )
    parser.add_argument(
        "--scenario",
        default=DEFAULT_SCENARIO,
        help=f"Demo request text (default: '{DEFAULT_SCENARIO}')",
    )
    parser.add_argument("--format", default=DEFAULT_FORMAT, choices=["slides", "video"])
    parser.add_argument(
        "--duration", default=DEFAULT_DURATION, help="Target duration (e.g. '3m', '180s')"
    )
    parser.add_argument("--max-iterations", type=int, default=DEFAULT_MAX_ITERATIONS)
    parser.add_argument("--pass-threshold", type=float, default=DEFAULT_PASS_THRESHOLD)
    parser.add_argument(
        "--eval-only",
        type=Path,
        default=None,
        help="Evaluate an existing demo directory (no generation or healing)",
    )
    args = parser.parse_args()

    from agents._log_setup import configure_logging

    configure_logging(agent="demo-eval", level="WARNING")
    # Only show our own messages
    logging.getLogger("agents").setLevel(logging.INFO)

    def print_flush(msg: str) -> None:
        """Print with immediate flush for real-time visibility."""
        print(msg, flush=True)

    with _tracer.start_as_current_span(
        "demo_eval.run",
        attributes={"agent.name": "demo_eval", "agent.repo": "hapax-council"},
    ):
        if args.eval_only:
            report = await evaluate_demo_output(args.eval_only)
            print_flush(
                f"\nOverall: {report.overall_score:.2f} ({'PASS' if report.overall_pass else 'FAIL'})"
            )
            for dim in report.dimensions:
                status = "PASS" if dim.passed else "FAIL"
                print_flush(f"  [{status}] {dim.name}: {dim.score:.2f}")
                for issue in dim.issues:
                    print_flush(f"         -> {issue}")
            sys.exit(0 if report.overall_pass else 1)

        result = await run_eval_loop(
            scenario=args.scenario,
            format=args.format,
            duration=args.duration,
            max_iterations=args.max_iterations,
            pass_threshold=args.pass_threshold,
            on_progress=print_flush,
        )

        print_flush(f"\n{'=' * 60}")
        print_flush(f"FINAL RESULT: {'PASSED' if result.passed else 'FAILED'}")
        print_flush(f"Iterations: {result.iterations}")
        print_flush(f"Score: {result.final_report.overall_score:.2f}")
        print_flush(f"Duration: {result.total_duration_seconds:.0f}s")
        print_flush(f"Output: {result.demo_dir}")
        print_flush(f"{'=' * 60}")

        sys.exit(0 if result.passed else 1)


if __name__ == "__main__":
    asyncio.run(main())
