import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

from models.constants import (
    ALCHEMY_RPC_URLS,
    DEXSCREENER_TO_CHAIN_HEX,
    STABLECOINS,
    WRAPPED_NATIVE,
    WRAPPED_NATIVE_BY_CHAIN,
)
from services.checkers.dexscreener import get_token_pairs
from services.early_buyers.block_lookup import timestamp_to_block
from services.early_buyers.classifier import (
    QuoteTokenConfig,
    aggregate_wallets,
    apply_filters,
    assign_swap_prices,
    classify_transfers,
    price_from_receipts,
)
from services.early_buyers.exceptions import (
    InsufficientPriceDataError,
    NoPairsFoundError,
    UnsupportedChainError,
)
from services.early_buyers.schemas import ClassifiedSwap, EarlyBuyerRecord, EarlyBuyerRequest, EarlyBuyerResponse, PricedSwap, TokenTransfer
from services.early_buyers.transfers import fetch_all_token_transfers, fetch_quote_transfers, fetch_tx_receipts

logger = logging.getLogger(__name__)

MIN_POOL_PEERS = 20
QUOTE_FETCH_CONCURRENCY = 10
MAX_QUOTE_PAGES = 1000
DISCOVERED_QUOTE_MAX_PAGES = 10
MAX_RECEIPT_FETCHES = 10000

_IGNORED_ADDRESSES: set[str] = {
    "0x0000000000000000000000000000000000000000",
    "0x000000000000000000000000000000000000dead",
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


def _resolve_chain(pairs: list[dict], request_chain: str | None) -> tuple[str, str]:
    chain_id = pairs[0]["chain_id"]
    chain_hex = DEXSCREENER_TO_CHAIN_HEX.get(chain_id)
    if request_chain:
        chain_hex = DEXSCREENER_TO_CHAIN_HEX.get(request_chain, request_chain)
        chain_id = request_chain

    if not chain_hex:
        raise NoPairsFoundError(f"Unsupported chain: {chain_id}")

    if chain_hex not in ALCHEMY_RPC_URLS:
        raise UnsupportedChainError(
            f"Chain {chain_hex} is not supported by RPC. "
            f"Supported: {', '.join(ALCHEMY_RPC_URLS)}"
        )
    return chain_hex, chain_id


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


def _collect_tx_hashes(
    swaps: list[ClassifiedSwap], limit: int,
) -> list[str]:
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
    for stable in STABLECOINS:
        configs.append(QuoteTokenConfig(address=stable, decimals=6, to_usd=1.0))
    return configs


async def _price_via_receipts(
    unpriced_buys: list[ClassifiedSwap],
    unpriced_sells: list[ClassifiedSwap],
    chain_hex: str,
    quote_to_usd: float,
) -> tuple[list[PricedSwap], list[PricedSwap]]:
    all_unpriced = unpriced_buys + unpriced_sells
    tx_hashes = _collect_tx_hashes(all_unpriced, MAX_RECEIPT_FETCHES)
    if not tx_hashes:
        return [], []

    logger.info("Fetching %d receipts for unpriced swaps", len(tx_hashes))
    receipt_logs = await fetch_tx_receipts(chain_hex, tx_hashes)

    configs = _build_quote_configs(chain_hex, quote_to_usd)
    receipt_buys = price_from_receipts(unpriced_buys, receipt_logs, configs, is_buy=True)
    receipt_sells = price_from_receipts(unpriced_sells, receipt_logs, configs, is_buy=False)
    return receipt_buys, receipt_sells


async def _fetch_and_price(
    dex_pools: list[_PoolInfo],
    token_address: str,
    chain_hex: str,
    from_date_iso: str,
    to_date_iso: str,
    from_block: int,
    to_block: int,
) -> tuple[list[PricedSwap], list[PricedSwap]]:
    all_transfers = await fetch_all_token_transfers(
        token_address, chain_hex, from_date_iso, to_date_iso,
        from_block, to_block,
    )
    if not all_transfers:
        return [], []

    discovered = _discover_pools(all_transfers)
    dex_addresses = {p.address for p in dex_pools}
    new_pool_addresses = discovered - dex_addresses
    all_pool_addresses = dex_addresses | new_pool_addresses

    wrapped_native = WRAPPED_NATIVE_BY_CHAIN.get(chain_hex)
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
    cache_from_dt = datetime.fromisoformat(from_date_iso)
    cache_to_dt = datetime.fromisoformat(to_date_iso)

    async def _fetch_quotes(pool: _PoolInfo, max_pages: int) -> list[TokenTransfer]:
        async with sem:
            return await fetch_quote_transfers(
                pool.address, pool.quote_token, chain_hex,
                from_block, to_block,
                max_pages=max_pages,
                from_dt=cache_from_dt, to_dt=cache_to_dt,
            )

    dex_coros = [_fetch_quotes(p, MAX_QUOTE_PAGES) for p in dex_pools]
    disc_coros = [_fetch_quotes(p, DISCOVERED_QUOTE_MAX_PAGES) for p in discovered_pools]
    all_quote_results = await asyncio.gather(*dex_coros, *disc_coros)

    combined_quotes: list[TokenTransfer] = []
    for quotes in all_quote_results:
        combined_quotes.extend(quotes)

    quote_to_usd = dex_pools[0].quote_to_usd if dex_pools else (native_to_usd or 0.0)
    priced_buys = assign_swap_prices(buys, combined_quotes, quote_to_usd)
    priced_sells = assign_swap_prices(sells, combined_quotes, quote_to_usd)

    logger.info(
        "Quote pricing: %d/%d buys, %d/%d sells (%d quote transfers)",
        len(priced_buys), len(buys),
        len(priced_sells), len(sells),
        len(combined_quotes),
    )

    priced_buy_hashes = {s.tx_hash for s in priced_buys}
    priced_sell_hashes = {s.tx_hash for s in priced_sells}
    unpriced_buys = [b for b in buys if b.tx_hash not in priced_buy_hashes]
    unpriced_sells = [s for s in sells if s.tx_hash not in priced_sell_hashes]

    if unpriced_buys or unpriced_sells:
        receipt_buys, receipt_sells = await _price_via_receipts(
            unpriced_buys, unpriced_sells, chain_hex, quote_to_usd,
        )
        priced_buys.extend(receipt_buys)
        priced_sells.extend(receipt_sells)
        logger.info(
            "Receipt pricing: +%d buys, +%d sells | Total: %d/%d buys, %d/%d sells",
            len(receipt_buys), len(receipt_sells),
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

    chain_hex, chain_id = _resolve_chain(pairs, request.chain)
    dex_pools = _resolve_dex_pools(pairs, chain_id)

    logger.info(
        "Resolved %d DexScreener pools for %s on %s: %s",
        len(dex_pools), request.token_address[:10], chain_id,
        ", ".join(f"{p.address[:10]}(q={p.quote_token[:10]})" for p in dex_pools) or "none",
    )

    from_date = datetime.fromtimestamp(request.pump_start, tz=timezone.utc)
    to_date = datetime.fromtimestamp(request.pump_peak, tz=timezone.utc)

    from_block, to_block = await asyncio.gather(
        timestamp_to_block(chain_hex, request.pump_start),
        timestamp_to_block(chain_hex, request.pump_peak),
    )
    logger.info("Block range: %d → %d", from_block, to_block)

    priced_buys, priced_sells = await _fetch_and_price(
        dex_pools, request.token_address, chain_hex,
        from_date.isoformat(), to_date.isoformat(),
        from_block, to_block,
    )

    if not priced_buys and not priced_sells:
        return _empty_response(request)

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

    chain_hex, chain_id = _resolve_chain(pairs, request.chain)
    dex_pools = _resolve_dex_pools(pairs, chain_id)

    from_date = datetime.fromtimestamp(request.pump_start, tz=timezone.utc)
    to_date = datetime.fromtimestamp(request.pump_peak, tz=timezone.utc)

    from_block, to_block = await asyncio.gather(
        timestamp_to_block(chain_hex, request.pump_start),
        timestamp_to_block(chain_hex, request.pump_peak),
    )

    priced_buys, priced_sells = await _fetch_and_price(
        dex_pools, request.token_address, chain_hex,
        from_date.isoformat(), to_date.isoformat(),
        from_block, to_block,
    )

    if not priced_buys:
        return []

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
