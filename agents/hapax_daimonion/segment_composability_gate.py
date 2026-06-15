"""Topic+type composability gate (S2) — reject un-composable plans BEFORE the expensive compose.

Drops into `agents/hapax_daimonion/segment_composability_gate.py`. The S1 2x2 isolated topic+type
composability as the DOMINANT binding constraint (un-composable ≈ -2.0 pts; a clean prompt cannot rescue
it). Operator-ratified policy: STRUCTURAL must-form-the-arc composability ONLY (no taste bias). So the gate
asks one question: does (role, topic, beats) admit a BUILDING NARRATIVE ARC (concrete opening hook ->
premise -> evidence -> complication -> payoff that resolves the opening), or is it a PARALLEL/LIST
(rank/enumerate independent items; tier-list/catalogue/abstract-of-abstracts)?

FINDINGS (2026-06-15, validated 2/2 vs the 2x2 anchors in ~/segprep-s2-gate.py):
  - The RESIDENT command-r CANNOT self-assess composability (confabulates an arc onto a tier-list). A
    CAPABLE model reads the structure correctly. Predictor = claude-sonnet-4-6 via the LiteLLM gateway.
  - The verdict MUST be computed deterministically from the structural signals; the model's own verdict
    field is unreliable (it returned parallel_list yet verdict=ACCEPT).
  - FAIL-OPEN: a gate error never blocks a legitimate compose (the gate is a cost optimization that skips
    wasted composes, not a hard governance gate).
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


def _default_gate_model() -> str:
    # Eval-plane precedent: the coherence council already calls the 'balanced' model via THIS gateway
    # during the SAME prep run (members.py -> get_model('balanced')), so a non-resident structural
    # pre-filter is PERMITTED — the resident-model invariant is compose-scoped, not run-scoped. Track the
    # council's alias so this gate and the acceptor stay on the same eval model.
    try:
        from shared import config

        return config.MODELS.get("balanced", "claude-sonnet")
    except Exception:  # noqa: BLE001 — config import must never break the gate
        return "claude-sonnet"


GATE_MODEL = os.environ.get("HAPAX_COMPOSABILITY_GATE_MODEL") or _default_gate_model()
REJECT_BELOW = 3.0  # mirror the live coherence floor; <3 = un-composable

_PROMPT = """You are a STRICT STRUCTURAL composability gate for a spoken-word broadcast segment. You do NOT
judge the topic's importance or taste — only whether this plan can form a BUILDING NARRATIVE ARC. Be
SKEPTICAL: most tier-lists, rankings, and catalogues are PARALLEL LISTS, not arcs, EVEN IF each item
mentions the previous one. Default to parallel_list unless a real arc is proven by BOTH tests.

  TEST 1 (specific-opening resolution): name the OPENING HOOK in one phrase. Does the FINAL beat resolve
    THAT SPECIFIC hook (a paradox/failure stated up front is paid off), or merely "conclude / land the
    chart / finish the list"? Opening a list and closing the list is NOT resolving a paradox.
  TEST 2 (reorder-invariance): if you REORDER the middle beats, does the conclusion change? If reordering
    is HARMLESS, the beats do NOT build -> parallel list. A true arc breaks if its middle beats are reordered.

PLAN:
  role/type: {role}
  topic: {topic}
  beats:
{beats}

Answer ONLY compact JSON: {{"opening_hook": "<phrase>", "test1_resolves_specific_hook": true|false,
"test2_reorder_breaks_it": true|false, "arc_or_list": "arc"|"parallel_list",
"score": <1-5, 1=pure list no spine, 5=tight paradox->resolution arc>}}"""


@dataclass
class CompositionGateResult:
    accept: bool
    reason: str
    signals: dict = field(default_factory=dict)
    errored: bool = False  # True => fail-open accept (gate could not run)


def _gateway() -> tuple[str, str]:
    base = os.environ.get("LITELLM_BASE_URL", "http://127.0.0.1:4000").rstrip("/")
    return base + "/v1/chat/completions", os.environ.get("LITELLM_API_KEY", "")


def assess_composability(
    role: str, topic: str, beats: list[str], *, timeout: float = 60.0
) -> CompositionGateResult:
    """Return ACCEPT iff (arc AND resolves-specific-hook AND reorder-breaks-it AND score>=floor).

    FAIL-OPEN: any error (network/model/parse) returns accept=True, errored=True — never blocks compose.
    """
    if not beats:
        return CompositionGateResult(True, "no beats — defer to the upstream no-beats skip")
    url, key = _gateway()
    prompt = _PROMPT.format(role=role, topic=topic, beats="\n".join(f"    - {b}" for b in beats))
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    payload = {
        "model": GATE_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 500,
        "temperature": 0.0,
    }
    try:
        req = urllib.request.Request(url, json.dumps(payload).encode(), headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = json.loads(resp.read().decode())["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", content, re.DOTALL)
        parsed = json.loads(m.group(0)) if m else {}
    except Exception as exc:  # noqa: BLE001 — fail-open on any gate failure
        log.warning("composability gate could not run (fail-open accept): %s", exc)
        return CompositionGateResult(True, f"gate unavailable (fail-open): {exc}", errored=True)

    shape = str(parsed.get("arc_or_list", "")).lower()
    resolves = bool(parsed.get("test1_resolves_specific_hook"))
    reorder_breaks = bool(parsed.get("test2_reorder_breaks_it"))
    score = parsed.get("score")
    score_ok = (not isinstance(score, (int, float))) or score >= REJECT_BELOW
    accept = (shape == "arc") and resolves and reorder_breaks and score_ok
    reason = (
        "composable building arc"
        if accept
        else f"un-composable {shape or 'plan'} "
        f"(resolves_specific_hook={resolves}, reorder_breaks_it={reorder_breaks}, score={score}): "
        f"{parsed.get('opening_hook', '')}"
    )
    return CompositionGateResult(accept, reason, signals=parsed)
