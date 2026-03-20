import asyncio
import logging
from datetime import datetime

import httpx

from config import settings
from services.early_buyers.schemas import TokenTransfer
from services.early_buyers.transfer_cache import get_cached_transfers, store_transfers

logger = logging.getLogger(__name__)

API_BASE_URL = "https://deep-index.moralis.io/api/v2.2"
MAX_RETRIES = 3
MAX_PAGES_PER_POOL = 1000


def _headers() -> dict[str, str]:
    return {
        "X-API-Key": settings.moralis_api_key,
        "Content-Type": "application/json",
    }


async def fetch_pool_transfers(
    pool_address: str,
    token_address: str,
    chain_hex: str,
    from_date_iso: str,
    to_date_iso: str,
    max_pages: int = MAX_PAGES_PER_POOL,
) -> list[TokenTransfer]:
    from_dt = datetime.fromisoformat(from_date_iso)
    to_dt = datetime.fromisoformat(to_date_iso)

    cached = await get_cached_transfers(pool_address, token_address, chain_hex, from_dt, to_dt)
    if cached is not None:
        logger.info("Cache hit for pool %s: %d transfers", pool_address[:10], len(cached))
        return cached

    url = f"{API_BASE_URL}/{pool_address}/erc20/transfers"
    transfers: list[TokenTransfer] = []
    cursor: str | None = None
    page = 0

    while page < max_pages:
        params: dict = {
            "chain": chain_hex,
            "contract_addresses[]": token_address,
            "from_date": from_date_iso,
            "to_date": to_date_iso,
            "limit": 100,
        }
        if cursor:
            params["cursor"] = cursor

        response = await _request_with_retry(url, params)
        if response is None:
            break

        data = response.json()
        for item in data.get("result", []):
            transfers.append(TokenTransfer(
                transaction_hash=item.get("transaction_hash", ""),
                from_address=item.get("from_address", "").lower(),
                to_address=item.get("to_address", "").lower(),
                value=item.get("value", "0"),
                block_timestamp=item.get("block_timestamp", ""),
                token_decimals=item.get("token_decimals", "18"),
            ))

        cursor = data.get("cursor")
        if not cursor:
            break
        page += 1

    if page >= max_pages:
        logger.warning(
            "Hit page cap (%d) for pool %s — results may be incomplete",
            max_pages, pool_address[:10],
        )

    await store_transfers(pool_address, token_address, chain_hex, from_dt, to_dt, transfers)
    return transfers


async def fetch_swaps_from_pools(
    pool_addresses: set[str],
    token_address: str,
    chain_hex: str,
    from_date_iso: str,
    to_date_iso: str,
    max_pages: int = MAX_PAGES_PER_POOL,
) -> list[TokenTransfer]:
    all_transfers: list[TokenTransfer] = []

    for pool in pool_addresses:
        transfers = await fetch_pool_transfers(
            pool, token_address, chain_hex,
            from_date_iso, to_date_iso, max_pages,
        )
        all_transfers.extend(transfers)
        logger.info("Pool %s: %d transfers", pool[:10], len(transfers))

    seen: set[str] = set()
    deduplicated: list[TokenTransfer] = []
    for t in all_transfers:
        key = f"{t.transaction_hash}:{t.from_address}:{t.to_address}:{t.value}"
        if key not in seen:
            seen.add(key)
            deduplicated.append(t)

    logger.info(
        "Fetched %d swap transfers for %s [%s → %s]",
        len(deduplicated), token_address[:10], from_date_iso, to_date_iso,
    )
    return deduplicated


async def _request_with_retry(
    url: str, params: dict, retries: int = MAX_RETRIES,
) -> httpx.Response | None:
    for attempt in range(retries):
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url, headers=_headers(), params=params, timeout=30,
            )

        if response.status_code == 200:
            return response

        if response.status_code in (429, 500, 502, 503):
            wait = 2 * (attempt + 1)
            logger.warning(
                "Moralis %s, retrying in %ds (attempt %d/%d)",
                response.status_code, wait, attempt + 1, retries,
            )
            await asyncio.sleep(wait)
            continue

        logger.error(
            "Moralis transfers failed: %s %s",
            response.status_code, response.text[:200],
        )
        return None

    logger.error("Moralis retries exhausted")
    return None
