import logging
from datetime import datetime, timezone

import httpx

from services.schemas import TokenData

logger = logging.getLogger(__name__)

BASE_URL = "https://api.dexscreener.com/latest/dex/tokens"


async def get_token_data(token_address: str) -> TokenData | None:
    url = f"{BASE_URL}/{token_address}"
    async with httpx.AsyncClient() as client:
        response = await client.get(url, timeout=10)

    if response.status_code != 200:
        logger.error("DexScreener returned %s for %s", response.status_code, token_address)
        return None

    data = response.json()
    pairs = data.get("pairs")
    if not pairs:
        logger.warning("No pairs found for %s", token_address)
        return None

    pair = pairs[0]

    created_at_ms = pair.get("pairCreatedAt", 0)
    if created_at_ms:
        created_at_date = datetime.fromtimestamp(created_at_ms / 1000, tz=timezone.utc)
        age_days = (datetime.now(timezone.utc) - datetime.fromtimestamp(created_at_ms / 1000, tz=timezone.utc)).days
    else:
        created_at_date = None
        age_days = 0

    txns_24h = pair.get("txns", {}).get("h24", {})

    return TokenData(
        symbol=pair.get("baseToken", {}).get("symbol", "???"),
        liquidity_usd=float(pair.get("liquidity", {}).get("usd", 0)),
        price_usd=float(pair.get("priceUsd", 0)),
        price_impact_pct=float(pair.get("priceImpact", 0)),
        pair_created_at=created_at_ms,
        pair_created_at_date=created_at_date.strftime("%Y-%m-%d") if created_at_date else None,
        token_age_days=age_days,
        txns_24h=txns_24h.get("buys", 0) + txns_24h.get("sells", 0),
    )
