import logging
from collections import defaultdict
from datetime import datetime

from models.constants import STABLECOINS, WRAPPED_NATIVE_BY_CHAIN
from services.early_buyers.block_lookup import timestamp_to_block
from services.early_buyers.classifier import QuoteTokenConfig, price_from_receipts
from services.early_buyers.schemas import ClassifiedSwap, PricedSwap, TokenTransfer
from services.early_buyers.transfers import (
    fetch_all_token_transfers,
    fetch_quote_transfers,
    fetch_tx_receipts,
)

logger = logging.getLogger(__name__)

MAX_RECEIPT_FETCHES = 10000


class EvmGateway:
    def __init__(self, chain_hex: str) -> None:
        self._chain_hex = chain_hex

    async def resolve_block(self, target_ts: int) -> int:
        return await timestamp_to_block(self._chain_hex, target_ts)

    async def fetch_token_transfers(
        self,
        token: str,
        from_block: int,
        to_block: int,
        from_dt: datetime,
        to_dt: datetime,
        pool_hints: list[str] | None = None,
    ) -> list[TokenTransfer]:
        return await fetch_all_token_transfers(
            token, self._chain_hex,
            from_dt.isoformat(), to_dt.isoformat(),
            from_block, to_block,
        )

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
        return await fetch_quote_transfers(
            pool, quote_token, self._chain_hex,
            from_block, to_block,
            max_pages=max_pages,
            from_dt=from_dt, to_dt=to_dt,
        )

    async def price_remaining_swaps(
        self,
        unpriced_buys: list[ClassifiedSwap],
        unpriced_sells: list[ClassifiedSwap],
        quote_to_usd: float,
    ) -> tuple[list[PricedSwap], list[PricedSwap]]:
        all_unpriced = unpriced_buys + unpriced_sells
        tx_hashes = _collect_tx_hashes(all_unpriced, MAX_RECEIPT_FETCHES)
        if not tx_hashes:
            return [], []

        logger.info("Fetching %d receipts for unpriced swaps", len(tx_hashes))
        receipt_logs = await fetch_tx_receipts(self._chain_hex, tx_hashes)

        configs = _build_quote_configs(self._chain_hex, quote_to_usd)
        receipt_buys = price_from_receipts(unpriced_buys, receipt_logs, configs, is_buy=True)
        receipt_sells = price_from_receipts(unpriced_sells, receipt_logs, configs, is_buy=False)
        return receipt_buys, receipt_sells


def _collect_tx_hashes(swaps: list[ClassifiedSwap], limit: int) -> list[str]:
    by_amount: dict[str, float] = defaultdict(float)
    for s in swaps:
        by_amount[s.tx_hash] += s.token_amount
    ranked = sorted(by_amount, key=by_amount.get, reverse=True)
    return ranked[:limit]


def _build_quote_configs(
    chain_hex: str,
    dex_quote_to_usd: float,
) -> list[QuoteTokenConfig]:
    configs: list[QuoteTokenConfig] = []
    wrapped = WRAPPED_NATIVE_BY_CHAIN.get(chain_hex)
    if wrapped:
        configs.append(QuoteTokenConfig(address=wrapped, decimals=18, to_usd=dex_quote_to_usd))
    for stable, decimals in STABLECOINS.items():
        configs.append(QuoteTokenConfig(address=stable, decimals=decimals, to_usd=1.0))
    return configs
