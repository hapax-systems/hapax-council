"""Contract tests for scripts/wyoming-llc-remaining-steps.py."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "wyoming-llc-remaining-steps.py"


@pytest.fixture(scope="module")
def runner_mod() -> ModuleType:
    spec = importlib.util.spec_from_file_location("wyoming_llc_remaining_steps", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _packet_config(
    tmp_path: Path,
    *,
    mercury_ready: bool = True,
    mn_assessment: str = "yes",
    sensitive_tail: str = "",
) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    formation = tmp_path / "articles-of-organization.pdf"
    irs_letter = tmp_path / "irs-confirmation-letter.pdf"
    address_doc = tmp_path / "address-verification.pdf"
    agreement = tmp_path / "operating-agreement.pdf"
    records = tmp_path / "records"
    for path in (formation, irs_letter, address_doc, agreement):
        path.write_text("placeholder\n", encoding="utf-8")
    records.mkdir()

    address_ready = str(mercury_ready).lower()
    prohibited_reviewed = str(mercury_ready).lower()
    physical_kind = "residential" if mercury_ready else "po_box"
    path = tmp_path / "remaining-steps.toml"
    path.write_text(
        f"""
schema_version = 1

[entity]
legal_name = "Example Research LLC"
home_jurisdiction = "WY"
formation_document_path = "{formation}"
irs_confirmation_letter_path = "{irs_letter}"
wyoming_good_standing_path = ""

[mercury]
industry = "Professional, Scientific, and Technical Services"
business_description = "Research infrastructure and software systems."
source_of_funds = "Customer payments, sponsorships, grants, and consulting revenue."
planned_us_operations = "US-operated single-member research and software business."
legal_address_operator_ready = true
physical_address_operator_ready = {address_ready}
physical_address_kind = "{physical_kind}"
physical_address_verification_path = "{address_doc}"
formation_doc_matches_legal_name = true
owners_25_percent_plus_confirmed = true
control_person_confirmed = true
beneficial_owner_count = 1
prohibited_business_reviewed = {prohibited_reviewed}

[minnesota]
operator_transacting_business_assessment = "{mn_assessment}"
sos_forms_reviewed = true
statute_322c_reviewed = true
name_availability_checked = true
registered_agent_ready = true
registered_office_ready = true
principal_place_of_business_ready = true
home_office_address_ready = true
official_notice_email_ready = true
authorized_signer_ready = true
professional_firm = false
professional_firm_attachment_ready = false
filing_method = "online"

[operating_agreement]
draft_path = ""
final_signed_path = "{agreement}"
legal_review_status = "executed"
single_member_terms_recorded = true
management_structure_recorded = true
capital_contribution_recorded = true
distribution_policy_recorded = true
transferability_recorded = true
amendment_process_recorded = true
records_storage_path = "{records}"
bank_copy_ready = true
{sensitive_tail}
""".lstrip(),
        encoding="utf-8",
    )
    return path


def test_ready_packet_builds_all_three_sections(
    runner_mod: ModuleType,
    tmp_path: Path,
) -> None:
    config = runner_mod.load_config(_packet_config(tmp_path))
    report = runner_mod.build_report(
        config,
        now=datetime(2026, 5, 19, 1, 0, tzinfo=UTC),
    )

    assert report["overall_status"] == "ready_for_operator"
    assert report["sections"]["mercury"]["status"] == "ready_for_operator"
    assert report["sections"]["minnesota"]["status"] == "ready_for_operator"
    assert report["sections"]["operating_agreement"]["status"] == "ready_for_operator"
    assert report["sections"]["minnesota"]["current_fee_usd"] == 205
    assert report["official_sources"]["verified_on"] == "2026-05-19"
    assert report["safety"]["no_provider_or_government_calls"] is True
    assert any("submit Mercury" in gate for gate in report["operator_gates"])


def test_sensitive_keys_and_values_fail_closed(
    runner_mod: ModuleType,
    tmp_path: Path,
) -> None:
    with pytest.raises(runner_mod.ConfigError, match="sensitive key"):
        runner_mod.load_config(
            _packet_config(
                tmp_path / "key",
                sensitive_tail='bank_account_number = "123456789012"\n',
            )
        )

    with pytest.raises(runner_mod.ConfigError, match="EIN-like"):
        runner_mod.load_config(
            _packet_config(
                tmp_path / "value",
                sensitive_tail='private_note = "12-3456789"\n',
            )
        )


def test_mercury_rejects_disallowed_address_kind(
    runner_mod: ModuleType,
    tmp_path: Path,
) -> None:
    config = runner_mod.load_config(_packet_config(tmp_path, mercury_ready=False))
    mercury = runner_mod.build_mercury_section(config)

    assert mercury["status"] == "blocked"
    address_check = next(
        check for check in mercury["checks"] if check["id"] == "mercury_physical_address_kind"
    )
    assert address_check["status"] == "blocked"
    assert address_check["evidence"] == "po_box"


def test_minnesota_unknown_assessment_remains_operator_review(
    runner_mod: ModuleType,
    tmp_path: Path,
) -> None:
    config = runner_mod.load_config(_packet_config(tmp_path, mn_assessment="unknown"))
    section = runner_mod.build_minnesota_section(config)

    assert section["status"] == "operator_review"
    assert section["assessment"] == "unknown"
    assert "does not decide" in section["legal_boundary"]


def test_main_writes_redacted_local_packet(
    runner_mod: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = _packet_config(tmp_path / "config")
    output_dir = tmp_path / "out"

    rc = runner_mod.main(["--config", str(config_path), "--output-dir", str(output_dir)])

    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    report_path = Path(summary["report_path"])
    note_path = Path(summary["note_path"])
    report_text = report_path.read_text(encoding="utf-8")
    note_text = note_path.read_text(encoding="utf-8")
    assert summary["overall_status"] == "ready_for_operator"
    assert "12-3456789" not in report_text
    assert "12-3456789" not in note_text
    assert "Dry-run local packet only" in note_text


def test_example_config_writer_refuses_overwrite(
    runner_mod: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    example = tmp_path / "example.toml"
    rc = runner_mod.main(["--write-example-config", str(example)])
    assert rc == 0
    assert "Example Research LLC" in example.read_text(encoding="utf-8")
    assert json.loads(capsys.readouterr().out)["example_config"] == str(example)

    rc = runner_mod.main(["--write-example-config", str(example)])
    assert rc == 2
