"""resource_state_producer — the FIRST producer into the Reins representation.

Re-scoped task ``estate-resource-state-determinative-projection-20261004``; governing design
``frame/ESTATE-KNOWLEDGE-PRODUCERS-20261004.md``; contract
``reins-text-context-producer-contract-2026-06-30.md``.

Reduces read-only estate observations to typed facts in a ``reins_context_fact_bundle`` that
``reins/api/reins_context.py`` projects per audience. PRODUCER only: reads observations and emits
facts; never calls a model, mutates state, sends, or injects. Honest missing-state is load-bearing
(contract §Missing-State; reins AIR default-deny): a dead declared endpoint -> ``absent`` (**LOST**);
a loaded model with no admitting row -> ``hold`` (**UNEXPLAINED**); a field past its freshness window
-> ``stale`` (never a fabricated live value); an unreachable host -> ``dark``. These are fact states,
not a separate alarm system.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

SCHEMA_VERSION = 1
PRODUCER = "resource_state_producer"

# Resource facts are internal estate state: operator/yard/substrate may read; never on-air.
_AIR_INTERNAL = {
    "operator_private": "allow",
    "yard_context": "allow",
    "hapax_substrate": "allow",
    "public_or_air": "deny",
}

# Default per-field freshness windows (seconds). A field older than its window is `stale`.
FRESHNESS_WINDOWS_S = {
    "resource_vram": 300,
    "loaded_model": 300,
    "declared_endpoint": 300,
    "remote_entitlement": 86_400,
    "capability_shape": 86_400 * 7,
    "usage": 3_600,
}


def _parse_iso(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def freshness_state(observed_at: str | None, now: datetime, window_s: int) -> str:
    """fresh | aging | stale | absent. A field with no observation is `absent`, never a default."""
    if not observed_at:
        return "absent"
    obs = _parse_iso(observed_at)
    if obs is None:
        return "absent"
    age = (now - obs).total_seconds()
    if age < 0:
        return "fresh"  # clock skew; treat a just-future stamp as fresh, never stale
    if age <= window_s:
        return "fresh"
    if age <= window_s * 3:
        return "aging"
    return "stale"


def classify_declared_endpoint(declared: bool, alive: bool) -> tuple[str, list[str]]:
    """A declared serving endpoint that is dead is LOST (value_state absent) — the measured failure
    class (appendix 5000/5001 since the 10-03 reboot). An alive one is `lit`."""
    if declared and not alive:
        return "absent", ["LOST", "declared_endpoint_dead"]
    if alive:
        return "lit", []
    return "absent", ["not_declared"]


def classify_loaded_model(loaded: bool, admitting_row: str | None) -> tuple[str, list[str]]:
    """A loaded model joined to WHY (an admitting row) is `lit`. A loaded model with no admitting row
    is UNEXPLAINED (value_state hold) — evidence exists but its reason does not."""
    if loaded and admitting_row:
        return "lit", []
    if loaded and not admitting_row:
        return "hold", ["UNEXPLAINED", "no_admitting_row"]
    return "absent", ["not_loaded"]


def _fact(
    fact_type: str,
    subject_ref: str,
    *,
    now: datetime,
    observed_at: str | None,
    value: dict[str, Any],
    value_state: str,
    reason_codes: list[str] | None = None,
    confidence_word: str = "high",
    source: str = "",
    air: dict[str, str] | None = None,
) -> dict[str, Any]:
    window = FRESHNESS_WINDOWS_S.get(fact_type, 300)
    fresh = freshness_state(observed_at, now, window)
    # A stale field must not project as a live value (contract §7 stale-not-live).
    vs = "stale" if fresh == "stale" and value_state == "lit" else value_state
    return {
        "fact_id": f"{fact_type}:{subject_ref}",
        "fact_type": fact_type,
        "subject_ref": subject_ref,
        "freshness_state": fresh,
        "confidence_word": confidence_word,
        "confidence_basis": {"source": source or PRODUCER, "observed_at": observed_at},
        "provenance": {"producer": PRODUCER, "source": source, "observed_at": observed_at},
        "air": dict(air or _AIR_INTERNAL),
        "state": {"value_state": vs, "reason_codes": reason_codes or []},
        "value": value,
        "affordance_inputs": {"can_explain": True},
    }


def _model_field_facts(
    subject: str, model: str, metadata: Any, *, now: datetime
) -> list[dict[str, Any]]:
    """Project allowlisted /v1/models metadata, never process flags or model-name guesses.

    Each field has its own fact envelope. Endpoint-reported values describe the listing,
    not benchmarked fit, admitted capability, or the executable's verified identity.
    """
    fields = {
        "context_tokens": ("meta.n_ctx", "max_model_len"),
        "training_context_tokens": ("meta.n_ctx_train",),
        "quantization": ("meta.ftype",),
        "serving_owner": ("owned_by",),
        "embedding_dimensions": ("meta.n_embd",),
        "parameter_count": ("meta.n_params",),
        "model_bytes": ("meta.size",),
    }
    malformed = metadata is not None and not isinstance(metadata, dict)
    envelope = metadata if isinstance(metadata, dict) else {}
    data = envelope.get("data", [])
    malformed |= not isinstance(data, list)
    rows = (
        [r for r in data if isinstance(r, dict) and r.get("id") == model]
        if isinstance(data, list)
        else []
    )
    observed_at = envelope.get("observed_at")
    instant = _parse_iso(observed_at) if isinstance(observed_at, str) else None
    valid_time = instant is not None and instant.tzinfo is not None and instant <= now
    facts = []
    for field, paths in fields.items():
        candidates = []
        sources = []
        invalid = malformed
        for row in rows:
            for path in paths:
                value: Any = row
                for part in path.split("."):
                    if not isinstance(value, dict):
                        invalid = True
                        break
                    value = value.get(part)
                    if value is None:
                        break
                if value is None:
                    continue
                valid = (
                    isinstance(value, str) and bool(value.strip())
                    if field in {"quantization", "serving_owner"}
                    else type(value) is int and value > 0
                )
                if not valid:
                    invalid = True
                    continue
                candidates.append(value)
                sources.append(path)
        state, reasons, result = "absent", ["model_metadata_absent"], None
        if invalid:
            state, reasons = "refused", ["unsupported_model_metadata"]
        elif candidates:
            if any(v != candidates[0] for v in candidates[1:]):
                state, reasons = "hold", ["conflicting_model_metadata"]
            else:
                state, reasons, result = "lit", [], candidates[0]
                if not valid_time:
                    state, reasons = "hold", ["model_metadata_observation_time_invalid"]
        fact = _fact(
            "loaded_model",
            f"{subject}/field:{field}",
            now=now,
            observed_at=observed_at if valid_time and (candidates or invalid) else None,
            value={"model": model, "field": field, "value": result},
            value_state=state,
            reason_codes=reasons,
            confidence_word="absent" if state in {"absent", "refused"} else "medium",
            source="/v1/models " + ",".join(f"data[].{p}" for p in dict.fromkeys(sources or paths)),
        )
        # Metadata expires at its own window, not the enclosing snapshot's collection time.
        if (
            valid_time
            and candidates
            and (now - instant).total_seconds() > FRESHNESS_WINDOWS_S["loaded_model"]
        ):
            fact["freshness_state"] = "stale"
            if state == "lit":
                fact["state"]["value_state"] = "stale"
        facts.append(fact)
    return facts


def build_bundle(
    *,
    observation: dict[str, Any],
    surface: dict[str, Any] | None = None,
    admitting_rows: dict[str, str] | None = None,
    kimi_usage: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a reins_context_fact_bundle from a read-only observation + joined inputs.

    ``observation`` is one line of hapax-capacity-observer. ``admitting_rows`` maps a loaded-model
    subject_ref to its admitting row (the WHY join); a model absent from it is UNEXPLAINED.
    ``surface`` is entitlement-surface-20261004/SURFACE.json. ``kimi_usage`` is parsed kimi-bench
    ledger records (usage facts); None/empty emits a single `absent` usage fact (honest missing state).
    """
    now = now or datetime.now(UTC)
    admitting_rows = admitting_rows or {}
    obs_at = observation.get("ts")
    facts: dict[str, list[dict]] = {
        "resource_vram": [],
        "loaded_model": [],
        "declared_endpoint": [],
        "remote_entitlement": [],
        "usage": [],
    }
    # capability_shape deferred to this row's next slice (seat disposition, review #5027): no empty
    # bucket is emitted, so the bundle never signals a capability that does not exist.

    # --- VRAM / memory per host and tier (hearth classed separately in provenance) ---
    HEARTH = {"beelink1"}
    # Attribute local GPUs/endpoints to the host that actually ran the observer, never a hard-coded
    # 'appendix' (review #5027 major 4): a mislabeled host is the silently-wrong resource statement this
    # task exists to eliminate.
    local_host = observation.get("host") or "localhost"
    # Per-card VRAM from gpus_percard (index,name,total,used,FREE,util). Per-card FREE is the operator's
    # never-correct-me item (review #5027 major 1); the old 3-column gpus line dropped free+util on the
    # floor. Fall back to the back-compat line only when percard is absent, and then free/util are
    # honestly partial, never fabricated.
    for line in observation.get("gpus_percard", []) or []:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 6:
            idx, name, total, used, free, util = parts[:6]
            facts["resource_vram"].append(
                _fact(
                    "resource_vram",
                    f"host:{local_host}/card:{idx}",
                    now=now,
                    observed_at=obs_at,
                    value={
                        "card": name,
                        "index": idx,
                        "total": total,
                        "used": used,
                        "free": free,
                        "util": util,
                        "owner": "hapax",
                    },
                    value_state="lit",
                    source="nvidia-smi --query-gpu per-card",
                )
            )
    if not (observation.get("gpus_percard") or []):
        for line in observation.get("gpus", []) or []:
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3:
                name, total, used = parts[0], parts[1], parts[2]
                facts["resource_vram"].append(
                    _fact(
                        "resource_vram",
                        f"host:{local_host}/{name}",
                        now=now,
                        observed_at=obs_at,
                        value={
                            "card": name,
                            "total": total,
                            "used": used,
                            "free": None,
                            "util": None,
                            "owner": "hapax",
                        },
                        value_state="partial",
                        reason_codes=["per_card_free_util_absent_backcompat_gpus"],
                        source="nvidia-smi (3-col back-compat)",
                    )
                )
    for host, mem in (observation.get("fleet_memory") or {}).items():
        owner = "hearth" if host in HEARTH else "hapax"
        if mem is None:
            facts["resource_vram"].append(
                _fact(
                    "resource_vram",
                    f"host:{host}",
                    now=now,
                    observed_at=obs_at,
                    value={"owner": owner},
                    value_state="dark",
                    reason_codes=["host_unreachable"],
                    confidence_word="absent",
                    source="ssh",
                )
            )
        else:
            facts["resource_vram"].append(
                _fact(
                    "resource_vram",
                    f"host:{host}",
                    now=now,
                    observed_at=obs_at,
                    value={
                        "owner": owner,
                        "total_mb": mem.get("total_mb"),
                        "avail_mb": mem.get("avail_mb"),
                    },
                    value_state="lit",
                    source="ssh free -m",
                )
            )

    # --- declared serving endpoints -> LOST when dead. Only KNOWN-declared ports are classified:
    #     a probe-only port (e.g. ollama 11434) that is not a declared serving endpoint must not be
    #     reported LOST when down (declared/probed conflation overstated the LOST set). Host-attributed
    #     to the observed host, never a hard-coded 'appendix' (major 4). The NAS-backed-Docker backing
    #     is an appendix-specific ERRATA, so it is only asserted when the observer ran on appendix.
    DECLARED_PORTS = {
        "5000",
        "5001",
    }  # the declared local_serving endpoints (baseline serving.* rows)
    appendix_backing = (
        "NAS-backed Docker container (ERRATA 2026-10-04)" if local_host == "appendix" else None
    )
    for port, alive in (observation.get("local_endpoints") or {}).items():
        if str(port) not in DECLARED_PORTS:
            continue  # probed-but-not-declared: feeds loaded_model, not a declared_endpoint/LOST claim
        if not isinstance(alive, bool):
            vs, reasons = "refused", ["unsupported_endpoint_response"]
        else:
            vs, reasons = classify_declared_endpoint(declared=True, alive=bool(alive))
        value: dict[str, Any] = {"port": port, "alive": alive}
        if appendix_backing:
            value["backing"] = appendix_backing
        facts["declared_endpoint"].append(
            _fact(
                "declared_endpoint",
                f"serving.{local_host}-{port}",
                now=now,
                observed_at=obs_at,
                value=value,
                value_state=vs,
                reason_codes=reasons,
                source="curl /v1/models",
            )
        )

    # --- loaded models: ONLY from observed /v1/models ids + process inspection, NEVER a RAM-occupancy
    #     heuristic. A RAM heuristic is exactly the false resource claim this producer exists to end
    #     (review #5027 finding 1): used memory does not name a model, a quant, or a serving stack. A
    #     model with no admitting row is UNEXPLAINED. A host with no /v1/models probe makes NO loaded
    #     claim here (its memory is reported as a VRAM value above, not as a loaded model).
    serving_procs = observation.get("serving_procs") or []
    metadata = observation.get("model_metadata", {})
    for endpoint, model_ids in (observation.get("loaded_models") or {}).items():
        for model in model_ids or []:
            subj = f"host:{local_host}:{endpoint}/{model}"
            vs, reasons = classify_loaded_model(loaded=True, admitting_row=admitting_rows.get(subj))
            facts["loaded_model"].append(
                _fact(
                    "loaded_model",
                    subj,
                    now=now,
                    observed_at=obs_at,
                    value={
                        "host": local_host,
                        "endpoint": endpoint,
                        "model": model,
                        "admitting_row": admitting_rows.get(subj),
                        "serving_procs": serving_procs,
                    },
                    value_state=vs,
                    reason_codes=reasons,
                    confidence_word="high",
                    source="/v1/models + process inspection",
                )
            )
            facts["loaded_model"].extend(
                _model_field_facts(
                    subj,
                    model,
                    metadata.get(endpoint) if isinstance(metadata, dict) else metadata,
                    now=now,
                )
            )

    # --- remote entitlements from the E1 surface (ERRATA: Featherless billing is low-confidence) ---
    if surface:
        for b in surface.get("billing", []) or []:
            ent = b.get("entitlement", "")
            conf = "low" if "featherless" in ent.lower() else "medium"
            reasons = (
                ["ERRATA_featherless_billing_low_confidence_from_receipts"] if conf == "low" else []
            )
            facts["remote_entitlement"].append(
                _fact(
                    "remote_entitlement",
                    f"entitlement:{ent}",
                    now=now,
                    observed_at=surface.get("meta", {}).get("generated_at"),
                    value={
                        "vendor": b.get("vendor"),
                        "state": b.get("state"),
                        "amount": b.get("amount"),
                    },
                    value_state="lit",
                    reason_codes=reasons,
                    confidence_word=conf,
                    source="SURFACE.json",
                )
            )
    else:
        # Honest missing-state (review #5027 major 3): when the entitlement surface is not present,
        # emit an absent fact rather than silently dropping every entitlement (matching the kimi path).
        facts["remote_entitlement"].append(
            _fact(
                "remote_entitlement",
                "entitlement:surface",
                now=now,
                observed_at=None,
                value={},
                value_state="absent",
                reason_codes=["entitlement_surface_absent"],
                confidence_word="absent",
                source="SURFACE.json",
            )
        )

    # --- usage facts from the kimi-bench ledger (absent when the input is not present) ---
    if kimi_usage:
        for u in kimi_usage:
            facts["usage"].append(
                _fact(
                    "usage",
                    f"usage:kimi-bench:{u.get('model', u.get('route', '?'))}",
                    now=now,
                    observed_at=u.get("ts"),
                    value=u,
                    value_state="lit",
                    source="kimi-bench/ledger.jsonl",
                )
            )
    else:
        facts["usage"].append(
            _fact(
                "usage",
                "usage:kimi-bench",
                now=now,
                observed_at=None,
                value={},
                value_state="absent",
                reason_codes=["kimi_bench_ledger_absent"],
                confidence_word="absent",
                source="kimi-bench/ledger.jsonl",
            )
        )

    lit = sum(1 for lst in facts.values() for f in lst if f["state"]["value_state"] == "lit")
    total = sum(len(lst) for lst in facts.values())
    bundle_state = "lit" if lit == total and total else ("partial" if lit else "dark")
    return {
        "schema_version": SCHEMA_VERSION,
        "bundle_id": f"resource-state-{now.strftime('%Y%m%dT%H%M%SZ')}",
        "facts": facts,
        "evaluation": {"bundle_state": bundle_state, "confidence_word": "medium" if lit else "low"},
        "provenance": {"producer": PRODUCER, "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")},
    }


def resource_summary_for_boundary(bundle: dict[str, Any]) -> str:
    """One-line-per-concern summary reconstructed at a decision boundary (BCA: SessionStart / reset).
    Reads the bundle only — never memory."""
    facts = [f for lst in (bundle.get("facts") or {}).values() for f in lst]
    lost = [f["subject_ref"] for f in facts if "LOST" in f["state"]["reason_codes"]]
    unexpl = [f["subject_ref"] for f in facts if "UNEXPLAINED" in f["state"]["reason_codes"]]
    dark = [f["subject_ref"] for f in facts if f["state"]["value_state"] == "dark"]
    stale = [f["subject_ref"] for f in facts if f["freshness_state"] == "stale"]
    bid = bundle.get("bundle_id", "?")
    return (
        f"resource-state {bid} [{bundle.get('evaluation', {}).get('bundle_state')}]: "
        f"{len(facts)} facts; LOST={lost or '-'}; UNEXPLAINED={unexpl or '-'}; "
        f"DARK={dark or '-'}; STALE={stale or '-'}. Cite a fact id for any capacity/host/routing claim."
    )


def claim_cites_fresh_resource_fact(
    claim_text: str, bundle: dict[str, Any], *, now: datetime | None = None, window_s: int = 300
) -> bool:
    """First enforced obligation (D-011/OFP): a capacity/host/routing claim must cite a resource
    ``fact_id`` that is present in the bundle and fresher than ``window_s``. Mechanically decidable."""
    now = now or datetime.now(UTC)
    by_id = {f["fact_id"]: f for lst in (bundle.get("facts") or {}).values() for f in lst}
    for fid, f in by_id.items():
        if fid in claim_text:
            return freshness_state(f["provenance"].get("observed_at"), now, window_s) in (
                "fresh",
                "aging",
            )
    return False
