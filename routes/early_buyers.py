import logging

from fastapi import APIRouter, HTTPException

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
        return await detect_early_buyers(request)
    except NoPairsFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (InsufficientPriceDataError, UnsupportedChainError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Early buyer detection failed: %s", e)
        raise HTTPException(status_code=502, detail="External API error")


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
