from shared.ward_publisher_schemas import (
    ChatSignalsSnapshot,
    ChatState,
    RecentImpingementEntry,
    RecentImpingements,
)


def test_recent_impingements_round_trip():
    r = RecentImpingements(
        generated_at=1000.0,
        entries=[RecentImpingementEntry(path="focus.narrow", value=0.82, family="focus")],
    )
    payload = r.model_dump_json()
    restored = RecentImpingements.model_validate_json(payload)
    assert restored == r


def test_chat_state_projection_from_snapshot():
    snap = ChatSignalsSnapshot(
        generated_at=1000.0,
        message_count_60s=12,
        unique_authors_60s=4,
    )
    state = ChatState(
        generated_at=snap.generated_at,
        total_messages=snap.message_count_60s,
        unique_authors=snap.unique_authors_60s,
    )
    assert state.total_messages == 12
    assert state.unique_authors == 4
