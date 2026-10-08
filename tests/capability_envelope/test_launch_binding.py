"""Real adapter/dispatch code with in-memory ledgers and a synthetic T2 executor."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from shared import coord_dispatch
from shared.capability_adapter_protocol import AuthorityViolation, CodexAdapter
from shared.capability_envelope import EnvelopeDeclaration, render
from shared.coord_dispatch import CoordDispatchError, DispatchLaunchRequest
from shared.dispatcher_policy import DispatchAction, RouteDecision

UNIT = {"memory_high": 64, "memory_max": 128, "memory_swap_max": 0, "runtime_max_sec": 30}


def declaration(**overrides):
    return EnvelopeDeclaration(
        **{
            "harness": "claude",
            "argv": ("/usr/bin/true",),
            "unit": UNIT,
            "billing_surface": "api",
            **overrides,
        }
    )


def decision(allowed=True):
    return RouteDecision(
        decision_id="fixture",
        created_at=datetime.now(UTC),
        task_id="fixture",
        lane="fixture",
        route_id="fixture",
        platform="codex",
        mode="headless",
        profile="full",
        action=DispatchAction.LAUNCH if allowed else DispatchAction.REFUSE,
        policy_outcome="fixture",
        launch_allowed=allowed,
        prompt_allowed=False,
        quality_floor_satisfied=True,
        authority_allowed=allowed,
        message="fixture",
    )


class Log:
    def __init__(self):
        self.events = []

    def replay(self, **kwargs):
        return SimpleNamespace(events=self.events)

    def append(self, event, **kwargs):
        self.events.append(event)


def request(tmp_path, envelope=None):
    return DispatchLaunchRequest(
        task_id="fixture",
        lane="fixture",
        platform="codex",
        mode="headless",
        profile="full",
        authority_case="CASE-SYSTEM-INTEGRITY-20260611",
        parent_spec="synthetic-parent",
        message_id="synthetic-message",
        mq_db_path=tmp_path / "unused.db",
        event_log=Log(),
        envelope=envelope,
    )


@pytest.fixture
def boundaries(monkeypatch):
    accepted, cleanup, execute = Mock(), Mock(), Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(coord_dispatch, "_accept_dispatch_message", accepted)
    monkeypatch.setattr(coord_dispatch, "_cleanup_dispatch_message", cleanup)
    monkeypatch.setattr(coord_dispatch, "lane_is_retired", lambda lane: False)
    import importlib

    monkeypatch.setattr(
        importlib.import_module("shared.capability_envelope.render"), "execute", execute
    )
    return accepted, cleanup, execute


def test_declared_launch_cannot_fall_back_to_unenveloped_callable(tmp_path, boundaries):
    req = request(tmp_path, declaration())
    legacy = Mock(return_value=0)
    with pytest.raises(CoordDispatchError, match="rendered_envelope_required"):
        CodexAdapter().launch(decision(), req, legacy)
    legacy.assert_not_called()
    for boundary in boundaries:
        boundary.assert_not_called()
    assert req.event_log.events == []


def test_existing_unenveloped_request_still_uses_its_callable(tmp_path, boundaries):
    req = request(tmp_path)
    legacy = Mock(return_value=0)
    result = CodexAdapter().launch(decision(), req, legacy)
    assert result.launched is True
    legacy.assert_called_once_with()
    boundaries[2].assert_not_called()
    assert all(e.payload["envelope_sha256"] is None for e in req.event_log.events)


def test_bound_t2_reaches_existing_executor_and_records_same_identity(tmp_path, boundaries):
    req = request(tmp_path, declaration())
    rendered = render(req.envelope, run_root=tmp_path / "run")
    legacy = Mock(return_value=0)
    result = CodexAdapter().launch(decision(), req, legacy, rendered_envelope=rendered)
    assert result.launched is True
    legacy.assert_not_called()
    actual = boundaries[2].call_args
    assert actual.args[0] == rendered
    assert actual.kwargs == {"timeout": 30}
    assert len(req.event_log.events) == 2
    assert all(
        e.payload["envelope_sha256"] == rendered.facts["declaration_sha256"]
        for e in req.event_log.events
    )
    again = CodexAdapter().launch(decision(), req, legacy, rendered_envelope=rendered)
    assert again.replayed is True
    boundaries[2].assert_called_once()


@pytest.mark.parametrize("carrier", ["t1", "t3"])
def test_unimplemented_unit_oci_execution_refuses_before_mq(tmp_path, boundaries, carrier):
    req = request(tmp_path, declaration())
    rendered = render(
        req.envelope,
        run_root=tmp_path / "run",
        carrier=carrier,
        oci_uid=100000,
        oci_gid=100000,
        oci_launcher_uid=1000,
        oci_launcher_gid=1000,
    )
    with pytest.raises(
        CoordDispatchError,
        match="runner_unavailable.*next action:.*independent acceptance.*executor admission",
    ):
        CodexAdapter().launch(decision(), req, Mock(), rendered_envelope=rendered)
    for boundary in boundaries:
        boundary.assert_not_called()


def test_mutated_declaration_is_not_silently_rebound(tmp_path, boundaries):
    req = request(tmp_path, declaration(env={"DECLARED": "before"}))
    rendered = render(req.envelope, run_root=tmp_path / "run")
    req.envelope.env["DECLARED"] = "after"
    with pytest.raises(CoordDispatchError, match="envelope_identity_changed"):
        CodexAdapter().launch(decision(), req, Mock(), rendered_envelope=rendered)
    for boundary in boundaries:
        boundary.assert_not_called()


@pytest.mark.parametrize("change", ["command", "environment"])
def test_forged_renderer_metadata_cannot_hide_changed_command_or_env(tmp_path, boundaries, change):
    req = request(tmp_path, declaration())
    rendered = render(req.envelope, run_root=tmp_path / "run")
    argv = list(rendered.argv)
    if change == "command":
        argv[-1] = "/undeclared-program"
    else:
        i = argv.index("--clearenv") + 1
        argv[i:i] = ["--setenv", "UNDECLARED", "value"]
    corrupted = rendered.model_copy(update={"argv": tuple(argv)})
    with pytest.raises(ValueError, match="conformance"):
        CodexAdapter().launch(decision(), req, Mock(), rendered_envelope=corrupted)
    for boundary in boundaries:
        boundary.assert_not_called()


def test_replay_cannot_accept_a_different_envelope_identity(tmp_path, boundaries):
    req = request(tmp_path, declaration())
    rendered = render(req.envelope, run_root=tmp_path / "run")
    CodexAdapter().launch(decision(), req, Mock(), rendered_envelope=rendered)
    req.event_log.events[-1].payload["envelope_sha256"] = "wrong"
    with pytest.raises(
        CoordDispatchError,
        match="envelope_identity_mismatch.*next action:.*original declaration.*new launch",
    ):
        coord_dispatch.replay_terminal_result(req, idempotency_key=req.effective_idempotency_key)


def test_authority_refusal_precedes_envelope_processing(tmp_path, boundaries):
    req = request(tmp_path, declaration())
    with pytest.raises(AuthorityViolation):
        CodexAdapter().launch(decision(False), req, Mock(), rendered_envelope=None)
    for boundary in boundaries:
        boundary.assert_not_called()


def test_rendered_envelope_without_a_declaration_is_not_legacy_compatibility(tmp_path, boundaries):
    req = request(tmp_path)
    rendered = render(declaration(), run_root=tmp_path / "run")
    legacy = Mock()
    with pytest.raises(CoordDispatchError, match="undeclared_envelope"):
        CodexAdapter().launch(decision(), req, legacy, rendered_envelope=rendered)
    legacy.assert_not_called()
    for boundary in boundaries:
        boundary.assert_not_called()


def test_rendered_identity_must_match_launch_declaration(tmp_path, boundaries):
    req = request(tmp_path, declaration())
    rendered = render(declaration(env={"DECLARED": "different"}), run_root=tmp_path / "run")
    with pytest.raises(CoordDispatchError, match="envelope_identity_mismatch"):
        CodexAdapter().launch(decision(), req, Mock(), rendered_envelope=rendered)
    for boundary in boundaries:
        boundary.assert_not_called()


@pytest.mark.parametrize(
    "carrier,element",
    [
        (carrier, flag)
        for carrier in ("t1", "t2")
        for flag in (
            "--unshare-pid",
            "--unshare-ipc",
            "--unshare-net",
            "--unshare-uts",
            "--unshare-cgroup-try",
            "--die-with-parent",
            "--new-session",
            "--clearenv",
        )
    ]
    + [
        ("t3", namespace)
        for namespace in ("pid", "ipc", "uts", "mount", "user", "network", "cgroup")
    ],
)
@pytest.mark.parametrize("change", ["remove", "duplicate"])
def test_isolation_refuses_before_dispatch(tmp_path, boundaries, carrier, element, change):
    import copy

    req = request(tmp_path, declaration())
    result = render(
        req.envelope,
        run_root=tmp_path / "run",
        carrier=carrier,
        oci_uid=100000,
        oci_gid=100000,
        oci_launcher_uid=1000,
        oci_launcher_gid=1000,
    )
    if carrier == "t3":
        spec = copy.deepcopy(result.oci_spec)
        parts = spec["linux"]["namespaces"]
        entry = {"type": element}
        if change == "remove":
            parts.remove(entry)
        else:
            parts.append(entry)
        result = result.model_copy(update={"oci_spec": spec})
    else:
        argv = list(result.argv)
        if change == "remove":
            argv.remove(element)
        else:
            argv.insert(argv.index(element), element)
        result = result.model_copy(update={"argv": tuple(argv)})
    legacy = Mock()
    with pytest.raises(ValueError, match="conformance"):
        CodexAdapter().launch(decision(), req, legacy, rendered_envelope=result)
    legacy.assert_not_called()
    for boundary in boundaries:
        boundary.assert_not_called()
    assert req.event_log.events == []


@pytest.mark.parametrize("carrier", ["t1", "t2", "t3"])
@pytest.mark.parametrize("entry", ["file", "directory", "symlink"])
def test_home_injection_refuses_before_dispatch(tmp_path, boundaries, carrier, entry):
    req = request(tmp_path, declaration())
    result = render(
        req.envelope,
        run_root=tmp_path / "run",
        carrier=carrier,
        oci_uid=100000,
        oci_gid=100000,
        oci_launcher_uid=1000,
        oci_launcher_gid=1000,
    )
    path = result.run_root / "home" / "CLAUDE.md"
    if entry == "file":
        path.write_text("undeclared")
    elif entry == "directory":
        path.mkdir()
    else:
        path.symlink_to(tmp_path / "missing")
    legacy = Mock()
    with pytest.raises(ValueError, match="conformance"):
        CodexAdapter().launch(decision(), req, legacy, rendered_envelope=result)
    legacy.assert_not_called()
    for boundary in boundaries:
        boundary.assert_not_called()
    assert req.event_log.events == []


def test_subscription_qualification_refuses_before_dispatch(tmp_path, boundaries):
    req = request(tmp_path, declaration(billing_surface="subscription"))
    result = render(declaration(), run_root=tmp_path / "run")
    result.facts["declaration_sha256"] = req.envelope_sha256
    legacy = Mock()
    with pytest.raises(ValueError, match="billing qualification"):
        CodexAdapter().launch(decision(), req, legacy, rendered_envelope=result)
    legacy.assert_not_called()
    for boundary in boundaries:
        boundary.assert_not_called()
    assert req.event_log.events == []
