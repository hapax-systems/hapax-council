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
    only with ``eth_getLogs`` + ``eth_blockNumber`` — never
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
tuple. We persist the cursor to a JSONL state file so re-poll
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
import threading
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from prometheus_client import Counter

from agents.operator_awareness.state import PaymentEvent
from agents.payment_processors.event_log import append_event

log = logging.getLogger(__name__)

# Base mainnet USDC contract — official Circle deployment, eip155:8453.
# Verifiable at https://basescan.org/token/0x833589fcd6edb6e08f4c7c32d4f71b54bda02913
BASE_USDC_CONTRACT_ADDRESS: str = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

# keccak256("Transfer(address,address,uint256)") — standard ERC-20.
ERC20_TRANSFER_TOPIC: str = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# USDC has 6 decimal places (vs ETH's 18).
USDC_DECIMALS: int = 6

DEFAULT_BASE_RPC_URL: str = "https://mainnet.base.org"
DEFAULT_POLL_INTERVAL_S: float = 30.0
DEFAULT_BLOCK_LOOKBACK: int = 1000  # ~30 min at 2s blocks; safe rewind on restart

OPERATOR_WALLET_ENV: str = "HAPAX_X402_OPERATOR_WALLET"
BASE_RPC_URL_ENV: str = "HAPAX_BASE_RPC_URL"
CURSOR_PATH_ENV: str = "HAPAX_X402_USDC_CURSOR_PATH"
DEFAULT_CURSOR_PATH: Path = Path.home() / ".cache/hapax/x402-usdc-cursor.json"

# Allowed JSON-RPC methods. Any deviation is a contract violation —
# the runtime test pins this set.
READ_ONLY_RPC_METHODS: frozenset[str] = frozenset(
    {
        "eth_blockNumber",
        "eth_getLogs",
    }
)

# Per-rail metric — same naming convention as the other receive rails.
usdc_receipts_total: Counter = Counter(
    "hapax_leverage_x402_usdc_receipts_total",
    "USDC-on-Base receipts ingested via Base RPC eth_getLogs polling.",
    ["rail"],
)

# x402-USDC-Base rail label. Distinct from "lightning" / "nostr_zap" /
# "liberapay" so the aggregator can route per-rail. The PaymentEvent
# model needs to learn this literal; substrate ships with the
# rail name pinned and the model migration is a follow-up.
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
    from_address: str
    to_address: str
    amount_atomic: int

    @property
    def amount_usdc(self) -> Decimal:
        """Render the amount in USDC (1 USDC = 10^6 atomic units)."""

        return Decimal(self.amount_atomic) / Decimal(10**USDC_DECIMALS)


def _normalise_address(value: str) -> str:
    """Return a 0x-prefixed lowercased 40-hex-char address.

    Mirrors the EIP-55 normalisation we accept — input may be
    checksummed-mixed-case or all-lower; output is always all-lower
    for set-membership comparison.
    """

    if not value or not value.startswith("0x") or len(value) != 42:
        raise ValueError(f"invalid Ethereum address: {value!r}")
    try:
        int(value[2:], 16)
    except ValueError as exc:
        raise ValueError(f"address {value!r} is not 40 hex chars") from exc
    return value.lower()


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

    Returns ``None`` when the row is malformed (missing topics, bad
    hex, wrong topic count). ``eth_getLogs`` is a public, untrusted
    JSON-RPC response — defensive parsing is the contract.
    """

    try:
        topics = log.get("topics") or []
        if len(topics) < 3:
            return None
        # Transfer(address indexed from, address indexed to, uint256 value)
        # topic[0] = event sig; topic[1] = from (padded); topic[2] = to (padded)
        from_padded = str(topics[1])
        to_padded = str(topics[2])
        from_addr = "0x" + from_padded[-40:]
        to_addr = "0x" + to_padded[-40:]

        # data is hex-encoded uint256 amount (66 chars including 0x).
        data_hex = log.get("data") or "0x"
        amount = int(str(data_hex), 16) if data_hex != "0x" else 0

        tx_hash = str(log["transactionHash"])
        log_index = int(str(log["logIndex"]), 16)
        block_number = int(str(log["blockNumber"]), 16)
    except (KeyError, ValueError, TypeError):
        log_logger = logging.getLogger(__name__)
        log_logger.debug("malformed eth_getLogs row skipped", exc_info=True)
        return None

    return TransferReceipt(
        tx_hash=tx_hash,
        log_index=log_index,
        block_number=block_number,
        from_address=from_addr.lower(),
        to_address=to_addr.lower(),
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

    def __post_init__(self) -> None:
        if self.seen_keys is None:
            self.seen_keys = set()


def _load_cursor(path: Path) -> _Cursor:
    if not path.exists():
        return _Cursor()
    try:
        import json

        raw = json.loads(path.read_text(encoding="utf-8"))
        seen = {(str(t[0]), int(t[1])) for t in raw.get("seen_keys", [])}
        return _Cursor(last_block=int(raw.get("last_block", 0)), seen_keys=seen)
    except (OSError, ValueError, TypeError):
        log.warning("cursor at %s unreadable; resetting", path, exc_info=True)
        return _Cursor()


def _save_cursor(path: Path, cursor: _Cursor) -> None:
    """Persist cursor via tmp + rename for atomic update."""

    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "last_block": cursor.last_block,
        "seen_keys": sorted(cursor.seen_keys),
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(path)


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
        self._cursor: _Cursor = _load_cursor(self._cursor_path)

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

        try:
            tip_block = self._call_rpc("eth_blockNumber", [])
            tip_int = int(str(tip_block), 16)
        except Exception:  # noqa: BLE001
            log.warning("eth_blockNumber failed; skipping tick", exc_info=True)
            return 0

        from_block = max(
            self._cursor.last_block + 1,
            tip_int - self._block_lookback,
        )
        if from_block > tip_int:
            return 0

        try:
            logs_raw = self._call_rpc(
                "eth_getLogs",
                [
                    {
                        "fromBlock": hex(from_block),
                        "toBlock": hex(tip_int),
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

        emitted = 0
        for receipt in self._parse_and_filter(logs_raw):
            key = (receipt.tx_hash, receipt.log_index)
            if key in self._cursor.seen_keys:
                continue
            self._cursor.seen_keys.add(key)
            self._emit_payment_event(receipt, now=now)
            emitted += 1

        self._cursor.last_block = tip_int
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

    def _parse_and_filter(self, logs_raw: Any) -> Iterator[TransferReceipt]:
        if not isinstance(logs_raw, list):
            return
        assert self._operator_wallet is not None  # gated by self.enabled
        for row in logs_raw:
            if not isinstance(row, dict):
                continue
            receipt = _parse_log_to_receipt(row)
            if receipt is None:
                continue
            if not _filter_receipt(
                receipt,
                min_amount_atomic=self._min_amount_atomic,
                max_amount_atomic=self._max_amount_atomic,
                expected_to=self._operator_wallet,
            ):
                continue
            yield receipt

    def _emit_payment_event(self, receipt: TransferReceipt, *, now: datetime | None = None) -> None:
        """Append one PaymentEvent to the canonical event log.

        ``rail`` carries the ``x402_usdc_base`` literal; the
        :class:`PaymentEvent` Literal type may need extending in a
        follow-up — substrate ships with the rail tag pinned.
        """

        ts = now if now is not None else datetime.now(UTC)
        # PaymentEvent's Literal currently allows lightning / nostr_zap
        # / liberapay only. We construct via dict and bypass the
        # Literal validation only at the receiver boundary; the
        # follow-up cc-task widens the Literal.
        event = self._build_payment_event(receipt, ts)
        try:
            append_event(event)
            usdc_receipts_total.labels(rail=RAIL_LABEL).inc()
        except Exception:  # noqa: BLE001
            log.warning("usdc payment event append failed", exc_info=True)

    def _build_payment_event(self, receipt: TransferReceipt, ts: datetime) -> PaymentEvent:
        """Construct a PaymentEvent for emission.

        Isolated so tests can drive the receiver's projection logic
        without an event-log side effect. The PaymentEvent's Literal
        type doesn't yet include ``x402_usdc_base`` — bypass via
        ``model_construct`` (no validation) per the interim contract;
        the follow-up adds the literal upstream.
        """

        return PaymentEvent.model_construct(
            timestamp=ts,
            rail=RAIL_LABEL,  # type: ignore[arg-type]
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
    "BASE_USDC_CONTRACT_ADDRESS",
    "CURSOR_PATH_ENV",
    "DEFAULT_BASE_RPC_URL",
    "DEFAULT_BLOCK_LOOKBACK",
    "DEFAULT_CURSOR_PATH",
    "DEFAULT_POLL_INTERVAL_S",
    "ERC20_TRANSFER_TOPIC",
    "OPERATOR_WALLET_ENV",
    "RAIL_LABEL",
    "READ_ONLY_RPC_METHODS",
    "TransferReceipt",
    "USDCReceiver",
    "USDC_DECIMALS",
    "iter_receipts_for_test",
    "usdc_receipts_total",
]
