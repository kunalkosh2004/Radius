from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select, text, update

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

    async def get_many(self, message_ids: list[UUID]) -> dict[UUID, Message]:
        result = await self._session.execute(
            select(Message).where(Message.id.in_(message_ids))
        )
        return {m.id: m for m in result.scalars()}

    async def mark_read(
        self, message_ids: list[UUID], by_user: UUID
    ) -> list[Message]:
        """Mark messages as read, but only those addressed to `by_user`.

        Messages the user sent themselves, or that don't exist, are skipped.
        """
        result = await self._session.execute(
            update(Message)
            .where(
                Message.id.in_(message_ids),
                Message.recipient_id == by_user,
                Message.read_at.is_(None),
            )
            .values(read_at=datetime.now(UTC))
            .returning(Message)
        )
        return list(result.scalars())

    async def list_latest_message_ids(
        self, user_id: UUID
    ) -> dict[UUID, UUID]:
        """Map peer_id -> id of the peer's most recent message with `user_id`.

        A "conversation" is implicit: it exists once two users have exchanged
        messages. This is a Postgres DISTINCT ON over a UNION ALL of both
        directions (sent + received), keeping the newest message per peer.
        Raw SQL is clearer here than forcing the ORM to emit DISTINCT ON.
        """
        sql = text(
            """
            SELECT DISTINCT ON (peer_id) peer_id, id
            FROM (
                SELECT recipient_id AS peer_id, id, created_at
                FROM messages
                WHERE sender_id = :me
                UNION ALL
                SELECT sender_id AS peer_id, id, created_at
                FROM messages
                WHERE recipient_id = :me
            ) AS convo
            ORDER BY peer_id, created_at DESC, id DESC
            """
        )
        result = await self._session.execute(sql, {"me": user_id})
        return {row.peer_id: row.id for row in result.all()}

    async def unread_counts(self, user_id: UUID) -> dict[UUID, int]:
        """Map sender_id -> number of unread messages sent to `user_id`."""
        stmt = (
            select(Message.sender_id, func.count())
            .where(
                Message.recipient_id == user_id,
                Message.read_at.is_(None),
            )
            .group_by(Message.sender_id)
        )
        result = await self._session.execute(stmt)
        return {sender_id: count for sender_id, count in result.all()}
