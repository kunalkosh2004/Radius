from app.db.base import Base
from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from geoalchemy2 import Geography
from geoalchemy2.elements import WKBElement
from geoalchemy2.shape import to_shape
from datetime import UTC, datetime
import uuid


TIMESTAMP = DateTime(timezone=True)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    nickname: Mapped[str] = mapped_column(
        String(30), unique=True, nullable=False
    )
    location: Mapped[WKBElement] = mapped_column(
        Geography("POINT", srid=4326),
        nullable=False,
    )
    is_online: Mapped[bool] = mapped_column(
        Boolean,
        default=False, 
        server_default="false",
        nullable=False
    )
    last_seen: Mapped[datetime | None] = mapped_column(
        TIMESTAMP,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    @property
    def latitude(self) -> float:
        return to_shape(self.location).y

    @property
    def longitude(self) -> float:
        return to_shape(self.location).x
