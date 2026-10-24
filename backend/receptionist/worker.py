"""Separate durable-job worker: python -m receptionist.worker."""
import asyncio
import contextlib
from .config import settings
from .main import worker_loop, verify_production_schema
from .core_runtime import shutdown_event, drain_tasks


async def run_worker():
    stop = shutdown_event()
    task = asyncio.create_task(worker_loop(stop))
    stopping = asyncio.create_task(stop.wait())
    try:
        await asyncio.wait({task, stopping}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        stop.set()
        stopping.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await stopping
        await drain_tasks({task})
    if task.done() and not task.cancelled():
        task.result()


if __name__ == "__main__":
    settings.validate()
    if settings.environment.lower() in {"production", "prod"}:
        verify_production_schema()
    asyncio.run(run_worker())

