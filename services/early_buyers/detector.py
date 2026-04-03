import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

from models.constants import (
    DEXSCREENER_TO_CHAIN_HEX,
    STABLECOINS,
    WRAPPED_NATIVE,
    WRAPPED_NATIVE_BY_CHAIN,
)
from services.checkers.dexscreener import get_token_pairs
from services.early_buyers.classifier import (
    aggregate_wallets,
    apply_filters,
    assign_swap_prices,
    classify_transfers,
)
from services.early_buyers.exceptions import (
    InsufficientPriceDataError,
    NoPairsFoundError,
)
from services.early_buyers.gateway import ChainGateway, create_gateway
from services.early_buyers.schemas import EarlyBuyerRecord, EarlyBuyerRequest, EarlyBuyerResponse, PricedSwap, TokenTransfer

logger = logging.getLogger(__name__)

MIN_POOL_PEERS = 20
QUOTE_FETCH_CONCURRENCY = 10
MAX_QUOTE_PAGES = 50
DISCOVERED_QUOTE_MAX_PAGES = 10

_IGNORED_ADDRESSES: set[str] = {
    "0x0000000000000000000000000000000000000000",
    "0x000000000000000000000000000000000000dead",
    "11111111111111111111111111111111",
}


@dataclass
class _PoolInfo:
    address: str
    quote_token: str
    quote_to_usd: float


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


def _resolve_chain(pairs: list[dict], request_chain: str | None) -> str:
    chain_id = request_chain or pairs[0]["chain_id"]
    if chain_id not in DEXSCREENER_TO_CHAIN_HEX:
        raise NoPairsFoundError(f"Unsupported chain: {chain_id}")
    return chain_id


def _resolve_dex_pools(pairs: list[dict], chain_id: str) -> list[_PoolInfo]:
    pools: list[_PoolInfo] = []
    seen: set[str] = set()
    for pair in pairs:
        if pair["chain_id"] != chain_id:
            continue
        addr = pair["pair_address"]
        if addr in seen:
            continue
        seen.add(addr)
        try:
            q2u = _resolve_quote_to_usd(pair["quote_token"], pair)
        except InsufficientPriceDataError:
            logger.debug("Skipping pool %s: unsupported quote token %s", addr[:10], pair["quote_token"][:10])
            continue
        pools.append(_PoolInfo(address=addr, quote_token=pair["quote_token"], quote_to_usd=q2u))
    return pools


def _discover_pools(transfers: list[TokenTransfer]) -> set[str]:
    send_peers: dict[str, set[str]] = defaultdict(set)
    recv_peers: dict[str, set[str]] = defaultdict(set)
    for t in transfers:
        send_peers[t.from_address].add(t.to_address)
        recv_peers[t.to_address].add(t.from_address)

    discovered: set[str] = set()
    for addr in send_peers:
        if addr in _IGNORED_ADDRESSES:
            continue
        if (
            addr in recv_peers
            and len(send_peers[addr]) >= MIN_POOL_PEERS
            and len(recv_peers[addr]) >= MIN_POOL_PEERS
        ):
            discovered.add(addr)
    return discovered


def _dedup_priced(swaps: list[PricedSwap]) -> list[PricedSwap]:
    seen: set[tuple[str, str]] = set()
    result: list[PricedSwap] = []
    for s in swaps:
        key = (s.tx_hash, s.wallet_address)
        if key in seen:
            continue
        seen.add(key)
        result.append(s)
    return result


async def _fetch_and_price(
    dex_pools: list[_PoolInfo],
    token_address: str,
    chain_id: str,
    gateway: ChainGateway,
    from_dt: datetime,
    to_dt: datetime,
    from_block: int,
    to_block: int,
) -> tuple[list[PricedSwap], list[PricedSwap]]:
    pool_hints = [p.address for p in dex_pools]
    all_transfers = await gateway.fetch_token_transfers(
        token_address, from_block, to_block, from_dt, to_dt,
        pool_hints=pool_hints,
    )
    if not all_transfers:
        return [], []

    discovered = _discover_pools(all_transfers)
    dex_addresses = set(pool_hints)
    new_pool_addresses = discovered - dex_addresses
    all_pool_addresses = dex_addresses | new_pool_addresses

    wrapped_native = WRAPPED_NATIVE_BY_CHAIN.get(
        DEXSCREENER_TO_CHAIN_HEX.get(chain_id, chain_id),
    )
    native_to_usd = next(
        (p.quote_to_usd for p in dex_pools if p.quote_token == wrapped_native),
        None,
    )

    discovered_pools: list[_PoolInfo] = []
    for addr in sorted(new_pool_addresses):
        if wrapped_native and native_to_usd:
            discovered_pools.append(_PoolInfo(address=addr, quote_token=wrapped_native, quote_to_usd=native_to_usd))

    logger.info(
        "Pool discovery: %d DexScreener + %d discovered = %d total (%d transfers)",
        len(dex_pools), len(discovered_pools),
        len(dex_pools) + len(discovered_pools), len(all_transfers),
    )

    buys, sells = classify_transfers(all_transfers, all_pool_addresses)
    logger.info(
        "Classification: %d buys, %d sells, %d ignored",
        len(buys), len(sells), len(all_transfers) - len(buys) - len(sells),
    )

    sem = asyncio.Semaphore(QUOTE_FETCH_CONCURRENCY)

    async def _fetch_quotes(pool: _PoolInfo, max_pages: int) -> list[TokenTransfer]:
        async with sem:
            return await gateway.fetch_pool_quote_transfers(
                pool.address, pool.quote_token,
                from_block, to_block,
                max_pages=max_pages,
                from_dt=from_dt, to_dt=to_dt,
            )

    all_pools = list(dex_pools) + list(discovered_pools)
    dex_coros = [_fetch_quotes(p, MAX_QUOTE_PAGES) for p in dex_pools]
    disc_coros = [_fetch_quotes(p, DISCOVERED_QUOTE_MAX_PAGES) for p in discovered_pools]
    all_quote_results = await asyncio.gather(*dex_coros, *disc_coros)

    quote_usd_by_tx: dict[str, float] = defaultdict(float)
    total_quote_count = 0
    for pool, quotes in zip(all_pools, all_quote_results):
        total_quote_count += len(quotes)
        for qt in quotes:
            quote_usd_by_tx[qt.transaction_hash] += qt.token_amount * pool.quote_to_usd

    priced_buys = assign_swap_prices(buys, quote_usd_by_tx)
    priced_sells = assign_swap_prices(sells, quote_usd_by_tx)

    logger.info(
        "Quote pricing: %d/%d buys, %d/%d sells (%d quote transfers)",
        len(priced_buys), len(buys),
        len(priced_sells), len(sells),
        total_quote_count,
    )

    priced_buy_hashes = {s.tx_hash for s in priced_buys}
    priced_sell_hashes = {s.tx_hash for s in priced_sells}
    unpriced_buys = [b for b in buys if b.tx_hash not in priced_buy_hashes]
    unpriced_sells = [s for s in sells if s.tx_hash not in priced_sell_hashes]

    if unpriced_buys or unpriced_sells:
        native_usd = native_to_usd or (dex_pools[0].quote_to_usd if dex_pools else 0.0)
        extra_buys, extra_sells = await gateway.price_remaining_swaps(
            unpriced_buys, unpriced_sells, native_usd,
        )
        priced_buys.extend(extra_buys)
        priced_sells.extend(extra_sells)
        logger.info(
            "Fallback pricing: +%d buys, +%d sells | Total: %d/%d buys, %d/%d sells",
            len(extra_buys), len(extra_sells),
            len(priced_buys), len(buys),
            len(priced_sells), len(sells),
        )

    return _dedup_priced(priced_buys), _dedup_priced(priced_sells)


async def detect_early_buyers(request: EarlyBuyerRequest) -> EarlyBuyerResponse:
    pairs = await get_token_pairs(request.token_address)
    if not pairs:
        raise NoPairsFoundError(
            f"No DEX pairs found for {request.token_address}"
        )

    chain_id = _resolve_chain(pairs, request.chain)
    gateway = create_gateway(chain_id)
    token_symbol = pairs[0].get("base_symbol", "???")
    dex_pools = _resolve_dex_pools(pairs, chain_id)

    logger.info(
        "Resolved %d DexScreener pools for %s on %s: %s",
        len(dex_pools), request.token_address[:10], chain_id,
        ", ".join(f"{p.address[:10]}(q={p.quote_token[:10]})" for p in dex_pools) or "none",
    )

    from_date = datetime.fromtimestamp(request.pump_start, tz=timezone.utc)
    to_date = datetime.fromtimestamp(request.pump_peak, tz=timezone.utc)

    from_block, to_block = await asyncio.gather(
        gateway.resolve_block(request.pump_start),
        gateway.resolve_block(request.pump_peak),
    )
    logger.info("Block range: %d → %d", from_block, to_block)

    priced_buys, priced_sells = await _fetch_and_price(
        dex_pools, request.token_address, chain_id, gateway,
        from_date, to_date,
        from_block, to_block,
    )

    if not priced_buys and not priced_sells:
        return _empty_response(request, token_symbol)

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
        token_symbol=token_symbol,
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

    chain_id = _resolve_chain(pairs, request.chain)
    gateway = create_gateway(chain_id)
    dex_pools = _resolve_dex_pools(pairs, chain_id)

    from_date = datetime.fromtimestamp(request.pump_start, tz=timezone.utc)
    to_date = datetime.fromtimestamp(request.pump_peak, tz=timezone.utc)

    from_block, to_block = await asyncio.gather(
        gateway.resolve_block(request.pump_start),
        gateway.resolve_block(request.pump_peak),
    )

    priced_buys, priced_sells = await _fetch_and_price(
        dex_pools, request.token_address, chain_id, gateway,
        from_date, to_date,
        from_block, to_block,
    )

    if not priced_buys:
        return []

    records = aggregate_wallets(
        priced_buys, priced_sells, request.pump_start, request.pump_peak,
    )

    records.sort(key=lambda r: r.profit_pct, reverse=True)
    return records[:limit]


def _empty_response(request: EarlyBuyerRequest, token_symbol: str) -> EarlyBuyerResponse:
    return EarlyBuyerResponse(
        token_address=request.token_address,
        token_symbol=token_symbol,
        pump_start=request.pump_start,
        pump_peak=request.pump_peak,
        pump_end=request.pump_peak,
        peak_price=0.0,
        total_early_buyers=0,
        results=[],
    )
