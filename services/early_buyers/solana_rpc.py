import asyncio
import logging
from typing import Any

import httpx

from config import settings

logger = logging.getLogger(__name__)

MAX_RETRIES = 5
_semaphore = asyncio.Semaphore(3)
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        headers = {"x-api-key": settings.solana_rpc_api_key} if settings.solana_rpc_api_key else {}
        _client = httpx.AsyncClient(timeout=30, headers=headers)
    return _client


async def solana_rpc_call(method: str, params: list) -> Any:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }

    async with _semaphore:
        for attempt in range(MAX_RETRIES):
            response = await _get_client().post(settings.solana_rpc_url, json=payload)

            if response.status_code == 200:
                data = response.json()
                if "error" in data:
                    logger.error("Solana RPC error %s: %s", method, data["error"])
                    return None
                return data.get("result")

            if response.status_code in (429, 500, 502, 503):
                wait = 3 * (attempt + 1)
                logger.warning(
                    "Solana RPC %s, retrying in %ds (attempt %d/%d)",
                    response.status_code, wait, attempt + 1, MAX_RETRIES,
                )
                await asyncio.sleep(wait)
                continue

            logger.error("Solana RPC failed: %s %s", response.status_code, response.text[:200])
            return None

    logger.error("Solana RPC retries exhausted for %s", method)
    return None


async def solana_rpc_batch(requests: list[dict]) -> list[Any]:
    payload = [
        {"jsonrpc": "2.0", "id": i, "method": r["method"], "params": r["params"]}
        for i, r in enumerate(requests)
    ]

    async with _semaphore:
        for attempt in range(MAX_RETRIES):
            response = await _get_client().post(settings.solana_rpc_url, json=payload)

            if response.status_code == 200:
                data = response.json()
                results = [None] * len(requests)
                for item in data:
                    idx = item.get("id", 0)
                    if "error" in item:
                        logger.warning("Solana batch item %d error: %s", idx, item["error"])
                    else:
                        results[idx] = item.get("result")
                return results

            if response.status_code in (429, 500, 502, 503):
                wait = 3 * (attempt + 1)
                logger.warning(
                    "Solana RPC batch %s, retrying in %ds (attempt %d/%d)",
                    response.status_code, wait, attempt + 1, MAX_RETRIES,
                )
                await asyncio.sleep(wait)
                continue

            logger.error("Solana RPC batch failed: %s %s", response.status_code, response.text[:200])
            return [None] * len(requests)

    logger.error("Solana RPC batch retries exhausted")
    return [None] * len(requests)
