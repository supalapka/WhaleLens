import asyncio
import logging

from models.constants import PAIR_CREATED_TOPIC, KNOWN_TOKENS, CHAIN_MAP
from services.moralis import get_token_metadata
from services.notifier.formatter import build_pair_message
from services.notifier.telegram import send_alert
from services.schemas import PairCreatedPayload
from services.checkers.token_security import check_token_security

logger = logging.getLogger(__name__)

# give the coin developer some time to process coin and then check for security
SECURITY_DELAY = 900


async def _identify_new_tokens(
    token0: str, token1: str, chain_id: str,
) -> list[str]:
    t0_known = token0 in KNOWN_TOKENS
    t1_known = token1 in KNOWN_TOKENS

    if t0_known and t1_known:
        return []
    if t0_known:
        return [token1]
    if t1_known:
        return [token0]

    meta0, meta1 = await asyncio.gather(
        get_token_metadata(token0, chain_id),
        get_token_metadata(token1, chain_id),
    )

    created0 = meta0.get("created_at") if meta0 else None
    created1 = meta1.get("created_at") if meta1 else None

    if created0 and created1:
        return [token0] if created0 > created1 else [token1]
    if created0 is None and created1 is not None:
        return [token0]
    if created1 is None and created0 is not None:
        return [token1]
    return [token0, token1]


async def _evaluate_and_notify(
    new_token: str,
    pair_address: str | None,
    chain_id: str,
    chain_name: str | None,
    tx_hash: str,
) -> None:
    try:
        await asyncio.sleep(SECURITY_DELAY)
        logger.info("Running delayed security check for %s", new_token)

        security = await check_token_security(new_token, chain_name)
        if security and security.failed_checks:
            logger.info(
                "Token %s hard-failed: %s | tx: %s",
                new_token, security.failed_checks, tx_hash)
            return

        warnings = security.warnings if security else []
        if warnings:
            logger.info("Token %s has warnings: %s", new_token, warnings)

        metadata = await get_token_metadata(new_token, chain_id)
        symbol = metadata.get("symbol", "???") if metadata else "???"
        name = metadata.get("name", "") if metadata else ""

        text = build_pair_message(
            symbol=symbol,
            name=name,
            token_address=new_token,
            pair_address=pair_address,
            chain_id=chain_id,
            warnings=warnings,
        )

        await send_alert(text)
        logger.info("New pair: %s (%s) — %s", symbol, new_token[:10], pair_address or "unknown")
    except Exception:
        logger.exception("Failed to evaluate pair for token %s", new_token)


async def process_pair_created(payload: PairCreatedPayload) -> dict:
    scheduled = 0

    for log in payload.logs:
        if log.topic0 != PAIR_CREATED_TOPIC or not log.topic1 or not log.topic2:
            continue

        token0 = "0x" + log.topic1[-40:].lower()
        token1 = "0x" + log.topic2[-40:].lower()
        pair_address = "0x" + log.data[26:66] if len(log.data) >= 66 else None

        new_tokens = await _identify_new_tokens(token0, token1, payload.chainId)

        for new_token in new_tokens:
            asyncio.create_task(_evaluate_and_notify(
                new_token=new_token,
                pair_address=pair_address,
                chain_id=payload.chainId,
                chain_name=CHAIN_MAP.get(payload.chainId),
                tx_hash=log.transactionHash,
            ))
            scheduled += 1

            logger.info(
                "Scheduled delayed security check for %s in %ds | tx: %s",
                new_token[:10], SECURITY_DELAY, log.transactionHash)

    return {"status": "ok", "scheduled": scheduled}
