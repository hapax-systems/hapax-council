"""USDC-on-Base receive-rail via Base RPC ``eth_getLogs`` polling.

Polls the public Base mainnet RPC (default ``https://mainnet.base.org``)
for inbound USDC ERC-20 ``Transfer`` events to the operator's
configured wallet address. Each new event emits one
:class:`agents.operator_awareness.state.PaymentEvent` with
``rail="x402_usdc_base"``.

cc-task: ``x402-payment-rail-evm-stablecoin-receive``. Decision-B
substrate per ``docs/research/2026-05-01-x402-spec-current-research.md``;
gated on operator-side legal entity (Wyoming SMLLC) +
explicit Decision-B election. Until ``HAPAX_X402_OPERATOR_WALLET`` is
populated the receiver constructs in ``disabled`` state and the
poll loop is a no-op.

READ-ONLY contract:

    This module never signs, sends, or initiates an outbound EVM
    transaction. There is no method named ``send``, ``transfer``,
    ``withdraw``, ``payout``, ``initiate``, or ``remit``. No private
    key is read from disk or env at any point. The Base RPC is hit
    only with ``eth_chainId`` +
    ``eth_getBlockByNumber("finalized", false)`` + ``eth_getLogs`` — never
    ``eth_sendTransaction`` / ``eth_sendRawTransaction`` /
    ``personal_sign`` / ``eth_signTypedData`` / ``eth_call`` against
    state-mutating selectors. The contract test in
    ``tests/payment_processors/test_read_only_contract.py`` enforces
    the verb-naming subset by source scan; the runtime contract test
    here pins the JSON-RPC method allowlist.

Constitutional posture:

* `corporate_boundary` (weight 90): the Base RPC endpoint is hit
  directly from the host — never through an employer VPN/proxy. The
  default ``https://mainnet.base.org`` is the public Coinbase-run
  endpoint; operators may override via ``HAPAX_BASE_RPC_URL`` to
  another public RPC (Alchemy, QuickNode, Llamanodes) but MUST NOT
  point it at an employer-internal endpoint.
* `single_user`: the wallet address is one operator-owned address.
  Multi-operator wallets are out-of-scope and would require axiom
  precedent review.
* `interpersonal_transparency`: ``from`` addresses on the bus are
  on-chain pseudonyms (no PII); we hash them only for log-line
  truncation, not consent-gating.

Idempotency: each Transfer event has a stable ``(tx_hash, log_index)``
    tuple. We persist the cursor to a JSON state file so re-poll
overlap is harmless and a daemon restart resumes from the last seen
event.

Credential bootstrap:

    pass insert evm/operator-wallet-address  # one-time, address only
    # (NOT a private key — operator's hardware wallet is the sole
    # signer; this rail never sees the key.)
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from prometheus_client import Counter

from agents.operator_awareness.state import PaymentEvent
from agents.payment_processors.event_log import DEFAULT_PAYMENT_LOG_PATH, append_event
from agents.payment_processors.resource_receipts import (
    commit_prepared_resource_receipt,
    prepare_payment_event_resource_receipt,
    record_external_api_poll_receipt,
    resource_receipt_recovery_guidance,
)

log = logging.getLogger(__name__)

# Base mainnet USDC contract — official Circle deployment, eip155:8453.
# Verifiable at https://basescan.org/token/0x833589fcd6edb6e08f4c7c32d4f71b54bda02913
BASE_USDC_CONTRACT_ADDRESS: str = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
BASE_CHAIN_ID: int = 8453

# keccak256("Transfer(address,address,uint256)") — standard ERC-20.
ERC20_TRANSFER_TOPIC: str = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# USDC has 6 decimal places (vs ETH's 18).
USDC_DECIMALS: int = 6

DEFAULT_BASE_RPC_URL: str = "https://mainnet.base.org"
DEFAULT_POLL_INTERVAL_S: float = 30.0
DEFAULT_BLOCK_LOOKBACK: int = 1000  # first cursor-zero bootstrap only
MAX_ETH_GETLOGS_BLOCK_SPAN: int = 2000

OPERATOR_WALLET_ENV: str = "HAPAX_X402_OPERATOR_WALLET"
BASE_RPC_URL_ENV: str = "HAPAX_BASE_RPC_URL"
CURSOR_PATH_ENV: str = "HAPAX_X402_USDC_CURSOR_PATH"
PAYMENT_LOG_ENV: str = "HAPAX_MONETIZATION_LOG_PATH"
DEFAULT_CURSOR_PATH: Path = Path.home() / ".cache/hapax/x402-usdc-cursor.json"
CURSOR_SCHEMA_VERSION: int = 2

# Allowed JSON-RPC methods. Any deviation is a contract violation —
# the runtime test pins this set.
READ_ONLY_RPC_METHODS: frozenset[str] = frozenset(
    {
        "eth_getBlockByNumber",
        "eth_getLogs",
        "eth_chainId",
    }
)

# Per-rail metric — same naming convention as the other receive rails.
usdc_receipts_total: Counter = Counter(
    "hapax_leverage_x402_usdc_receipts_total",
    "USDC-on-Base receipts ingested via Base RPC eth_getLogs polling.",
    ["rail"],
)

# x402-USDC-Base rail label. Distinct from "lightning" / "nostr_zap" /
# "liberapay" so the aggregator can route per-rail.
RAIL_LABEL: str = "x402_usdc_base"


@dataclass(frozen=True)
class TransferReceipt:
    """One USDC ``Transfer`` event projected from an ``eth_getLogs`` row.

    Pure dataclass — no behaviour. The receiver maps these into
    :class:`PaymentEvent` instances at emission time. Kept separate
    so the parsing logic is unit-testable without the PaymentEvent's
    pydantic constructor.
    """

    tx_hash: str
    log_index: int
    block_number: int
    block_hash: str
    transaction_index: int
    from_address: str
    to_address: str
    amount_atomic: int

    @property
    def amount_usdc(self) -> Decimal:
        """Render the amount in USDC (1 USDC = 10^6 atomic units)."""

        return Decimal(self.amount_atomic) / Decimal(10**USDC_DECIMALS)


@dataclass(frozen=True)
class _FinalizedBlock:
    number: int
    block_hash: str


_HEX_FIELD_RE = re.compile(r"^0x[0-9a-fA-F]+$")
_HEX_QUANTITY_RE = re.compile(r"^0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)$")


def _normalise_address(value: str) -> str:
    """Return a 0x-prefixed lowercased 40-hex-char address.

    Mirrors the EIP-55 normalisation we accept — input may be
    checksummed-mixed-case or all-lower; output is always all-lower
    for set-membership comparison.
    """

    if not isinstance(value, str) or not value.startswith("0x") or len(value) != 42:
        raise ValueError(f"invalid Ethereum address: {value!r}")
    if not _is_hex_field(value, hex_chars=40):
        raise ValueError(f"address {value!r} is not 40 hex chars")
    return value.lower()


def _is_hex_field(value: Any, *, hex_chars: int) -> bool:
    if not isinstance(value, str):
        return False
    if len(value) != 2 + hex_chars:
        return False
    return bool(_HEX_FIELD_RE.fullmatch(value))


def _is_hex_quantity(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return bool(_HEX_QUANTITY_RE.fullmatch(value))


def _quantity_to_int(value: Any) -> int | None:
    if not _is_hex_quantity(value):
        return None
    return int(str(value), 16)


def _normalise_32_byte_hex(value: Any) -> str | None:
    if not _is_hex_field(value, hex_chars=64):
        return None
    return str(value).lower()


def _topic_to_address(value: Any) -> str | None:
    if not _is_hex_field(value, hex_chars=64):
        return None
    text = str(value).lower()
    if text[2:26] != "0" * 24:
        return None
    try:
        return _normalise_address("0x" + text[-40:])
    except ValueError:
        return None


def _parse_finalized_block(value: Any) -> _FinalizedBlock | None:
    if not isinstance(value, dict):
        return None
    number = _quantity_to_int(value.get("number"))
    block_hash = _normalise_32_byte_hex(value.get("hash"))
    if number is None or block_hash is None:
        return None
    return _FinalizedBlock(number=number, block_hash=block_hash)


def _topic_address(value: str) -> str:
    """Format an address as a 32-byte left-padded ``0x``-prefixed topic.

    ``eth_getLogs`` topic filters compare 32-byte slots, not 20-byte
    addresses. The Transfer event's indexed ``to`` topic is the
    address left-padded with 12 zero bytes.
    """

    addr = _normalise_address(value)
    return "0x" + ("0" * 24) + addr[2:]


def _parse_log_to_receipt(log: dict[str, Any]) -> TransferReceipt | None:
    """Project one ``eth_getLogs`` row into a :class:`TransferReceipt`.

    Returns ``None`` when the row is malformed (wrong contract,
    missing fields, bad hex, wrong topic count, wrong topic/hash
    width). ``eth_getLogs`` is a public, untrusted JSON-RPC response
    — defensive parsing is the contract.
    """

    try:
        emitting_address = _normalise_address(str(log["address"]))
        if emitting_address != _normalise_address(BASE_USDC_CONTRACT_ADDRESS):
            return None

        topics = log.get("topics") or []
        if not isinstance(topics, list) or len(topics) != 3:
            return None
        if not _is_hex_field(topics[0], hex_chars=64):
            return None
        if str(topics[0]).lower() != ERC20_TRANSFER_TOPIC:
            return None
        # Transfer(address indexed from, address indexed to, uint256 value)
        # topic[0] = event sig; topic[1] = from (padded); topic[2] = to (padded)
        from_addr = _topic_to_address(topics[1])
        to_addr = _topic_to_address(topics[2])
        if from_addr is None or to_addr is None:
            return None

        # data is hex-encoded uint256 amount (66 chars including 0x).
        data_hex = log.get("data")
        if not _is_hex_field(data_hex, hex_chars=64):
            return None
        amount = int(str(data_hex), 16)

        tx_hash = _normalise_32_byte_hex(log.get("transactionHash"))
        block_hash = _normalise_32_byte_hex(log.get("blockHash"))
        log_index = _quantity_to_int(log.get("logIndex"))
        block_number = _quantity_to_int(log.get("blockNumber"))
        transaction_index = _quantity_to_int(log.get("transactionIndex"))
        if (
            tx_hash is None
            or block_hash is None
            or log_index is None
            or block_number is None
            or transaction_index is None
        ):
            return None
        if log.get("removed") is not False:
            return None
    except (KeyError, ValueError, TypeError):
        log_logger = logging.getLogger(__name__)
        log_logger.debug("malformed eth_getLogs row skipped", exc_info=True)
        return None

    return TransferReceipt(
        tx_hash=tx_hash,
        log_index=log_index,
        block_number=block_number,
        block_hash=block_hash,
        transaction_index=transaction_index,
        from_address=from_addr,
        to_address=to_addr,
        amount_atomic=amount,
    )


def _filter_receipt(
    receipt: TransferReceipt,
    *,
    min_amount_atomic: int,
    max_amount_atomic: int | None,
    expected_to: str,
) -> bool:
    """Apply per-amount + destination-address gates.

    The destination check is defence-in-depth — ``eth_getLogs`` is
    already filtered server-side by the topic, but a malicious or
    malformed RPC response could include other addresses. Better to
    drop than to credit.
    """

    if receipt.to_address != expected_to:
        return False
    if receipt.amount_atomic < min_amount_atomic:
        return False
    return not (max_amount_atomic is not None and receipt.amount_atomic > max_amount_atomic)


@dataclass
class _Cursor:
    """Persistent cursor: highest seen ``(tx_hash, log_index)`` plus
    last-polled block number for backstop rewind.

    Stored at ``$HAPAX_X402_USDC_CURSOR_PATH`` (default
    ``~/.cache/hapax/x402-usdc-cursor.json``) so a daemon restart
    resumes from the last seen event without re-emitting the entire
    history.
    """

    last_block: int = 0
    seen_keys: set[tuple[str, int]] = None  # type: ignore[assignment]
    cursor_schema: int = CURSOR_SCHEMA_VERSION
    chain_id: int = BASE_CHAIN_ID
    contract_address: str = BASE_USDC_CONTRACT_ADDRESS.lower()
    operator_wallet: str | None = None
    load_error: str | None = None

    def __post_init__(self) -> None:
        if self.seen_keys is None:
            self.seen_keys = set()
        if self.contract_address:
            self.contract_address = _normalise_address(self.contract_address)
        if self.operator_wallet:
            self.operator_wallet = _normalise_address(self.operator_wallet)


def _load_cursor(
    path: Path,
    *,
    operator_wallet: str | None = None,
    chain_id: int = BASE_CHAIN_ID,
    contract_address: str = BASE_USDC_CONTRACT_ADDRESS,
) -> _Cursor:
    expected_contract = _normalise_address(contract_address)
    expected_wallet = _normalise_address(operator_wallet) if operator_wallet else None
    empty = _Cursor(
        chain_id=chain_id,
        contract_address=expected_contract,
        operator_wallet=expected_wallet,
    )
    if not path.exists():
        return empty
    try:
        import json

        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return replace(empty, load_error="cursor JSON is not an object")
        if raw.get("cursor_schema") != CURSOR_SCHEMA_VERSION:
            return replace(
                empty,
                load_error=(
                    f"legacy or incompatible cursor schema {raw.get('cursor_schema')!r}; "
                    f"expected {CURSOR_SCHEMA_VERSION}"
                ),
            )
        raw_chain_id = raw.get("chain_id")
        if raw_chain_id != chain_id:
            return replace(
                empty,
                load_error=f"incompatible cursor chain_id {raw_chain_id!r}; expected {chain_id}",
            )
        try:
            raw_contract = _normalise_address(raw.get("contract_address"))
        except (TypeError, ValueError) as exc:
            return replace(empty, load_error=f"incompatible cursor contract address: {exc}")
        if raw_contract != expected_contract:
            return replace(
                empty,
                load_error=(
                    f"incompatible cursor contract {raw_contract}; expected {expected_contract}"
                ),
            )
        raw_wallet = raw.get("operator_wallet")
        try:
            loaded_wallet = _normalise_address(raw_wallet) if raw_wallet else None
        except (TypeError, ValueError) as exc:
            return replace(empty, load_error=f"incompatible cursor operator wallet: {exc}")
        if expected_wallet is not None and loaded_wallet != expected_wallet:
            return replace(
                empty,
                load_error=(
                    f"incompatible cursor operator wallet {loaded_wallet}; "
                    f"expected {expected_wallet}"
                ),
            )
        last_block_raw = raw.get("last_block")
        if not isinstance(last_block_raw, int) or last_block_raw < 0:
            return replace(
                empty,
                load_error=f"incompatible cursor last_block {last_block_raw!r}",
            )
        seen = _parse_cursor_seen_keys(raw.get("seen_keys", []))
        if seen is None:
            return replace(empty, load_error="incompatible cursor seen_keys")
        return _Cursor(
            last_block=last_block_raw,
            seen_keys=seen,
            chain_id=chain_id,
            contract_address=expected_contract,
            operator_wallet=loaded_wallet,
        )
    except (OSError, ValueError, TypeError):
        log.warning("cursor at %s unreadable; holding without reset", path, exc_info=True)
        return replace(empty, load_error="corrupt or unreadable cursor JSON")


def _save_cursor(path: Path, cursor: _Cursor) -> None:
    """Persist cursor via tmp + rename for atomic update."""

    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "cursor_schema": CURSOR_SCHEMA_VERSION,
        "rail": RAIL_LABEL,
        "chain_id": cursor.chain_id,
        "chain_id_hex": hex(cursor.chain_id),
        "contract_address": cursor.contract_address,
        "operator_wallet": cursor.operator_wallet,
        "last_block": cursor.last_block,
        "seen_keys": sorted(cursor.seen_keys),
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(path)


def _parse_cursor_seen_keys(value: object) -> set[tuple[str, int]] | None:
    if not isinstance(value, list):
        return None
    seen: set[tuple[str, int]] = set()
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            return None
        tx_hash = _normalise_32_byte_hex(item[0])
        if tx_hash is None:
            return None
        log_index = item[1]
        if not isinstance(log_index, int) or log_index < 0:
            return None
        seen.add((tx_hash, log_index))
    return seen


class USDCReceiver:
    """USDC-on-Base inbound-only receive rail.

    Constructs in ``disabled`` state when ``HAPAX_X402_OPERATOR_WALLET``
    is empty — :meth:`poll_once` is a no-op. Once the operator has
    bootstrapped the wallet address (via ``pass insert
    evm/operator-wallet-address`` flowed into the env via
    ``hapax-secrets.service``), the rail becomes active and the daemon
    can run :meth:`run_forever` without any further wiring.

    No private key is ever read. The receiver only knows the
    operator's *public* address — the operator's hardware wallet (or
    other off-host signer) is the sole signer. This rail is
    structurally incapable of initiating outbound value.
    """

    def __init__(
        self,
        *,
        operator_wallet: str | None = None,
        rpc_url: str | None = None,
        rpc_caller: Any = None,
        cursor_path: Path | None = None,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        min_amount_atomic: int = 1,
        max_amount_atomic: int | None = None,
        block_lookback: int = DEFAULT_BLOCK_LOOKBACK,
    ) -> None:
        operator_wallet = (
            operator_wallet
            if operator_wallet is not None
            else os.environ.get(OPERATOR_WALLET_ENV, "")
        )
        if operator_wallet:
            self._operator_wallet: str | None = _normalise_address(operator_wallet)
            self._to_topic: str | None = _topic_address(self._operator_wallet)
        else:
            self._operator_wallet = None
            self._to_topic = None

        self._rpc_url = rpc_url or os.environ.get(BASE_RPC_URL_ENV, DEFAULT_BASE_RPC_URL)
        self._rpc_caller = rpc_caller  # injected for tests; lazy-built otherwise
        self._cursor_path = cursor_path or Path(
            os.environ.get(CURSOR_PATH_ENV, str(DEFAULT_CURSOR_PATH))
        )
        self._poll_interval_s = max(1.0, poll_interval_s)
        self._min_amount_atomic = min_amount_atomic
        self._max_amount_atomic = max_amount_atomic
        self._block_lookback = max(1, block_lookback)
        self._stop_evt = threading.Event()
        self._cursor: _Cursor = _load_cursor(
            self._cursor_path,
            operator_wallet=self._operator_wallet,
            chain_id=BASE_CHAIN_ID,
            contract_address=BASE_USDC_CONTRACT_ADDRESS,
        )

    # ── Public API ────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        """True iff an operator wallet is configured.

        When False, :meth:`poll_once` is a no-op and the daemon emits
        no events. The bootstrap path is operator-action: configure
        ``pass evm/operator-wallet-address`` and restart the daemon.
        """

        return self._operator_wallet is not None

    def poll_once(self, *, now: datetime | None = None) -> int:
        """Run one poll tick. Returns the count of new events emitted."""

        if not self.enabled:
            return 0
        if self._cursor.load_error is not None:
            log.warning(
                "x402 USDC cursor hold at %s: %s; %s",
                self._cursor_path,
                self._cursor.load_error,
                self._cursor_recovery_action(),
            )
            return 0
        if (
            record_external_api_poll_receipt(
                rail=RAIL_LABEL,
                endpoint="Base RPC eth_chainId+eth_getBlockByNumber(finalized)+eth_getLogs",
                downstream_action="USDCReceiver.poll_once._call_rpc",
            )
            is None
        ):
            log.warning(
                "usdc poll blocked: external API poll resource receipt missing; %s",
                _resource_receipt_recovery_action(),
            )
            return 0

        try:
            chain_id_raw = self._call_rpc("eth_chainId", [])
        except Exception:  # noqa: BLE001
            log.warning("eth_chainId failed; skipping tick", exc_info=True)
            return 0
        chain_id = _quantity_to_int(chain_id_raw)
        if chain_id != BASE_CHAIN_ID:
            log.warning(
                "eth_chainId returned %r, expected Base chain %s (%s); "
                "skipping tick without advancing cursor %s; %s",
                chain_id_raw,
                BASE_CHAIN_ID,
                hex(BASE_CHAIN_ID),
                self._cursor_path,
                self._cursor_recovery_action(),
            )
            return 0

        try:
            finalized_raw = self._call_rpc("eth_getBlockByNumber", ["finalized", False])
        except Exception:  # noqa: BLE001
            log.warning("eth_getBlockByNumber(finalized) failed; skipping tick", exc_info=True)
            return 0
        finalized = _parse_finalized_block(finalized_raw)
        if finalized is None:
            log.warning(
                "eth_getBlockByNumber(finalized) returned invalid finalized head; "
                "skipping tick without advancing cursor %s",
                self._cursor_path,
            )
            return 0

        from_block = self._next_from_block(finalized.number)
        if from_block > finalized.number:
            if self._cursor.last_block > finalized.number:
                log.warning(
                    "x402 USDC cursor %s last_block=%s is ahead of finalized Base head %s; "
                    "holding without advancing cursor; %s",
                    self._cursor_path,
                    self._cursor.last_block,
                    finalized.number,
                    self._cursor_recovery_action(),
                )
            return 0
        to_block = min(finalized.number, from_block + MAX_ETH_GETLOGS_BLOCK_SPAN - 1)

        try:
            logs_raw = self._call_rpc(
                "eth_getLogs",
                [
                    {
                        "fromBlock": hex(from_block),
                        "toBlock": hex(to_block),
                        "address": BASE_USDC_CONTRACT_ADDRESS,
                        "topics": [
                            ERC20_TRANSFER_TOPIC,
                            None,  # any from
                            self._to_topic,
                        ],
                    }
                ],
            )
        except Exception:  # noqa: BLE001
            log.warning("eth_getLogs failed; skipping tick", exc_info=True)
            return 0
        if not isinstance(logs_raw, list):
            log.warning(
                "eth_getLogs returned invalid top-level result type %s; "
                "skipping tick without advancing cursor %s",
                type(logs_raw).__name__,
                self._cursor_path,
            )
            return 0

        receipts = self._materialize_and_filter_logs(
            logs_raw,
            from_block=from_block,
            to_block=to_block,
            finalized=finalized,
        )
        if receipts is None:
            return 0

        emitted = 0
        highest_successful_block = self._cursor.last_block
        receipt_by_seen_key = {
            (receipt.tx_hash, receipt.log_index): receipt for receipt in receipts
        }
        for receipt in receipts:
            key = (receipt.tx_hash, receipt.log_index)
            if key in self._cursor.seen_keys:
                highest_successful_block = max(highest_successful_block, receipt.block_number)
                continue
            if not self._emit_payment_event(receipt, now=now):
                self._cursor.last_block = min(
                    highest_successful_block,
                    max(self._cursor.last_block, receipt.block_number - 1),
                )
                self._retain_seen_keys_needed_for_retry(receipt_by_seen_key)
                _save_cursor(self._cursor_path, self._cursor)
                return emitted
            self._cursor.seen_keys.add(key)
            highest_successful_block = max(highest_successful_block, receipt.block_number)
            emitted += 1

        self._cursor.last_block = to_block
        self._cursor.seen_keys.clear()
        _save_cursor(self._cursor_path, self._cursor)
        return emitted

    def run_forever(self) -> None:
        """Block + poll until SIGTERM/SIGINT.

        For systemd ``Type=simple`` units. Calls :meth:`poll_once` on
        a cadence of ``poll_interval_s`` (default 30 s). On any
        exception the loop logs and continues — a single bad tick
        must not crash the daemon.
        """

        import signal as _signal

        for sig in (_signal.SIGTERM, _signal.SIGINT):
            try:
                _signal.signal(sig, lambda *_: self._stop_evt.set())
            except ValueError:
                pass

        log.info(
            "x402 USDC receiver starting (rpc=%s, wallet=%s, enabled=%s)",
            self._rpc_url,
            "<configured>" if self._operator_wallet else "<missing>",
            self.enabled,
        )
        while not self._stop_evt.is_set():
            try:
                self.poll_once()
            except Exception:  # noqa: BLE001
                log.exception("usdc poll tick raised; continuing")
            self._stop_evt.wait(self._poll_interval_s)

    def stop(self) -> None:
        self._stop_evt.set()

    # ── Internals ─────────────────────────────────────────────────────

    def _materialize_and_filter_logs(
        self,
        logs_raw: list[Any],
        *,
        from_block: int,
        to_block: int,
        finalized: _FinalizedBlock,
    ) -> list[TransferReceipt] | None:
        assert self._operator_wallet is not None  # gated by self.enabled
        receipts_by_key: dict[tuple[str, int], TransferReceipt] = {}
        block_hash_by_number: dict[int, str] = {}
        receipts_by_block_log: dict[tuple[str, int], TransferReceipt] = {}
        tx_locations: dict[str, tuple[int, str, int]] = {}
        for index, row in enumerate(logs_raw):
            if not isinstance(row, dict):
                log.warning(
                    "eth_getLogs returned invalid row %s type %s; "
                    "skipping tick without advancing cursor %s",
                    index,
                    type(row).__name__,
                    self._cursor_path,
                )
                return None
            receipt = _parse_log_to_receipt(row)
            if receipt is None:
                log.warning(
                    "eth_getLogs returned malformed row %s; "
                    "skipping tick without advancing cursor %s",
                    index,
                    self._cursor_path,
                )
                return None
            if not from_block <= receipt.block_number <= to_block:
                log.warning(
                    "eth_getLogs returned row %s outside requested interval "
                    "[%s, %s]; skipping tick without advancing cursor %s",
                    index,
                    from_block,
                    to_block,
                    self._cursor_path,
                )
                return None
            if (
                receipt.block_number == finalized.number
                and receipt.block_hash != finalized.block_hash
            ):
                log.warning(
                    "eth_getLogs returned row %s with finalized block hash %s but "
                    "eth_getBlockByNumber(finalized) returned %s for block %s; "
                    "skipping tick without advancing cursor %s",
                    index,
                    receipt.block_hash,
                    finalized.block_hash,
                    finalized.number,
                    self._cursor_path,
                )
                return None
            prior_block_hash = block_hash_by_number.get(receipt.block_number)
            if prior_block_hash is not None and prior_block_hash != receipt.block_hash:
                log.warning(
                    "eth_getLogs returned multiple block hashes for block %s; "
                    "skipping tick without advancing cursor %s",
                    receipt.block_number,
                    self._cursor_path,
                )
                return None
            block_hash_by_number[receipt.block_number] = receipt.block_hash
            if receipt.to_address != self._operator_wallet:
                log.warning(
                    "eth_getLogs returned row %s outside requested destination topic; "
                    "skipping tick without advancing cursor %s",
                    index,
                    self._cursor_path,
                )
                return None
            key = (receipt.tx_hash, receipt.log_index)
            prior = receipts_by_key.get(key)
            if prior is not None:
                if _transfer_receipt_semantics(prior) == _transfer_receipt_semantics(receipt):
                    continue
                log.warning(
                    "eth_getLogs returned conflicting duplicate row %s for %s:%s; "
                    "skipping tick without advancing cursor %s",
                    index,
                    receipt.tx_hash,
                    receipt.log_index,
                    self._cursor_path,
                )
                return None
            block_log_key = (receipt.block_hash, receipt.log_index)
            prior_block_log = receipts_by_block_log.get(block_log_key)
            if prior_block_log is not None:
                if _transfer_receipt_semantics(prior_block_log) == _transfer_receipt_semantics(
                    receipt
                ):
                    continue
                log.warning(
                    "eth_getLogs returned conflicting semantic rows for block_hash/log_index "
                    "%s:%s; skipping tick without advancing cursor %s",
                    receipt.block_hash,
                    receipt.log_index,
                    self._cursor_path,
                )
                return None
            tx_location = (receipt.block_number, receipt.block_hash, receipt.transaction_index)
            prior_tx_location = tx_locations.get(receipt.tx_hash)
            if prior_tx_location is not None and prior_tx_location != tx_location:
                log.warning(
                    "eth_getLogs returned transaction hash %s at multiple locations; "
                    "skipping tick without advancing cursor %s",
                    receipt.tx_hash,
                    self._cursor_path,
                )
                return None
            tx_locations[receipt.tx_hash] = tx_location
            receipts_by_key[key] = receipt
            receipts_by_block_log[block_log_key] = receipt

        materialized = sorted(
            receipts_by_key.values(),
            key=lambda receipt: (
                receipt.block_number,
                receipt.transaction_index,
                receipt.log_index,
                receipt.tx_hash,
            ),
        )
        return [
            receipt
            for receipt in materialized
            if _filter_receipt(
                receipt,
                min_amount_atomic=self._min_amount_atomic,
                max_amount_atomic=self._max_amount_atomic,
                expected_to=self._operator_wallet,
            )
        ]

    def _next_from_block(self, finalized_number: int) -> int:
        if self._cursor.last_block <= 0:
            return max(0, finalized_number - self._block_lookback)
        return self._cursor.last_block + 1

    def _retain_seen_keys_needed_for_retry(
        self,
        receipt_by_seen_key: dict[tuple[str, int], TransferReceipt],
    ) -> None:
        self._cursor.seen_keys = {
            key
            for key in self._cursor.seen_keys
            if (receipt := receipt_by_seen_key.get(key)) is not None
            and receipt.block_number > self._cursor.last_block
        }

    def _emit_payment_event(self, receipt: TransferReceipt, *, now: datetime | None = None) -> bool:
        """Append one PaymentEvent to the canonical event log.

        ``rail`` carries the ``x402_usdc_base`` literal through the
        canonical :class:`PaymentEvent` model, so the event can be
        tailed and revalidated after append.
        """

        ts = now if now is not None else datetime.now(UTC)
        event = self._build_payment_event(receipt, ts)
        receipt_ref, resource_receipt = prepare_payment_event_resource_receipt(
            rail=RAIL_LABEL,
            external_id=event.external_id,
            event_kind="erc20_transfer",
            downstream_action="payment_event_log.append_event",
        )
        if commit_prepared_resource_receipt(resource_receipt) is None:
            log.warning(
                "usdc payment event blocked: resource receipt append failed; %s; %s",
                _resource_receipt_recovery_action(),
                self._payment_event_retry_action(receipt),
            )
            return False
        event = event.model_copy(update={"resource_receipt_ref": receipt_ref})
        try:
            event_appended = append_event(event)
        except Exception:  # noqa: BLE001
            log.warning(
                "usdc payment event append raised; %s",
                self._payment_event_retry_action(receipt),
                exc_info=True,
            )
            return False
        if not event_appended:
            log.warning(
                "usdc payment event append failed; %s",
                self._payment_event_retry_action(receipt),
            )
            return False
        usdc_receipts_total.labels(rail=RAIL_LABEL).inc()
        return True

    def _build_payment_event(self, receipt: TransferReceipt, ts: datetime) -> PaymentEvent:
        """Construct a PaymentEvent for emission.

        Isolated so tests can drive the receiver's projection logic
        without an event-log side effect.
        """

        return PaymentEvent(
            timestamp=ts,
            rail=RAIL_LABEL,
            amount_usd=float(receipt.amount_usdc),
            amount_sats=None,
            amount_eur=None,
            sender_excerpt=f"from={receipt.from_address[:10]}...",
            external_id=f"{receipt.tx_hash}:{receipt.log_index}",
        )

    def _call_rpc(self, method: str, params: list[Any]) -> Any:
        """Single-method JSON-RPC call against the Base endpoint.

        Restricted to the methods in :data:`READ_ONLY_RPC_METHODS`;
        any deviation is a contract violation. Tests pin this
        allowlist by source-scan + by injection of a recording
        transport that asserts every call's method.
        """

        if method not in READ_ONLY_RPC_METHODS:
            raise RuntimeError(
                f"x402 USDC receiver attempted forbidden RPC method {method!r}; "
                f"allowed methods: {sorted(READ_ONLY_RPC_METHODS)}"
            )
        caller = self._rpc_caller or _default_rpc_caller(self._rpc_url)
        return caller(method, params)

    def _payment_event_retry_action(self, receipt: TransferReceipt) -> str:
        configured_payment_log = os.environ.get(PAYMENT_LOG_ENV)
        payment_log = (
            Path(configured_payment_log) if configured_payment_log else DEFAULT_PAYMENT_LOG_PATH
        )
        resolved_payment_log = payment_log.expanduser().resolve(strict=False)
        event_id = f"{receipt.tx_hash}:{receipt.log_index}"
        return (
            f"cursor {self._cursor_path} remains before x402 USDC event {event_id} "
            f"at block {receipt.block_number}; cursor preservation is intentional; "
            f"check {PAYMENT_LOG_ENV}={configured_payment_log or '<unset>'}, "
            f"payment-event log {payment_log}, resolved path {resolved_payment_log}, "
            "/dev/shm availability, and payment-event log directory/file permissions; "
            "fix the event log, then retry by waiting for the next poll or restarting "
            "the daemon; do not manually advance the cursor"
        )

    def _cursor_recovery_action(self) -> str:
        configured_cursor = os.environ.get(CURSOR_PATH_ENV)
        resolved_cursor = self._cursor_path.expanduser().resolve(strict=False)
        wallet = self._operator_wallet or "<missing>"
        contract = _normalise_address(BASE_USDC_CONTRACT_ADDRESS)
        return (
            f"check {CURSOR_PATH_ENV}={configured_cursor or '<unset>'}, cursor file "
            f"{self._cursor_path}, resolved path {resolved_cursor}, expected chain "
            f"{BASE_CHAIN_ID} ({hex(BASE_CHAIN_ID)}), USDC contract {contract}, "
            f"operator wallet {wallet}, cursor file directory/file permissions, and "
            "payment-event/resource-receipt log continuity; preserve the cursor, "
            "seen_keys, payment events, and resource receipts for audit, then quarantine "
            "or migrate only after reconciling the last processed x402 USDC event"
        )


def _default_rpc_caller(rpc_url: str) -> Any:
    """Construct the default JSON-RPC caller using ``requests``.

    Lazy import so unit tests that inject a stub never have to load
    ``requests``. Production use needs ``requests`` installed.
    """

    def _call(method: str, params: list[Any]) -> Any:
        import requests

        payload = {
            "jsonrpc": "2.0",
            "id": int(time.time() * 1000),
            "method": method,
            "params": params,
        }
        response = requests.post(rpc_url, json=payload, timeout=30.0)
        response.raise_for_status()
        body = response.json()
        if "error" in body:
            raise RuntimeError(f"RPC error: {body['error']}")
        return body.get("result")

    return _call


def _resource_receipt_recovery_action() -> str:
    return resource_receipt_recovery_guidance()


def _transfer_receipt_semantics(receipt: TransferReceipt) -> tuple[object, ...]:
    return (
        receipt.tx_hash,
        receipt.log_index,
        receipt.block_number,
        receipt.block_hash,
        receipt.transaction_index,
        receipt.from_address,
        receipt.to_address,
        receipt.amount_atomic,
    )


def iter_receipts_for_test(
    logs: Iterable[dict[str, Any]],
    *,
    operator_wallet: str,
    min_amount_atomic: int = 1,
    max_amount_atomic: int | None = None,
) -> Iterator[TransferReceipt]:
    """Pure helper for tests: project + filter a list of log rows.

    Keeps the parse + filter logic accessible without instantiating
    the full :class:`USDCReceiver` (which loads cursor state from
    disk).
    """

    expected_to = _normalise_address(operator_wallet)
    for row in logs:
        receipt = _parse_log_to_receipt(row)
        if receipt is None:
            continue
        if _filter_receipt(
            receipt,
            min_amount_atomic=min_amount_atomic,
            max_amount_atomic=max_amount_atomic,
            expected_to=expected_to,
        ):
            yield receipt


__all__ = [
    "BASE_RPC_URL_ENV",
    "BASE_CHAIN_ID",
    "BASE_USDC_CONTRACT_ADDRESS",
    "CURSOR_SCHEMA_VERSION",
    "CURSOR_PATH_ENV",
    "DEFAULT_BASE_RPC_URL",
    "DEFAULT_BLOCK_LOOKBACK",
    "DEFAULT_CURSOR_PATH",
    "DEFAULT_POLL_INTERVAL_S",
    "ERC20_TRANSFER_TOPIC",
    "MAX_ETH_GETLOGS_BLOCK_SPAN",
    "OPERATOR_WALLET_ENV",
    "RAIL_LABEL",
    "READ_ONLY_RPC_METHODS",
    "TransferReceipt",
    "USDCReceiver",
    "USDC_DECIMALS",
    "iter_receipts_for_test",
    "usdc_receipts_total",
]
