from fastapi import APIRouter, Query

from services.checkers.dexscreener import get_token_data
from services.checkers.honeypot import check_token_security
from services.moralis import create_pair_stream
from services.queue import tx_queue, worker_tasks
from services.scoring.engine import compute_score

router = APIRouter()


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "queue_size": tx_queue.qsize(),
        "workers": len(worker_tasks),
        "workers_alive": sum(1 for t in worker_tasks if not t.done()),
        "workers_failed": [str(t.exception()) for t in worker_tasks if t.done() and t.exception()],
    }


@router.get("/debug/token/{token_address}")
async def debug_token(token_address: str):
    return await get_token_data(token_address)


@router.get("/debug/security/{chain}/{token_address}")
async def debug_security(chain: str, token_address: str):
    return await check_token_security(token_address, chain.upper())


@router.get("/debug/score")
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


@router.post("/debug/create-pair-stream")
async def debug_create_pair_stream():
    stream_id = await create_pair_stream()
    return {"stream_id": stream_id}
