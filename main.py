import logging
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from config import settings
from database import async_session
from models.constants import STABLECOINS
from models.wallet import Wallet
from services.checkers.dexscreener import get_token_data
from services.checkers.honeypot import check_token_security
from services.queue import tx_queue, start_workers, worker_tasks
from services.schemas import TransactionEvent, WalletCreate
from services.scoring.engine import compute_score

class _ColorFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: "\033[36m",
        logging.INFO: "\033[33m",
        logging.WARNING: "\033[35m",
        logging.ERROR: "\033[31m",
        logging.CRITICAL: "\033[1;31m",
    }
    RESET = "\033[0m"

    def format(self, record):
        color = self.COLORS.get(record.levelno, self.RESET)
        record.msg = f"{color}{record.msg}{self.RESET}"
        return super().format(record)


_handler = logging.StreamHandler()
_handler.setFormatter(_ColorFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
logging.root.handlers = [_handler]
logging.root.setLevel(logging.INFO)
logger = logging.getLogger(__name__)

CHAIN_MAP = {
    "0x1": "ETH",
    "0x38": "BSC",
    "0x2105": "BASE",
    "0xa4b1": "ARBITRUM",
}


class ERC20Transfer(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    transactionHash: str = ""
    contract: str = ""
    from_address: str = Field("", alias="from")
    to: str = ""
    valueWithDecimals: str = "0"
    tokenSymbol: str = ""
    triggered_by: list[str] = Field(default_factory=list)


class WebhookPayload(BaseModel):
    chainId: str = ""
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
    return {
        "status": "ok",
        "queue_size": tx_queue.qsize(),
        "workers": len(worker_tasks),
        "workers_alive": sum(1 for t in worker_tasks if not t.done()),
        "workers_failed": [str(t.exception()) for t in worker_tasks if t.done() and t.exception()],
    }


@app.post("/webhook/tx")
async def webhook_tx(payload: WebhookPayload):
    enqueued = 0
    skipped = []
    chain = CHAIN_MAP.get(payload.chainId, payload.chainId)

    by_tx: dict[str, list[ERC20Transfer]] = defaultdict(list)
    for t in payload.erc20Transfers:
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


@app.post("/wallets")
async def add_wallet(body: WalletCreate):
    wallet = Wallet(
        address=body.address,
        label=body.label,
        category=body.category,
    )
    try:
        async with async_session() as session:
            session.add(wallet)
            await session.commit()
            await session.refresh(wallet)
    except IntegrityError:
        return JSONResponse(
            status_code=409,
            content={"detail": f"wallet {body.address} already exists"},
        )
    return {
        "id": wallet.id,
        "address": wallet.address,
        "label": wallet.label,
        "category": wallet.category,
        "credibility_score": wallet.credibility_score,
        "is_active": wallet.is_active,
        "added_at": wallet.added_at.isoformat(),
    }


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
