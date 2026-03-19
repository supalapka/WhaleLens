import asyncio
import logging

import httpx

from services.early_buyers.schemas import OhlcvCandle

logger = logging.getLogger(__name__)

BASE_URL = "https://api.geckoterminal.com/api/v2"
MAX_CANDLES_PER_REQUEST = 1000
RATE_LIMIT_DELAY = 3.0
MAX_RETRIES = 3


async def _request_with_retry(
    url: str, params: dict, retries: int = MAX_RETRIES,
) -> httpx.Response | None:
    for attempt in range(retries):
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=15)

        if response.status_code == 200:
            return response

        if response.status_code == 429:
            wait = RATE_LIMIT_DELAY * (attempt + 2)
            logger.warning("GeckoTerminal 429, retrying in %.0fs", wait)
            await asyncio.sleep(wait)
            continue

        logger.error(
            "GeckoTerminal OHLCV failed: %s %s",
            response.status_code, response.text[:200],
        )
        return None

    logger.error("GeckoTerminal retries exhausted")
    return None


async def get_ohlcv_range(
    network: str,
    pool_address: str,
    start_ts: int,
    end_ts: int,
    timeframe: str = "minute",
    aggregate: int = 1,
) -> list[OhlcvCandle]:
    all_candles: list[OhlcvCandle] = []
    cursor_ts = end_ts

    while cursor_ts > start_ts:
        url = (
            f"{BASE_URL}/networks/{network}/pools/{pool_address}"
            f"/ohlcv/{timeframe}"
        )
        params = {
            "aggregate": aggregate,
            "before_timestamp": cursor_ts,
            "limit": MAX_CANDLES_PER_REQUEST,
        }

        response = await _request_with_retry(url, params)
        if response is None:
            break

        data = response.json()
        ohlcv_list = (
            data.get("data", {})
            .get("attributes", {})
            .get("ohlcv_list", [])
        )

        if not ohlcv_list:
            break

        for row in ohlcv_list:
            ts, o, h, l, c, v = row
            if ts < start_ts:
                continue
            all_candles.append(OhlcvCandle(
                timestamp=ts, open=o, high=h, low=l, close=c, volume=v,
            ))

        earliest = min(row[0] for row in ohlcv_list)
        if earliest >= cursor_ts:
            break
        cursor_ts = earliest

        await asyncio.sleep(RATE_LIMIT_DELAY)

    all_candles.sort(key=lambda c: c.timestamp)
    logger.info(
        "Fetched %d OHLCV candles for %s/%s [%d → %d]",
        len(all_candles), network, pool_address[:10], start_ts, end_ts,
    )
    return all_candles
