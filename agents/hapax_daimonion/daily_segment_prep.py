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

# How many segments to prep per run.  Fewer segments = more time per
# segment for iterative refinement.  Each segment gets an initial
# composition pass PLUS a critic/rewrite pass.
MAX_SEGMENTS = int(os.environ.get("HAPAX_SEGMENT_PREP_MAX", "4"))


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
    JSON array of narration blocks — one per beat.  Each beat is a
    substantial paragraph (800-2000 chars, ~1-2 minutes spoken).
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
        "== DRAMATIC ARC ==\n"
        "Every segment is a PERFORMANCE, not a listicle. Shape energy across beats:\n"
        "- OPEN with a hook that creates *tension* — a question, a paradox, a provocation\n"
        "- BUILD through the body — each beat must EARN the next, not just follow it\n"
        "- Include at least one PIVOT — a moment where the frame shifts unexpectedly\n"
        "- PEAK at roughly 2/3 through — the deepest, most surprising, most specific beat\n"
        "- BREATHE before landing — a beat that lets the audience absorb what just happened\n"
        "- CLOSE with a reframe that changes how the opening sounds in retrospect\n\n"
        "== BEAT DEPTH ==\n"
        "Each beat is 800-2000 characters of spoken prose (1-2 minutes at broadcast pace).\n"
        "That means 8-20 sentences per beat. Think ESSAY PARAGRAPH, not tweet thread.\n"
        "- Every claim gets its FULL ARGUMENT, not just an assertion\n"
        "- Sources get CONTEXT: 'Zuboff argues X because Y, which matters because Z'\n"
        "- Transitions between beats should feel like a DJ crossfade, not a chapter break\n"
        "- Use rhetorical questions, callbacks to earlier beats, direct address to chat\n"
        "- Let ideas BREATHE — develop a point, sit with it, then pivot\n"
        "- A beat that can be summarized in one sentence is a beat that wasn't written yet\n\n"
        "== YOUR TASK ==\n"
        "Compose the COMPLETE narration for this segment — one SUBSTANTIAL block of "
        "broadcast-ready prose per beat. Return a JSON array where each element is "
        "the spoken text for that beat (800-2000 characters each, 8-20 sentences).\n\n"
        "Example format:\n"
        '[\n  "Opening beat — a full paragraph that hooks, contextualizes, and builds '
        'anticipation. Multiple sentences developing the frame...",\n'
        '  "Second beat — continues with depth. Names sources with context. Develops '
        'the argument across many sentences...",\n'
        "  ...\n]\n\n"
        "REGISTER: specialist host on a live production. Mid-Atlantic "
        "broadcast — informed, direct, opinionated. Conference keynote "
        "meets late-night monologue. Charlie Rose depth meets Anthony Bourdain energy.\n\n"
        "RHETORIC — every beat must satisfy ALL of these:\n"
        "1. CLAIM → EVIDENCE → SO-WHAT → IMPLICATION chain per beat.\n"
        "2. Every sentence has at least one TECHNICAL NOUN or PROPER NAME.\n"
        "3. Every claim NAMES ITS SOURCE with context, not just a name-drop.\n"
        "4. ACTIVE VOICE throughout.\n"
        "5. Code for INSIDERS, land for OUTSIDERS.\n"
        "6. Hapax is the system's name. Never 'the AI'.\n"
        "7. VARY SENTENCE LENGTH — short punches between longer developments.\n"
        "8. Each beat must be AT LEAST 800 characters. Shorter beats are FAILURES.\n"
        f"{referent_clause}\n"
        "Segment research & assets:\n"
        "---\n"
        f"{seed}\n"
        "---\n\n"
        "Output ONLY the JSON array. No preamble, no markdown fences, "
        "no explanation. Start with [ and end with ]."
    )


# LLM timeout — raised from 180s to 300s to accommodate longer, richer
# output from the expanded prompt (800-2000 chars per beat × 10-15 beats).
_PREP_LLM_TIMEOUT_S = 300


def _call_llm(prompt: str) -> str:
    """Call the LLM — TabbyAPI primary, LiteLLM fallback.

    Mirrors the programme planner's local-first routing: TabbyAPI at
    localhost:5000 for zero external dependency, LiteLLM at localhost:4000
    as fallback.
    """
    import urllib.request

    tabby_url = os.environ.get("HAPAX_TABBY_URL", "http://localhost:5000/v1/chat/completions")
    litellm_url = os.environ.get("HAPAX_LITELLM_URL", "http://localhost:4000/v1/chat/completions")
    litellm_key = os.environ.get("LITELLM_API_KEY", "")
    model = os.environ.get("HAPAX_SEGMENT_PREP_MODEL", "command-r-08-2024-exl3-5.0bpw")

    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 16384,
            "temperature": 0.7,
            "chat_template_kwargs": {"enable_thinking": False},
        }
    ).encode()

    # Primary: TabbyAPI (local, no auth)
    try:
        req = urllib.request.Request(tabby_url, body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=_PREP_LLM_TIMEOUT_S) as resp:
            data = json.loads(resp.read())
        content = data["choices"][0]["message"]["content"] or ""
        if content:
            content = _strip_think_tags(content)
            log.info("segment prep LLM: served by TabbyAPI (local)")
            return content
    except Exception:
        log.info("segment prep LLM: TabbyAPI unavailable, trying LiteLLM")

    # Fallback: LiteLLM
    try:
        req = urllib.request.Request(
            litellm_url,
            body,
            {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {litellm_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=_PREP_LLM_TIMEOUT_S) as resp:
            data = json.loads(resp.read())
        return _strip_think_tags(data["choices"][0]["message"]["content"] or "")
    except Exception:
        log.warning("segment prep LLM: both TabbyAPI and LiteLLM failed", exc_info=True)
        raise


def _strip_think_tags(text: str) -> str:
    """Strip Qwen3's <think>...</think> chain-of-thought from responses."""
    import re

    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _parse_script(raw: str) -> list[str]:
    """Parse the LLM response into a list of beat narration blocks."""
    text = _strip_think_tags(raw.strip())
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


def _build_refinement_prompt(script: list[str], programme: Any) -> str:
    """Build a critic/rewrite prompt for iterative refinement.

    Takes the initial draft and asks the LLM to evaluate each beat
    and rewrite any that are thin, rushed, or don't earn their
    conclusions.
    """
    role = getattr(getattr(programme, "role", None), "value", "rant")
    content = getattr(programme, "content", None)
    narrative_beat = getattr(content, "narrative_beat", "") or "" if content else ""
    beats = getattr(content, "segment_beats", []) or [] if content else []

    beat_review = ""
    for i, (direction, text) in enumerate(zip(beats, script, strict=False)):
        chars = len(text)
        beat_review += f"\n--- Beat {i + 1} ({chars} chars) ---\n"
        beat_review += f"Direction: {direction}\n"
        beat_review += f"Draft: {text}\n"

    return (
        f"You are a broadcast editor reviewing a {role.upper().replace('_', ' ')} "
        f"segment script for a research livestream.\n\n"
        f"Topic: {narrative_beat}\n\n"
        "== REVIEW CRITERIA ==\n"
        "For each beat, evaluate:\n"
        "1. LENGTH: Is it at least 800 characters? Beats under 600 chars are THIN.\n"
        "2. SPECIFICITY: Does it name sources WITH context, or just name-drop?\n"
        "3. ARC: Does it earn the next beat, or just stop and start a new topic?\n"
        "4. RHETORIC: Does it vary sentence length? Use direct address? Callbacks?\n"
        "5. ENERGY: Does the beat breathe, or does it rush through its material?\n"
        "6. DEPTH: Could a Wikipedia article make this same point? If yes, it's too shallow.\n\n"
        "== THE DRAFT ==\n"
        f"{beat_review}\n\n"
        "== YOUR TASK ==\n"
        "Rewrite the ENTIRE script. For beats that are strong, keep them largely "
        "intact but polish transitions. For beats that are thin, rushed, or shallow, "
        "SUBSTANTIALLY expand them — add argument, add evidence, add rhetorical "
        "texture. Every beat in the output MUST be at least 800 characters.\n\n"
        "Return a JSON array of the rewritten beats (same count as the input). "
        "Output ONLY the JSON array. No preamble, no markdown fences. "
        "Start with [ and end with ]."
    )


def _refine_script(
    script: list[str],
    programme: Any,
) -> list[str]:
    """Iterative refinement pass — critic + rewrite.

    Sends the initial draft to the LLM with a broadcast-editor persona
    that evaluates each beat on specificity, arc, length, and rhetoric,
    then rewrites weak beats.  Returns the improved script.
    """
    prompt = _build_refinement_prompt(script, programme)
    try:
        raw = _call_llm(prompt)
        refined = _parse_script(raw)
        if refined and len(refined) >= len(script):
            # Log improvement stats
            old_avg = sum(len(b) for b in script) / max(len(script), 1)
            new_avg = sum(len(b) for b in refined) / max(len(refined), 1)
            log.info(
                "refinement: avg chars/beat %.0f → %.0f (%.0f%% change)",
                old_avg,
                new_avg,
                ((new_avg - old_avg) / max(old_avg, 1)) * 100,
            )
            return refined[: len(script)]  # Trim to original beat count
        log.warning(
            "refinement: got %d beats (expected %d), keeping original",
            len(refined) if refined else 0,
            len(script),
        )
    except Exception:
        log.warning("refinement: LLM call failed, keeping original", exc_info=True)
    return script


def prep_segment(programme: Any, prep_dir: Path) -> Path | None:
    """Compose the full narration script for one programme and save it.

    Two-pass process:
      1. Initial composition — full script from the segment prompt
      2. Refinement — broadcast-editor review + rewrite of weak beats

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

    # Pass 1: Initial composition
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

    avg_chars = sum(len(b) for b in script) / max(len(script), 1)
    log.info(
        "prep_segment: pass 1 done for %s — %d beats, avg %.0f chars/beat",
        prog_id,
        len(script),
        avg_chars,
    )

    # Pass 2: Iterative refinement
    script = _refine_script(script, programme)

    # Save to disk
    out_path = prep_dir / f"{prog_id}.json"
    final_avg = sum(len(b) for b in script) / max(len(script), 1)
    payload = {
        "programme_id": prog_id,
        "role": role,
        "topic": getattr(content, "narrative_beat", "") or "",
        "segment_beats": list(beats),
        "prepared_script": script,
        "prepped_at": datetime.now(tz=UTC).isoformat(),
        "beat_count": len(beats),
        "avg_chars_per_beat": round(final_avg),
        "refinement_applied": True,
    }
    tmp = out_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(out_path)
    log.info(
        "prep_segment: saved %s (%d blocks, avg %.0f chars/beat)",
        out_path,
        len(script),
        final_avg,
    )

    # Pass 3: Self-evaluation → emit impingement
    # This is how taste develops. Hapax evaluates its own output and
    # the evaluation flows through the impingement bus into the
    # narrative drive's Bayesian prior, shaping future generation.
    _emit_self_evaluation(prog_id, role, script, beats)

    return out_path


def _emit_self_evaluation(
    prog_id: str,
    role: str,
    script: list[str],
    beat_directions: list[str],
) -> None:
    """Emit a self-evaluation impingement after segment prep.

    Scores the segment on depth, specificity, and arc — then writes
    the evaluation to the impingement bus.  The narrative drive
    consumes these impingements and accumulates them as evidence
    about what Hapax does well and where it falls short.

    This is NOT a personality simulation.  It is a selection pressure:
    segments that score well on a topic bias future planning toward
    that topic.  Segments that score poorly bias against the pattern
    that produced them.
    """
    try:
        thin_beats = sum(1 for b in script if len(b) < 600)
        avg_chars = sum(len(b) for b in script) / max(len(script), 1)
        # Rough source density: count capitalized proper nouns as proxy
        total_text = " ".join(script)
        # Words that look like source citations (capitalized, 2+ chars)
        source_like = [
            w
            for w in total_text.split()
            if len(w) > 2
            and w[0].isupper()
            and w not in ("The", "This", "That", "And", "But", "For", "Not")
        ]
        source_density = len(source_like) / max(len(total_text.split()), 1)

        quality = (
            "strong"
            if thin_beats == 0 and avg_chars > 800
            else "developing"
            if thin_beats <= 2
            else "thin"
        )

        impingement = {
            "source": "self_evaluation.segment_prep",
            "programme_id": prog_id,
            "role": role,
            "evaluation": {
                "quality": quality,
                "avg_chars_per_beat": round(avg_chars),
                "thin_beats": thin_beats,
                "total_beats": len(script),
                "source_density": round(source_density, 3),
            },
            "ts": datetime.now(tz=UTC).isoformat(),
        }

        bus_path = Path("/dev/shm/hapax-dmn/impingements.jsonl")
        if bus_path.parent.exists():
            with bus_path.open("a") as f:
                f.write(json.dumps(impingement) + "\n")
            log.info(
                "self-eval: %s quality=%s avg_chars=%.0f thin=%d sources=%.3f",
                prog_id,
                quality,
                avg_chars,
                thin_beats,
                source_density,
            )
    except Exception:
        log.debug("self-eval: impingement emission failed (non-fatal)", exc_info=True)


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

    # Step 1: Plan — call the planner in rounds until we have enough
    # segmented programmes. Each round yields ~3 programmes; for 10
    # segments we typically need 4 rounds.
    log.info("daily_segment_prep: planning programmes (target=%d)...", MAX_SEGMENTS)
    segmented: list[Any] = []
    seen_ids: set[str] = set()
    plan_round = 0
    max_rounds = (MAX_SEGMENTS // 2) + 2  # generous ceiling

    try:
        from agents.programme_manager.planner import ProgrammePlanner

        planner = ProgrammePlanner()
    except Exception:
        log.error("daily_segment_prep: planner construction failed", exc_info=True)
        return saved

    while len(segmented) < MAX_SEGMENTS and plan_round < max_rounds:
        elapsed = time.monotonic() - start
        if elapsed >= PREP_BUDGET_S:
            log.warning(
                "daily_segment_prep: prep budget exhausted during planning (%.0fs)", elapsed
            )
            break

        plan_round += 1
        show_id = f"show-{datetime.now(tz=UTC).strftime('%Y%m%d')}-{plan_round:02d}"
        try:
            plan = planner.plan(show_id=show_id)
        except Exception:
            log.warning("daily_segment_prep: planner round %d failed", plan_round, exc_info=True)
            continue

        if plan is None or not plan.programmes:
            log.warning("daily_segment_prep: planner round %d returned no programmes", plan_round)
            continue

        for p in plan.programmes:
            pid = getattr(p, "programme_id", "")
            role_val = getattr(getattr(p, "role", None), "value", "")
            if role_val in SEGMENTED_CONTENT_ROLES and pid not in seen_ids:
                segmented.append(p)
                seen_ids.add(pid)

        log.info(
            "daily_segment_prep: round %d → %d total segmented (%d new this round)",
            plan_round,
            len(segmented),
            len(
                [
                    p
                    for p in plan.programmes
                    if getattr(getattr(p, "role", None), "value", "") in SEGMENTED_CONTENT_ROLES
                ]
            ),
        )

    log.info(
        "daily_segment_prep: %d segmented programmes collected in %d rounds",
        len(segmented),
        plan_round,
    )

    # Step 2: Compose each segmented-content programme
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

    # Step 4: Upsert programme summaries into Qdrant so the affordance
    # pipeline can semantically match impingements against available
    # pre-composed content.
    _upsert_programmes_to_qdrant(segmented[:MAX_SEGMENTS], saved)

    log.info(
        "daily_segment_prep: done. %d segments prepped in %.0fs",
        len(saved),
        time.monotonic() - start,
    )
    return saved


def _upsert_programmes_to_qdrant(
    programmes: list[Any],
    saved_paths: list[Path],
) -> None:
    """Embed and upsert prepped programmes into Qdrant.

    Each programme gets a semantic summary embedded and stored in the
    affordances collection with a ``programme.prepped.*`` capability name.
    This lets the affordance pipeline's cosine-similarity retrieval
    surface relevant pre-composed programmes when impingements fire.

    Best-effort: Qdrant or Ollama unavailability does NOT block the prep.
    """
    if not programmes or not saved_paths:
        return

    try:
        import uuid

        from shared.affordance_pipeline import (
            COLLECTION_NAME,
            embed_batch_safe,
        )
        from shared.config import get_qdrant

        # Build semantic summaries for each programme
        texts: list[str] = []
        prog_ids: list[str] = []
        prog_meta: list[dict] = []
        for prog in programmes:
            pid = getattr(prog, "programme_id", None) or ""
            if not pid:
                continue
            content = getattr(prog, "content", None)
            role_value = getattr(getattr(prog, "role", None), "value", "rant")
            topic = getattr(content, "narrative_beat", "") or "" if content else ""
            beats = getattr(content, "segment_beats", []) or [] if content else []
            script = getattr(content, "prepared_script", []) or [] if content else []

            # Build a rich text summary for embedding
            beat_summary = " → ".join(str(b)[:60] for b in beats[:8])
            text = (
                f"Programme {pid}: {role_value} segment about {topic[:200]}. "
                f"Beats: {beat_summary}. "
                f"{'Pre-composed script available.' if script else 'No script yet.'}"
            )
            texts.append(text)
            prog_ids.append(pid)
            prog_meta.append(
                {
                    "programme_id": pid,
                    "role": role_value,
                    "topic": str(topic)[:500],
                    "beat_count": len(beats),
                    "has_script": bool(script),
                    "prepped_at": datetime.now(tz=UTC).isoformat(),
                }
            )

        if not texts:
            return

        # Batch embed
        embeddings = embed_batch_safe(texts, prefix="search_document")
        if embeddings is None:
            log.warning("prep qdrant: embed_batch failed, skipping Qdrant upsert")
            return

        # Build Qdrant points
        from qdrant_client.models import PointStruct

        points = []
        for i, (pid, meta) in enumerate(zip(prog_ids, prog_meta, strict=True)):
            if i >= len(embeddings) or embeddings[i] is None:
                continue
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"programme.prepped.{pid}"))
            points.append(
                PointStruct(
                    id=point_id,
                    vector=embeddings[i],
                    payload={
                        "capability_name": f"programme.prepped.{pid}",
                        "description": texts[i],
                        "daemon": "hapax_daimonion",
                        **meta,
                    },
                )
            )

        if not points:
            return

        client = get_qdrant()
        client.upsert(collection_name=COLLECTION_NAME, points=points)
        log.info("prep qdrant: upserted %d programme points", len(points))

    except Exception:
        log.warning("prep qdrant: upsert failed (non-fatal)", exc_info=True)


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
