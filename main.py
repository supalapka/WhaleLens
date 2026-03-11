import logging

from fastapi import FastAPI
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="WhaleLens")

CHAIN_MAP = {
    "0x1": "ETH",
    "0x38": "BSC",
    "0x2105": "BASE",
    "0xa4b1": "ARBITRUM"}


class ERC20Transfer(BaseModel):
    contract: str = ""

class MoralisTx(BaseModel):
    fromAddress: str = ""
    chainId: str = ""
    hash: str = ""

class WebhookPayload(BaseModel):
    txs: list[MoralisTx] = []
    erc20Transfers: list[ERC20Transfer] = []

TRACKED_WALLETS: dict[str, dict[str, str]] = {
    "0x742d35cc6634c0532925a3b844bc454e4438f44e": {
        "label": "Exchange Whale",
        "category": "WHALE"
    },
}

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/webhook/tx")
async def webhook_tx(payload: WebhookPayload) -> dict[str, str]:
    for tx in payload.txs:
        from_address = tx.fromAddress.lower()
        wallet = TRACKED_WALLETS.get(from_address)
        if not wallet:
            continue

        chain = CHAIN_MAP.get(tx.chainId, tx.chainId)
        tokens = [t.contract for t in payload.erc20Transfers]

        logger.info(
            "Tracked wallet tx: %s (%s) on %s | tokens: %s | tx: %s",
            wallet["label"],
            from_address[:10],
            chain,
            tokens,
            tx.hash,
        )

    return {"status": "ok"}
