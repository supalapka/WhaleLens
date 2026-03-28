import logging

from fastapi import APIRouter, HTTPException

from services.pump_analysis.analyzer import run_pump_analysis
from services.pump_analysis.exceptions import NoBscTransactionsError
from services.pump_analysis.schemas import PumpAnalysisResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pump-analysis", tags=["pump-analysis"])


@router.get("/", response_model=PumpAnalysisResponse)
async def analyze_pumps():
    try:
        return await run_pump_analysis()
    except NoBscTransactionsError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("Pump analysis failed: %s", e)
        raise HTTPException(status_code=502, detail="External API error")
