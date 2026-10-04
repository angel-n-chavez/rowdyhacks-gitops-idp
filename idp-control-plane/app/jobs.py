"""Lightweight background execution (spec sections 12 and 33).

A small thread pool inside the API process. No Celery/Redis/queue service.
With one worker (the default) deployments run strictly one at a time; anything
submitted while a deployment is running just waits, and the store keeps it in
`pending` until a worker picks it up. That is what `pending` means in the
state machine.
"""
import logging
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor

logger = logging.getLogger(__name__)


class JobRunner:
    def __init__(self, workers: int = 1) -> None:
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="idp-job")

    def submit(self, fn: Callable[..., None], *args) -> Future:
        future = self._pool.submit(fn, *args)
        future.add_done_callback(self._log_unhandled)
        return future

    @staticmethod
    def _log_unhandled(future: Future) -> None:
        # The pipeline catches its own errors; this is the last-resort net.
        exc = future.exception()
        if exc is not None:
            logger.error("background job crashed", exc_info=exc)

    def shutdown(self, wait: bool = False) -> None:
        # Drop queued jobs; a job already running finishes on its own thread.
        # `wait=True` additionally blocks until that running job is done.
        self._pool.shutdown(wait=wait, cancel_futures=True)
