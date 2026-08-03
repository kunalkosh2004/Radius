import uuid

import pytest
from geoalchemy2.elements import WKTElement
from geoalchemy2.shape import to_shape

from app.core.exceptions import UserNotFoundError
from app.models import User
from app.schemas.user import LocationUpdate
from app.services.nearby import NearbyService


class FakeUserRepository:
    def __init__(self) -> None:
        self.by_id: dict[uuid.UUID, User] = {}
        self.nearby_calls: list[list[tuple[User, float]]] = []

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return self.by_id.get(user_id)

    async def find_nearby(self, origin, radius_m, exclude_id):
        return self.nearby_calls.pop(0)


def make_user(nickname: str) -> User:
    return User(
        id=uuid.uuid4(),
        nickname=nickname,
        location=WKTElement("POINT(0 0)", srid=4326),
        is_online=True,
    )


async def test_update_location_reports_entered_and_left_peers():
    repo = FakeUserRepository()
    service = NearbyService(repository=repo)
    mover = make_user("Mover")
    left = make_user("Left")      # was nearby, moved out of range
    stayed = make_user("Stayed")  # nearby before and after
    entered = make_user("Entered")  # newly nearby
    repo.by_id[mover.id] = mover

    # update_location queries new location first, then the old one.
    repo.nearby_calls = [
        [(stayed, 40.0), (entered, 120.5)],  # new nearby
        [(left, 30.0), (stayed, 10.0)],      # old nearby
    ]

    change = await service.update_location(
        mover.id, LocationUpdate(latitude=12.5, longitude=-99.5), radius_m=500
    )

    point = to_shape(change.mover.location)
    assert (point.x, point.y) == (-99.5, 12.5)
    assert change.mover.last_seen is not None
    assert change.affected == {
        left.id: None,
        stayed.id: 40.0,
        entered.id: 120.5,
    }


async def test_update_location_unknown_user_raises():
    service = NearbyService(repository=FakeUserRepository())

    with pytest.raises(UserNotFoundError):
        await service.update_location(
            uuid.uuid4(), LocationUpdate(latitude=0.0, longitude=0.0), radius_m=500
        )


async def test_nearby_delegates_with_users_location():
    repo = FakeUserRepository()
    service = NearbyService(repository=repo)
    user = make_user("Radman")
    repo.by_id[user.id] = user
    repo.nearby_calls = [[(user, 0.0)]]

    result = await service.nearby(user.id, 500)

    assert result == [(user, 0.0)]


async def test_nearby_unknown_user_raises():
    service = NearbyService(repository=FakeUserRepository())

    with pytest.raises(UserNotFoundError):
        await service.nearby(uuid.uuid4(), 500)
