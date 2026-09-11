"""Consent management backed by the authoritative council registry."""

from shared.governance.consent import (
    REGISTERED_CHILD_PRINCIPALS,
    REGISTERED_PRINCIPALS,
    ConsentContract,
    ConsentRegistry,
    is_child_principal,
    load_contracts,
    resolve_contract_id,
    resolve_principal_id,
)
from shared.governance.consent import (
    parse_contract as _parse_contract,
)

__all__ = [
    "REGISTERED_CHILD_PRINCIPALS",
    "REGISTERED_PRINCIPALS",
    "ConsentContract",
    "ConsentRegistry",
    "is_child_principal",
    "load_contracts",
    "resolve_contract_id",
    "resolve_principal_id",
    "_parse_contract",
]
