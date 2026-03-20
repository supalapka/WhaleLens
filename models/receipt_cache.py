from sqlalchemy import JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from models import Base


class ReceiptCache(Base):
    __tablename__ = "receipt_cache"
    __table_args__ = (
        UniqueConstraint("chain", "tx_hash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chain: Mapped[str] = mapped_column(String(10), nullable=False)
    tx_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    logs_json: Mapped[list] = mapped_column(JSON, nullable=False)
