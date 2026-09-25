"""The witness rota judges pre-submission records with the pinned agy reviewer, scrubbed.

Every run records the witness's observed execution identity. Any failure records "no witness",
which refuses; the rota never falls back to another family.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from shared import witness_rota as rota
from shared.public_gate_receipts import public_gate_authority_signature
from shared.signing_holder import cgroup_admitted
from shared.witness_rota import (
    FAMILY,
    Identity,
    agy_identity,
    framing_problems,
    parse_review,
    process,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REVIEWER = REPO_ROOT / "scripts/hapax-agy-reviewer"
SECRET = "test-secret-not-a-real-key"
NOW = datetime(2026, 9, 25, 9, 0, tzinfo=UTC)
DIGEST = hashlib.sha256(b"the artifact").hexdigest()
CANARY = "CANARY-7f3a-estate-framing"
ACCEPT = "```yaml\nverdict: accept\nfindings: []\nchecklist: {}\n```\n"
BLOCK = (
    "```yaml\nverdict: block\nfindings:\n- severity: major\n  lens: witness\n  file: note.md\n"
    "  line: 1\n  title: no reception scenario for the maintainer\n  detail: x\n"
    "checklist: {}\n```\n"
)


def sign(payload: Any) -> str:
    return public_gate_authority_signature(payload, SECRET)


def identity() -> Identity:
    return Identity("/usr/local/lib/hapax/witness-rota/agy", "a" * 64, "1.2.11", "b" * 64, True)


@pytest.fixture
def tree(tmp_path: Path) -> dict[str, Path]:
    vault = tmp_path / "vault"
    lanebus = vault / "lanebus"
    (lanebus / "witness-rota").mkdir(parents=True)
    (lanebus / "dev32").mkdir()
    (vault / "note.md").write_text("audience, channel norms, receptions, readiness\n")
    active = tmp_path / "active"
    active.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    return {"vault": vault, "lanebus": lanebus, "active": active, "work": work, "tmp": tmp_path}


def drop(
    tree: dict[str, Path], name: str = "20260925T085000Z-dev32-record.md", **overrides: Any
) -> Path:
    note = (tree["vault"] / "note.md").read_bytes()
    record: dict[str, Any] = {
        "from": "claude/dev32",
        "to": "witness-rota",
        "created_at": "2026-09-25T08:50:00Z",
        "artifact_fingerprint": DIGEST,
        "nonce": "0123456789abcdef0123",
        "policy_ref": "public-gate:cp-artifact-1",
        "audience": "maintainers of the public repository",
        "channel": "forge",
        "not_before": "2026-09-25T08:00:00Z",
        "not_after": "2026-09-25T20:00:00Z",
        "expected_head_sha": "c" * 40,
        "author": "claude/dev32",
        "author_family": "claude",
        "tier": "B",
        "evidence_refs": [{"path": "note.md", "sha256": hashlib.sha256(note).hexdigest()}],
    }
    record.update(overrides)
    record = {k: v for k, v in record.items() if v is not None}
    path = tree["lanebus"] / "witness-rota" / name
    path.write_text("---\n" + yaml.safe_dump(record, sort_keys=False) + "---\n\nThe artifact.\n")
    return path


class FakeRunner:
    def __init__(self, stdout: str = ACCEPT, rc: int = 0, error: Exception | None = None) -> None:
        self.stdout, self.rc, self.error = stdout, rc, error
        self.calls: list[tuple[list[str], str, dict[str, str]]] = []

    def __call__(self, argv: list[str], stdin: str, env: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append((argv, stdin, dict(env)))
        if self.error is not None:
            raise self.error
        return subprocess.CompletedProcess(argv, self.rc, self.stdout, "")


def run(tree: dict[str, Path], path: Path, runner: FakeRunner, **kw: Any) -> rota.Outcome:
    kw.setdefault("identity", identity())
    kw.setdefault("identity_problems", [])
    return process(
        path,
        out_dir=tree["active"],
        evidence_root=tree["vault"],
        lanebus=tree["lanebus"],
        runner=runner,
        workroot=tree["work"],
        home=tree["tmp"] / "home",
        now=NOW,
        sign=sign,
        **kw,
    )


def slot_data(tree: dict[str, Path]) -> dict[str, Any]:
    (path,) = tree["active"].iterdir()
    return yaml.safe_load(path.read_text())


# --- the witness's execution identity ---


def _pin(
    tmp_path: Path, content: bytes = b"pinned agy", version: str = "1.2.11"
) -> tuple[Path, Path]:
    agy = tmp_path / "agy"
    agy.write_bytes(content)
    pin = tmp_path / "agy.pin"
    pin.write_text(json.dumps({"sha256": hashlib.sha256(content).hexdigest(), "version": version}))
    return agy, pin


def test_the_identity_is_the_pinned_binary_as_installed(tmp_path: Path) -> None:
    agy, pin = _pin(tmp_path)
    lane = tmp_path / "lane-agy"
    lane.write_bytes(b"pinned agy")
    found, problems = agy_identity(agy, pin, lane)
    assert problems == [] and found is not None
    assert found.agy_sha256 == hashlib.sha256(b"pinned agy").hexdigest()
    assert found.agy_version == "1.2.11" and found.lane_agy_differs is False


def test_a_pinned_binary_that_differs_from_its_pin_is_refused(tmp_path: Path) -> None:
    agy, pin = _pin(tmp_path)
    agy.write_bytes(b"replaced after install")
    found, problems = agy_identity(agy, pin, tmp_path / "lane-agy")
    assert found is None and problems


def test_a_missing_pin_is_refused(tmp_path: Path) -> None:
    agy, pin = _pin(tmp_path)
    pin.unlink()
    found, problems = agy_identity(agy, pin, tmp_path / "lane-agy")
    assert found is None and problems


def test_a_lane_agy_that_differs_is_recorded_not_refused(tmp_path: Path) -> None:
    agy, pin = _pin(tmp_path)
    lane = tmp_path / "lane-agy"
    lane.write_bytes(b"a newer agy")
    found, problems = agy_identity(agy, pin, lane)
    assert problems == [] and found is not None
    assert found.lane_agy_differs is True
    assert found.lane_agy_sha256 == hashlib.sha256(b"a newer agy").hexdigest()


# --- scrubbing: no framing above the workroot ---


@pytest.mark.parametrize("name", rota.FRAMING)
def test_framing_above_the_workroot_is_found(tmp_path: Path, name: str) -> None:
    planted = tmp_path / name
    if name.endswith((".md", ".json")):
        planted.write_text(CANARY)
    else:
        planted.mkdir()
    work = tmp_path / "a" / "work"
    work.mkdir(parents=True)
    assert framing_problems(work)


def test_a_clean_workroot_has_no_framing(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    assert framing_problems(work) == []


# --- the reviewer's verdict ---


def test_accept_is_parsed() -> None:
    assert parse_review(ACCEPT)[0] == "accept"


def test_block_is_parsed_with_its_findings() -> None:
    verdict, detail = parse_review(BLOCK)
    assert verdict == "block" and "no reception scenario" in detail


@pytest.mark.parametrize(
    "stdout",
    [
        "I think it looks fine.",
        "```yaml\nverdict: [\n```",
        "```yaml\nverdict: pass\nfindings: []\n```",
        "```yaml\n- accept\n```",
    ],
)
def test_output_that_is_not_one_valid_verdict_is_refused(stdout: str) -> None:
    assert parse_review(stdout)[0] is None


# --- the canary: estate framing never reaches the model (real reviewer, fake agy) ---


def _fake_agy(tmp_path: Path) -> tuple[Path, Path]:
    seen = tmp_path / "seen.txt"
    agy = tmp_path / "bin" / "agy"
    agy.parent.mkdir()
    agy.write_text(
        "#!/usr/bin/python3\n"
        "import json, os, pathlib\n"
        "seen = []\n"
        "cwd = pathlib.Path.cwd()\n"
        f"names = {list(rota.FRAMING)!r}\n"
        "for d in [cwd, *cwd.parents]:\n"
        "    for n in names:\n"
        "        p = d / n\n"
        "        if p.is_file():\n"
        "            seen.append(p.read_text(errors='replace'))\n"
        "        elif p.is_dir():\n"
        "            seen += [f.read_text(errors='replace') for f in p.rglob('*') if f.is_file()]\n"
        "home = pathlib.Path(os.environ.get('HOME', '/nonexistent'))\n"
        "if home.is_dir():\n"
        "    seen += [f.read_text(errors='replace') for f in home.rglob('*') if f.is_file()]\n"
        "seen.append((cwd / 'review-dossier.md').read_text())\n"
        "seen.append(json.dumps(dict(os.environ)))\n"
        f"pathlib.Path({str(seen)!r}).write_text('\\n'.join(seen))\n"
        f"print({ACCEPT!r}, end='')\n"
    )
    agy.chmod(0o755)
    return agy, seen


def _operator_home(tree: dict[str, Path]) -> Path:
    home = tree["tmp"] / "home"
    (home / ".gemini" / "antigravity-cli").mkdir(parents=True)
    token = {"access_token": "t" * 40, "refresh_token": "r" * 40, "token_type": "Bearer"}
    (home / ".gemini" / "antigravity-cli" / "antigravity-oauth-token").write_text(json.dumps(token))
    (home / "AGENTS.md").write_text(f"estate framing {CANARY}\n")
    (home / ".gemini" / "GEMINI.md").write_text(f"memory {CANARY}\n")
    (home / ".gemini" / "settings.json").write_text(json.dumps({"mcpServers": {CANARY: {}}}))
    return home


def _real_runner(argv: list[str], stdin: str, env: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv, input=stdin, env=dict(env), text=True, capture_output=True, timeout=60
    )


def test_estate_framing_never_reaches_the_model(tree: dict[str, Path]) -> None:
    home = _operator_home(tree)
    agy, seen = _fake_agy(tree["tmp"])
    ident = Identity(str(agy), "a" * 64, "1.2.11", "b" * 64, False)
    outcome = process(
        drop(tree),
        out_dir=tree["active"],
        evidence_root=tree["vault"],
        lanebus=tree["lanebus"],
        runner=_real_runner,
        identity=ident,
        identity_problems=[],
        workroot=tree["work"],
        home=home,
        now=NOW,
        reviewer=REVIEWER,
        sign=sign,
    )
    assert outcome.receipt is not None, outcome.reasons
    observed = seen.read_text()
    assert "maintainers of the public repository" in observed
    assert CANARY not in observed


def test_framing_above_the_workroot_means_no_witness_and_agy_never_runs(
    tree: dict[str, Path],
) -> None:
    home = _operator_home(tree)
    agy, seen = _fake_agy(tree["tmp"])
    (tree["tmp"] / "AGENTS.md").write_text(f"planted {CANARY}\n")
    ident = Identity(str(agy), "a" * 64, "1.2.11", "b" * 64, False)
    outcome = process(
        drop(tree),
        out_dir=tree["active"],
        evidence_root=tree["vault"],
        lanebus=tree["lanebus"],
        runner=_real_runner,
        identity=ident,
        identity_problems=[],
        workroot=tree["work"],
        home=home,
        now=NOW,
        reviewer=REVIEWER,
        sign=sign,
    )
    assert outcome.receipt is None and not seen.exists()
    assert slot_data(tree)["review_team_verdict"] == "refused"


# --- processing a record ---


def test_a_validated_record_gets_a_receipt_with_the_identity_and_a_reply(tree) -> None:
    runner = FakeRunner()
    outcome = run(tree, drop(tree), runner)
    assert outcome.receipt is not None and outcome.reply is not None
    data = yaml.safe_load(outcome.receipt.read_text())
    assert data["review_team_verdict"] == "quorum-accept"
    assert data["reviewers"][0]["family"] == FAMILY
    assert data["witness_execution"] == identity().as_record()
    assert outcome.reply.parent == tree["lanebus"] / "dev32"
    assert outcome.receipt.name in outcome.reply.read_text()


def test_the_reviewer_runs_the_pinned_agy_isolated(tree) -> None:
    runner = FakeRunner()
    run(tree, drop(tree), runner)
    argv, stdin, env = runner.calls[0]
    assert argv[:2] == ["/usr/bin/python3", "-I"]
    assert argv[argv.index("--agy-bin") + 1] == identity().agy_path
    assert env["TMPDIR"] == str(tree["work"])
    assert "maintainers of the public repository" in stdin


def test_a_blocked_record_gets_a_recorded_refusal(tree) -> None:
    outcome = run(tree, drop(tree), FakeRunner(stdout=BLOCK))
    assert outcome.receipt is None
    data = slot_data(tree)
    assert data["review_team_verdict"] == "refused"
    assert data["witness_execution"] == identity().as_record()
    assert outcome.reply is not None and "no reception scenario" in outcome.reply.read_text()


@pytest.mark.parametrize(
    "runner",
    [
        FakeRunner(error=FileNotFoundError("/usr/bin/python3")),
        FakeRunner(rc=65, stdout=ACCEPT),
        FakeRunner(stdout="looks fine to me"),
    ],
    ids=["unavailable", "token-echo", "invalid-output"],
)
def test_a_failed_witness_records_no_witness_and_never_another_family(tree, runner) -> None:
    outcome = run(tree, drop(tree), runner)
    assert outcome.receipt is None
    assert len(runner.calls) == 1
    data = slot_data(tree)
    assert data["review_team_verdict"] == "refused"
    assert any("no witness" in r for r in data["refusals"])


def test_no_identity_means_no_witness_and_no_run(tree) -> None:
    runner = FakeRunner()
    outcome = run(tree, drop(tree), runner, identity=None, identity_problems=["pin missing"])
    assert outcome.receipt is None and runner.calls == []
    assert any("no witness" in r for r in slot_data(tree)["refusals"])


def test_a_malformed_record_is_refused_without_a_witness_run(tree) -> None:
    runner = FakeRunner()
    outcome = run(tree, drop(tree, not_after="2026-09-25T08:30:00Z"), runner)
    assert outcome.receipt is None and runner.calls == []
    assert slot_data(tree)["review_team_verdict"] == "refused"


def test_an_author_other_than_the_sender_is_refused(tree) -> None:
    runner = FakeRunner()
    outcome = run(tree, drop(tree, author="claude/dev7"), runner)
    assert outcome.receipt is None and runner.calls == []


def test_a_processed_record_is_not_witnessed_again(tree) -> None:
    path = drop(tree)
    run(tree, path, FakeRunner())
    again = FakeRunner()
    outcome = run(tree, path, again)
    assert outcome.skipped and again.calls == []


# --- packaging: system units the holder admits, and root-owned code ---


def test_the_rota_unit_is_the_one_the_holder_admits() -> None:
    service = (REPO_ROOT / "systemd/units/hapax-witness-rota@.service").read_text()
    timer = (REPO_ROOT / "systemd/units/hapax-witness-rota.timer").read_text()
    assert "# Hapax-Install-Scope: system" in service and "# Hapax-Install-Scope: system" in timer
    assert "Unit=hapax-witness-rota@scan.service" in timer
    assert cgroup_admitted(
        "/system.slice/system-hapax\\x2dwitness\\x2drota.slice/hapax-witness-rota@scan.service"
    )
    for line in (
        "User=hapax",
        "PrivateTmp=yes",
        "NoNewPrivileges=yes",
        "ExecStart=/usr/local/sbin/hapax-witness-rota",
        "Environment=HAPAX_AGY_BIN=/usr/local/lib/hapax/witness-rota/agy",
    ):
        assert line in service, line


def test_the_entry_script_imports_only_the_installed_library() -> None:
    lines = (REPO_ROOT / "scripts/hapax-witness-rota").read_text().splitlines()
    assert lines[0] == "#!/usr/bin/python3 -I"
    text = "\n".join(lines)
    assert 'sys.path.insert(0, "/usr/local/lib/hapax/witness-rota")' in text
    assert "from shared.witness_rota import main" in text


def test_the_reviewer_verdict_window_is_the_production_time(tree) -> None:
    outcome = run(tree, drop(tree), FakeRunner())
    assert outcome.receipt is not None
    data = yaml.safe_load(outcome.receipt.read_text())
    assert datetime.fromisoformat(data["reviewers"][0]["at"]) == NOW
