import logging

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from database import async_session
from models.ohlcv_cache import OhlcvCache
from services.early_buyers.schemas import OhlcvCandle

logger = logging.getLogger(__name__)

_CacheKey = tuple[str, str, str]

_l1: dict[_CacheKey, tuple[int, int, list[OhlcvCandle]]] = {}


def _make_key(pool_address: str, token_address: str, network: str) -> _CacheKey:
    return pool_address.lower(), token_address.lower(), network


async def get_cached_ohlcv(
    pool_address: str,
    token_address: str,
    network: str,
    start_ts: int,
    end_ts: int,
) -> list[OhlcvCandle] | None:
    key = _make_key(pool_address, token_address, network)

    entry = _l1.get(key)
    if entry and entry[0] <= start_ts and end_ts <= entry[1]:
        candles = [c for c in entry[2] if start_ts <= c.timestamp <= end_ts]
        logger.debug("L1 OHLCV cache hit for %s: %d candles", pool_address[:10], len(candles))
        return candles

    async with async_session() as session:
        stmt = (
            select(OhlcvCache)
            .where(
                OhlcvCache.pool_address == pool_address.lower(),
                OhlcvCache.token_address == token_address.lower(),
                OhlcvCache.network == network,
                OhlcvCache.start_ts <= start_ts,
                OhlcvCache.end_ts >= end_ts,
            )
            .limit(1)
        )
        row = (await session.execute(stmt)).scalar_one_or_none()

    if row is None:
        return None

    candles = [OhlcvCandle(**item) for item in row.candles_json]
    _l1[key] = (row.start_ts, row.end_ts, candles)

    result = [c for c in candles if start_ts <= c.timestamp <= end_ts]
    logger.debug("DB OHLCV cache hit for %s: %d candles", pool_address[:10], len(result))
    return result


async def store_ohlcv(
    pool_address: str,
    token_address: str,
    network: str,
    start_ts: int,
    end_ts: int,
    candles: list[OhlcvCandle],
) -> None:
    key = _make_key(pool_address, token_address, network)
    pool_lower = pool_address.lower()
    token_lower = token_address.lower()
    candles_json = [c.model_dump() for c in candles]

    stmt = insert(OhlcvCache).values(
        pool_address=pool_lower,
        token_address=token_lower,
        network=network,
        start_ts=start_ts,
        end_ts=end_ts,
        candles_json=candles_json,
    ).on_conflict_do_update(
        index_elements=["pool_address", "token_address", "network"],
        set_={
            "start_ts": start_ts,
            "end_ts": end_ts,
            "candles_json": candles_json,
        },
    )

    async with async_session() as session:
        await session.execute(stmt)
        await session.commit()

    _l1[key] = (start_ts, end_ts, candles)
    logger.debug(
        "Stored %d OHLCV candles for %s [%d → %d]",
        len(candles), pool_address[:10], start_ts, end_ts,
    )
