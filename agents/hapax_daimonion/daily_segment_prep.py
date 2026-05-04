"""Daily segment prep — compose all segments offline before going live.

Every day Hapax spends a prep window (default 30 min) composing full
narration scripts for all planned segments.  The resulting scripts are
stored to disk and loaded by the programme loop during the livestream.
During delivery, TTS reads the pre-composed text — zero LLM calls.

This is the "radio show prep" pattern: write the script before you go
on air, then DELIVER it live.

Usage:
    uv run python -m agents.hapax_daimonion.daily_segment_prep
    uv run python -m agents.hapax_daimonion.daily_segment_prep --prep-dir ~/.cache/hapax/segment-prep

The runner can also be triggered by a systemd timer (see
config/systemd/hapax-segment-prep.timer).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Where prepped segments live.  One subdirectory per date.
DEFAULT_PREP_DIR = Path(
    os.environ.get(
        "HAPAX_SEGMENT_PREP_DIR",
        os.path.expanduser("~/.cache/hapax/segment-prep"),
    )
)

# Max wall-clock for the entire prep window.
PREP_BUDGET_S = float(os.environ.get("HAPAX_SEGMENT_PREP_BUDGET_S", "1800"))  # 30 min

# How many segments to prep per run.
MAX_SEGMENTS = int(os.environ.get("HAPAX_SEGMENT_PREP_MAX", "6"))


def _today_dir(base: Path) -> Path:
    today = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    d = base / today
    d.mkdir(parents=True, exist_ok=True)
    return d


def _build_full_segment_prompt(
    programme: Any,
    seed: str,
    operator_referent: str | None = None,
) -> str:
    """Build a prompt that asks the LLM to compose ALL beats at once.

    Unlike the live `build_segment_prompt` which asks for the current
    beat only, this prompt gives the full structure and asks for a
    JSON array of narration blocks — one per beat.
    """
    from shared.claim_prompt import SURFACE_FLOORS, render_envelope
    from shared.operator_referent import REFERENTS

    envelope = render_envelope([], floor=SURFACE_FLOORS["autonomous_narrative"])

    role = getattr(programme, "role", None)
    role_value = getattr(role, "value", str(role)) if role else "rant"
    content = getattr(programme, "content", None)
    narrative_beat = getattr(content, "narrative_beat", "") or "" if content else ""
    beats = getattr(content, "segment_beats", []) or [] if content else []

    beat_lines = "\n".join(f"  {i + 1}. {b}" for i, b in enumerate(beats))

    referent_clause = ""
    if operator_referent:
        referents = ", ".join(f"'{r}'" for r in REFERENTS)
        referent_clause = (
            f"- If you refer to the operator, use exactly '{operator_referent}'. "
            f"Other referents: {referents}.\n"
        )

    return (
        f"{envelope}\n\n"
        f"You are Hapax, preparing a {role_value.upper().replace('_', ' ')} segment "
        f"for your research livestream.\n\n"
        f"== SEGMENT DIRECTION ==\n{narrative_beat}\n\n"
        f"== SEGMENT STRUCTURE ==\n{beat_lines}\n\n"
        "== YOUR TASK ==\n"
        "Compose the COMPLETE narration for this segment — one block of "
        "broadcast-ready prose per beat. Return a JSON array where each "
        "element is the spoken text for that beat (3-8 sentences, 200-600 "
        "characters each).\n\n"
        "Example format:\n"
        '[\n  "First beat narration here. Specific claims with sources. ...",\n'
        '  "Second beat narration. Continue the argument. ...",\n'
        "  ...\n]\n\n"
        "REGISTER: specialist host on a live production. Mid-Atlantic "
        "broadcast — informed, direct, opinionated. Conference keynote "
        "meets late-night monologue.\n\n"
        "RHETORIC — every beat must satisfy ALL of these:\n"
        "1. CLAIM → EVIDENCE → SO-WHAT per beat.\n"
        "2. Every sentence has at least one TECHNICAL NOUN or PROPER NAME.\n"
        "3. Every claim NAMES ITS SOURCE.\n"
        "4. ACTIVE VOICE throughout.\n"
        "5. Code for INSIDERS, land for OUTSIDERS.\n"
        "6. Hapax is the system's name. Never 'the AI'.\n"
        f"{referent_clause}\n"
        "Segment research & assets:\n"
        "---\n"
        f"{seed}\n"
        "---\n\n"
        "Output ONLY the JSON array. No preamble, no markdown fences, "
        "no explanation. Start with [ and end with ]."
    )


def _call_llm(prompt: str) -> str:
    """Call the LLM for segment prep via the LiteLLM gateway.

    Uses the same raw urllib pattern as the programme planner so the
    prep runner works in the same environments (service, CLI with secrets).
    """
    import urllib.request

    litellm_url = os.environ.get("HAPAX_LITELLM_URL", "http://localhost:4000/v1/chat/completions")
    litellm_key = os.environ.get("LITELLM_API_KEY", "")
    model = os.environ.get("HAPAX_SEGMENT_PREP_MODEL", "claude-opus")

    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 8192,
        }
    ).encode()

    req = urllib.request.Request(
        litellm_url,
        body,
        {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {litellm_key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        log.warning("segment prep LLM HTTP %d: %s", e.code, err_body)
        raise

    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError):
        log.warning("segment prep: unexpected LLM response shape")
        return ""


def _parse_script(raw: str) -> list[str]:
    """Parse the LLM response into a list of beat narration blocks."""
    text = raw.strip()
    # Strip markdown fences
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]  # drop opening fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        log.warning("segment prep: LLM response is not valid JSON")
        return []

    if not isinstance(parsed, list):
        log.warning("segment prep: LLM response is not a JSON array")
        return []

    return [str(item).strip() for item in parsed if str(item).strip()]


def _build_seed(programme: Any) -> str:
    """Build a research seed from the programme's vault/perception context."""
    from agents.hapax_daimonion.autonomous_narrative.compose import _build_seed

    # The compose module's _build_seed expects a NarrativeContext.
    # For prep, we build a minimal one.
    try:
        from agents.hapax_daimonion.autonomous_narrative.state_readers import (
            NarrativeContext,
        )

        ctx = NarrativeContext(programme=programme)
        return _build_seed(ctx)
    except Exception:
        # Fallback: use narrative_beat as seed
        content = getattr(programme, "content", None)
        return getattr(content, "narrative_beat", "") or ""


def prep_segment(programme: Any, prep_dir: Path) -> Path | None:
    """Compose the full narration script for one programme and save it.

    Returns the path to the saved JSON file, or None on failure.
    """
    prog_id = getattr(programme, "programme_id", "unknown")
    role = getattr(getattr(programme, "role", None), "value", "unknown")
    content = getattr(programme, "content", None)
    beats = getattr(content, "segment_beats", []) or [] if content else []

    if not beats:
        log.info("prep_segment: %s has no beats, skipping", prog_id)
        return None

    log.info("prep_segment: composing %s (%s, %d beats)", prog_id, role, len(beats))

    seed = _build_seed(programme)
    prompt = _build_full_segment_prompt(programme, seed)
    raw = _call_llm(prompt)
    script = _parse_script(raw)

    if not script:
        log.warning("prep_segment: empty script for %s", prog_id)
        return None

    # Pad or truncate to match beat count
    if len(script) < len(beats):
        log.warning(
            "prep_segment: script has %d blocks but %d beats; padding",
            len(script),
            len(beats),
        )
        script.extend([""] * (len(beats) - len(script)))
    elif len(script) > len(beats):
        script = script[: len(beats)]

    # Save to disk
    out_path = prep_dir / f"{prog_id}.json"
    payload = {
        "programme_id": prog_id,
        "role": role,
        "topic": getattr(content, "narrative_beat", "") or "",
        "segment_beats": list(beats),
        "prepared_script": script,
        "prepped_at": datetime.now(tz=UTC).isoformat(),
        "beat_count": len(beats),
    }
    tmp = out_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(out_path)
    log.info("prep_segment: saved %s (%d blocks)", out_path, len(script))
    return out_path


def run_prep(prep_dir: Path | None = None) -> list[Path]:
    """Run the daily prep window.

    1. Call the planner to generate programme plans
    2. For each segmented-content programme, compose the full script
    3. Save results to the prep directory
    4. Write a manifest summarizing what was prepped

    Returns list of saved file paths.
    """
    from agents.hapax_daimonion.autonomous_narrative.segment_prompts import (
        SEGMENTED_CONTENT_ROLES,
    )

    if prep_dir is None:
        prep_dir = DEFAULT_PREP_DIR
    today = _today_dir(prep_dir)

    start = time.monotonic()
    saved: list[Path] = []

    # Step 1: Plan
    log.info("daily_segment_prep: planning programmes...")
    try:
        from agents.programme_manager.planner import ProgrammePlanner

        planner = ProgrammePlanner()
        show_id = f"show-{datetime.now(tz=UTC).strftime('%Y%m%d')}"
        plan = planner.plan(show_id=show_id)
    except Exception:
        log.error("daily_segment_prep: planner failed", exc_info=True)
        return saved

    if plan is None or not plan.programmes:
        log.warning("daily_segment_prep: planner returned no programmes")
        return saved

    # Step 2: Compose each segmented-content programme
    segmented = [
        p
        for p in plan.programmes
        if getattr(getattr(p, "role", None), "value", "") in SEGMENTED_CONTENT_ROLES
    ]
    log.info(
        "daily_segment_prep: %d programmes, %d segmented",
        len(plan.programmes),
        len(segmented),
    )

    for prog in segmented[:MAX_SEGMENTS]:
        elapsed = time.monotonic() - start
        if elapsed >= PREP_BUDGET_S:
            log.warning("daily_segment_prep: prep budget exhausted (%.0fs)", elapsed)
            break

        path = prep_segment(prog, today)
        if path:
            saved.append(path)

    # Step 3: Write manifest
    manifest = today / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "date": datetime.now(tz=UTC).strftime("%Y-%m-%d"),
                "prepped_at": datetime.now(tz=UTC).isoformat(),
                "programmes": [p.name for p in saved],
                "total_elapsed_s": round(time.monotonic() - start, 1),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    log.info(
        "daily_segment_prep: done. %d segments prepped in %.0fs",
        len(saved),
        time.monotonic() - start,
    )
    return saved


def load_prepped_programmes(prep_dir: Path | None = None) -> list[dict]:
    """Load today's prepped segments from disk.

    Returns a list of dicts, each with programme_id, prepared_script, etc.
    Used by the programme loop to populate prepared_script on programmes.
    """
    if prep_dir is None:
        prep_dir = DEFAULT_PREP_DIR
    today = _today_dir(prep_dir)

    results = []
    for f in sorted(today.glob("*.json")):
        if f.name == "manifest.json":
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("prepared_script"):
                results.append(data)
        except Exception:
            log.debug("load_prepped: failed to read %s", f, exc_info=True)
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Daily segment prep runner")
    parser.add_argument("--prep-dir", type=Path, default=None)
    args = parser.parse_args()
    saved = run_prep(prep_dir=args.prep_dir)
    for p in saved:
        print(f"  ✓ {p}")
