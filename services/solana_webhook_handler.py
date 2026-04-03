import logging

from sqlalchemy import select

from database import async_session
from models.constants import STABLECOINS
from models.wallet import Wallet
from services.queue import tx_queue
from services.schemas import HeliusTx, TransactionEvent

logger = logging.getLogger(__name__)

_WSOL = "So11111111111111111111111111111111111111112"
_SOLANA_STABLECOINS: frozenset[str] = frozenset(a for a in STABLECOINS if not a.startswith("0x"))
_SOLANA_EXCLUDED: frozenset[str] = frozenset({_WSOL}) | _SOLANA_STABLECOINS


async def process_solana_webhook(txs: list[HeliusTx]) -> dict:
    enqueued = 0
    for tx in txs:
        enqueued += await _process_tx(tx)
    return {"status": "ok", "enqueued": enqueued, "queue_size": tx_queue.qsize()}


async def _process_tx(tx: HeliusTx) -> int:
    all_addresses: set[str] = set()
    for tt in tx.tokenTransfers:
        all_addresses.add(tt.fromUserAccount)
        all_addresses.add(tt.toUserAccount)
    for nt in tx.nativeTransfers:
        all_addresses.add(nt.fromUserAccount)
        all_addresses.add(nt.toUserAccount)
    all_addresses.discard("")

    tracked = await _fetch_tracked_wallets(all_addresses)
    if not tracked:
        return 0

    enqueued = 0
    for wallet_address, wallet in tracked.items():
        received = [
            tt for tt in tx.tokenTransfers
            if tt.toUserAccount == wallet_address
            and tt.mint not in _SOLANA_EXCLUDED
            and tt.tokenAmount > 0
        ]
        if not received:
            logger.info("Solana tx %s wallet %s: no non-excluded tokens received", tx.signature[:10], wallet_address[:10])
            continue

        bought = max(received, key=lambda t: t.tokenAmount)
        stable_sent = [
            tt for tt in tx.tokenTransfers
            if tt.fromUserAccount == wallet_address and tt.mint in _SOLANA_STABLECOINS
        ]
        buy_amount_usd = sum(tt.tokenAmount for tt in stable_sent) or None

        await tx_queue.put(TransactionEvent(
            token_address=bought.mint,
            chain="solana",
            wallet_address=wallet_address,
            wallet_id=wallet.id,
            wallet_label=wallet.label or wallet_address[:10],
            wallet_credibility=wallet.credibility_score,
            token_amount=bought.tokenAmount,
            tx_hash=tx.signature,
            buy_amount_usd=buy_amount_usd,
            always_alert=wallet.always_alert,
        ))
        logger.info("Solana tx %s enqueued for wallet %s token %s", tx.signature[:10], wallet_address[:10], bought.mint[:10])
        enqueued += 1

    return enqueued


async def _fetch_tracked_wallets(addresses: set[str]) -> dict[str, Wallet]:
    if not addresses:
        return {}
    async with async_session() as session:
        result = await session.execute(
            select(Wallet).where(Wallet.address.in_(addresses)).where(Wallet.is_active.is_(True))
        )
        return {w.address: w for w in result.scalars().all()}
