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
    assert list(notes) == ["REQ-REGISTER-DUE-com-2026-0004-20261001"]
    note = notes["REQ-REGISTER-DUE-com-2026-0004-20261001"]
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
        "REQ-REGISTER-DUE-com-2026-0004-20261001",
        "REQ-REGISTER-SLIPPED-com-2026-0004-20261001",
    ]
    note = notes["REQ-REGISTER-SLIPPED-com-2026-0004-20261001"]
    assert note["candidate_kind"] == "slipped"
    assert note["intake_owner"] == "E3 Ledger"
    assert note["latest_attestation"] is None
    body = (requests_dir / "REQ-REGISTER-SLIPPED-com-2026-0004-20261001.md").read_text()
    # It asserts only absence of discharge in a named snapshot; it runs no check of its own.
    assert "no discharging attestation" in body
    assert SNAPSHOT in body


def test_rerunning_writes_nothing_new_and_never_overwrites(tmp_path: Path) -> None:
    web = FakeWeb(_register(_commitment()))
    _run(tmp_path, web, "2026-10-02T00:30:00Z")
    requests_dir = tmp_path / "hapax-requests" / "active"
    path = requests_dir / "REQ-REGISTER-SLIPPED-com-2026-0004-20261001.md"
    path.write_text(path.read_text() + "\nedited by E3\n", encoding="utf-8")
    rc, _, state = _run(tmp_path, web, "2026-10-03T00:30:00Z")
    assert rc == 0
    assert path.read_text().endswith("edited by E3\n")
    assert json.loads(state.read_text())["skipped_existing"] == [
        "REQ-REGISTER-DUE-com-2026-0004-20261001",
        path.stem,
    ]


def test_a_demand_already_moved_to_closed_is_not_rewritten(tmp_path: Path) -> None:
    web = FakeWeb(_register(_commitment()))
    _run(tmp_path, web, "2026-10-02T00:30:00Z")
    active = tmp_path / "hapax-requests" / "active"
    closed = tmp_path / "hapax-requests" / "closed"
    closed.mkdir()
    (active / "REQ-REGISTER-SLIPPED-com-2026-0004-20261001.md").rename(
        closed / "REQ-REGISTER-SLIPPED-com-2026-0004-20261001.md"
    )
    _run(tmp_path, web, "2026-10-03T00:30:00Z")
    assert "REQ-REGISTER-SLIPPED-com-2026-0004-20261001" not in _written(active)


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


def test_a_commitment_first_seen_overdue_also_gets_its_owner_demand(tmp_path: Path) -> None:
    rc, requests_dir, _ = _run(tmp_path, FakeWeb(_register(_commitment())), "2026-10-02T00:30:00Z")
    assert rc == 0
    notes = _written(requests_dir)
    assert sorted(notes) == [
        "REQ-REGISTER-DUE-com-2026-0004-20261001",
        "REQ-REGISTER-SLIPPED-com-2026-0004-20261001",
    ]
    owner = notes["REQ-REGISTER-DUE-com-2026-0004-20261001"]
    assert owner["intake_owner"] == "E1 Identity"
    assert "was due" in owner["title"]


def test_an_owner_demand_written_before_the_due_point_is_not_duplicated(tmp_path: Path) -> None:
    web = FakeWeb(_register(_commitment()))
    _run(tmp_path, web, "2026-09-30T12:00:00Z")
    rc, requests_dir, state = _run(tmp_path, web, "2026-10-02T00:30:00Z")
    assert rc == 0
    assert sorted(_written(requests_dir)) == [
        "REQ-REGISTER-DUE-com-2026-0004-20261001",
        "REQ-REGISTER-SLIPPED-com-2026-0004-20261001",
    ]
    recorded = json.loads(state.read_text())
    assert recorded["created"] == ["REQ-REGISTER-SLIPPED-com-2026-0004-20261001"]
    assert recorded["skipped_existing"] == ["REQ-REGISTER-DUE-com-2026-0004-20261001"]


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
