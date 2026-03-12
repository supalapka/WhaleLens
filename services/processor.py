import logging

from config import settings
from services.checkers.dexscreener import get_token_data
from services.checkers.honeypot import check_token_security
from services.notifier.formatter import build_message
from services.notifier.telegram import send_alert
from services.scoring.engine import compute_score

logger = logging.getLogger(__name__)

DB_MOCK_DEFAULTS = {
    "whale_count": 1,
    "wallet_credibility": 0.5,
    "time_gap_hours": 0,
}


async def process_transaction(event: dict) -> dict | None:
    token_address = event["token_address"]
    chain = event["chain"]
    wallet_label = event["wallet_label"]
    tx_hash = event["tx_hash"]

    security = await check_token_security(token_address, chain)
    if security and not security["is_safe"]:
        logger.info(
            "Token %s failed safety: %s | tx: %s",
            token_address, security["failed_checks"], tx_hash,
        )
        return None

    if not security:
        logger.warning("GoPlus unavailable for %s, proceeding without safety check", token_address)

    token_data = await get_token_data(token_address)
    if not token_data:
        logger.warning("DexScreener unavailable for %s, skipping", token_address)
        return None

    buy_amount_usd = event["token_amount"] * token_data["price_usd"]

    factors = {
        "liquidity_usd": token_data["liquidity_usd"],
        "buy_amount_usd": buy_amount_usd,
        "price_impact_pct": token_data["price_impact_pct"],
        **DB_MOCK_DEFAULTS,
    }

    result = compute_score(factors)

    logger.info(
        "Scored %s | wallet: %s | score: %.1f | breakdown: %s | tx: %s",
        token_address, wallet_label, result["total"], result["breakdown"], tx_hash,
    )

    if result["total"] >= settings.min_score_to_alert:
        alert_data = {
            "token_address": token_address,
            "chain": chain,
            "symbol": token_data["symbol"],
            "wallet_label": wallet_label,
            "buy_amount_usd": buy_amount_usd,
            "score": result["total"],
            "breakdown": result["breakdown"],
            "liquidity_usd": token_data["liquidity_usd"],
            "price_impact_pct": token_data["price_impact_pct"],
            "token_age_days": token_data["token_age_days"],
            "txns_24h": token_data["txns_24h"],
        }
        text = build_message(alert_data)
        await send_alert(text)

    return {
        "score": result["total"],
        "breakdown": result["breakdown"],
        "token_data": token_data,
        "security": security,
    }
