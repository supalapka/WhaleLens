from datetime import datetime

from sqlalchemy import JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from models import Base


class OhlcvCache(Base):
    __tablename__ = "ohlcv_cache"
    __table_args__ = (
        UniqueConstraint("pool_address", "token_address", "network"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    pool_address: Mapped[str] = mapped_column(String(42), nullable=False)
    token_address: Mapped[str] = mapped_column(String(42), nullable=False)
    network: Mapped[str] = mapped_column(String(10), nullable=False)
    start_ts: Mapped[int] = mapped_column(nullable=False)
    end_ts: Mapped[int] = mapped_column(nullable=False)
    candles_json: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
