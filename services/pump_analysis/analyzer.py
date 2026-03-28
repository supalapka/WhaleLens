import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from database import async_session
from models.constants import CHAIN_BY_SHORT_NAME
from models.transaction import Transaction
from models.wallet import Wallet
from services.checkers.dexscreener import get_token_pairs
from services.checkers.geckoterminal import get_ohlcv_range
from services.early_buyers.schemas import OhlcvCandle
from services.pump_analysis.exceptions import NoBscTransactionsError
from services.pump_analysis.ohlcv_cache import store_ohlcv, get_cached_ohlcv
from services.pump_analysis.schemas import PumpAnalysisResponse, PumpResult

logger = logging.getLogger(__name__)

PUMP_THRESHOLD = 3.0
WINDOW_HOURS = 96
CANDLE_TIMEFRAME = "minute"
CANDLE_AGGREGATE = 15
RATE_LIMIT_DELAY = 5.0


@dataclass
class _TokenOhlcv:
    pool_address: str
    candles: list[OhlcvCandle]


def _find_nearest_candle_price(
    candles: list[OhlcvCandle], target_ts: int,
) -> float | None:
    if not candles:
        return None
    best = min(candles, key=lambda c: abs(c.timestamp - target_ts))
    return best.close


def _find_max_high_in_window(
    candles: list[OhlcvCandle], start_ts: int, end_ts: int,
) -> float | None:
    window = [c for c in candles if start_ts <= c.timestamp <= end_ts]
    if not window:
        return None
    return max(c.high for c in window)


async def _fetch_bsc_transactions() -> list:
    stmt = (
        select(
            Transaction.id,
            Transaction.wallet_id,
            Transaction.token_address,
            Transaction.token_symbol,
            Transaction.created_at,
            Wallet.address.label("wallet_address"),
        )
        .join(Wallet, Transaction.wallet_id == Wallet.id)
        .where(Transaction.chain == "BSC")
        .order_by(Transaction.created_at.asc())
    )

    async with async_session() as session:
        result = await session.execute(stmt)
        return result.all()


async def _resolve_bsc_pool(token_address: str) -> str | None:
    pairs = await get_token_pairs(token_address)
    chain_name = CHAIN_BY_SHORT_NAME["BSC"].name
    for pair in pairs:
        if pair["chain_id"] == chain_name:
            return pair["pair_address"]
    return None


async def _fetch_token_ohlcv(
    token_address: str,
    pool_address: str,
    start_ts: int,
    end_ts: int,
) -> tuple[_TokenOhlcv | None, bool]:
    network = CHAIN_BY_SHORT_NAME["BSC"].gecko_network
    now_ts = int(datetime.now(timezone.utc).timestamp())
    end_ts = min(end_ts, now_ts)
    end_ts = end_ts - (end_ts % 3600)

    cached = await get_cached_ohlcv(
        pool_address, token_address, network, start_ts, end_ts,
    )
    if cached is not None:
        logger.info("OHLCV cache hit for %s: %d candles", token_address[:10], len(cached))
        return _TokenOhlcv(pool_address=pool_address, candles=cached), True

    candles = await get_ohlcv_range(
        network=network,
        pool_address=pool_address,
        start_ts=start_ts,
        end_ts=end_ts,
        timeframe=CANDLE_TIMEFRAME,
        aggregate=CANDLE_AGGREGATE,
    )

    if not candles:
        logger.warning("No OHLCV candles for %s, skipping", token_address[:10])
        return None, False

    await store_ohlcv(pool_address, token_address, network, start_ts, end_ts, candles)
    return _TokenOhlcv(pool_address=pool_address, candles=candles), False


async def run_pump_analysis() -> PumpAnalysisResponse:
    rows = await _fetch_bsc_transactions()
    if not rows:
        raise NoBscTransactionsError("No BSC transactions found in the database")

    logger.info("Loaded %d BSC transactions", len(rows))

    token_txs: dict[str, list] = defaultdict(list)
    for row in rows:
        token_txs[row.token_address].append(row)

    unique_tokens = list(token_txs.keys())
    logger.info("Found %d unique tokens to analyze", len(unique_tokens))

    pool_cache: dict[str, str | None] = {}
    for token_address in unique_tokens:
        pool_cache[token_address] = await _resolve_bsc_pool(token_address)
        if pool_cache[token_address] is None:
            logger.warning("No BSC pool for %s, skipping", token_address[:10])

    window_seconds = WINDOW_HOURS * 3600
    ohlcv_cache: dict[str, _TokenOhlcv | None] = {}
    tokens_with_pools = [t for t in unique_tokens if pool_cache[t] is not None]

    for i, token_address in enumerate(tokens_with_pools):
        txs = token_txs[token_address]
        earliest_dt = min(tx.created_at for tx in txs)
        latest_dt = max(tx.created_at for tx in txs)

        if earliest_dt.tzinfo is None:
            earliest_dt = earliest_dt.replace(tzinfo=timezone.utc)
        if latest_dt.tzinfo is None:
            latest_dt = latest_dt.replace(tzinfo=timezone.utc)

        start_ts = int(earliest_dt.timestamp())
        end_ts = int((latest_dt + timedelta(hours=WINDOW_HOURS)).timestamp())

        result, was_cached = await _fetch_token_ohlcv(
            token_address, pool_cache[token_address], start_ts, end_ts,
        )
        ohlcv_cache[token_address] = result

        if not was_cached and i < len(tokens_with_pools) - 1:
            await asyncio.sleep(RATE_LIMIT_DELAY)

    tokens_skipped = sum(
        1 for t in unique_tokens
        if pool_cache.get(t) is None or ohlcv_cache.get(t) is None
    )

    results: list[PumpResult] = []
    for row in rows:
        token_data = ohlcv_cache.get(row.token_address)
        if token_data is None:
            continue

        created_at = row.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        tx_ts = int(created_at.timestamp())

        price_at_tx = _find_nearest_candle_price(token_data.candles, tx_ts)
        if price_at_tx is None or price_at_tx <= 0:
            continue

        window_end = tx_ts + window_seconds
        max_high = _find_max_high_in_window(token_data.candles, tx_ts, window_end)
        if max_high is None:
            continue

        if max_high >= PUMP_THRESHOLD * price_at_tx:
            results.append(PumpResult(
                wallet_id=row.wallet_id,
                wallet_address=row.wallet_address,
                tx_id=row.id,
                token_symbol=row.token_symbol or "???",
                token_address=row.token_address,
                price_at_tx=price_at_tx,
                max_price_after=max_high,
                gain_multiple=round(max_high / price_at_tx, 2),
            ))

    logger.info(
        "Pump analysis complete: %d/%d transactions had 3x+ pump",
        len(results), len(rows),
    )

    return PumpAnalysisResponse(
        total_bsc_transactions=len(rows),
        unique_tokens_scanned=len(unique_tokens),
        tokens_skipped=tokens_skipped,
        results=results,
    )
