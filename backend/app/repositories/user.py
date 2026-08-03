from uuid import UUID

from geoalchemy2.elements import WKBElement
from sqlalchemy import func, select

from app.models import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_nickname(self, nickname: str) -> User | None:
        result = await self._session.execute(
            select(User).where(User.nickname == nickname)
        )
        return result.scalar_one_or_none()

    async def get_many(self, user_ids: list[UUID]) -> dict[UUID, User]:
        result = await self._session.execute(
            select(User).where(User.id.in_(user_ids))
        )
        return {user.id: user for user in result.scalars()}

    async def find_nearby(
        self, origin: WKBElement, radius_m: int, exclude_id: UUID
    ) -> list[tuple[User, float]]:
        """Return (user, distance_m) for online users within radius_m of origin."""
        stmt = (
            select(User, func.ST_Distance(User.location, origin))
            .where(
                User.id != exclude_id,
                User.is_online.is_(True),
                func.ST_DWithin(User.location, origin, radius_m),
            )
            .order_by(User.location.op("<->")(origin))
        )
        result = await self._session.execute(stmt)
        return list(result.all())
