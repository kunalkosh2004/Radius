import pytest
from geoalchemy2.elements import WKTElement

from app.core.exceptions import NicknameAlreadyTakenError
from app.schemas.user import UserCreate
from app.services.user import UserService


class FakeUserRepository:
    def __init__(self) -> None:
        self.users: dict[str, object] = {}

    async def get_by_nickname(self, nickname: str):
        return self.users.get(nickname)

    async def create(self, user):
        self.users[user.nickname] = user
        return user


async def test_create_user_strips_nickname_and_builds_point():
    service = UserService(repository=FakeUserRepository())

    user = await service.create_user(
        UserCreate(nickname="  Radman  ", latitude=37.7749, longitude=-122.4194)
    )

    assert user.nickname == "Radman"
    assert isinstance(user.location, WKTElement)
    assert user.is_online is True
    assert user.last_seen is not None


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
