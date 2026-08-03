import uuid

import pytest
from geoalchemy2.elements import WKTElement
from geoalchemy2.shape import to_shape

from app.core.exceptions import NicknameAlreadyTakenError, UserNotFoundError
from app.models import User
from app.schemas.user import LocationUpdate, UserCreate
from app.services.user import UserService


class FakeUserRepository:
    def __init__(self) -> None:
        self.by_id: dict[uuid.UUID, User] = {}
        self.by_nickname: dict[str, User] = {}

    async def get_by_nickname(self, nickname: str) -> User | None:
        return self.by_nickname.get(nickname)

    async def create(self, user: User) -> User:
        if user.id is None:
            user.id = uuid.uuid4()
        self.by_id[user.id] = user
        self.by_nickname[user.nickname] = user
        return user

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return self.by_id.get(user_id)

    async def find_nearby(self, origin, radius_m, exclude_id) -> list[tuple[User, float]]:
        return []


def make_user(nickname: str = "Radman") -> User:
    return User(
        id=uuid.uuid4(),
        nickname=nickname,
        location=WKTElement("POINT(0 0)", srid=4326),
        is_online=True,
    )


async def test_create_user_strips_nickname_and_builds_point():
    service = UserService(repository=FakeUserRepository())

    user = await service.create_user(
        UserCreate(nickname="  Radman  ", latitude=37.7749, longitude=-122.4194)
    )

    assert user.nickname == "Radman"
    assert isinstance(user.location, WKTElement)
    assert user.is_online is not True
    assert user.last_seen is None


async def test_create_user_duplicate_nickname_raises():
    repo = FakeUserRepository()
    service = UserService(repository=repo)
    await service.create_user(
        UserCreate(nickname="Radman", latitude=37.0, longitude=-122.0)
    )

    with pytest.raises(NicknameAlreadyTakenError):
        await service.create_user(
            UserCreate(nickname="Radman", latitude=40.0, longitude=-73.0)
        )


async def test_update_location_updates_point_and_last_seen():
    repo = FakeUserRepository()
    service = UserService(repository=repo)
    user = make_user()
    await repo.create(user)

    updated = await service.update_location(
        user.id, LocationUpdate(latitude=12.5, longitude=-99.5)
    )

    point = to_shape(updated.location)
    assert (point.x, point.y) == (-99.5, 12.5)
    assert updated.last_seen is not None


async def test_update_location_unknown_user_raises():
    service = UserService(repository=FakeUserRepository())

    with pytest.raises(UserNotFoundError):
        await service.update_location(
            uuid.uuid4(), LocationUpdate(latitude=0.0, longitude=0.0)
        )


async def test_find_nearby_delegates_with_users_location():
    repo = FakeUserRepository()
    service = UserService(repository=repo)
    user = make_user()
    await repo.create(user)

    result = await service.find_nearby(user.id, 500)

    assert result == []


async def test_find_nearby_unknown_user_raises():
    service = UserService(repository=FakeUserRepository())

    with pytest.raises(UserNotFoundError):
        await service.find_nearby(uuid.uuid4(), 500)
