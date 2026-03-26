from sqlalchemy.dialects.postgresql import insert

from database import async_session
from models.skipped_wallet import SkippedWallet


async def increment_skipped_wallet(wallet_address: str) -> None:
    async with async_session() as session:
        stmt = (
            insert(SkippedWallet)
            .values(wallet_address=wallet_address.lower(), skips_count=1)
            .on_conflict_do_update(
                index_elements=["wallet_address"],
                set_={"skips_count": SkippedWallet.skips_count + 1},
            )
        )
        await session.execute(stmt)
        await session.commit()
