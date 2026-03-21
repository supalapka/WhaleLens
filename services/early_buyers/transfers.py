import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from database import async_session
from models.constants import AVG_BLOCK_TIME
from models.receipt_cache import ReceiptCache
from services.early_buyers.block_lookup import timestamp_to_block
from services.early_buyers.rpc import rpc_batch, rpc_call
from services.early_buyers.schemas import TokenTransfer
from services.early_buyers.transfer_cache import get_cached_transfers, store_transfers

logger = logging.getLogger(__name__)

MAX_PAGES = 1000


async def _fetch_asset_transfers(
    chain_hex: str,
    token_address: str,
    from_block: int,
    to_block: int,
    from_address: str | None = None,
    to_address: str | None = None,
    max_pages: int = MAX_PAGES,
) -> list[dict]:
    all_transfers: list[dict] = []
    page_key: str | None = None
    page = 0

    while page < max_pages:
        params: dict = {
            "fromBlock": hex(from_block),
            "toBlock": hex(to_block),
            "contractAddresses": [token_address],
            "category": ["erc20"],
            "maxCount": "0x3e8",
            "withMetadata": True,
        }
        if from_address:
            params["fromAddress"] = from_address
        if to_address:
            params["toAddress"] = to_address
        if page_key:
            params["pageKey"] = page_key

        result = await rpc_call(chain_hex, "alchemy_getAssetTransfers", [params])
        if not result:
            break

        transfers = result.get("transfers", [])
        all_transfers.extend(transfers)

        page_key = result.get("pageKey")
        if not page_key:
            break
        page += 1

    return all_transfers


def _parse_transfer(
    t: dict,
    chain_hex: str = "",
    from_block: int = 0,
    from_ts: float = 0,
) -> TokenTransfer | None:
    raw_value = t.get("rawContract", {}).get("value")
    if not raw_value or raw_value == "0x":
        return None

    value = str(int(raw_value, 16))
    decimals = t.get("rawContract", {}).get("decimal")
    token_decimals = str(int(decimals, 16)) if decimals else "18"

    block_ts = (t.get("metadata") or {}).get("blockTimestamp", "")
    if not block_ts:
        avg = AVG_BLOCK_TIME.get(chain_hex, 0)
        block_hex = t.get("blockNum", "0x0")
        if avg and block_hex and from_ts:
            block_num = int(block_hex, 16)
            estimated = from_ts + (block_num - from_block) * avg
            block_ts = datetime.fromtimestamp(estimated, tz=timezone.utc).isoformat()
        else:
            return None

    return TokenTransfer(
        transaction_hash=t.get("hash", ""),
        from_address=t.get("from", "").lower(),
        to_address=t.get("to", "").lower(),
        value=value,
        block_timestamp=block_ts,
        token_decimals=token_decimals,
    )


async def fetch_pool_transfers(
    pool_address: str,
    token_address: str,
    chain_hex: str,
    from_date_iso: str,
    to_date_iso: str,
    from_block: int | None = None,
    to_block: int | None = None,
) -> list[TokenTransfer]:
    from_dt = datetime.fromisoformat(from_date_iso)
    to_dt = datetime.fromisoformat(to_date_iso)

    cached = await get_cached_transfers(pool_address, token_address, chain_hex, from_dt, to_dt)
    if cached is not None:
        logger.info("Cache hit for pool %s: %d transfers", pool_address[:10], len(cached))
        return cached

    if from_block is None or to_block is None:
        from_ts = int(from_dt.timestamp())
        to_ts = int(to_dt.timestamp())
        from_block, to_block = await asyncio.gather(
            timestamp_to_block(chain_hex, from_ts),
            timestamp_to_block(chain_hex, to_ts),
        )
    logger.info(
        "Block range for %s: %d → %d (%d blocks)",
        token_address[:10], from_block, to_block, to_block - from_block,
    )

    buy_raw, sell_raw = await asyncio.gather(
        _fetch_asset_transfers(
            chain_hex, token_address, from_block, to_block,
            from_address=pool_address,
        ),
        _fetch_asset_transfers(
            chain_hex, token_address, from_block, to_block,
            to_address=pool_address,
        ),
    )

    logger.info(
        "Fetched %d buy + %d sell raw transfers for pool %s",
        len(buy_raw), len(sell_raw), pool_address[:10],
    )

    seen: set[str] = set()
    transfers: list[TokenTransfer] = []

    ft = from_dt.timestamp()
    for raw in buy_raw + sell_raw:
        parsed = _parse_transfer(raw, chain_hex, from_block, ft)
        if not parsed:
            continue
        dedup_key = f"{parsed.transaction_hash}:{parsed.from_address}:{parsed.to_address}:{parsed.value}"
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        transfers.append(parsed)

    logger.info(
        "Parsed %d transfers for pool %s [%s → %s]",
        len(transfers), pool_address[:10], from_date_iso, to_date_iso,
    )

    await store_transfers(pool_address, token_address, chain_hex, from_dt, to_dt, transfers)
    return transfers


_ALL_POOLS_SENTINEL = "_all"


async def fetch_all_token_transfers(
    token_address: str,
    chain_hex: str,
    from_date_iso: str,
    to_date_iso: str,
    from_block: int,
    to_block: int,
) -> list[TokenTransfer]:
    from_dt = datetime.fromisoformat(from_date_iso)
    to_dt = datetime.fromisoformat(to_date_iso)

    cached = await get_cached_transfers(_ALL_POOLS_SENTINEL, token_address, chain_hex, from_dt, to_dt)
    if cached is not None:
        logger.info("Cache hit for all transfers %s: %d transfers", token_address[:10], len(cached))
        return cached

    raw = await _fetch_asset_transfers(
        chain_hex, token_address, from_block, to_block,
    )
    logger.info("Fetched %d raw token transfers for %s", len(raw), token_address[:10])

    seen: set[str] = set()
    transfers: list[TokenTransfer] = []

    ft = from_dt.timestamp()
    for r in raw:
        parsed = _parse_transfer(r, chain_hex, from_block, ft)
        if not parsed:
            continue
        dedup_key = f"{parsed.transaction_hash}:{parsed.from_address}:{parsed.to_address}:{parsed.value}"
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        transfers.append(parsed)

    logger.info("Parsed %d token transfers for %s", len(transfers), token_address[:10])

    await store_transfers(_ALL_POOLS_SENTINEL, token_address, chain_hex, from_dt, to_dt, transfers)
    return transfers


async def fetch_quote_transfers(
    pool_address: str,
    quote_token_address: str,
    chain_hex: str,
    from_block: int,
    to_block: int,
    max_pages: int = MAX_PAGES,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
) -> list[TokenTransfer]:
    if from_dt and to_dt:
        cached = await get_cached_transfers(pool_address, quote_token_address, chain_hex, from_dt, to_dt)
        if cached is not None:
            logger.info("Cache hit for quote transfers pool %s: %d transfers", pool_address[:10], len(cached))
            return cached

    inbound_raw, outbound_raw = await asyncio.gather(
        _fetch_asset_transfers(
            chain_hex, quote_token_address, from_block, to_block,
            to_address=pool_address,
            max_pages=max_pages,
        ),
        _fetch_asset_transfers(
            chain_hex, quote_token_address, from_block, to_block,
            from_address=pool_address,
            max_pages=max_pages,
        ),
    )

    logger.info(
        "Fetched %d inbound + %d outbound quote transfers for pool %s",
        len(inbound_raw), len(outbound_raw), pool_address[:10],
    )

    seen: set[str] = set()
    transfers: list[TokenTransfer] = []

    ft = from_dt.timestamp() if from_dt else 0
    for raw in inbound_raw + outbound_raw:
        parsed = _parse_transfer(raw, chain_hex, from_block, ft)
        if not parsed:
            continue
        dedup_key = f"{parsed.transaction_hash}:{parsed.from_address}:{parsed.to_address}:{parsed.value}"
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        transfers.append(parsed)

    logger.info(
        "Parsed %d quote transfers for pool %s",
        len(transfers), pool_address[:10],
    )

    if from_dt and to_dt:
        await store_transfers(pool_address, quote_token_address, chain_hex, from_dt, to_dt, transfers)

    return transfers


_receipt_l1: dict[tuple[str, str], list[dict]] = {}

RECEIPT_DB_BATCH = 500


async def _load_cached_receipts(
    chain_hex: str, tx_hashes: list[str],
) -> dict[str, list[dict]]:
    cached: dict[str, list[dict]] = {}
    unchecked: list[str] = []

    for h in tx_hashes:
        l1_val = _receipt_l1.get((chain_hex, h))
        if l1_val is not None:
            cached[h] = l1_val
        else:
            unchecked.append(h)

    if not unchecked:
        return cached

    async with async_session() as session:
        for i in range(0, len(unchecked), RECEIPT_DB_BATCH):
            batch = unchecked[i:i + RECEIPT_DB_BATCH]
            stmt = select(ReceiptCache).where(
                ReceiptCache.chain == chain_hex,
                ReceiptCache.tx_hash.in_(batch),
            )
            rows = (await session.execute(stmt)).scalars().all()
            for row in rows:
                cached[row.tx_hash] = row.logs_json
                _receipt_l1[(chain_hex, row.tx_hash)] = row.logs_json

    return cached


async def _store_receipts(
    chain_hex: str, new_receipts: dict[str, list[dict]],
) -> None:
    if not new_receipts:
        return

    values = [
        {"chain": chain_hex, "tx_hash": h, "logs_json": logs}
        for h, logs in new_receipts.items()
    ]

    async with async_session() as session:
        for i in range(0, len(values), RECEIPT_DB_BATCH):
            batch = values[i:i + RECEIPT_DB_BATCH]
            stmt = insert(ReceiptCache).values(batch).on_conflict_do_nothing()
            await session.execute(stmt)
        await session.commit()


RECEIPT_RETRY_ROUNDS = 5
RECEIPT_RETRY_DELAY = 5.0


async def fetch_tx_receipts(
    chain_hex: str,
    tx_hashes: list[str],
) -> dict[str, list[dict]]:
    cached = await _load_cached_receipts(chain_hex, tx_hashes)
    remaining = [h for h in tx_hashes if h not in cached]

    receipts = dict(cached)
    all_new: dict[str, list[dict]] = {}

    for attempt in range(RECEIPT_RETRY_ROUNDS):
        if not remaining:
            break

        calls = [("eth_getTransactionReceipt", [h]) for h in remaining]
        results = await rpc_batch(chain_hex, calls)

        fetched_this_round = 0
        for tx_hash, result in zip(remaining, results):
            if result and "logs" in result:
                receipts[tx_hash] = result["logs"]
                all_new[tx_hash] = result["logs"]
                _receipt_l1[(chain_hex, tx_hash)] = result["logs"]
                fetched_this_round += 1

        remaining = [h for h in remaining if h not in receipts]

        if remaining and attempt < RECEIPT_RETRY_ROUNDS - 1:
            logger.warning(
                "Receipt fetch: %d/%d still missing after round %d, retrying in %.0fs",
                len(remaining), len(tx_hashes), attempt + 1, RECEIPT_RETRY_DELAY,
            )
            await asyncio.sleep(RECEIPT_RETRY_DELAY)

    await _store_receipts(chain_hex, all_new)

    if remaining:
        logger.warning(
            "Receipt fetch incomplete: %d/%d missing after %d rounds",
            len(remaining), len(tx_hashes), RECEIPT_RETRY_ROUNDS,
        )

    logger.info(
        "Fetched %d/%d receipts (%d cached, %d retried)",
        len(receipts), len(tx_hashes),
        len(tx_hashes) - len(remaining) - len(all_new),
        len(all_new),
    )
    return receipts
