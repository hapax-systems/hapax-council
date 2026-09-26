from __future__ import annotations

import importlib.util
import sys
from datetime import datetime
from pathlib import Path
from types import ModuleType
from unittest import mock
from zoneinfo import ZoneInfo

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "send-stakeholder-revenue-brief.py"
TZ = ZoneInfo("America/Chicago")
NOW = datetime(2026, 4, 30, 8, 45, tzinfo=TZ)


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("stakeholder_revenue_brief", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


brief = _load_module()


def _source(path: Path) -> Path:
    path.write_text(
        """---
title: Stakeholder Brief
status: draft
gmail_message_id: old-message
---
# Stakeholder Brief

Opening note.

## Revenue

Scenario table.
""",
        encoding="utf-8",
    )
    return path


def _config(tmp_path: Path) -> brief.BriefConfig:
    return brief.BriefConfig(
        source_path=_source(tmp_path / "brief.md"),
        generated_dir=tmp_path / "generated",
        state_dir=tmp_path / "state",
        timezone=TZ,
        recipient_name="Stakeholder",
        delivery_note=None,
        summary_lines=(),
    )


def _fake_pandoc(_markdown_path: Path, docx_path: Path) -> None:
    docx_path.write_bytes(b"fake-docx")


def test_generates_docx_without_sending_or_state(tmp_path: Path) -> None:
    config = _config(tmp_path)
    with mock.patch.object(brief, "_run_pandoc", side_effect=_fake_pandoc):
        result = brief.run(config, now=NOW)

    assert result["sent"] is False
    assert Path(result["generated_markdown"]).exists()
    assert Path(result["docx"]).read_bytes() == b"fake-docx"
    assert not (config.state_dir / "state.json").exists()


def test_the_script_has_no_send_path() -> None:
    assert not hasattr(brief, "_send_email")
    assert not hasattr(brief, "_build_gmail_service_from_pass")


def test_send_flag_is_refused_with_a_next_action(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        brief.main(["--send"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "sending from this script is retired" in err
    assert "Next action:" in err
