"""Output-only seat watches retain status while withholding foreign content."""

import json
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/hapax-seat-watch"


def watch(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(SCRIPT), *args], capture_output=True, text=True, check=False)


def test_inbox_and_han_report_metadata_without_reading_bodies(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    han = tmp_path / "han"
    inbox.mkdir()
    han.mkdir()
    (inbox / "notice.md").write_text("foreign inbox body SECRET-CONTROL", encoding="utf-8")
    (han / "sha256-record.eml").write_text("foreign HAN body SECRET-CONTROL", encoding="utf-8")
    (han / "sha256-record.json").write_text("foreign HAN metadata SECRET-CONTROL", encoding="utf-8")
    for kind, flag, directory in (("inbox", "--inbox-dir", inbox), ("han", "--han-dir", han)):
        result = watch(kind, flag, str(directory))
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["kind"] == kind
        assert payload["status"] == "ok"
        assert payload["count"] == 1
        assert "SECRET-CONTROL" not in result.stdout + result.stderr


def test_blocked_panes_emit_reason_only_and_refuse_failed_tmux(tmp_path: Path) -> None:
    fake = tmp_path / "tmux"
    fake.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = list-panes ]; then printf 'hapax-codex-seat\\t%%1\\t0\\n'; "
        "else printf 'credential SECRET-CONTROL\\nHOLD — quota wall\\n'; fi\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    result = watch("panes", "--tmux-bin", str(fake))
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["blocked"] == [{"session": "hapax-codex-seat", "pane": "%1", "reason": "quota"}]
    assert "SECRET-CONTROL" not in result.stdout + result.stderr
    fake.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    failed = watch("panes", "--tmux-bin", str(fake))
    assert failed.returncode != 0
    assert json.loads(failed.stdout)["status"] == "unavailable"


def test_github_budget_projects_existing_rate_limit_response(tmp_path: Path) -> None:
    fake = tmp_path / "gh"
    fake.write_text(
        "#!/bin/sh\n"
        'printf \'{"resources":{"core":{"limit":5000,"remaining":3,"reset":1800000000},'
        '"search":{"limit":30,"remaining":12,"reset":1800000000}}}\'\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    result = watch("github", "--gh-bin", str(fake))
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["core"]["remaining"] == 3
    assert payload["search"]["remaining"] == 12
    assert "resources" not in payload


def test_memory_timer_instance_invokes_existing_projection(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "MEMORY.md").write_text("seat memory\n", encoding="utf-8")
    dest = tmp_path / "vault" / "memory-export-current"
    result = watch("memory", "--source-dir", str(source), "--dest-dir", str(dest))
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "updated"
    assert payload["export_dir"] == str(dest)
    assert (dest / "MEMORY.md").read_text() == "seat memory\n"
