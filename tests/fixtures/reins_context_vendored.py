# VENDORED FIXTURE -- a re-vendored copy of the governed reins_context projection engine (ruff-normalized
# to pass council CI; behaviourally identical, proven by the full-projection drift guard below), committed
# here so the resource-state producer's AIR contract tests RUN in CI (review #5027 finding 6):
# "public_or_air -> 0 facts" and AIR default-deny must be WITNESSED, not skip-gated. The governed
# reins_context is the SSOT; do NOT edit the body below to change behaviour -- edit reins and re-vendor.
#
# PINNED SOURCE (seat #5029 delta round, 2026-10-04):
#   source:         ~/projects/reins/api/reins_context.py
#   reins commit:   ff2b1a227d269cb2c04f8c0e6d5bc59303eea130
#   sha256(source): d5e9e9dd2974d08d1dd732fae3e26ba70df766fee7dbe4f7d61ab34809f9879a
# The drift guard in test_resource_state_scripts_and_contract.py requires HAPAX_REINS_ROOT to name the
# governed API directory; missing/unreadable bindings FAIL. It checks the source hash above and FULL
# per-audience projections. Both pytest CI jobs materialize the pinned Reins checkout and bind its API
# directory. Governed parity remains carried by estate-resource-state-determinative-projection-20261004.

"""reins_context — the tri-audience context-fact-bundle projection engine (convergence major-system #1).

Reins is ONE classified representational substrate rendered for THREE audiences (tri-audience):
    operator_cockpit  ·  the Yard Crow context  ·  the Hapax substrate
(+ the public_or_air channel for the livestream). It consumes the `reins_context_fact_bundle`
(reins-text-context-producer-contract) and projects it PER AUDIENCE, sealing each fact to that audience's
AIR channel BEFORE any derivation (count / sort / relation / salience / affordance) — so a field denied to
one audience can never leak through a derived channel.

Doctrine held here:
  * NEVER-INJECTOR / readout-only. Every function returns pure projection DATA. There is no send, dispatch,
    spawn, publish, spend, provider-call, or inject path in this module — action routes through the governed
    apply seam elsewhere. (coord-context-consent + never-injector-guard, baked in.)
  * Honest missing-state. A missing/denied/low-confidence fact renders absent / DARK / HOLD / stale /
    refused — NEVER a fabricated zero, live-positive, or default-certainty.
  * AIR default-DENY. An absent air decision is treated as `deny` (defense in depth), not `allow`.

Producer (spine/council bundle) lands later; this is verified against the contract's fixture now.
"""

from __future__ import annotations

# the fact_envelope.air channels — the tri-audience (+ public/on-air).
AUDIENCES = ("operator_private", "yard_context", "hapax_substrate", "public_or_air")
REDACTION_TOKEN = "▒▒▒"

# body fields that carry potentially-sensitive content — redacted (not the structural envelope) on `redact`.
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
    """Seal a fact for an audience: deny -> None (the fact is DROPPED entirely, so it cannot be counted,
    sorted, or turned into an affordance); redact -> the structural envelope survives but redactable body
    is replaced with the token; allow -> the fact as-is. Sealing happens BEFORE any derivation."""
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
    """Fold the bundle into ONE audience's projection: seal every fact for the audience FIRST (denied facts
    drop out here), then derive only over what survived. Returns a readout view (pure data)."""
    if audience not in AUDIENCES:
        raise ValueError(f"unknown audience: {audience}")
    sealed = [s for f in _facts(bundle) if (s := seal_fact(f, audience)) is not None]
    return {
        "audience": audience,
        "facts": sealed,  # only AIR-surviving facts — the derivation domain
        "fact_count": len(sealed),  # derived AFTER sealing → a denied fact is never in the count
        "affordances": [affordance_explanation(f, audience) for f in sealed],
        "bundle_state": (bundle.get("evaluation") or {}).get("bundle_state", "absent"),
    }


def project_all(bundle: dict) -> dict[str, dict]:
    """The tri-audience projection: the same substrate, one sealed readout per audience."""
    return {a: project(bundle, a) for a in AUDIENCES}


# --- classification -> affordance -> WHY (the show-WHY seed) ---------------------------------------------


def affordance_explanation(sealed_fact: dict, audience: str) -> dict:
    """Explain which affordances a (already-sealed) fact earns, and WHY — from its classification / freshness
    / confidence / air envelope. Honest states: present | absent | dark | hold | stale | refused. READOUT
    only — an affordance being `present` is permission to INSPECT/EXPLAIN, never a bypass of the governed
    apply seam."""
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

    # value_state GATES the affordance set (producer contract §Missing-State). A HOLD/refused fact must NOT
    # project as a live row with full affordances — that is the "stale rows look live" failure §7 forbids.
    if value_state == "hold":
        # evidence exists but a gate (AIR/authority/confidence/consent/review) blocks use — a hold marker
        # carrying the blocked reason + a refocus skeleton, nothing live.
        return {
            "subject_ref": subject,
            "affordances": [entry("hold", "hold"), entry("refocus", "present")],
        }
    if value_state == "refused":
        # the producer/governance spine refuses projection — refusal skeleton (inspect/refocus only).
        return {
            "subject_ref": subject,
            "affordances": [entry("inspect", "refused"), entry("refocus", "present")],
        }

    out: list[dict] = []
    # explain_why: present if the classification survived AIR (structure remains) and freshness isn't dark.
    if fresh == "dark":
        out.append(entry("explain_why", "dark"))
    elif fresh == "stale":
        out.append(entry("explain_why", "stale"))
    elif inputs.get("can_explain") or sealed_fact.get("text_domain"):
        out.append(entry("explain_why", "present"))
    else:
        out.append(entry("explain_why", "absent"))

    # refocus: present even for a redacted/stale row if the structural skeleton survived (it did — we're here).
    out.append(entry("refocus", "present"))

    # yank_operator_private: ONLY in the operator audience, un-redacted body, AND fresh — a STALE fact must
    # not offer a live yank (the contract §7 stale-not-live rule; stale evidence is inspect-only).
    if (
        audience == "operator_private"
        and inputs.get("can_yank_operator_private")
        and not redacted
        and fresh not in ("stale", "dark", "absent")
    ):
        out.append(entry("yank_operator_private", "present"))

    # stage_injection_preview: HOLD when the content is provider-prompt-eligible but egress/consent is absent
    # (requires_hold) — the classic never-injector HOLD. Never `present` from this readout.
    if inputs.get("can_enter_provider_prompt"):
        # never-injector: provider-prompt-eligible content is ALWAYS HOLD from this readout (egress/consent
        # is not reins' to grant). A "present" injection affordance would need a separate governed path.
        out.append(entry("stage_injection_preview", "hold"))

    return {"subject_ref": subject, "affordances": out}
