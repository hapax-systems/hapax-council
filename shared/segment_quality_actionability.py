"""Segment quality and actionability rubric for prepared livestream scripts."""

from __future__ import annotations

import re
from typing import Any

QUALITY_RUBRIC_VERSION = 1
ACTIONABILITY_RUBRIC_VERSION = 1
LAYOUT_RESPONSIBILITY_VERSION = 1
LAYOUT_RESPONSIBILITY_RUBRIC_VERSION = LAYOUT_RESPONSIBILITY_VERSION
RESPONSIBLE_HOSTING_CONTEXT = "hapax_responsible_live"
NON_RESPONSIBLE_STATIC_CONTEXT = "non_responsible_static"
EXPLICIT_LAYOUT_FALLBACK_CONTEXT = "explicit_fallback"
RESPONSIBLE_LAYOUT_MODE = RESPONSIBLE_HOSTING_CONTEXT
EXPLICIT_LAYOUT_FALLBACK_MODE = EXPLICIT_LAYOUT_FALLBACK_CONTEXT
NON_RESPONSIBLE_LAYOUT_MODE = NON_RESPONSIBLE_STATIC_CONTEXT
LAYOUT_RESPONSIBILITY_MODES = (
    RESPONSIBLE_HOSTING_CONTEXT,
    EXPLICIT_LAYOUT_FALLBACK_CONTEXT,
    NON_RESPONSIBLE_STATIC_CONTEXT,
)

QUALITY_RUBRIC: tuple[dict[str, str], ...] = (
    {
        "key": "premise",
        "criterion": "The opening beat names a specific, defensible premise.",
    },
    {
        "key": "tension",
        "criterion": "The segment has a reason to keep watching: paradox, conflict, ranking pressure, or stakes.",
    },
    {
        "key": "arc",
        "criterion": "Beats escalate, pivot, and land rather than repeating independent mini-essays.",
    },
    {
        "key": "specificity",
        "criterion": "Claims are grounded in named sources, artifacts, people, places, or technical nouns.",
    },
    {
        "key": "pacing",
        "criterion": "Beat lengths vary enough to breathe without collapsing into thin filler.",
    },
    {
        "key": "stakes",
        "criterion": "The host explains why the claim matters and what changes if it is true.",
    },
    {
        "key": "callbacks",
        "criterion": "Later beats reuse earlier premises or images so the segment feels composed.",
    },
    {
        "key": "audience_address",
        "criterion": "The script addresses viewers or chat when participation would improve the bit.",
    },
    {
        "key": "source_fidelity",
        "criterion": "Sources are represented as arguments with context, not decorative name-drops.",
    },
    {
        "key": "ending",
        "criterion": "The final beat resolves, reframes, or tees up a concrete next move.",
    },
)

ACTIONABILITY_RUBRIC: tuple[dict[str, str], ...] = (
    {
        "kind": "tier_chart",
        "trigger": "Place [item] in [S/A/B/C/D]-tier",
        "expected_effect": "The tier chart should update with the named item and tier.",
    },
    {
        "kind": "countdown",
        "trigger": "#N is... or Number N:",
        "expected_effect": "The countdown display should advance to the named entry number.",
    },
    {
        "kind": "iceberg_depth",
        "trigger": "surface level, going deeper, obscure, deepest, bottom of the iceberg",
        "expected_effect": "The depth visual should move to the corresponding layer.",
    },
    {
        "kind": "chat_poll",
        "trigger": "What do you think, drop it in chat, what would you change",
        "expected_effect": "The audience prompt should be treated as a chat-poll moment.",
    },
    {
        "kind": "mood_shift",
        "trigger": "Intentional escalation, skepticism, revelation, or de-escalation language",
        "expected_effect": "The visual mood should shift consistently with the spoken affect.",
    },
    {
        "kind": "comparison",
        "trigger": "Compare, contrast, versus, ranking, or tradeoff language",
        "expected_effect": "The beat should make the comparison explicit in speech or an available surface.",
    },
    {
        "kind": "source_citation",
        "trigger": "According to [source]... or [Source] argues/writes/shows...",
        "expected_effect": "The cited source or evidence context should become visible or legible.",
    },
)

LAYOUT_RESPONSIBILITY_DOCTRINE = {
    "responsible_context": (
        "Default/static layout is not acceptable success for Hapax-hosted livestream "
        "segments when Hapax is responsible for content quality."
    ),
    "allowed_static_contexts": (
        "Static default layout is allowed only as explicit TTL-bound fallback with receipt "
        "or a non-responsible context where Hapax does not control or owe layout quality."
    ),
    "contract": (
        "Responsible layout is a witnessed runtime control loop, not a template choice. "
        "Prepared artifacts propose typed layout needs derived from action intents. Runtime "
        "rendered-compositor readbacks and canonical broadcast authority decide what actually happens."
    ),
    "rendered_authority": (
        "Layout responsibility success requires StudioCompositor.layout_state rendered by "
        "fx_chain walking Layout.assignments; LayoutStore active layout/gauge success alone "
        "is advisory."
    ),
}

LAYOUT_NEED_RUBRIC: tuple[dict[str, str], ...] = (
    {
        "kind": "action_visible",
        "source_action_kind": "spoken_argument",
        "source_affordance": "argument_context",
        "expected_visible_effect": "ward:programme-context",
    },
    {
        "kind": "tier_visual",
        "source_action_kind": "tier_chart",
        "source_affordance": "tier_chart",
        "expected_visible_effect": "ward:tier-panel",
    },
    {
        "kind": "countdown_visual",
        "source_action_kind": "countdown",
        "source_affordance": "countdown",
        "expected_visible_effect": "ward:ranked-list-panel",
    },
    {
        "kind": "depth_visual",
        "source_action_kind": "iceberg_depth",
        "source_affordance": "iceberg_depth",
        "expected_visible_effect": "ward:artifact-detail-panel",
    },
    {
        "kind": "chat_prompt",
        "source_action_kind": "chat_poll",
        "source_affordance": "chat",
        "expected_visible_effect": "ward:chat-panel",
    },
    {
        "kind": "action_visible",
        "source_action_kind": "mood_shift",
        "source_affordance": "visual_mood",
        "expected_visible_effect": "ward:programme-context",
    },
    {
        "kind": "comparison",
        "source_action_kind": "comparison",
        "source_affordance": "comparison",
        "expected_visible_effect": "ward:compare-panel",
    },
    {
        "kind": "source_visible",
        "source_action_kind": "source_citation",
        "source_affordance": "source_context",
        "expected_visible_effect": "ward:artifact-detail-panel",
    },
)

_LAYOUT_NEED_BY_ACTION_KIND = {item["source_action_kind"]: item for item in LAYOUT_NEED_RUBRIC}
_FORBIDDEN_LAYOUT_AUTHORITY_KEYS = {
    "command",
    "coordinates",
    "cue",
    "cues",
    "cue_string",
    "cue_strings",
    "h",
    "height",
    "active_layout",
    "layout",
    "layout_command",
    "layout_id",
    "layout_name",
    "requested_layout",
    "selected_layout",
    "segment_cues",
    "shm_path",
    "shm_paths",
    "surface_id",
    "target_layout",
    "w",
    "width",
    "x",
    "y",
    "z-index",
    "z_index",
    "z-order",
    "z_order",
}
_STATIC_DEFAULT_LAYOUT_NAMES = {
    "balanced",
    "default",
    "default_fallback",
    "garage-door",
    "garage_door",
    "garagedoor",
    "hardcoded_rescue",
    "rescue",
    "static",
}


def _canonical_layout_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _canonical_layout_key(value: str) -> str:
    return _canonical_layout_token(value)


_FORBIDDEN_LAYOUT_AUTHORITY_KEY_TOKENS = {
    _canonical_layout_key(key) for key in _FORBIDDEN_LAYOUT_AUTHORITY_KEYS
}
_STATIC_DEFAULT_LAYOUT_TOKENS = {
    _canonical_layout_token(name) for name in _STATIC_DEFAULT_LAYOUT_NAMES
}


def _layout_value_looks_static_default(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    lowered = text.lower()
    if lowered.startswith("layout:"):
        lowered = lowered.split(":", 1)[1]
    basename = lowered.rsplit("/", 1)[-1]
    stem = basename.rsplit(".", 1)[0]
    token = _canonical_layout_token(stem)
    if token in _STATIC_DEFAULT_LAYOUT_TOKENS:
        return True
    return token.startswith(("default", "balanced", "garagedoor"))


def forbidden_layout_authority_fields(value: Any, path: str = "$") -> list[dict[str, str]]:
    """Find artifact fields that look like direct compositor authority."""
    found: list[dict[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            if _canonical_layout_key(key_text) in _FORBIDDEN_LAYOUT_AUTHORITY_KEY_TOKENS:
                found.append({"path": child_path, "field": key_text})
                continue
            found.extend(forbidden_layout_authority_fields(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(forbidden_layout_authority_fields(child, f"{path}[{index}]"))
    elif isinstance(value, str) and _layout_value_looks_static_default(value):
        found.append({"path": path, "value": value})
    return found


_TIER_RE = re.compile(
    r"\bplace\s+(?P<target>[^.?!]{2,80}?)\s+in\s+(?P<tier>[sabcd])-tier\b",
    re.IGNORECASE,
)
_COUNTDOWN_RE = re.compile(r"\b(?:#|number\s+)(?P<number>\d{1,2})\s*(?:is|:)", re.IGNORECASE)
_CHAT_RE = re.compile(
    r"\b(?:what do you think|drop it in (?:the )?chat|let me know in (?:the )?chat|"
    r"what would you change|what's your pick|what is your pick)\b",
    re.IGNORECASE,
)
_COMPARISON_RE = re.compile(
    r"\b(?:compare|contrast|versus|vs\.?|tradeoff|ranking|ranked|tier)\b",
    re.IGNORECASE,
)
_SOURCE_CITATION_RE = re.compile(
    r"\b(?:[Aa]ccording to|[Dd]rawing on|[Ff]rom)\s+"
    r"(?P<prefix_target>[^,.;:!?]{3,80})"
    r"|\b(?P<verb_target>[A-Z][A-Za-z0-9'’.-]*(?:\s+[A-Z][A-Za-z0-9'’.-]*){0,5})\s+"
    r"(?:argues|writes|says|shows|demonstrates|documents|finds|warns|claims)\b"
)
_UNSUPPORTED_ACTION_RE = re.compile(
    r"\b(?:watch this|watch the clip|play the clip|roll the clip|show the clip|"
    r"show this clip|pull up (?:the )?(?:video|image|screenshot|chart|graph)|"
    r"put (?:it|this) on screen|on screen you can see)\b",
    re.IGNORECASE,
)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")

_ICEBERG_TRIGGERS: tuple[tuple[str, str], ...] = (
    ("surface level", "surface"),
    ("commonly known", "surface"),
    ("going deeper", "middle"),
    ("specialist knowledge", "middle"),
    ("obscure", "deep"),
    ("almost nobody talks about", "deep"),
    ("the deepest", "abyss"),
    ("bottom of the iceberg", "abyss"),
)
_MOOD_TRIGGERS: tuple[tuple[str, str], ...] = (
    ("ridiculous", "escalate"),
    ("unacceptable", "escalate"),
    ("outrageous", "escalate"),
    ("fair", "de_escalate"),
    ("nuance", "de_escalate"),
    ("reasonable", "de_escalate"),
    ("brilliant", "warm"),
    ("impressive", "warm"),
    ("incredible", "warm"),
    ("wait", "skeptical"),
    ("hold on", "skeptical"),
    ("exactly", "revelation"),
    ("nailed it", "revelation"),
)


def render_quality_prompt_block() -> str:
    """Render the rubric as prompt text for resident Command-R prep."""
    quality_lines = "\n".join(f"- {item['key']}: {item['criterion']}" for item in QUALITY_RUBRIC)
    action_lines = "\n".join(
        f"- {item['kind']}: say {item['trigger']!r}; expect {item['expected_effect']}"
        for item in ACTIONABILITY_RUBRIC
    )
    layout_lines = "\n".join(
        f"- {item['source_action_kind']} -> {item['kind']}: expect "
        f"{item['expected_visible_effect']}"
        for item in LAYOUT_NEED_RUBRIC
    )
    return (
        "== SEGMENT QUALITY RUBRIC ==\n"
        f"{quality_lines}\n\n"
        "== ACTIONABILITY RUBRIC ==\n"
        "Every beat must declare what is seen, changed, ranked, compared, polled, "
        "triggered, or deliberately left as spoken argument. Do not claim a clip, "
        "screenshot, chart, or screen event unless the beat uses one of these "
        "supported affordances:\n"
        f"{action_lines}\n\n"
        "== LAYOUT RESPONSIBILITY RUBRIC ==\n"
        "In Hapax-hosted livestream contexts, default/static layout is not success. "
        "Each beat should create typed layout needs from action intents, with runtime "
        "readbacks required before a responsible layout decision counts as witnessed. "
        "Static layout is only an explicit fallback or non-responsible posture. "
        "Responsible layout is a witnessed runtime control loop, not a template choice. "
        "Do not emit direct layout commands in prose.\n"
        f"{layout_lines}\n\n"
    )


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_RE.split(text.strip()) if part.strip()]


def _intent(
    *,
    kind: str,
    trigger: str,
    expected_effect: str,
    target: str | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "kind": kind,
        "trigger": trigger,
        "expected_effect": expected_effect,
        "status": "supported",
    }
    if target:
        out["target"] = target.strip()
    return out


def _intents_for_text(text: str) -> list[dict[str, Any]]:
    intents: list[dict[str, Any]] = []
    lower = text.lower()

    for match in _TIER_RE.finditer(text):
        target = match.group("target").strip()
        tier = match.group("tier").upper()
        intents.append(
            _intent(
                kind="tier_chart",
                trigger=match.group(0),
                target=target,
                expected_effect=f"tier_chart.place:{target}:{tier}",
            )
        )

    for match in _COUNTDOWN_RE.finditer(text):
        number = match.group("number")
        intents.append(
            _intent(
                kind="countdown",
                trigger=match.group(0),
                target=number,
                expected_effect=f"countdown.current:{number}",
            )
        )

    for match in _CHAT_RE.finditer(text):
        intents.append(
            _intent(
                kind="chat_poll",
                trigger=match.group(0),
                expected_effect="chat.poll.requested",
            )
        )

    for phrase, layer in _ICEBERG_TRIGGERS:
        if phrase in lower:
            intents.append(
                _intent(
                    kind="iceberg_depth",
                    trigger=phrase,
                    target=layer,
                    expected_effect=f"iceberg.depth:{layer}",
                )
            )

    for phrase, mood in _MOOD_TRIGGERS:
        if phrase in lower:
            intents.append(
                _intent(
                    kind="mood_shift",
                    trigger=phrase,
                    target=mood,
                    expected_effect=f"visual_mood:{mood}",
                )
            )

    if _COMPARISON_RE.search(text):
        intents.append(
            _intent(
                kind="comparison",
                trigger="comparison language",
                expected_effect="spoken.comparison.explicit",
            )
        )

    seen_source_targets: set[str] = set()
    for match in _SOURCE_CITATION_RE.finditer(text):
        target = (match.group("prefix_target") or match.group("verb_target") or "").strip()
        target_key = target.lower()
        if not target or target_key in seen_source_targets:
            continue
        seen_source_targets.add(target_key)
        intents.append(
            _intent(
                kind="source_citation",
                trigger=match.group(0),
                target=target,
                expected_effect=f"source.visible:{target}",
            )
        )

    if not intents:
        intents.append(
            _intent(
                kind="spoken_argument",
                trigger="no external affordance claimed",
                expected_effect="spoken.argument.only",
            )
        )
    return intents


def _unsupported_action_lines(text: str) -> list[str]:
    return [sentence for sentence in _sentences(text) if _UNSUPPORTED_ACTION_RE.search(sentence)]


def _remove_unsupported_action_lines(text: str) -> tuple[str, list[str]]:
    removed = _unsupported_action_lines(text)
    if not removed:
        return text.strip(), []
    removed_set = set(removed)
    kept = [sentence for sentence in _sentences(text) if sentence not in removed_set]
    if not kept:
        kept = ["This beat continues the spoken argument without an unsupported visual claim."]
    return " ".join(kept).strip(), removed


def build_beat_action_intents(
    script: list[str],
    segment_beats: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Build beat-level declarations of what the spoken script should do."""
    segment_beats = segment_beats or []
    out: list[dict[str, Any]] = []
    for index, text in enumerate(script):
        beat_direction = segment_beats[index] if index < len(segment_beats) else ""
        out.append(
            {
                "beat_index": index,
                "beat_direction": beat_direction,
                "intents": _intents_for_text(text),
                "unsupported_action_lines": _unsupported_action_lines(text),
            }
        )
    return out


def validate_segment_actionability(
    script: list[str],
    segment_beats: list[str] | None = None,
) -> dict[str, Any]:
    """Return sanitized script plus beat action declarations."""
    sanitized: list[str] = []
    removed: list[dict[str, Any]] = []
    for index, text in enumerate(script):
        clean, removed_lines = _remove_unsupported_action_lines(text)
        sanitized.append(clean)
        for line in removed_lines:
            removed.append({"beat_index": index, "line": line})
    return {
        "rubric_version": ACTIONABILITY_RUBRIC_VERSION,
        "ok": not removed,
        "prepared_script": sanitized,
        "beat_action_intents": build_beat_action_intents(sanitized, segment_beats),
        "removed_unsupported_action_lines": removed,
    }


def _layout_need_from_intent(
    *,
    beat_index: int,
    intent_index: int,
    intent: dict[str, Any],
    responsibility_mode: str,
) -> dict[str, Any]:
    action_kind = str(intent.get("kind") or "spoken_argument")
    if responsibility_mode == RESPONSIBLE_HOSTING_CONTEXT and action_kind == "spoken_argument":
        return {
            "kind": "unsupported_layout_need",
            "source_action_kind": action_kind,
            "source_affordance": "spoken_argument_only",
            "expected_visible_effect": "layout.refusal.visible",
            "evidence_ref": f"beat_action_intents[{beat_index}].intents[{intent_index}]",
            "priority": "low",
            "ttl_ms": 8000,
            "hysteresis_key": "unsupported:spoken_argument_only",
            "fallback_posture": "explicit_fallback_spoken_focus",
            "readback_required": True,
            "status": "spoken_only_not_responsible",
        }
    rubric = _LAYOUT_NEED_BY_ACTION_KIND.get(action_kind)
    if rubric is None:
        return {
            "kind": "unsupported_layout_need",
            "source_action_kind": action_kind,
            "source_affordance": "unknown",
            "expected_visible_effect": "layout.refusal.visible",
            "evidence_ref": f"beat_action_intents[{beat_index}].intents[{intent_index}]",
            "priority": "low",
            "ttl_ms": 8000,
            "hysteresis_key": f"unsupported:{action_kind}",
            "fallback_posture": "explicit_fallback_spoken_focus",
            "readback_required": responsibility_mode == RESPONSIBLE_LAYOUT_MODE,
            "status": "unsupported_affordance",
        }

    target = intent.get("target")
    kind = rubric["kind"]
    return {
        "kind": kind,
        "source_action_kind": action_kind,
        "source_affordance": rubric["source_affordance"],
        "expected_visible_effect": rubric["expected_visible_effect"],
        "evidence_ref": f"beat_action_intents[{beat_index}].intents[{intent_index}]",
        "priority": "high" if action_kind != "spoken_argument" else "low",
        "ttl_ms": 12000 if action_kind != "spoken_argument" else 8000,
        "hysteresis_key": f"{kind}:{target or action_kind}",
        "fallback_posture": "explicit_fallback_spoken_focus",
        "readback_required": responsibility_mode == RESPONSIBLE_LAYOUT_MODE,
        "status": "proposed_prior",
    }


def build_beat_layout_intents(
    beat_action_intents: list[dict[str, Any]],
    *,
    responsibility_mode: str = RESPONSIBLE_HOSTING_CONTEXT,
) -> list[dict[str, Any]]:
    """Build typed layout intents from action intents without commanding layout."""
    out: list[dict[str, Any]] = []
    for declaration in beat_action_intents:
        beat_index = int(declaration.get("beat_index", len(out)))
        needs: list[str] = []
        evidence_refs: list[str] = []
        source_affordances: list[str] = []
        seen: set[tuple[str, str]] = set()
        for intent_index, intent in enumerate(declaration.get("intents") or []):
            if not isinstance(intent, dict):
                continue
            need = _layout_need_from_intent(
                beat_index=beat_index,
                intent_index=intent_index,
                intent=intent,
                responsibility_mode=responsibility_mode,
            )
            key = (need["kind"], need["hysteresis_key"])
            if key in seen:
                continue
            seen.add(key)
            need_kind = str(need["kind"])
            if need_kind not in needs:
                needs.append(need_kind)
            evidence_refs.append(str(need["evidence_ref"]))
            source_affordance = str(need["source_affordance"])
            if source_affordance not in source_affordances:
                source_affordances.append(source_affordance)
        if not needs:
            needs.append(
                str(
                    _layout_need_from_intent(
                        beat_index=beat_index,
                        intent_index=0,
                        intent={"kind": "spoken_argument"},
                        responsibility_mode=responsibility_mode,
                    )["kind"]
                )
            )
            evidence_refs.append(f"beat_action_intents[{beat_index}].intents[0]")
            source_affordances.append("host_camera_or_voice_presence")
        out.append(
            {
                "beat_id": f"beat-{beat_index + 1}",
                "beat_index": beat_index,
                "beat_direction": declaration.get("beat_direction", ""),
                "responsibility_mode": responsibility_mode,
                "needs": needs,
                "evidence_refs": evidence_refs,
                "source_affordances": source_affordances,
                "default_static_success_allowed": responsibility_mode
                in {EXPLICIT_LAYOUT_FALLBACK_CONTEXT, NON_RESPONSIBLE_STATIC_CONTEXT},
            }
        )
    return out


def build_beat_layout_needs(
    beat_action_intents: list[dict[str, Any]],
    *,
    responsibility_mode: str = RESPONSIBLE_HOSTING_CONTEXT,
) -> list[dict[str, Any]]:
    """Compatibility wrapper for the renamed beat layout intent contract."""
    return build_beat_layout_intents(
        beat_action_intents,
        responsibility_mode=responsibility_mode,
    )


def _observed_static_default_layout(observed_layout_state: dict[str, Any]) -> bool:
    if observed_layout_state.get("is_static_default") is True:
        return True
    for key in ("layout_id", "posture", "layout"):
        value = observed_layout_state.get(key)
        if isinstance(value, str) and _layout_value_looks_static_default(value):
            return True
    return False


def validate_layout_responsibility(
    beat_action_intents: list[dict[str, Any]],
    *,
    responsibility_mode: str = RESPONSIBLE_HOSTING_CONTEXT,
    observed_layout_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate the layout-responsibility contract for prepared segment needs."""
    violations: list[dict[str, Any]] = []
    if responsibility_mode not in LAYOUT_RESPONSIBILITY_MODES:
        violations.append(
            {
                "reason": "unsupported_responsibility_mode",
                "responsibility_mode": responsibility_mode,
            }
        )

    beat_layout_intents = build_beat_layout_intents(
        beat_action_intents,
        responsibility_mode=responsibility_mode,
    )
    for beat in beat_layout_intents:
        if beat.get("beat_index") is None or not isinstance(beat.get("needs"), list):
            violations.append({"reason": "invalid_beat_layout_needs", "beat": beat})
            continue
        if responsibility_mode == RESPONSIBLE_HOSTING_CONTEXT and beat.get(
            "default_static_success_allowed"
        ):
            violations.append(
                {
                    "reason": "static_default_allowed_for_responsible_beat",
                    "beat_index": beat["beat_index"],
                }
            )
        if not beat.get("evidence_refs"):
            violations.append(
                {
                    "reason": "missing_layout_evidence_refs",
                    "beat_index": beat["beat_index"],
                }
            )
        if not beat.get("source_affordances"):
            violations.append(
                {
                    "reason": "missing_layout_source_affordances",
                    "beat_index": beat["beat_index"],
                }
            )
        for need in beat["needs"]:
            if not isinstance(need, str) or not need:
                violations.append(
                    {
                        "reason": "invalid_layout_need",
                        "beat_index": beat["beat_index"],
                    }
                )
                continue
            if need == "unsupported_layout_need":
                violations.append(
                    {
                        "reason": "unsupported_layout_need",
                        "beat_index": beat["beat_index"],
                    }
                )
            if (
                responsibility_mode == RESPONSIBLE_HOSTING_CONTEXT
                and need == "action_visible"
                and "spoken_argument_only" in beat.get("source_affordances", [])
            ):
                violations.append(
                    {
                        "reason": "spoken_only_not_responsible_layout",
                        "beat_index": beat["beat_index"],
                    }
                )

    if observed_layout_state and responsibility_mode == RESPONSIBLE_HOSTING_CONTEXT:
        explicit_static_allowed = bool(
            observed_layout_state.get("fallback_explicit")
            or observed_layout_state.get("non_responsible_context")
            or observed_layout_state.get("responsibility_mode")
            in {EXPLICIT_LAYOUT_FALLBACK_CONTEXT, NON_RESPONSIBLE_STATIC_CONTEXT}
            or observed_layout_state.get("hosting_context")
            in {EXPLICIT_LAYOUT_FALLBACK_CONTEXT, NON_RESPONSIBLE_STATIC_CONTEXT}
        )
        if _observed_static_default_layout(observed_layout_state) and not explicit_static_allowed:
            violations.append(
                {
                    "reason": "static_default_layout_not_responsible_success",
                    "layout_id": observed_layout_state.get("layout_id")
                    or observed_layout_state.get("posture")
                    or observed_layout_state.get("layout"),
                }
            )
        if _observed_static_default_layout(observed_layout_state) and observed_layout_state.get(
            "fallback_explicit"
        ):
            has_fallback_receipt = bool(
                observed_layout_state.get("decision_id")
                or observed_layout_state.get("receipt_id")
                or observed_layout_state.get("readback")
            )
            has_fallback_ttl = bool(
                observed_layout_state.get("ttl_ms") or observed_layout_state.get("ttl_s")
            )
            if not (has_fallback_receipt and has_fallback_ttl):
                violations.append(
                    {
                        "reason": "static_fallback_missing_ttl_or_receipt",
                        "layout_id": observed_layout_state.get("layout_id"),
                    }
                )
        if observed_layout_state.get("claims_success") is True and not (
            observed_layout_state.get("decision_id")
            or observed_layout_state.get("receipt_id")
            or observed_layout_state.get("readback")
        ):
            violations.append(
                {
                    "reason": "layout_success_without_decision_readback",
                    "layout_id": observed_layout_state.get("layout_id"),
                }
            )
        if (
            observed_layout_state.get("layout_store_success")
            or observed_layout_state.get("gauge_success")
        ) and not (
            observed_layout_state.get("rendered_readback")
            or observed_layout_state.get("layout_state_readback")
        ):
            violations.append(
                {
                    "reason": "advisory_layout_store_not_rendered_success",
                    "layout_id": observed_layout_state.get("layout_id"),
                }
            )

    rendered_readback = bool(
        observed_layout_state
        and (
            observed_layout_state.get("rendered_readback")
            or observed_layout_state.get("layout_state_readback")
            or (
                observed_layout_state.get("readback")
                and observed_layout_state.get("readback_surface") == "rendered_compositor"
            )
        )
    )
    explicit_static_fallback_receipt = bool(
        observed_layout_state
        and observed_layout_state.get("fallback_explicit")
        and _observed_static_default_layout(observed_layout_state)
        and (observed_layout_state.get("receipt_id") or observed_layout_state.get("decision_id"))
        and (observed_layout_state.get("ttl_ms") or observed_layout_state.get("ttl_s"))
    )
    fallback_active = bool(explicit_static_fallback_receipt and not violations)
    layout_success = bool(
        observed_layout_state
        and not violations
        and rendered_readback
        and not _observed_static_default_layout(observed_layout_state)
    )

    return {
        "layout_responsibility_version": LAYOUT_RESPONSIBILITY_VERSION,
        "rubric_version": LAYOUT_RESPONSIBILITY_VERSION,
        "hosting_context": responsibility_mode,
        "responsibility_mode": responsibility_mode,
        "doctrine": dict(LAYOUT_RESPONSIBILITY_DOCTRINE),
        "ok": not violations,
        "beat_layout_intents": beat_layout_intents,
        "beat_layout_needs": beat_layout_intents,
        "violations": violations,
        "layout_decision_contract": {
            "artifact_posture": "proposal_only",
            "authority_boundary": "canonical_broadcast_runtime_decides",
            "hosting_context": responsibility_mode,
            "default_static_success_allowed": responsibility_mode
            in {EXPLICIT_LAYOUT_FALLBACK_CONTEXT, NON_RESPONSIBLE_STATIC_CONTEXT},
            "requires_runtime_affordance_readback": responsibility_mode
            == RESPONSIBLE_HOSTING_CONTEXT,
            "may_command_layout": False,
            "responsible_layout_doctrine": (
                "responsible layout is a witnessed runtime control loop, not a template choice"
            ),
            "rendered_authority": "StudioCompositor.layout_state via fx_chain/Layout.assignments",
            "advisory_not_success": ["LayoutStore.active_layout", "layout_gauge"],
        },
        "runtime_layout_validation": {
            "status": "pending_runtime_readback",
            "observed_layout_state": observed_layout_state or None,
            "ok": not violations,
            "layout_success": layout_success,
            "fallback_active": fallback_active,
            "responsible_posture_receipt_required": responsibility_mode
            == RESPONSIBLE_HOSTING_CONTEXT,
        },
        "layout_decision_receipts": [],
        "chaos_controls": {
            "bounded_vocabulary": [item["kind"] for item in LAYOUT_NEED_RUBRIC],
            "ttl_required": True,
            "hysteresis_required": True,
            "conflict_arbitration": "runtime_priority_then_freshness_then_fallback",
            "readback_required_for_responsible_mode": True,
            "fallback_posture": "explicit_fallback_spoken_focus",
        },
    }


def _word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z][A-Za-z'-]*", text))


def _proper_noun_count(text: str) -> int:
    words = re.findall(r"\b[A-Z][A-Za-z0-9'-]{2,}\b", text)
    stop = {"The", "This", "That", "But", "And", "For", "Because", "Number"}
    return len([word for word in words if word not in stop])


def _has_any(text: str, phrases: tuple[str, ...]) -> bool:
    lower = text.lower()
    return any(phrase in lower for phrase in phrases)


def score_segment_quality(
    script: list[str], segment_beats: list[str] | None = None
) -> dict[str, Any]:
    """Heuristic scorecard used by tests and prep artifacts."""
    segment_beats = segment_beats or []
    joined = " ".join(script)
    first = script[0] if script else ""
    last = script[-1] if script else ""
    lengths = [len(item) for item in script]
    avg_len = sum(lengths) / max(len(lengths), 1)
    word_count = _word_count(joined)
    proper_nouns = _proper_noun_count(joined)
    proper_density = proper_nouns / max(word_count, 1)
    thin_beats = sum(1 for item in script if len(item) < 450)
    actionability = validate_segment_actionability(script, segment_beats)
    layout = validate_layout_responsibility(actionability["beat_action_intents"])
    concrete_action_kinds = {
        intent["kind"]
        for beat in actionability["beat_action_intents"]
        for intent in beat["intents"]
        if intent.get("kind") != "spoken_argument"
    }
    concrete_layout_kinds = {
        need
        for beat in layout["beat_layout_intents"]
        for need in beat["needs"]
        if need not in {"host_presence", "unsupported_layout_need"}
    }

    scores = {
        "premise": min(
            5,
            2 + int(len(first) > 250) + int(_has_any(first, ("because", "but", "why", "problem"))),
        ),
        "tension": min(
            5,
            1
            + 2 * int(_has_any(joined, ("but", "however", "tension", "paradox", "problem")))
            + int("?" in joined),
        ),
        "arc": min(
            5,
            1
            + int(len(script) >= 3)
            + int(_has_any(joined, ("pivot", "deeper", "now", "finally", "so"))),
        ),
        "specificity": min(5, int(proper_density * 100) + int(proper_nouns >= 6)),
        "pacing": min(
            5,
            1
            + int(avg_len >= 600)
            + int(thin_beats == 0)
            + int(max(lengths or [0]) - min(lengths or [0]) > 120),
        ),
        "stakes": min(
            5,
            1 + 2 * int(_has_any(joined, ("matters", "stakes", "risk", "consequence", "changes"))),
        ),
        "callbacks": min(
            5, 1 + 2 * int(_has_any(joined, ("earlier", "remember", "back to", "circle back")))
        ),
        "audience_address": min(
            5, 1 + 2 * int(_has_any(joined, ("you", "chat", "what do you think")))
        ),
        "source_fidelity": min(
            5,
            int(proper_nouns >= 4)
            + 2 * int(_has_any(joined, ("argues", "writes", "finds", "study", "report", "source"))),
        ),
        "ending": min(
            5,
            1
            + 2
            * int(_has_any(last, ("so", "therefore", "leaves us", "next", "chat", "that is why"))),
        ),
        "actionability": min(5, 1 + int(actionability["ok"]) + min(3, len(concrete_action_kinds))),
        "layout_responsibility": min(
            5,
            1 + int(layout["ok"]) + min(3, len(concrete_layout_kinds)),
        ),
    }
    overall = round(sum(scores.values()) / len(scores), 2)
    return {
        "rubric_version": QUALITY_RUBRIC_VERSION,
        "scores": scores,
        "overall": overall,
        "label": "excellent" if overall >= 4.0 else "solid" if overall >= 3.0 else "generic",
        "diagnostics": {
            "avg_chars_per_beat": round(avg_len),
            "thin_beats": thin_beats,
            "proper_noun_count": proper_nouns,
            "word_count": word_count,
        },
    }
