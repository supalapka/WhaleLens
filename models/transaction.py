from datetime import datetime

from sqlalchemy import String, Float, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from models import Base


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    wallet_id: Mapped[int] = mapped_column(ForeignKey("wallets.id"))
    token_address: Mapped[str] = mapped_column(String(42), nullable=False)
    token_symbol: Mapped[str | None] = mapped_column(String(20))
    chain: Mapped[str | None] = mapped_column(String(10))
    usd_amount: Mapped[float | None] = mapped_column(Float)
    tx_hash: Mapped[str] = mapped_column(String(66), unique=True)
    score: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
