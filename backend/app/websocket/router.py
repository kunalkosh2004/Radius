import anyio
import asyncio
import logging
from uuid import UUID

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.core.config import get_settings
from app.core.exceptions import SelfMessageNotAllowedError, UserNotFoundError
from app.core.pubsub import publish
from app.core.redis import get_redis
from app.core.ws_token import verify_ws_token
from app.db.session import SessionLocal
from app.models import Message, User
from app.repositories.message import MessageRepository
from app.repositories.user import UserRepository
from app.schemas.user import LocationUpdate
from app.services.connection_tracker import ConnectionTracker
from app.services.message import MessageService
from app.services.nearby import NearbyService
from app.services.presence import PresenceService
from app.websocket.manager import ConnectionManager

logger = logging.getLogger(__name__)

router = APIRouter()
manager = ConnectionManager()
tracker = ConnectionTracker(get_redis())
settings = get_settings()


async def _fanout(target_ids: list[UUID], payload: dict) -> None:
    """Deliver to every socket of the target users on all instances."""
    await publish(get_redis(), manager, target_ids, payload)


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
        "read_at": (
            message.read_at.isoformat() if message.read_at is not None else None
        ),
        "created_at": message.created_at.isoformat(),
    }


async def _handle_message_read(
    websocket: WebSocket, reader_id: UUID, raw: dict
) -> None:
    """Handle message:read: mark received messages read and notify senders."""
    ids_raw = raw.get("ids")
    if not isinstance(ids_raw, list) or not ids_raw:
        await websocket.send_json(
            {"type": "message:error", "error": "ids is required"}
        )
        return

    try:
        message_ids = [UUID(str(item)) for item in ids_raw]
    except (ValueError, TypeError):
        await websocket.send_json(
            {"type": "message:error", "error": "invalid message id"}
        )
        return

    async with SessionLocal() as session:
        service = MessageService(
            MessageRepository(session), UserRepository(session)
        )
        messages = await service.mark_read(reader_id, message_ids)
        await session.commit()
        # Capture everything while the session is open (commit expires rows).
        read_at = messages[0].read_at if messages else None
        marked_by_sender: dict[str, list[str]] = {}
        for message in messages:
            marked_by_sender.setdefault(str(message.sender_id), []).append(
                str(message.id)
            )

    await websocket.send_json(
        {
            "type": "message:read",
            "ids": [str(m.id) for m in messages],
            "read_at": read_at.isoformat() if read_at is not None else None,
        }
    )
    for sender_id, ids in marked_by_sender.items():
        await _fanout(
            [UUID(sender_id)],
            {
                "type": "message:read",
                "ids": ids,
                "read_at": read_at.isoformat() if read_at is not None else None,
            },
        )


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
    await _fanout(
        [recipient_id], {"type": "message:new", "message": payload}
    )


def _nearby_update_payload(radius_m: int, nearby) -> dict:
    """A user's full nearby list, pushed after a move and periodically."""
    return {
        "type": "nearby:update",
        "radius_m": radius_m,
        "users": [
            {
                "id": str(other.id),
                "nickname": other.nickname,
                "distance_m": round(distance, 1),
            }
            for other, distance in nearby
        ],
    }


def _neighbor_updated_payload(mover: User, distance_m: float | None) -> dict:
    """Tell a peer about a move; distance_m is null when the mover left range."""
    return {
        "type": "nearby:neighbor-updated",
        "user": {"id": str(mover.id), "nickname": mover.nickname},
        "distance_m": distance_m,
    }


async def apply_location_update(
    user_id: UUID, data: LocationUpdate
) -> tuple[UUID, dict, dict[UUID, dict]]:
    """Persist a location change and build the nearby fan-out payloads.

    Returns (mover_id, mover's nearby:update payload, per-peer neighbor
    payloads). Payloads are built while the session is open because commit
    expires the ORM instances.
    """
    radius = settings.PRESENCE_NEARBY_RADIUS_M
    async with SessionLocal() as session:
        service = NearbyService(UserRepository(session))
        change = await service.update_location(user_id, data, radius)
        mover_payload = _nearby_update_payload(radius, change.nearby)
        neighbor_payloads = {
            peer_id: _neighbor_updated_payload(change.mover, distance)
            for peer_id, distance in change.affected.items()
        }
        await session.commit()
    return change.mover.id, mover_payload, neighbor_payloads


async def publish_nearby_changes(
    mover_id: UUID, mover_payload: dict, neighbor_payloads: dict[UUID, dict]
) -> None:
    """Fan a location change out: full list to the mover, deltas to peers."""
    await _fanout([mover_id], mover_payload)
    for peer_id, payload in neighbor_payloads.items():
        await _fanout([peer_id], payload)


async def _handle_location_update(
    websocket: WebSocket, me: User, raw: dict
) -> None:
    """Handle location:update: move the user and push live nearby changes."""
    try:
        data = LocationUpdate.model_validate(raw)
    except ValidationError:
        await websocket.send_json(
            {"type": "nearby:error", "error": "invalid location"}
        )
        return

    try:
        mover_id, mover_payload, neighbor_payloads = await apply_location_update(
            me.id, data
        )
    except UserNotFoundError:
        await websocket.send_json({"type": "nearby:error", "error": "unknown user"})
        return
    await publish_nearby_changes(mover_id, mover_payload, neighbor_payloads)


async def broadcast_nearby() -> None:
    """Push a fresh nearby:update to every socket connected to this instance."""
    radius = settings.PRESENCE_NEARBY_RADIUS_M
    for user_id in list(manager.online_user_ids):
        try:
            async with SessionLocal() as session:
                service = NearbyService(UserRepository(session))
                nearby = await service.nearby(user_id, radius)
                payload = _nearby_update_payload(radius, nearby)
            await manager.send_to_user(user_id, payload)
        except UserNotFoundError:
            continue
        except Exception:
            logger.exception("nearby broadcast failed for %s", user_id)


async def nearby_broadcaster() -> None:
    """Periodically refresh nearby lists so missed events self-heal."""
    while True:
        await asyncio.sleep(settings.NEARBY_BROADCAST_INTERVAL_S)
        try:
            await broadcast_nearby()
        except Exception:
            logger.exception("nearby broadcast pass failed")


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket, token: str = Query(...)
) -> None:
    """Presence connection: heartbeat + online/offline notification to nearby users.

    The `token` query parameter is a short-lived signed token issued by
    ``POST /api/v1/auth/ws-token``; it identifies the connecting user, so a
    leaked websocket URL stops working once the token expires.

    Note: unlike HTTP dependencies, we never hold a DB session for the
    lifetime of the socket. Each operation opens a short-lived session and
    commits explicitly, so one idle connection doesn't pin a pooled
    connection to the database.

    Presence is global, not per-process: `tracker` counts sockets across all
    instances in Redis, and fan-out goes through Redis pub/sub so sockets on
    other instances receive the same events.
    """
    user_id = verify_ws_token(token)
    if user_id is None:
        await websocket.close(code=4401, reason="invalid token")
        return

    async with SessionLocal() as session:
        service = PresenceService(UserRepository(session))
        me = await service.get_user(user_id)
        if me is None:
            await websocket.close(code=4404, reason="unknown user")
            return

    radius = settings.PRESENCE_NEARBY_RADIUS_M
    await websocket.accept()
    try:
        manager.add(user_id, websocket)
        is_first = await tracker.connect(user_id)

        if is_first:
            async with SessionLocal() as session:
                service = PresenceService(UserRepository(session))
                await service.mark_online(user_id)
                await session.commit()

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
        if is_first:
            for other, distance in nearby:
                await _fanout(
                    [other.id],
                    _presence_update(me, "online", round(distance, 1)),
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
            elif message.get("type") == "message:read":
                await _handle_message_read(websocket, me.id, message)
            elif message.get("type") == "location:update":
                await _handle_location_update(websocket, me, message)
    finally:
        manager.remove(user_id, websocket)
        try:
            is_last = await tracker.disconnect(user_id)
        except Exception:
            logger.exception("connection tracker disconnect failed")
            is_last = False
        if is_last:
            async with SessionLocal() as session:
                service = PresenceService(UserRepository(session))
                await service.mark_offline(user_id)
                await session.commit()
                nearby = await service.nearby_online(user_id, radius)
            for other, distance in nearby:
                await _fanout(
                    [other.id],
                    _presence_update(me, "offline", round(distance, 1)),
                )
