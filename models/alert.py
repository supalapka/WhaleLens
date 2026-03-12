from datetime import datetime

from sqlalchemy import String, Float, Integer, BigInteger, func
from sqlalchemy.orm import Mapped, mapped_column

from models import Base


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_address: Mapped[str] = mapped_column(String(42), nullable=False)
    token_symbol: Mapped[str | None] = mapped_column(String(20))
    chain: Mapped[str | None] = mapped_column(String(10))
    score: Mapped[float | None] = mapped_column(Float)
    whale_count: Mapped[int | None] = mapped_column(Integer)
    liquidity_usd: Mapped[float | None] = mapped_column(Float)
    price_at_alert: Mapped[float | None] = mapped_column(Float)
    telegram_msg_id: Mapped[int | None] = mapped_column(BigInteger)
    sent_at: Mapped[datetime] = mapped_column(server_default=func.now())
