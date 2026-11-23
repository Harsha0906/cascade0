"""
CascadeZero — Telegram long-poll worker.

    python -m app.telegram_poll

For a laptop or any host without a public HTTPS URL: instead of a webhook, this process asks
Telegram for updates (`getUpdates`, 30 s long poll) and feeds each one to the same shared inbound
flow (`inbound.handle`) the webhook uses, so linking, vendor replies, alerts and approvals behave
identically. Polling and a webhook are exclusive, so `deleteWebhook` runs once at start.

The next offset is kept in a small local file (TELEGRAM_POLL_OFFSET_FILE). If the file is lost
nothing breaks: updates are de-duplicated on `tg:<update_id>` in `webhook_events`. An update whose
processing raises is retried on the next poll (the inbound flow releases its dedupe id), up to
`MAX_ATTEMPTS` times, then skipped with an error log so one poison update cannot stall the bot.
Ctrl-C stops the loop cleanly. Needs TELEGRAM_BOT_TOKEN in backend/.env; the token is never logged.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Dict, Optional

from fastapi.concurrency import run_in_threadpool

from app import inbound
from app.channels.telegram import TelegramChannel
from app.config import settings

logger = logging.getLogger("cascadezero.telegram_poll")

POLL_TIMEOUT_S = 30
MAX_ATTEMPTS = 3
ERROR_BACKOFF_S = 5.0

_attempts: Dict[int, int] = {}


def load_offset(path: Optional[str] = None) -> Optional[int]:
    try:
        with open(path or settings.TELEGRAM_POLL_OFFSET_FILE, encoding="utf-8") as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return None


def save_offset(offset: int, path: Optional[str] = None) -> None:
    target = path or settings.TELEGRAM_POLL_OFFSET_FILE
    tmp = f"{target}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(str(offset))
        os.replace(tmp, target)
    except OSError as exc:
        logger.warning("Could not save the poll offset: %s", type(exc).__name__)


async def poll_once(channel: TelegramChannel, offset: Optional[int], timeout: int = POLL_TIMEOUT_S) -> Optional[int]:
    """One getUpdates round. Returns the offset for the next round (the last handled update_id + 1;
    unchanged when nothing arrived or the first update failed and will be retried)."""
    updates = await run_in_threadpool(channel.get_updates, offset, timeout)
    if updates is None:
        await asyncio.sleep(ERROR_BACKOFF_S)
        return offset
    next_offset = offset
    for update in updates:
        update_id = update.get("update_id")
        if not isinstance(update_id, int):
            continue
        try:
            # parse_inbound answers a button's callback query (a blocking Bot API call).
            messages = await run_in_threadpool(channel.parse_inbound, update)
            for msg in messages:
                await inbound.handle(channel, msg)
        except Exception:
            _attempts[update_id] = _attempts.get(update_id, 0) + 1
            if _attempts[update_id] < MAX_ATTEMPTS:
                logger.exception("Update %s failed (attempt %s); it will be retried", update_id, _attempts[update_id])
                return next_offset   # do not advance past it
            logger.exception("Update %s failed %s times; skipping it", update_id, MAX_ATTEMPTS)
        _attempts.pop(update_id, None)
        next_offset = update_id + 1
    return next_offset


async def run(channel: TelegramChannel, offset_file: Optional[str] = None) -> None:
    await run_in_threadpool(channel.delete_webhook)
    offset = load_offset(offset_file)
    logger.info("Telegram polling started (offset %s)", offset)
    while True:
        new_offset = await poll_once(channel, offset)
        if new_offset is not None and new_offset != offset:
            offset = new_offset
            save_offset(offset, offset_file)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    if not settings.TELEGRAM_BOT_TOKEN:
        print("error: TELEGRAM_BOT_TOKEN is not set in backend/.env", file=sys.stderr)
        return 1
    try:
        asyncio.run(run(TelegramChannel(settings.TELEGRAM_BOT_TOKEN)))
    except KeyboardInterrupt:
        print("Telegram polling stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
