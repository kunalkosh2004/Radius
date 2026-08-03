import anyio
from uuid import UUID

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.config import get_settings
from app.core.exceptions import SelfMessageNotAllowedError, UserNotFoundError
from app.db.session import SessionLocal
from app.models import Message, User
from app.repositories.message import MessageRepository
from app.repositories.user import UserRepository
from app.services.message import MessageService
from app.services.presence import PresenceService
from app.websocket.manager import ConnectionManager

router = APIRouter()
manager = ConnectionManager()
settings = get_settings()


def _presence_update(
    user: User, status: str, distance_m: float | None
) -> dict:
    return {
        "type": "presence:update",
        "status": status,
        "user": {"id": str(user.id), "nickname": user.nickname},
        "distance_m": distance_m,
    }


def _message_payload(message: Message) -> dict:
    return {
        "id": str(message.id),
        "from": str(message.sender_id),
        "to": str(message.recipient_id),
        "body": message.body,
        "created_at": message.created_at.isoformat(),
    }


async def _handle_message_send(
    websocket: WebSocket, sender_id: UUID, raw: dict
) -> None:
    """Handle message:send: validate, persist, ack the sender, deliver to peer."""
    try:
        recipient_id = UUID(str(raw.get("to")))
    except (ValueError, TypeError):
        await websocket.send_json(
            {"type": "message:error", "error": "invalid recipient"}
        )
        return

    body = raw.get("body")
    if not isinstance(body, str):
        await websocket.send_json(
            {"type": "message:error", "error": "message body is required"}
        )
        return
    body = body.strip()
    if not body:
        await websocket.send_json(
            {"type": "message:error", "error": "message body is required"}
        )
        return
    if len(body) > settings.MESSAGE_MAX_LENGTH:
        await websocket.send_json(
            {
                "type": "message:error",
                "error": (
                    f"message body exceeds {settings.MESSAGE_MAX_LENGTH} characters"
                ),
            }
        )
        return

    async with SessionLocal() as session:
        service = MessageService(
            MessageRepository(session), UserRepository(session)
        )
        try:
            message = await service.send_message(sender_id, recipient_id, body)
        except (UserNotFoundError, SelfMessageNotAllowedError) as exc:
            await websocket.send_json(
                {"type": "message:error", "error": exc.detail}
            )
            return
        await session.commit()
        # Access attributes while the session is still open (commit expires
        # the instance; doing this later would hit a detached instance).
        payload = _message_payload(message)

    await websocket.send_json({"type": "message:ack", "message": payload})
    await manager.send_to_user(
        recipient_id, {"type": "message:new", "message": payload}
    )


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket, user_id: UUID = Query(...)
) -> None:
    """Presence connection: heartbeat + online/offline notification to nearby users.

    Note: unlike HTTP dependencies, we never hold a DB session for the
    lifetime of the socket. Each operation opens a short-lived session and
    commits explicitly, so one idle connection doesn't pin a pooled
    connection to the database.
    """
    async with SessionLocal() as session:
        service = PresenceService(UserRepository(session))
        me = await service.get_user(user_id)
        if me is None:
            await websocket.close(code=4404, reason="unknown user")
            return
        await service.mark_online(user_id)
        await session.commit()

    await websocket.accept()
    manager.add(user_id, websocket)

    radius = settings.PRESENCE_NEARBY_RADIUS_M
    try:
        async with SessionLocal() as session:
            service = PresenceService(UserRepository(session))
            nearby = await service.nearby_online(user_id, radius)

        await websocket.send_json(
            {
                "type": "presence:initial",
                "users": [
                    {
                        "id": str(other.id),
                        "nickname": other.nickname,
                        "distance_m": round(distance, 1),
                    }
                    for other, distance in nearby
                ],
            }
        )
        for other, distance in nearby:
            await manager.send_to_user(
                other.id, _presence_update(me, "online", round(distance, 1))
            )

        while True:
            try:
                with anyio.fail_after(
                    settings.PRESENCE_HEARTBEAT_TIMEOUT_S
                ):
                    message = await websocket.receive_json()
            except TimeoutError:
                await websocket.close(code=4400, reason="heartbeat timeout")
                break
            except WebSocketDisconnect:
                break

            if message.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
                async with SessionLocal() as session:
                    service = PresenceService(UserRepository(session))
                    await service.touch(user_id)
                    await session.commit()
            elif message.get("type") == "message:send":
                await _handle_message_send(websocket, me.id, message)
    finally:
        is_last = manager.remove(user_id, websocket)
        if is_last:
            me = None
            nearby = []
            async with SessionLocal() as session:
                service = PresenceService(UserRepository(session))
                me = await service.get_user(user_id)
                if me is not None:
                    await service.mark_offline(user_id)
                    await session.commit()
                    nearby = await service.nearby_online(user_id, radius)
            if me is not None:
                for other, distance in nearby:
                    await manager.send_to_user(
                        other.id, _presence_update(me, "offline", round(distance, 1))
                    )
