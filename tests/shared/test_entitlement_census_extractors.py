"""Spend-free readback payloads become bounded ledger quantities, never provider identities."""

from datetime import UTC, datetime

from shared.entitlement_census import EXTRACTORS

NOW = datetime(2026, 9, 28, tzinfo=UTC)


def test_kimi_usage_has_window_reset_and_unverified_booster_scale():
    payload = {
        "usage": {"limit": "100", "used": "5", "resetTime": "2026-10-01T00:00:00Z"},
        "limits": [
            {
                "window": {"duration": 300, "timeUnit": "TIME_UNIT_MINUTE"},
                "detail": {"limit": "100", "used": "23", "resetTime": "2026-09-28T02:00:00Z"},
            }
        ],
        "booster_wallet": {
            "id": "identity-must-not-leak",
            "balance": {"amount": "3200", "unit": "UNIT_CURRENCY"},
        },
    }
    extracted = EXTRACTORS["kimi_usages"](payload, NOW, "census:test")
    by_id = {m["capacity_id"]: m for m in extracted.measurements}
    assert by_id["kimi.subscription.weekly"]["quantity"] == 5.0
    assert by_id["kimi.subscription.five_hour"]["quantity"] == 23.0
    assert by_id["kimi.subscription.five_hour"]["resets_at"] == "2026-09-28T02:00:00Z"
    assert by_id["kimi.booster.balance"]["details"]["scale"] == "unverified"
    assert "identity-must-not-leak" not in str(extracted)


def test_glm_wall_has_named_window_and_reset():
    payload = {
        "data": {
            "level": "max",
            "limits": [
                {
                    "type": "TOKENS_LIMIT",
                    "unit": 6,
                    "number": 1,
                    "percentage": 100,
                    "nextResetTime": 1790480184984,
                },
            ],
        }
    }
    extracted = EXTRACTORS["glm_quota_limit"](payload, NOW, "census:test")
    assert extracted.measurements[0]["capacity_id"] == "glm.subscription.weekly"
    assert extracted.measurements[0]["quantity"] == 100.0
    assert extracted.measurements[0]["resets_at"] == "2026-09-27T03:36:24Z"


def test_unusable_quantities_are_omitted_not_zero():
    extracted = EXTRACTORS["kimi_usages"](
        {"usage": {"limit": "unknown", "used": "0"}}, NOW, "census:test"
    )
    assert extracted.measurements == []
