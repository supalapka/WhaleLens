import logging

import httpx

from config import settings

logger = logging.getLogger(__name__)

STREAMS_BASE_URL = "https://api.moralis-streams.com/streams/evm"
SUPPORTED_CHAINS = ["0x1", "0x38", "0x2105", "0xa4b1"]


def _headers() -> dict[str, str]:
    return {
        "X-API-Key": settings.moralis_api_key,
        "Content-Type": "application/json",
    }


async def create_stream() -> str:
    body = {
        "webhookUrl": settings.webhook_url,
        "description": "WhaleLens wallet tracker",
        "tag": "whalelens",
        "chainIds": SUPPORTED_CHAINS,
        "includeNativeTxs": True,
        "includeContractLogs": True,
    }
    async with httpx.AsyncClient() as client:
        response = await client.put(STREAMS_BASE_URL, headers=_headers(), json=body)
        if response.status_code != 200:
            logger.error("Moralis create_stream failed: %s %s", response.status_code, response.text)
            response.raise_for_status()
        stream_id = response.json()["id"]
    logger.info("Created Moralis stream: %s", stream_id)
    return stream_id


async def subscribe_addresses(addresses: list[str]) -> dict:
    url = f"{STREAMS_BASE_URL}/{settings.moralis_stream_id}/address"
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=_headers(), json={"address": addresses})
        response.raise_for_status()
        result = response.json()
    logger.info("Subscribed %d addresses to Moralis stream", len(addresses))
    return result


async def delete_stream() -> None:
    url = f"{STREAMS_BASE_URL}/{settings.moralis_stream_id}"
    async with httpx.AsyncClient() as client:
        response = await client.delete(url, headers=_headers())
        response.raise_for_status()
    logger.info("Deleted Moralis stream: %s", settings.moralis_stream_id)
