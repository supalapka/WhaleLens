from __future__ import annotations

import logging
from datetime import datetime
from typing import Protocol

from models.constants import ALCHEMY_RPC_URLS, DEXSCREENER_TO_CHAIN_HEX
from services.early_buyers.exceptions import UnsupportedChainError
from services.early_buyers.schemas import ClassifiedSwap, PricedSwap, TokenTransfer

logger = logging.getLogger(__name__)


class ChainGateway(Protocol):
    async def resolve_block(self, target_ts: int) -> int: ...

    async def fetch_token_transfers(
        self,
        token: str,
        from_block: int,
        to_block: int,
        from_dt: datetime,
        to_dt: datetime,
        pool_hints: list[str] | None = None,
    ) -> list[TokenTransfer]: ...

    async def fetch_pool_quote_transfers(
        self,
        pool: str,
        quote_token: str,
        from_block: int,
        to_block: int,
        max_pages: int,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
    ) -> list[TokenTransfer]: ...

    async def price_remaining_swaps(
        self,
        unpriced_buys: list[ClassifiedSwap],
        unpriced_sells: list[ClassifiedSwap],
        quote_to_usd: float,
    ) -> tuple[list[PricedSwap], list[PricedSwap]]: ...


SOLANA_CHAIN_ID = "solana"


def create_gateway(chain_id: str) -> ChainGateway:
    if chain_id == SOLANA_CHAIN_ID:
        from config import settings

        if settings.helius_api_key:
            logger.info("Solana gateway: Helius indexed path active")
            from services.early_buyers.solana_indexed_gateway import SolanaIndexedGateway

            return SolanaIndexedGateway()

        logger.warning("Solana gateway: falling back to RPC (set HELIUS_API_KEY to use indexed path)")
        from services.early_buyers.solana_gateway import SolanaGateway

        return SolanaGateway()

    chain_hex = DEXSCREENER_TO_CHAIN_HEX.get(chain_id)
    if not chain_hex or chain_hex not in ALCHEMY_RPC_URLS:
        raise UnsupportedChainError(
            f"Chain '{chain_id}' is not supported. "
            f"Supported: {', '.join(ALCHEMY_RPC_URLS)}, {SOLANA_CHAIN_ID}"
        )

    from services.early_buyers.evm_gateway import EvmGateway

    return EvmGateway(chain_hex)
