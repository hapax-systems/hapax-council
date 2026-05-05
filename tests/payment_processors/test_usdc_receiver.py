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
from pathlib import Path

import pytest

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

    def test_emits_one_event_per_new_log(self, monkeypatch, tmp_path: Path) -> None:
        caller, _ = self._make_caller(tip_block=1000, logs=[_log_row()])

        appended: list = []

        def _capture_append(event):
            appended.append(event)

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

    def test_dedup_across_ticks(self, monkeypatch, tmp_path: Path) -> None:
        same_log = _log_row(tx_hash="0x" + "aa" * 32, log_index=7)
        caller, _ = self._make_caller(tip_block=1000, logs=[same_log])
        monkeypatch.setattr("agents.payment_processors.usdc_receiver.append_event", lambda e: None)

        receiver = USDCReceiver(
            operator_wallet=_OPERATOR_WALLET,
            cursor_path=tmp_path / "cursor.json",
            rpc_caller=caller,
        )
        # First tick emits 1; second tick (same log returned) emits 0.
        assert receiver.poll_once() == 1
        assert receiver.poll_once() == 0

    def test_filters_logs_to_other_addresses(self, monkeypatch, tmp_path: Path) -> None:
        # eth_getLogs server may return rows with the operator's
        # to-topic AND defensively-injected rows for other addresses
        # (defence-in-depth filter rejects those).
        wrong_to = _log_row(to_addr=_OTHER_WALLET, tx_hash="0x" + "bb" * 32)
        right_to = _log_row(to_addr=_OPERATOR_WALLET, tx_hash="0x" + "cc" * 32)
        caller, _ = self._make_caller(tip_block=1000, logs=[wrong_to, right_to])
        monkeypatch.setattr("agents.payment_processors.usdc_receiver.append_event", lambda e: None)

        receiver = USDCReceiver(
            operator_wallet=_OPERATOR_WALLET,
            cursor_path=tmp_path / "cursor.json",
            rpc_caller=caller,
        )
        assert receiver.poll_once() == 1

    def test_min_amount_filter_drops_dust(self, monkeypatch, tmp_path: Path) -> None:
        dust = _log_row(amount_atomic=100, tx_hash="0x" + "dd" * 32)  # 0.0001 USDC
        ok = _log_row(amount_atomic=5_000_000, tx_hash="0x" + "ee" * 32)
        caller, _ = self._make_caller(tip_block=1000, logs=[dust, ok])
        monkeypatch.setattr("agents.payment_processors.usdc_receiver.append_event", lambda e: None)

        receiver = USDCReceiver(
            operator_wallet=_OPERATOR_WALLET,
            cursor_path=tmp_path / "cursor.json",
            rpc_caller=caller,
            min_amount_atomic=1_000_000,  # drop sub-1-USDC
        )
        assert receiver.poll_once() == 1

    def test_persists_cursor_after_tick(self, monkeypatch, tmp_path: Path) -> None:
        caller, _ = self._make_caller(tip_block=12345, logs=[_log_row()])
        monkeypatch.setattr("agents.payment_processors.usdc_receiver.append_event", lambda e: None)

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
