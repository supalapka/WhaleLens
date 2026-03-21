from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from models import Base


class WalletDetection(Base):
    __tablename__ = "wallet_detections"
    __table_args__ = (
        UniqueConstraint("wallet_address", "token_address"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    wallet_address: Mapped[str] = mapped_column(String(42), nullable=False)
    token_address: Mapped[str] = mapped_column(String(42), nullable=False)
