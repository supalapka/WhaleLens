import logging

from models.constants import PAIR_CREATED_TOPIC, WBNB
from services.moralis import get_token_metadata
from services.notifier.formatter import build_pair_message
from services.notifier.telegram import send_alert
from services.schemas import PairCreatedPayload

logger = logging.getLogger(__name__)


async def process_pair_created(payload: PairCreatedPayload) -> dict:
    notified = 0

    for log in payload.logs:
        if log.topic0 != PAIR_CREATED_TOPIC or not log.topic1 or not log.topic2:
            continue

        token0 = "0x" + log.topic1[-40:].lower()
        token1 = "0x" + log.topic2[-40:].lower()

        if token0 == WBNB:
            new_token = token1
        elif token1 == WBNB:
            new_token = token0
        else:
            continue

        pair_address = "0x" + log.data[26:66] if len(log.data) >= 66 else None

        metadata = await get_token_metadata(new_token, payload.chainId)
        symbol = metadata.get("symbol", "???") if metadata else "???"
        name = metadata.get("name", "") if metadata else ""

        text = build_pair_message(
            symbol=symbol,
            name=name,
            token_address=new_token,
            pair_address=pair_address,
        )
        await send_alert(text)
        notified += 1

        logger.info("New pair: %s (%s) — %s", symbol, new_token[:10], pair_address or "unknown")

    return {"status": "ok", "notified": notified}
