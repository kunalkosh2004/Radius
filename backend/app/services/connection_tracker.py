from uuid import UUID

from redis.asyncio import Redis


class ConnectionTracker:
    """Global per-user socket count, so presence is correct across instances.

    Presence is decided by "does at least one socket exist anywhere", not by
    what a single process can see. Each connect INCRs the user's counter; the
    connection that moves it 0 -> 1 is the first and the one that moves it
    1 -> 0 is the last.
    """

    _KEY = "radius:conns:{}"

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def connect(self, user_id: UUID) -> bool:
        """Register a new socket. Returns True for the user's first socket."""
        count = await self._redis.incr(self._KEY.format(user_id))
        return count == 1

    async def disconnect(self, user_id: UUID) -> bool:
        """Unregister a socket. Returns True for the user's last socket."""
        count = await self._redis.decr(self._KEY.format(user_id))
        if count < 0:
            # Guard against races (e.g. expiry); never leave a negative count.
            await self._redis.set(self._KEY.format(user_id), 0)
            count = 0
        return count == 0
