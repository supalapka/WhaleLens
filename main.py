from contextlib import asynccontextmanager

from fastapi import FastAPI

from config import settings
from logging_config import setup_logging
from routes.debug import router as debug_router
from routes.early_buyers import router as early_buyers_router
from routes.pump_analysis import router as pump_analysis_router
from routes.wallets import router as wallets_router
from routes.webhook import router as webhook_router
from services.queue import start_workers

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    workers = await start_workers(settings.n_workers)
    yield
    for task in workers:
        task.cancel()


app = FastAPI(title="WhaleLens", lifespan=lifespan)
app.include_router(webhook_router)
app.include_router(wallets_router)
app.include_router(debug_router)
app.include_router(early_buyers_router)
app.include_router(pump_analysis_router)
