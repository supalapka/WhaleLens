import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query
from pydantic import BaseModel
from sqlalchemy import select

from config import settings
from database import async_session
from models.wallet import Wallet
from services.checkers.dexscreener import get_token_data
from services.checkers.honeypot import check_token_security
from services.queue import tx_queue, start_workers
from services.schemas import TransactionEvent
from services.scoring.engine import compute_score

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CHAIN_MAP = {
    "0x1": "ETH",
    "0x38": "BSC",
    "0x2105": "BASE",
    "0xa4b1": "ARBITRUM",
}


class ERC20Transfer(BaseModel):
    contract: str = ""
    valueWithDecimals: str = "0"


class MoralisTx(BaseModel):
    fromAddress: str = ""
    chainId: str = ""
    hash: str = ""
    value: str = "0"


class WebhookPayload(BaseModel):
    txs: list[MoralisTx] = []
    erc20Transfers: list[ERC20Transfer] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    workers = await start_workers(settings.n_workers)
    yield
    for task in workers:
        task.cancel()


app = FastAPI(title="WhaleLens", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "queue_size": tx_queue.qsize()}


@app.post("/webhook/tx")
async def webhook_tx(payload: WebhookPayload) -> dict[str, str]:
    for tx in payload.txs:
        from_address = tx.fromAddress.lower()

        async with async_session() as session:
            result = await session.execute(
                select(Wallet).where(Wallet.address == from_address).where(Wallet.is_active.is_(True))
            )
            wallet = result.scalar_one_or_none()

        if not wallet:
            continue

        chain = CHAIN_MAP.get(tx.chainId, tx.chainId)

        for transfer in payload.erc20Transfers:
            event = TransactionEvent(
                token_address=transfer.contract,
                chain=chain,
                wallet_address=from_address,
                wallet_id=wallet.id,
                wallet_label=wallet.label or from_address[:10],
                wallet_credibility=wallet.credibility_score,
                token_amount=float(transfer.valueWithDecimals),
                tx_hash=tx.hash,
            )
            await tx_queue.put(event)
            logger.info(
                "Enqueued tx: %s (%s) on %s | token: %s | tx: %s",
                wallet.label, from_address[:10], chain, transfer.contract, tx.hash,
            )

    return {"status": "ok"}


@app.get("/debug/token/{token_address}")
async def debug_token(token_address: str):
    return await get_token_data(token_address)


@app.get("/debug/security/{chain}/{token_address}")
async def debug_security(chain: str, token_address: str):
    return await check_token_security(token_address, chain.upper())


@app.get("/debug/score")
async def debug_score(
    liquidity_usd: float = Query(),
    buy_amount_usd: float = Query(),
    whale_count: int = Query(),
    wallet_credibility: float = Query(),
    time_gap_hours: float = Query(),
    price_impact_pct: float = Query(),
):
    factors = {
        "liquidity_usd": liquidity_usd,
        "buy_amount_usd": buy_amount_usd,
        "whale_count": whale_count,
        "wallet_credibility": wallet_credibility,
        "time_gap_hours": time_gap_hours,
        "price_impact_pct": price_impact_pct,
    }
    return compute_score(factors)
