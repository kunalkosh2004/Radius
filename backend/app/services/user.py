from datetime import UTC, datetime
from uuid import UUID

from geoalchemy2.elements import WKTElement

from app.core.exceptions import NicknameAlreadyTakenError, UserNotFoundError
from app.models import User
from app.repositories.user import UserRepository
from app.schemas.user import LocationUpdate, UserCreate


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
        )

        return await self._repository.create(user)

    async def update_location(self, user_id: UUID, data: LocationUpdate) -> User:
        user = await self._repository.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError()

        user.location = WKTElement(
            f"POINT({data.longitude} {data.latitude})", srid=4326
        )
        user.last_seen = datetime.now(UTC)
        return user

    async def find_nearby(self, user_id: UUID, radius_m: int) -> list[tuple[User, float]]:
        user = await self._repository.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError()

        return await self._repository.find_nearby(user.location, radius_m, user.id)
