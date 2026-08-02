from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.dependencies import get_db
from app.models import User
from app.repositories.user import UserRepository
from app.schemas.user import LocationUpdate, UserCreate, UserNearby, UserRead
from app.services.user import UserService

router = APIRouter(prefix="/users", tags=["users"])


async def get_user_service(db: AsyncSession = Depends(get_db)) -> UserService:
    return UserService(repository=UserRepository(db))


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    service: UserService = Depends(get_user_service),
) -> User:
    return await service.create_user(payload)


@router.patch(
    "/{user_id}/location",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def update_location(
    user_id: UUID,
    payload: LocationUpdate,
    service: UserService = Depends(get_user_service),
) -> None:
    await service.update_location(user_id, payload)


@router.get("/{user_id}/nearby", response_model=list[UserNearby])
async def get_nearby_users(
    user_id: UUID,
    radius_m: int = Query(default=500, ge=10, le=10000),
    service: UserService = Depends(get_user_service),
) -> list[UserNearby]:
    nearby = await service.find_nearby(user_id, radius_m)
    return [
        UserNearby(**UserRead.model_validate(user).model_dump(), distance_m=distance)
        for user, distance in nearby
    ]
