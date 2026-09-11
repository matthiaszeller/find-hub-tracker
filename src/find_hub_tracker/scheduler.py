import asyncio
from datetime import datetime, UTC, timedelta
import os
import signal
from collections import namedtuple
from dataclasses import dataclass
from typing import Callable, Awaitable

import structlog
from apscheduler import AsyncScheduler
from apscheduler.abc import Trigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger


@dataclass(frozen=True)
class Job:
    id: str
    fun: Callable
    trigger: Trigger

log = structlog.get_logger()


type ShutdownHook = Callable[[], Awaitable[None]]

class Scheduler:

    def __init__(self, shutdown_grace_seconds: float = 10.0):
        self._shutdown_event = asyncio.Event()
        self._jobs: list[Job] = []
        self._shutdown_hooks: list[ShutdownHook] = []
        self.shutdown_grace_seconds = shutdown_grace_seconds

    def run_once(self, fun: Callable, *, id: str, wait_seconds: float = 0.) -> None:
        """Schedule a job to run a single time."""
        run_time = datetime.now(UTC) + timedelta(seconds=wait_seconds)
        self._add_job(fun, trigger=DateTrigger(run_time=run_time), id=id)

    def run_every(self, fun: Callable, *, id: str, start_immediately: bool = False, interval: timedelta) -> None:
        """Schedule a job to run at regular intervals."""
        start_time = datetime.now(UTC)
        if not start_immediately:
            start_time += interval

        self._add_job(fun, trigger=IntervalTrigger(seconds=interval.total_seconds(), start_time=start_time), id=id)

    def on_shutdown(self, hook: ShutdownHook) -> None:
        """Register a shutdown hook to be called when the scheduler is shutting down."""
        self._shutdown_hooks.append(hook)

    def _add_job(self, fun: Callable, trigger: Trigger, id: str) -> None:
        """Add a job to the scheduler."""
        self._jobs.append(Job(id=id, fun=fun, trigger=trigger))

    async def run(self) -> None:
        # register signal handlers for graceful shutdown
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._shutdown_event.set)

        aps = AsyncScheduler()
        await aps.__aenter__()
        try:
            for job in self._jobs:
                await aps.add_schedule(job.fun, job.trigger, id=job.id)

            await aps.start_in_background()
            log.info("scheduler_running")
            await self._shutdown_event.wait()
            log.info("shutdown_requested")
        finally:
            try:
                await asyncio.wait_for(aps.__aexit__(None, None, None), timeout=self.shutdown_grace_seconds)
            except TimeoutError:
                log.error("shutdown_grace_period_exceeded", message="A job didn't stop in time, forcing exit")
                os._exit(1)

            for hook in self._shutdown_hooks:
                hook_name = getattr(hook, '__qualname__', repr(hook))
                try:
                    await asyncio.wait_for(hook(), timeout=self.shutdown_grace_seconds)
                except TimeoutError:
                    log.error("shutdown_hook_timeout", hook=hook_name)
                except Exception:
                    log.exception("shutdown_hook_error", hook=hook_name)

            os._exit(0)
