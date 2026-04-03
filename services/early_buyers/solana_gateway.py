import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone

from models.constants import STABLECOINS
from services.early_buyers.classifier import QuoteTokenConfig
from services.early_buyers.schemas import ClassifiedSwap, PricedSwap, TokenTransfer
from services.early_buyers.solana_rpc import solana_rpc_call
from services.early_buyers.transfer_cache import get_cached_transfers, store_transfers

logger = logging.getLogger(__name__)

SOLANA_CHAIN = "solana"
WSOL = "So11111111111111111111111111111111111111112"
AVG_SLOT_TIME = 0.4
MAX_SIGNATURES_PAGES = 50
MAX_TX_CONCURRENCY = 5
MAX_EARLY_SIGNATURES = 5000


class SolanaGateway:
    def __init__(self) -> None:
        self._tx_cache: dict[str, dict] = {}
        self._slot_cache: dict[int, int] = {}

    async def resolve_block(self, target_ts: int) -> int:
        if target_ts in self._slot_cache:
            return self._slot_cache[target_ts]

        current_slot = await solana_rpc_call("getSlot", [])
        if current_slot is None:
            raise RuntimeError("Failed to fetch current Solana slot")

        current_ts = await solana_rpc_call("getBlockTime", [current_slot])
        if current_ts is None:
            raise RuntimeError(f"Failed to fetch block time for slot {current_slot}")

        if target_ts >= current_ts:
            estimated = current_slot
        else:
            estimated = int(current_slot - (current_ts - target_ts) / AVG_SLOT_TIME)

        self._slot_cache[target_ts] = estimated
        logger.info("resolve_block(%d) = slot %d (estimated)", target_ts, estimated)
        return estimated

    async def fetch_token_transfers(
        self,
        token: str,
        from_block: int,
        to_block: int,
        from_dt: datetime,
        to_dt: datetime,
        pool_hints: list[str] | None = None,
    ) -> list[TokenTransfer]:
        cached = await get_cached_transfers("_all", token, SOLANA_CHAIN, from_dt, to_dt)
        if cached is not None:
            logger.info("Cache hit for Solana token %s: %d transfers", token[:10], len(cached))
            return cached

        sigs = await self._fetch_signatures_in_range(token, int(from_dt.timestamp()), int(to_dt.timestamp()), to_block)
        unique_sigs = list(dict.fromkeys(sigs))
        logger.info("Fetched %d unique signatures for token %s", len(unique_sigs), token[:10])

        earliest_sigs = unique_sigs[-MAX_EARLY_SIGNATURES:] if len(unique_sigs) > MAX_EARLY_SIGNATURES else unique_sigs
        logger.info("Loading %d earliest transactions", len(earliest_sigs))
        await self._load_transactions(earliest_sigs)

        transfers = _extract_token_transfers(self._tx_cache, token, from_dt, to_dt)
        logger.info("Parsed %d token transfers for %s", len(transfers), token[:10])

        await store_transfers("_all", token, SOLANA_CHAIN, from_dt, to_dt, transfers)
        return transfers

    async def fetch_pool_quote_transfers(
        self,
        pool: str,
        quote_token: str,
        from_block: int,
        to_block: int,
        max_pages: int,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
    ) -> list[TokenTransfer]:
        if from_dt and to_dt:
            cached = await get_cached_transfers(pool, quote_token, SOLANA_CHAIN, from_dt, to_dt)
            if cached is not None:
                return cached

        transfers = _extract_pool_quote_transfers(self._tx_cache, pool, quote_token, from_dt, to_dt)
        logger.info("Extracted %d quote transfers for pool %s", len(transfers), pool[:10])

        if from_dt and to_dt:
            await store_transfers(pool, quote_token, SOLANA_CHAIN, from_dt, to_dt, transfers)
        return transfers

    async def price_remaining_swaps(
        self,
        unpriced_buys: list[ClassifiedSwap],
        unpriced_sells: list[ClassifiedSwap],
        quote_to_usd: float,
    ) -> tuple[list[PricedSwap], list[PricedSwap]]:
        configs = _build_solana_quote_configs(quote_to_usd)
        priced_buys = _price_from_balance_changes(unpriced_buys, self._tx_cache, configs, is_buy=True)
        priced_sells = _price_from_balance_changes(unpriced_sells, self._tx_cache, configs, is_buy=False)
        return priced_buys, priced_sells

    async def _find_block_cursor(self, slot: int) -> str | None:
        block_params = {"transactionDetails": "signatures", "rewards": False, "maxSupportedTransactionVersion": 0}
        for s in range(slot, slot + 50):
            block = await solana_rpc_call("getBlock", [s, block_params])
            if block and block.get("signatures"):
                cursor = block["signatures"][-1]
                logger.info("_find_block_cursor: slot=%d cursor=%s", s, cursor[:10])
                return cursor
        logger.warning("_find_block_cursor: no block found near slot %d", slot)
        return None

    async def _fetch_signatures_in_range(
        self, address: str, from_ts: int, to_ts: int, to_slot: int,
    ) -> list[str]:
        sigs: list[str] = []
        before: str | None = await self._find_block_cursor(to_slot)
        logger.info("_fetch_signatures_in_range: address=%s from_ts=%d to_ts=%d cursor=%s", address[:10], from_ts, to_ts, before[:10] if before else None)

        for page in range(MAX_SIGNATURES_PAGES):
            params: dict = {"limit": 1000, "commitment": "finalized"}
            if before:
                params["before"] = before

            result = await solana_rpc_call("getSignaturesForAddress", [address, params])
            if not result:
                break

            page_done = False
            for item in result:
                block_time = item.get("blockTime") or 0
                if block_time > to_ts:
                    continue
                if block_time < from_ts:
                    page_done = True
                    break
                if not item.get("err"):
                    sigs.append(item.get("signature", ""))

            logger.info("_fetch_signatures page %d: collected %d sigs so far", page, len(sigs))
            if page_done or len(result) < 1000:
                break

            before = result[-1].get("signature")

        logger.info("_fetch_signatures done: %d sigs for %s", len(sigs), address[:10])
        return sigs

    async def _load_transactions(self, signatures: list[str]) -> None:
        missing = [s for s in signatures if s not in self._tx_cache]
        logger.info("_load_transactions: %d total, %d missing from cache", len(signatures), len(missing))
        if not missing:
            return

        tx_params = {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}
        results = await asyncio.gather(*[solana_rpc_call("getTransaction", [s, tx_params]) for s in missing])
        loaded = 0
        for sig, tx in zip(missing, results):
            if tx:
                self._tx_cache[sig] = tx
                loaded += 1
        logger.info("_load_transactions: loaded %d/%d transactions", loaded, len(missing))


def _get_balance_deltas(tx: dict, mint: str) -> dict[str, int]:
    pre: dict[str, int] = {}
    post: dict[str, int] = {}

    for entry in tx.get("meta", {}).get("preTokenBalances", []):
        if entry.get("mint") == mint:
            owner = entry.get("owner", "")
            amount = int(entry.get("uiTokenAmount", {}).get("amount", "0"))
            pre[owner] = pre.get(owner, 0) + amount

    for entry in tx.get("meta", {}).get("postTokenBalances", []):
        if entry.get("mint") == mint:
            owner = entry.get("owner", "")
            amount = int(entry.get("uiTokenAmount", {}).get("amount", "0"))
            post[owner] = post.get(owner, 0) + amount

    all_owners = set(pre) | set(post)
    return {
        owner: post.get(owner, 0) - pre.get(owner, 0)
        for owner in all_owners
        if post.get(owner, 0) - pre.get(owner, 0) != 0
    }


def _get_token_decimals(tx: dict, mint: str) -> int:
    for entry in (tx.get("meta", {}).get("preTokenBalances") or []) + (tx.get("meta", {}).get("postTokenBalances") or []):
        if entry.get("mint") == mint:
            return int(entry.get("uiTokenAmount", {}).get("decimals", 9))
    return 9


def _get_block_time_iso(tx: dict) -> str | None:
    block_time = tx.get("blockTime")
    if block_time is None:
        return None
    return datetime.fromtimestamp(block_time, tz=timezone.utc).isoformat()


def _extract_token_transfers(
    tx_cache: dict[str, dict],
    mint: str,
    from_dt: datetime,
    to_dt: datetime,
) -> list[TokenTransfer]:
    transfers: list[TokenTransfer] = []
    seen: set[str] = set()

    for sig, tx in tx_cache.items():
        block_ts = _get_block_time_iso(tx)
        if not block_ts:
            continue

        ts = datetime.fromisoformat(block_ts)
        if not (from_dt <= ts <= to_dt):
            continue

        deltas = _get_balance_deltas(tx, mint)
        if not deltas:
            continue

        decimals = str(_get_token_decimals(tx, mint))
        senders = [(addr, -d) for addr, d in deltas.items() if d < 0]
        receivers = [(addr, d) for addr, d in deltas.items() if d > 0]

        if not senders or not receivers:
            continue

        sender_addr, send_amount = max(senders, key=lambda x: x[1])
        receiver_addr, recv_amount = max(receivers, key=lambda x: x[1])
        amount = min(send_amount, recv_amount)

        dedup_key = f"{sig}:{sender_addr}:{receiver_addr}"
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        transfers.append(TokenTransfer(
            transaction_hash=sig,
            from_address=sender_addr,
            to_address=receiver_addr,
            value=str(amount),
            block_timestamp=block_ts,
            token_decimals=decimals,
        ))

    return transfers


def _extract_pool_quote_transfers(
    tx_cache: dict[str, dict],
    pool_authority: str,
    quote_mint: str,
    from_dt: datetime | None,
    to_dt: datetime | None,
) -> list[TokenTransfer]:
    transfers: list[TokenTransfer] = []
    seen: set[str] = set()

    for sig, tx in tx_cache.items():
        block_ts = _get_block_time_iso(tx)
        if not block_ts:
            continue

        if from_dt and to_dt:
            ts = datetime.fromisoformat(block_ts)
            if not (from_dt <= ts <= to_dt):
                continue

        deltas = _get_balance_deltas(tx, quote_mint)
        if pool_authority not in deltas:
            continue

        decimals = str(_get_token_decimals(tx, quote_mint))
        pool_delta = deltas[pool_authority]
        amount = abs(pool_delta)

        if amount == 0:
            continue

        from_addr = pool_authority if pool_delta < 0 else next(
            (addr for addr, d in deltas.items() if d < 0 and addr != pool_authority), pool_authority
        )
        to_addr = pool_authority if pool_delta > 0 else next(
            (addr for addr, d in deltas.items() if d > 0 and addr != pool_authority), pool_authority
        )

        dedup_key = f"{sig}:{from_addr}:{to_addr}:{quote_mint}"
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        transfers.append(TokenTransfer(
            transaction_hash=sig,
            from_address=from_addr,
            to_address=to_addr,
            value=str(amount),
            block_timestamp=block_ts,
            token_decimals=decimals,
        ))

    return transfers


def _build_solana_quote_configs(native_to_usd: float) -> list[QuoteTokenConfig]:
    configs = [QuoteTokenConfig(address=WSOL, decimals=9, to_usd=native_to_usd)]
    for addr, decimals in STABLECOINS.items():
        if not addr.startswith("0x"):
            configs.append(QuoteTokenConfig(address=addr, decimals=decimals, to_usd=1.0))
    return configs


def _compute_wallet_quote_flows(
    tx: dict,
    wallet: str,
    configs: list[QuoteTokenConfig],
) -> tuple[float, float]:
    total_inflow_usd = 0.0
    total_outflow_usd = 0.0
    for cfg in configs:
        deltas = _get_balance_deltas(tx, cfg.address)
        delta = deltas.get(wallet, 0)
        if delta == 0:
            continue
        usd_value = abs(delta) / (10 ** cfg.decimals) * cfg.to_usd
        if delta > 0:
            total_inflow_usd += usd_value
        else:
            total_outflow_usd += usd_value
    return total_inflow_usd, total_outflow_usd


def _price_from_balance_changes(
    swaps: list[ClassifiedSwap],
    tx_cache: dict[str, dict],
    configs: list[QuoteTokenConfig],
    is_buy: bool,
) -> list[PricedSwap]:
    base_by_key: dict[tuple[str, str], float] = defaultdict(float)
    for swap in swaps:
        base_by_key[(swap.tx_hash, swap.wallet_address)] += swap.token_amount

    priced: list[PricedSwap] = []
    for swap in swaps:
        tx = tx_cache.get(swap.tx_hash)
        if not tx:
            continue
        inflow, outflow = _compute_wallet_quote_flows(tx, swap.wallet_address, configs)
        net_usd = outflow - inflow if is_buy else inflow - outflow
        if net_usd <= 0:
            continue
        total_base = base_by_key.get((swap.tx_hash, swap.wallet_address), 0)
        if total_base <= 0:
            continue
        price_usd = net_usd / total_base
        priced.append(PricedSwap(
            wallet_address=swap.wallet_address,
            token_amount=swap.token_amount,
            timestamp=swap.timestamp,
            tx_hash=swap.tx_hash,
            price_usd=price_usd,
            usd_value=swap.token_amount * price_usd,
        ))
    return priced
