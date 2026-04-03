import logging
from datetime import timedelta

from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

from config import settings
from database import async_session
from models.alert import Alert
from models.transaction import Transaction
from services.checkers.dexscreener import get_token_data
from services.checkers.token_security import check_token_security
from services.notifier.formatter import build_message, build_vip_message
from services.notifier.telegram import send_alert
from services.schemas import TransactionEvent, AlertData
from services.scoring.engine import compute_score
from services.skipped_wallets import increment_skipped_wallet

logger = logging.getLogger(__name__)


def _norm_addr(addr: str) -> str:
    return addr.lower() if addr.startswith("0x") else addr


async def _is_duplicate_alert(token_address: str) -> bool:
    async with async_session() as session:
        cutoff = func.now() - timedelta(hours=settings.alert_cooldown_hours)
        result = await session.execute(
            select(Alert.id)
            .where(Alert.token_address == _norm_addr(token_address))
            .where(Alert.sent_at >= cutoff)
            .limit(1)
        )
        return result.scalar() is not None


async def _get_whale_factors(token_address: str) -> dict:
    async with async_session() as session:
        seven_days_ago = func.now() - timedelta(days=7)

        whale_count_result = await session.execute(
            select(func.count(func.distinct(Transaction.wallet_id)))
            .where(Transaction.token_address == _norm_addr(token_address))
            .where(Transaction.created_at >= seven_days_ago)
        )
        whale_count = whale_count_result.scalar() or 0
        whale_count = max(whale_count, 1)

        time_gap_result = await session.execute(
            select(
                func.extract("epoch", func.max(Transaction.created_at) - func.min(Transaction.created_at)) / 3600
            )
            .where(Transaction.token_address == _norm_addr(token_address))
            .where(Transaction.created_at >= seven_days_ago)
        )
        time_gap_hours = time_gap_result.scalar() or 0

    return {
        "whale_count": whale_count,
        "time_gap_hours": float(time_gap_hours),
    }


async def _save_transaction(event: TransactionEvent, score: float, symbol: str) -> None:
    try:
        async with async_session() as session:
            tx = Transaction(
                wallet_id=event.wallet_id,
                token_address=_norm_addr(event.token_address),
                token_symbol=symbol,
                chain=event.chain,
                usd_amount=event.buy_amount_usd,
                tx_hash=event.tx_hash,
                score=score,
            )
            session.add(tx)
            await session.commit()
    except IntegrityError:
        logger.warning("Duplicate tx_hash %s, skipping save", event.tx_hash)


async def _save_alert(alert: AlertData, telegram_msg_id: int | None) -> None:
    async with async_session() as session:
        record = Alert(
            token_address=_norm_addr(alert.token_address),
            token_symbol=alert.symbol,
            chain=alert.chain,
            score=alert.score,
            whale_count=alert.whale_count,
            liquidity_usd=alert.liquidity_usd,
            price_at_alert=alert.price_at_alert,
            telegram_msg_id=telegram_msg_id,
        )
        session.add(record)
        await session.commit()


async def _tx_already_processed(tx_hash: str) -> bool:
    async with async_session() as session:
        result = await session.execute(
            select(Transaction.id).where(Transaction.tx_hash == tx_hash).limit(1)
        )
        return result.scalar() is not None


async def process_transaction(event: TransactionEvent) -> dict | None:
    if event.always_alert:
        text = build_vip_message(event)
        await send_alert(text)
        return None

    token_address = event.token_address
    chain = event.chain
    tx_hash = event.tx_hash

    if await _tx_already_processed(tx_hash):
        logger.info("Tx %s already processed, skipping", tx_hash[:10])
        await increment_skipped_wallet(event.wallet_address)
        return None

    security = None

    if await _is_duplicate_alert(token_address):
        logger.info("Token %s alerted within cooldown (%dh), skipping | tx: %s",
                     token_address, settings.alert_cooldown_hours, tx_hash)
        await increment_skipped_wallet(event.wallet_address)
        return None

    token_data = await get_token_data(token_address)
    if not token_data:
        logger.warning("DexScreener unavailable for %s, skipping", token_address)
        await increment_skipped_wallet(event.wallet_address)
        return None

    if event.buy_amount_usd is None:
        event.buy_amount_usd = event.token_amount * token_data.price_usd

    whale_factors = await _get_whale_factors(token_address)

    factors = {
        "liquidity_usd": token_data.liquidity_usd,
        "buy_amount_usd": event.buy_amount_usd,
        "price_impact_pct": token_data.price_impact_pct,
        "wallet_credibility": event.wallet_credibility,
        **whale_factors,
    }

    result = compute_score(factors)

    logger.info(
        "Scored %s (%s)\n"
        "  wallet:    %s\n"
        "  amount:    $%.2f\n"
        "  score:     %.1f\n"
        "  breakdown: %s\n"
        "  tx:        %s",
        token_address, token_data.symbol, event.wallet_label,
        event.buy_amount_usd, result.total, result.breakdown, tx_hash,
    )

    await _save_transaction(event, result.total, token_data.symbol)

    if result.total >= settings.min_score_to_alert:
        alert = AlertData(
            token_address=token_address,
            chain=chain,
            symbol=token_data.symbol,
            wallet_label=event.wallet_label,
            buy_amount_usd=event.buy_amount_usd,
            score=result.total,
            breakdown=result.breakdown,
            liquidity_usd=token_data.liquidity_usd,
            price_impact_pct=token_data.price_impact_pct,
            token_age_days=token_data.token_age_days,
            txns_24h=token_data.txns_24h,
            whale_count=whale_factors["whale_count"],
            price_at_alert=token_data.price_usd,
        )
        text = build_message(alert)
        msg_id = await send_alert(text)
        await _save_alert(alert, msg_id)

    return {
        "score": result.total,
        "breakdown": result.breakdown,
        "token_data": token_data.model_dump(),
        "security": security.model_dump() if security else None,
    }
