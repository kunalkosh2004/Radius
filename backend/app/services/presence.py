from datetime import UTC, datetime
from uuid import UUID

from app.core.exceptions import UserNotFoundError
from app.models import User
from app.repositories.user import UserRepository


class PresenceService:
    """Manages the online/offline lifecycle and nearby presence fan-out.

    Operates on the session it is handed; the caller owns the transaction.
    """

    def __init__(self, repository: UserRepository) -> None:
        self._repository = repository

    async def get_user(self, user_id: UUID) -> User | None:
        return await self._repository.get_by_id(user_id)

    async def mark_online(self, user_id: UUID) -> User:
        user = await self._repository.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError()
        user.is_online = True
        user.last_seen = datetime.now(UTC)
        return user

    async def mark_offline(self, user_id: UUID) -> User:
        user = await self._repository.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError()
        user.is_online = False
        return user

    async def touch(self, user_id: UUID) -> User:
        """Refresh last_seen; the heartbeat equivalent of a DB write."""
        user = await self._repository.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError()
        user.last_seen = datetime.now(UTC)
        return user

    async def nearby_online(
        self, user_id: UUID, radius_m: int
    ) -> list[tuple[User, float]]:
        user = await self._repository.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError()
        return await self._repository.find_nearby(user.location, radius_m, user.id)
