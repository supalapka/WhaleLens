import asyncio
import logging
from datetime import datetime, timezone

from services.early_buyers.block_lookup import timestamp_to_block
from services.early_buyers.rpc import rpc_call
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
) -> list[dict]:
    all_transfers: list[dict] = []
    page_key: str | None = None
    page = 0

    while page < MAX_PAGES:
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


def _parse_transfer(t: dict) -> TokenTransfer | None:
    raw_value = t.get("rawContract", {}).get("value")
    if not raw_value or raw_value == "0x":
        return None

    value = str(int(raw_value, 16))
    decimals = t.get("rawContract", {}).get("decimal")
    token_decimals = str(int(decimals, 16)) if decimals else "18"

    block_ts = t.get("metadata", {}).get("blockTimestamp", "")

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

    for raw in buy_raw + sell_raw:
        parsed = _parse_transfer(raw)
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


async def fetch_quote_transfers(
    pool_address: str,
    quote_token_address: str,
    chain_hex: str,
    from_block: int,
    to_block: int,
) -> list[TokenTransfer]:
    inbound_raw, outbound_raw = await asyncio.gather(
        _fetch_asset_transfers(
            chain_hex, quote_token_address, from_block, to_block,
            to_address=pool_address,
        ),
        _fetch_asset_transfers(
            chain_hex, quote_token_address, from_block, to_block,
            from_address=pool_address,
        ),
    )

    logger.info(
        "Fetched %d inbound + %d outbound quote transfers for pool %s",
        len(inbound_raw), len(outbound_raw), pool_address[:10],
    )

    seen: set[str] = set()
    transfers: list[TokenTransfer] = []

    for raw in inbound_raw + outbound_raw:
        parsed = _parse_transfer(raw)
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
    return transfers
