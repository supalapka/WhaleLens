from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from models import Base


class SkippedWallet(Base):
    __tablename__ = "skipped_wallets"

    id: Mapped[int] = mapped_column(primary_key=True)
    wallet_address: Mapped[str] = mapped_column(String(42), unique=True, nullable=False)
    skips_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
