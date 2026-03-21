from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class OhlcvCandle(BaseModel):
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class TokenTransfer(BaseModel):
    transaction_hash: str
    from_address: str
    to_address: str
    value: str
    block_timestamp: str
    token_decimals: str = "18"

    @property
    def token_amount(self) -> float:
        return int(self.value) / (10 ** int(self.token_decimals))

    @property
    def timestamp_dt(self) -> datetime:
        return datetime.fromisoformat(self.block_timestamp.replace("Z", "+00:00"))


class ClassifiedSwap(BaseModel):
    wallet_address: str
    token_amount: float
    timestamp: datetime
    tx_hash: str


class PricedSwap(ClassifiedSwap):
    price_usd: float
    usd_value: float


_CHAIN_ALIASES: dict[str, str] = {
    "eth": "ethereum",
    "ethereum": "ethereum",
    "0x1": "ethereum",
    "1": "ethereum",
    "bsc": "bsc",
    "bnb": "bsc",
    "0x38": "bsc",
    "56": "bsc",
    "base": "base",
    "0x2105": "base",
    "8453": "base",
    "arbitrum": "arbitrum",
    "arb": "arbitrum",
    "0xa4b1": "arbitrum",
    "42161": "arbitrum",
}


class EarlyBuyerRequest(BaseModel):
    token_address: str
    pump_start: int
    pump_peak: int
    chain: str | None = None

    @field_validator("token_address")
    @classmethod
    def normalize_address(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("chain")
    @classmethod
    def normalize_chain(cls, v: str | None) -> str | None:
        if v is None:
            return None
        normalized = _CHAIN_ALIASES.get(v.strip().lower())
        if normalized is None:
            raise ValueError(
                f"Unknown chain '{v}'. "
                f"Accepted: {', '.join(sorted(set(_CHAIN_ALIASES.values())))}"
            )
        return normalized

    @field_validator("pump_peak")
    @classmethod
    def peak_after_start(cls, v: int, info) -> int:
        if "pump_start" in info.data and v < info.data["pump_start"]:
            raise ValueError("pump_peak must be >= pump_start")
        return v


def _r2(v: float) -> float:
    return round(v, 2)


def _r_price(v: float) -> float:
    return round(v, 10)


class BuySummary(BaseModel):
    first_time: datetime
    tokens: float
    usd: float
    avg_price: float


class SellSummary(BaseModel):
    count: int
    first_time: datetime | None = None
    last_time: datetime | None = None
    tokens: float
    usd: float
    avg_price: float


class EarlyBuyerRecord(BaseModel):
    wallet: str
    buy: BuySummary
    sell: SellSummary
    sold_pct: float
    profit_pct: float
    profit_usd: float


class EarlyBuyerResponse(BaseModel):
    token_address: str
    token_symbol: str
    pump_start: int
    pump_peak: int
    pump_end: int
    peak_price: float
    total_early_buyers: int
    results: list[EarlyBuyerRecord]
