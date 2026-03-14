from fastapi import APIRouter

from services.webhook_handler import process_webhook
from services.schemas import WebhookPayload

router = APIRouter()


@router.post("/webhook/tx")
async def webhook_tx(payload: WebhookPayload):
    if not payload.confirmed:
        return {"status": "skipped", "reason": "unconfirmed"}
    return await process_webhook(payload)
