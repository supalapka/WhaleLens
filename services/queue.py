import asyncio
import logging

from services.processor import process_transaction

logger = logging.getLogger(__name__)

tx_queue: asyncio.Queue = asyncio.Queue(maxsize=500)


async def _worker(worker_id: int) -> None:
    logger.info("Worker %d started", worker_id)
    while True:
        event = await tx_queue.get()
        try:
            await process_transaction(event)
        except Exception:
            logger.exception("Worker %d failed processing tx: %s", worker_id, event.tx_hash)
        finally:
            tx_queue.task_done()


async def start_workers(n_workers: int) -> list[asyncio.Task]:
    tasks = [asyncio.create_task(_worker(i)) for i in range(n_workers)]
    logger.info("Started %d queue workers", n_workers)
    return tasks
