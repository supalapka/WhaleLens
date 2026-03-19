import logging
from datetime import datetime, timezone

from models.constants import DEXSCREENER_TO_GECKO_NETWORK, DEXSCREENER_TO_MORALIS_CHAIN
from services.checkers.dexscreener import get_token_pairs
from services.checkers.geckoterminal import get_ohlcv_range
from services.early_buyers.classifier import (
    aggregate_wallets,
    apply_filters,
    assign_usd_prices,
    classify_transfers,
)
from services.early_buyers.exceptions import InsufficientPriceDataError, NoPairsFoundError
from services.early_buyers.schemas import EarlyBuyerRequest, EarlyBuyerResponse
from services.early_buyers.transfers import fetch_swaps_from_pools

logger = logging.getLogger(__name__)


async def detect_early_buyers(request: EarlyBuyerRequest) -> EarlyBuyerResponse:
    pairs = await get_token_pairs(request.token_address)
    if not pairs:
        raise NoPairsFoundError(
            f"No DEX pairs found for {request.token_address}"
        )

    chain_id = pairs[0]["chain_id"]
    chain_hex = DEXSCREENER_TO_MORALIS_CHAIN.get(chain_id)
    if request.chain:
        chain_hex = DEXSCREENER_TO_MORALIS_CHAIN.get(request.chain, request.chain)
        chain_id = request.chain

    if not chain_hex:
        raise NoPairsFoundError(f"Unsupported chain: {chain_id}")

    network = DEXSCREENER_TO_GECKO_NETWORK.get(chain_id, chain_id)
    pool_addresses = {p["pair_address"] for p in pairs}
    primary_pool = pairs[0]["pair_address"]

    from_date = datetime.fromtimestamp(request.pump_start, tz=timezone.utc)
    to_date = datetime.fromtimestamp(request.pump_peak, tz=timezone.utc)

    transfers = await fetch_swaps_from_pools(
        pool_addresses, request.token_address, chain_hex,
        from_date.isoformat(), to_date.isoformat(),
    )

    if not transfers:
        return _empty_response(request)

    candles = await get_ohlcv_range(
        network, primary_pool,
        start_ts=request.pump_start,
        end_ts=request.pump_peak,
        timeframe="minute",
        aggregate=5,
    )

    if not candles:
        raise InsufficientPriceDataError(
            "No OHLCV data available for the analysis window"
        )

    peak_price = max(c.high for c in candles)

    buys, sells = classify_transfers(transfers, pool_addresses)
    logger.info(
        "Classification: %d transfers → %d buys, %d sells, %d ignored | pools: %s",
        len(transfers), len(buys), len(sells),
        len(transfers) - len(buys) - len(sells),
        pool_addresses,
    )

    priced_buys = assign_usd_prices(buys, candles)
    priced_sells = assign_usd_prices(sells, candles)

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
