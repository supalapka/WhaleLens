import logging
import time
from datetime import datetime, timezone

import httpx

from services.schemas import TokenData

logger = logging.getLogger(__name__)

BASE_URL = "https://api.dexscreener.com/latest/dex/tokens"
CACHE_TTL = 3600
_cache: dict[str, tuple[float, TokenData]] = {}


async def get_token_data(token_address: str) -> TokenData | None:
    key = token_address.lower()
    if key in _cache:
        cached_at, cached_data = _cache[key]
        if time.monotonic() - cached_at < CACHE_TTL:
            logger.debug("DexScreener cache hit for %s", token_address)
            return cached_data
        del _cache[key]

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

    base_pair = next(
        (p for p in pairs if p.get("baseToken", {}).get("address", "").lower() == key),
        None,
    )

    if base_pair:
        pair = base_pair
        price_usd = float(pair.get("priceUsd", 0))
        symbol = pair.get("baseToken", {}).get("symbol", "???")
    else:
        pair = pairs[0]
        base_price_usd = float(pair.get("priceUsd", 0))
        price_native = float(pair.get("priceNative", 0))
        price_usd = base_price_usd / price_native if price_native > 0 else 0.0
        symbol = pair.get("quoteToken", {}).get("symbol", "???")

    created_at_ms = pair.get("pairCreatedAt", 0)
    if created_at_ms:
        created_at_date = datetime.fromtimestamp(created_at_ms / 1000, tz=timezone.utc)
        age_days = (datetime.now(timezone.utc) - datetime.fromtimestamp(created_at_ms / 1000, tz=timezone.utc)).days
    else:
        created_at_date = None
        age_days = 0

    txns_24h = pair.get("txns", {}).get("h24", {})

    result = TokenData(
        symbol=symbol,
        liquidity_usd=float(pair.get("liquidity", {}).get("usd", 0)),
        price_usd=price_usd,
        price_impact_pct=float(pair.get("priceImpact", 0)),
        pair_created_at=created_at_ms,
        pair_created_at_date=created_at_date.strftime("%Y-%m-%d") if created_at_date else None,
        token_age_days=age_days,
        txns_24h=txns_24h.get("buys", 0) + txns_24h.get("sells", 0),
    )
    _cache[key] = (time.monotonic(), result)
    return result
