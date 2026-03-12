from pydantic import BaseModel


class TransactionEvent(BaseModel):
    token_address: str
    chain: str
    wallet_address: str
    wallet_id: int
    wallet_label: str
    wallet_credibility: float
    token_amount: float
    tx_hash: str
    buy_amount_usd: float | None = None


class TokenData(BaseModel):
    symbol: str
    liquidity_usd: float
    price_usd: float
    price_impact_pct: float
    pair_created_at: int
    pair_created_at_date: str | None
    token_age_days: int
    txns_24h: int


class SecurityResult(BaseModel):
    is_safe: bool
    failed_checks: list[str]
    buy_tax: float | None
    sell_tax: float | None


class ScoreResult(BaseModel):
    total: float
    breakdown: dict[str, float]


class AlertData(BaseModel):
    token_address: str
    chain: str
    symbol: str
    wallet_label: str
    buy_amount_usd: float
    score: float
    breakdown: dict[str, float]
    liquidity_usd: float
    price_impact_pct: float
    token_age_days: int
    txns_24h: int
    whale_count: int
    price_at_alert: float
