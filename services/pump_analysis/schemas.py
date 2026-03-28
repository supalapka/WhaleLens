from pydantic import BaseModel


class PumpResult(BaseModel):
    wallet_id: int
    wallet_address: str
    tx_id: int
    token_symbol: str
    token_address: str
    price_at_tx: float
    max_price_after: float
    gain_multiple: float


class PumpAnalysisResponse(BaseModel):
    total_bsc_transactions: int
    unique_tokens_scanned: int
    tokens_skipped: int
    results: list[PumpResult]
