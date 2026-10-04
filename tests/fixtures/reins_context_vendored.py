"""VENDORED FIXTURE — a verbatim copy of ``~/projects/reins/api/reins_context.py`` (the
reins-text-context-producer-contract projection engine), committed here ONLY so the resource-state
producer's contract tests RUN in CI (review #5027 finding 6): AIR default-deny and "public_or_air -> 0
facts" must be witnessed, not skip-gated.

The real reins_context is the SSOT. ``test_resource_state_producer.py`` has a drift guard that compares
this fixture against the governed reins (``HAPAX_REINS_ROOT``) when it is importable, so this copy
cannot silently diverge. Do not edit this to change behavior — edit reins and re-vendor.
"""

from __future__ import annotations

AUDIENCES = ("operator_private", "yard_context", "hapax_substrate", "public_or_air")
REDACTION_TOKEN = "▒▒▒"

_REDACTABLE_BODY = (
    "summary_ref",
    "labels",
    "extracted",
    "private_task_body",
    "raw_session_turns",
    "why_refs",
)


def air_decision(fact: dict, audience: str) -> str:
    """allow | redact | deny for a fact on an audience channel. DEFAULT-DENY on an absent decision."""
    air = fact.get("air") or {}
    dec = air.get(audience)
    return dec if dec in ("allow", "redact", "deny") else "deny"


def seal_fact(fact: dict, audience: str) -> dict | None:
    dec = air_decision(fact, audience)
    if dec == "deny":
        return None
    if dec == "allow":
        return fact
    sealed = dict(fact)
    for k in _REDACTABLE_BODY:
        if k in sealed:
            sealed[k] = REDACTION_TOKEN
    sealed["_air_redacted"] = True
    return sealed


def _facts(bundle: dict) -> list[dict]:
    out: list[dict] = []
    for lst in (bundle.get("facts") or {}).values():
        if isinstance(lst, list):
            out.extend(f for f in lst if isinstance(f, dict))
    return out


def project(bundle: dict, audience: str) -> dict:
    if audience not in AUDIENCES:
        raise ValueError(f"unknown audience: {audience}")
    sealed = [s for f in _facts(bundle) if (s := seal_fact(f, audience)) is not None]
    return {
        "audience": audience,
        "facts": sealed,
        "fact_count": len(sealed),
        "affordances": [affordance_explanation(f, audience) for f in sealed],
        "bundle_state": (bundle.get("evaluation") or {}).get("bundle_state", "absent"),
    }


def project_all(bundle: dict) -> dict[str, dict]:
    return {a: project(bundle, a) for a in AUDIENCES}


def affordance_explanation(sealed_fact: dict, audience: str) -> dict:
    subject = sealed_fact.get("subject_ref", "")
    fresh = sealed_fact.get("freshness_state", "absent")
    conf = sealed_fact.get("confidence_word", "absent")
    inputs = sealed_fact.get("affordance_inputs") or {}
    redacted = sealed_fact.get("_air_redacted", False)
    state = sealed_fact.get("state") or {}
    value_state = state.get("value_state", "lit")
    why = {
        "fact_id": sealed_fact.get("fact_id"),
        "freshness": fresh,
        "confidence": conf,
        "value_state": value_state,
        "reason_codes": state.get("reason_codes", []),
    }

    def entry(kind: str, st: str) -> dict:
        return {"subject_ref": subject, "affordance_kind": kind, "state": st, "why": why}

    if value_state == "hold":
        return {
            "subject_ref": subject,
            "affordances": [entry("hold", "hold"), entry("refocus", "present")],
        }
    if value_state == "refused":
        return {
            "subject_ref": subject,
            "affordances": [entry("inspect", "refused"), entry("refocus", "present")],
        }

    out: list[dict] = []
    if fresh == "dark":
        out.append(entry("explain_why", "dark"))
    elif fresh == "stale":
        out.append(entry("explain_why", "stale"))
    elif inputs.get("can_explain") or sealed_fact.get("text_domain"):
        out.append(entry("explain_why", "present"))
    else:
        out.append(entry("explain_why", "absent"))

    out.append(entry("refocus", "present"))

    if (
        audience == "operator_private"
        and inputs.get("can_yank_operator_private")
        and not redacted
        and fresh not in ("stale", "dark", "absent")
    ):
        out.append(entry("yank_operator_private", "present"))

    if inputs.get("can_enter_provider_prompt"):
        out.append(entry("stage_injection_preview", "hold"))

    return {"subject_ref": subject, "affordances": out}
