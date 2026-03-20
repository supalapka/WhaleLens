import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from database import async_session
from models.transfer_cache import TransferCache
from services.early_buyers.schemas import TokenTransfer

logger = logging.getLogger(__name__)

_CacheKey = tuple[str, str, str]


@dataclass(frozen=True, slots=True)
class _CacheEntry:
    from_dt: datetime
    to_dt: datetime
    transfers: list[TokenTransfer] = field(hash=False)


_l1: dict[_CacheKey, _CacheEntry] = {}


def _make_key(pool_address: str, token_address: str, chain: str) -> _CacheKey:
    return pool_address.lower(), token_address.lower(), chain


def _filter_by_window(
    transfers: list[TokenTransfer], from_dt: datetime, to_dt: datetime,
) -> list[TokenTransfer]:
    return [t for t in transfers if from_dt <= t.timestamp_dt <= to_dt]


async def get_cached_transfers(
    pool_address: str,
    token_address: str,
    chain: str,
    from_dt: datetime,
    to_dt: datetime,
) -> list[TokenTransfer] | None:
    key = _make_key(pool_address, token_address, chain)

    entry = _l1.get(key)
    if entry and entry.from_dt <= from_dt and to_dt <= entry.to_dt:
        filtered = _filter_by_window(entry.transfers, from_dt, to_dt)
        logger.debug("L1 cache hit for %s: %d transfers", pool_address[:10], len(filtered))
        return filtered

    async with async_session() as session:
        stmt = (
            select(TransferCache)
            .where(
                TransferCache.pool_address == pool_address.lower(),
                TransferCache.token_address == token_address.lower(),
                TransferCache.chain == chain,
                TransferCache.from_dt <= from_dt,
                TransferCache.to_dt >= to_dt,
            )
            .limit(1)
        )
        row = (await session.execute(stmt)).scalar_one_or_none()

    if row is None:
        return None

    transfers = [TokenTransfer(**item) for item in row.transfers_json]
    _l1[key] = _CacheEntry(from_dt=row.from_dt, to_dt=row.to_dt, transfers=transfers)

    filtered = _filter_by_window(transfers, from_dt, to_dt)
    logger.debug("DB cache hit for %s: %d transfers", pool_address[:10], len(filtered))
    return filtered


async def store_transfers(
    pool_address: str,
    token_address: str,
    chain: str,
    from_dt: datetime,
    to_dt: datetime,
    transfers: list[TokenTransfer],
) -> None:
    key = _make_key(pool_address, token_address, chain)
    pool_lower = pool_address.lower()
    token_lower = token_address.lower()
    transfers_json = [t.model_dump() for t in transfers]

    stmt = insert(TransferCache).values(
        pool_address=pool_lower,
        token_address=token_lower,
        chain=chain,
        from_dt=from_dt,
        to_dt=to_dt,
        transfers_json=transfers_json,
    ).on_conflict_do_update(
        index_elements=["pool_address", "token_address", "chain"],
        set_={
            "from_dt": from_dt,
            "to_dt": to_dt,
            "transfers_json": transfers_json,
        },
    )

    async with async_session() as session:
        await session.execute(stmt)
        await session.commit()

    _l1[key] = _CacheEntry(from_dt=from_dt, to_dt=to_dt, transfers=transfers)
    logger.debug(
        "Stored %d transfers for %s [%s → %s]",
        len(transfers), pool_address[:10], from_dt.isoformat(), to_dt.isoformat(),
    )
