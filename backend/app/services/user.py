from datetime import UTC, datetime

from geoalchemy2.elements import WKTElement

from app.core.exceptions import NicknameAlreadyTakenError
from app.models import User
from app.repositories.user import UserRepository
from app.schemas.user import UserCreate


class UserService:
    def __init__(self, repository: UserRepository) -> None:
        self._repository = repository

    async def create_user(self, data: UserCreate) -> User:
        nickname = data.nickname.strip()

        existing = await self._repository.get_by_nickname(nickname)
        if existing is not None:
            raise NicknameAlreadyTakenError()

        user = User(
            nickname=nickname,
            location=WKTElement(f"POINT({data.longitude} {data.latitude})", srid=4326),
            is_online=True,
            last_seen=datetime.now(UTC),
        )

        return await self._repository.create(user)
