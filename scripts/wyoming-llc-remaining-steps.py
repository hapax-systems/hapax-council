#!/usr/bin/env python3
"""Build a dry-run operator packet for the Wyoming LLC remaining steps.

This runner is intentionally local-only. It validates a non-secret TOML
worksheet and writes a redacted readiness report for three operator-owned
threads: Mercury onboarding, Minnesota foreign LLC review, and the Wyoming LLC
operating agreement packet. It never files government forms, opens accounts,
stores identity material, signs documents, pays fees, or calls provider APIs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

TASK_ID = "wyoming-llc-remaining-steps"
DEFAULT_CONFIG = Path(
    os.environ.get(
        "HAPAX_WYOMING_LLC_REMAINING_STEPS_CONFIG",
        str(Path.home() / ".config/hapax/wyoming-llc-remaining-steps.toml"),
    )
)
DEFAULT_OUTPUT_DIR = Path.home() / ".local/state/hapax/wyoming-llc-remaining-steps"
DEFAULT_VAULT_NOTE = (
    Path.home() / "Documents/Personal/30-areas/hapax/wyoming-llc-remaining-steps.md"
)

VERIFIED_ON = "2026-05-19"

MERCURY_ELIGIBILITY_URL = (
    "https://support.mercury.com/hc/en-us/articles/"
    "28770467511060-Eligibility-and-requirements-for-opening-a-Mercury-account"
)
MERCURY_DOCUMENTS_URL = (
    "https://support.mercury.com/hc/en-us/articles/28770957425172-Gathering-your-documents"
)
MERCURY_ADDRESS_URL = (
    "https://support.mercury.com/hc/en-us/articles/28769699533588-Company-address-requirements"
)
MN_FOREIGN_LLC_FORMS_URL = (
    "https://www.sos.mn.gov/business-liens/business-forms-fees/"
    "foreign-limited-liability-company-forms/"
)
MN_FOREIGN_LLC_FEE_URL = "https://sos.mn.gov/fees"
MN_CERTIFICATE_FORM_URL = "https://www.sos.mn.gov/media/1580/foreignllccertificateofauthority.pdf"
MN_322C_0802_URL = "https://www.revisor.mn.gov/statutes/cite/322C.0802"
MN_322C_0804_URL = "https://www.revisor.mn.gov/statutes/cite/322C.0804"
MN_322C_0808_URL = "https://www.revisor.mn.gov/statutes/2025/cite/322C.0808"
WY_OPERATING_AGREEMENT_URL = (
    "https://wyoleg.gov/NXT/gateway.dll/2022%20Wyoming%20Statutes/"
    "2022%20Titles/898/1040/1041?f=templates&fn=document-frameset.htm"
)

OPERATOR_GATES: tuple[str, ...] = (
    "submit Mercury application fields, identity documents, beneficial-owner data, "
    "or address documents",
    "create or approve a bank account, card, transfer, ACH, wire, check deposit, "
    "or any other banking instruction",
    "determine whether Minnesota foreign registration is legally required",
    "file Minnesota Certificate of Authority forms or pay Secretary of State fees",
    "sign, notarize, mail, or submit any government or bank document",
    "draft legal terms as legal advice, execute the operating agreement, or make "
    "tax/legal elections",
    "store EIN, TIN, SSN, passport, driver's-license, bank-account, routing, or "
    "other sensitive identity values in repo files or runner output",
)

SENSITIVE_CONFIG_KEY_RE = re.compile(
    r"(?:^|_)(?:ein|tin|ssn|itin|tax_id|taxpayer_id|routing_number|"
    r"account_number|bank_account_number|passport_number|driver_license|"
    r"date_of_birth|birthdate|dob|api_key|secret|token|password|private_key)(?:_|$)",
    re.IGNORECASE,
)
EIN_VALUE_RE = re.compile(r"\b\d{2}-\d{7}\b")
SSN_VALUE_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

US_JURISDICTIONS: frozenset[str] = frozenset(
    {
        "AL",
        "AK",
        "AZ",
        "AR",
        "CA",
        "CO",
        "CT",
        "DE",
        "DC",
        "FL",
        "GA",
        "HI",
        "ID",
        "IL",
        "IN",
        "IA",
        "KS",
        "KY",
        "LA",
        "ME",
        "MD",
        "MA",
        "MI",
        "MN",
        "MS",
        "MO",
        "MT",
        "NE",
        "NV",
        "NH",
        "NJ",
        "NM",
        "NY",
        "NC",
        "ND",
        "OH",
        "OK",
        "OR",
        "PA",
        "RI",
        "SC",
        "SD",
        "TN",
        "TX",
        "UT",
        "VT",
        "VA",
        "WA",
        "WV",
        "WI",
        "WY",
        "AS",
        "GU",
        "MP",
        "PR",
        "VI",
    }
)

ACCEPTED_PHYSICAL_ADDRESS_KINDS = frozenset(
    {"commercial_office", "coworking", "residential", "international"}
)
REJECTED_PHYSICAL_ADDRESS_KINDS = frozenset(
    {"cmra", "mail_center", "po_box", "registered_agent", "unknown", "virtual_address"}
)
MN_ASSESSMENTS = frozenset({"unknown", "yes", "no"})
MN_FILING_METHODS = frozenset({"mail", "online", "in_person"})
OPERATING_REVIEW_STATUSES = frozenset(
    {"not_started", "operator_draft", "counsel_reviewed", "executed"}
)

EXAMPLE_CONFIG = """# Non-secret worksheet for scripts/wyoming-llc-remaining-steps.py.
# Do not place EIN/TIN/SSN/passport/bank/routing/account values in this file.
schema_version = 1

[entity]
legal_name = "Example Research LLC"
home_jurisdiction = "WY"
formation_document_path = "~/Documents/Personal/legal/example/articles-of-organization.pdf"
irs_confirmation_letter_path = "~/Documents/Personal/legal/example/irs-confirmation-letter.pdf"
wyoming_good_standing_path = ""

[mercury]
industry = "Professional, Scientific, and Technical Services"
business_description = "Operator-authored research infrastructure and software systems."
source_of_funds = "Customer payments, sponsorships, grants, and consulting revenue."
planned_us_operations = "US-operated single-member research and software business."
legal_address_operator_ready = true
physical_address_operator_ready = false
physical_address_kind = "residential"
physical_address_verification_path = ""
formation_doc_matches_legal_name = true
owners_25_percent_plus_confirmed = true
control_person_confirmed = true
beneficial_owner_count = 1
prohibited_business_reviewed = false

[minnesota]
operator_transacting_business_assessment = "unknown"
sos_forms_reviewed = false
statute_322c_reviewed = false
name_availability_checked = false
registered_agent_ready = false
registered_office_ready = false
principal_place_of_business_ready = false
home_office_address_ready = false
official_notice_email_ready = false
authorized_signer_ready = false
professional_firm = false
professional_firm_attachment_ready = false
filing_method = "online"

[operating_agreement]
draft_path = "~/Documents/Personal/legal/example/operating-agreement-draft.md"
final_signed_path = ""
legal_review_status = "not_started"
single_member_terms_recorded = false
management_structure_recorded = false
capital_contribution_recorded = false
distribution_policy_recorded = false
transferability_recorded = false
amendment_process_recorded = false
records_storage_path = "~/Documents/Personal/legal/example/"
bank_copy_ready = false
"""


class ConfigError(ValueError):
    """Invalid remaining-steps worksheet."""


@dataclass(frozen=True)
class EntityPacket:
    legal_name: str
    home_jurisdiction: str
    formation_document_path: str = ""
    irs_confirmation_letter_path: str = ""
    wyoming_good_standing_path: str = ""


@dataclass(frozen=True)
class MercuryPacket:
    industry: str = ""
    business_description: str = ""
    source_of_funds: str = ""
    planned_us_operations: str = ""
    legal_address_operator_ready: bool = False
    physical_address_operator_ready: bool = False
    physical_address_kind: str = "unknown"
    physical_address_verification_path: str = ""
    formation_doc_matches_legal_name: bool = False
    owners_25_percent_plus_confirmed: bool = False
    control_person_confirmed: bool = False
    beneficial_owner_count: int = 0
    prohibited_business_reviewed: bool = False


@dataclass(frozen=True)
class MinnesotaPacket:
    operator_transacting_business_assessment: str = "unknown"
    sos_forms_reviewed: bool = False
    statute_322c_reviewed: bool = False
    name_availability_checked: bool = False
    registered_agent_ready: bool = False
    registered_office_ready: bool = False
    principal_place_of_business_ready: bool = False
    home_office_address_ready: bool = False
    official_notice_email_ready: bool = False
    authorized_signer_ready: bool = False
    professional_firm: bool = False
    professional_firm_attachment_ready: bool = False
    filing_method: str = "online"


@dataclass(frozen=True)
class OperatingAgreementPacket:
    draft_path: str = ""
    final_signed_path: str = ""
    legal_review_status: str = "not_started"
    single_member_terms_recorded: bool = False
    management_structure_recorded: bool = False
    capital_contribution_recorded: bool = False
    distribution_policy_recorded: bool = False
    transferability_recorded: bool = False
    amendment_process_recorded: bool = False
    records_storage_path: str = ""
    bank_copy_ready: bool = False


@dataclass(frozen=True)
class RemainingStepsConfig:
    schema_version: int
    entity: EntityPacket
    mercury: MercuryPacket
    minnesota: MinnesotaPacket
    operating_agreement: OperatingAgreementPacket


def _required_table(raw: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = raw.get(key)
    if not isinstance(value, Mapping):
        raise ConfigError(f"{key!r} must be a TOML table")
    return value


def _required_str(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{key!r} must be a non-empty string")
    return value.strip()


def _optional_str(raw: Mapping[str, Any], key: str, *, default: str = "") -> str:
    value = raw.get(key, default)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ConfigError(f"{key!r} must be a string")
    return value.strip()


def _required_int(raw: Mapping[str, Any], key: str) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{key!r} must be an integer")
    return value


def _optional_bool(raw: Mapping[str, Any], key: str, *, default: bool = False) -> bool:
    value = raw.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"{key!r} must be a boolean")
    return value


def _reject_sensitive_content(value: Any, *, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_str = str(key)
            if SENSITIVE_CONFIG_KEY_RE.search(key_str):
                raise ConfigError(f"sensitive key {path}.{key_str} is not allowed")
            _reject_sensitive_content(nested, path=f"{path}.{key_str}")
        return
    if isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_sensitive_content(nested, path=f"{path}[{index}]")
        return
    if isinstance(value, str):
        if EIN_VALUE_RE.search(value):
            raise ConfigError(f"sensitive EIN-like value at {path} is not allowed")
        if SSN_VALUE_RE.search(value):
            raise ConfigError(f"sensitive SSN-like value at {path} is not allowed")


def load_config(path: Path) -> RemainingStepsConfig:
    if not path.exists():
        raise ConfigError(f"config not found: {path}")
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    _reject_sensitive_content(raw)

    version = _required_int(raw, "schema_version")
    if version != 1:
        raise ConfigError(f"unsupported schema_version {version}; expected 1")

    entity_raw = _required_table(raw, "entity")
    mercury_raw = _required_table(raw, "mercury")
    minnesota_raw = _required_table(raw, "minnesota")
    agreement_raw = _required_table(raw, "operating_agreement")

    entity = EntityPacket(
        legal_name=_required_str(entity_raw, "legal_name"),
        home_jurisdiction=_required_str(entity_raw, "home_jurisdiction").upper(),
        formation_document_path=_optional_str(entity_raw, "formation_document_path"),
        irs_confirmation_letter_path=_optional_str(entity_raw, "irs_confirmation_letter_path"),
        wyoming_good_standing_path=_optional_str(entity_raw, "wyoming_good_standing_path"),
    )
    if entity.home_jurisdiction not in US_JURISDICTIONS:
        raise ConfigError("entity.home_jurisdiction must be a US state or territory code")

    physical_kind = _optional_str(
        mercury_raw,
        "physical_address_kind",
        default="unknown",
    ).lower()
    if physical_kind not in ACCEPTED_PHYSICAL_ADDRESS_KINDS | REJECTED_PHYSICAL_ADDRESS_KINDS:
        raise ConfigError(
            "mercury.physical_address_kind must be one of "
            + ", ".join(sorted(ACCEPTED_PHYSICAL_ADDRESS_KINDS | REJECTED_PHYSICAL_ADDRESS_KINDS))
        )
    owner_count = _required_int(mercury_raw, "beneficial_owner_count")
    if owner_count < 0:
        raise ConfigError("mercury.beneficial_owner_count must be non-negative")
    mercury = MercuryPacket(
        industry=_optional_str(mercury_raw, "industry"),
        business_description=_optional_str(mercury_raw, "business_description"),
        source_of_funds=_optional_str(mercury_raw, "source_of_funds"),
        planned_us_operations=_optional_str(mercury_raw, "planned_us_operations"),
        legal_address_operator_ready=_optional_bool(
            mercury_raw,
            "legal_address_operator_ready",
        ),
        physical_address_operator_ready=_optional_bool(
            mercury_raw,
            "physical_address_operator_ready",
        ),
        physical_address_kind=physical_kind,
        physical_address_verification_path=_optional_str(
            mercury_raw,
            "physical_address_verification_path",
        ),
        formation_doc_matches_legal_name=_optional_bool(
            mercury_raw,
            "formation_doc_matches_legal_name",
        ),
        owners_25_percent_plus_confirmed=_optional_bool(
            mercury_raw,
            "owners_25_percent_plus_confirmed",
        ),
        control_person_confirmed=_optional_bool(mercury_raw, "control_person_confirmed"),
        beneficial_owner_count=owner_count,
        prohibited_business_reviewed=_optional_bool(mercury_raw, "prohibited_business_reviewed"),
    )

    mn_assessment = _optional_str(
        minnesota_raw,
        "operator_transacting_business_assessment",
        default="unknown",
    ).lower()
    if mn_assessment not in MN_ASSESSMENTS:
        raise ConfigError(
            "minnesota.operator_transacting_business_assessment must be unknown, yes, or no"
        )
    filing_method = _optional_str(minnesota_raw, "filing_method", default="online").lower()
    if filing_method not in MN_FILING_METHODS:
        raise ConfigError("minnesota.filing_method must be mail, online, or in_person")
    minnesota = MinnesotaPacket(
        operator_transacting_business_assessment=mn_assessment,
        sos_forms_reviewed=_optional_bool(minnesota_raw, "sos_forms_reviewed"),
        statute_322c_reviewed=_optional_bool(minnesota_raw, "statute_322c_reviewed"),
        name_availability_checked=_optional_bool(minnesota_raw, "name_availability_checked"),
        registered_agent_ready=_optional_bool(minnesota_raw, "registered_agent_ready"),
        registered_office_ready=_optional_bool(minnesota_raw, "registered_office_ready"),
        principal_place_of_business_ready=_optional_bool(
            minnesota_raw,
            "principal_place_of_business_ready",
        ),
        home_office_address_ready=_optional_bool(minnesota_raw, "home_office_address_ready"),
        official_notice_email_ready=_optional_bool(
            minnesota_raw,
            "official_notice_email_ready",
        ),
        authorized_signer_ready=_optional_bool(minnesota_raw, "authorized_signer_ready"),
        professional_firm=_optional_bool(minnesota_raw, "professional_firm"),
        professional_firm_attachment_ready=_optional_bool(
            minnesota_raw,
            "professional_firm_attachment_ready",
        ),
        filing_method=filing_method,
    )

    review_status = _optional_str(
        agreement_raw,
        "legal_review_status",
        default="not_started",
    ).lower()
    if review_status not in OPERATING_REVIEW_STATUSES:
        raise ConfigError(
            "operating_agreement.legal_review_status must be not_started, "
            "operator_draft, counsel_reviewed, or executed"
        )
    agreement = OperatingAgreementPacket(
        draft_path=_optional_str(agreement_raw, "draft_path"),
        final_signed_path=_optional_str(agreement_raw, "final_signed_path"),
        legal_review_status=review_status,
        single_member_terms_recorded=_optional_bool(
            agreement_raw,
            "single_member_terms_recorded",
        ),
        management_structure_recorded=_optional_bool(
            agreement_raw,
            "management_structure_recorded",
        ),
        capital_contribution_recorded=_optional_bool(
            agreement_raw,
            "capital_contribution_recorded",
        ),
        distribution_policy_recorded=_optional_bool(
            agreement_raw,
            "distribution_policy_recorded",
        ),
        transferability_recorded=_optional_bool(agreement_raw, "transferability_recorded"),
        amendment_process_recorded=_optional_bool(
            agreement_raw,
            "amendment_process_recorded",
        ),
        records_storage_path=_optional_str(agreement_raw, "records_storage_path"),
        bank_copy_ready=_optional_bool(agreement_raw, "bank_copy_ready"),
    )

    return RemainingStepsConfig(
        schema_version=version,
        entity=entity,
        mercury=mercury,
        minnesota=minnesota,
        operating_agreement=agreement,
    )


def _redact_path(path_text: str) -> str:
    if not path_text:
        return ""
    expanded = Path(path_text).expanduser()
    try:
        return f"~/{expanded.relative_to(Path.home())}"
    except ValueError:
        return str(expanded)


def _path_exists(path_text: str) -> bool:
    return bool(path_text.strip()) and Path(path_text).expanduser().exists()


def _check(
    *,
    check_id: str,
    label: str,
    ok: bool,
    source: str,
    evidence: str = "",
    fail_status: str = "missing",
) -> dict[str, str]:
    return {
        "id": check_id,
        "label": label,
        "status": "pass" if ok else fail_status,
        "evidence": evidence,
        "source": source,
    }


def _path_check(
    *,
    check_id: str,
    label: str,
    path_text: str,
    source: str,
) -> dict[str, str]:
    redacted = _redact_path(path_text)
    if not path_text.strip():
        evidence = "not configured"
    else:
        evidence = f"{redacted} ({'exists' if _path_exists(path_text) else 'missing'})"
    return _check(
        check_id=check_id,
        label=label,
        ok=_path_exists(path_text),
        evidence=evidence,
        source=source,
    )


def _section_status(checks: Sequence[Mapping[str, str]]) -> str:
    statuses = {check.get("status", "") for check in checks}
    if "missing" in statuses or "blocked" in statuses:
        return "blocked"
    if "operator_review" in statuses:
        return "operator_review"
    return "ready_for_operator"


def _fee_for_filing_method(method: str) -> int:
    if method == "mail":
        return 185
    return 205


def build_mercury_section(config: RemainingStepsConfig) -> dict[str, Any]:
    entity = config.entity
    mercury = config.mercury
    physical_kind_accepted = mercury.physical_address_kind in ACCEPTED_PHYSICAL_ADDRESS_KINDS
    checks = [
        _check(
            check_id="mercury_us_company",
            label="Company is formed in the United States or a US territory",
            ok=entity.home_jurisdiction in US_JURISDICTIONS,
            evidence=f"home_jurisdiction={entity.home_jurisdiction}",
            source=MERCURY_ELIGIBILITY_URL,
        ),
        _check(
            check_id="mercury_legal_name",
            label="Business legal name is available for operator entry",
            ok=bool(entity.legal_name.strip()),
            evidence="configured",
            source=MERCURY_ELIGIBILITY_URL,
        ),
        _path_check(
            check_id="mercury_formation_document",
            label="State-filed formation document is staged",
            path_text=entity.formation_document_path,
            source=MERCURY_DOCUMENTS_URL,
        ),
        _path_check(
            check_id="mercury_irs_confirmation_letter",
            label="IRS confirmation letter document is staged",
            path_text=entity.irs_confirmation_letter_path,
            source=MERCURY_DOCUMENTS_URL,
        ),
        _check(
            check_id="mercury_formation_name_match",
            label="Operator confirmed formation document matches legal name",
            ok=mercury.formation_doc_matches_legal_name,
            source=MERCURY_DOCUMENTS_URL,
        ),
        _check(
            check_id="mercury_industry",
            label="Industry is prepared for operator entry",
            ok=bool(mercury.industry),
            evidence=mercury.industry,
            source=MERCURY_ELIGIBILITY_URL,
        ),
        _check(
            check_id="mercury_business_description",
            label="Business description is prepared for operator entry",
            ok=bool(mercury.business_description),
            evidence=mercury.business_description,
            source=MERCURY_ELIGIBILITY_URL,
        ),
        _check(
            check_id="mercury_source_of_funds",
            label="Source-of-funds description is prepared",
            ok=bool(mercury.source_of_funds),
            evidence=mercury.source_of_funds,
            source=MERCURY_ELIGIBILITY_URL,
        ),
        _check(
            check_id="mercury_us_operations",
            label="Current or planned US operations are described",
            ok=bool(mercury.planned_us_operations),
            evidence=mercury.planned_us_operations,
            source=MERCURY_ELIGIBILITY_URL,
        ),
        _check(
            check_id="mercury_legal_address_ready",
            label="Operator has a US physical legal address ready",
            ok=mercury.legal_address_operator_ready,
            source=MERCURY_ADDRESS_URL,
        ),
        _check(
            check_id="mercury_physical_address_kind",
            label="Physical operating address kind is acceptable",
            ok=physical_kind_accepted,
            evidence=mercury.physical_address_kind,
            source=MERCURY_ADDRESS_URL,
            fail_status="blocked"
            if mercury.physical_address_kind in REJECTED_PHYSICAL_ADDRESS_KINDS
            else "missing",
        ),
        _check(
            check_id="mercury_physical_address_ready",
            label="Operator has a physical operating address ready",
            ok=mercury.physical_address_operator_ready,
            source=MERCURY_ADDRESS_URL,
        ),
        _path_check(
            check_id="mercury_address_verification",
            label="Address verification document is staged if Mercury asks",
            path_text=mercury.physical_address_verification_path,
            source=MERCURY_ADDRESS_URL,
        ),
        _check(
            check_id="mercury_beneficial_owner_count",
            label="At least one individual beneficial owner/control path is identified",
            ok=mercury.beneficial_owner_count >= 1,
            evidence=f"count={mercury.beneficial_owner_count}",
            source=MERCURY_ELIGIBILITY_URL,
        ),
        _check(
            check_id="mercury_25_percent_owners",
            label="Operator confirmed all 25 percent or greater owners are accounted for",
            ok=mercury.owners_25_percent_plus_confirmed,
            source=MERCURY_ELIGIBILITY_URL,
        ),
        _check(
            check_id="mercury_control_person",
            label="Operator confirmed the control person is ready",
            ok=mercury.control_person_confirmed,
            source=MERCURY_ELIGIBILITY_URL,
        ),
        _check(
            check_id="mercury_prohibited_business_review",
            label="Operator reviewed Mercury eligibility/prohibited-business constraints",
            ok=mercury.prohibited_business_reviewed,
            source=MERCURY_ELIGIBILITY_URL,
        ),
    ]
    return {
        "status": _section_status(checks),
        "provider": "Mercury",
        "source_verified_on": VERIFIED_ON,
        "checks": checks,
        "operator_next_action": (
            "Use the staged packet only in the Mercury portal; this runner does not submit "
            "applications or identity material."
        ),
    }


def build_minnesota_section(config: RemainingStepsConfig) -> dict[str, Any]:
    mn = config.minnesota
    assessment = mn.operator_transacting_business_assessment
    checks: list[dict[str, str]] = [
        _check(
            check_id="mn_operator_assessment",
            label="Operator-owned transacting-business assessment is recorded",
            ok=assessment != "unknown",
            evidence=assessment,
            source=MN_322C_0802_URL,
            fail_status="operator_review",
        ),
        _check(
            check_id="mn_sos_forms_reviewed",
            label="Operator reviewed Minnesota SOS foreign LLC form packet",
            ok=mn.sos_forms_reviewed,
            source=MN_FOREIGN_LLC_FORMS_URL,
        ),
        _check(
            check_id="mn_statutes_reviewed",
            label="Operator reviewed Minnesota Chapter 322C certificate authority sources",
            ok=mn.statute_322c_reviewed,
            source=MN_322C_0802_URL,
        ),
    ]

    if assessment == "yes":
        checks.extend(
            [
                _check(
                    check_id="mn_name_availability",
                    label="Name availability or alternate Minnesota name check is complete",
                    ok=mn.name_availability_checked,
                    source=MN_CERTIFICATE_FORM_URL,
                ),
                _check(
                    check_id="mn_registered_agent",
                    label="Minnesota registered agent is ready",
                    ok=mn.registered_agent_ready,
                    source=MN_CERTIFICATE_FORM_URL,
                ),
                _check(
                    check_id="mn_registered_office",
                    label="Minnesota registered office street address is ready",
                    ok=mn.registered_office_ready,
                    source=MN_CERTIFICATE_FORM_URL,
                ),
                _check(
                    check_id="mn_principal_place",
                    label="Principal place of business street address is ready",
                    ok=mn.principal_place_of_business_ready,
                    source=MN_CERTIFICATE_FORM_URL,
                ),
                _check(
                    check_id="mn_home_office_address",
                    label="Home-jurisdiction office address is ready if required there",
                    ok=mn.home_office_address_ready,
                    source=MN_CERTIFICATE_FORM_URL,
                ),
                _check(
                    check_id="mn_official_notice_email",
                    label="Official-notice email decision is ready",
                    ok=mn.official_notice_email_ready,
                    source=MN_CERTIFICATE_FORM_URL,
                ),
                _check(
                    check_id="mn_authorized_signer",
                    label="Authorized signer is identified for operator-only signature",
                    ok=mn.authorized_signer_ready,
                    source=MN_CERTIFICATE_FORM_URL,
                ),
                _check(
                    check_id="mn_professional_attachment",
                    label="Professional firm attachment is ready when applicable",
                    ok=(not mn.professional_firm) or mn.professional_firm_attachment_ready,
                    evidence=f"professional_firm={mn.professional_firm}",
                    source=MN_CERTIFICATE_FORM_URL,
                ),
            ]
        )
        next_action = (
            "If operator/counsel confirms Minnesota registration is required, use the "
            "official SOS form path and pay the current fee directly with the state."
        )
    elif assessment == "no":
        next_action = (
            "Retain the operator/counsel basis for no Minnesota Certificate of Authority "
            "and revisit before starting Minnesota operations."
        )
    else:
        next_action = (
            "Operator/counsel must decide whether planned activity is transacting business "
            "in Minnesota before any filing or no-filing decision."
        )

    return {
        "status": _section_status(checks),
        "source_verified_on": VERIFIED_ON,
        "assessment": assessment,
        "filing_method": mn.filing_method,
        "current_fee_usd": _fee_for_filing_method(mn.filing_method),
        "checks": checks,
        "operator_next_action": next_action,
        "legal_boundary": (
            "This packet does not decide whether Minnesota foreign registration is "
            "required. That decision remains operator/counsel owned."
        ),
    }


def build_operating_agreement_section(config: RemainingStepsConfig) -> dict[str, Any]:
    agreement = config.operating_agreement
    has_draft_or_final = _path_exists(agreement.draft_path) or _path_exists(
        agreement.final_signed_path
    )
    review_complete = agreement.legal_review_status in {"counsel_reviewed", "executed"}
    checks = [
        _check(
            check_id="oa_draft_or_final",
            label="Operating agreement draft or executed copy is staged",
            ok=has_draft_or_final,
            evidence=(
                f"draft={_redact_path(agreement.draft_path) or 'not configured'}, "
                f"final={_redact_path(agreement.final_signed_path) or 'not configured'}"
            ),
            source=WY_OPERATING_AGREEMENT_URL,
        ),
        _check(
            check_id="oa_review_status",
            label="Operator recorded legal review/execution status",
            ok=agreement.legal_review_status != "not_started",
            evidence=agreement.legal_review_status,
            source=WY_OPERATING_AGREEMENT_URL,
            fail_status="operator_review",
        ),
        _check(
            check_id="oa_review_complete",
            label="Counsel review or execution is complete before bank use",
            ok=review_complete,
            evidence=agreement.legal_review_status,
            source=WY_OPERATING_AGREEMENT_URL,
            fail_status="operator_review",
        ),
        _check(
            check_id="oa_single_member_terms",
            label="Single-member formation/effect terms are recorded",
            ok=agreement.single_member_terms_recorded,
            source=WY_OPERATING_AGREEMENT_URL,
        ),
        _check(
            check_id="oa_management_structure",
            label="Management rights and duties are recorded",
            ok=agreement.management_structure_recorded,
            source=WY_OPERATING_AGREEMENT_URL,
        ),
        _check(
            check_id="oa_capital_contribution",
            label="Initial contribution/asset records are recorded",
            ok=agreement.capital_contribution_recorded,
            source=WY_OPERATING_AGREEMENT_URL,
        ),
        _check(
            check_id="oa_distribution_policy",
            label="Distribution policy is recorded",
            ok=agreement.distribution_policy_recorded,
            source=WY_OPERATING_AGREEMENT_URL,
        ),
        _check(
            check_id="oa_transferability",
            label="Transferability of membership interests is recorded",
            ok=agreement.transferability_recorded,
            source=WY_OPERATING_AGREEMENT_URL,
        ),
        _check(
            check_id="oa_amendment_process",
            label="Amendment process is recorded",
            ok=agreement.amendment_process_recorded,
            source=WY_OPERATING_AGREEMENT_URL,
        ),
        _check(
            check_id="oa_records_storage",
            label="Records storage location is configured",
            ok=bool(agreement.records_storage_path.strip()),
            evidence=_redact_path(agreement.records_storage_path),
            source=WY_OPERATING_AGREEMENT_URL,
        ),
        _check(
            check_id="oa_bank_copy_ready",
            label="Operator has a bank-provider copy ready",
            ok=agreement.bank_copy_ready,
            source=MERCURY_DOCUMENTS_URL,
        ),
    ]
    return {
        "status": _section_status(checks),
        "source_verified_on": VERIFIED_ON,
        "checks": checks,
        "operator_next_action": (
            "Have the operator/counsel finalize and execute the agreement before using "
            "it for bank onboarding."
        ),
    }


def official_sources() -> dict[str, Any]:
    return {
        "verified_on": VERIFIED_ON,
        "mercury": {
            "eligibility": MERCURY_ELIGIBILITY_URL,
            "documents": MERCURY_DOCUMENTS_URL,
            "address_requirements": MERCURY_ADDRESS_URL,
        },
        "minnesota": {
            "foreign_llc_forms": MN_FOREIGN_LLC_FORMS_URL,
            "fee_schedule": MN_FOREIGN_LLC_FEE_URL,
            "certificate_form": MN_CERTIFICATE_FORM_URL,
            "application_statute": MN_322C_0802_URL,
            "filing_statute": MN_322C_0804_URL,
            "failure_to_have_certificate_statute": MN_322C_0808_URL,
        },
        "wyoming": {"operating_agreement_statute": WY_OPERATING_AGREEMENT_URL},
    }


def build_report(config: RemainingStepsConfig, *, now: datetime | None = None) -> dict[str, Any]:
    created_at = (now or datetime.now(UTC)).isoformat().replace("+00:00", "Z")
    sections = {
        "mercury": build_mercury_section(config),
        "minnesota": build_minnesota_section(config),
        "operating_agreement": build_operating_agreement_section(config),
    }
    statuses = {section["status"] for section in sections.values()}
    if "blocked" in statuses:
        overall = "blocked"
    elif "operator_review" in statuses:
        overall = "operator_review"
    else:
        overall = "ready_for_operator"
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "created_at": created_at,
        "mode": "dry_run_operator_packet",
        "overall_status": overall,
        "entity": {
            "legal_name": config.entity.legal_name,
            "home_jurisdiction": config.entity.home_jurisdiction,
        },
        "sections": sections,
        "official_sources": official_sources(),
        "operator_gates": list(OPERATOR_GATES),
        "safety": {
            "local_only": True,
            "no_provider_or_government_calls": True,
            "no_secret_values_in_output": True,
            "not_legal_tax_or_financial_advice": True,
        },
        "config_snapshot": {
            "entity": _redacted_mapping(asdict(config.entity)),
            "mercury": _redacted_mapping(asdict(config.mercury)),
            "minnesota": _redacted_mapping(asdict(config.minnesota)),
            "operating_agreement": _redacted_mapping(asdict(config.operating_agreement)),
        },
    }


def _redacted_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, nested in value.items():
        if isinstance(nested, Mapping):
            redacted[key] = _redacted_mapping(nested)
        elif isinstance(nested, str) and (key.endswith("_path") or key.endswith("_storage_path")):
            redacted[key] = _redact_path(nested)
        else:
            redacted[key] = nested
    return redacted


def render_operator_note(report: Mapping[str, Any]) -> str:
    lines = [
        "# Wyoming LLC Remaining Steps Operator Packet",
        "",
        "## Boundary",
        "",
        "- Dry-run local packet only; no filings, applications, account creation, "
        "payments, signatures, or external API calls.",
        "- Not legal, tax, financial, or banking advice.",
        "- Sensitive identifiers belong only in the operator's private vault/pass store.",
        "",
        "## Summary",
        "",
        f"- Overall status: `{report.get('overall_status', 'unknown')}`",
    ]
    sections = report.get("sections", {})
    if isinstance(sections, Mapping):
        for name, section in sections.items():
            if isinstance(section, Mapping):
                lines.append(f"- {name}: `{section.get('status', 'unknown')}`")

    for title, key in (
        ("Mercury", "mercury"),
        ("Minnesota Foreign LLC Check", "minnesota"),
        ("Operating Agreement", "operating_agreement"),
    ):
        lines.extend(["", f"## {title}", ""])
        section = sections.get(key, {}) if isinstance(sections, Mapping) else {}
        if isinstance(section, Mapping):
            next_action = section.get("operator_next_action")
            if isinstance(next_action, str) and next_action:
                lines.append(f"- Next: {next_action}")
            checks = section.get("checks", [])
            if isinstance(checks, list):
                for check in checks:
                    if not isinstance(check, Mapping):
                        continue
                    status = check.get("status", "unknown")
                    label = check.get("label", "check")
                    evidence = check.get("evidence", "")
                    suffix = f" ({evidence})" if evidence else ""
                    lines.append(f"- `{status}` {label}{suffix}")

    lines.extend(["", "## Official Sources", ""])
    sources = report.get("official_sources", {})
    if isinstance(sources, Mapping):
        lines.append(f"- Verified on: `{sources.get('verified_on', 'unknown')}`")
        for group_name, group in sources.items():
            if group_name == "verified_on" or not isinstance(group, Mapping):
                continue
            for source_name, url in group.items():
                lines.append(f"- {group_name}.{source_name}: {url}")

    lines.extend(["", "## Operator Gates", ""])
    for gate in report.get("operator_gates", []):
        lines.append(f"- {gate}")
    return "\n".join(lines).rstrip() + "\n"


def write_example_config(path: Path, *, force: bool) -> None:
    if path.exists() and not force:
        raise ConfigError(f"refusing to overwrite existing config: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(EXAMPLE_CONFIG, encoding="utf-8")


def write_records(
    *,
    output_dir: Path,
    report: Mapping[str, Any],
    write_vault_note: bool,
    vault_note: Path,
) -> dict[str, str]:
    run_dir = output_dir / datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    run_dir.mkdir(parents=True, exist_ok=True)
    report_path = run_dir / "remaining-steps-report.json"
    note_path = run_dir / "operator-packet.md"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    note = render_operator_note(report)
    note_path.write_text(note, encoding="utf-8")
    paths = {
        "output_dir": str(run_dir),
        "report_path": str(report_path),
        "note_path": str(note_path),
    }
    if write_vault_note:
        vault_note.parent.mkdir(parents=True, exist_ok=True)
        vault_note.write_text(note, encoding="utf-8")
        paths["vault_note_path"] = str(vault_note)
    return paths


def _args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--write-vault-note", action="store_true")
    parser.add_argument("--vault-note", type=Path, default=DEFAULT_VAULT_NOTE)
    parser.add_argument("--write-example-config", type=Path)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _args(argv)
    try:
        if args.write_example_config:
            path = args.write_example_config.expanduser()
            write_example_config(path, force=args.force)
            print(json.dumps({"example_config": str(path)}, sort_keys=True))
            return 0

        config = load_config(args.config.expanduser())
        report = build_report(config)
        paths = write_records(
            output_dir=args.output_dir.expanduser(),
            report=report,
            write_vault_note=args.write_vault_note,
            vault_note=args.vault_note.expanduser(),
        )
    except ConfigError as exc:
        print(f"wyoming-llc-remaining-steps: {exc}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                **paths,
                "mode": report["mode"],
                "overall_status": report["overall_status"],
                "source_verified_on": VERIFIED_ON,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
