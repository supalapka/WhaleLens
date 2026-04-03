from datetime import datetime

from sqlalchemy import String, Float, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column

from models import Base


class Wallet(Base):
    __tablename__ = "wallets"

    id: Mapped[int] = mapped_column(primary_key=True)
    address: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    label: Mapped[str | None] = mapped_column(String(100))
    category: Mapped[str | None] = mapped_column(String(20))
    credibility_score: Mapped[float] = mapped_column(Float, server_default="0.5")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    always_alert: Mapped[bool] = mapped_column(Boolean, server_default="false")
    added_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
