import logging
from collections import defaultdict

from sqlalchemy import select

from database import async_session
from models.constants import CHAIN_MAP, STABLECOINS
from models.wallet import Wallet
from services.moralis import decode_logs_to_transfers
from services.queue import tx_queue
from services.schemas import ERC20Transfer, TransactionEvent, WebhookPayload

logger = logging.getLogger(__name__)


async def process_webhook(payload: WebhookPayload) -> dict:
    enqueued = 0
    skipped = []
    chain = CHAIN_MAP.get(payload.chainId, payload.chainId)

    transfers_source = payload.erc20Transfers
    if not transfers_source:
        transfers_source = await decode_logs_to_transfers(payload.logs, payload.chainId)

    by_tx: dict[str, list[ERC20Transfer]] = defaultdict(list)
    for t in transfers_source:
        by_tx[t.transactionHash].append(t)

    for tx_hash, transfers in by_tx.items():
        for transfer in transfers:
            wallet_address = next((a.lower() for a in transfer.triggered_by), None)
            if not wallet_address:
                continue

            if transfer.to.lower() != wallet_address:
                continue

            if transfer.contract.lower() in STABLECOINS:
                continue

            async with async_session() as session:
                result = await session.execute(
                    select(Wallet).where(Wallet.address == wallet_address).where(Wallet.is_active.is_(True))
                )
                wallet = result.scalar_one_or_none()

            if not wallet:
                skipped.append(wallet_address)
                continue

            buy_amount_usd = None
            for other in transfers:
                if other.from_address.lower() == wallet_address and other.contract.lower() in STABLECOINS:
                    buy_amount_usd = float(other.valueWithDecimals)
                    break

            event = TransactionEvent(
                token_address=transfer.contract,
                chain=chain,
                wallet_address=wallet_address,
                wallet_id=wallet.id,
                wallet_label=wallet.label or wallet_address[:10],
                wallet_credibility=wallet.credibility_score,
                token_amount=float(transfer.valueWithDecimals),
                tx_hash=tx_hash,
                buy_amount_usd=buy_amount_usd,
            )
            await tx_queue.put(event)
            enqueued += 1

    return {
        "status": "ok",
        "enqueued": enqueued,
        "skipped_addresses": skipped,
        "queue_size": tx_queue.qsize(),
    }
