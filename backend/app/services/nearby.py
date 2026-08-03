from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from geoalchemy2.elements import WKTElement

from app.core.exceptions import UserNotFoundError
from app.models import User
from app.repositories.user import UserRepository
from app.schemas.user import LocationUpdate


@dataclass
class NearbyChange:
    """What a location update changes: the mover's view plus affected peers.

    `affected` maps every peer that was in range before *or* after the move to
    their new distance from the mover; `None` means they fell out of range.
    """

    mover: User
    nearby: list[tuple[User, float]]
    affected: dict[UUID, float | None] = field(default_factory=dict)


class NearbyService:
    """Compute who is nearby before and after a location change.

    Operates on the session it is handed; the caller owns the transaction.
    """

    def __init__(self, repository: UserRepository) -> None:
        self._repository = repository

    async def nearby(self, user_id: UUID, radius_m: int) -> list[tuple[User, float]]:
        user = await self._repository.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError()
        return await self._repository.find_nearby(user.location, radius_m, user.id)

    async def update_location(
        self, user_id: UUID, data: LocationUpdate, radius_m: int
    ) -> NearbyChange:
        user = await self._repository.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError()

        old_location = user.location
        new_location = WKTElement(
            f"POINT({data.longitude} {data.latitude})", srid=4326
        )
        user.location = new_location
        user.last_seen = datetime.now(UTC)

        new_nearby = await self._repository.find_nearby(
            new_location, radius_m, user.id
        )
        old_nearby = await self._repository.find_nearby(
            old_location, radius_m, user.id
        )

        new_by_id = {other.id: round(distance, 1) for other, distance in new_nearby}
        old_ids = {other.id for other, _ in old_nearby}
        affected = {
            peer_id: new_by_id.get(peer_id) for peer_id in old_ids | set(new_by_id)
        }
        return NearbyChange(mover=user, nearby=new_nearby, affected=affected)
