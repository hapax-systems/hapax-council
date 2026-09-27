"""Register due-point sweeper (R7): public-loop-register-due-sweeper-20260925.

The four unsafe cases from the row's exit predicate come first. Each is pinned so that
the named mistake turns a test red:

1. a fetch failure read as "nothing due";
2. a timezone off-by-one at the due boundary;
3. a discharged entry reported as slipped;
4. a stale register.json (older than the site's release) treated as current.

No test touches the network: the fetcher is injected.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import sys
import urllib.error
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-register-due-sweep"
SERVICE = REPO_ROOT / "systemd" / "units" / "hapax-register-due-sweep.service"
TIMER = REPO_ROOT / "systemd" / "units" / "hapax-register-due-sweep.timer"
PRESET = REPO_ROOT / "systemd" / "user-preset.d" / "hapax.preset"

loader = importlib.machinery.SourceFileLoader("hapax_register_due_sweep", str(SCRIPT))
spec = importlib.util.spec_from_loader("hapax_register_due_sweep", loader)
assert spec and spec.loader
sweep = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = sweep
spec.loader.exec_module(sweep)

RELEASE_LM = "Sat, 26 Sep 2026 00:53:42 GMT"
OLDER_LM = "Fri, 25 Sep 2026 10:00:00 GMT"
SNAPSHOT = "fixture-snapshot-0001"


def _commitment(
    cid: str = "com-2026-0004", deadline: str = "2026-10-01T23:59:59Z", **extra
) -> dict:
    record = {
        "schema_version": "1.0",
        "id": cid,
        "type": "commitment",
        "title": "Identity of the lab's public properties",
        "status": "open",
        "statement": "Every public property states the lab's identity by 1 October 2026.",
        "resolution_criteria": "Kept when each listed property shows the lab's name and a link.",
        "committed_on": "2026-09-26",
        "deadline": deadline,
        "obliged": "E1 Identity",
        "fulfilment": {
            "check": "anonymous GET of each listed property",
            "pass_if": "each response names the lab and links hapaxresearch.com",
            "result_recorded_in": "an attestation whose obligation is this commitment",
        },
        "registered_at": None,
        "registration_receipt": None,
        "outcome": None,
        "resolved_at": None,
        "license": "CC-BY-4.0",
    }
    record.update(extra)
    return {"record": record, "body": "", "sha256": "0" * 64}


def _attestation(aid: str, obligation: str, kind: str, outcome: bool, checked_at: str) -> dict:
    record = {
        "schema_version": "1.0",
        "id": aid,
        "type": "attestation",
        "title": "attestation",
        "statement": "attestation",
        "obligation": obligation,
        "kind": kind,
        "outcome": outcome,
        "checked_at": checked_at,
        "license": "CC-BY-4.0",
    }
    if kind == "check":
        record["result"] = {
            "checked": "x",
            "passes": 1 if outcome else 0,
            "failures": 0 if outcome else 1,
            "evidence": "https://example.org/e",
        }
    if kind == "cancellation":
        record["reason"] = "withdrawn"
    return {"record": record, "body": "", "sha256": "0" * 64}


def _register(*records: dict, snapshot: str = SNAPSHOT) -> bytes:
    return json.dumps(
        {
            "schema_version": "1.0",
            "snapshot": snapshot,
            "registration_state": "draft-slate",
            "license_scope": "CC BY 4.0",
            "records": list(records),
        }
    ).encode()


class FakeResponse:
    def __init__(self, body: bytes, last_modified: str | None, status: int = 200) -> None:
        self.status = status
        self.headers = {"Last-Modified": last_modified} if last_modified else {}
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class FakeWeb:
    """Serves the register and the site's release page; records every request."""

    def __init__(
        self,
        register: bytes | Exception,
        *,
        register_lm: str | None = RELEASE_LM,
        release_lm: str | None = RELEASE_LM,
    ) -> None:
        self.register = register
        self.register_lm = register_lm
        self.release_lm = release_lm
        self.requests: list = []

    def __call__(self, request, data=None, *, timeout: float) -> FakeResponse:
        # urllib.request.urlopen(url, data=None, timeout=...): a second positional
        # argument is the request body. The live run on 2026-09-26 sent the timeout there.
        assert data is None, "the timeout must be passed by keyword, not as the request body"
        self.requests.append(request)
        url = request.full_url
        if "register.json" in url:
            if isinstance(self.register, Exception):
                raise self.register
            return FakeResponse(self.register, self.register_lm)
        return FakeResponse(b"<html>release</html>", self.release_lm)


def _run(tmp_path: Path, web: FakeWeb, now: str, *, write: bool = True) -> tuple[int, Path, Path]:
    requests_dir = tmp_path / "hapax-requests" / "active"
    requests_dir.mkdir(parents=True, exist_ok=True)
    state = tmp_path / "state.json"
    rc = sweep.main(
        [
            *(["--write"] if write else []),
            "--requests-dir",
            str(requests_dir),
            "--state-path",
            str(state),
            "--now",
            now,
        ],
        opener=web,
    )
    return rc, requests_dir, state


def _written(requests_dir: Path) -> dict[str, dict]:
    out = {}
    for path in sorted(requests_dir.glob("*.md")):
        _, frontmatter, _ = path.read_text(encoding="utf-8").split("---", 2)
        out[path.stem] = yaml.safe_load(frontmatter)
    return out


# ── unsafe case 1: a fetch failure is never "nothing due" ─────────────────────


@pytest.mark.parametrize(
    "failure",
    [
        urllib.error.URLError("network unreachable"),
        urllib.error.HTTPError("u", 503, "unavailable", {}, None),
        TimeoutError("timed out"),
    ],
    ids=["url-error", "http-503", "timeout"],
)
def test_a_fetch_failure_fails_the_sweep_instead_of_reporting_nothing_due(
    tmp_path: Path, failure: Exception
) -> None:
    rc, requests_dir, state = _run(tmp_path, FakeWeb(failure), "2026-10-02T00:30:00Z")
    assert rc == sweep.EXIT_SWEEP_FAILED
    assert _written(requests_dir) == {}
    recorded = json.loads(state.read_text())
    assert recorded["status"] == "failed"
    assert recorded["reason"].startswith("fetch_failed")
    assert "due_soon" not in recorded and "slipped" not in recorded


def test_an_unexpected_error_is_a_recorded_failure_not_a_crash(tmp_path: Path) -> None:
    class Broken(FakeWeb):
        def __call__(self, request, data=None, *, timeout: float) -> FakeResponse:
            raise RuntimeError("unexpected")

    rc, requests_dir, state = _run(tmp_path, Broken(b""), "2026-10-02T00:30:00Z")
    assert rc == sweep.EXIT_SWEEP_FAILED
    assert _written(requests_dir) == {}
    assert json.loads(state.read_text())["reason"].startswith("internal_error")


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"{not json",
        json.dumps({"schema_version": "9.9", "records": []}).encode(),
        json.dumps({"schema_version": "1.0"}).encode(),
    ],
    ids=["empty", "malformed", "unknown-schema", "no-records"],
)
def test_an_unreadable_register_fails_the_sweep(tmp_path: Path, body: bytes) -> None:
    rc, requests_dir, state = _run(tmp_path, FakeWeb(body), "2026-10-02T00:30:00Z")
    assert rc == sweep.EXIT_SWEEP_FAILED
    assert _written(requests_dir) == {}
    assert json.loads(state.read_text())["status"] == "failed"


# ── unsafe case 2: the due boundary is compared in UTC, to the second ──────────


@pytest.mark.parametrize(
    ("deadline", "now", "expected"),
    [
        ("2026-10-01T23:59:59Z", "2026-10-01T23:59:58Z", "due_soon"),
        ("2026-10-01T23:59:59Z", "2026-10-01T23:59:59Z", "slipped"),
        ("2026-10-01T23:59:59Z", "2026-10-02T00:30:00Z", "slipped"),
        # 2026-10-02T04:59:59Z in UTC: an offset dropped or read as UTC would slip it early.
        ("2026-10-01T23:59:59-05:00", "2026-10-02T02:00:00Z", "due_soon"),
        ("2026-10-01T23:59:59-05:00", "2026-10-02T05:00:00Z", "slipped"),
        # outside the 72 h window: nothing yet
        ("2026-10-01T23:59:59Z", "2026-09-28T23:59:58Z", None),
        ("2026-10-01T23:59:59Z", "2026-09-28T23:59:59Z", "due_soon"),
    ],
)
def test_the_due_boundary_is_exact_in_utc(deadline: str, now: str, expected: str | None) -> None:
    register = sweep.parse_register(_register(_commitment(deadline=deadline)))
    findings = sweep.classify(register, sweep.parse_instant(now))
    assert [f.kind for f in findings] == ([expected] if expected else [])


def test_a_deadline_without_an_offset_fails_the_sweep(tmp_path: Path) -> None:
    web = FakeWeb(_register(_commitment(deadline="2026-10-01T23:59:59")))
    rc, requests_dir, state = _run(tmp_path, web, "2026-10-02T00:30:00Z")
    assert rc == sweep.EXIT_SWEEP_FAILED
    assert _written(requests_dir) == {}
    assert json.loads(state.read_text())["reason"].startswith("register_invalid")


# ── unsafe case 3: a discharged entry is never reported as slipped ────────────


def test_a_kept_commitment_is_not_slipped() -> None:
    register = sweep.parse_register(
        _register(
            _commitment(),
            _attestation("att-1", "com-2026-0004", "check", True, "2026-10-01T12:00:00Z"),
        )
    )
    assert sweep.classify(register, sweep.parse_instant("2026-10-02T00:30:00Z")) == []


def test_a_cancelled_commitment_is_not_slipped() -> None:
    register = sweep.parse_register(
        _register(
            _commitment(),
            _attestation("att-1", "com-2026-0004", "cancellation", False, "2026-09-30T12:00:00Z"),
        )
    )
    assert sweep.classify(register, sweep.parse_instant("2026-10-02T00:30:00Z")) == []


def test_an_attestation_for_another_commitment_does_not_discharge() -> None:
    register = sweep.parse_register(
        _register(
            _commitment(),
            _attestation("att-1", "com-2026-9999", "check", True, "2026-10-01T12:00:00Z"),
        )
    )
    findings = sweep.classify(register, sweep.parse_instant("2026-10-02T00:30:00Z"))
    assert [f.kind for f in findings] == ["slipped"]


def test_the_latest_attestation_decides_as_the_site_does() -> None:
    # hrl-portal#8: a commitment's state is its latest attestation. A later failed check
    # after a pass leaves it "open (last check failed)", so it is undischarged.
    register = sweep.parse_register(
        _register(
            _commitment(),
            _attestation("att-1", "com-2026-0004", "check", True, "2026-09-30T12:00:00Z"),
            _attestation("att-2", "com-2026-0004", "check", False, "2026-10-01T12:00:00Z"),
        )
    )
    findings = sweep.classify(register, sweep.parse_instant("2026-10-02T00:30:00Z"))
    assert [f.kind for f in findings] == ["slipped"]
    assert findings[0].latest_attestation == "att-2"


def test_a_standing_commitment_moves_its_due_point_with_each_passing_check() -> None:
    standing = _commitment(
        cid="com-2026-0010", deadline="2026-10-07T23:59:59Z", standing=True, review_every="P3M"
    )
    passed = _attestation("att-1", "com-2026-0010", "check", True, "2026-10-07T12:00:00Z")
    register = sweep.parse_register(_register(standing, passed))
    # next due: 2027-01-07T12:00:00Z; not slipped in December, due soon in January
    assert sweep.classify(register, sweep.parse_instant("2026-12-20T00:00:00Z")) == []
    soon = sweep.classify(register, sweep.parse_instant("2027-01-05T12:00:00Z"))
    assert [f.kind for f in soon] == ["due_soon"]
    assert soon[0].due == datetime(2027, 1, 7, 12, 0, tzinfo=UTC)
    late = sweep.classify(register, sweep.parse_instant("2027-01-08T00:00:00Z"))
    assert [f.kind for f in late] == ["slipped"]


# ── unsafe case 4: a register older than the site's release is not current ─────


def test_a_register_older_than_the_site_release_fails_the_sweep(tmp_path: Path) -> None:
    web = FakeWeb(_register(_commitment()), register_lm=OLDER_LM, release_lm=RELEASE_LM)
    rc, requests_dir, state = _run(tmp_path, web, "2026-10-02T00:30:00Z")
    assert rc == sweep.EXIT_SWEEP_FAILED
    assert _written(requests_dir) == {}
    assert json.loads(state.read_text())["reason"].startswith("register_stale")


@pytest.mark.parametrize(("register_lm", "release_lm"), [(None, RELEASE_LM), (RELEASE_LM, None)])
def test_a_register_whose_currency_cannot_be_established_fails_the_sweep(
    tmp_path: Path, register_lm: str | None, release_lm: str | None
) -> None:
    web = FakeWeb(_register(_commitment()), register_lm=register_lm, release_lm=release_lm)
    rc, requests_dir, _ = _run(tmp_path, web, "2026-10-02T00:30:00Z")
    assert rc == sweep.EXIT_SWEEP_FAILED
    assert _written(requests_dir) == {}


def test_both_reads_bypass_the_cache_and_are_anonymous(tmp_path: Path) -> None:
    web = FakeWeb(_register(_commitment()))
    _run(tmp_path, web, "2026-09-20T00:00:00Z")
    assert len(web.requests) == 2
    for request in web.requests:
        headers = {k.lower(): v for k, v in request.header_items()}
        assert headers["user-agent"] == sweep.USER_AGENT
        assert "authorization" not in headers and "cookie" not in headers
        assert "_sweep=" in request.full_url  # a fresh edge copy, not a cached one


# ── the demands ──────────────────────────────────────────────────────────────


def test_due_soon_writes_one_owner_demand_into_the_request_intake(tmp_path: Path) -> None:
    rc, requests_dir, state = _run(
        tmp_path, FakeWeb(_register(_commitment())), "2026-09-30T12:00:00Z"
    )
    assert rc == 0
    notes = _written(requests_dir)
    assert list(notes) == ["REQ-REGISTER-DUE-com-2026-0004-20261001T235959Z"]
    note = notes["REQ-REGISTER-DUE-com-2026-0004-20261001T235959Z"]
    assert note["type"] == "hapax-request"
    assert note["status"] == "captured"
    assert note["requester"] == "register-due-sweep"
    assert note["obliged"] == "E1 Identity"
    assert note["commitment_id"] == "com-2026-0004"
    assert note["due"] == "2026-10-01T23:59:59Z"
    assert note["register_snapshot"] == SNAPSHOT
    assert json.loads(state.read_text())["status"] == "ok"


def test_slipped_writes_a_candidate_for_e3_carrying_its_evidence_of_absence(tmp_path: Path) -> None:
    rc, requests_dir, _ = _run(tmp_path, FakeWeb(_register(_commitment())), "2026-10-02T00:30:00Z")
    assert rc == 0
    notes = _written(requests_dir)
    # The owner demand is written too (codex-1's finding on 268c45e24).
    assert sorted(notes) == [
        "REQ-REGISTER-DUE-com-2026-0004-20261001T235959Z",
        "REQ-REGISTER-SLIPPED-com-2026-0004-20261001T235959Z",
    ]
    note = notes["REQ-REGISTER-SLIPPED-com-2026-0004-20261001T235959Z"]
    assert note["candidate_kind"] == "slipped"
    assert note["intake_owner"] == "E3 Ledger"
    assert note["latest_attestation"] is None
    body = (requests_dir / "REQ-REGISTER-SLIPPED-com-2026-0004-20261001T235959Z.md").read_text()
    # It asserts only absence of discharge in a named snapshot; it runs no check of its own.
    assert "no discharging attestation" in body
    assert SNAPSHOT in body


def test_rerunning_writes_nothing_new_and_never_overwrites(tmp_path: Path) -> None:
    web = FakeWeb(_register(_commitment()))
    _run(tmp_path, web, "2026-10-02T00:30:00Z")
    requests_dir = tmp_path / "hapax-requests" / "active"
    path = requests_dir / "REQ-REGISTER-SLIPPED-com-2026-0004-20261001T235959Z.md"
    path.write_text(path.read_text() + "\nedited by E3\n", encoding="utf-8")
    rc, _, state = _run(tmp_path, web, "2026-10-03T00:30:00Z")
    assert rc == 0
    assert path.read_text().endswith("edited by E3\n")
    assert json.loads(state.read_text())["skipped_existing"] == [
        "REQ-REGISTER-DUE-com-2026-0004-20261001T235959Z",
        path.stem,
    ]


def test_a_demand_already_moved_to_closed_is_not_rewritten(tmp_path: Path) -> None:
    web = FakeWeb(_register(_commitment()))
    _run(tmp_path, web, "2026-10-02T00:30:00Z")
    active = tmp_path / "hapax-requests" / "active"
    closed = tmp_path / "hapax-requests" / "closed"
    closed.mkdir()
    (active / "REQ-REGISTER-SLIPPED-com-2026-0004-20261001T235959Z.md").rename(
        closed / "REQ-REGISTER-SLIPPED-com-2026-0004-20261001T235959Z.md"
    )
    _run(tmp_path, web, "2026-10-03T00:30:00Z")
    assert "REQ-REGISTER-SLIPPED-com-2026-0004-20261001T235959Z" not in _written(active)


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    rc, requests_dir, state = _run(
        tmp_path, FakeWeb(_register(_commitment())), "2026-10-02T00:30:00Z", write=False
    )
    assert rc == 0
    assert _written(requests_dir) == {}
    assert not state.exists()


def test_todays_register_with_no_commitments_is_a_clean_sweep(tmp_path: Path) -> None:
    claim = {
        "record": {"schema_version": "1.0", "id": "clm-2026-0001", "type": "claim"},
        "body": "",
        "sha256": "0",
    }
    rc, requests_dir, state = _run(tmp_path, FakeWeb(_register(claim)), "2026-10-02T00:30:00Z")
    assert rc == 0
    assert _written(requests_dir) == {}
    recorded = json.loads(state.read_text())
    assert recorded["status"] == "ok" and recorded["commitments"] == 0


# ── review findings on 268c45e24 (codex-1, claude-1), red first ──────────────


@pytest.mark.parametrize(
    "bad_id",
    [
        "../../etc/x",  # traversal
        "x/../../../../outside",  # traversal after a harmless prefix
        "com/2026",  # a slash
        "/etc/passwd",  # an absolute path
        "com\x002026",  # a NUL
        "..",
        "",
        "com 2026",
        "-leading-dash",
    ],
    ids=[
        "dotdot",
        "prefix-dotdot",
        "slash",
        "absolute",
        "nul",
        "bare-dotdot",
        "empty",
        "space",
        "dash",
    ],
)
def test_an_unsafe_commitment_id_is_refused_by_name_and_writes_nothing(
    tmp_path: Path, bad_id: str
) -> None:
    # The intake sits four levels inside tmp_path, so any escape the ids above could make
    # (at most four levels up) still lands inside tmp_path, where it is seen.
    requests_dir = tmp_path / "d1" / "d2" / "hapax-requests" / "active"
    requests_dir.mkdir(parents=True)
    state = tmp_path / "state.json"
    rc = sweep.main(
        [
            "--write",
            "--requests-dir",
            str(requests_dir),
            "--state-path",
            str(state),
            "--now",
            "2026-10-02T00:30:00Z",
        ],
        opener=FakeWeb(_register(_commitment(cid=bad_id))),
    )
    assert rc == sweep.EXIT_SWEEP_FAILED
    assert [p for p in tmp_path.rglob("*") if p.is_file() and p != state] == []
    reason = json.loads(state.read_text())["reason"]
    assert reason.startswith("register_invalid:unsafe_commitment_id")
    # The refusal states the grammar the code enforces, length bound included.
    assert "[A-Za-z0-9][A-Za-z0-9._-]{0,127}" in reason
    assert "at most 128 characters" in reason


def test_a_commitment_first_seen_overdue_also_gets_its_owner_demand(tmp_path: Path) -> None:
    rc, requests_dir, _ = _run(tmp_path, FakeWeb(_register(_commitment())), "2026-10-02T00:30:00Z")
    assert rc == 0
    notes = _written(requests_dir)
    assert sorted(notes) == [
        "REQ-REGISTER-DUE-com-2026-0004-20261001T235959Z",
        "REQ-REGISTER-SLIPPED-com-2026-0004-20261001T235959Z",
    ]
    owner = notes["REQ-REGISTER-DUE-com-2026-0004-20261001T235959Z"]
    assert owner["intake_owner"] == "E1 Identity"
    assert "was due" in owner["title"]


def test_an_owner_demand_written_before_the_due_point_is_not_duplicated(tmp_path: Path) -> None:
    web = FakeWeb(_register(_commitment()))
    _run(tmp_path, web, "2026-09-30T12:00:00Z")
    rc, requests_dir, state = _run(tmp_path, web, "2026-10-02T00:30:00Z")
    assert rc == 0
    assert sorted(_written(requests_dir)) == [
        "REQ-REGISTER-DUE-com-2026-0004-20261001T235959Z",
        "REQ-REGISTER-SLIPPED-com-2026-0004-20261001T235959Z",
    ]
    recorded = json.loads(state.read_text())
    assert recorded["created"] == ["REQ-REGISTER-SLIPPED-com-2026-0004-20261001T235959Z"]
    assert recorded["skipped_existing"] == ["REQ-REGISTER-DUE-com-2026-0004-20261001T235959Z"]


def test_a_missing_intake_directory_fails_instead_of_being_created(tmp_path: Path) -> None:
    missing = tmp_path / "no-such-vault" / "hapax-requests" / "active"
    state = tmp_path / "state.json"
    rc = sweep.main(
        [
            "--write",
            "--requests-dir",
            str(missing),
            "--state-path",
            str(state),
            "--now",
            "2026-10-02T00:30:00Z",
        ],
        opener=FakeWeb(_register(_commitment())),
    )
    assert rc == sweep.EXIT_SWEEP_FAILED
    assert not missing.exists()
    assert json.loads(state.read_text())["reason"].startswith("intake_missing")


def test_a_write_failure_is_a_recorded_failure(tmp_path: Path, monkeypatch) -> None:
    def refuse(*_args, **_kwargs):
        raise PermissionError("read-only intake")

    monkeypatch.setattr(sweep, "write_requests", refuse)
    rc, requests_dir, state = _run(
        tmp_path, FakeWeb(_register(_commitment())), "2026-10-02T00:30:00Z"
    )
    assert rc == sweep.EXIT_SWEEP_FAILED
    recorded = json.loads(state.read_text())
    assert recorded["status"] == "failed"
    assert recorded["reason"].startswith("write_failed")


def test_the_default_intake_is_the_vault_request_intake() -> None:
    # The same intake security-signal-intake writes to; the vault root is ~/Documents/Personal.
    assert (
        Path.home() / "Documents/Personal/20-projects/hapax-requests/active"
        == sweep.DEFAULT_REQUESTS_DIR
    )


def test_a_standing_commitment_with_no_passing_check_is_due_at_its_deadline() -> None:
    standing = _commitment(
        cid="com-2026-0010", deadline="2026-10-07T23:59:59Z", standing=True, review_every="P3M"
    )
    register = sweep.parse_register(_register(standing))
    soon = sweep.classify(register, sweep.parse_instant("2026-10-06T00:00:00Z"))
    assert [f.kind for f in soon] == ["due_soon"]
    assert soon[0].due == datetime(2026, 10, 7, 23, 59, 59, tzinfo=UTC)


def test_an_invalid_review_interval_fails_the_sweep(tmp_path: Path) -> None:
    standing = _commitment(
        cid="com-2026-0010", deadline="2026-10-07T23:59:59Z", standing=True, review_every="3 months"
    )
    passed = _attestation("att-1", "com-2026-0010", "check", True, "2026-10-07T12:00:00Z")
    rc, requests_dir, state = _run(
        tmp_path, FakeWeb(_register(standing, passed)), "2026-12-20T00:00:00Z"
    )
    assert rc == sweep.EXIT_SWEEP_FAILED
    assert _written(requests_dir) == {}
    assert "review_every" in json.loads(state.read_text())["reason"]


def test_the_installer_enables_new_timers_which_is_why_the_flag_gates_the_service() -> None:
    # The activation contract in one place: install-units.sh enables newly linked timers
    # (--now) and sweeps linked-but-disabled ones, so only the flag keeps activation a
    # separate act. If the installer stops enabling timers, this test says so.
    installer = (REPO_ROOT / "systemd" / "scripts" / "install-units.sh").read_text(encoding="utf-8")
    assert 'systemctl --user enable --now "$timer"' in installer
    assert 'systemctl --user enable "$timer_name"' in installer
    assert "ConditionPathExists=%h/.config/hapax/register-due-sweep.enabled" in SERVICE.read_text(
        encoding="utf-8"
    )


# ── review findings on 7128558dc (codex-1, claude-1), red first ──────────────


def test_a_note_is_created_exclusively_and_never_replaced(tmp_path: Path) -> None:
    # Two runs racing on one name: the first creates it, the second must not replace it,
    # and no temporary file is left behind.
    path = tmp_path / "REQ-REGISTER-DUE-com-2026-0004-20261001T235959Z.md"
    assert sweep.create_note(path, "first\n") is True
    path.write_text("edited by E3\n", encoding="utf-8")
    assert sweep.create_note(path, "second\n") is False
    assert path.read_text(encoding="utf-8") == "edited by E3\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == [path.name]


def test_a_write_failure_midway_leaves_only_complete_notes_and_the_rerun_finishes(
    tmp_path: Path, monkeypatch
) -> None:
    real_create = sweep.create_note
    calls = {"n": 0}

    def fail_second(path, content, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk full")
        return real_create(path, content, **kwargs)

    web = FakeWeb(_register(_commitment()))
    monkeypatch.setattr(sweep, "create_note", fail_second)
    rc, requests_dir, state = _run(tmp_path, web, "2026-10-02T00:30:00Z")
    assert rc == sweep.EXIT_SWEEP_FAILED
    assert json.loads(state.read_text())["reason"].startswith("write_failed")
    # The note written before the failure is whole, and nothing partial is left.
    assert sorted(_written(requests_dir)) == ["REQ-REGISTER-DUE-com-2026-0004-20261001T235959Z"]
    assert [p.name for p in requests_dir.iterdir() if p.suffix != ".md"] == []
    monkeypatch.setattr(sweep, "create_note", real_create)
    rc, _, state = _run(tmp_path, web, "2026-10-02T00:30:00Z")
    assert rc == 0
    recorded = json.loads(state.read_text())
    assert recorded["created"] == ["REQ-REGISTER-SLIPPED-com-2026-0004-20261001T235959Z"]
    assert recorded["skipped_existing"] == ["REQ-REGISTER-DUE-com-2026-0004-20261001T235959Z"]


def test_a_non_200_response_fails_the_sweep(tmp_path: Path) -> None:
    class ServerError(FakeWeb):
        def __call__(self, request, data=None, *, timeout: float) -> FakeResponse:
            return FakeResponse(b"{}", RELEASE_LM, status=500)

    rc, requests_dir, state = _run(tmp_path, ServerError(b""), "2026-10-02T00:30:00Z")
    assert rc == sweep.EXIT_SWEEP_FAILED
    assert _written(requests_dir) == {}
    assert json.loads(state.read_text())["reason"].endswith("http_500")


# ── the unit ─────────────────────────────────────────────────────────────────


def test_the_service_is_a_oneshot_gated_on_an_activation_flag() -> None:
    body = SERVICE.read_text(encoding="utf-8")
    assert "Type=oneshot" in body
    assert "OnFailure=notify-failure@%n.service" in body
    assert "ConditionPathExists=%h/.config/hapax/register-due-sweep.enabled" in body
    assert "scripts/hapax-register-due-sweep --write" in body


def test_the_timer_is_daily_and_persistent() -> None:
    body = TIMER.read_text(encoding="utf-8")
    assert "OnCalendar=*-*-* 06:10:00 UTC" in body
    assert "Persistent=true" in body
    assert "WantedBy=timers.target" in body


def test_activation_is_not_folded_into_the_preset() -> None:
    assert "hapax-register-due-sweep" not in PRESET.read_text(encoding="utf-8")


def test_the_window_is_seventy_two_hours() -> None:
    assert timedelta(hours=72) == sweep.DEMAND_WINDOW


# ── follow-ups from the #4798 reviews ────────────────────────────────────────
# public-loop-register-due-sweeper-followups-20260926


def _standing(review_every: str) -> dict:
    return _commitment(
        cid="com-2026-0011",
        deadline="2026-10-05T00:00:00Z",
        standing=True,
        review_every=review_every,
    )


def test_the_request_identity_is_the_due_instant_in_utc() -> None:
    register = sweep.parse_register(_register(_commitment(deadline="2026-10-02T01:30:00+02:00")))
    [finding] = sweep.classify(register, sweep.parse_instant("2026-09-30T12:00:00Z"))
    assert sweep.request_id_for(finding) == "REQ-REGISTER-DUE-com-2026-0004-20261001T233000Z"
    assert (
        sweep.request_id_for(finding, sweep.SLIPPED_CANDIDATE)
        == "REQ-REGISTER-SLIPPED-com-2026-0004-20261001T233000Z"
    )


@pytest.mark.parametrize(
    ("review_every", "checks", "runs", "expected"),
    [
        # A sub-day interval: passes at 00:00 and 06:00 put due points at 06:00 and 12:00.
        (
            "PT6H",
            ["2026-10-01T00:00:00Z", "2026-10-01T06:00:00Z"],
            ["2026-10-01T01:00:00Z", "2026-10-01T07:00:00Z"],
            ["20261001T060000Z", "20261001T120000Z"],
        ),
        # A daily interval with two passing checks on one day: due points at 01:00 and 20:00.
        (
            "P1D",
            ["2026-09-30T01:00:00Z", "2026-09-30T20:00:00Z"],
            ["2026-09-30T02:00:00Z", "2026-09-30T21:00:00Z"],
            ["20261001T010000Z", "20261001T200000Z"],
        ),
    ],
    ids=["sub-day-interval", "two-passes-in-one-day"],
)
def test_each_same_day_due_point_of_a_standing_commitment_gets_its_own_demand(
    tmp_path: Path, review_every: str, checks: list[str], runs: list[str], expected: list[str]
) -> None:
    records = [_standing(review_every)]
    for n, (checked_at, now) in enumerate(zip(checks, runs, strict=True), start=1):
        records.append(_attestation(f"att-{n}", "com-2026-0011", "check", True, checked_at))
        rc, requests_dir, state = _run(tmp_path, FakeWeb(_register(*records)), now)
        assert rc == 0
        assert json.loads(state.read_text())["created"] == [
            f"REQ-REGISTER-DUE-com-2026-0011-{expected[n - 1]}"
        ]
    assert sorted(_written(requests_dir)) == [
        f"REQ-REGISTER-DUE-com-2026-0011-{stamp}" for stamp in expected
    ]


def test_a_second_slip_on_the_same_day_gets_its_own_candidate(tmp_path: Path) -> None:
    standing = _standing("PT6H")
    first = _attestation("att-1", "com-2026-0011", "check", True, "2026-10-01T00:00:00Z")
    late = _attestation("att-2", "com-2026-0011", "check", True, "2026-10-01T08:00:00Z")
    # 06:00 slips; a late pass at 08:00 moves the due point to 14:00, and that slips too.
    _run(tmp_path, FakeWeb(_register(standing, first)), "2026-10-01T07:00:00Z")
    rc, requests_dir, state = _run(
        tmp_path, FakeWeb(_register(standing, first, late)), "2026-10-01T15:00:00Z"
    )
    assert rc == 0
    assert json.loads(state.read_text())["created"] == [
        "REQ-REGISTER-DUE-com-2026-0011-20261001T140000Z",
        "REQ-REGISTER-SLIPPED-com-2026-0011-20261001T140000Z",
    ]
    assert sorted(_written(requests_dir)) == [
        "REQ-REGISTER-DUE-com-2026-0011-20261001T060000Z",
        "REQ-REGISTER-DUE-com-2026-0011-20261001T140000Z",
        "REQ-REGISTER-SLIPPED-com-2026-0011-20261001T060000Z",
        "REQ-REGISTER-SLIPPED-com-2026-0011-20261001T140000Z",
    ]


def _date_only_note(directory: Path, name: str, due_literal: str | None) -> Path:
    # The shape #4798 wrote before the full-instant identity; E3 may have re-quoted it.
    # None writes a note with no due line at all.
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.md"
    due_line = "" if due_literal is None else f"due: {due_literal}\n"
    path.write_text(
        f'---\ntype: "hapax-request"\nrequest_id: "{name}"\n{due_line}---\n\n# before\n',
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize("where", ["active", "closed"])
@pytest.mark.parametrize(
    "due_literal",
    ['"2026-10-01T23:59:59Z"', "'2026-10-01T23:59:59Z'", "2026-10-01T23:59:59+00:00"],
    ids=["as-written", "single-quoted", "offset-form"],
)
def test_a_date_only_note_for_the_same_due_instant_is_the_same_note(
    tmp_path: Path, where: str, due_literal: str
) -> None:
    # Podium ran the date-only identity from 2026-09-26T23:47Z; its 09-29 run may write this.
    legacy = _date_only_note(
        tmp_path / "hapax-requests" / where,
        "REQ-REGISTER-DUE-com-2026-0004-20261001",
        due_literal,
    )
    rc, requests_dir, state = _run(
        tmp_path, FakeWeb(_register(_commitment())), "2026-09-30T06:10:00Z"
    )
    assert rc == 0
    recorded = json.loads(state.read_text())
    assert recorded["created"] == []
    assert recorded["skipped_existing"] == [legacy.stem]
    assert sorted(p.name for p in requests_dir.iterdir()) == (
        [legacy.name] if where == "active" else []
    )


def test_a_date_only_note_for_another_due_point_that_day_does_not_suppress(
    tmp_path: Path,
) -> None:
    _date_only_note(
        tmp_path / "hapax-requests" / "active",
        "REQ-REGISTER-DUE-com-2026-0004-20261001",
        '"2026-10-01T06:00:00Z"',
    )
    rc, _, state = _run(tmp_path, FakeWeb(_register(_commitment())), "2026-09-30T06:10:00Z")
    assert rc == 0
    assert json.loads(state.read_text())["created"] == [
        "REQ-REGISTER-DUE-com-2026-0004-20261001T235959Z"
    ]


def test_a_failed_content_write_leaves_no_temporary_file(tmp_path: Path) -> None:
    # A lone surrogate escape in a register title cannot be encoded, so the write fails
    # inside handle.write, after the temporary file exists.
    bad = _commitment(title="Identity \ud800 check")
    rc, requests_dir, state = _run(tmp_path, FakeWeb(_register(bad)), "2026-09-30T12:00:00Z")
    assert rc == sweep.EXIT_SWEEP_FAILED
    assert json.loads(state.read_text())["reason"].startswith("write_failed:UnicodeEncodeError")
    assert list(requests_dir.iterdir()) == []


@pytest.mark.parametrize(
    "due_literal",
    ['"not a date"', '"2026-10-01T23:59:59"', None],
    ids=["garbled", "naive", "absent"],
)
def test_a_date_only_note_whose_due_cannot_be_read_is_not_the_same_note(
    tmp_path: Path, due_literal: str | None
) -> None:
    # A second demand is the safe error; a lost one is not.
    _date_only_note(
        tmp_path / "hapax-requests" / "active",
        "REQ-REGISTER-DUE-com-2026-0004-20261001",
        due_literal,
    )
    rc, _, state = _run(tmp_path, FakeWeb(_register(_commitment())), "2026-09-30T06:10:00Z")
    assert rc == 0
    assert json.loads(state.read_text())["created"] == [
        "REQ-REGISTER-DUE-com-2026-0004-20261001T235959Z"
    ]


def test_the_switch_over_matches_what_podium_wrote_for_an_offset_deadline(
    tmp_path: Path,
) -> None:
    # A +02:00 deadline whose local date (10-02) is the day after its UTC date (10-01).
    offset = _commitment(deadline="2026-10-02T01:30:00+02:00")
    now = "2026-09-30T06:10:00Z"
    [finding] = sweep.classify(sweep.parse_register(_register(offset)), sweep.parse_instant(now))
    # The identity #4798 shipped, verbatim: finding.due.strftime('%Y%m%d'). Due points are UTC
    # before they reach any identity, so podium named this note by its UTC date.
    shipped = f"REQ-REGISTER-DUE-{finding.commitment_id}-{finding.due.strftime('%Y%m%d')}"
    assert shipped == "REQ-REGISTER-DUE-com-2026-0004-20261001"
    assert shipped == sweep.date_only_request_id_for(finding)
    legacy = _date_only_note(
        tmp_path / "hapax-requests" / "active", shipped, '"2026-10-01T23:30:00Z"'
    )
    rc, _, state = _run(tmp_path, FakeWeb(_register(offset)), now)
    assert rc == 0
    recorded = json.loads(state.read_text())
    assert recorded["created"] == []
    assert recorded["skipped_existing"] == [legacy.stem]
    # A standing due point stays UTC through review_every, from a check stamped +05:00.
    standing = _standing("P1D")
    check = _attestation("att-1", "com-2026-0011", "check", True, "2026-09-30T23:00:00+05:00")
    [moved] = sweep.classify(
        sweep.parse_register(_register(standing, check)),
        sweep.parse_instant("2026-09-30T19:00:00Z"),
    )
    assert moved.due == datetime(2026, 10, 1, 18, 0, tzinfo=UTC)
    assert moved.due.utcoffset() == timedelta(0)


SLIPPED_NOTE = "REQ-REGISTER-SLIPPED-com-2026-0004-20261001T235959Z.md"


def _close_during_link(active: Path, closed: Path, *, reopen: bool = False):
    real_link = os.link

    def link(src, dst, *args, **kwargs):
        # E3 closes the note after the run's closed check and before its link.
        if Path(dst).name == SLIPPED_NOTE and (active / SLIPPED_NOTE).exists():
            (active / SLIPPED_NOTE).rename(closed / SLIPPED_NOTE)
            result = real_link(src, dst, *args, **kwargs)
            if reopen:
                # ...and something else takes the name over before the run looks again.
                (active / SLIPPED_NOTE).unlink()
                (active / SLIPPED_NOTE).write_text("reopened by E3\n", encoding="utf-8")
            return result
        return real_link(src, dst, *args, **kwargs)

    return link


def test_a_note_closed_while_the_run_creates_it_is_not_reopened(
    tmp_path: Path, monkeypatch
) -> None:
    web = FakeWeb(_register(_commitment()))
    _run(tmp_path, web, "2026-10-02T00:30:00Z")
    active = tmp_path / "hapax-requests" / "active"
    closed = tmp_path / "hapax-requests" / "closed"
    closed.mkdir()
    monkeypatch.setattr(os, "link", _close_during_link(active, closed))
    rc, _, state = _run(tmp_path, web, "2026-10-03T00:30:00Z")
    assert rc == 0
    assert not (active / SLIPPED_NOTE).exists()
    assert (closed / SLIPPED_NOTE).exists()
    recorded = json.loads(state.read_text())
    assert recorded["created"] == []
    assert Path(SLIPPED_NOTE).stem in recorded["skipped_existing"]
    assert sorted(p.name for p in active.iterdir()) == [
        "REQ-REGISTER-DUE-com-2026-0004-20261001T235959Z.md"
    ]


def test_a_note_already_closed_is_never_relinked_even_briefly(tmp_path: Path, monkeypatch) -> None:
    # The intake is watched: a closed demand must not reappear in active/ even for the instant
    # between a link and the re-check. Only a close that races the run can cost that instant.
    web = FakeWeb(_register(_commitment()))
    _run(tmp_path, web, "2026-10-02T00:30:00Z")
    active = tmp_path / "hapax-requests" / "active"
    closed = tmp_path / "hapax-requests" / "closed"
    closed.mkdir()
    (active / SLIPPED_NOTE).rename(closed / SLIPPED_NOTE)
    real_link = os.link
    linked: list[str] = []

    def recording_link(src, dst, *args, **kwargs):
        linked.append(Path(dst).name)
        return real_link(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "link", recording_link)
    rc, _, _ = _run(tmp_path, web, "2026-10-03T00:30:00Z")
    assert rc == 0
    assert SLIPPED_NOTE not in linked


def test_the_race_check_removes_only_the_runs_own_note(tmp_path: Path, monkeypatch) -> None:
    web = FakeWeb(_register(_commitment()))
    _run(tmp_path, web, "2026-10-02T00:30:00Z")
    active = tmp_path / "hapax-requests" / "active"
    closed = tmp_path / "hapax-requests" / "closed"
    closed.mkdir()
    monkeypatch.setattr(os, "link", _close_during_link(active, closed, reopen=True))
    rc, _, state = _run(tmp_path, web, "2026-10-03T00:30:00Z")
    assert rc == 0
    assert (active / SLIPPED_NOTE).read_text(encoding="utf-8") == "reopened by E3\n"
    assert json.loads(state.read_text())["created"] == []


def test_a_note_the_closer_moves_before_the_recheck_is_treated_as_closed(
    tmp_path: Path, monkeypatch
) -> None:
    # gemini, #4799: the closer takes the run's own new note into closed/ between the link
    # and the re-check, so there is no path left to compare or remove.
    active = tmp_path / "hapax-requests" / "active"
    closed = tmp_path / "hapax-requests" / "closed"
    closed.mkdir(parents=True)
    real_link = os.link

    def link_then_close(src, dst, *args, **kwargs):
        result = real_link(src, dst, *args, **kwargs)
        if Path(dst).name == SLIPPED_NOTE:
            Path(dst).rename(closed / SLIPPED_NOTE)
        return result

    monkeypatch.setattr(os, "link", link_then_close)
    rc, _, state = _run(tmp_path, FakeWeb(_register(_commitment())), "2026-10-02T00:30:00Z")
    assert rc == 0
    assert not (active / SLIPPED_NOTE).exists()
    assert (closed / SLIPPED_NOTE).exists()
    recorded = json.loads(state.read_text())
    assert recorded["created"] == ["REQ-REGISTER-DUE-com-2026-0004-20261001T235959Z"]
    assert recorded["skipped_existing"] == [Path(SLIPPED_NOTE).stem]


def test_a_note_gone_between_the_comparison_and_the_removal_is_not_an_error(
    tmp_path: Path, monkeypatch
) -> None:
    web = FakeWeb(_register(_commitment()))
    _run(tmp_path, web, "2026-10-02T00:30:00Z")
    active = tmp_path / "hapax-requests" / "active"
    closed = tmp_path / "hapax-requests" / "closed"
    closed.mkdir()
    monkeypatch.setattr(os, "link", _close_during_link(active, closed))
    real_samefile = os.path.samefile

    def samefile_then_gone(a, b):
        result = real_samefile(a, b)
        if Path(b).name == SLIPPED_NOTE:
            Path(b).unlink()  # the closer disposes of the re-created note first
        return result

    monkeypatch.setattr(os.path, "samefile", samefile_then_gone)
    rc, _, state = _run(tmp_path, web, "2026-10-03T00:30:00Z")
    assert rc == 0
    assert not (active / SLIPPED_NOTE).exists()
    assert json.loads(state.read_text())["created"] == []
