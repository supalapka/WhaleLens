from fastapi import APIRouter

from services.pair_handler import process_pair_created
from services.webhook_handler import process_webhook
from services.schemas import PairCreatedPayload, WebhookPayload

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
