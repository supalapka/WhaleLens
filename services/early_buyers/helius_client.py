import asyncio
import logging
from datetime import datetime

import httpx

from config import settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.helius.xyz"
_SIG_PAGE_LIMIT = 1000
_BULK_BATCH_SIZE = 100
_BULK_CONCURRENCY = 10
_MAX_RETRIES = 5
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=30)
    return _client


def _helius_rpc_url() -> str:
    return f"https://mainnet.helius-rpc.com/?api-key={settings.helius_api_key}"


async def fetch_token_swaps(
    mint: str,
    from_dt: datetime,
    to_dt: datetime,
    before: str | None = None,
) -> list[dict]:
    from_ts = int(from_dt.timestamp())
    to_ts = int(to_dt.timestamp())

    sigs = await _fetch_signatures_in_window(mint, from_ts, to_ts)
    logger.info("Collected %d signatures for %s", len(sigs), mint[:10])

    sem = asyncio.Semaphore(_BULK_CONCURRENCY)
    return await _fetch_transactions_bulk(sigs, sem)


async def _fetch_signatures_in_window(mint: str, from_ts: int, to_ts: int) -> list[str]:
    cursor: str | None = None
    collected: list[str] = []

    while True:
        options: dict = {"limit": _SIG_PAGE_LIMIT}
        if cursor:
            options["before"] = cursor

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getSignaturesForAddress",
            "params": [mint, options],
        }

        page = await _rpc_with_retry(payload)
        if not page:
            break

        page_min_ts = min((item.get("blockTime") or 0) for item in page)
        if page_min_ts > to_ts:
            cursor = page[-1]["signature"]
            logger.info("Fast-skip sig page (min_ts=%d > to_ts=%d)", page_min_ts, to_ts)
            continue

        done = False
        for item in page:
            ts = item.get("blockTime") or 0
            sig = item.get("signature", "")
            if ts > to_ts:
                continue
            if ts < from_ts:
                done = True
                break
            if sig:
                collected.append(sig)

        logger.info("Sig page: %d items, collected=%d total", len(page), len(collected))

        if done or len(page) < _SIG_PAGE_LIMIT:
            break

        cursor = page[-1]["signature"]

    return collected


async def _fetch_transactions_bulk(signatures: list[str], sem: asyncio.Semaphore) -> list[dict]:
    url = f"{_BASE_URL}/v0/transactions"
    batches = [
        signatures[i: i + _BULK_BATCH_SIZE]
        for i in range(0, len(signatures), _BULK_BATCH_SIZE)
    ]

    async def fetch_batch(batch: list[str]) -> list[dict]:
        async with sem:
            for attempt in range(_MAX_RETRIES):
                try:
                    response = await _get_client().post(
                        url,
                        params={"api-key": settings.helius_api_key},
                        json={"transactions": batch},
                    )
                except (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadError) as exc:
                    wait = 3 * (attempt + 1)
                    logger.warning("Helius bulk transport error: %s, retrying in %ds", exc, wait)
                    await asyncio.sleep(wait)
                    continue

                if response.status_code == 200:
                    return [tx for tx in response.json() if tx]
                if response.status_code in (429, 500, 502, 503):
                    wait = 3 * (attempt + 1)
                    logger.warning("Helius bulk %s, retrying in %ds", response.status_code, wait)
                    await asyncio.sleep(wait)
                    continue
                logger.error("Helius bulk failed: %s %s", response.status_code, response.text[:200])
                return []
            logger.error("Helius bulk retries exhausted")
            return []

    results = await asyncio.gather(*[fetch_batch(b) for b in batches])
    return [tx for batch_result in results for tx in batch_result]


async def _rpc_with_retry(payload: dict) -> list[dict]:
    url = _helius_rpc_url()
    for attempt in range(_MAX_RETRIES):
        try:
            response = await _get_client().post(url, json=payload)
        except (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadError) as exc:
            wait = 3 * (attempt + 1)
            logger.warning("Helius RPC transport error: %s, retrying in %ds", exc, wait)
            await asyncio.sleep(wait)
            continue

        if response.status_code == 200:
            data = response.json()
            if "error" in data:
                logger.error("Helius RPC error: %s", data["error"])
                return []
            return data.get("result") or []
        if response.status_code in (429, 500, 502, 503):
            wait = 3 * (attempt + 1)
            logger.warning("Helius RPC %s, retrying in %ds", response.status_code, wait)
            await asyncio.sleep(wait)
            continue
        logger.error("Helius RPC failed: %s %s", response.status_code, response.text[:200])
        return []
    logger.error("Helius RPC retries exhausted")
    return []
