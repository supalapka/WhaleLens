import asyncio
import logging
from typing import Any

import httpx

from config import settings
from models.constants import ALCHEMY_RPC_URLS
from services.early_buyers.exceptions import UnsupportedChainError

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BATCH_SIZE = 100
BATCH_DELAY = 0.25


def _get_rpc_url(chain_hex: str) -> str:
    base_url = ALCHEMY_RPC_URLS.get(chain_hex)
    if not base_url:
        raise UnsupportedChainError(
            f"Chain {chain_hex} is not supported. "
            f"Supported: {', '.join(ALCHEMY_RPC_URLS)}"
        )
    return f"{base_url}/{settings.alchemy_api_key}"


async def rpc_call(chain_hex: str, method: str, params: list) -> Any:
    url = _get_rpc_url(chain_hex)
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }

    for attempt in range(MAX_RETRIES):
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=30)

        if response.status_code == 200:
            data = response.json()
            if "error" in data:
                logger.error("RPC error %s: %s", method, data["error"])
                return None
            return data.get("result")

        if response.status_code in (429, 500, 502, 503):
            wait = 2 * (attempt + 1)
            logger.warning(
                "Alchemy %s, retrying in %ds (attempt %d/%d)",
                response.status_code, wait, attempt + 1, MAX_RETRIES,
            )
            await asyncio.sleep(wait)
            continue

        logger.error("Alchemy RPC failed: %s %s", response.status_code, response.text[:200])
        return None

    logger.error("Alchemy RPC retries exhausted for %s", method)
    return None


async def rpc_batch(chain_hex: str, calls: list[tuple[str, list]]) -> list[Any]:
    url = _get_rpc_url(chain_hex)
    results: list[Any] = [None] * len(calls)

    for batch_start in range(0, len(calls), BATCH_SIZE):
        batch = calls[batch_start:batch_start + BATCH_SIZE]
        payload = [
            {"jsonrpc": "2.0", "id": batch_start + i, "method": method, "params": params}
            for i, (method, params) in enumerate(batch)
        ]

        response_data = None
        for attempt in range(MAX_RETRIES):
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, timeout=60)

            if response.status_code == 200:
                response_data = response.json()
                break

            if response.status_code in (429, 500, 502, 503):
                wait = 2 * (attempt + 1)
                logger.warning(
                    "Alchemy batch %s, retrying in %ds (attempt %d/%d)",
                    response.status_code, wait, attempt + 1, MAX_RETRIES,
                )
                await asyncio.sleep(wait)
                continue

            logger.error("Alchemy batch failed: %s", response.status_code)
            break

        if response_data:
            for item in response_data:
                idx = item.get("id")
                if idx is not None and "result" in item:
                    results[idx] = item["result"]

        if batch_start + BATCH_SIZE < len(calls):
            await asyncio.sleep(BATCH_DELAY)

    return results
