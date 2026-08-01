from sqlalchemy import select

from app.models import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_nickname(self, nickname: str) -> User | None:
        result = await self._session.execute(
            select(User).where(User.nickname == nickname)
        )
        return result.scalar_one_or_none()
