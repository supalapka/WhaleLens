import logging
from collections import defaultdict

from sqlalchemy import select

from database import async_session
from models.constants import CHAIN_MAP, STABLECOINS, WRAPPED_NATIVE
from models.wallet import Wallet
from services.moralis import decode_logs_to_transfers, fetch_tx_logs
from services.queue import tx_queue
from services.schemas import ERC20Transfer, TransactionEvent, WebhookPayload

logger = logging.getLogger(__name__)

EXCLUDED_TOKENS = set(STABLECOINS) | WRAPPED_NATIVE


async def _fetch_tracked_wallets(addresses: set[str]) -> dict[str, Wallet]:
    if not addresses:
        return {}

    async with async_session() as session:
        result = await session.execute(
            select(Wallet).where(Wallet.address.in_(addresses)).where(Wallet.is_active.is_(True))
        )
        wallets = {w.address: w for w in result.scalars().all()}

    for addr, wallet in wallets.items():
        logger.info("Webhook from %s (%s)", wallet.label or addr[:10], addr)

    return wallets


async def _resolve_transfers(payload: WebhookPayload) -> list[ERC20Transfer]:
    if payload.erc20Transfers:
        return payload.erc20Transfers

    from_logs = await decode_logs_to_transfers(payload.logs, payload.chainId)
    if from_logs:
        return from_logs

    resolved = []
    for tx in payload.txs:
        if tx.receiptStatus != "1":
            continue
        fetched_logs = await fetch_tx_logs(tx.hash, payload.chainId, tx.triggered_by)
        decoded = await decode_logs_to_transfers(fetched_logs, payload.chainId)
        logger.info("Fetched tx %s: %d logs -> %d transfers", tx.hash[:10], len(fetched_logs), len(decoded))
        resolved.extend(decoded)

    return resolved


def _detect_router_swap(
    transfers: list[ERC20Transfer],
    router: str,
    wallet: str,
) -> tuple[list[ERC20Transfer], list[ERC20Transfer]]:
    sent = []
    received = []
    router = router.lower()

    for transfer in transfers:
        from_addr = transfer.from_address.lower()
        to_addr = transfer.to.lower()
        contract = transfer.contract.lower()

        if from_addr == router and contract in EXCLUDED_TOKENS:
            sent.append(ERC20Transfer(
                transactionHash=transfer.transactionHash,
                contract=transfer.contract,
                from_address=wallet,
                to=router,
                valueWithDecimals=transfer.valueWithDecimals,
                triggered_by=transfer.triggered_by,
            ))

        if to_addr == router and contract not in STABLECOINS:
            received.append(ERC20Transfer(
                transactionHash=transfer.transactionHash,
                contract=transfer.contract,
                from_address=router,
                to=wallet,
                valueWithDecimals=transfer.valueWithDecimals,
                triggered_by=transfer.triggered_by,
            ))

    return sent, received


def _sum_stablecoin_usd(sent: list[ERC20Transfer]) -> float | None:
    total = None
    for transfer in sent:
        if transfer.contract.lower() in STABLECOINS:
            total = (total or 0) + float(transfer.valueWithDecimals)
    return total


def _log_token_burns(transfers: list[ERC20Transfer]) -> None:
    for transfer in transfers:
        if transfer.to.lower() == "0x0000000000000000000000000000000000000000":
            logger.info(
                "Token burn detected: wallet=%s token=%s amount=%s",
                transfer.from_address[:10],
                transfer.contract,
                transfer.valueWithDecimals,
            )


async def process_webhook(payload: WebhookPayload) -> dict:
    enqueued = 0
    skipped = []
    chain = CHAIN_MAP.get(payload.chainId, payload.chainId)

    trigger_sources = payload.erc20Transfers or payload.logs or payload.txs
    all_addresses = {addr.lower() for item in trigger_sources for addr in item.triggered_by}
    tracked_wallets = await _fetch_tracked_wallets(all_addresses)

    transfers = await _resolve_transfers(payload)
    if not transfers:
        logger.info("No ERC20 transfers resolved for chain=%s txs=%d", chain, len(payload.txs))
    tx_metadata = {tx.hash.lower(): tx for tx in payload.txs}

    grouped: dict[str, list[ERC20Transfer]] = defaultdict(list)
    for transfer in transfers:
        grouped[transfer.transactionHash].append(transfer)

    for tx_hash, tx_transfers in grouped.items():

        _log_token_burns(tx_transfers)

        wallets_in_tx = {addr.lower() for t in tx_transfers for addr in t.triggered_by}
        tx_meta = tx_metadata.get(tx_hash.lower())

        for wallet_address in wallets_in_tx:
            sent = [t for t in tx_transfers if t.from_address.lower() == wallet_address]
            received = [t for t in tx_transfers if t.to.lower() == wallet_address]

            if not sent or not received:
                if tx_meta and tx_meta.fromAddress.lower() == wallet_address:
                    router = tx_meta.toAddress.lower()
                    sent, received = _detect_router_swap(tx_transfers, router, wallet_address)
                    logger.info(
                        "Router swap for %s via %s: sent=%d received=%d",
                        wallet_address[:10], router[:10], len(sent), len(received),
                    )

            is_native_swap = (
                not sent
                and received
                and tx_meta
                and tx_meta.fromAddress.lower() == wallet_address
            )
            if is_native_swap:
                logger.info("Native swap detected for %s", wallet_address[:10])

            selector = tx_meta.input[:10] if tx_meta and len(tx_meta.input) >= 10 else "N/A"

            if not sent and not is_native_swap:
                logger.info(
                    "Skip tx %s wallet %s: no outgoing tokens (not a buy) [selector=%s]",
                    tx_hash[:10], wallet_address[:10], selector,
                )
                continue
            if not received:
                logger.info(
                    "Skip tx %s wallet %s: no incoming tokens (sell/transfer) [selector=%s]",
                    tx_hash[:10], wallet_address[:10], selector,
                )
                continue

            bought = [t for t in received if t.contract.lower() not in EXCLUDED_TOKENS]
            if not bought:
                logger.info(
                    "Skip tx %s wallet %s: only received stablecoins/WETH [selector=%s]",
                    tx_hash[:10], wallet_address[:10], selector,
                )
                continue

            wallet = tracked_wallets.get(wallet_address)
            if not wallet:
                skipped.append(wallet_address)
                continue

            buy_amount_usd = _sum_stablecoin_usd(sent) if not is_native_swap else None
            bought_token = max(bought, key=lambda t: float(t.valueWithDecimals))

            event = TransactionEvent(
                token_address=bought_token.contract,
                chain=chain,
                wallet_address=wallet_address,
                wallet_id=wallet.id,
                wallet_label=wallet.label or wallet_address[:10],
                wallet_credibility=wallet.credibility_score,
                token_amount=float(bought_token.valueWithDecimals),
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
