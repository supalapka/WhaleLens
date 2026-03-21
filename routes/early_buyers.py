import logging

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from database import async_session
from models.wallet import Wallet
from models.wallet_detection import WalletDetection
from services.early_buyers.detector import detect_early_buyers, top_wallets
from services.early_buyers.exceptions import (
    InsufficientPriceDataError,
    NoPairsFoundError,
    UnsupportedChainError,
)
from services.early_buyers.schemas import EarlyBuyerRecord, EarlyBuyerRequest, EarlyBuyerResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/early-buyers", tags=["early-buyers"])


@router.post("/detect", response_model=EarlyBuyerResponse)
async def detect(request: EarlyBuyerRequest):
    try:
        response = await detect_early_buyers(request)
    except NoPairsFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (InsufficientPriceDataError, UnsupportedChainError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Early buyer detection failed: %s", e)
        raise HTTPException(status_code=502, detail="External API error")

    if response.results:
        await _save_wallets(response)

    return response


async def _save_wallets(response: EarlyBuyerResponse) -> None:
    addresses = [r.wallet for r in response.results]
    token = response.token_address
    label = f"Early buyer #{response.token_symbol}"

    async with async_session() as session:
        det_result = await session.execute(
            select(WalletDetection.wallet_address).where(
                WalletDetection.wallet_address.in_(addresses),
                WalletDetection.token_address == token,
            )
        )
        already_detected = set(det_result.scalars().all())
        new_addresses = [a for a in addresses if a not in already_detected]

        if not new_addresses:
            return

        wal_result = await session.execute(
            select(Wallet).where(Wallet.address.in_(new_addresses))
        )
        existing = {w.address: w for w in wal_result.scalars().all()}

        for address in new_addresses:
            wallet = existing.get(address)
            if wallet:
                wallet.credibility_score += 1
            else:
                session.add(Wallet(
                    address=address,
                    label=label,
                    category="early_buyer",
                ))
            session.add(WalletDetection(
                wallet_address=address,
                token_address=token,
            ))

        await session.commit()

    logger.info(
        "Saved %d wallets (%d new, %d updated, %d skipped) for %s",
        len(new_addresses),
        len(new_addresses) - len(existing),
        len(existing),
        len(already_detected),
        response.token_symbol,
    )


@router.post("/top-wallets", response_model=list[EarlyBuyerRecord])
async def get_top_wallets(request: EarlyBuyerRequest):
    try:
        return await top_wallets(request)
    except NoPairsFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (InsufficientPriceDataError, UnsupportedChainError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Top wallets query failed: %s", e)
        raise HTTPException(status_code=502, detail="External API error")
