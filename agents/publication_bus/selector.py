"""PBX-R8: local event + composed candidate -> create-only orchestrator draft.

Run ``python -m agents.publication_bus.selector --event event.json --artifact
candidate.json --register register.json --state-root STATE``. All inputs are
explicit local bindings; STATE/publish/draft must already exist. This command
never fetches, calls a judgment provider, approves, schedules, or dispatches.

The carriers are ResearchVehiclePublicEvent and PreprintArtifact. Selection
metadata travels in the artifact's existing publication_gate_context under
``emission_intent``. Supply content_form (artifact/post), external_utterance_refs
(an explicit list, empty for standalone work), manual_dispatch (bool),
expected_effect, and cancel_predicate. Optional judgment_required holds the
candidate. Missing or ambiguous declarations are held, never guessed.

Form/reply declarations identify the composer's claimed structural predicates;
length and durable targets can only strengthen them. This is not a semantic
oracle for concealed replies, earned grades, safety, or substantive novelty.
Exact body/identity matches against the supplied site register are duplicates;
same-title candidates require judgment. Other candidates are only *unmatched
in that snapshot*, not certified novel. Snapshot currency is an admission duty.
All seven doctrine checks remain explicitly not_run. Class A retains non-author
admission, C retains its bounds even alongside A, and manual transport adds the
intent/discharge/readback duties. Draft selection grants no release permission.
"""

from __future__ import annotations

import argparse
import errno
import json
import logging
import os
import re
import stat
import uuid
from hashlib import sha256
from pathlib import Path

from pydantic import ValidationError

from agents.cross_surface.bluesky_post import BLUESKY_TEXT_LIMIT
from agents.cross_surface.mastodon_post import MASTODON_TEXT_LIMIT
from shared.preprint_artifact import DRAFT_DIR_NAME, ApprovalState, PreprintArtifact
from shared.publication_artifact_public_event import _SURFACE_BY_PUBLISH_SURFACE as SURFACE_BINDINGS
from shared.research_vehicle_public_event import ResearchVehiclePublicEvent

log = logging.getLogger(__name__)
REGISTER_URL = "https://hapaxresearch.com/register/latest/register.json"
# Existing adapter text contracts (cross_surface/{bluesky,mastodon}_post.py).
SHORT_LIMITS = {"bluesky-post": BLUESKY_TEXT_LIMIT, "mastodon-post": MASTODON_TEXT_LIMIT}
# Canonical event surface identities; aliases resolve through the existing adapter.
DURABLE_SURFACES = {"omg_weblog", "zenodo"}
CHECKS = (
    "hieh_bounds",
    "chanc_fairness",
    "haca_disclosure",
    "grade_ceiling",
    "register_lint",
    "promise_registration",
    "ligatory_inscription",
)
SAFE_SLUG = re.compile(r"[a-z0-9][a-z0-9_.-]{0,119}\Z")


def _bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode()


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _register_features(path: Path, artifact: PreprintArtifact, event: ResearchVehiclePublicEvent):
    raw = path.read_bytes()
    data = json.loads(raw)
    if (
        not isinstance(data, dict)
        or data.get("schema_version") != "1.0"
        or not _nonempty(data.get("snapshot"))
        or not isinstance(data.get("records"), list)
    ):
        raise ValueError("invalid_register")
    novelty = "unmatched_in_snapshot"
    for item in data["records"]:
        if not isinstance(item, dict):
            raise ValueError("invalid_register_record")
        record = item.get("record", item)
        if not isinstance(record, dict) or not _nonempty(record.get("id")):
            raise ValueError("invalid_register_record")
        if record["id"] in {event.event_id, event.source.evidence_ref} or (
            artifact.body_md.strip() and item.get("body", "").strip() == artifact.body_md.strip()
        ):
            novelty = "duplicate"
        elif novelty != "duplicate" and record.get("title") == artifact.title:
            novelty = "judgment_required"
    return {
        "source": REGISTER_URL,
        "snapshot_path": str(path),
        "observation": "supplied_local_snapshot_only",
        "snapshot": data["snapshot"],
        "sha256": sha256(raw).hexdigest(),
        "novelty": novelty,
    }


def _selection(event: ResearchVehiclePublicEvent, artifact: PreprintArtifact, register_path: Path):
    """Compute features before exposing the unresolved judgment boundary."""
    context = artifact.publication_gate_context or {}
    meta = context.get("emission_intent")
    meta = meta if isinstance(meta, dict) else {}
    reasons = []
    fuzzy = []
    features: dict[str, object] = {"event_type": event.event_type, "hygiene_flags": []}
    if not SAFE_SLUG.fullmatch(artifact.slug):
        reasons.append("unsafe_slug")
    if artifact.approval != ApprovalState.DRAFT or artifact.approved_at is not None:
        reasons.append("input_not_draft")
    if not artifact.body_md.strip() or artifact.body_html:
        fuzzy.append("empty_or_unexamined_content")
    if not artifact.surfaces_targeted:
        fuzzy.append("no_target_surface")
    hygiene = features["hygiene_flags"]
    if event.privacy_class != "public_safe":
        hygiene.append("privacy_not_public_safe")
    if event.rights_class not in {
        "operator_original",
        "operator_controlled",
        "third_party_attributed",
    }:
        hygiene.append("rights_unresolved")
    if not (
        event.source.evidence_ref.strip()
        and _nonempty(event.source.freshness_ref)
        and event.provenance.evidence_refs
        and all(_nonempty(ref) for ref in event.provenance.evidence_refs)
        and event.provenance.rights_basis.strip()
    ):
        hygiene.append("provenance_incomplete")
    if (event.rights_class == "third_party_attributed" and not event.attribution_refs) or any(
        not _nonempty(ref) for ref in event.attribution_refs
    ):
        hygiene.append("attribution_missing")
    policy = event.surface_policy
    for surface in artifact.surfaces_targeted:
        binding = SURFACE_BINDINGS.get(surface)
        if binding is None:
            fuzzy.append("unresolved_surface_binding")
        elif binding not in policy.allowed_surfaces or binding in policy.denied_surfaces:
            hygiene.append("surface_policy_excludes_target")
    if policy.redaction_policy not in {"none", "operator_referent"}:
        hygiene.append("redaction_unresolved")
    if policy.dry_run_reason or policy.fallback_action in {"deny", "private_only", "dry_run"}:
        hygiene.append("source_policy_held")
    if policy.requires_human_review:
        fuzzy.append("source_requires_review")
    if policy.requires_audio_safe:
        fuzzy.append("audio_safety_unresolved")
    # Already-public lifecycle events must not recirculate into new proposals.
    if event.event_type in {"publication.artifact", "fanout.decision", "omg.weblog"}:
        reasons.append("publication_lifecycle_event")
    try:
        register = _register_features(register_path, artifact, event)
        features["register"] = register
        if register["novelty"] == "duplicate":
            reasons.append("register_duplicate")
        elif register["novelty"] == "judgment_required":
            fuzzy.append("register_similarity")
    except (OSError, ValueError, TypeError, AttributeError):
        reasons.append("register_unreadable_or_invalid")
    form = meta.get("content_form")
    refs = meta.get("external_utterance_refs")
    form_valid = form in ("artifact", "post")
    refs_valid = isinstance(refs, list) and all(_nonempty(x) for x in refs)
    if not form_valid:
        fuzzy.append("content_form_unresolved")
    if not refs_valid:
        fuzzy.append("reactivity_unresolved")
    if type(meta.get("manual_dispatch")) is not bool:
        fuzzy.append("transport_unresolved")
    for key in ("expected_effect", "cancel_predicate"):
        if not _nonempty(meta.get(key)):
            fuzzy.append(f"{key}_unresolved")
    if meta.get("judgment_required", False) is not False:
        fuzzy.append("declared_judgment_required")
    if not _nonempty(context.get("authority_case")) or not _nonempty(context.get("parent_spec")):
        reasons.append("authority_provenance_missing")
    # Unknown short-form bounds stay fuzzy; no invented cross-platform threshold.
    limits = [SHORT_LIMITS[s] for s in artifact.surfaces_targeted if s in SHORT_LIMITS]
    durable = any(SURFACE_BINDINGS.get(s) in DURABLE_SURFACES for s in artifact.surfaces_targeted)
    if form == "post" and not limits and not durable:
        fuzzy.append("short_form_bound_unresolved")
    content_characters = len(artifact.title + artifact.abstract + artifact.body_md)
    long_form = form == "artifact" or durable or bool(limits and content_characters > min(limits))
    classes = ["A" if long_form else "B"]
    if isinstance(refs, list) and refs:
        classes.append("C")
    strictest = "A" if "A" in classes else "C" if "C" in classes else "B"
    declared = meta.get("content_class")
    if declared is not None and declared != strictest:
        reasons.append("class_violation")
    features.update(
        body_characters=len(artifact.body_md),
        content_characters=content_characters,
        content_form=form if form_valid else {"valid": False, "type": type(form).__name__},
        external_utterance_refs=refs
        if refs_valid
        else {"valid": False, "type": type(refs).__name__},
        applicable_classes=classes,
        content_class=strictest,
    )
    return features, list(dict.fromkeys([*reasons, *hygiene, *fuzzy])), bool(fuzzy)


def _open_draft(state_root: Path) -> int:
    """Walk the declared absolute binding without following directory symlinks."""
    path = state_root.absolute() / DRAFT_DIR_NAME
    fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            if part in {".", ".."}:
                raise ValueError("unsafe_state_root")
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


class _DraftDurabilityError(OSError):
    """The matching draft is installed, but its durability is unconfirmed."""


def _create(fd: int, name: str, payload: bytes, cleanup_errors: list[int | None]) -> str:
    """Install complete bytes exclusively, including concurrent callers and replays."""
    temporary = f".selector-{uuid.uuid4().hex}.tmp"
    try:
        out = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd
        )
        with os.fdopen(out, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
            status = "created"
        except FileExistsError:
            existing = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            with os.fdopen(existing, "rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    return "conflict"
                if stream.read(len(payload) + 1) != payload:
                    return "conflict"
                try:
                    os.fsync(stream.fileno())
                except OSError as exc:
                    raise _DraftDurabilityError(exc.errno, "existing_draft_fsync_failed") from exc
            status = "replay"
        # A previous installation may have failed here. Byte equality alone is
        # insufficient for replay success: retry the durability boundary every time.
        try:
            os.fsync(fd)
        except OSError as exc:
            raise _DraftDurabilityError(exc.errno, "draft_directory_fsync_failed") from exc
        return status
    finally:
        try:
            os.unlink(temporary, dir_fd=fd)
        except FileNotFoundError:
            pass
        except OSError as exc:
            # Secondary cleanup must not erase the install result or the primary
            # failure. The caller retains both and holds even a durable install.
            cleanup_errors.append(exc.errno)


def _diagnostic(reason: str, register_path: Path, state_root: Path) -> dict[str, str]:
    """Static repair guidance: never render exception bodies or candidate content."""
    if reason == "register_unreadable_or_invalid":
        return {
            "reason": reason,
            "input": "register",
            "path": str(register_path),
            "next_action": "Supply a readable schema-1.0 register snapshot with valid records; retry.",
        }
    if reason.startswith("draft_") or reason == "unsafe_state_root":
        action = (
            "Preserve the installed draft; repair filesystem sync support and retry identical inputs "
            "until durability is confirmed. Do not dispatch or create another intent."
            if reason.startswith("draft_durability_unconfirmed")
            else "Check the existing publish/draft directory, permissions and storage; use an "
            "absolute state root without symlinks or parent traversal, then retry identical inputs."
        )
        if reason == "draft_conflict":
            action = "Inspect the existing draft without overwriting it; reconcile the candidate with its owner."
        if reason.startswith("draft_cleanup_failed"):
            action = (
                "Preserve any installed draft and its reported durability; inspect leftover "
                ".selector-*.tmp files and repair directory cleanup permissions or storage. "
                "Retry identical inputs; do not dispatch or create another intent."
            )
        return {
            "reason": reason,
            "input": "state-root",
            "path": str(state_root),
            "next_action": action,
        }
    guidance = {
        "unsafe_slug": "Use a slug of 1–120 lowercase letters, digits, dots, underscores or hyphens, starting with a letter or digit.",
        "class_violation": "Correct the declared content class to the computed strictest class; retain all applicable duties.",
        "input_not_draft": "Supply an unapproved draft candidate through the composition path.",
        "authority_provenance_missing": "Supply the existing authority case and parent spec in publication_gate_context.",
        "provenance_incomplete": "Supply nonblank source, freshness, evidence and rights references, including every list element.",
        "attribution_missing": "Supply nonblank attribution references for every third-party source.",
        "register_duplicate": "Reconcile this candidate with its existing register entry; do not create a duplicate publication.",
        "publication_lifecycle_event": "Use an originating research event; do not recirculate publication lifecycle events.",
    }
    return {
        "reason": reason,
        "next_action": guidance.get(
            reason,
            "Resolve the named selection or hygiene condition using source evidence and the existing "
            "admission process, update the candidate declarations or source policy, then rerun selection. "
            "Unresolved judgment must remain held.",
        ),
    }


def produce(
    event: ResearchVehiclePublicEvent,
    artifact: PreprintArtifact,
    *,
    register_path: Path,
    state_root: Path,
) -> dict[str, object]:
    """The only writer: recompute selection at use, then create a DRAFT exclusively."""
    features, reasons, fuzzy = _selection(event, artifact, register_path)
    judgment = "unresolved" if fuzzy else "not_invoked"
    result: dict[str, object] = {
        "status": "held",
        "judgment": judgment,
        "features": features,
        "reasons": reasons,
    }
    if not reasons:
        draft = artifact.model_copy(deep=True)
        context = draft.publication_gate_context
        receipt = context["emission_intent"]
        receipt.update(features)
        receipt.update(
            source_event=event.model_dump(mode="json"),
            judgment=judgment,
            publication_authorized=False,
            non_author_admission_required=features["content_class"] == "A",
            admission_checklist=[{"check": check, "status": "not_run"} for check in CHECKS],
            feedback_obligations=["readback", "capture", "correction"]
            + (["retro"] if features["content_class"] == "A" else []),
            reactive_obligations=[
                "pointers_only_while_disposition_open",
                "delete_pointer_on_request",
            ]
            if "C" in features["applicable_classes"]
            else [],
            manual_obligations=[
                "intent_receipt",
                "manual_discharge",
                "manual_readback_not_independent",
            ]
            if receipt["manual_dispatch"]
            else [],
        )
        receipt.pop("intent_sha256", None)
        context["publication_authorized"] = False
        # Bind content, expected effect, class, transport, provenance and outstanding duties.
        receipt["intent_sha256"] = sha256(_bytes(draft.model_dump(mode="json"))).hexdigest()
        fd = None
        cleanup_errors: list[int | None] = []
        try:
            fd = _open_draft(state_root)
            status = _create(
                fd, f"{draft.slug}.json", _bytes(draft.model_dump(mode="json")), cleanup_errors
            )
            result.update(status=status, path=str(draft.draft_path(state_root=state_root)))
            if status in {"created", "replay"}:
                result.update(installed=True, durability="confirmed")
            else:
                result["reasons"] = ["draft_conflict"]
        except _DraftDurabilityError as exc:
            result.update(
                path=str(draft.draft_path(state_root=state_root)),
                installed=True,
                durability="unconfirmed",
                reasons=[f"draft_durability_unconfirmed:{exc.errno}"],
            )
        except OSError as exc:
            result["reasons"] = [f"draft_write_refused:{exc.errno}"]
            # A final symlink is an existing intent conflict, never a replay or overwrite.
            if exc.errno == errno.ELOOP:
                result["status"] = "conflict" if fd is not None else "held"
        except ValueError:
            result["reasons"] = ["unsafe_state_root"]
        finally:
            if fd is not None:
                os.close(fd)
        if cleanup_errors:
            result["reasons"].extend(f"draft_cleanup_failed:{code}" for code in cleanup_errors)
            if result["status"] in {"created", "replay"}:
                result["status"] = "held"
    result["diagnostics"] = [
        _diagnostic(reason, register_path, state_root) for reason in result["reasons"]
    ]
    log.info(
        "publication selector status=%s judgment=%s reasons=%s",
        result["status"],
        judgment,
        result["reasons"],
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("event", "artifact", "register", "state-root"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args(argv)
    inputs = {}
    for name, model in (("event", ResearchVehiclePublicEvent), ("artifact", PreprintArtifact)):
        path = getattr(args, name)
        try:
            inputs[name] = model.model_validate_json(path.read_bytes())
        except (OSError, ValueError) as exc:
            diagnostic = {
                "input": name,
                "path": str(path),
                "next_action": "Supply a readable JSON file conforming to the named input model, repair the reported fields, and retry.",
            }
            if isinstance(exc, ValidationError):
                diagnostic["fields"] = [
                    {"location": error["loc"], "type": error["type"]}
                    for error in exc.errors(
                        include_input=False, include_context=False, include_url=False
                    )
                ]
            elif isinstance(exc, OSError):
                diagnostic["errno"] = exc.errno
            result = {
                "status": "held",
                "judgment": "not_invoked",
                "reasons": [type(exc).__name__],
                "diagnostics": [diagnostic],
            }
            break
    else:
        event, artifact = inputs["event"], inputs["artifact"]
        result = produce(event, artifact, register_path=args.register, state_root=args.state_root)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] in {"created", "replay"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
