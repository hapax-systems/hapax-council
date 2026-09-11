"""Tests for the CEI SLICE 4 caller (cc-execution-attestation-check).

Self-contained: loads the script as a module, mocks transcript/claim resolution, exercises
the shipped observer against fixture transcripts. No shared fixtures; unittest.mock only.
"""

import importlib.util
import json
from pathlib import Path
from unittest import mock

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "cc-execution-attestation-check.py"
_spec = importlib.util.spec_from_file_location("cc_exec_attest_check", _SCRIPT)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _write_transcript(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def _assistant(model: str, text: str = "ok") -> dict:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "model": model,
            "content": [{"type": "text", "text": text}],
        },
    }


def _fallback(frm: str, to: str, request_id: str, trigger: str = "refusal") -> dict:
    return {
        "type": "system",
        "subtype": "model_refusal_fallback",
        "originalModel": frm,
        "fallbackModel": to,
        "trigger": trigger,
        "requestId": request_id,
    }


def _note(path: Path, task_id: str) -> Path:
    path.write_text(f"---\ntask_id: {task_id}\nstatus: claimed\n---\n# body\n", encoding="utf-8")
    return path


class TestExecutionAttestationCaller:
    def test_captures_served_model_mismatch_with_request_id(self, tmp_path):
        transcript = tmp_path / "session.jsonl"
        _write_transcript(
            transcript,
            [
                _assistant("claude-opus-4-8"),
                _fallback("claude-fable-5", "claude-opus-4-8", "req_TEST123"),
            ],
        )
        note = _note(tmp_path / "task.md", "cc-task-x")

        with (
            mock.patch.object(mod, "_claiming_session_id", return_value="s1"),
            mock.patch.object(mod, "_resolve_transcript", return_value=transcript),
            mock.patch.object(mod, "LEDGER_DIR", tmp_path / "ledger"),
        ):
            payload = mod.observe_close(note)
            # observe_close is pure; persist + re-read to prove the receipt is JOINable.
            mod._ledger(payload["task_id"], payload)  # noqa: SLF001

        # The accounting defect made visible: both ends of the fallback are attributed.
        assert payload["fallback_events"] == [
            {
                "from_model": "claude-fable-5",
                "to_model": "claude-opus-4-8",
                "trigger": "refusal",
                "request_id": "req_TEST123",
            }
        ]
        assert set(payload["observed_models"]) == {"claude-fable-5", "claude-opus-4-8"}
        ledger = json.loads((tmp_path / "ledger" / "cc-task-x.json").read_text(encoding="utf-8"))
        assert ledger["fallback_events"][0]["request_id"] == "req_TEST123"

    def test_admissible_single_sanctioned_model_no_fallback(self, tmp_path):
        transcript = tmp_path / "s.jsonl"
        _write_transcript(transcript, [_assistant("claude-sonnet-5")])
        note = _note(tmp_path / "t.md", "cc-task-y")

        with (
            mock.patch.object(mod, "_claiming_session_id", return_value="s"),
            mock.patch.object(mod, "_resolve_transcript", return_value=transcript),
            mock.patch.object(mod, "LEDGER_DIR", tmp_path / "l"),
        ):
            payload = mod.observe_close(note)

        assert payload["fallback_events"] == []
        assert payload["observed_models"] == ["claude-sonnet-5"]
        assert payload["turn_count"] == 1

    def test_no_transcript_is_fail_open(self, tmp_path):
        note = _note(tmp_path / "t.md", "cc-task-z")
        with (
            mock.patch.object(mod, "_claiming_session_id", return_value=None),
            mock.patch.object(mod, "_resolve_transcript", return_value=None),
            mock.patch.object(mod, "LEDGER_DIR", tmp_path / "l"),
        ):
            payload = mod.observe_close(note)
        # Advisory: a missing transcript never blocks; records that there was nothing to observe.
        assert payload["fallback_events"] == []
        assert payload["transcript"] is None
        assert "nothing to observe" in payload["note"]

    def test_ledger_is_idempotent_per_close(self, tmp_path):
        transcript = tmp_path / "s.jsonl"
        _write_transcript(transcript, [_assistant("claude-haiku-4-5")])
        note = _note(tmp_path / "t.md", "cc-task-idem")
        ledger_dir = tmp_path / "ledger"

        for _ in range(3):
            with (
                mock.patch.object(mod, "_claiming_session_id", return_value="s"),
                mock.patch.object(mod, "_resolve_transcript", return_value=transcript),
                mock.patch.object(mod, "LEDGER_DIR", ledger_dir),
            ):
                payload = mod.observe_close(note)
                mod._ledger(payload["task_id"], payload)  # noqa: SLF001 — exercise the writer

        files = list(ledger_dir.glob("*.json"))
        assert len(files) == 1, (
            "ledger overwrites per task (one file per close, not append-only growth)"
        )
        record = json.loads(files[0].read_text(encoding="utf-8"))
        assert record["task_id"] == "cc-task-idem"

    def test_main_is_noop_when_shadow_off(self, tmp_path, monkeypatch):
        note = _note(tmp_path / "t.md", "cc-task-off")
        monkeypatch.setattr(mod, "LEDGER_DIR", tmp_path / "ledger")
        monkeypatch.delenv(mod.GATE_ENV, raising=False)
        # main() takes sys.argv-style: argv[0]=prog, argv[1]=note path.
        assert mod.main(["cc-execution-attestation-check.py", str(note)]) == 0
        # No ledger written when the gate is off.
        ledger_dir = tmp_path / "ledger"
        assert not ledger_dir.exists() or not list(ledger_dir.glob("*.json"))

    def test_main_ledgers_when_shadow_on(self, tmp_path, monkeypatch):
        transcript = tmp_path / "s.jsonl"
        _write_transcript(
            transcript,
            [
                _assistant("claude-opus-4-8"),
                _fallback("claude-fable-5", "claude-opus-4-8", "req_LIVE"),
            ],
        )
        note = _note(tmp_path / "t.md", "cc-task-on")
        monkeypatch.setenv(mod.GATE_ENV, "shadow")
        monkeypatch.setattr(mod, "LEDGER_DIR", tmp_path / "ledger")
        with (
            mock.patch.object(mod, "_claiming_session_id", return_value="s"),
            mock.patch.object(mod, "_resolve_transcript", return_value=transcript),
        ):
            rc = mod.main(["cc-execution-attestation-check.py", str(note)])
        assert rc == 0  # SHADOW never blocks close.
        record = json.loads((tmp_path / "ledger" / "cc-task-on.json").read_text(encoding="utf-8"))
        assert record["fallback_events"][0]["request_id"] == "req_LIVE"


def test_script_has_a_production_call_site_of_the_observer():
    """The acceptance criterion: the shipped observer gains a non-test, non-vulture call-site."""
    text = _SCRIPT.read_text(encoding="utf-8")
    assert "from shared.execution_observer import" in text
    assert "observe_claude_transcript" in text
    # The caller never invokes an enforce-flip routine (receipt-attribution only).
    assert "enforce_flip(" not in text
    # The decline is legitimate + final: the docstring states it RECORDS, never circumvents.
    assert "RECORDS, never" in text


def test_scope_worktrees_reads_mutation_scope_refs(tmp_path):
    note = tmp_path / "t.md"
    note.write_text(
        "---\n"
        "task_id: cc-task-w\n"
        "mutation_scope_refs:\n"
        '  - "~/projects/hapax-council/"\n'
        "  - ~/projects/hapax-constitution--metadata-owner/\n"
        "authority_case: CASE-X\n"
        "---\n",
        encoding="utf-8",
    )
    refs = mod._scope_worktrees(note)  # noqa: SLF001
    assert refs == [
        Path("~/projects/hapax-council/").expanduser(),
        Path("~/projects/hapax-constitution--metadata-owner/").expanduser(),
    ]


def test_encode_project_dir_matches_claude_cwd_encoding():
    # /home/hapax/projects/hapax-council -> -home-hapax-projects-hapax-council
    assert mod._encode_project_dir(Path("/home/hapax/projects/hapax-council")) == (  # noqa: SLF001
        "-home-hapax-projects-hapax-council"
    )
