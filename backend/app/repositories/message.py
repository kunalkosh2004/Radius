from uuid import UUID

from sqlalchemy import and_, or_, select

from app.models import Message
from app.repositories.base import BaseRepository


class MessageRepository(BaseRepository[Message]):
    model = Message

    async def get_conversation(
        self,
        me: UUID,
        peer: UUID,
        before: UUID | None,
        limit: int,
    ) -> list[Message]:
        """Newest-first messages exchanged between me and peer (both directions).

        `before` is a cursor message id; messages at or before it are excluded
        by comparing against that message's created_at. Passing an unknown
        cursor yields an empty page rather than an error.
        """
        stmt = select(Message).where(
            or_(
                and_(
                    Message.sender_id == me,
                    Message.recipient_id == peer,
                ),
                and_(
                    Message.sender_id == peer,
                    Message.recipient_id == me,
                ),
            )
        )
        if before is not None:
            cursor_created_at = select(Message.created_at).where(Message.id == before)
            stmt = stmt.where(
                Message.created_at < cursor_created_at.scalar_subquery()
            )
        stmt = (
            stmt.order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars())
