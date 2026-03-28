from sqlalchemy import Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from models import Base


class PumpCredit(Base):
    __tablename__ = "pump_credits"
    __table_args__ = (
        UniqueConstraint("wallet_id", "token_address"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    wallet_id: Mapped[int] = mapped_column(Integer, nullable=False)
    token_address: Mapped[str] = mapped_column(String(42), nullable=False)
