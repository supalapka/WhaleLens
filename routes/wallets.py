from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from database import async_session
from models.wallet import Wallet
from services.moralis import create_stream, subscribe_addresses
from services.schemas import WalletCreate

router = APIRouter()


@router.post("/wallets")
async def add_wallet(body: WalletCreate):
    wallet = Wallet(
        address=body.address,
        label=body.label,
        category=body.category,
    )
    try:
        async with async_session() as session:
            session.add(wallet)
            await session.commit()
            await session.refresh(wallet)
    except IntegrityError:
        return JSONResponse(
            status_code=409,
            content={"detail": f"wallet {body.address} already exists"},
        )
    return {
        "id": wallet.id,
        "address": wallet.address,
        "label": wallet.label,
        "category": wallet.category,
        "credibility_score": wallet.credibility_score,
        "is_active": wallet.is_active,
        "added_at": wallet.added_at.isoformat(),
    }


@router.post("/wallets/subscribe")
async def wallets_subscribe():
    async with async_session() as session:
        result = await session.execute(
            select(Wallet.address).where(Wallet.is_active.is_(True))
        )
        addresses = list(result.scalars().all())

    if not addresses:
        return {"status": "ok", "subscribed": 0, "stream_id": None}

    stream_id = await create_stream()
    await subscribe_addresses(stream_id, addresses)
    return {"status": "ok", "subscribed": len(addresses), "stream_id": stream_id}
