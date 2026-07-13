from __future__ import annotations

import os
from pathlib import Path

import pytest

import shared.sdlc_task_store as task_store
from shared.sdlc_task_store import (
    ClaimDispatchBinding,
    TaskIdentityWriteIntent,
    TaskStoreError,
    assess_task_identity_index,
    build_task_identity_index,
    claim_dispatch_binding_path,
    load_claim_dispatch_binding,
    load_task_identity_write_guard,
    open_task_store_directory_fd,
    prepare_task_identity_writes,
    reconcile_task_identity_writes,
    refresh_task_identity_index,
    resolve_claim_leases,
    resolve_claim_leases_for_task,
    resolve_task_identity_projection,
    resolve_task_note,
    write_claim_dispatch_binding,
)


def _note(path: Path, task_id: str, *, extra: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\ntype: cc-task\ntask_id: {task_id}\nstatus: offered\n{extra}---\n\nbody\n",
        encoding="utf-8",
    )
    return path


def test_descriptor_walk_creates_real_directories_and_rejects_symlink_hops(
    tmp_path: Path,
) -> None:
    created = tmp_path / "vault" / "active"
    descriptor = open_task_store_directory_fd(created, create=True)
    try:
        assert os.path.samestat(os.fstat(descriptor), created.stat())
    finally:
        os.close(descriptor)

    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "vault" / "closed").symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        open_task_store_directory_fd(tmp_path / "vault" / "closed")


def test_live_identity_projection_tracks_current_state_and_request_order(tmp_path: Path) -> None:
    active = _note(tmp_path / "active" / "task-a.md", "task-a")
    closed = _note(tmp_path / "closed" / "task-b.md", "task-b")

    entries = resolve_task_identity_projection(tmp_path, ("task-b", "task-a"))

    assert [entry.path for entry in entries] == [closed.resolve(), active.resolve()]


def test_live_identity_projection_refuses_missing_and_ambiguous_identities(
    tmp_path: Path,
) -> None:
    with pytest.raises(TaskStoreError, match="task_identity_projection_missing"):
        resolve_task_identity_projection(tmp_path, ("task-a",))

    _note(tmp_path / "active" / "task-a.md", "task-a")
    _note(tmp_path / "closed" / "task-a.md", "task-a")
    with pytest.raises(TaskStoreError, match="task_identity_projection_ambiguous"):
        resolve_task_identity_projection(tmp_path, ("task-a",))


def test_resolves_exact_identity_and_preserves_exact_preimage(tmp_path: Path) -> None:
    path = _note(tmp_path / "active" / "cc-task-a.md", "cc-task-a")

    snapshot = resolve_task_note(tmp_path, "cc-task-a")

    assert snapshot.path == path.resolve()
    assert snapshot.content == path.read_bytes()
    assert snapshot.frontmatter["task_id"] == "cc-task-a"
    assert snapshot.mode == 0o644


def test_resolves_descriptor_identity(tmp_path: Path) -> None:
    path = _note(tmp_path / "active" / "cc-task-a-descriptor.md", "cc-task-a")

    assert resolve_task_note(tmp_path, "cc-task-a").path == path.resolve()


@pytest.mark.parametrize(
    ("paths", "reason_code"),
    [
        (("cc-task-a.md", "cc-task-a-descriptor.md"), "task_note_identity_ambiguous"),
        (("cc-task-a-one.md", "cc-task-a-two.md"), "task_note_identity_ambiguous"),
    ],
)
def test_refuses_multiple_identity_matches(
    tmp_path: Path, paths: tuple[str, ...], reason_code: str
) -> None:
    for name in paths:
        _note(tmp_path / "active" / name, "cc-task-a")

    with pytest.raises(TaskStoreError, match=reason_code):
        resolve_task_note(tmp_path, "cc-task-a")


def test_prefix_related_distinct_task_ids_both_resolve(tmp_path: Path) -> None:
    parent = _note(tmp_path / "active" / "cc-task-a.md", "cc-task-a")
    child = _note(tmp_path / "active" / "cc-task-a-child.md", "cc-task-a-child")

    assert resolve_task_note(tmp_path, "cc-task-a").path == parent.resolve()
    assert resolve_task_note(tmp_path, "cc-task-a-child").path == child.resolve()


def test_exact_locator_with_different_identity_refuses(tmp_path: Path) -> None:
    _note(tmp_path / "active" / "cc-task-a.md", "cc-task-b")

    with pytest.raises(TaskStoreError, match="task_note_identity_mismatch"):
        resolve_task_note(tmp_path, "cc-task-a")


def test_refuses_malformed_frontmatter(tmp_path: Path) -> None:
    path = tmp_path / "active" / "cc-task-a.md"
    path.parent.mkdir(parents=True)
    path.write_text("---\ntask_id: [\n---\n", encoding="utf-8")

    with pytest.raises(TaskStoreError, match="task_note_frontmatter_malformed"):
        resolve_task_note(tmp_path, "cc-task-a")


def test_refuses_symlink_note(tmp_path: Path) -> None:
    target = _note(tmp_path / "elsewhere.md", "cc-task-a")
    active = tmp_path / "active"
    active.mkdir()
    (active / "cc-task-a.md").symlink_to(target)

    with pytest.raises(TaskStoreError, match="task_note_path_unsafe"):
        resolve_task_note(tmp_path, "cc-task-a")


def test_refuses_symlinked_state_directory(tmp_path: Path) -> None:
    outside = tmp_path / "outside" / "active"
    _note(outside / "cc-task-a.md", "cc-task-a")
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "active").symlink_to(outside, target_is_directory=True)

    with pytest.raises(TaskStoreError, match="task_note_directory_unsafe"):
        resolve_task_note(vault, "cc-task-a")


def test_refuses_active_and_closed_duplicate_by_default(tmp_path: Path) -> None:
    _note(tmp_path / "active" / "cc-task-a.md", "cc-task-a")
    _note(tmp_path / "closed" / "cc-task-a-old.md", "cc-task-a")

    with pytest.raises(TaskStoreError, match="task_note_cross_state_duplicate"):
        resolve_task_note(tmp_path, "cc-task-a")


def test_partial_cross_state_resolution_is_forbidden(tmp_path: Path) -> None:
    _note(tmp_path / "active" / "cc-task-a.md", "cc-task-a")

    with pytest.raises(TaskStoreError, match="task_note_partial_resolution_forbidden"):
        resolve_task_note(tmp_path, "cc-task-a", require_no_other_state=False)


def test_other_state_prefix_with_different_identity_is_not_a_duplicate(tmp_path: Path) -> None:
    path = _note(tmp_path / "active" / "cc-task-a.md", "cc-task-a")
    _note(tmp_path / "closed" / "cc-task-a-other.md", "cc-task-a-other")

    assert resolve_task_note(tmp_path, "cc-task-a").path == path.resolve()


def test_refuses_active_and_refused_duplicate(tmp_path: Path) -> None:
    _note(tmp_path / "active" / "cc-task-a.md", "cc-task-a")
    _note(tmp_path / "refused" / "cc-task-a-rejected.md", "cc-task-a")

    with pytest.raises(TaskStoreError, match="task_note_cross_state_duplicate"):
        resolve_task_note(tmp_path, "cc-task-a")


def test_nonprefix_cross_state_duplicate_cannot_hide(tmp_path: Path) -> None:
    _note(tmp_path / "active" / "cc-task-a.md", "cc-task-a")
    _note(tmp_path / "closed" / "legacy-name.md", "cc-task-a")

    with pytest.raises(TaskStoreError, match="task_note_cross_state_duplicate"):
        resolve_task_note(tmp_path, "cc-task-a")


def test_nonprefix_same_state_duplicate_cannot_hide(tmp_path: Path) -> None:
    _note(tmp_path / "active" / "cc-task-a.md", "cc-task-a")
    _note(tmp_path / "active" / "legacy-name.md", "cc-task-a")

    with pytest.raises(TaskStoreError, match="task_note_identity_ambiguous"):
        resolve_task_note(tmp_path, "cc-task-a")


def test_provider_conflict_name_has_no_special_precedence(tmp_path: Path) -> None:
    _note(tmp_path / "active" / "cc-task-a.md", "cc-task-a")
    _note(
        tmp_path / "active" / "cc-task-a.sync-conflict-20260712.md",
        "cc-task-a",
    )

    with pytest.raises(TaskStoreError, match="task_note_identity_ambiguous"):
        resolve_task_note(tmp_path, "cc-task-a")


def test_requested_state_must_match_canonical_location(tmp_path: Path) -> None:
    _note(tmp_path / "closed" / "cc-task-a.md", "cc-task-a")

    with pytest.raises(TaskStoreError, match="task_note_state_mismatch"):
        resolve_task_note(tmp_path, "cc-task-a", state="active")


def test_frontier_change_during_resolution_refuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _note(tmp_path / "active" / "cc-task-a.md", "cc-task-a")
    original = task_store._state_manifest
    calls = 0

    def changed_manifest(
        vault_root: Path,
        state: task_store.TaskState,
    ) -> task_store._StateManifest:
        nonlocal calls
        calls += 1
        manifest = original(vault_root, state)
        if calls == 4:
            return (
                *manifest,
                (
                    tmp_path / "active" / "late.md",
                    (0, 0, 0, 0, 0, 0, 0, 0, 0),
                ),
            )
        return manifest

    monkeypatch.setattr(task_store, "_state_manifest", changed_manifest)

    with pytest.raises(TaskStoreError, match="task_store_frontier_changed"):
        resolve_task_note(tmp_path, "cc-task-a")


def test_explicit_index_reuses_parses_and_refreshes_only_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _note(tmp_path / "active" / "cc-task-a.md", "cc-task-a")
    other = _note(tmp_path / "active" / "cc-task-b.md", "cc-task-b")
    original = task_store._index_entry
    parsed: list[Path] = []

    def counted(
        path: Path,
        *,
        state: task_store.TaskState,
        stat_vector: task_store._StatVector,
    ) -> task_store.TaskIdentityEntry:
        parsed.append(path)
        return original(path, state=state, stat_vector=stat_vector)

    monkeypatch.setattr(task_store, "_index_entry", counted)
    index = build_task_identity_index(tmp_path)
    assert len(parsed) == 2

    resolve_task_note(tmp_path, "cc-task-a", identity_index=index)
    resolve_task_note(tmp_path, "cc-task-a", identity_index=index)
    assert len(parsed) == 2

    other.write_text(other.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
    with pytest.raises(TaskStoreError, match="task_store_frontier_changed_since_index"):
        resolve_task_note(tmp_path, "cc-task-a", identity_index=index)

    refreshed = refresh_task_identity_index(index)
    assert parsed[-1] == other
    resolve_task_note(tmp_path, "cc-task-a", identity_index=refreshed)


def test_stale_index_hold_has_complete_changed_path_evidence(tmp_path: Path) -> None:
    _note(tmp_path / "active" / "cc-task-a.md", "cc-task-a")
    changed = _note(tmp_path / "active" / "cc-task-b.md", "cc-task-b")
    index = build_task_identity_index(tmp_path)
    changed.write_text(changed.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")

    with pytest.raises(TaskStoreError) as caught:
        resolve_task_note(tmp_path, "cc-task-a", identity_index=index)

    assert caught.value.reason_code == "task_store_frontier_changed_since_index"
    assert "changed=1" in str(caught.value.detail)
    assert len(caught.value.evidence_refs) == 1
    assert "active/cc-task-b.md" in caught.value.evidence_refs[0]


def test_identity_index_root_mismatch_refuses(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _note(first / "active" / "cc-task-a.md", "cc-task-a")
    _note(second / "active" / "cc-task-a.md", "cc-task-a")
    index = build_task_identity_index(first)

    with pytest.raises(TaskStoreError, match="task_identity_index_root_mismatch"):
        resolve_task_note(second, "cc-task-a", identity_index=index)


def _write_intent(task_id: str, *, state: str = "active") -> tuple[TaskIdentityWriteIntent, bytes]:
    content = (f"---\ntype: cc-task\ntask_id: {task_id}\nstatus: blocked\n---\n\nbody\n").encode()
    relative_path = f"{state}/{task_id}.md"
    return (
        TaskIdentityWriteIntent.create(
            task_id=task_id,
            state=state,  # type: ignore[arg-type]
            relative_path=relative_path,
            content_sha256=task_store.hashlib.sha256(content).hexdigest(),
        ),
        content,
    )


def test_write_guard_round_trips_and_reconciles_exact_addition(tmp_path: Path) -> None:
    _note(tmp_path / "active" / "existing.md", "existing")
    index = build_task_identity_index(tmp_path)
    intent, content = _write_intent("new-task")

    guard = prepare_task_identity_writes(
        index,
        (intent,),
        {intent.relative_path: content},
    )
    assert guard.may_authorize is False
    assert load_task_identity_write_guard(guard.to_record(), vault_root=tmp_path) == guard

    path = tmp_path / intent.relative_path
    path.write_bytes(content)
    current = build_task_identity_index(tmp_path)
    reconciliation = reconcile_task_identity_writes(guard, current)

    assert reconciliation.complete is True
    assert reconciliation.installed_task_ids == ("new-task",)
    assert reconciliation.absent_task_ids == ()
    assert reconciliation.may_authorize is False
    assert reconciliation.base_content_frontier_hash == guard.base_content_frontier_hash
    assert reconciliation.observed_content_frontier_hash == guard.expected_content_frontier_hash


@pytest.mark.parametrize("state", ["active", "closed", "refused"])
def test_write_guard_refuses_existing_identity_under_any_locator(
    tmp_path: Path,
    state: str,
) -> None:
    _note(tmp_path / state / "legacy-descriptor.sync-conflict.md", "new-task")
    index = build_task_identity_index(tmp_path)
    intent, content = _write_intent("new-task")

    with pytest.raises(TaskStoreError, match="task_identity_write_identity_exists"):
        prepare_task_identity_writes(
            index,
            (intent,),
            {intent.relative_path: content},
        )


def test_write_guard_refuses_unclassified_unbound_artifact(tmp_path: Path) -> None:
    path = tmp_path / "closed" / "legacy.md"
    path.parent.mkdir(parents=True)
    path.write_text("---\ntitle: legacy\n---\n", encoding="utf-8")
    index = build_task_identity_index(tmp_path)
    intent, content = _write_intent("new-task")

    with pytest.raises(TaskStoreError) as caught:
        prepare_task_identity_writes(
            index,
            (intent,),
            {intent.relative_path: content},
        )

    assert caught.value.reason_code == "task_identity_write_store_unclassified"
    assert "closed/legacy.md" in caught.value.evidence_refs[0]


@pytest.mark.parametrize(
    ("task_type", "classification"),
    [("", "annotated_legacy"), ("type: cc-task\n", "legacy_cc_task")],
)
def test_terminal_legacy_snapshot_is_non_authorizing_and_does_not_globally_hold(
    tmp_path: Path,
    task_type: str,
    classification: str,
) -> None:
    path = tmp_path / "closed" / "legacy-record.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        f"---\n{task_type}title: Legacy\nstatus: done\n---\n\nbody\n",
        encoding="utf-8",
    )
    index = build_task_identity_index(tmp_path)
    assessment = assess_task_identity_index(index)
    intent, content = _write_intent("unrelated-new-task")

    guard = prepare_task_identity_writes(
        index,
        (intent,),
        {intent.relative_path: content},
    )

    assert guard.may_authorize is False
    assert assessment.blocking_unbound_refs == ()
    assert assessment.legacy_snapshots[0].classification == classification
    assert assessment.legacy_snapshots[0].legacy_locator == "legacy-record"
    assert assessment.legacy_snapshots[0].may_authorize is False
    assert assessment.to_record()["assessment_hash"] == assessment.assessment_hash


def test_write_guard_refuses_targeting_unresolved_legacy_locator(tmp_path: Path) -> None:
    path = tmp_path / "closed" / "legacy-record.md"
    path.parent.mkdir(parents=True)
    path.write_text("---\ntitle: Legacy\nstatus: completed\n---\n", encoding="utf-8")
    index = build_task_identity_index(tmp_path)
    intent, content = _write_intent("legacy-record")

    with pytest.raises(TaskStoreError, match="legacy_alias_collision"):
        prepare_task_identity_writes(index, (intent,), {intent.relative_path: content})


def test_assessment_exposes_latent_canonical_legacy_alias_collision(tmp_path: Path) -> None:
    _note(tmp_path / "active" / "canonical-descriptor.md", "legacy-record")
    legacy = tmp_path / "closed" / "legacy-record.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("---\ntitle: Legacy\nstatus: done\n---\n", encoding="utf-8")

    assessment = assess_task_identity_index(build_task_identity_index(tmp_path))

    assert assessment.legacy_canonical_collisions == ("legacy-record",)
    assert assessment.may_authorize is False


def test_write_guard_content_frontier_ignores_metadata_only_changes(tmp_path: Path) -> None:
    existing = _note(tmp_path / "active" / "existing.md", "existing")
    index = build_task_identity_index(tmp_path)
    intent, content = _write_intent("new-task")
    guard = prepare_task_identity_writes(index, (intent,), {intent.relative_path: content})
    existing.chmod(0o600)
    refreshed = build_task_identity_index(tmp_path)

    assert refreshed.content_frontier_hash == index.content_frontier_hash
    with pytest.raises(TaskStoreError, match="residual_frontier_mismatch"):
        reconcile_task_identity_writes(guard, refreshed)


def test_write_guard_refuses_staged_identity_mismatch(tmp_path: Path) -> None:
    index = build_task_identity_index(tmp_path)
    intent, _content = _write_intent("new-task")
    mismatched = b"---\ntask_id: other-task\nstatus: blocked\n---\n"
    rebound = TaskIdentityWriteIntent.create(
        task_id=intent.task_id,
        state=intent.state,
        relative_path=intent.relative_path,
        content_sha256=task_store.hashlib.sha256(mismatched).hexdigest(),
    )

    with pytest.raises(TaskStoreError, match="staged_identity_mismatch"):
        prepare_task_identity_writes(
            index,
            (rebound,),
            {rebound.relative_path: mismatched},
        )


def test_write_guard_accepts_exact_partial_then_complete_sequence(tmp_path: Path) -> None:
    first, first_content = _write_intent("first-task")
    second, second_content = _write_intent("second-task")
    index = build_task_identity_index(tmp_path)
    guard = prepare_task_identity_writes(
        index,
        (first, second),
        {first.relative_path: first_content, second.relative_path: second_content},
    )

    first_path = tmp_path / first.relative_path
    first_path.parent.mkdir(parents=True)
    first_path.write_bytes(first_content)
    partial = reconcile_task_identity_writes(guard, build_task_identity_index(tmp_path))
    assert partial.installed_task_ids == ("first-task",)
    assert partial.absent_task_ids == ("second-task",)
    assert partial.complete is False

    (tmp_path / second.relative_path).write_bytes(second_content)
    complete = reconcile_task_identity_writes(guard, build_task_identity_index(tmp_path))
    assert complete.installed_task_ids == ("first-task", "second-task")
    assert complete.complete is True


def test_write_guard_rejects_unrelated_frontier_drift(tmp_path: Path) -> None:
    existing = _note(tmp_path / "active" / "existing.md", "existing")
    index = build_task_identity_index(tmp_path)
    intent, content = _write_intent("new-task")
    guard = prepare_task_identity_writes(
        index,
        (intent,),
        {intent.relative_path: content},
    )
    (tmp_path / intent.relative_path).write_bytes(content)
    existing.write_text(existing.read_text() + "\ndrift\n")

    with pytest.raises(TaskStoreError, match="residual_content_frontier_mismatch"):
        reconcile_task_identity_writes(guard, build_task_identity_index(tmp_path))


def test_write_guard_rejects_raced_cross_state_duplicate(tmp_path: Path) -> None:
    index = build_task_identity_index(tmp_path)
    intent, content = _write_intent("new-task")
    guard = prepare_task_identity_writes(
        index,
        (intent,),
        {intent.relative_path: content},
    )
    (tmp_path / intent.relative_path).parent.mkdir(parents=True)
    (tmp_path / intent.relative_path).write_bytes(content)
    _note(tmp_path / "closed" / "raced-descriptor.md", "new-task")

    with pytest.raises(TaskStoreError, match="store_ambiguous"):
        reconcile_task_identity_writes(guard, build_task_identity_index(tmp_path))


def _binding() -> ClaimDispatchBinding:
    return ClaimDispatchBinding.create(
        task_id="cc-task-a",
        lane="cx-a",
        session_id="session-a",
        claim_epoch=123,
        dispatch_message_id="message-a",
        platform="codex",
        mode="headless",
        profile="full",
        authority_case="CASE-X",
        binding_hash="a" * 64,
        coord_dispatch_idempotency_key="dispatch-a",
    )


def test_claim_dispatch_binding_round_trips_exactly(tmp_path: Path) -> None:
    path = write_claim_dispatch_binding(tmp_path, "cx-a-session-a", _binding())

    assert path == claim_dispatch_binding_path(tmp_path, "cx-a-session-a")
    assert load_claim_dispatch_binding(path) == _binding()
    assert path.stat().st_mode & 0o777 == 0o600


def test_claim_dispatch_binding_refuses_hash_tampering(tmp_path: Path) -> None:
    path = write_claim_dispatch_binding(tmp_path, "cx-a-session-a", _binding())
    path.write_text(path.read_text().replace('"task_id":"cc-task-a"', '"task_id":"other"'))

    with pytest.raises(TaskStoreError, match="receipt_hash_mismatch"):
        load_claim_dispatch_binding(path)


def test_claim_dispatch_binding_refuses_duplicate_json_key(tmp_path: Path) -> None:
    path = tmp_path / "cc-claim-dispatch-cx-a.json"
    path.write_text('{"schema":"x","schema":"y"}\n', encoding="ascii")

    with pytest.raises(TaskStoreError, match="duplicate_key"):
        load_claim_dispatch_binding(path)


@pytest.mark.parametrize("session_id", ["", "12345", "bad/session"])
def test_claim_dispatch_binding_refuses_unkeyable_or_pid_session(session_id: str) -> None:
    with pytest.raises(TaskStoreError, match="session"):
        ClaimDispatchBinding.create(
            task_id="cc-task-a",
            lane="cx-a",
            session_id=session_id,
            claim_epoch=123,
            dispatch_message_id="message-a",
            platform="codex",
            mode="headless",
            profile="full",
            authority_case="CASE-X",
            binding_hash="a" * 64,
        )


def test_claim_dispatch_binding_refuses_non_string_identity_field(tmp_path: Path) -> None:
    path = write_claim_dispatch_binding(tmp_path, "cx-a-session-a", _binding())
    path.write_text(path.read_text().replace('"lane":"cx-a"', '"lane":7'), encoding="ascii")

    with pytest.raises(TaskStoreError, match="malformed"):
        load_claim_dispatch_binding(path)


def test_resolve_claim_leases_binds_role_session_epoch_and_dispatch(tmp_path: Path) -> None:
    binding = _binding()
    for key in ("cx-a", "cx-a-session-a"):
        (tmp_path / f"cc-active-task-{key}").write_text("cc-task-a\n")
        (tmp_path / f"cc-claim-epoch-{key}").write_text("123 cc-task-a\n")
        write_claim_dispatch_binding(tmp_path, key, binding)

    leases = resolve_claim_leases(
        tmp_path,
        role="cx-a",
        session_id="session-a",
        task_id="cc-task-a",
    )

    assert [lease.claim_key for lease in leases] == ["cx-a", "cx-a-session-a"]
    assert all(lease.binding == binding for lease in leases)


def test_role_rooted_claim_resolution_uses_bound_session(tmp_path: Path) -> None:
    binding = _binding()
    for key in ("cx-a", "cx-a-session-a"):
        (tmp_path / f"cc-active-task-{key}").write_text("cc-task-a\n")
        (tmp_path / f"cc-claim-epoch-{key}").write_text("123 cc-task-a\n")
        write_claim_dispatch_binding(tmp_path, key, binding)

    leases = resolve_claim_leases_for_task(tmp_path, role="cx-a", task_id="cc-task-a")

    assert [lease.claim_key for lease in leases] == ["cx-a", "cx-a-session-a"]


def test_resolve_claim_leases_refuses_stale_epoch_binding(tmp_path: Path) -> None:
    for key in ("cx-a", "cx-a-session-a"):
        (tmp_path / f"cc-active-task-{key}").write_text("cc-task-a\n")
        (tmp_path / f"cc-claim-epoch-{key}").write_text("124 cc-task-a\n")
        write_claim_dispatch_binding(tmp_path, key, _binding())

    with pytest.raises(TaskStoreError, match="claim_binding_vector_mismatch"):
        resolve_claim_leases(
            tmp_path,
            role="cx-a",
            session_id="session-a",
            task_id="cc-task-a",
        )
