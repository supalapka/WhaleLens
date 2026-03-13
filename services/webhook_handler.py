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

    transfers_by_transaction: dict[str, list[ERC20Transfer]] = defaultdict(list)
    for t in transfers_source:
        transfers_by_transaction[t.transactionHash].append(t)

    for tx_hash, transfers in transfers_by_transaction.items():
        wallets_in_tx = {a.lower() for t in transfers for a in t.triggered_by}

        for wallet_address in wallets_in_tx:
            sent = [t for t in transfers if t.from_address.lower() == wallet_address]
            received = [t for t in transfers if t.to.lower() == wallet_address]

            if not sent or not received:
                continue

            bought = [t for t in received if t.contract.lower() not in STABLECOINS]
            if not bought:
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
            for t in sent:
                if t.contract.lower() in STABLECOINS:
                    buy_amount_usd = (buy_amount_usd or 0) + float(t.valueWithDecimals)

            for token in bought:
                event = TransactionEvent(
                    token_address=token.contract,
                    chain=chain,
                    wallet_address=wallet_address,
                    wallet_id=wallet.id,
                    wallet_label=wallet.label or wallet_address[:10],
                    wallet_credibility=wallet.credibility_score,
                    token_amount=float(token.valueWithDecimals),
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
