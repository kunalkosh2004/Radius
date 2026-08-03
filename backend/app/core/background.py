import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import User

logger = logging.getLogger(__name__)
settings = get_settings()


async def mark_stale_offline(session: AsyncSession, cutoff: datetime) -> int:
    """Flip is_online for users whose last_seen is older than cutoff.

    Backs up the clean-disconnect path for clients that vanish without a
    close frame (crashes, airplane mode, NAT timeouts).
    """
    stmt = (
        update(User)
        .where(User.is_online.is_(True), User.last_seen < cutoff)
        .values(is_online=False)
    )
    result = await session.execute(stmt)
    return result.rowcount or 0


async def sweep_once() -> int:
    """Run one reconciliation pass with its own committed short-lived session."""
    cutoff = datetime.now(UTC) - timedelta(
        seconds=settings.PRESENCE_HEARTBEAT_TIMEOUT_S
    )
    async with SessionLocal() as session:
        count = await mark_stale_offline(session, cutoff)
        await session.commit()
    if count:
        logger.info("presence sweep marked %d user(s) offline", count)
    return count


async def presence_sweeper() -> None:
    """Periodically reconcile presence from heartbeats (runs forever)."""
    while True:
        await asyncio.sleep(settings.PRESENCE_SWEEP_INTERVAL_S)
        try:
            await sweep_once()
        except Exception:
            logger.exception("presence sweep failed")
