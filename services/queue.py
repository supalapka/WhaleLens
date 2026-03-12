import asyncio
import logging

from services.processor import process_transaction

logger = logging.getLogger(__name__)

tx_queue: asyncio.Queue = asyncio.Queue(maxsize=500)
worker_tasks: list[asyncio.Task] = []


async def _worker(worker_id: int) -> None:
    while True:
        event = await tx_queue.get()
        try:
            await process_transaction(event)
        except Exception:
            logger.exception("Worker %d failed processing tx: %s", worker_id, event.tx_hash)
        finally:
            tx_queue.task_done()


async def start_workers(n_workers: int) -> list[asyncio.Task]:
    worker_tasks.clear()
    for i in range(n_workers):
        task = asyncio.create_task(_worker(i))
        worker_tasks.append(task)
    return worker_tasks
