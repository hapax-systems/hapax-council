"""USDC-on-Base receive-rail tests.

Coverage:

1. Disabled-state — no wallet env → poll_once is no-op.
2. Address normalisation + topic encoding.
3. Log-row projection — happy path + malformed rows skipped.
4. Filter — min/max amount + destination-address gate.
5. Cursor — load from missing file, atomic write, dedup across ticks.
6. RPC method allowlist — only eth_blockNumber + eth_getLogs accepted;
   any other method (eth_sendTransaction etc.) raises.
7. Poll-once — drives parse + filter + cursor advance + emit count.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from agents.payment_processors.event_log import tail_events
from agents.payment_processors.resource_receipts import (
    MoneyRailReceiptOperation,
    receipt_reference,
    tail_resource_receipts,
)
from agents.payment_processors.usdc_receiver import (
    BASE_USDC_CONTRACT_ADDRESS,
    ERC20_TRANSFER_TOPIC,
    OPERATOR_WALLET_ENV,
    READ_ONLY_RPC_METHODS,
    TransferReceipt,
    USDCReceiver,
    _filter_receipt,
    _load_cursor,
    _normalise_address,
    _parse_log_to_receipt,
    _save_cursor,
    _topic_address,
    iter_receipts_for_test,
)

_OPERATOR_WALLET = "0x" + "ab" * 20  # 0xabab...ab; 40 hex chars
_OTHER_WALLET = "0x" + "cd" * 20


@pytest.fixture(autouse=True)
def resource_receipt_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    import agents.payment_processors.resource_receipts as resource_receipts

    log_path = tmp_path / "resource-receipts.jsonl"
    monkeypatch.setattr(
        resource_receipts,
        "DEFAULT_MONEY_RAIL_RESOURCE_RECEIPT_LOG_PATH",
        log_path,
    )
    return log_path


def _log_row(
    *,
    from_addr: str = "0x" + "11" * 20,
    to_addr: str = _OPERATOR_WALLET,
    amount_atomic: int = 1_000_000,  # 1 USDC = 10^6 atomic
    tx_hash: str = "0x" + "ee" * 32,
    log_index: int = 0,
    block_number: int = 12_345,
) -> dict:
    return {
        "address": BASE_USDC_CONTRACT_ADDRESS,
        "topics": [
            ERC20_TRANSFER_TOPIC,
            "0x" + ("0" * 24) + from_addr[2:],
            "0x" + ("0" * 24) + to_addr[2:],
        ],
        "data": "0x" + format(amount_atomic, "064x"),
        "transactionHash": tx_hash,
        "logIndex": hex(log_index),
        "blockNumber": hex(block_number),
    }


def _receipts_with_operation(log_path: Path, operation: MoneyRailReceiptOperation):
    return [
        receipt
        for receipt in tail_resource_receipts(log_path=log_path)
        if receipt.operation is operation
    ]


# ── address normalisation ─────────────────────────────────────────────


class TestAddressNormalisation:
    def test_lowercases_checksummed_input(self) -> None:
        assert _normalise_address("0x" + "AB" * 20) == "0x" + "ab" * 20

    def test_rejects_short_address(self) -> None:
        with pytest.raises(ValueError, match="invalid Ethereum address"):
            _normalise_address("0xshort")

    def test_rejects_no_prefix(self) -> None:
        with pytest.raises(ValueError, match="invalid Ethereum address"):
            _normalise_address("ab" * 20)

    def test_rejects_non_hex(self) -> None:
        with pytest.raises(ValueError, match="not 40 hex chars"):
            _normalise_address("0x" + "z" * 40)

    def test_topic_address_left_pads_to_32_bytes(self) -> None:
        topic = _topic_address(_OPERATOR_WALLET)
        assert topic.startswith("0x" + "0" * 24)
        assert topic.endswith("ab" * 20)
        assert len(topic) == 66  # 0x + 64 hex chars


# ── log row projection ───────────────────────────────────────────────


class TestParseLogToReceipt:
    def test_happy_path(self) -> None:
        row = _log_row(amount_atomic=2_500_000, log_index=3, block_number=999)
        receipt = _parse_log_to_receipt(row)
        assert receipt is not None
        assert receipt.amount_atomic == 2_500_000
        assert receipt.log_index == 3
        assert receipt.block_number == 999
        assert receipt.to_address == _OPERATOR_WALLET.lower()

    def test_amount_usdc_property_divides_by_10_to_6(self) -> None:
        row = _log_row(amount_atomic=12_345_678)  # 12.345678 USDC
        receipt = _parse_log_to_receipt(row)
        assert receipt is not None
        assert str(receipt.amount_usdc) == "12.345678"

    def test_skips_row_with_too_few_topics(self) -> None:
        row = _log_row()
        row["topics"] = [ERC20_TRANSFER_TOPIC]  # missing from + to
        assert _parse_log_to_receipt(row) is None

    def test_skips_row_with_missing_tx_hash(self) -> None:
        row = _log_row()
        del row["transactionHash"]
        assert _parse_log_to_receipt(row) is None

    def test_skips_row_with_bad_hex_amount(self) -> None:
        row = _log_row()
        row["data"] = "0xnot-hex"
        assert _parse_log_to_receipt(row) is None

    def test_handles_zero_amount(self) -> None:
        row = _log_row()
        row["data"] = "0x"
        receipt = _parse_log_to_receipt(row)
        assert receipt is not None
        assert receipt.amount_atomic == 0


# ── filter logic ─────────────────────────────────────────────────────


class TestFilterReceipt:
    def _r(self, *, amount: int = 1_000_000, to: str = _OPERATOR_WALLET) -> TransferReceipt:
        return TransferReceipt(
            tx_hash="0x" + "ee" * 32,
            log_index=0,
            block_number=1,
            from_address="0x" + "11" * 20,
            to_address=to.lower(),
            amount_atomic=amount,
        )

    def test_passes_when_to_matches_and_amount_in_range(self) -> None:
        assert _filter_receipt(
            self._r(),
            min_amount_atomic=1,
            max_amount_atomic=None,
            expected_to=_OPERATOR_WALLET.lower(),
        )

    def test_rejects_wrong_destination(self) -> None:
        assert not _filter_receipt(
            self._r(to=_OTHER_WALLET),
            min_amount_atomic=1,
            max_amount_atomic=None,
            expected_to=_OPERATOR_WALLET.lower(),
        )

    def test_rejects_below_min_amount(self) -> None:
        assert not _filter_receipt(
            self._r(amount=500_000),
            min_amount_atomic=1_000_000,
            max_amount_atomic=None,
            expected_to=_OPERATOR_WALLET.lower(),
        )

    def test_rejects_above_max_amount(self) -> None:
        assert not _filter_receipt(
            self._r(amount=10_000_000),
            min_amount_atomic=1,
            max_amount_atomic=5_000_000,
            expected_to=_OPERATOR_WALLET.lower(),
        )


# ── cursor persistence ──────────────────────────────────────────────


class TestCursor:
    def test_load_missing_file_returns_empty(self, tmp_path: Path) -> None:
        cursor = _load_cursor(tmp_path / "nonexistent.json")
        assert cursor.last_block == 0
        assert cursor.seen_keys == set()

    def test_save_then_load_roundtrip(self, tmp_path: Path) -> None:
        from agents.payment_processors.usdc_receiver import _Cursor

        target = tmp_path / "cursor.json"
        cursor = _Cursor(last_block=1234, seen_keys={("0xtx1", 0), ("0xtx2", 1)})
        _save_cursor(target, cursor)
        loaded = _load_cursor(target)
        assert loaded.last_block == 1234
        assert loaded.seen_keys == {("0xtx1", 0), ("0xtx2", 1)}

    def test_save_atomically_via_tmp_rename(self, tmp_path: Path) -> None:
        from agents.payment_processors.usdc_receiver import _Cursor

        target = tmp_path / "cursor.json"
        _save_cursor(target, _Cursor(last_block=1, seen_keys=set()))
        assert target.exists()
        assert not (tmp_path / "cursor.json.tmp").exists()

    def test_load_corrupt_file_resets(self, tmp_path: Path) -> None:
        target = tmp_path / "cursor.json"
        target.write_text("{not-json")
        cursor = _load_cursor(target)
        assert cursor.last_block == 0
        assert cursor.seen_keys == set()


# ── disabled state ──────────────────────────────────────────────────


class TestDisabledState:
    def test_no_wallet_env_means_disabled(self, monkeypatch) -> None:
        monkeypatch.delenv(OPERATOR_WALLET_ENV, raising=False)
        receiver = USDCReceiver()
        assert not receiver.enabled

    def test_disabled_poll_once_is_noop(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.delenv(OPERATOR_WALLET_ENV, raising=False)
        receiver = USDCReceiver(cursor_path=tmp_path / "cursor.json")
        assert receiver.poll_once() == 0
        # Cursor file MUST NOT be written when disabled — preserves
        # the "no wallet, no operation" invariant.
        assert not (tmp_path / "cursor.json").exists()

    def test_enabled_when_wallet_provided_explicitly(self, tmp_path: Path) -> None:
        receiver = USDCReceiver(
            operator_wallet=_OPERATOR_WALLET,
            cursor_path=tmp_path / "cursor.json",
        )
        assert receiver.enabled


# ── RPC method allowlist ────────────────────────────────────────────


class TestRpcAllowlist:
    def test_allowlist_excludes_state_mutating_methods(self) -> None:
        for forbidden in (
            "eth_sendTransaction",
            "eth_sendRawTransaction",
            "personal_sign",
            "eth_signTypedData_v4",
            "eth_call",  # may be safe but conservative — outside our needs
        ):
            assert forbidden not in READ_ONLY_RPC_METHODS

    def test_allowlist_includes_only_two_methods(self) -> None:
        assert frozenset({"eth_blockNumber", "eth_getLogs"}) == READ_ONLY_RPC_METHODS

    def test_call_rpc_with_forbidden_method_raises(self, tmp_path: Path) -> None:
        receiver = USDCReceiver(
            operator_wallet=_OPERATOR_WALLET,
            cursor_path=tmp_path / "cursor.json",
            rpc_caller=lambda m, p: None,  # no-op
        )
        with pytest.raises(RuntimeError, match="forbidden RPC method"):
            receiver._call_rpc("eth_sendTransaction", [])  # noqa: SLF001

    def test_call_rpc_with_allowed_method_dispatches(self, tmp_path: Path) -> None:
        called: list[tuple[str, list]] = []

        def _capture(method: str, params: list) -> str:
            called.append((method, params))
            return "0xresult"

        receiver = USDCReceiver(
            operator_wallet=_OPERATOR_WALLET,
            cursor_path=tmp_path / "cursor.json",
            rpc_caller=_capture,
        )
        assert receiver._call_rpc("eth_blockNumber", []) == "0xresult"  # noqa: SLF001
        assert called == [("eth_blockNumber", [])]


# ── poll_once integration ────────────────────────────────────────────


class TestPollOnce:
    def _make_caller(self, *, tip_block: int, logs: list[dict]):
        """Return a stub rpc_caller that scripts the two-call sequence."""

        calls: list[str] = []

        def _call(method: str, params: list) -> object:
            calls.append(method)
            if method == "eth_blockNumber":
                return hex(tip_block)
            if method == "eth_getLogs":
                return logs
            raise RuntimeError(f"unexpected method {method!r}")

        return _call, calls

    def test_records_poll_resource_receipt_before_rpc(
        self,
        monkeypatch,
        tmp_path: Path,
        resource_receipt_log: Path,
    ) -> None:
        caller, calls = self._make_caller(tip_block=1000, logs=[_log_row()])
        monkeypatch.setattr("agents.payment_processors.usdc_receiver.append_event", lambda e: True)

        receiver = USDCReceiver(
            operator_wallet=_OPERATOR_WALLET,
            cursor_path=tmp_path / "cursor.json",
            rpc_caller=caller,
        )

        assert receiver.poll_once() == 1
        assert calls == ["eth_blockNumber", "eth_getLogs"]
        receipts = tail_resource_receipts(log_path=resource_receipt_log)
        assert [receipt.operation for receipt in receipts] == [
            MoneyRailReceiptOperation.EXTERNAL_API_POLL,
            MoneyRailReceiptOperation.PAYMENT_EVENT_APPEND,
        ]
        poll_receipt = receipts[0]
        assert poll_receipt.rail == "x402_usdc_base"
        assert poll_receipt.downstream_action == "USDCReceiver.poll_once._call_rpc"
        assert "external_api:Base RPC eth_blockNumber+eth_getLogs" in (
            poll_receipt.resource_provenance
        )

    def test_missing_poll_resource_receipt_blocks_rpc_and_cursor(
        self,
        monkeypatch,
        tmp_path: Path,
    ) -> None:
        import agents.payment_processors.usdc_receiver as usdc_mod

        caller, calls = self._make_caller(tip_block=1000, logs=[_log_row()])
        monkeypatch.setattr(usdc_mod, "record_external_api_poll_receipt", lambda **_: None)

        cursor_path = tmp_path / "cursor.json"
        receiver = USDCReceiver(
            operator_wallet=_OPERATOR_WALLET,
            cursor_path=cursor_path,
            rpc_caller=caller,
        )

        assert receiver.poll_once() == 0
        assert calls == []
        assert not cursor_path.exists()

    def test_emits_one_event_per_new_log(self, monkeypatch, tmp_path: Path) -> None:
        caller, _ = self._make_caller(tip_block=1000, logs=[_log_row()])

        appended: list = []

        def _capture_append(event):
            appended.append(event)
            return True

        monkeypatch.setattr("agents.payment_processors.usdc_receiver.append_event", _capture_append)

        receiver = USDCReceiver(
            operator_wallet=_OPERATOR_WALLET,
            cursor_path=tmp_path / "cursor.json",
            rpc_caller=caller,
        )
        emitted = receiver.poll_once()
        assert emitted == 1
        assert len(appended) == 1
        evt = appended[0]
        assert evt.rail == "x402_usdc_base"
        assert evt.amount_usd == 1.0  # 1_000_000 atomic = 1 USDC
        assert evt.external_id is not None and ":0" in evt.external_id
        assert evt.resource_receipt_ref is not None

    def test_payment_event_receipt_binds_hashed_external_identity(
        self,
        monkeypatch,
        tmp_path: Path,
        resource_receipt_log: Path,
    ) -> None:
        row = _log_row(tx_hash="0x" + "ef" * 32, log_index=5)
        caller, _ = self._make_caller(tip_block=1000, logs=[row])

        appended: list = []

        def _capture_append(event):
            receipts = _receipts_with_operation(
                resource_receipt_log,
                MoneyRailReceiptOperation.PAYMENT_EVENT_APPEND,
            )
            assert len(receipts) == 1
            appended.append(event)
            return True

        monkeypatch.setattr("agents.payment_processors.usdc_receiver.append_event", _capture_append)

        receiver = USDCReceiver(
            operator_wallet=_OPERATOR_WALLET,
            cursor_path=tmp_path / "cursor.json",
            rpc_caller=caller,
        )

        assert receiver.poll_once() == 1
        receipts = _receipts_with_operation(
            resource_receipt_log,
            MoneyRailReceiptOperation.PAYMENT_EVENT_APPEND,
        )
        assert len(receipts) == 1
        receipt = receipts[0]
        assert receipt.rail == "x402_usdc_base"
        assert receipt.operation is MoneyRailReceiptOperation.PAYMENT_EVENT_APPEND
        assert receipt.event_kind == "erc20_transfer"
        assert receipt.external_id_sha256 is not None
        assert receipt.downstream_action == "payment_event_log.append_event"
        assert "route:agents.payment_processors.event_log" in receipt.route_provenance
        assert "resource:payment_event_log" in receipt.resource_provenance
        assert appended[0].resource_receipt_ref == receipt_reference(receipt)
        receipt_json = receipt.model_dump_json()
        assert appended[0].external_id not in receipt_json
        assert row["transactionHash"] not in receipt_json
        assert _OPERATOR_WALLET.lower() not in receipt_json
        assert row["topics"][1][-40:].lower() not in receipt_json

    def test_appends_canonical_event_that_tail_events_reloads(
        self,
        monkeypatch,
        tmp_path: Path,
    ) -> None:
        import agents.payment_processors.event_log as event_log_mod

        row = _log_row(tx_hash="0x" + "f1" * 32, log_index=9)
        caller, _ = self._make_caller(tip_block=1000, logs=[row])
        payment_log = tmp_path / "events.jsonl"

        monkeypatch.setattr(
            "agents.payment_processors.usdc_receiver.append_event",
            lambda event: event_log_mod.append_event(event, log_path=payment_log),
        )

        receiver = USDCReceiver(
            operator_wallet=_OPERATOR_WALLET,
            cursor_path=tmp_path / "cursor.json",
            rpc_caller=caller,
        )

        assert receiver.poll_once() == 1
        events = tail_events(log_path=payment_log)
        assert len(events) == 1
        event = events[0]
        assert event.rail == "x402_usdc_base"
        assert event.external_id == "0x" + "f1" * 32 + ":9"
        assert event.resource_receipt_ref is not None

    def test_dedup_across_ticks(
        self,
        monkeypatch,
        tmp_path: Path,
        resource_receipt_log: Path,
    ) -> None:
        same_log = _log_row(tx_hash="0x" + "aa" * 32, log_index=7)
        caller, _ = self._make_caller(tip_block=1000, logs=[same_log])
        monkeypatch.setattr("agents.payment_processors.usdc_receiver.append_event", lambda e: True)

        receiver = USDCReceiver(
            operator_wallet=_OPERATOR_WALLET,
            cursor_path=tmp_path / "cursor.json",
            rpc_caller=caller,
        )
        # First tick emits 1; second tick (same log returned) emits 0.
        assert receiver.poll_once() == 1
        assert receiver.poll_once() == 0
        assert (
            len(
                _receipts_with_operation(
                    resource_receipt_log,
                    MoneyRailReceiptOperation.PAYMENT_EVENT_APPEND,
                )
            )
            == 1
        )
        assert (
            len(
                _receipts_with_operation(
                    resource_receipt_log,
                    MoneyRailReceiptOperation.EXTERNAL_API_POLL,
                )
            )
            == 2
        )

    def test_filters_logs_to_other_addresses(self, monkeypatch, tmp_path: Path) -> None:
        # eth_getLogs server may return rows with the operator's
        # to-topic AND defensively-injected rows for other addresses
        # (defence-in-depth filter rejects those).
        wrong_to = _log_row(to_addr=_OTHER_WALLET, tx_hash="0x" + "bb" * 32)
        right_to = _log_row(to_addr=_OPERATOR_WALLET, tx_hash="0x" + "cc" * 32)
        caller, _ = self._make_caller(tip_block=1000, logs=[wrong_to, right_to])
        monkeypatch.setattr("agents.payment_processors.usdc_receiver.append_event", lambda e: True)

        receiver = USDCReceiver(
            operator_wallet=_OPERATOR_WALLET,
            cursor_path=tmp_path / "cursor.json",
            rpc_caller=caller,
        )
        assert receiver.poll_once() == 1

    def test_min_amount_filter_drops_dust(
        self,
        monkeypatch,
        tmp_path: Path,
        resource_receipt_log: Path,
    ) -> None:
        dust = _log_row(amount_atomic=100, tx_hash="0x" + "dd" * 32)  # 0.0001 USDC
        ok = _log_row(amount_atomic=5_000_000, tx_hash="0x" + "ee" * 32)
        caller, _ = self._make_caller(tip_block=1000, logs=[dust, ok])
        appended: list = []

        def _capture_append(event):
            appended.append(event)
            return True

        monkeypatch.setattr("agents.payment_processors.usdc_receiver.append_event", _capture_append)

        cursor_path = tmp_path / "cursor.json"
        receiver = USDCReceiver(
            operator_wallet=_OPERATOR_WALLET,
            cursor_path=cursor_path,
            rpc_caller=caller,
            min_amount_atomic=1_000_000,  # drop sub-1-USDC
        )
        assert receiver.poll_once() == 1
        assert [event.external_id for event in appended] == ["0x" + "ee" * 32 + ":0"]
        assert (
            len(
                _receipts_with_operation(
                    resource_receipt_log,
                    MoneyRailReceiptOperation.PAYMENT_EVENT_APPEND,
                )
            )
            == 1
        )
        loaded = json.loads(cursor_path.read_text())
        assert loaded["last_block"] == 1000
        assert loaded["seen_keys"] == [["0x" + "ee" * 32, 0]]

    def test_persists_cursor_after_tick(self, monkeypatch, tmp_path: Path) -> None:
        caller, _ = self._make_caller(tip_block=12345, logs=[_log_row()])
        monkeypatch.setattr("agents.payment_processors.usdc_receiver.append_event", lambda e: True)

        cursor_path = tmp_path / "cursor.json"
        receiver = USDCReceiver(
            operator_wallet=_OPERATOR_WALLET,
            cursor_path=cursor_path,
            rpc_caller=caller,
        )
        receiver.poll_once()
        assert cursor_path.exists()
        loaded = json.loads(cursor_path.read_text())
        assert loaded["last_block"] == 12345

    def test_receipt_append_failure_blocks_event_and_keeps_cursor_retryable(
        self,
        monkeypatch,
        tmp_path: Path,
        resource_receipt_log: Path,
    ) -> None:
        import agents.payment_processors.usdc_receiver as usdc_mod

        row = _log_row(tx_hash="0x" + "10" * 32, block_number=500)
        caller, _ = self._make_caller(tip_block=1000, logs=[row])
        appended: list = []
        original_commit = usdc_mod.commit_prepared_resource_receipt
        commit_attempts = 0

        def _flaky_commit(receipt):
            nonlocal commit_attempts
            commit_attempts += 1
            if commit_attempts == 1:
                return None
            return original_commit(receipt)

        def _capture_append(event):
            appended.append(event)
            return True

        monkeypatch.setattr(usdc_mod, "commit_prepared_resource_receipt", _flaky_commit)
        monkeypatch.setattr(usdc_mod, "append_event", _capture_append)

        cursor_path = tmp_path / "cursor.json"
        receiver = USDCReceiver(
            operator_wallet=_OPERATOR_WALLET,
            cursor_path=cursor_path,
            rpc_caller=caller,
        )

        assert receiver.poll_once() == 0
        assert appended == []
        assert [
            receipt.operation for receipt in tail_resource_receipts(log_path=resource_receipt_log)
        ] == [MoneyRailReceiptOperation.EXTERNAL_API_POLL]
        loaded = json.loads(cursor_path.read_text())
        assert loaded["last_block"] == 0
        assert loaded["seen_keys"] == []

        assert receiver.poll_once() == 1
        assert [event.external_id for event in appended] == ["0x" + "10" * 32 + ":0"]
        loaded = json.loads(cursor_path.read_text())
        assert loaded["last_block"] == 1000
        assert loaded["seen_keys"] == [["0x" + "10" * 32, 0]]

    def test_event_append_failure_preserves_receipt_and_keeps_cursor_retryable(
        self,
        caplog,
        monkeypatch,
        tmp_path: Path,
        resource_receipt_log: Path,
    ) -> None:
        row = _log_row(tx_hash="0x" + "20" * 32, block_number=500)
        caller, _ = self._make_caller(tip_block=1000, logs=[row])
        append_attempts = 0
        caplog.set_level(logging.WARNING, logger="agents.payment_processors.usdc_receiver")

        def _flaky_append(_event):
            nonlocal append_attempts
            append_attempts += 1
            return append_attempts > 1

        monkeypatch.setattr("agents.payment_processors.usdc_receiver.append_event", _flaky_append)

        cursor_path = tmp_path / "cursor.json"
        receiver = USDCReceiver(
            operator_wallet=_OPERATOR_WALLET,
            cursor_path=cursor_path,
            rpc_caller=caller,
        )

        assert receiver.poll_once() == 0
        assert [
            receipt.operation for receipt in tail_resource_receipts(log_path=resource_receipt_log)
        ] == [
            MoneyRailReceiptOperation.EXTERNAL_API_POLL,
            MoneyRailReceiptOperation.PAYMENT_EVENT_APPEND,
        ]
        loaded = json.loads(cursor_path.read_text())
        assert loaded["last_block"] == 0
        assert loaded["seen_keys"] == []
        assert str(cursor_path) in caplog.text
        assert "x402 USDC event " + "0x" + "20" * 32 + ":0" in caplog.text
        assert "fix payment-event log" in caplog.text
        assert "do not manually advance the cursor" in caplog.text

        assert receiver.poll_once() == 1
        assert (
            len(
                _receipts_with_operation(
                    resource_receipt_log,
                    MoneyRailReceiptOperation.PAYMENT_EVENT_APPEND,
                )
            )
            == 1
        )
        loaded = json.loads(cursor_path.read_text())
        assert loaded["last_block"] == 1000
        assert loaded["seen_keys"] == [["0x" + "20" * 32, 0]]

    def test_event_append_retry_reuses_preserved_receipt(
        self,
        monkeypatch,
        tmp_path: Path,
        resource_receipt_log: Path,
    ) -> None:
        import agents.payment_processors.usdc_receiver as usdc_mod

        row = _log_row(tx_hash="0x" + "30" * 32, block_number=500)
        caller, _ = self._make_caller(tip_block=1000, logs=[row])
        append_attempts = 0

        def _flaky_append(_event):
            nonlocal append_attempts
            append_attempts += 1
            return append_attempts > 1

        monkeypatch.setattr(usdc_mod, "append_event", _flaky_append)

        cursor_path = tmp_path / "cursor.json"
        receiver = USDCReceiver(
            operator_wallet=_OPERATOR_WALLET,
            cursor_path=cursor_path,
            rpc_caller=caller,
        )

        assert receiver.poll_once() == 0
        receipts_after_failure = _receipts_with_operation(
            resource_receipt_log,
            MoneyRailReceiptOperation.PAYMENT_EVENT_APPEND,
        )
        assert len(receipts_after_failure) == 1

        assert receiver.poll_once() == 1
        receipts_after_retry = _receipts_with_operation(
            resource_receipt_log,
            MoneyRailReceiptOperation.PAYMENT_EVENT_APPEND,
        )
        assert len(receipts_after_retry) == 1
        assert receipts_after_retry[0].receipt_id == receipts_after_failure[0].receipt_id
        assert (
            len(
                _receipts_with_operation(
                    resource_receipt_log,
                    MoneyRailReceiptOperation.EXTERNAL_API_POLL,
                )
            )
            == 2
        )

    def test_cursor_advances_only_to_success_before_failed_receipt(
        self,
        monkeypatch,
        tmp_path: Path,
    ) -> None:
        import agents.payment_processors.usdc_receiver as usdc_mod

        first = _log_row(tx_hash="0x" + "41" * 32, log_index=0, block_number=700)
        second = _log_row(tx_hash="0x" + "42" * 32, log_index=1, block_number=701)
        caller, _ = self._make_caller(tip_block=1000, logs=[first, second])
        appended: list = []
        original_commit = usdc_mod.commit_prepared_resource_receipt
        commit_attempts = 0

        def _fail_second_commit(receipt):
            nonlocal commit_attempts
            commit_attempts += 1
            if commit_attempts == 2:
                return None
            return original_commit(receipt)

        def _capture_append(event):
            appended.append(event)
            return True

        monkeypatch.setattr(usdc_mod, "commit_prepared_resource_receipt", _fail_second_commit)
        monkeypatch.setattr(usdc_mod, "append_event", _capture_append)

        cursor_path = tmp_path / "cursor.json"
        receiver = USDCReceiver(
            operator_wallet=_OPERATOR_WALLET,
            cursor_path=cursor_path,
            rpc_caller=caller,
        )

        assert receiver.poll_once() == 1
        loaded = json.loads(cursor_path.read_text())
        assert loaded["last_block"] == 700
        assert loaded["seen_keys"] == [["0x" + "41" * 32, 0]]
        assert [event.external_id for event in appended] == ["0x" + "41" * 32 + ":0"]

    def test_rpc_failure_returns_zero_no_crash(self, monkeypatch, tmp_path: Path) -> None:
        def _raises(method: str, params: list):
            raise RuntimeError("RPC unreachable")

        receiver = USDCReceiver(
            operator_wallet=_OPERATOR_WALLET,
            cursor_path=tmp_path / "cursor.json",
            rpc_caller=_raises,
        )
        assert receiver.poll_once() == 0


# ── pure helper for downstream tests ─────────────────────────────────


class TestIterReceiptsForTest:
    def test_projects_and_filters(self) -> None:
        logs = [
            _log_row(amount_atomic=500, tx_hash="0x" + "01" * 32),  # too small
            _log_row(amount_atomic=2_000_000, tx_hash="0x" + "02" * 32),
            _log_row(to_addr=_OTHER_WALLET, tx_hash="0x" + "03" * 32),  # wrong to
        ]
        out = list(
            iter_receipts_for_test(
                logs,
                operator_wallet=_OPERATOR_WALLET,
                min_amount_atomic=1_000,
            )
        )
        assert len(out) == 1
        assert out[0].tx_hash == "0x" + "02" * 32
