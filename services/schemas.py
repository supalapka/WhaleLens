import re

from pydantic import BaseModel, ConfigDict, Field, field_validator


_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


class ERC20Transfer(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    transactionHash: str = ""
    contract: str = ""
    from_address: str = Field("", alias="from")
    to: str = ""
    valueWithDecimals: str = "0"
    tokenSymbol: str = ""
    triggered_by: list[str] = Field(default_factory=list)


class RawLog(BaseModel):
    transactionHash: str = ""
    address: str = ""
    topic0: str | None = None
    topic1: str | None = None
    topic2: str | None = None
    data: str = "0x"
    triggered_by: list[str] = Field(default_factory=list)


class WebhookPayload(BaseModel):
    chainId: str = ""
    erc20Transfers: list[ERC20Transfer] = []
    logs: list[RawLog] = []


class WalletCreate(BaseModel):
    address: str
    label: str | None = None
    category: str | None = None

    @field_validator("address")
    @classmethod
    def validate_address(cls, v: str) -> str:
        if not _ADDRESS_RE.match(v):
            raise ValueError("invalid EVM address")
        return v.lower()


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
