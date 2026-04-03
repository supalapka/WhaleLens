import logging
from collections import defaultdict
from datetime import datetime, timezone

from models.constants import STABLECOINS
from services.early_buyers.helius_client import fetch_token_swaps
from services.early_buyers.schemas import ClassifiedSwap, PricedSwap, TokenTransfer
from services.early_buyers.transfer_cache import get_cached_transfers, store_transfers

logger = logging.getLogger(__name__)

SOLANA_CHAIN = "solana"
WSOL = "So11111111111111111111111111111111111111112"

_SOLANA_STABLECOINS: frozenset[str] = frozenset(
    addr for addr in STABLECOINS if not addr.startswith("0x")
)

_tx_cache: dict[str, dict] = {}


class SolanaIndexedGateway:

    async def resolve_block(self, target_ts: int) -> int:
        return 0

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
            cached_hashes = {t.transaction_hash for t in cached}
            missing = cached_hashes - set(_tx_cache.keys())
            if not missing:
                logger.info("Cache hit for %s: %d transfers (pricing data warm)", token[:10], len(cached))
                return cached
            logger.info("Cache hit for %s: %d transfers, re-fetching %d txs for pricing", token[:10], len(cached), len(missing))

        txs = await fetch_token_swaps(token, from_dt, to_dt)
        logger.info("Fetched %d Helius swap txs for %s", len(txs), token[:10])

        for tx in txs:
            _tx_cache[tx["signature"]] = tx

        if cached is not None:
            fresh_hashes = {tx["signature"] for tx in txs}
            if not (fresh_hashes - cached_hashes):
                return cached
            logger.info("Cache stale for %s: %d new txs, re-extracting", token[:10], len(fresh_hashes - cached_hashes))

        transfers = _extract_token_transfers(txs, token)
        logger.info("Extracted %d token transfers for %s", len(transfers), token[:10])

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
        return []

    async def price_remaining_swaps(
        self,
        unpriced_buys: list[ClassifiedSwap],
        unpriced_sells: list[ClassifiedSwap],
        quote_to_usd: float,
    ) -> tuple[list[PricedSwap], list[PricedSwap]]:
        priced_buys = _price_swaps(unpriced_buys, _tx_cache, quote_to_usd, is_buy=True)
        priced_sells = _price_swaps(unpriced_sells, _tx_cache, quote_to_usd, is_buy=False)
        return priced_buys, priced_sells


def _extract_token_transfers(txs: list[dict], mint: str) -> list[TokenTransfer]:
    transfers: list[TokenTransfer] = []
    for tx in txs:
        sig = tx.get("signature", "")
        ts = tx.get("timestamp")
        if not ts:
            continue
        block_ts = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

        for tt in tx.get("tokenTransfers", []):
            if tt.get("mint") != mint:
                continue
            token_amount = tt.get("tokenAmount", 0)
            if token_amount <= 0:
                continue
            decimals = tt.get("decimals", 9)
            raw_value = int(round(token_amount * (10 ** decimals)))

            transfers.append(TokenTransfer(
                transaction_hash=sig,
                from_address=tt.get("fromUserAccount", ""),
                to_address=tt.get("toUserAccount", ""),
                value=str(raw_value),
                block_timestamp=block_ts,
                token_decimals=str(decimals),
            ))

    return transfers


def _get_wallet_usd_flow(
    tx: dict,
    wallet: str,
    is_buy: bool,
    sol_to_usd: float,
) -> float:
    usd = 0.0

    for nt in tx.get("nativeTransfers", []):
        amount_sol = nt.get("amount", 0) / 1e9
        if is_buy and nt.get("fromUserAccount") == wallet:
            usd += amount_sol * sol_to_usd
        elif not is_buy and nt.get("toUserAccount") == wallet:
            usd += amount_sol * sol_to_usd

    for tt in tx.get("tokenTransfers", []):
        mint = tt.get("mint", "")
        token_amount = tt.get("tokenAmount", 0)

        if mint == WSOL:
            usd_amount = token_amount * sol_to_usd
        elif mint in _SOLANA_STABLECOINS:
            usd_amount = token_amount
        else:
            continue

        if is_buy and tt.get("fromUserAccount") == wallet:
            usd += usd_amount
        elif not is_buy and tt.get("toUserAccount") == wallet:
            usd += usd_amount

    return usd


def _price_swaps(
    swaps: list[ClassifiedSwap],
    tx_cache: dict[str, dict],
    sol_to_usd: float,
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
        usd = _get_wallet_usd_flow(tx, swap.wallet_address, is_buy, sol_to_usd)
        if usd <= 0:
            continue
        total_base = base_by_key.get((swap.tx_hash, swap.wallet_address), 0)
        if total_base <= 0:
            continue
        price_usd = usd / total_base
        priced.append(PricedSwap(
            wallet_address=swap.wallet_address,
            token_amount=swap.token_amount,
            timestamp=swap.timestamp,
            tx_hash=swap.tx_hash,
            price_usd=price_usd,
            usd_value=swap.token_amount * price_usd,
        ))
    return priced
