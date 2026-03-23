"""Contract tests: Schemathesis fuzzing of council logos API against OpenAPI spec.

Generates valid and edge-case inputs for every endpoint, verifying that:
- No endpoint returns 5xx on valid input
- Response status codes match declared OpenAPI responses
- Response content types match declared OpenAPI content types
- Response bodies conform to declared OpenAPI schemas

Run: uv run pytest -m contract tests/contract/
"""

from __future__ import annotations

import pytest

schemathesis = pytest.importorskip("schemathesis")

from logos.api.app import app  # noqa: E402

schema = schemathesis.openapi.from_asgi("/openapi.json", app)


@pytest.mark.contract
@schema.parametrize()
def test_council_api(case):
    case.call_and_validate()
