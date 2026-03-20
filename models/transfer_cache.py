from datetime import datetime

from sqlalchemy import DateTime, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from models import Base


class TransferCache(Base):
    __tablename__ = "transfer_cache"
    __table_args__ = (
        UniqueConstraint("pool_address", "token_address", "chain"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    pool_address: Mapped[str] = mapped_column(String(42), nullable=False)
    token_address: Mapped[str] = mapped_column(String(42), nullable=False)
    chain: Mapped[str] = mapped_column(String(10), nullable=False)
    from_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    to_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    transfers_json: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
