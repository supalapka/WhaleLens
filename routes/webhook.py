from fastapi import APIRouter, HTTPException, Request

from config import settings
from services.pair_handler import process_pair_created
from services.schemas import HeliusTx, PairCreatedPayload, WebhookPayload
from services.solana_webhook_handler import process_solana_webhook
from services.webhook_handler import process_webhook

router = APIRouter()


@router.post("/webhook/tx")
async def webhook_tx(payload: WebhookPayload):
    if not payload.confirmed:
        return {"status": "skipped", "reason": "unconfirmed"}
    return await process_webhook(payload)


@router.post("/webhook/pairs")
async def webhook_pairs(payload: PairCreatedPayload):
    if not payload.confirmed:
        return {"status": "skipped", "reason": "unconfirmed"}
    return await process_pair_created(payload)


@router.post("/webhook/solana")
async def webhook_solana(request: Request, txs: list[HeliusTx]):
    if settings.helius_webhook_secret:
        auth = request.headers.get("Authorization", "")
        if auth != settings.helius_webhook_secret:
            raise HTTPException(status_code=401)
    return await process_solana_webhook(txs)
