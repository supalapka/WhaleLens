import logging

from models.constants import AVG_BLOCK_TIME
from services.early_buyers.rpc import rpc_call

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 20

_block_cache: dict[tuple[str, int], int] = {}


async def timestamp_to_block(chain_hex: str, target_ts: int) -> int:
    cache_key = (chain_hex, target_ts)
    if cache_key in _block_cache:
        return _block_cache[cache_key]
    latest = await rpc_call(chain_hex, "eth_getBlockByNumber", ["latest", False])
    if not latest:
        raise RuntimeError("Failed to fetch latest block")

    latest_number = int(latest["number"], 16)
    latest_ts = int(latest["timestamp"], 16)

    if target_ts >= latest_ts:
        return latest_number

    avg_time = AVG_BLOCK_TIME.get(chain_hex, 12)
    estimated = latest_number - (latest_ts - target_ts) // avg_time
    low = max(0, estimated - estimated // 10)
    high = latest_number

    best_block = low

    for _ in range(MAX_ITERATIONS):
        if low > high:
            break

        mid = (low + high) // 2
        block = await rpc_call(chain_hex, "eth_getBlockByNumber", [hex(mid), False])
        if not block:
            break

        block_ts = int(block["timestamp"], 16)

        if block_ts <= target_ts:
            best_block = mid
            low = mid + 1
        else:
            high = mid - 1

    logger.debug(
        "timestamp_to_block(%s, %d) = %d",
        chain_hex, target_ts, best_block,
    )
    _block_cache[cache_key] = best_block
    return best_block
