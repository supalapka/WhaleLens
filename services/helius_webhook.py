import logging

import httpx

from config import settings

logger = logging.getLogger(__name__)

_HELIUS_WEBHOOKS_URL = "https://api-mainnet.helius-rpc.com/v0/webhooks"


async def subscribe_solana_addresses(addresses: list[str]) -> None:
    if settings.helius_webhook_id:
        await _update_webhook(settings.helius_webhook_id, addresses)
    else:
        webhook_id = await _create_webhook(addresses)
        logger.info("Helius webhook created: %s — add HELIUS_WEBHOOK_ID=%s to .env", webhook_id, webhook_id)


async def _create_webhook(addresses: list[str]) -> str:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            _HELIUS_WEBHOOKS_URL,
            params={"api-key": settings.helius_api_key},
            json={
                "webhookURL": settings.helius_webhook_url,
                "webhookType": "enhanced",
                "transactionTypes": ["SWAP", "TRANSFER"],
                "accountAddresses": addresses,
                "authHeader": settings.helius_webhook_secret,
            },
        )
        response.raise_for_status()
        return response.json()["webhookID"]


async def _update_webhook(webhook_id: str, addresses: list[str]) -> None:
    url = f"{_HELIUS_WEBHOOKS_URL}/{webhook_id}"
    params = {"api-key": settings.helius_api_key}

    async with httpx.AsyncClient(timeout=15) as client:
        current = (await client.get(url, params=params)).json()
        await client.put(
            url,
            params=params,
            json={
                "webhookURL": current.get("webhookURL", settings.helius_webhook_url),
                "webhookType": current.get("webhookType", "enhanced"),
                "transactionTypes": current.get("transactionTypes", ["SWAP", "TRANSFER"]),
                "accountAddresses": addresses,
                "authHeader": current.get("authHeader", settings.helius_webhook_secret),
            },
        )
    logger.info("Helius webhook %s updated with %d addresses", webhook_id, len(addresses))
