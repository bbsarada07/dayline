"""Background housekeeping, run once a minute while the server is up."""

import asyncio
import sys

from sqlmodel import Session

from app.db import engine
from app.services import canteen_service, memory_service, print_service

INTERVAL_SECONDS = 60


def run_once() -> None:
    """One pass of every periodic job."""
    with Session(engine) as session:
        print_service.expire_old_jobs(session)
        print_service.remove_stale_uploads(session)
        canteen_service.mark_no_shows(session)
    memory_service.reconnect_if_due()  # back to Qdrant if we had to fall back


async def loop() -> None:
    while True:
        try:
            await asyncio.to_thread(run_once)
        except Exception as exc:  # keep the loop alive; log and try again next minute
            print(f"[maintenance] {exc!r}", file=sys.stderr)
        await asyncio.sleep(INTERVAL_SECONDS)
