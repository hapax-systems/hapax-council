"""Topic+type composability gate (S2) — reject un-composable plans BEFORE the expensive compose.

Drops into `agents/hapax_daimonion/segment_composability_gate.py`. The S1 2x2 isolated topic+type
composability as the DOMINANT binding constraint (un-composable ≈ -2.0 pts; a clean prompt cannot rescue
it). Operator-ratified policy: STRUCTURAL must-form-the-arc composability ONLY (no taste bias). So the gate
asks one question: does (role, topic, beats) admit a BUILDING NARRATIVE ARC (concrete opening hook ->
premise -> evidence -> complication -> payoff that resolves the opening), or is it a PARALLEL/LIST
(rank/enumerate independent items; tier-list/catalogue/abstract-of-abstracts)?

FINDINGS (2026-06-15, validated 2/2 vs the 2x2 anchors in ~/segprep-s2-gate.py):
  - The RESIDENT command-r CANNOT self-assess composability (confabulates an arc onto a tier-list). A
    CAPABLE model reads the structure correctly. The predictor is the council's ``balanced`` eval route
    (``shared.config.MODELS['balanced']`` -> ``claude-sonnet``; override with ``HAPAX_COMPOSABILITY_GATE_MODEL``)
    reached through the SAME authenticated LiteLLM gateway the coherence council uses on this prep run
    (auth resolved via ``shared.config``, NOT a bare ``os.environ`` read — a raw read 401s in production
    where the key is materialized from the secrets env, which would silently render the gate inert).
  - The verdict MUST be computed deterministically from the structural signals; the model's own verdict
    field is unreliable (it returned parallel_list yet verdict=ACCEPT).
  - FAIL-OPEN: a gate error never blocks a legitimate compose (the gate is a cost optimization that skips
    wasted composes, not a hard governance gate).

Reproduce the anchor classification live (excluded from CI by the ``llm`` marker):
    uv run pytest tests/hapax_daimonion/test_segment_composability_gate.py -m llm
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
_GATE_OFF_VALUES = {"off", "0", "false", "no", "disabled"}
# The structural decision keys a real gate response MUST carry. A 200-OK that omits any of them is a
# degraded/misrouted model (the fields would silently default to False -> mass reject); treat as
# un-assessable and FAIL OPEN rather than reject a whole batch on a bad gateway route.
_REQUIRED_DECISION_KEYS = ("arc_or_list", "test1_resolves_specific_hook", "test2_reorder_breaks_it")
# Operator next-action appended to fail-open messages (executive_function axiom: errors carry a recovery).
_RECOVERY = "check the LiteLLM 'balanced' route on :4000, or disable the gate with HAPAX_COMPOSABILITY_GATE=off"
# Output-token floor for the structural verdict JSON. Default 2048 (env-overridable). A REASONING model
# served via fallback (e.g. gemini-pro for a credit-capped claude-sonnet, the 2026-06-19 incident) burns
# the budget on hidden CoT before the compact JSON; at the old 500 it truncated -> empty parse -> silent
# fail-open accept on EVERY plan (the gate went inert). Read per-call so an operator flip takes effect live.
_GATE_MAX_TOKENS_DEFAULT = 2048
_GATE_MAX_TOKENS_ENV = "HAPAX_COMPOSABILITY_GATE_MAX_TOKENS"


def _gate_max_tokens() -> int:
    try:
        return max(256, int(os.environ.get(_GATE_MAX_TOKENS_ENV, _GATE_MAX_TOKENS_DEFAULT)))
    except (TypeError, ValueError):
        return _GATE_MAX_TOKENS_DEFAULT


def _as_bool(value: object) -> bool:
    """Coerce a model-emitted truthiness signal to a real bool.

    ``bool("false")`` is True, so a JSON-schema drift that returns the STRING "false" must not be read as
    pass — that would let an un-composable plan slip the structural tests. Only genuine truthy values pass.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


def _as_score(value: object) -> float | None:
    """Coerce a model-emitted score to a float, tolerating numeric strings; None when not numeric."""
    if isinstance(value, bool):  # bool is an int subclass — reject it as a score
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


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
    # Resolve base + key via shared.config — the SAME path the coherence council uses on this gateway.
    # shared.config materializes LITELLM_API_KEY from the secrets env when it is not exported, so the gate
    # is not silently inert with a 401 in production (a bare os.environ read would be). Egress therefore
    # rides the council's existing, eval-plane-consistent route — no new consent/egress surface.
    try:
        from shared import config

        return config.LITELLM_BASE.rstrip("/") + "/v1/chat/completions", config.LITELLM_KEY
    except Exception:  # noqa: BLE001 — config import must never break the gate; fall back to env
        base = os.environ.get("LITELLM_BASE_URL", "http://127.0.0.1:4000").rstrip("/")
        return base + "/v1/chat/completions", os.environ.get("LITELLM_API_KEY", "")


def assess_composability(
    role: str, topic: str, beats: list[str], *, timeout: float = 60.0
) -> CompositionGateResult:
    """Return ACCEPT iff (arc AND resolves-specific-hook AND reorder-breaks-it AND score-not-below-floor).

    The score floor only ever TIGHTENS: a present numeric score below ``REJECT_BELOW`` rejects, but a
    missing/non-numeric score does not by itself reject (fail-open spirit) — the three structural signals
    are the load-bearing test. Truthiness signals are coerced strictly (a string ``"false"`` reads False).

    FAIL-OPEN: any error (network/model/parse) returns accept=True, errored=True — never blocks compose.
    An incomplete gateway response (HTTP 200 but missing the structural decision fields — the shape a
    misrouted/weak model produces) also fails OPEN, so a gateway misroute can never silently mass-reject a
    whole batch. The operator may hard-disable the gate with ``HAPAX_COMPOSABILITY_GATE=off`` (the repo's
    standard ``*_GATE_OFF`` killswitch pattern) if it ever misbehaves on air.
    """
    if os.environ.get("HAPAX_COMPOSABILITY_GATE", "").strip().lower() in _GATE_OFF_VALUES:
        return CompositionGateResult(
            True, "gate disabled via HAPAX_COMPOSABILITY_GATE", errored=True
        )
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
        "max_tokens": _gate_max_tokens(),
        "temperature": 0.0,
    }
    served_model = ""
    finish_reason = ""
    try:
        req = urllib.request.Request(url, json.dumps(payload).encode(), headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        choice = (data.get("choices") or [{}])[0]
        served_model = str(data.get("model") or "")
        finish_reason = str(choice.get("finish_reason") or "")
        content = (choice.get("message") or {}).get("content") or ""
        m = re.search(r"\{.*\}", content, re.DOTALL)
        parsed = json.loads(m.group(0)) if m else {}
    except Exception as exc:  # noqa: BLE001 — fail-open on any gate failure
        log.warning("composability gate could not run (fail-open accept): %s — %s", exc, _RECOVERY)
        return CompositionGateResult(
            True, f"gate unavailable (fail-open): {exc} [{_RECOVERY}]", errored=True
        )

    # LOUD truncation detection (2026-06-19 credit-cap incident): a reasoning model served via fallback
    # burns the token budget on hidden CoT, so the compact JSON truncates. Without this, the missing-fields
    # path below SILENTLY fail-opens on every plan — the gate rubber-stamps. Make the degradation visible.
    if finish_reason == "length":
        log.warning(
            "composability gate TRUNCATED (finish_reason=length) at max_tokens=%d, served_model=%s "
            "(fail-open accept, LOUD — not a real verdict): %s",
            payload["max_tokens"],
            served_model or "<unknown>",
            _RECOVERY,
        )
        return CompositionGateResult(
            True,
            f"gate truncated at max_tokens={payload['max_tokens']} "
            f"(served_model={served_model or 'unknown'}; likely a reasoning-model fallback) — "
            f"fail-open accept, NOT a real verdict [{_RECOVERY}]",
            signals={"served_model": served_model, "finish_reason": finish_reason},
            errored=True,
        )

    missing = [k for k in _REQUIRED_DECISION_KEYS if k not in parsed]
    if missing:
        log.warning(
            "composability gate response missing structural fields %s (served_model=%s) "
            "(fail-open accept): %s — %s",
            missing,
            served_model or "<unknown>",
            parsed,
            _RECOVERY,
        )
        return CompositionGateResult(
            True,
            f"gate response incomplete (fail-open): missing {missing} "
            f"(served_model={served_model or 'unknown'}) [{_RECOVERY}]",
            signals={**parsed, "served_model": served_model},
            errored=True,
        )

    shape = str(parsed.get("arc_or_list", "")).lower()
    resolves = _as_bool(parsed.get("test1_resolves_specific_hook"))
    reorder_breaks = _as_bool(parsed.get("test2_reorder_breaks_it"))
    score = _as_score(parsed.get("score"))
    score_ok = score is None or score >= REJECT_BELOW
    accept = (shape == "arc") and resolves and reorder_breaks and score_ok
    reason = (
        "composable building arc"
        if accept
        else f"un-composable {shape or 'plan'} "
        f"(resolves_specific_hook={resolves}, reorder_breaks_it={reorder_breaks}, score={score}): "
        f"{parsed.get('opening_hook', '')}"
    )
    return CompositionGateResult(accept, reason, signals={**parsed, "served_model": served_model})


# ── compose-on-reject reframe (RED-1) ────────────────────────────────────────
# The resident grounding model frames topics EXPOSITORY ("a rant on the importance
# of X", beats = "highlight / emphasize / make the case") which this gate correctly
# rejects as parallel_list. Neither more arc-exhortation nor role-restriction fixes
# the topic FRAMING (empirically: arc-role `rant` still produced expository topics).
# So, on a real reject, rewrite (topic, beats) into a true arc with the SAME capable
# eval model the gate uses, then RE-VERIFY with assess_composability — a bad reframe
# just fails the gate again, so this never airs an un-composable segment.

_REFRAME_MODEL_ENV = "HAPAX_S2_REFRAME_MODEL"


def _reframe_model() -> str:
    """Resolve the reframe model at CALL time (not import) so an env override —
    or a re-resolved GATE_MODEL — takes effect at runtime."""
    return os.environ.get(_REFRAME_MODEL_ENV) or GATE_MODEL


_REFRAME_MAX_TOKENS_ENV = "HAPAX_S2_REFRAME_MAX_TOKENS"
# Generous by design: the reframe emits a topic + several beats, and the eval route
# may serve a REASONING model (the gemini fallback when the Claude seat is down)
# that burns budget on hidden CoT before the JSON. 2048 truncated gemini-3.1-pro on
# the live RED-1 input; 8192 completes a gate-passing arc. A non-reasoning model
# (sonnet) stops early at finish_reason=stop, so this is a ceiling, not a target.
_REFRAME_MAX_TOKENS_DEFAULT = 8192


def _reframe_max_tokens() -> int:
    raw = os.environ.get(_REFRAME_MAX_TOKENS_ENV, str(_REFRAME_MAX_TOKENS_DEFAULT))
    try:
        return max(512, int(raw))
    except ValueError:
        return _REFRAME_MAX_TOKENS_DEFAULT


_REFRAME_PROMPT = """You re-frame a spoken-word broadcast segment that a STRICT structural composability
gate just REJECTED as a PARALLEL LIST (not a building narrative arc). The gate's two tests, BOTH of
which must pass:
  TEST 1 (specific-opening resolution): the OPENING beat states a SPECIFIC hook — a concrete paradox /
    disputed claim / failure — and the FINAL beat resolves THAT specific hook (not "conclude / land
    the list / make the case").
  TEST 2 (reorder-invariance): REORDERING the middle beats must BREAK the conclusion — each beat builds
    on the previous one.

REJECTED plan:
  role/type: {role}
  topic: {topic}
  beats:
{beats}
  gate verdict: {reason}

Rewrite it into a TRUE ARC on the SAME subject, keeping EVERY `src:N` source citation that appears in
the beats. Do NOT make it expository: forbid "the importance of X", "X is an asset", "highlight",
"emphasize", "review", "make the case". Open on a concrete specific hook; let each beat depend on the
last; resolve THAT hook at the end. The topic must NAME the tension/turn the arc resolves, not a label.

Answer ONLY compact JSON, no prose:
{{"topic": "<one line (<=240 chars) naming the specific tension/turn>",
"narrative_beat": "<1-2 sentence prose INTENT/direction for the segment (NOT the topic restated)>",
"beats": ["<beat 1: the specific hook>", "<beat 2 builds>", "...", "<final beat: pays off the hook>"]}}"""


def reframe_to_arc(
    role: str, topic: str, beats: list[str], *, reason: str = "", timeout: float = 60.0
) -> tuple[str, str, list[str]] | None:
    """Rewrite an expository (parallel-list) plan into a building arc via the capable eval model.

    Returns ``(new_topic, new_narrative_beat, new_beats)`` or ``None`` on any error / empty /
    malformed response. ``new_topic`` is the concrete tension (for ``declared_topic``);
    ``new_narrative_beat`` is the 1-2 sentence prose intent/direction (for ``narrative_beat`` —
    distinct from the topic), falling back to the topic only if the model omits it. The CALLER must
    re-verify the result with :func:`assess_composability` before using it — this function only
    proposes; it never asserts the rewrite is composable. Best-effort and fail-quiet (a reframe
    failure must never block prep): every error path returns ``None`` so the caller falls back to the
    existing abstain.
    """
    if not beats:
        return None
    url, key = _gateway()
    prompt = _REFRAME_PROMPT.format(
        role=role,
        topic=topic,
        reason=reason or "parallel_list",
        beats="\n".join(f"    - {b}" for b in beats),
    )
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    payload = {
        "model": _reframe_model(),
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": _reframe_max_tokens(),
        "temperature": 0.2,
    }
    try:
        req = urllib.request.Request(url, json.dumps(payload).encode(), headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        choice = (data.get("choices") or [{}])[0]
        if str(choice.get("finish_reason") or "") == "length":
            log.warning("S2 reframe truncated (finish_reason=length) — skipping reframe")
            return None
        content = (choice.get("message") or {}).get("content") or ""
        m = re.search(r"\{.*\}", content, re.DOTALL)
        parsed = json.loads(m.group(0)) if m else {}
    except Exception as exc:  # noqa: BLE001 — a reframe error must never block prep
        log.warning("S2 reframe could not run (skipping): %s", exc)
        return None
    new_topic = str(parsed.get("topic") or "").strip()
    raw_beats = parsed.get("beats")
    if not new_topic or not isinstance(raw_beats, list):
        return None
    new_beats = [str(b).strip() for b in raw_beats if str(b).strip()]
    if len(new_beats) < 2:
        return None
    # narrative_beat is a distinct 1-2 sentence prose intent (NOT the topic restated);
    # fall back to the topic only if the model omits it.
    new_narrative = str(parsed.get("narrative_beat") or "").strip() or new_topic
    return new_topic, new_narrative, new_beats
