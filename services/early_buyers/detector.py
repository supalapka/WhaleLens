import asyncio
import logging
from datetime import datetime, timezone

from models.constants import ALCHEMY_RPC_URLS, DEXSCREENER_TO_CHAIN_HEX, STABLECOINS, WRAPPED_NATIVE
from services.checkers.dexscreener import get_token_pairs
from services.early_buyers.block_lookup import timestamp_to_block
from services.early_buyers.classifier import (
    aggregate_wallets,
    apply_filters,
    assign_swap_prices,
    classify_transfers,
)
from services.early_buyers.exceptions import (
    InsufficientPriceDataError,
    NoPairsFoundError,
    UnsupportedChainError,
)
from services.early_buyers.schemas import EarlyBuyerRecord, EarlyBuyerRequest, EarlyBuyerResponse
from services.early_buyers.transfers import fetch_pool_transfers, fetch_quote_transfers

logger = logging.getLogger(__name__)


def _resolve_quote_to_usd(quote_token: str, pair: dict) -> float:
    if quote_token in STABLECOINS:
        return 1.0
    if quote_token in WRAPPED_NATIVE:
        price_native = pair.get("price_native", 0)
        price_usd = pair.get("price_usd", 0)
        if price_native > 0:
            return price_usd / price_native
    raise InsufficientPriceDataError(
        f"Cannot determine USD price for quote token {quote_token}"
    )


async def detect_early_buyers(request: EarlyBuyerRequest) -> EarlyBuyerResponse:
    pairs = await get_token_pairs(request.token_address)
    if not pairs:
        raise NoPairsFoundError(
            f"No DEX pairs found for {request.token_address}"
        )

    chain_id = pairs[0]["chain_id"]
    chain_hex = DEXSCREENER_TO_CHAIN_HEX.get(chain_id)
    if request.chain:
        chain_hex = DEXSCREENER_TO_CHAIN_HEX.get(request.chain, request.chain)
        chain_id = request.chain

    if not chain_hex:
        raise NoPairsFoundError(f"Unsupported chain: {chain_id}")

    if chain_hex not in ALCHEMY_RPC_URLS:
        raise UnsupportedChainError(
            f"Chain {chain_hex} is not supported by RPC. "
            f"Supported: {', '.join(ALCHEMY_RPC_URLS)}"
        )

    primary_pair = pairs[0]
    primary_pool = primary_pair["pair_address"]
    quote_token = primary_pair["quote_token"]
    quote_to_usd = _resolve_quote_to_usd(quote_token, primary_pair)
    logger.info(
        "Quote token %s, quote_to_usd=%.4f, pool=%s",
        quote_token[:10], quote_to_usd, primary_pool[:10],
    )

    from_date = datetime.fromtimestamp(request.pump_start, tz=timezone.utc)
    to_date = datetime.fromtimestamp(request.pump_peak, tz=timezone.utc)

    from_block, to_block = await asyncio.gather(
        timestamp_to_block(chain_hex, request.pump_start),
        timestamp_to_block(chain_hex, request.pump_peak),
    )
    logger.info("Block range: %d → %d", from_block, to_block)

    transfers, quote_transfers = await asyncio.gather(
        fetch_pool_transfers(
            primary_pool, request.token_address, chain_hex,
            from_date.isoformat(), to_date.isoformat(),
            from_block, to_block,
        ),
        fetch_quote_transfers(
            primary_pool, quote_token, chain_hex,
            from_block, to_block,
        ),
    )

    if not transfers:
        return _empty_response(request)

    pool_addresses = {primary_pool}
    buys, sells = classify_transfers(transfers, pool_addresses)
    logger.info(
        "Classification: %d transfers → %d buys, %d sells, %d ignored | pool: %s",
        len(transfers), len(buys), len(sells),
        len(transfers) - len(buys) - len(sells),
        primary_pool[:10],
    )

    priced_buys = assign_swap_prices(buys, quote_transfers, quote_to_usd)
    priced_sells = assign_swap_prices(sells, quote_transfers, quote_to_usd)
    logger.info(
        "Pricing: %d/%d buys priced, %d/%d sells priced",
        len(priced_buys), len(buys), len(priced_sells), len(sells),
    )

    all_priced = priced_buys + priced_sells
    peak_price = max(s.price_usd for s in all_priced) if all_priced else 0.0

    records = aggregate_wallets(
        priced_buys, priced_sells, request.pump_start, request.pump_peak,
    )
    logger.info(
        "Aggregation: %d wallets with buys (before filtering)", len(records),
    )
    for r in records[:5]:
        logger.info(
            "  %s: bought=$%.2f sold=%.1f%% profit=%.1f%%",
            r.wallet[:10], r.buy.usd, r.sold_pct, r.profit_pct,
        )

    records = apply_filters(records)

    logger.info(
        "Early buyer detection complete for %s: %d results (after filters)",
        request.token_address[:10], len(records),
    )

    return EarlyBuyerResponse(
        token_address=request.token_address,
        pump_start=request.pump_start,
        pump_peak=request.pump_peak,
        pump_end=request.pump_peak,
        peak_price=peak_price,
        total_early_buyers=len(records),
        results=records,
    )


async def top_wallets(request: EarlyBuyerRequest, limit: int = 10) -> list[EarlyBuyerRecord]:
    pairs = await get_token_pairs(request.token_address)
    if not pairs:
        raise NoPairsFoundError(
            f"No DEX pairs found for {request.token_address}"
        )

    chain_id = pairs[0]["chain_id"]
    chain_hex = DEXSCREENER_TO_CHAIN_HEX.get(chain_id)
    if request.chain:
        chain_hex = DEXSCREENER_TO_CHAIN_HEX.get(request.chain, request.chain)
        chain_id = request.chain

    if not chain_hex:
        raise NoPairsFoundError(f"Unsupported chain: {chain_id}")

    if chain_hex not in ALCHEMY_RPC_URLS:
        raise UnsupportedChainError(
            f"Chain {chain_hex} is not supported by RPC. "
            f"Supported: {', '.join(ALCHEMY_RPC_URLS)}"
        )

    primary_pair = pairs[0]
    primary_pool = primary_pair["pair_address"]
    quote_token = primary_pair["quote_token"]
    quote_to_usd = _resolve_quote_to_usd(quote_token, primary_pair)

    from_date = datetime.fromtimestamp(request.pump_start, tz=timezone.utc)
    to_date = datetime.fromtimestamp(request.pump_peak, tz=timezone.utc)

    from_block, to_block = await asyncio.gather(
        timestamp_to_block(chain_hex, request.pump_start),
        timestamp_to_block(chain_hex, request.pump_peak),
    )

    transfers, quote_transfers = await asyncio.gather(
        fetch_pool_transfers(
            primary_pool, request.token_address, chain_hex,
            from_date.isoformat(), to_date.isoformat(),
            from_block, to_block,
        ),
        fetch_quote_transfers(
            primary_pool, quote_token, chain_hex,
            from_block, to_block,
        ),
    )

    if not transfers:
        return []

    buys, sells = classify_transfers(transfers, {primary_pool})
    priced_buys = assign_swap_prices(buys, quote_transfers, quote_to_usd)
    priced_sells = assign_swap_prices(sells, quote_transfers, quote_to_usd)

    records = aggregate_wallets(
        priced_buys, priced_sells, request.pump_start, request.pump_peak,
    )

    records.sort(key=lambda r: r.profit_pct, reverse=True)
    return records[:limit]


def _empty_response(request: EarlyBuyerRequest) -> EarlyBuyerResponse:
    return EarlyBuyerResponse(
        token_address=request.token_address,
        pump_start=request.pump_start,
        pump_peak=request.pump_peak,
        pump_end=request.pump_peak,
        peak_price=0.0,
        total_early_buyers=0,
        results=[],
    )
